"""Tests for BustController core logic."""

import asyncio
from pathlib import Path

from busty.bust.controller import BustController
from busty.bust.models import BustPhase
from tests.conftest import make_track


class TestBustController:
    """Tests for BustController core logic."""

    def test_initial_phase_is_listed(
        self,
        settings,
        sample_tracks,
        mock_output,
        mock_ai_service,
        mock_user_preferences,
    ):
        """Controller starts in LISTED phase."""
        controller = BustController(
            settings, sample_tracks, mock_output, mock_ai_service, mock_user_preferences
        )
        assert controller.phase == BustPhase.LISTED

    def test_tracks_stored_correctly(
        self,
        settings,
        sample_tracks,
        mock_output,
        mock_ai_service,
        mock_user_preferences,
    ):
        """Controller stores track list."""
        controller = BustController(
            settings, sample_tracks, mock_output, mock_ai_service, mock_user_preferences
        )
        assert len(controller.tracks) == 3
        assert controller.tracks[0].attachment_filename == "track1.mp3"
        assert controller.tracks[2].submitter_name == "Charlie"


class TestPlaybackSequence:
    """Tests for sequential track playback."""

    async def test_plays_all_tracks_in_sequence(
        self,
        settings,
        sample_tracks,
        mock_output,
        mock_audio,
        mock_ai_service,
        mock_user_preferences,
    ):
        """All tracks play in order from start to finish."""
        controller = BustController(
            settings, sample_tracks, mock_output, mock_ai_service, mock_user_preferences
        )

        # Start playback in background
        play_task = asyncio.create_task(controller.play(mock_audio, start_index=0))

        # Wait for first track to start
        await asyncio.sleep(0.01)
        assert mock_audio.played[0][0] == Path("/fake/track1.mp3")
        assert controller.phase == BustPhase.PLAYING

        # Complete first track
        mock_audio.complete_current_track()
        await asyncio.sleep(0.01)

        # Second track should start
        assert len(mock_audio.played) == 2
        assert mock_audio.played[1][0] == Path("/fake/track2.mp3")

        # Complete second track
        mock_audio.complete_current_track()
        await asyncio.sleep(0.01)

        # Third track should start
        assert len(mock_audio.played) == 3
        assert mock_audio.played[2][0] == Path("/fake/track3.mp3")

        # Complete third track - should finish
        mock_audio.complete_current_track()
        await play_task

        # Verify all tracks played
        assert len(mock_audio.played) == 3
        assert controller.phase == BustPhase.FINISHED

    async def test_emits_correct_event_sequence(
        self,
        settings,
        sample_tracks,
        mock_output,
        mock_audio_auto,
        mock_ai_service,
        mock_user_preferences,
    ):
        """Verify BustOutput protocol calls in correct order."""
        controller = BustController(
            settings, sample_tracks, mock_output, mock_ai_service, mock_user_preferences
        )

        await controller.play(mock_audio_auto, start_index=0)

        events = [e[0] for e in mock_output.events]

        # Should see:
        # 1. send_bust_started
        # 2-4. For each track: cooldown, display_now_playing, unpin_now_playing
        # 5. send_bust_finished

        assert events[0] == "send_bust_started"
        assert events.count("send_cooldown_notice") == 3
        assert events.count("display_now_playing") == 3
        assert events.count("unpin_now_playing") == 3
        # send_bust_finished is followed by set_bot_nickname (restoring nickname)
        assert any(e == "send_bust_finished" for e in events)
        assert events[-1] == "set_bot_nickname"

    async def test_play_from_middle_index(
        self,
        settings,
        sample_tracks,
        mock_output,
        mock_audio_auto,
        mock_ai_service,
        mock_user_preferences,
    ):
        """Starting from non-zero index skips earlier tracks."""
        controller = BustController(
            settings, sample_tracks, mock_output, mock_ai_service, mock_user_preferences
        )

        await controller.play(mock_audio_auto, start_index=1)  # Start from track 2

        # Should only play tracks 2 and 3
        assert len(mock_audio_auto.played) == 2
        assert mock_audio_auto.played[0][0] == Path("/fake/track2.mp3")
        assert mock_audio_auto.played[1][0] == Path("/fake/track3.mp3")


class TestSkip:
    """Tests for skip_to() functionality."""

    async def test_skip_advances_to_next_track(
        self,
        settings,
        sample_tracks,
        mock_output,
        mock_audio,
        mock_ai_service,
        mock_user_preferences,
    ):
        """skip_to() cancels current track and starts specified track."""
        controller = BustController(
            settings, sample_tracks, mock_output, mock_ai_service, mock_user_preferences
        )

        play_task = asyncio.create_task(controller.play(mock_audio, start_index=0))

        # Wait for first track to start
        await asyncio.sleep(0.01)
        assert mock_audio.played[-1][0] == Path("/fake/track1.mp3")

        # Skip to track 3
        controller.skip_to(2)
        await asyncio.sleep(0.01)

        # Should now be playing track 3
        assert mock_audio.played[-1][0] == Path("/fake/track3.mp3")

        # Complete and finish
        mock_audio.complete_current_track()
        await play_task

        # Should have played: track1 (interrupted), track3 (completed)
        assert len(mock_audio.played) == 2

    async def test_replay_current_track(
        self,
        settings,
        sample_tracks,
        mock_output,
        mock_audio,
        mock_ai_service,
        mock_user_preferences,
    ):
        """skip_to(current_index) replays current track from start."""
        controller = BustController(
            settings, sample_tracks, mock_output, mock_ai_service, mock_user_preferences
        )

        play_task = asyncio.create_task(controller.play(mock_audio, start_index=1))

        # Wait for track 2 to start
        await asyncio.sleep(0.01)
        assert len(mock_audio.played) == 1

        # Replay current track
        controller.skip_to(1)  # Same index
        await asyncio.sleep(0.01)

        # Track 2 should be played twice
        assert len(mock_audio.played) == 2
        assert mock_audio.played[0][0] == Path("/fake/track2.mp3")
        assert mock_audio.played[1][0] == Path("/fake/track2.mp3")

        # Complete replay and finish
        mock_audio.complete_current_track()
        await asyncio.sleep(0.01)

        # Should continue to track 3
        assert mock_audio.played[-1][0] == Path("/fake/track3.mp3")

        mock_audio.complete_current_track()
        await play_task


