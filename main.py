import asyncio
import base64
import os
import random
from io import BytesIO
from os import path
from typing import List, Optional, Tuple

from mutagen import File as MutagenFile, MutagenError
from mutagen.flac import FLAC, Picture
from mutagen.id3 import ID3FileType, PictureType
from mutagen.ogg import OggFileType
from mutagen.wave import WAVE
from nextcord import (
    Attachment,
    ChannelType,
    Client,
    ClientException,
    Embed,
    FFmpegPCMAudio,
    File,
    Forbidden,
    HTTPException,
    Intents,
    Message,
    NotFound,
    TextChannel,
    VoiceClient,
)
from nextcord.utils import escape_markdown
from PIL import Image, UnidentifiedImageError

# CONSTANTS
# See https://discord.com/developers/docs/resources/channel#embed-limits for LIMIT values
# Max number of characters in an embed description
EMBED_DESCRIPTION_LIMIT = 4096
# Max number of characters in an embed field.value
EMBED_FIELD_VALUE_LIMIT = 1024
# Max number of characters in a normal Disord message
MESSAGE_LIMIT = 2000
# Color of !list embed
LIST_EMBED_COLOR = 0xDD2E44
# Color of "Now Playing" embed
PLAY_EMBED_COLOR = 0x33B86B
# The maximum character length of any song title or artist name
MAXIMUM_SONG_METADATA_CHARACTERS = 1000

# SETTINGS
# How many seconds to wait in-between songs
seconds_between_songs = int(os.environ.get("BUSTY_COOLDOWN_SECS", 10))
# Where to save media files locally
attachment_directory_filepath = os.environ.get("BUSTY_ATTACHMENT_DIR", "attachments")
# The Discord role needed to perform bot commands
dj_role_name = os.environ.get("BUSTY_DJ_ROLE", "bangermeister")

# GLOBAL VARIABLES
# The channel to send messages in
current_channel: Optional[TextChannel] = None
# The media in the current channel
current_channel_content: Optional[List[Tuple[Message, Attachment, str]]] = None
# The actively connected voice client
active_voice_client: Optional[VoiceClient] = None
# The nickname of the bot. We need to store it as it will be
# changed while songs are being played.
original_bot_nickname: Optional[str] = None
# Allow only one async routine to calculate !list at a time
list_task_control_lock = asyncio.Lock()

# STARTUP
# Import list of emojis from either a custom or the default list.
# The default list is expected to be stored at `./emoji_list.py`.
emoji_filepath = os.environ.get("BUSTY_CUSTOM_EMOJI_FILEPATH", "emoji_list")
emoji_dict = __import__(emoji_filepath).DISCORD_TO_UNICODE
emoji_list = list(emoji_dict.values())

# This is necessary to query server members
intents = Intents.default()
intents.members = True

# Set up the Discord client. Connecting to Discord is done at
# the bottom of this file.
client = Client(intents=intents)


@client.event
async def on_ready():
    print("We have logged in as {0.user}.".format(client))


