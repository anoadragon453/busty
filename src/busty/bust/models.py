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


@dataclass
class SubmitterStat:
    """Statistics for a single submitter."""

    user_id: int
    total_duration: float


@dataclass
class BustStats:
    """Statistics about a bust session."""

    num_tracks: int
    total_duration: float
    total_bust_time: float
    submitter_stats: list[SubmitterStat]
    has_errors: bool
