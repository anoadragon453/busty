import discord
import asyncio
import os

from discord import Message, TextChannel, Member, VoiceClient, ClientException, ChannelType
from os import path
from typing import List, Tuple, Optional

## SETTINGS
# How many seconds to wait in-between songs
seconds_between_songs = 10
# Where to save media files locally
attachment_directory_filepath = "attachments"
# The Discord role needed to perform bot commands
dj_role_name = "bangermeister"

## GLOBAL VARIABLES
# The channel to send messages in
current_channel: Optional = None
# The media in the current channel
current_channel_content: Optional[List] = None
# The actively connected voice client
active_voice_client: Optional[VoiceClient] = None

## STARTUP
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
        stop()


def stop():
    """Stop playing music."""
    # Clear the queue
    global current_channel_content
    current_channel_content = None

    # Stop playing music
    active_voice_client.stop()


async def play(message: Message):
    # Join active voice call
    voice_channels = message.guild.voice_channels + message.guild.stage_channels
    if not voice_channels:
        await message.channel.send("You need to be in an active voice or stage channel, sugar.")
        return

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
                # Get our own member profile
                # TODO: This seems hacky.
                for member in voice_channel.members:
                    if member.id == client.user.id:
                        # Set the bot's own member to be speaking in the voice channel
                        await member.edit(suppress=False)
                        break
                else:
                    await current_channel.send("I got fuckin' lost down a dark alleyway...")
                    return

            break
        except ClientException as e:
            print("Unable to connect to voice channel:", e)
            return
    else:
        # No voice channel was found
        await message.channel.send("You need to be in an active voice channel, sugar.")
        return

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
        if not current_channel_content:
            # If there are no more songs to play, leave the active voice channel
            await active_voice_client.disconnect()

            # Say our goodbyes
            await current_channel.send("Thas it y'all. Hope ya had a good **BUST** ❤️‍🔥 ")

            # Clear the current channel and content
            current_channel = None
            current_channel_content = None

        # Wait some time between songs
        if seconds_between_songs:
            await current_channel.send(f"Chillin' for {seconds_between_songs} seconds...")
            await asyncio.sleep(seconds_between_songs)

        # After the current song has finished, pop another off the front and continue playing
        author, filename, local_filepath = current_channel_content.pop(0)
        await current_channel.send(f"**Playing:** <@{author.id}> - `{filename}`.")
        active_voice_client.play(discord.FFmpegPCMAudio(local_filepath), after=play_next_song)

    asyncio.run_coroutine_threadsafe(inner_f(), client.loop)


async def list(message: Message):
    # Scrape all tracks in the message's channel and list them
    channel_media_attachments = await scrape_channel_media(message.channel)

    message_to_send = "❤️‍🔥 AIGHT. IT'S BUSTY TIME ❤️‍🔥\n\n**Track Listing**"

    for index, (author, filename, media_content_bytes) in enumerate(channel_media_attachments):
        message_to_send += f"""
{index+1}. <@{author.id}> - `{filename}`"""

    # Send the message
    await message.channel.send(message_to_send)

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
client.run('YOUR_BOT_TOKEN_HERE')
