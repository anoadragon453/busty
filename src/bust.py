import asyncio
import random
from typing import List, Optional, Tuple, Union

from nextcord import (
    Attachment,
    ChannelType,
    Client,
    ClientException,
    Embed,
    FFmpegPCMAudio,
    Message,
    StageChannel,
    TextChannel,
    VoiceChannel,
    VoiceClient,
)
from nextcord.utils import escape_markdown

import config
import discord_utils
import song_utils

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
# Total length of all songs in seconds
total_song_len: Optional[float]
# Currently pinned "now playing" message ID
now_playing_msg: Optional[Message] = None
# Keep track of the coroutine used to play the next track, which is active while
# waiting in the intermission between songs. This task should be interrupted if
# stopping playback is requested.
play_next_task: Optional[asyncio.Task] = None
# When play_next_task.cancel() is called, it is only actually cancelled on unsuspend
# so play_next_task.cancelled() may return False.
# We use this variable to keep track of /actual/ cancelled state
play_next_cancelled: bool = False
# Client object
client: Client = None


async def command_stop() -> None:
    """Stop playing music."""
    global play_next_cancelled
    play_next_cancelled = True
    play_next_task.cancel()
    await finish_bust(say_goodbye=False)


async def command_play(message: Message, skip_count: int = 0) -> None:
    # Join active voice call
    voice_channels: List[Union[VoiceChannel, StageChannel]] = list(
        message.guild.voice_channels
    )
    voice_channels.extend(message.guild.stage_channels)

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
    play_next_coro()


def play_next_coro(skip_count: int = 0) -> None:
    """Run play_next_song() wrapped in a coroutine so it is cancellable by stop command"""
    global play_next_task
    global play_next_cancelled
    play_next_cancelled = False
    play_next_task = client.loop.create_task(play_next_song(skip_count))
    asyncio.run_coroutine_threadsafe(play_next_task.get_coro(), client.loop)


def command_skip() -> None:
    # Stop any currently playing song
    # The next song will play automatically.
    active_voice_client.stop()


async def finish_bust(say_goodbye: bool = True) -> None:
    """End the current bust.

    Args:
        say_goodbye: If True, a goodbye message will be posted to `current_channel`. If False, the bust
            will be ended silently.
    """
    global active_voice_client
    global original_bot_nickname
    global current_channel_content
    global current_channel
    global total_song_len

    # Disconnect from voice if necessary
    if active_voice_client and active_voice_client.is_connected():
        await active_voice_client.disconnect()

    # Restore the bot's original guild nickname (if it had one)
    if original_bot_nickname and current_channel:
        bot_member = current_channel.guild.get_member(client.user.id)
        await bot_member.edit(nick=original_bot_nickname)

    if say_goodbye:
        embed_title = "❤️‍🔥 That's it everyone ❤️‍🔥"
        embed_content = "Hope ya had a good **BUST!**"
        embed_content += "\n*Total length of all submissions: {}*".format(
            song_utils.format_time(int(total_song_len))
        )
        embed = Embed(
            title=embed_title, description=embed_content, color=config.LIST_EMBED_COLOR
        )
        await current_channel.send(embed=embed)

    # Clear variables relating to current bust
    active_voice_client = None
    original_bot_nickname = None
    current_channel_content = None
    current_channel = None
    total_song_len = None