@client.event
async def on_message(message: Message):
    if message.author == client.user:
        return

    # Do not process messages in DM channels
    if message.guild is None:
        return

    for role in message.author.roles:
        if role.name == dj_role_name:
            break
    else:
        # This message's author does not have appropriate permissions
        # to control the bot
        return

    # Allow commands to be case-sensitive and contain leading/following spaces
    message_text = message.content.lower().strip()

    # Determine if the message was a command
    if message_text.startswith("!list"):
        if active_voice_client and active_voice_client.is_connected():
            await message.channel.send("We're busy busting.")
            return

        command_success = "\N{THUMBS UP SIGN}"
        command_fail = "\N{OCTAGONAL SIGN}"

        # Ensure two scrapes aren't making/deleting files at the same time
        if list_task_control_lock.locked():
            await message.add_reaction(command_fail)
            return

        await message.add_reaction(command_success)
        async with list_task_control_lock:
            await command_list(message)

    elif message_text.startswith("!bust"):
        if active_voice_client and active_voice_client.is_connected():
            await message.channel.send("We're already busting.")
            return

        if not current_channel_content or not current_channel:
            await message.channel.send("You need to use !list first.")
            return

        command_args = message.content.split()[1:]
        skip_count = 0
        if command_args:
            try:
                # Expects a positive integer
                bust_index = int(command_args[0])
            except ValueError:
                await message.channel.send("That isn't a number.")
                return
            if bust_index < 0:
                await message.channel.send("That isn't possible.")
                return
            if bust_index == 0:
                await message.channel.send("We start from 1 around here.")
                return
            if bust_index > len(current_channel_content):
                await message.channel.send("There aren't that many tracks.")
                return
            skip_count = bust_index - 1

        await command_play(message, skip_count)

    elif message_text.startswith("!form"):
        if not current_channel_content or not current_channel:
            await message.channel.send("You need to use !list first, sugar.")
            return
        await command_form(message)

    elif message_text.startswith("!skip"):
        if not active_voice_client or not active_voice_client.is_playing():
            await message.channel.send("Nothing is playing.")
            return

        await message.channel.send("I didn't like that track anyways.")
        command_skip()

    elif message_text.startswith("!stop"):
        if not active_voice_client or not active_voice_client.is_playing():
            await message.channel.send("Nothing is playing.")
            return

        await message.channel.send("Alright I'll shut up.")
        await command_stop()


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

    if len(tag_value) > MAXIMUM_SONG_METADATA_CHARACTERS:
        # Cap the length of the string and append an ellipsis
        tag_value = tag_value[: MAXIMUM_SONG_METADATA_CHARACTERS - 1] + "…"

    return tag_value


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
    content = ""
    artist = None
    title = None

    # load tags
    try:
        tags = MutagenFile(local_filepath, easy=True)
        artist = tags.get("artist", [None])[0]
        title = tags.get("title", [None])[0]
    except MutagenError:
        # Ignore file and move on
        print("Error reading tags from file:", local_filepath)

    # Sanitize tag contents.
    # We explicitly check for None here, as anything else means that the data was
    # pulled from the audio.
    if artist is not None:
        artist = sanitize_tag(artist)
    if title is not None:
        title = sanitize_tag(title)

    # Display in the format <Artist-tag> - <Title-tag>
    # If no artist tag use fallback if valid. Otherwise, skip artist
    if artist:
        content += artist + " - "
    elif artist_fallback:
        content += artist_fallback + " - "

    # Always display either title or beautified filename
    if title:
        content += title
    else:
        filename = path.splitext(filename)[0]
        content += filename.replace("_", " ")

    return content


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

    # Make sure it doesn't go over 8MB
    # This is a safe lower bound on the Discord upload limit of 8MiB
    if image_data is None or len(image_data) > 8_000_000:
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


async def command_stop() -> None:
    """Stop playing music."""
    # Clear the queue
    global current_channel_content
    current_channel_content = None

    # Stop playing music. Note that this will run play_next_song, when runs
    # after each song stops playing.
    active_voice_client.stop()

    # Restore the bot's original nick (if it exists)
    if original_bot_nickname and current_channel:
        bot_member = current_channel.guild.get_member(client.user.id)
        await bot_member.edit(nick=original_bot_nickname)


