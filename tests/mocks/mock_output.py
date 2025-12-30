"""Mock implementation of BustOutput protocol for testing."""

from busty.track import Track


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
