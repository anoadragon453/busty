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

# Allow only one async routine to calculate !list at a time
list_task_control_lock = asyncio.Lock()


class BustController:
    def __init__(
        self,
        client: Client,
        current_channel_content: List[Tuple[Message, Attachment, str]],
        current_channel: TextChannel,
    ):

        # The actively connected voice client
        self.voice_client: Optional[VoiceClient] = None
        # Currently pinned "now playing" message ID
        self.now_playing_msg: Optional[Message] = None
        # Keep track of the coroutine used to play the next track, which is active while
        # waiting in the intermission between songs. This task should be interrupted if
        # stopping playback is requested.
        self.play_next_task: Optional[asyncio.Task] = None

        # The nickname of the bot. We need to store it as it will be
        # changed while songs are being played.
        self.original_bot_nickname: str = ""

        # The channel to send messages in
        self.current_channel: TextChannel = current_channel
        # The media in the current channel
        self.current_channel_content: List[
            Tuple[Message, Attachment, str]
        ] = current_channel_content
        # When play_next_task.cancel() is called, it is only actually cancelled on unsuspend
        # so play_next_task.cancelled() may return False.
        # We use this variable to keep track of /actual/ cancelled state
        self.play_next_cancelled: bool = False
        # Client object
        self.client: Client = client

        # Calculate total length of all songs in seconds
        self.total_song_len: float = 0.0
        for _, _, local_filepath in self.current_channel_content:
            song_len = song_utils.get_song_length(local_filepath)
            if song_len:
                self.total_song_len += song_len

        self._finished: bool = False

    def active(self) -> bool:
        return self.voice_client and self.voice_client.is_connected()

    def finished(self) -> bool:
        # TODO: This function should become unnecessary once for-refactor is done
        # See comment in main.py
        return self._finished

    async def stop(self) -> None:
        """Stop playing music."""
        self.play_next_cancelled = True
        if self.play_next_task:
            self.play_next_task.cancel()
        await self.finish(say_goodbye=False)

    async def play(self, message: Message, skip_count: int = 0) -> None:
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
        bot_member = message.guild.get_member(self.client.user.id)

        for voice_channel in voice_channels:
            if message.author not in voice_channel.members:
                # Skip this voice channel
                continue

            # We found a voice channel that the author is in.
            # Join the voice channel.
            try:
                self.voice_client = await voice_channel.connect()

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
        self.original_bot_nickname = bot_member.display_name

        # Play content
        await message.channel.send("Let's get **BUSTY**.")
        self.play_next_coro(skip_count)

    def play_next_coro(self, skip_count: int = 0) -> None:
        """Run play_next_song() wrapped in a coroutine so it is cancellable by stop command"""
        self.play_next_cancelled = False
        self.play_next_task = self.client.loop.create_task(
            self.play_next_song(skip_count)
        )
        asyncio.run_coroutine_threadsafe(
            self.play_next_task.get_coro(), self.client.loop
        )

    def skip_song(self) -> None:
        # Stop any currently playing song
        # The next song will play automatically.
        if self.voice_client:
            self.voice_client.stop()

    async def finish(self, say_goodbye: bool = True) -> None:
        """End the current bust.

        Args:
            say_goodbye: If True, a goodbye message will be posted to `current_channel`. If False, the bust
                will be ended silently.
        """
        # Disconnect from voice if necessary
        if self.voice_client and self.voice_client.is_connected():
            await self.voice_client.disconnect()

        # Restore the bot's original guild nickname (if it had one)
        if self.original_bot_nickname and self.current_channel:
            bot_member = self.current_channel.guild.get_member(self.client.user.id)
            await bot_member.edit(nick=self.original_bot_nickname)

        # Unpin current "now playing" message if it exists
        if self.now_playing_msg:
            await discord_utils.try_set_pin(self.now_playing_msg, False)

        if say_goodbye:
            embed_title = "❤️‍🔥 That's it everyone ❤️‍🔥"
            embed_content = "Hope ya had a good **BUST!**"
            embed_content += "\n*Total length of all submissions: {}*".format(
                song_utils.format_time(int(self.total_song_len))
            )
            embed = Embed(
                title=embed_title,
                description=embed_content,
                color=config.LIST_EMBED_COLOR,
            )
            await self.current_channel.send(embed=embed)

        # Clear variables relating to current bust
        self.voice_client = None
        self.original_bot_nickname = ""
        self._finished = True

    async def play_next_song(self, skip_count: int = 0) -> None:
        if not self.current_channel_content:
            # If there are no more songs to play, conclude the bust
            await self.finish()
            return

        # Wait some time between songs
        if config.seconds_between_songs:
            embed_title = "Currently Chilling"
            embed_content = "Waiting for {} second{}...\n\n**REMEMBER TO VOTE ON THE GOOGLE FORM!**".format(
                config.seconds_between_songs,
                "s" if config.seconds_between_songs != 1 else "",
            )
            embed = Embed(title=embed_title, description=embed_content)
            await self.current_channel.send(embed=embed)
            await asyncio.sleep(config.seconds_between_songs)

        # Remove skip_count number of songs from the front of the queue
        self.current_channel_content = self.current_channel_content[skip_count:]

        # Pop a song off the front of the queue and play it
        (
            submit_message,
            attachment,
            local_filepath,
        ) = self.current_channel_content.pop(0)

        # Associate a random emoji with this song
        random_emoji = random.choice(config.emoji_list).encode("Latin1").decode()

        # Build and send "Now Playing" embed
        embed_title = f"{random_emoji} Now Playing {random_emoji}"
        list_format = "{0}: [{1}]({2}) [`↲jump`]({3})"
        embed_content = list_format.format(
            submit_message.author.mention,
            escape_markdown(
                song_utils.song_format(local_filepath, attachment.filename)
            ),
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

        # Add cover art and send
        cover_art = song_utils.get_cover_art(local_filepath)
        if cover_art is not None:
            embed.set_image(url=f"attachment://{cover_art.filename}")
            self.now_playing_msg = await self.current_channel.send(
                file=cover_art, embed=embed
            )
        else:
            self.now_playing_msg = await self.current_channel.send(embed=embed)

        await discord_utils.try_set_pin(self.now_playing_msg, True)

        # Called when song finishes playing
        def ffmpeg_post_hook(e: BaseException = None):
            if e is not None:
                print("Song playback quit with error:", e)

            # Unpin song
            asyncio.run_coroutine_threadsafe(
                discord_utils.try_set_pin(self.now_playing_msg, False), self.client.loop
            )
            self.now_playing_msg = None

            # Play next song if we were not stopped
            if not self.play_next_cancelled:
                self.play_next_coro()

        # Play song
        self.voice_client.play(
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
        bot_member = self.current_channel.guild.get_member(self.client.user.id)
        await bot_member.edit(nick=new_nick)


async def create_controller(client, message: Message) -> Optional[BustController]:
    """Attempt to create a BustController given a channel list command"""
    command_success = "\N{THUMBS UP SIGN}"
    command_fail = "\N{OCTAGONAL SIGN}"

    # Ensure two scrapes aren't making/deleting files at the same time
    if list_task_control_lock.locked():
        await message.add_reaction(command_fail)
        return None

    # Ensure target channel is text
    target_channel = message.channel
    # If any channels were mentioned in the message, use the first from the list
    if message.channel_mentions:
        target_channel = message.channel_mentions[0]

    if not isinstance(target_channel, TextChannel):
        print(f"Cannot create controller for {type(target_channel)}")
        await message.add_reaction(command_fail)
        return None

    await message.add_reaction(command_success)

    async with list_task_control_lock:
        # Scrape all tracks in the target channel and list them
        channel_media_attachments = await discord_utils.scrape_channel_media(
            target_channel
        )

        # Break on no songs to list
        if len(channel_media_attachments) == 0:
            await message.channel.send("There aren't any songs there.")
            return None

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

        # Construct and return controller
        return BustController(client, channel_media_attachments, target_channel)