async def play_next_song(skip_count: int = 0) -> None:
    global current_channel_content
    global current_channel
    global now_playing_msg

    if not current_channel_content:
        # If there are no more songs to play, conclude the bust
        await finish_bust()
        return

    # Wait some time between songs
    if config.seconds_between_songs:
        embed_title = "Currently Chilling"
        embed_content = "Waiting for {} second{}...\n\n**REMEMBER TO VOTE ON THE GOOGLE FORM!**".format(
            config.seconds_between_songs,
            "s" if config.seconds_between_songs != 1 else "",
        )
        embed = Embed(title=embed_title, description=embed_content)
        await current_channel.send(embed=embed)
        await asyncio.sleep(config.seconds_between_songs)

    # Remove skip_count number of songs from the front of the queue
    current_channel_content = current_channel_content[skip_count:]

    # Pop a song off the front of the queue and play it
    (
        submit_message,
        attachment,
        local_filepath,
    ) = current_channel_content.pop(0)

    # Associate a random emoji with this song
    random_emoji = random.choice(config.emoji_list).encode("Latin1").decode()

    # Build and send "Now Playing" embed
    embed_title = f"{random_emoji} Now Playing {random_emoji}"
    list_format = "{0}: [{1}]({2}) [`↲jump`]({3})"
    embed_content = list_format.format(
        submit_message.author.mention,
        escape_markdown(song_utils.song_format(local_filepath, attachment.filename)),
        attachment.url,
        submit_message.jump_url,
    )
    embed = Embed(
        title=embed_title, description=embed_content, color=config.PLAY_EMBED_COLOR
    )

    # Add message content as "More Info", truncating to the embed field.value character limit
    if submit_message.content:
        more_info = submit_message.content
        if len(more_info) > config.EMBED_FIELD_VALUE_LIMIT:
            more_info = more_info[: config.EMBED_FIELD_VALUE_LIMIT - 1] + "…"
        embed.add_field(name="More Info", value=more_info, inline=False)

    cover_art = song_utils.get_cover_art(local_filepath)
    if cover_art is not None:
        embed.set_image(url=f"attachment://{cover_art.filename}")
        now_playing_msg = await current_channel.send(file=cover_art, embed=embed)
    else:
        now_playing_msg = await current_channel.send(embed=embed)

    await discord_utils.try_set_pin(now_playing_msg, True)

    # Called when song finishes playing
    def ffmpeg_post_hook(e: BaseException = None):
        global now_playing_msg

        if e is not None:
            print("Song playback quit with error:", e)

        # Unpin song
        asyncio.run_coroutine_threadsafe(
            discord_utils.try_set_pin(now_playing_msg, False), client.loop
        )
        now_playing_msg = None

        # Play next song if we were not stopped
        if not play_next_cancelled:
            play_next_coro()

    # Play song
    active_voice_client.play(
        FFmpegPCMAudio(
            local_filepath, options=f"-filter:a volume={config.VOLUME_MULTIPLIER}"
        ),
        after=ffmpeg_post_hook,
    )

    # Change the name of the bot to that of the currently playing song.
    # This allows people to quickly see which song is currently playing.
    new_nick = random_emoji + song_utils.song_format(
        local_filepath, attachment.filename, submit_message.author.display_name
    )

    # If necessary, truncate name to 32 characters (the maximum allowed by Discord),
    # including an ellipsis on the end.
    if len(new_nick) > 32:
        new_nick = new_nick[:31] + "…"

    # Set the new nickname
    bot_member = current_channel.guild.get_member(client.user.id)
    await bot_member.edit(nick=new_nick)


async def command_list(message: Message) -> None:
    target_channel = message.channel

    if not isinstance(target_channel, TextChannel):
        print(f"Unsupported channel type to !list: {type(target_channel)}")
        return

    # If any channels were mentioned in the message, use the first from the list
    if message.channel_mentions:
        mentioned_channel = message.channel_mentions[0]
        if isinstance(mentioned_channel, TextChannel):
            target_channel = mentioned_channel
        else:
            await message.channel.send("That isn't a text channel.")
            return
    # Scrape all tracks in the target channel and list them
    channel_media_attachments = await discord_utils.scrape_channel_media(target_channel)

    # Break on no songs to list
    if len(channel_media_attachments) == 0:
        await message.channel.send("There aren't any songs there.")
        return

    # Title of !list embed
    embed_title = "❤️‍🔥 AIGHT. IT'S BUSTY TIME ❤️‍🔥"
    embed_description_prefix = "**Track Listing**\n"

    # List of embed descriptions to circumvent the Discord character embed limit
    embed_description_list: List[str] = []
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
            song_utils.song_format(local_filepath, attachment.filename),
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
            > config.EMBED_DESCRIPTION_LIMIT
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
                color=config.LIST_EMBED_COLOR,
            )
        else:
            embed = Embed(
                description=embed_description,
                color=config.LIST_EMBED_COLOR,
            )
        list_message = await message.channel.send(embed=embed)
        message_list.append(list_message)

    # If message channel == target channel, pin messages in reverse order
    if target_channel == message.channel:
        for list_message in reversed(message_list):
            await discord_utils.try_set_pin(list_message, True)

    # Update global channel content
    global current_channel_content
    current_channel_content = channel_media_attachments

    global current_channel
    current_channel = target_channel

    # Calculate total length of all songs
    global total_song_len
    total_song_len = 0
    for _, _, local_filepath in channel_media_attachments:
        song_len = song_utils.get_song_length(local_filepath)
        if song_len:
            total_song_len += song_len
