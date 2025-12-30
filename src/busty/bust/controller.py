"""BustController for managing bust playback sessions."""

import asyncio
import logging
import time
from collections import defaultdict

from busty import song_utils
from busty.ai.protocols import AIService
from busty.bust.models import BustPhase, BustStats, PlaybackState, SubmitterStat
from busty.bust.protocols import AudioPlayer, BustOutput
from busty.config.settings import BustySettings
from busty.track import Track

logger = logging.getLogger(__name__)


class BustController:
    """Manages a bust session for a guild."""

    def __init__(
        self,
        settings: BustySettings,
        tracks: list[Track],
        output: BustOutput,
        ai_service: AIService,
    ):
        self.settings = settings
        self.tracks = tracks
        self.output = output
        self.ai_service = ai_service
        self.phase = BustPhase.LISTED
        self._playback: PlaybackState | None = None

    @property
    def is_playing(self) -> bool:
        """Check if currently in PLAYING phase."""
        return self.phase == BustPhase.PLAYING

    @property
    def current_track(self) -> Track | None:
        """Get currently playing track, if any."""
        if self._playback is None:
            return None
        return self.tracks[self._playback.current_index]

    @property
    def total_duration(self) -> float:
        """Calculate total duration of all tracks in seconds."""
        return sum(track.duration or 0.0 for track in self.tracks)

    def stop(self) -> None:
        """Request playback to stop."""
        if self._playback is None:
            return

        self._playback.stop_requested = True
        if self._playback.current_task:
            self._playback.current_task.cancel()

    def skip_to(self, track_index: int) -> None:
        """Skip to a specific track (0-indexed)."""
        if self._playback is None or self._playback.current_task is None:
            return

        # Set index to one before target (will be incremented after cancel)
        self._playback.current_index = max(0, track_index - 1)
        self._playback.current_task.cancel()

    def skip_next(self) -> None:
        """Skip to the next track in the playlist."""
        if self._playback is None:
            return

        # Skip to the track after current (current_index + 1)
        # skip_to will handle the case where current_task is None
        self.skip_to(self._playback.current_index + 1)

    def replay(self) -> None:
        """Replay the current track from the beginning."""
        if self._playback is None:
            return

        # Skip to the current track (will restart it)
        # skip_to will handle the case where current_task is None
        self.skip_to(self._playback.current_index)

    def seek(self, timestamp: int) -> None:
        """Seek current track to timestamp in seconds."""
        if self._playback is None:
            logger.warning("No track is currently playing. Ignoring seek.")
            return

        self._playback.seek_timestamp = timestamp
        # Skip to current track (will restart with seek timestamp)
        self.skip_to(self._playback.current_index)

    async def play(self, audio_player: AudioPlayer, start_index: int = 0) -> None:
        """Begin playback starting from the specified track index (0-indexed).

        Args:
            audio_player: An already-connected AudioPlayer instance.
            start_index: Track index to start playback from.
        """
        # Save original nickname for restoration
        original_nickname = await self.output.get_bot_nickname()

        try:
            await self.output.send_bust_started(len(self.tracks), start_index)

            # Initialize playback state
            self._playback = PlaybackState(
                current_index=start_index,
            )
            self.phase = BustPhase.PLAYING

            # Main playback loop
            while self._playback.current_index < len(self.tracks):
                if self._playback.stop_requested:
                    break

                # Wrap play_track in a task so it can be cancelled for skip/seek
                self._playback.current_task = asyncio.create_task(
                    self._play_track(self._playback.current_index, audio_player)
                )

                try:
                    await self._playback.current_task
                except asyncio.CancelledError:
                    # Stop audio playback when task cancelled
                    audio_player.stop()

                self._playback.current_index += 1

            # Playback finished
            await self._finish_playback()
        finally:
            # Restore original nickname
            await self.output.set_bot_nickname(original_nickname)

    async def _play_track(self, index: int, audio_player: AudioPlayer) -> None:
        """Play a single track.

        Args:
            index: Index of track to play.
            audio_player: AudioPlayer instance to use for playback.
        """
        if self._playback is None:
            return

        track = self.tracks[index]

        # Send cooldown notice
        await self.output.send_cooldown_notice()

        # Begin album art generation timer
        start_time = time.time()

        # Get cover art from file, or generate with AI if not present
        cover_art_data = song_utils.get_cover_art_bytes(track.local_filepath)
        if cover_art_data is None:
            cover_art_data = await self.ai_service.get_cover_art(track)

        # Wait remaining cooldown time
        elapsed = time.time() - start_time
        remaining = max(0, self.settings.seconds_between_songs - elapsed)
        await asyncio.sleep(remaining)

        # Display track as now playing (updates message and bot nickname)
        await self.output.display_now_playing(track, cover_art_data)

        # Get seek timestamp if set
        seek = self._playback.seek_timestamp
        self._playback.seek_timestamp = None  # Clear for next track

        # Play track (AudioPlayer handles all FFmpeg/Discord details)
        await audio_player.play(track.local_filepath, seek)

        # Clean up after track
        await self.output.unpin_now_playing()

    async def _finish_playback(self) -> None:
        """Finish playback and transition to FINISHED phase."""
        if self._playback is None:
            return

        # Determine completion status from playback position
        # If we reached the end of the track list, we completed naturally
        # If we stopped before the end, we were stopped early
        completed_naturally = self._playback.current_index >= len(self.tracks)

        self.phase = BustPhase.FINISHED
        self._playback = None

        await self.output.send_bust_finished(self.total_duration, completed_naturally)

    def get_stats(self) -> BustStats:
        """Get statistics about current bust.

        Returns:
            BustStats object containing session statistics.
        """
        total_duration = self.total_duration
        num_tracks = len(self.tracks)
        total_bust_time = (
            total_duration + self.settings.seconds_between_songs * num_tracks
        )

        # Compute submitter statistics
        submitter_durations: dict[int, float] = defaultdict(lambda: 0.0)

        has_errors = False
        for track in self.tracks:
            duration = track.duration
            if duration is None:
                has_errors = True
                duration = 0.0
            submitter_durations[track.submitter_id] += duration

        # Sort submitters by total duration (descending)
        submitter_stats = [
            SubmitterStat(user_id=user_id, total_duration=duration)
            for user_id, duration in sorted(
                submitter_durations.items(),
                key=lambda item: item[1],
                reverse=True,
            )
        ]

        return BustStats(
            num_tracks=num_tracks,
            total_duration=total_duration,
            total_bust_time=total_bust_time,
            submitter_stats=submitter_stats,
            has_errors=has_errors,
        )
