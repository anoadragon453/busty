"""Tests for BustRegistry controller lifecycle management."""

from busty.bust.controller import BustController
from busty.bust.models import BustPhase
from busty.bust.registry import BustRegistry


class TestBustRegistry:
    """Tests for BustRegistry controller lifecycle management."""

    def test_register_and_retrieve_controller(
        self,
        settings,
        sample_tracks,
        mock_output,
        mock_ai_service,
        mock_user_preferences,
    ):
        """Can register and retrieve a controller by guild_id."""
        registry = BustRegistry()
        controller = BustController(
            settings, sample_tracks, mock_output, mock_ai_service, mock_user_preferences
        )

        registry.register(123, controller)

        retrieved = registry.get(123)
        assert retrieved is controller

    def test_get_nonexistent_returns_none(self):
        """get() returns None for unregistered guild."""
        registry = BustRegistry()
        assert registry.get(999) is None

    def test_auto_cleans_finished_controllers(
        self,
        settings,
        sample_tracks,
        mock_output,
        mock_ai_service,
        mock_user_preferences,
    ):
        """Registry removes FINISHED controllers when accessed."""
        registry = BustRegistry()
        controller = BustController(
            settings, sample_tracks, mock_output, mock_ai_service, mock_user_preferences
        )

        # Register controller in FINISHED state
        controller.phase = BustPhase.FINISHED
        registry.register(123, controller)

        # get() should return None and remove it
        assert registry.get(123) is None

        # Verify it's really gone
        assert registry.get(123) is None

    def test_does_not_clean_listed_controllers(
        self,
        settings,
        sample_tracks,
        mock_output,
        mock_ai_service,
        mock_user_preferences,
    ):
        """Registry keeps LISTED controllers."""
        registry = BustRegistry()
        controller = BustController(
            settings, sample_tracks, mock_output, mock_ai_service, mock_user_preferences
        )

        # Controller starts in LISTED phase
        assert controller.phase == BustPhase.LISTED
        registry.register(123, controller)

        # Should still be retrievable
        assert registry.get(123) is controller

    def test_does_not_clean_playing_controllers(
        self,
        settings,
        sample_tracks,
        mock_output,
        mock_ai_service,
        mock_user_preferences,
    ):
        """Registry keeps PLAYING controllers."""
        registry = BustRegistry()
        controller = BustController(
            settings, sample_tracks, mock_output, mock_ai_service, mock_user_preferences
        )

        controller.phase = BustPhase.PLAYING
        registry.register(123, controller)

        # Should still be retrievable
        assert registry.get(123) is controller
