import asyncio
import logging
from pathlib import Path

from discord import (
    Attachment,
    Forbidden,
    HTTPException,
    Message,
    NotFound,
    Object,
    TextChannel,
)
from discord.utils import DISCORD_EPOCH

from busty.config import constants

logger = logging.getLogger(__name__)


async def try_set_pin(message: Message, pin_state: bool) -> None:
    """Attempt to set message's pin status to pin_state, catching and printing errors"""
    try:
        if pin_state:
            await message.pin()
        else:
            await message.unpin()
    except Forbidden:
        logger.error(
            "Insufficient permission to manage pinned messages. "
            'Please give me the "manage_messages" permission and try again'
        )
    except (HTTPException, NotFound) as e:
        logger.error(f"Altering message pin state failed: {e}")


def build_filepath_for_attachment(
    attachment_directory: Path, guild_id: int, attachment: Attachment
) -> Path:
    """Generate a unique, absolute filepath for a given attachment.

    Args:
        attachment_directory: Base directory for attachments.
        guild_id: Discord guild ID.
        attachment: Discord attachment object.

    Returns:
        Absolute filepath in format: <attachment_directory>/<guild_id>/<attachment_id>
    """
    return attachment_directory / str(guild_id) / str(attachment.id)


def build_filepath_for_media(
    attachment_directory: Path, guild_id: int, media_filename: str
) -> Path:
    """Generate a unique, absolute filepath for media files.

    Args:
        attachment_directory: Base directory for attachments.
        guild_id: Discord guild ID.
        media_filename: Name of the media file.

    Returns:
        Absolute filepath in format: <attachment_directory>/<guild_id>/<media_filename>
    """
    return attachment_directory / str(guild_id) / media_filename


def is_valid_media(attachment_content_type: str | None) -> bool:
    """Returns whether an attachment's content type is considered "media"."""
    return attachment_content_type is not None and (
        attachment_content_type.startswith("audio")
        or attachment_content_type.startswith("video")
    )


async def scrape_channel_media(
    channel: TextChannel,
    attachment_directory: Path,
    max_messages: int = constants.MAXIMUM_MESSAGES_TO_SCAN,
    max_concurrent_downloads: int = constants.MAXIMUM_CONCURRENT_DOWNLOADS,
) -> list[tuple[Message, Attachment, Path]]:
    """Scrape media attachments from a Discord channel.

    Args:
        channel: Discord text channel to scrape.
        attachment_directory: Base directory for storing attachments.
        max_messages: Maximum number of messages to scan.
        max_concurrent_downloads: Maximum concurrent download tasks.

    Returns:
        List of (message, attachment, filepath) tuples.
    """
    # A list of (original message, message attachment, local filepath)
    channel_media_attachments: list[tuple[Message, Attachment, Path]] = []

    attachment_dir = attachment_directory / str(channel.guild.id)

    # Ensure attachment directory exists
    attachment_dir.mkdir(parents=True, exist_ok=True)

    # Iterate through each message in the channel
    # We pass `after` explicitly to work around this nextcord
    # bug: https://github.com/nextcord/nextcord/issues/1238
    after = Object(id=DISCORD_EPOCH)
    async for message in channel.history(
        limit=max_messages, after=after, oldest_first=True
    ):
        if not message.attachments:
            # This message has no attached media
            continue

        for attachment in message.attachments:
            if not is_valid_media(attachment.content_type):
                # Ignore non-audio/video attachments
                continue

            attachment_filepath = build_filepath_for_attachment(
                attachment_directory, channel.guild.id, attachment
            )

            channel_media_attachments.append(
                (
                    message,
                    attachment,
                    attachment_filepath,
                )
            )

    # Clear unused files in this guild's attachment directory
    used_files = {filepath for (_, _, filepath) in channel_media_attachments}
    for file_path in attachment_dir.iterdir():
        if file_path not in used_files:
            if file_path.is_file():
                file_path.unlink()

    # Download attachments
    download_semaphore = asyncio.Semaphore(value=max_concurrent_downloads)

    # Save all files if not in cache
    async def dl_file(attachment: Attachment, attachment_filepath: Path) -> None:
        if attachment_filepath.exists():
            return

        # Limit concurrent downloads
        async with download_semaphore:
            await attachment.save(attachment_filepath)

    if channel_media_attachments:
        tasks = [
            asyncio.create_task(dl_file(at, fp))
            for _, at, fp in channel_media_attachments
        ]
        await asyncio.wait(tasks)

    return channel_media_attachments
