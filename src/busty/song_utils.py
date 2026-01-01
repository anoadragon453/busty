import base64
import logging
import os
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, cast

import discord
from discord import Embed, File
from discord.utils import escape_markdown
from mutagen import File as MutagenFile
from mutagen import MutagenError
from mutagen.flac import FLAC, Picture
from mutagen.id3 import ID3FileType, PictureType
from mutagen.ogg import OggFileType
from mutagen.wave import WAVE
from PIL import Image, UnidentifiedImageError

from busty.config import constants

if TYPE_CHECKING:
    from busty.track import Track

logger = logging.getLogger(__name__)


def embed_song(track: "Track", emoji: str) -> Embed:
    """Build and return a "Now Playing" embed."""

    embed_title = f"{emoji} Now Playing {emoji}"
    embed_content = f"<@{track.submitter_id}>: [{escape_markdown(song_format(track.local_filepath, track.attachment_filename))}]({track.attachment_url}) [`↲jump`]({track.message_jump_url})"
    embed = Embed(
        title=embed_title, description=embed_content, color=constants.PLAY_EMBED_COLOR
    )

    if track.message_content:
        message_content = track.message_content
        if len(message_content) > constants.EMBED_FIELD_VALUE_LIMIT:
            message_content = (
                message_content[: constants.EMBED_FIELD_VALUE_LIMIT - 1] + "…"
            )
        embed.add_field(name="More Info", value=message_content, inline=False)

    return embed


def get_song_metadata(local_filepath: Path, filename: str) -> tuple[str | None, str]:
    """
    Return nice artist and title names in a tuple (artist, title)

    If no artist name is read from the file and no fallback is given,
    artist will be None. The fallback song title if no title tag is
    present is a beautified version of its filename.

    Args:
        local_filepath: the actual path on disc
        filename: the filename on Discord
        artist_fallback: the fallback author value (no fallback if not passed)

    Returns:
        A tuple (artist, title). Artist may be None.
    """
    artist = None
    title = None

    # load tags
    try:
        tags = MutagenFile(local_filepath, easy=True)
        if tags is None:
            raise MutagenError()
        artist = tags.get("artist", [None])[0]
        title = tags.get("title", [None])[0]
    except MutagenError:
        # Ignore file and move on
        logger.error(f"Error reading tags from file: {local_filepath}")

    # Sanitize tag contents.
    # We explicitly check for None here, as anything else means that the data was
    # pulled from the audio.
    if artist:
        artist = sanitize_tag(artist)

    # Always display either title or beautified filename
    if not title:
        filename = os.path.splitext(filename)[0]
        title = filename.replace("_", " ")
    title = sanitize_tag(title)

    return artist, title


def get_song_metadata_with_fallback(
    local_filepath: Path, filename: str, artist_fallback: str
) -> tuple[str, str]:
    """Get song metadata with a fallback artist name.

    Args:
        local_filepath: the actual path on disc
        filename: the filename on Discord
        artist_fallback: the fallback artist name

    Returns:
        A tuple (artist, title).
    """
    artist, title = get_song_metadata(local_filepath, filename)
    if not artist:
        artist = artist_fallback
    return artist, title


def song_format(
    local_filepath: Path, filename: str, artist_fallback: str | None = None
) -> str:
    """
    Format a song as text nicely using artist/title tags if available

    Aims for the format "Artist - Title", however if the Artist tag is not
    available and no fallback artist is passed, just "Title" will be used.
    The fallback song title if no title tag is present is a beautified version of
    its filename.

    Args:
        local_filepath: the actual path on disc
        filename: the filename on Discord
        artist_fallback: the fallback author value (no fallback if not passed)

    Returns:
        A string presenting the given song information in a human-readable way.
    """

    artist, title = get_song_metadata(local_filepath, filename)
    if not artist:
        if not artist_fallback:
            return title
        artist = artist_fallback
    return f"{artist} - {title}"


def sanitize_tag(tag_value: str) -> str:
    """Sanitizes a tag value.

    Sanitizes by:
        * removing any newline characters.
        * capping to 1000 characters total.

    Args:
        tag_value: The tag to sanitize (i.e. an artist or song name).

    Returns:
        The sanitized string.
    """
    # Remove any newlines
    tag_value = "".join(tag_value.splitlines())

    if len(tag_value) > constants.MAXIMUM_SONG_METADATA_CHARACTERS:
        # Cap the length of the string and append an ellipsis
        tag_value = tag_value[: constants.MAXIMUM_SONG_METADATA_CHARACTERS - 1] + "…"

    return tag_value