async def command_play(message: Message, skip_count: int = 0):
    # Join active voice call
    voice_channels = message.guild.voice_channels + message.guild.stage_channels
    if not voice_channels:
        await message.channel.send(
            "You need to be in an active voice or stage channel."
        )
        return

    # Get a reference to the bot's Member object
    bot_member = message.guild.get_member(client.user.id)

    for voice_channel in voice_channels:
        if message.author not in voice_channel.members:
            # Skip this voice channel
            continue

        # We found a voice channel that the author is in.
        # Join the voice channel.
        try:
            global active_voice_client
            active_voice_client = await voice_channel.connect()

            # If this is a stage voice channel, ensure that we are currently speaking.
            if voice_channel.type == ChannelType.stage_voice:
                # Set the bot's own member to be speaking in the voice channel
                await bot_member.edit(suppress=False)

            break
        except ClientException as e:
            print("Unable to connect to voice channel:", e)
            return
    else:
        # No voice channel was found
        await message.channel.send("You need to be in an active voice channel.")
        return

    # Save the bot's current display name (nick or name)
    # We'll restore it after songs have finished playing.
    global original_bot_nickname
    original_bot_nickname = bot_member.display_name

    # Play content
    await message.channel.send("Let's get **BUSTY**.")
    await play_next_song(skip_count)


def command_skip() -> None:
    # Stop any currently playing song
    # The next song will play automatically.
    active_voice_client.stop()


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


async def play_next_song(skip_count: int = 0) -> None:
    global current_channel_content
    global current_channel

    # Get a reference to the bot's Member object
    bot_member = current_channel.guild.get_member(client.user.id)

    if not current_channel_content:
        # If there are no more songs to play, leave the active voice channel
        await active_voice_client.disconnect()

        # Restore the bot's original guild nickname (if it had one)
        if original_bot_nickname:
            await bot_member.edit(nick=original_bot_nickname)

        # Say our goodbyes
        embed_title = "❤️‍🔥 That's it everyone ❤️‍🔥"
        embed_content = "Hope ya had a good **BUST!**"
        embed = Embed(
            title=embed_title, description=embed_content, color=LIST_EMBED_COLOR
        )
        await current_channel.send(embed=embed)

        # Clear the current channel and content
        current_channel_content = None
        current_channel = None
        return

    # Wait some time between songs
    if seconds_between_songs:
        embed_title = "Currently Chilling"
        embed_content = "Waiting for {} second{}...\n\n**REMEMBER TO VOTE ON THE GOOGLE FORM!**".format(
            seconds_between_songs, "s" if seconds_between_songs != 1 else ""
        )
        embed = Embed(title=embed_title, description=embed_content)
        await current_channel.send(embed=embed)

        await asyncio.sleep(seconds_between_songs)

    # Remove skip_count number of songs from the front of the queue
    current_channel_content = current_channel_content[skip_count:]

    # Pop a song off the front of the queue and play it
    (
        submit_message,
        attachment,
        local_filepath,
    ) = current_channel_content.pop(0)

    # Associate a random emoji with this song
    random_emoji = pick_random_emoji()

    # Build and send "Now Playing" embed
    embed_title = f"{random_emoji} Now Playing {random_emoji}"
    list_format = "{0}: [{1}]({2}) [`↲jump`]({3})"
    embed_content = list_format.format(
        submit_message.author.mention,
        escape_markdown(song_format(local_filepath, attachment.filename)),
        attachment.url,
        submit_message.jump_url,
    )
    embed = Embed(title=embed_title, description=embed_content, color=PLAY_EMBED_COLOR)

    # Add message content as "More Info", truncating to the embed field.value character limit
    if submit_message.content:
        more_info = submit_message.content
        if len(more_info) > EMBED_FIELD_VALUE_LIMIT:
            more_info = more_info[: EMBED_FIELD_VALUE_LIMIT - 1] + "…"
        embed.add_field(name="More Info", value=more_info, inline=False)

    cover_art = get_cover_art(local_filepath)
    if cover_art is not None:
        embed.set_image(url=f"attachment://{cover_art.filename}")
        now_playing = await current_channel.send(file=cover_art, embed=embed)
    else:
        now_playing = await current_channel.send(embed=embed)

    await try_set_pin(now_playing, True)

    # Called when song finishes playing
    def ffmpeg_post_hook(e: BaseException = None):
        if e is not None:
            print("Song playback quit with error:", e)
        asyncio.run_coroutine_threadsafe(try_set_pin(now_playing, False), client.loop)
        asyncio.run_coroutine_threadsafe(play_next_song(), client.loop)

    # Play song
    active_voice_client.play(FFmpegPCMAudio(local_filepath), after=ffmpeg_post_hook)

    # Change the name of the bot to that of the currently playing song.
    # This allows people to quickly see which song is currently playing.
    new_nick = random_emoji + song_format(
        local_filepath, attachment.filename, submit_message.author.display_name
    )

    # If necessary, truncate name to 32 characters (the maximum allowed by Discord),
    # including an ellipsis on the end.
    if len(new_nick) > 32:
        new_nick = new_nick[:31] + "…"

    # Set the new nickname
    await bot_member.edit(nick=new_nick)


