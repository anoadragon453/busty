"""Data models for bust sessions."""

import asyncio
from dataclasses import dataclass
from enum import Enum, auto
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING

from discord import Attachment, Member, Message, User

from busty import song_utils

if TYPE_CHECKING:
    from discord import VoiceClient


class BustPhase(Enum):
    """Represents the current phase of a bust."""

    LISTED = auto()  # Content scraped and listed, ready to play
    PLAYING = auto()  # Currently playing songs
    FINISHED = auto()  # Bust completed or stopped


@dataclass(frozen=True)
class Track:
    """Immutable track information."""

    message: Message
    attachment: Attachment
    filepath: Path

    @property
    def submitter(self) -> User | Member:
        return self.message.author

    @cached_property
    def duration(self) -> float | None:
        return song_utils.get_song_length(self.filepath)

    @cached_property
    def formatted_title(self) -> str:
        return song_utils.song_format(
            self.filepath, self.attachment.filename, self.submitter.display_name
        )


@dataclass
class PlaybackState:
    """Mutable playback state that only exists during PLAYING phase."""

    voice_client: "VoiceClient"
    original_nickname: str | None
    current_index: int
    current_task: asyncio.Task[None] | None = None
    now_playing_msg: Message | None = None
    stop_requested: bool = False
    seek_timestamp: int | None = None
