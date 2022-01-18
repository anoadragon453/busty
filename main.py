import asyncio
import os
import random
from os import path
from typing import List, Optional, Tuple

import discord
from discord import (
    Attachment,
    ChannelType,
    ClientException,
    Forbidden,
    HTTPException,
    Message,
    NotFound,
    TextChannel,
    VoiceClient,
)
from tinytag import TinyTag

# SETTINGS
# How many seconds to wait in-between songs
seconds_between_songs = int(os.environ.get("BUSTY_COOLDOWN_SECS", 10))
# Where to save media files locally
attachment_directory_filepath = os.environ.get("BUSTY_ATTACHMENT_DIR", "attachments")
# The Discord role needed to perform bot commands
dj_role_name = os.environ.get("BUSTY_DJ_ROLE", "bangermeister")
# Max number of characters in an embed description (currently 4096 in Discord)
embed_description_limit = 4096
# Color of !list embed
list_embed_color = 0xDD2E44

# GLOBAL VARIABLES
# The channel to send messages in
current_channel: Optional = None
# The media in the current channel
current_channel_content: Optional[List] = None
# The actively connected voice client
active_voice_client: Optional[VoiceClient] = None
# The nickname of the bot. We need to store it as it will be
# changed while songs are being played.
original_bot_nickname: Optional[str] = None

# STARTUP
# Import list of emojis from either a custom or the default list.
# The default list is expected to be stored at `./emoji_list.py`.
emoji_filepath = os.environ.get("BUSTY_CUSTOM_EMOJI_FILEPATH", "emoji_list")
emoji_dict = __import__(emoji_filepath).DISCORD_TO_UNICODE
emoji_list = list(emoji_dict.values())

# This is necessary to query server members
intents = discord.Intents.default()
intents.members = True

# Set up the Discord client. Connecting to Discord is done at
# the bottom of this file.
client = discord.Client(intents=intents)


@client.event
async def on_ready():
    print("We have logged in as {0.user}.".format(client))


@client.event
async def on_message(message: Message):
    if message.author == client.user:
        return

    for role in message.author.roles:
        if role.name == dj_role_name:
            break
    else:
        # This message's author does not have appropriate permissions
        # to control the bot
        return

    if message.content.startswith("!list"):
        await command_list(message)

    elif message.content.startswith("!bust"):
        if not current_channel_content or not current_channel:
            await message.channel.send("You need to use !list first, sugar.")
            return

        await command_play(message)

    elif message.content.startswith("!skip"):
        if not active_voice_client.is_playing():
            await message.channel.send("Nothin' is playin'.")
            return

        await message.channel.send("I didn't like that track anyways.")
        command_skip()

    elif message.content.startswith("!stop"):
        if not active_voice_client.is_playing():
            await message.channel.send("Nothin' is playin'.")
            return

        await message.channel.send("Aight I'll shut up.")
        await command_stop()


# Take a filename as string and return it formatted nicely
def format_filename(filename: str):

    # Get all the tags for a track
    audio = TinyTag.get(
        str(os.path.join(f"{attachment_directory_filepath}", f"{filename}"))
    )
    content = ""
    # If the tag does not exist or is whitespace display the file name only
    # Otherwise display in the format @user: <Artist-tag> - <Title-tag>
    if audio.artist is not None and len(audio.artist.strip()) != 0:
        content = content + f"{str(audio.artist)} - "

    if audio.title is not None and len(audio.title.strip()) != 0:
        content = content + f"{str(audio.title)}"
    # If the title tag does not exist but the artist tag exists, display the file name along with artist tag
    else:
        filename = path.splitext(filename)[0]
        content = content + filename.replace("_", " ")

    return discord.utils.escape_markdown(content)


async def command_stop():
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


