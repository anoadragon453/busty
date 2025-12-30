"""Mock implementation of AudioPlayer protocol for testing."""

import asyncio
from pathlib import Path


class MockAudioPlayer:
    """Test double for AudioPlayer protocol.

    Records play() calls and provides test control over playback completion.
    """

    def __init__(self, auto_complete: bool = False) -> None:
        """Initialize mock audio player.

        Args:
            auto_complete: If True, play() completes immediately.
                          If False, test must call complete_current_track().
        """
        self.played: list[tuple[Path, int | None]] = []
        self._auto_complete = auto_complete
        self._play_done = asyncio.Event()
        self._is_playing = False

    async def play(self, filepath: Path, seek_seconds: int | None = None) -> None:
        """Play audio file. Records call and awaits completion signal."""
        self.played.append((filepath, seek_seconds))
        self._is_playing = True

        if self._auto_complete:
            # Immediately complete (for simple tests)
            self._is_playing = False
            return

        # Wait for test to call complete_current_track() or stop()
        self._play_done.clear()
        await self._play_done.wait()
        self._is_playing = False

    def stop(self) -> None:
        """Stop current playback (causes play() to return)."""
        if self._is_playing:
            self._play_done.set()

    def complete_current_track(self) -> None:
        """Test helper: simulate track finishing naturally."""
        self._play_done.set()