class TestStop:
    """Tests for stop() functionality."""

    async def test_stop_ends_playback_early(
        self,
        settings,
        sample_tracks,
        mock_output,
        mock_audio,
        mock_ai_service,
        mock_user_preferences,
    ):
        """stop() terminates playback without finishing remaining tracks."""
        controller = BustController(
            settings, sample_tracks, mock_output, mock_ai_service, mock_user_preferences
        )

        play_task = asyncio.create_task(controller.play(mock_audio, start_index=0))

        # Wait for first track to start
        await asyncio.sleep(0.01)
        assert len(mock_audio.played) == 1

        # Stop playback
        controller.stop()
        await play_task

        # Only one track should have been attempted
        assert len(mock_audio.played) == 1
        assert controller.phase == BustPhase.FINISHED

    async def test_stop_sends_finished_with_completed_naturally_false(
        self,
        settings,
        sample_tracks,
        mock_output,
        mock_audio,
        mock_ai_service,
        mock_user_preferences,
    ):
        """stop() calls send_bust_finished with completed_naturally=False."""
        controller = BustController(
            settings, sample_tracks, mock_output, mock_ai_service, mock_user_preferences
        )

        play_task = asyncio.create_task(controller.play(mock_audio, start_index=0))
        await asyncio.sleep(0.01)

        controller.stop()
        await play_task

        # Check send_bust_finished event
        finished_events = [
            e for e in mock_output.events if e[0] == "send_bust_finished"
        ]
        assert len(finished_events) == 1

        event_name, total_duration, completed_naturally = finished_events[0]
        assert completed_naturally is False


class TestPhaseTransitions:
    """Tests for BustPhase state management."""

    async def test_phase_transitions_listed_to_playing_to_finished(
        self,
        settings,
        sample_tracks,
        mock_output,
        mock_audio,
        mock_ai_service,
        mock_user_preferences,
    ):
        """Verify phase: LISTED → PLAYING → FINISHED."""
        controller = BustController(
            settings, sample_tracks, mock_output, mock_ai_service, mock_user_preferences
        )

        # Starts in LISTED
        assert controller.phase == BustPhase.LISTED

        # Transitions to PLAYING when play() starts
        play_task = asyncio.create_task(controller.play(mock_audio, start_index=0))
        await asyncio.sleep(0.01)
        assert controller.phase == BustPhase.PLAYING

        # Complete all tracks
        for _ in range(3):
            mock_audio.complete_current_track()
            await asyncio.sleep(0.01)

        # Transitions to FINISHED when play() completes
        await play_task
        assert controller.phase == BustPhase.FINISHED

    def test_is_playing_property(
        self,
        settings,
        sample_tracks,
        mock_output,
        mock_ai_service,
        mock_user_preferences,
    ):
        """is_playing property reflects PLAYING phase."""
        controller = BustController(
            settings, sample_tracks, mock_output, mock_ai_service, mock_user_preferences
        )

        assert controller.is_playing is False

        # Manually set to PLAYING (normally done by play())
        controller.phase = BustPhase.PLAYING
        assert controller.is_playing is True

        controller.phase = BustPhase.FINISHED
        assert controller.is_playing is False


class TestStats:
    """Tests for get_stats() functionality."""

    def test_get_stats_returns_correct_totals(
        self, settings, mock_output, mock_ai_service, mock_user_preferences
    ):
        """get_stats() calculates track counts and durations."""
        tracks = [
            make_track(
                "1.mp3", submitter_id=111, submitter_name="Alice", duration=100.0
            ),
            make_track("2.mp3", submitter_id=222, submitter_name="Bob", duration=200.0),
            make_track(
                "3.mp3", submitter_id=111, submitter_name="Alice", duration=150.0
            ),
        ]

        controller = BustController(
            settings, tracks, mock_output, mock_ai_service, mock_user_preferences
        )
        stats = controller.get_stats()

        assert stats.num_tracks == 3
        assert stats.total_duration == 450.0
        # total_bust_time = total_duration + cooldown * num_tracks
        # With seconds_between_songs=0, total_bust_time == total_duration
        assert stats.total_bust_time == 450.0
        assert stats.has_errors is False

    def test_get_stats_groups_by_submitter(
        self, settings, mock_output, mock_ai_service, mock_user_preferences
    ):
        """get_stats() aggregates tracks by submitter."""
        tracks = [
            make_track(
                "1.mp3", submitter_id=111, submitter_name="Alice", duration=100.0
            ),
            make_track("2.mp3", submitter_id=222, submitter_name="Bob", duration=200.0),
            make_track(
                "3.mp3", submitter_id=111, submitter_name="Alice", duration=150.0
            ),
            make_track("4.mp3", submitter_id=222, submitter_name="Bob", duration=50.0),
        ]

        controller = BustController(
            settings, tracks, mock_output, mock_ai_service, mock_user_preferences
        )
        stats = controller.get_stats()

        submitter_map = {s.user_id: s for s in stats.submitter_stats}

        # Alice: 2 tracks, 250s total
        assert submitter_map[111].total_duration == 250.0

        # Bob: 2 tracks, 250s total
        assert submitter_map[222].total_duration == 250.0
