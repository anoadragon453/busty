import base64
import os
from io import BytesIO
from typing import Optional, Tuple

from mutagen import File as MutagenFile, MutagenError
from mutagen.flac import FLAC, Picture
from mutagen.id3 import ID3FileType, PictureType
from mutagen.ogg import OggFileType
from mutagen.wave import WAVE
from nextcord import Attachment, Embed, File, User
from nextcord.utils import escape_markdown
from PIL import Image, UnidentifiedImageError

import config


def embed_song(
    message_content: str,
    attachment_filepath: str,
    attachment: Attachment,
    user: User,
    emoji: str,
    jump_url: str,
) -> Embed:
    """Build and return a "Now Playing" embed"""

    embed_title = f"{emoji} Now Playing {emoji}"
    list_format = "{0}: [{1}]({2}) [`↲jump`]({3})"
    embed_content = list_format.format(
        user.mention,
        escape_markdown(song_format(attachment_filepath, attachment.filename)),
        attachment.url,
        jump_url,
    )
    embed = Embed(
        title=embed_title, description=embed_content, color=config.PLAY_EMBED_COLOR
    )

    if message_content:
        if len(message_content) > config.EMBED_FIELD_VALUE_LIMIT:
            message_content = (
                message_content[: config.EMBED_FIELD_VALUE_LIMIT - 1] + "…"
            )
        embed.add_field(name="More Info", value=message_content, inline=False)

    return embed


def get_song_metadata(
    local_filepath: str, filename: str, artist_fallback: Optional[str] = None
) -> Tuple[Optional[str], str]:
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
        print(f"Error reading tags from file: {local_filepath}")

    # Sanitize tag contents.
    # We explicitly check for None here, as anything else means that the data was
    # pulled from the audio.
    if not artist:
        artist = artist_fallback
    if artist:
        artist = sanitize_tag(artist)

    # Always display either title or beautified filename
    if not title:
        filename = os.path.splitext(filename)[0]
        title = filename.replace("_", " ")
    title = sanitize_tag(title)

    return artist, title


def song_format(
    local_filepath: str, filename: str, artist_fallback: Optional[str] = None
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

    artist, title = get_song_metadata(local_filepath, filename, artist_fallback)
    if not artist:
        return title
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

    if len(tag_value) > config.MAXIMUM_SONG_METADATA_CHARACTERS:
        # Cap the length of the string and append an ellipsis
        tag_value = tag_value[: config.MAXIMUM_SONG_METADATA_CHARACTERS - 1] + "…"

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
def get_song_length(filename: str) -> Optional[float]:
    try:
        audio = MutagenFile(filename)
        if audio is not None:
            return audio.info.length
    except MutagenError as e:
        print(f"Error reading length of {filename}:", e)
    except Exception as e:
        print(f"Unknown error reading length of {filename}:", e)
    return None


def get_cover_art(filename: str) -> Optional[File]:
    # Get image data as bytes
    try:
        image_data = None
        audio = MutagenFile(filename)

        # In each case, ensure audio tags are not None or empty
        # mutagen.wave.WAVE is not an ID3FileType, although its tags are
        # of type mutagen.id3.ID3
        if isinstance(audio, ID3FileType) or isinstance(audio, WAVE):
            if audio.tags:
                for tag_name, tag_value in audio.tags.items():
                    if (
                        tag_name.startswith("APIC:")
                        and tag_value.type == PictureType.COVER_FRONT
                    ):
                        image_data = tag_value.data
        elif isinstance(audio, OggFileType):
            if audio.tags:
                artwork_tags = audio.tags.get("metadata_block_picture", [])
                if artwork_tags:
                    # artwork_tags[0] is the base64-encoded data
                    raw_data = base64.b64decode(artwork_tags[0])
                    image_data = Picture(raw_data).data
        elif isinstance(audio, FLAC):
            if audio.pictures:
                image_data = audio.pictures[0].data
    except MutagenError:
        # Ignore file and move on
        return None
    except Exception as e:
        print(f"Unknown error reading cover art for {filename}:", e)
        return None

    # Make sure it doesn't go over the maximum size allowed for a Discord attachment.
    # Important for when the bot later posts the image during a bust.
    if image_data is None or len(image_data) > config.ATTACHMENT_BYTE_LIMIT:
        return None

    # Get a file pointer to the bytes
    image_bytes_fp = BytesIO(image_data)

    # Read the filetype of the bytes and discern the appropriate file extension
    try:
        image = Image.open(image_bytes_fp)
    except UnidentifiedImageError:
        print(f"Warning: Skipping unidentifiable cover art field in {filename}")
        return None
    image_file_extension = image.format

    # Wind back the file pointer in order to read it a second time
    image_bytes_fp.seek(0)

    # Make up a filename
    cover_filename = f"cover.{image_file_extension}".lower()

    # Create a new discord file from the file pointer and name
    return File(image_bytes_fp, filename=cover_filename)


def convert_timestamp_to_seconds(time_str: str):
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
    parts = [int(part) for part in parts]

    # Pad with zeros if needed (e.g., "1:23" becomes [0, 1, 23])
    while len(parts) < 3:
        parts.insert(0, 0)

    # Calculate total seconds
    hours, minutes, seconds = parts

    # Validate ranges
    if minutes >= 60 or seconds >= 60:
        return None
    if hours < 0 or minutes < 0 or seconds < 0:
        return None

    return (hours * 3600) + (minutes * 60) + seconds