async def command_list(message: Message) -> None:
    target_channel = message.channel

    # If any channels were mentioned in the message, use the first from the list
    if message.channel_mentions:
        mentioned_channel = message.channel_mentions[0]
        if isinstance(mentioned_channel, TextChannel):
            target_channel = mentioned_channel
        else:
            await message.channel.send("That isn't a text channel.")
            return
    # Scrape all tracks in the target channel and list them
    channel_media_attachments = await scrape_channel_media(target_channel)

    # Break on no songs to list
    if len(channel_media_attachments) == 0:
        await message.channel.send("There aren't any songs there.")
        return

    # Title of !list embed
    embed_title = "❤️‍🔥 AIGHT. IT'S BUSTY TIME ❤️‍🔥"
    embed_description_prefix = "**Track Listing**\n"

    # List of embed descriptions to circumvent the Discord character embed limit
    embed_description_list = []
    embed_description_current = ""

    for index, (
        submit_message,
        attachment,
        local_filepath,
    ) in enumerate(channel_media_attachments):
        list_format = "**{0}.** {1}: [{2}]({3}) [`↲jump`]({4})\n"
        song_list_entry = list_format.format(
            index + 1,
            submit_message.author.mention,
            song_format(local_filepath, attachment.filename),
            attachment.url,
            submit_message.jump_url,
        )

        # We only add the embed description prefix to the first message
        description_prefix_charcount = 0
        if len(embed_description_list) == 0:
            description_prefix_charcount = len(embed_description_prefix)

        if (
            description_prefix_charcount
            + len(embed_description_current)
            + len(song_list_entry)
            > EMBED_DESCRIPTION_LIMIT
        ):
            # If adding a new list entry would go over, push our current list entries to a new embed
            embed_description_list.append(embed_description_current)
            # Start a new embed
            embed_description_current = song_list_entry
        else:
            embed_description_current += song_list_entry

    # Add the leftover part to a new embed
    embed_description_list.append(embed_description_current)

    # Iterate through each embed description, send and pin messages
    message_list = []

    # Send messages, only first message gets title and prefix
    for index, embed_description in enumerate(embed_description_list):
        if index == 0:
            embed = Embed(
                title=embed_title,
                description=embed_description_prefix + embed_description,
                color=LIST_EMBED_COLOR,
            )
        else:
            embed = Embed(
                description=embed_description,
                color=LIST_EMBED_COLOR,
            )
        list_message = await message.channel.send(embed=embed)
        message_list.append(list_message)

    # If message channel == target channel, pin messages in reverse order
    if target_channel == message.channel:
        for list_message in reversed(message_list):
            await try_set_pin(list_message, True)

    # Update global channel content
    global current_channel_content
    current_channel_content = channel_media_attachments

    global current_channel
    current_channel = target_channel


