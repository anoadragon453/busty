"""User preferences management."""

from busty.persistent_state import PersistentState


class UserPreferences:
    """Manages user preferences for a specific guild.

    This class provides a clean interface for querying user preferences
    without exposing the underlying persistent state structure.
    """

    def __init__(self, guild_id: int, persistent_state: PersistentState):
        """Initialize user preferences for a guild.

        Args:
            guild_id: The guild ID these preferences are scoped to.
            persistent_state: The persistent state manager.
        """
        self.guild_id = guild_id
        self._persistent_state = persistent_state

    def should_generate_ai_album_art(self, user_id: int) -> bool:
        """Check if AI-generated album art should be created for a user's submission.

        Args:
            user_id: The user ID who submitted the track.

        Returns:
            True if AI art generation is enabled for this user (default), False otherwise.
        """
        return self._persistent_state.get_ai_art_enabled(self.guild_id, user_id)

    def set_ai_album_art_enabled(self, user_id: int, enabled: bool) -> None:
        """Set whether AI-generated album art is enabled for a user.

        Args:
            user_id: The user ID to set the preference for.
            enabled: True to enable AI art, False to disable.
        """
        self._persistent_state.set_ai_art_enabled(self.guild_id, user_id, enabled)
