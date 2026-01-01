"""Track data model - pure data representation of a music submission."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import discord

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

    @classmethod
    def from_attachment(
        cls,
        attachment_filepath: Path,
        attachment: discord.Attachment,
        submitter_id: int,
        submitter_name: str,
        message_content: str | None,
        message_jump_url: str,
    ) -> Track:
        """Create a Track object from a Discord attachment.

        Args:
            attachment_filepath: Local path where attachment was saved
            attachment: Discord attachment object
            submitter_id: User ID of submitter
            submitter_name: Display name of submitter
            message_content: Optional message text
            message_jump_url: URL to jump to message

        Returns:
            Track object with extracted metadata
        """
        return cls(
            local_filepath=attachment_filepath,
            attachment_filename=attachment.filename,
            submitter_id=submitter_id,
            submitter_name=submitter_name,
            message_content=message_content,
            message_jump_url=message_jump_url,
            attachment_url=attachment.url,
            duration=song_utils.get_song_length(attachment_filepath),
        )
