"""BustController for managing bust playback sessions."""

import asyncio
import logging
import time
from collections import defaultdict
from typing import TYPE_CHECKING

import requests
from discord import Embed, Interaction, TextChannel

from busty import discord_utils, forms, llm, song_utils
from busty.bust.discord_impl import DiscordBustOutput
from busty.bust.models import BustPhase, BustStats, PlaybackState, SubmitterStat
from busty.bust.protocols import AudioPlayer, BustOutput
from busty.config import constants
from busty.config.settings import BustySettings
from busty.track import Track

if TYPE_CHECKING:
    from busty.main import BustyBot

logger = logging.getLogger(__name__)


class BustController:
    """Manages a bust session for a guild."""

    def __init__(
        self,
        settings: BustySettings,
        tracks: list[Track],
        message_channel: TextChannel,
        output: BustOutput,
    ):
        self.settings = settings
        self.tracks = tracks
        self.channel = message_channel
        self.output = output
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
            await self.output.send_bust_started()

            guild_id = self.channel.guild.id if self.channel.guild else "unknown"
            logger.info(
                f"Starting bust playback in guild {guild_id}, "
                f"{len(self.tracks)} tracks total, starting at track {start_index + 1}"
            )

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
            await self._finish_playback(say_goodbye=not self._playback.stop_requested)
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

        # Get or generate cover art as bytes
        cover_art_data = song_utils.get_cover_art_bytes(track.local_filepath)
        if cover_art_data is None and self.settings.openai_api_key:
            artist, title = song_utils.get_song_metadata_with_fallback(
                track.local_filepath, track.attachment_filename, track.submitter_name
            )
            try:
                cover_art_url = await asyncio.wait_for(
                    llm.generate_album_art(
                        artist or "Unknown Artist", title, track.message_content or ""
                    ),
                    timeout=20.0,
                )
                if cover_art_url:
                    cover_art_data = requests.get(cover_art_url).content
            except asyncio.TimeoutError:
                logger.warning("Cover art generation timed out")

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

    async def _finish_playback(self, say_goodbye: bool = True) -> None:
        """Finish playback and transition to FINISHED phase.

        Args:
            say_goodbye: Whether to post goodbye message.
        """
        self.phase = BustPhase.FINISHED
        self._playback = None

        if say_goodbye:
            await self.output.send_bust_finished(self.total_duration)
            logger.info(f"Bust playback completed in guild {self.channel.guild.id}")
        else:
            logger.info(f"Bust playback stopped early in guild {self.channel.guild.id}")

    def get_google_form_url(self, image_url: str | None = None) -> str | None:
        """Create a Google form for voting on this bust.

        Args:
            image_url: Optional image URL to display at start of form.

        Returns:
            Form URL, or None if form creation fails.
        """
        if self.settings.google_form_folder is None:
            logger.info("Skipping form generation as BUSTY_GOOGLE_FORM_FOLDER is unset")
            return None

        song_list = [
            f"{track.submitter_name}: {song_utils.song_format(track.local_filepath, track.attachment_filename)}"
            for track in self.tracks
        ]

        # Extract bust number from channel name
        bust_number = "".join([c for c in self.channel.name if c.isdigit()])
        if bust_number:
            bust_number = bust_number + " "

        form_url = forms.create_remote_form(
            f"Busty's {bust_number}Voting",
            song_list,
            low_val=0,
            high_val=7,
            low_label="OK",
            high_label="Masterpiece",
            google_auth_file=self.settings.google_auth_file,
            google_form_folder=self.settings.google_form_folder,
            image_url=image_url,
        )
        return form_url

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


async def create_controller(
    client: "BustyBot",
    settings: BustySettings,
    interaction: Interaction,
    list_channel: TextChannel,
) -> BustController | None:
    """Create a BustController by scraping and listing a channel.

    Args:
        client: Discord bot client.
        settings: Bot settings.
        interaction: An interaction which has not yet been responded to.
        list_channel: Channel to scrape for media.

    Returns:
        New BustController, or None if no media found or error.
    """
    await interaction.response.defer(ephemeral=True)

    # Scrape channel for media
    channel_media = await discord_utils.scrape_channel_media(
        list_channel, settings.attachment_cache_dir
    )
    if not channel_media:
        await interaction.edit_original_response(
            content=":warning: No valid media files found."
        )
        return None

    if not isinstance(interaction.channel, TextChannel):
        await interaction.edit_original_response(
            content="This command can only be used in a text channel."
        )
        return None

    # Convert to Track objects
    tracks = [
        Track(
            local_filepath=path,
            attachment_filename=att.filename,
            submitter_id=msg.author.id,
            submitter_name=msg.author.display_name,
            message_content=msg.content,
            message_jump_url=msg.jump_url,
            attachment_url=att.url,
            duration=song_utils.get_song_length(path),
        )
        for msg, att, path in channel_media
    ]

    # Create output implementation and controller
    output = DiscordBustOutput(interaction.channel, client, settings)
    controller = BustController(settings, tracks, interaction.channel, output)

    # Build list embeds
    bust_emoji = ":heart_on_fire:"
    embed_title = f"{bust_emoji} AIGHT. IT'S BUSTY TIME {bust_emoji}"
    embed_prefix = "**Track Listing**\n"

    # Split into multiple embeds if needed (Discord char limit)
    embed_descriptions: list[str] = []
    current_description = ""

    for index, track in enumerate(tracks):
        entry = (
            f"**{index + 1}.** <@{track.submitter_id}>: "
            f"[{song_utils.song_format(track.local_filepath, track.attachment_filename)}]"
            f"({track.attachment_url}) [`↲jump`]({track.message_jump_url})\n"
        )

        # Check if adding entry would exceed limit
        prefix_len = len(embed_prefix) if len(embed_descriptions) == 0 else 0
        if (
            prefix_len + len(current_description) + len(entry)
            > constants.EMBED_DESCRIPTION_LIMIT
        ):
            embed_descriptions.append(current_description)
            current_description = entry
        else:
            current_description += entry

    embed_descriptions.append(current_description)

    # Send embeds
    messages = []
    for i, description in enumerate(embed_descriptions):
        if i == 0:
            embed = Embed(
                title=embed_title,
                description=embed_prefix + description,
                color=constants.LIST_EMBED_COLOR,
            )
        else:
            embed = Embed(description=description, color=constants.LIST_EMBED_COLOR)

        message = await interaction.channel.send(embed=embed)
        messages.append(message)

    # Pin messages and generate form if listing in same channel
    if list_channel == interaction.channel:
        for message in reversed(messages):
            await discord_utils.try_set_pin(message, True)

        # Generate Google Form
        try:
            image_url = client.persistent_state.get_form_image_url(interaction)
            form_url = controller.get_google_form_url(image_url)

            if form_url:
                vote_emoji = ":ballot_box_with_ballot:"
                form_message = await interaction.channel.send(
                    f"{vote_emoji} **Voting Form** {vote_emoji}\n{form_url}"
                )
                await discord_utils.try_set_pin(form_message, True)
        except Exception as e:
            logger.error(f"Failed to generate Google Form: {e}")

    await interaction.delete_original_response()

    logger.info(
        f"Created bust list with {len(tracks)} tracks from channel "
        f"{list_channel.name} (guild {interaction.guild_id})"
    )

    return controller
