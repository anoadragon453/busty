import asyncio
import os
from os import path
from typing import List, Optional, Tuple

import discord
from discord import (
    ChannelType,
    ClientException,
    Forbidden,
    HTTPException,
    Member,
    Message,
    NotFound,
    TextChannel,
    VoiceClient,
)

# SETTINGS
# How many seconds to wait in-between songs
seconds_between_songs = int(os.environ.get("BUSTY_COOLDOWN_SECS", 10))
# Where to save media files locally
attachment_directory_filepath = os.environ.get("BUSTY_ATTACHMENT_DIR", "attachments")
# The Discord role needed to perform bot commands
dj_role_name = os.environ.get("BUSTY_DJ_ROLE", "bangermeister")

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
# This is necessary to query server members
intents = discord.Intents.default()
intents.members = True

# Set up the Discord client. Connecting to Discord is done at
# the bottom of this file.
client = discord.Client(intents=intents)


@client.event
async def on_ready():
    print('We have logged in as {0.user}.'.format(client))


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
        await list(message)

    elif message.content.startswith("!bust"):
        if not current_channel_content or not current_channel:
            await message.channel.send("You need to use !list first, sugar.")
            return

        await play(message)

    elif message.content.startswith("!skip"):
        if not active_voice_client.is_playing():
            await message.channel.send("Nothin' is playin'.")
            return

        await message.channel.send("I didn't like that track anyways.")
        skip()

    elif message.content.startswith("!stop"):
        if not active_voice_client.is_playing():
            await message.channel.send("Nothin' is playin'.")
            return

        await message.channel.send("Aight I'll shut up.")
        await stop()


async def stop():
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


async def play(message: Message):
    # Join active voice call
    voice_channels = message.guild.voice_channels + message.guild.stage_channels
    if not voice_channels:
        await message.channel.send("You need to be in an active voice or stage channel, sugar.")
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

    # Save the bot's current nickname (if it has one).
    # We'll restore it after songs have finished playing.
    global original_bot_nickname
    original_bot_nickname = bot_member.nick

    # Play content
    await message.channel.send("Let's get **BUSTY**.")
    play_next_song()


def skip():
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
            await current_channel.send("Thas it y'all. Hope ya had a good **BUST** ❤️‍🔥 ")

            # Clear the current channel and content
            current_channel = None
            current_channel_content = None

            return

        # Wait some time between songs
        if seconds_between_songs:
            await current_channel.send(f"Chillin' for {seconds_between_songs} seconds...")
            await asyncio.sleep(seconds_between_songs)

        # Pop a song off the front of the queue and play it
        author, filename, local_filepath = current_channel_content.pop(0)
        await current_channel.send(f"**Playing:** {author.mention} - `{filename}`.")
        active_voice_client.play(discord.FFmpegPCMAudio(local_filepath), after=play_next_song)

        # Change the name of the bot to that of the currently playing song.
        # This allows people to quickly see which song is currently playing.
        new_nick = f"{author.nick or author.name} - {filename}"

        # If necessary, truncate name to 32 characters (the maximum allowed by Discord),
        # including an ellipsis on the end.
        if len(new_nick) > 32:
            new_nick = new_nick[:31] + "…"

        # Set the new nickname
        await bot_member.edit(nick=new_nick)

    asyncio.run_coroutine_threadsafe(inner_f(), client.loop)


async def list(message: Message):
    # Scrape all tracks in the message's channel and list them
    channel_media_attachments = await scrape_channel_media(message.channel)

    message_to_send = "❤️‍🔥 AIGHT. IT'S BUSTY TIME ❤️‍🔥\n\n**Track Listing**"

    for index, (author, filename, media_content_bytes) in enumerate(channel_media_attachments):
        message_to_send += f"""
{index+1}. {author.mention} - `{filename}`"""

    # Send the message and pin it
    list_message = await message.channel.send(message_to_send)
    try:
        await list_message.pin()
    except Forbidden:
        print('Insufficient permission to pin tracklist. Please give me the "manage_messages" permission and try again')
    except (HTTPException, NotFound) as e:
        print('Pinning tracklist failed: ', e)

    # Update global channel content
    global current_channel_content
    current_channel_content = channel_media_attachments

    global current_channel
    current_channel = message.channel


async def scrape_channel_media(channel: TextChannel) -> List[Tuple[Member, str, str]]:
    # A list of (uploader, filename, local filepath)
    channel_media_attachments: List[Tuple[Member, str, str]] = []

    # Ensure attachment directory exists
    if not os.path.exists(attachment_directory_filepath):
        os.mkdir(attachment_directory_filepath)

    # Iterate through each message in the channel
    async for message in channel.history(limit=500, oldest_first=True):
        if not message.attachments:
            # This message has no attached media
            continue

        for attachment in message.attachments:
            if (
                not attachment.content_type.startswith("audio")
                and not attachment.content_type.startswith("video")
            ):
                # Ignore non-audio/video attachments
                continue

            # Save attachment content
            # TODO: Parse mp3 tags and things
            attachment_filepath = path.join(attachment_directory_filepath, attachment.filename)
            await attachment.save(attachment_filepath)

            channel_media_attachments.append((message.author, attachment.filename, attachment_filepath))

    return channel_media_attachments

# Connect to Discord. YOUR_BOT_TOKEN_HERE must be replaced with
# a valid Discord bot access token.
if "BUSTY_DISCORD_TOKEN" in os.environ:
    client.run(os.environ["BUSTY_DISCORD_TOKEN"])
else:
    print("Please pass in a Discord bot token via the BUSTY_DISCORD_TOKEN environment variable")
