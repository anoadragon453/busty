import asyncio
import os
from os import path
from typing import List, Optional, Tuple

from nextcord import (
    Attachment,
    Forbidden,
    HTTPException,
    Message,
    NotFound,
    TextChannel,
)

import config


async def try_set_pin(message: Message, pin_state: bool) -> None:
    """Attempt to set message's pin status to pin_state, catching and printing errors"""
    try:
        if pin_state:
            await message.pin()
        else:
            await message.unpin()
    except Forbidden:
        print(
            "Insufficient permission to manage pinned messages. "
            'Please give me the "manage_messages" permission and try again'
        )
    except (HTTPException, NotFound) as e:
        print("Altering message pin state failed:", e)


def build_filepath_for_attachment(message_id: int, attachment: Attachment) -> str:
    """
    Generate a unique filepath for a given attachment for the purposes of saving it to disk

    Generates a filepath in the following format:
    <attachment_directory>/<Discord message ID>.<attachment ID>.<file extension>

    For example:
    /home/user/busty/625891304148303894.625891304081063986.mp3

    Filepaths for each song should be unique and the rest of the codebase assumes that they are.
    A Discord message can contain multiple attachments, including the attachment ID as well.

    Args:
        message_id: The ID of the Discord message that included this attachment.
        attachment: The attachment to build a filepath for.

    Returns:
        An absolute filepath to a file for this attachment in the configured attachment directory.
    """
    filepath = path.join(
        config.attachment_directory_filepath,
        "{}.{}{}".format(
            message_id,
            attachment.id,
            os.path.splitext(attachment.filename)[1],
        ),
    )
    return filepath


def is_valid_media(attachment_content_type: Optional[str]) -> bool:
    """Returns whether an attachment's content type is considered "media".

    Valid media types are those that start with "audio" or "video".

    Args:
        attachment_content_type: A content type (aka MIME type).

    Returns:
        True if the content type is considered to be media, otherwise False.
    """
    return attachment_content_type is not None and (
        attachment_content_type.startswith("audio")
        or attachment_content_type.startswith("video")
    )


async def scrape_channel_media(
    channel: TextChannel,
) -> List[Tuple[Message, Attachment, str]]:
    # A list of (original message, message attachment, local filepath)
    channel_media_attachments: List[Tuple[Message, Attachment, str]] = []

    # Ensure attachment directory exists
    if not os.path.exists(config.attachment_directory_filepath):
        os.mkdir(config.attachment_directory_filepath)

    # Iterate through each message in the channel
    async for message in channel.history(
        limit=config.MAXIMUM_MESSAGES_TO_SCAN, oldest_first=True
    ):
        if not message.attachments:
            # This message has no attached media
            continue

        for attachment in message.attachments:
            if not is_valid_media(attachment.content_type):
                # Ignore non-audio/video attachments
                continue

            attachment_filepath = build_filepath_for_attachment(message.id, attachment)

            channel_media_attachments.append(
                (
                    message,
                    attachment,
                    attachment_filepath,
                )
            )

    download_semaphore = asyncio.Semaphore(value=config.MAXIMUM_CONCURRENT_DOWNLOADS)

    # Save all files if not in cache
    async def dl_file(attachment: Attachment, attachment_filepath: str) -> None:
        if os.path.exists(attachment_filepath):
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

    # Clear unused files in attachment directory
    used_files = {path for (_, _, path) in channel_media_attachments}
    for filename in os.listdir(config.attachment_directory_filepath):
        filepath = path.join(config.attachment_directory_filepath, filename)
        if filepath not in used_files:
            if os.path.isfile(filepath):
                os.remove(filepath)

    return channel_media_attachments