async def scrape_channel_media(
    channel: TextChannel,
) -> List[Tuple[Message, Attachment, str]]:
    # A list of (original message, message attachment, local filepath)
    channel_media_attachments: List[Tuple[Message, Attachment, str]] = []

    # Ensure attachment directory exists
    if not os.path.exists(attachment_directory_filepath):
        os.mkdir(attachment_directory_filepath)

    # Iterate through each message in the channel
    async for message in channel.history(limit=500, oldest_first=True):
        if not message.attachments:
            # This message has no attached media
            continue

        for attachment in message.attachments:
            if attachment.content_type is None or (
                not attachment.content_type.startswith("audio")
                and not attachment.content_type.startswith("video")
            ):
                # Ignore non-audio/video attachments
                continue

            # Computed local filepath
            attachment_filepath = path.join(
                attachment_directory_filepath,
                "{}.{}{}".format(
                    message.id,
                    attachment.id,
                    os.path.splitext(attachment.filename)[1],
                ),
            )

            channel_media_attachments.append(
                (
                    message,
                    attachment,
                    attachment_filepath,
                )
            )

    # Save all files if not in cache
    async def dl_file(attachment: Attachment, attachment_filepath: str) -> None:
        if not os.path.exists(attachment_filepath):
            await attachment.save(attachment_filepath)

    tasks = [
        asyncio.create_task(dl_file(at, fp)) for _, at, fp in channel_media_attachments
    ]
    await asyncio.wait(tasks)

    # Clear unused files in attachment directory
    used_files = {path for (_, _, path) in channel_media_attachments}
    for filename in os.listdir(attachment_directory_filepath):
        filepath = path.join(attachment_directory_filepath, filename)
        if filepath not in used_files:
            if os.path.isfile(filepath):
                os.remove(filepath)

    return channel_media_attachments


def pick_random_emoji() -> str:
    """Picks a random emoji from the loaded emoji list"""

    # Choose a random emoji
    encoded_random_emoji = random.choice(emoji_list)

    # Decode the emoji from the unicode characters
    decoded_random_emoji = encoded_random_emoji.encode("Latin1").decode()

    return decoded_random_emoji


async def command_form(message: Message) -> None:
    # Escape strings so they can be assigned as literals within appscript
    def escape_appscript(text: str) -> str:
        return text.replace("\\", "\\\\").replace('"', '\\"')

    # Constants in generated code, Make sure these strings are properly escaped
    default_title = "Busty's Voting"
    low_string = "OK"
    high_string = "Masterpiece"
    low_score = 0
    high_score = 7

    appscript = "function r(){"
    # Setup and grab form
    appscript += f'var f=FormApp.getActiveForm().setTitle("{default_title}");'
    # Clear existing data on form
    appscript += "f.getItems().forEach(i=>f.deleteItem(i));"
    # Add new data to form
    create_line = "[" + ",".join(
        [
            '"{}: {}"'.format(
                escape_appscript(submit_message.author.display_name),
                escape_appscript(song_format(local_filepath, attachment.filename)),
            )
            for submit_message, attachment, local_filepath in current_channel_content
        ]
    )
    create_line += '].forEach((s,i)=>f.addScaleItem().setTitle(i+1+". "+s).setBounds({},{}).setLabels("{}","{}"))'.format(
        low_score, high_score, low_string, high_string
    )
    create_line += "}"
    appscript += create_line

    # There is no way to escape ``` in a code block on Discord, so we replace ``` --> '''
    appscript = appscript.replace("```", "'''")

    # Print message in chunks respecting character limit
    chunk_size = MESSAGE_LIMIT - 6
    for i in range(0, len(appscript), chunk_size):
        await message.channel.send("```{}```".format(appscript[i : i + chunk_size]))


# Connect to Discord. YOUR_BOT_TOKEN_HERE must be replaced with
# a valid Discord bot access token.
if "BUSTY_DISCORD_TOKEN" in os.environ:
    client.run(os.environ["BUSTY_DISCORD_TOKEN"])
else:
    print(
        "Please pass in a Discord bot token via the BUSTY_DISCORD_TOKEN environment variable."
    )