# format an amount of seconds into HH:MM:SS
def format_time(seconds: int) -> str:
    int_seconds = seconds % 60
    int_minutes = (seconds // 60) % 60
    int_hours = seconds // 3600

    result = ""
    if int_hours:
        result += f"{int_hours}h "
    if int_minutes or int_hours:
        result += f"{int_minutes}m "
    result += f"{int_seconds}s"

    return result


# Get length of a song
def get_song_length(filename: Path) -> float | None:
    try:
        audio = MutagenFile(filename)
        if audio is not None:
            return cast(float, audio.info.length)
    except MutagenError as e:
        logger.error(f"Error reading length of {filename}: {e}")
    except Exception as e:
        logger.error(f"Unknown error reading length of {filename}: {e}")
    return None


def get_cover_art_bytes(filename: Path) -> bytes | None:
    """Extract cover art from audio file as raw bytes."""
    # Get image data as bytes
    try:
        image_data = None
        audio = MutagenFile(filename)

        # In each case, ensure audio tags are not None or empty
        # mutagen.wave.WAVE is not an ID3FileType, although its tags are
        # of type mutagen.id3.ID3
        match audio:
            case ID3FileType() | WAVE():
                if audio.tags:
                    for tag_name, tag_value in audio.tags.items():
                        if (
                            tag_name.startswith("APIC:")
                            and tag_value.type == PictureType.COVER_FRONT
                        ):
                            image_data = tag_value.data
            case OggFileType():
                if audio.tags:
                    artwork_tags = audio.tags.get("metadata_block_picture", [])
                    if artwork_tags:
                        # artwork_tags[0] is the base64-encoded data
                        raw_data = base64.b64decode(artwork_tags[0])
                        image_data = Picture(raw_data).data
            case FLAC():
                if audio.pictures:
                    image_data = audio.pictures[0].data
    except MutagenError:
        # Ignore file and move on
        return None
    except Exception as e:
        logger.error(f"Unknown error reading cover art for {filename}: {e}")
        return None

    # Make sure it doesn't go over the maximum size allowed for a Discord attachment.
    if image_data is None or len(image_data) > constants.ATTACHMENT_BYTE_LIMIT:
        return None

    # Validate that it's a readable image format
    try:
        image_bytes_fp = BytesIO(image_data)
        Image.open(image_bytes_fp)
    except UnidentifiedImageError:
        logger.warning(f"Skipping unidentifiable cover art field in {filename}")
        return None

    return image_data


def get_cover_art(filename: Path) -> File | None:
    """Extract cover art from audio file as a Discord File object."""
    image_data = get_cover_art_bytes(filename)
    if image_data is None:
        return None

    # Get a file pointer to the bytes
    image_bytes_fp = BytesIO(image_data)

    # Read the filetype of the bytes and discern the appropriate file extension
    try:
        image = Image.open(image_bytes_fp)
    except UnidentifiedImageError:
        # Should not happen since get_cover_art_bytes validates this
        return None
    image_file_extension = image.format

    # Wind back the file pointer in order to read it a second time
    image_bytes_fp.seek(0)

    # Make up a filename
    cover_filename = f"cover.{image_file_extension}".lower()

    # Create a new discord file from the file pointer and name
    return File(image_bytes_fp, filename=cover_filename)


def convert_timestamp_to_seconds(time_str: str | None) -> int | None:
    # Converts a time string into seconds. Returns 0 if format is invalid.
    # Format is handled either in pure seconds (93, 180) or hh:mm:ss format (1:23:45).
    if time_str is None:
        return None

    if ":" not in time_str:
        if not time_str.isdigit():
            return None
        return int(time_str)

    # Split the time string by colons
    parts = time_str.split(":")

    if len(parts) > 3:
        return None

    # All parts must be digits
    if not all(part.isdigit() for part in parts):
        return None
    int_parts = [int(part) for part in parts]

    # Pad with zeros if needed (e.g., "1:23" becomes [0, 1, 23])
    while len(int_parts) < 3:
        int_parts.insert(0, 0)

    # Calculate total seconds
    hours, minutes, seconds = int_parts

    # Validate ranges
    if minutes >= 60 or seconds >= 60:
        return None
    if hours < 0 or minutes < 0 or seconds < 0:
        return None

    return (hours * 3600) + (minutes * 60) + seconds


def create_track_from_attachment(
    attachment_filepath: Path,
    attachment: discord.Attachment,
    submitter_id: int,
    submitter_name: str,
    message_content: str | None,
    message_jump_url: str,
) -> "Track":
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
    from busty.track import Track  # Import here to avoid circular dependency

    return Track(
        local_filepath=attachment_filepath,
        attachment_filename=attachment.filename,
        submitter_id=submitter_id,
        submitter_name=submitter_name,
        message_content=message_content,
        message_jump_url=message_jump_url,
        attachment_url=attachment.url,
        duration=get_song_length(attachment_filepath),
    )


async def send_track_embed_with_cover_art(
    destination: discord.abc.Messageable,
    track: "Track",
    emoji: str,
    cover_art_bytes: bytes | None,
    content: str | None = None,
) -> discord.Message:
    """Send a track embed with optional cover art to a destination.

    This helper consolidates the common pattern of:
    1. Creating an embed with song_utils.embed_song()
    2. Attaching cover art if present
    3. Sending to a channel/DM

    Args:
        destination: Where to send (channel, DM, etc.)
        track: Track to display
        emoji: Emoji to use in embed
        cover_art_bytes: Optional cover art bytes
        content: Optional message content to include

    Returns:
        The sent Message object
    """
    embed = embed_song(track, emoji)

    if cover_art_bytes:
        # Convert bytes to Discord File
        image_fp = BytesIO(cover_art_bytes)
        cover_art_file = File(image_fp, filename="cover.jpg")
        embed.set_image(url=f"attachment://{cover_art_file.filename}")
        return await destination.send(content=content, file=cover_art_file, embed=embed)
    else:
        return await destination.send(content=content, embed=embed)
