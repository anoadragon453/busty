"""Protocol definitions for dependency injection in BustController."""

from pathlib import Path
from typing import Protocol

from busty.track import Track


class AIService(Protocol):
    """Protocol for AI-powered features."""

    async def get_cover_art(self, track: Track) -> bytes | None:
        """Generate cover art for a track using AI.

        Args:
            track: The track to generate cover art for.

        Returns:
            Generated cover art image data as bytes, or None if AI is not
            configured, generation fails, or times out.
        """
        ...


class BustOutput(Protocol):
    """Protocol for bust session output and user interface management.

    Implementations handle all user-visible output during a bust session,
    including messages, pinned content, and bot nickname updates.
    """

    async def send_bust_started(self, total_tracks: int, start_index: int) -> None:
        """Notify users that the bust session is beginning.

        Args:
            total_tracks: Total number of tracks in the session.
            start_index: Index of the track to start from (0-based).
        """
        ...

    async def send_cooldown_notice(self) -> None:
        """Display a notice during the cooldown period before a track plays."""
        ...

    async def display_now_playing(
        self,
        track: Track,
        cover_art_data: bytes | None,
    ) -> None:
        """Update all UI elements to show the track is now playing.

        Displays track metadata with album artwork, pins the message, and updates
        the bot's nickname to show the current track. Handles all presentation
        details internally (emoji selection, formatting, etc.).

        Args:
            track: The track currently being played.
            cover_art_data: Optional album art image data as raw bytes.
        """
        ...

    async def unpin_now_playing(self) -> None:
        """Unpin the currently pinned now-playing message."""
        ...

    async def send_bust_finished(
        self, total_duration: float, completed_naturally: bool
    ) -> None:
        """Notify users that the bust session has ended.

        Args:
            total_duration: Total playback time of all tracks in seconds.
            completed_naturally: True if all tracks played, False if stopped early.
        """
        ...

    async def get_bot_nickname(self) -> str | None:
        """Get the bot's current display nickname.

        Returns:
            The bot's current nickname, or None if unable to retrieve.
        """
        ...

    async def set_bot_nickname(self, nickname: str | None) -> None:
        """Set the bot's display nickname.

        Args:
            nickname: The nickname to set, or None to clear it.
        """
        ...


class AudioPlayer(Protocol):
    """Protocol for audio playback.

    The controller interacts with this protocol without knowing about
    Discord voice connections. Implementations handle connection lifecycle
    separately (connect/disconnect are not part of the protocol).
    """

    async def play(self, filepath: Path, seek_seconds: int | None = None) -> None:
        """Play an audio file, awaiting until playback completes.

        Args:
            filepath: Path to the audio file to play.
            seek_seconds: Optional timestamp to start playback from.

        Returns when playback finishes naturally or stop() is called.
        """
        ...

    def stop(self) -> None:
        """Stop current playback immediately.

        Calling this causes any pending play() call to return.
        Safe to call when nothing is playing.
        """
        ...