async def command_play(message: Message):
    # Join active voice call
    voice_channels = message.guild.voice_channels + message.guild.stage_channels
    if not voice_channels:
        await message.channel.send(
            "You need to be in an active voice or stage channel, sugar."
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
        await message.channel.send("You need to be in an active voice channel, sugar.")
        return

    # Save the bot's current display name (nick or name)
    # We'll restore it after songs have finished playing.
    global original_bot_nickname
    original_bot_nickname = bot_member.display_name

    # Play content
    await message.channel.send("Let's get **BUSTY**.")
    play_next_song()


def command_skip():
    # Stop any currently playing song
    # The next song will play automatically.
    active_voice_client.stop()


def play_next_song(e=None):
    async def inner_f():
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
            embed_title = "❤️‍🔥 Thas it y'all ❤️‍🔥"
            embed_content = "Hope ya had a good **BUST!**"
            embed = discord.Embed(
                title=embed_title, description=embed_content, color=0xDD2E44
            )
            await current_channel.send(embed=embed)

            # Clear the current channel and content
            current_channel = None
            current_channel_content = None

            return

        # Wait some time between songs
        if seconds_between_songs:
            embed_title = "Currently Chillin'"
            embed_content = "Waiting for {} second{}...".format(
                seconds_between_songs, "s" if seconds_between_songs != 1 else ""
            )
            embed = discord.Embed(title=embed_title, description=embed_content)
            await current_channel.send(embed=embed)

            await asyncio.sleep(seconds_between_songs)

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
            format_filename(attachment.filename),
            attachment.url,
            submit_message.jump_url,
        )
        embed = discord.Embed(
            title=embed_title, description=embed_content, color=0x33B86B
        )
        if submit_message.content:
            embed.add_field(
                name="More Info", value=submit_message.content, inline=False
            )
        await current_channel.send(embed=embed)

        # Play song
        active_voice_client.play(
            discord.FFmpegPCMAudio(local_filepath), after=play_next_song
        )

        # Change the name of the bot to that of the currently playing song.
        # This allows people to quickly see which song is currently playing.
        new_nick = f"{random_emoji}{submit_message.author.display_name} - {attachment.filename}"

        # If necessary, truncate name to 32 characters (the maximum allowed by Discord),
        # including an ellipsis on the end.
        if len(new_nick) > 32:
            new_nick = new_nick[:31] + "…"

        # Set the new nickname
        await bot_member.edit(nick=new_nick)

    asyncio.run_coroutine_threadsafe(inner_f(), client.loop)


async def command_list(message: Message):
    target_channel = None

    # if any channels were mentioned in the message, use the first from the list
    if message.channel_mentions:
        mentioned_channel = message.channel_mentions[0]
        if isinstance(mentioned_channel, TextChannel):
            target_channel = mentioned_channel
        else:
            await message.channel.send("That ain't a text channel.")
            return
    else:
        target_channel = message.channel

    # Scrape all tracks in the target channel and list them
    channel_media_attachments = await scrape_channel_media(target_channel)
    # title of !list embed
    embed_title = "❤️‍🔥 AIGHT. IT'S BUSTY TIME ❤️‍🔥"
    embed_description_prefix = "**Track Listing**\n"

    # stack of embed descriptions to circumvent the 4096 character embed limit
    embed_description_stack = []
    embed_description_current = ""

    for index, (
        submit_message,
        attachment,
        local_filepath,
    ) in enumerate(channel_media_attachments):
        list_format = "**{0}.** {1}: [{2}]({3}) [`↲jump`]({4})\n"
        list_entry = list_format.format(
            index + 1,
            submit_message.author.mention,
            format_filename(attachment.filename),
            attachment.url,
            submit_message.jump_url,
        )
        if (
            len(embed_description_prefix)
            + len(embed_description_current)
            + len(list_entry)
            > embed_description_limit
        ):
            # if adding a new list entry would go over, push our current list entries to an embed
            embed_description_stack.append(embed_description_current)
            # start a new embed
            embed_description_current = list_entry
        else:
            embed_description_current += list_entry

    # add the leftover part to a new embed (it it exists)
    if len(embed_description_current) > 0:
        embed_description_stack.append(embed_description_current)

    # iterate through each embed description, send and stack messages
    message_stack = []
    if len(embed_description_stack) == 0:
        await message.channel.send("There aint any songs there.")
        return

    for embed_description in embed_description_stack:
        embed = discord.Embed(
            title=embed_title,
            description=embed_description_prefix + embed_description,
            color=list_embed_color,
        )
        list_message = await message.channel.send(embed=embed)
        message_stack.append(list_message)

    # If message channel == target channel, pin messages in reverse order
    if target_channel == message.channel:
        for list_message in reversed(message_stack):
            try:
                await list_message.pin()
            except Forbidden:
                print(
                    'Insufficient permission to pin tracklist. Please give me the "manage_messages" permission and try again'
                )
            except (HTTPException, NotFound) as e:
                print("Pinning tracklist failed: ", e)

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

            # Save attachment content
            attachment_filepath = path.join(
                attachment_directory_filepath, attachment.filename
            )
            await attachment.save(attachment_filepath)

            channel_media_attachments.append(
                (
                    message,
                    attachment,
                    attachment_filepath,
                )
            )

    return channel_media_attachments


def pick_random_emoji() -> str:
    """Picks a random emoji from the loaded emoji list"""

    # Choose a random emoji
    encoded_random_emoji = random.choice(emoji_list)

    # Decode the emoji from the unicode characters
    decoded_random_emoji = encoded_random_emoji.encode("Latin1").decode()

    return decoded_random_emoji


# Connect to Discord. YOUR_BOT_TOKEN_HERE must be replaced with
# a valid Discord bot access token.
if "BUSTY_DISCORD_TOKEN" in os.environ:
    client.run(os.environ["BUSTY_DISCORD_TOKEN"])
else:
    print(
        "Please pass in a Discord bot token via the BUSTY_DISCORD_TOKEN environment variable"
    )
