"""Mock implementations of protocols for testing."""

from busty.config import constants
from busty.track import Track


class MockUserPreferences:
    """Test double for UserPreferences."""

    def __init__(self, guild_id: int = 123456789):
        """Initialize mock user preferences.

        Args:
            guild_id: Mock guild ID (default for testing).
        """
        self.guild_id = guild_id
        self._ai_art_preferences: dict[int, bool] = {}
        self._mailbox_preview_preferences: dict[int, bool] = {}

    def should_generate_ai_album_art(self, user_id: int) -> bool:
        """Check if AI art should be generated - uses constant default."""
        return self._ai_art_preferences.get(user_id, constants.AI_ART_ENABLED_DEFAULT)

    def set_ai_album_art_enabled(self, user_id: int, enabled: bool) -> None:
        """Set AI art preference for testing."""
        self._ai_art_preferences[user_id] = enabled

    def should_show_mailbox_preview(self, user_id: int) -> bool:
        """Check if mailbox preview DMs are enabled - uses constant default."""
        return self._mailbox_preview_preferences.get(
            user_id, constants.MAILBOX_PREVIEW_ENABLED_DEFAULT
        )

    def set_mailbox_preview_enabled(self, user_id: int, enabled: bool) -> None:
        """Set mailbox preview preference for testing."""
        self._mailbox_preview_preferences[user_id] = enabled


class MockAIService:
    """Test double for AIService protocol."""

    async def get_cover_art(self, track: Track) -> bytes | None:
        return None

    async def complete_chat(
        self, messages: list[dict[str, str]], max_tokens: int = 512
    ) -> str | None:
        return None

    async def generate_image(self, prompt: str) -> str | None:
        return None


class MockBustOutput:
    """Test double for BustOutput protocol.

    Records all method calls as events for test verification.
    Events are tuples: ('method_name', *args)
    """

    def __init__(self) -> None:
        self.events: list[tuple] = []
        self._nickname: str | None = "MockBot"

    async def send_bust_started(self, total_tracks: int, start_index: int) -> None:
        """Record bust started event."""
        self.events.append(("send_bust_started", total_tracks, start_index))

    async def send_cooldown_notice(self) -> None:
        """Record cooldown notice event."""
        self.events.append(("send_cooldown_notice",))

    async def display_now_playing(
        self, track: Track, cover_art_data: bytes | None
    ) -> None:
        """Record now playing event."""
        self.events.append(
            ("display_now_playing", track.attachment_filename, cover_art_data)
        )

    async def unpin_now_playing(self) -> None:
        """Record unpin event."""
        self.events.append(("unpin_now_playing",))

    async def send_bust_finished(
        self, total_duration: float, completed_naturally: bool
    ) -> None:
        """Record bust finished event."""
        self.events.append(("send_bust_finished", total_duration, completed_naturally))

    async def get_bot_nickname(self) -> str | None:
        """Get current mock nickname."""
        return self._nickname

    async def set_bot_nickname(self, nickname: str | None) -> None:
        """Record nickname change event."""
        self.events.append(("set_bot_nickname", nickname))
        self._nickname = nickname
