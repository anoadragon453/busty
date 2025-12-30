"""Track data model - pure data representation of a music submission."""

from dataclasses import dataclass
from pathlib import Path

from busty import song_utils


@dataclass(frozen=True)
class Track:
    """Pure data representation of a track, independent of Discord types."""

    local_filepath: Path
    attachment_filename: str
    submitter_id: int
    submitter_name: str
    message_content: str | None
    message_jump_url: str
    attachment_url: str
    duration: float | None

    @property
    def formatted_title(self) -> str:
        return song_utils.song_format(
            self.local_filepath, self.attachment_filename, self.submitter_name
        )
