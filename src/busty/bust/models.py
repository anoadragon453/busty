"""Data models for bust sessions."""

import asyncio
from dataclasses import dataclass
from enum import Enum, auto


class BustPhase(Enum):
    """Represents the current phase of a bust."""

    LISTED = auto()  # Content scraped and listed, ready to play
    PLAYING = auto()  # Currently playing songs
    FINISHED = auto()  # Bust completed or stopped


@dataclass
class PlaybackState:
    """Mutable playback state that only exists during PLAYING phase."""

    current_index: int
    current_task: asyncio.Task[None] | None = None
    stop_requested: bool = False
    seek_timestamp: int | None = None
