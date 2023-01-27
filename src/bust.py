import asyncio
import random
from collections import defaultdict
from typing import List, Optional, Tuple, Union

from nextcord import (
    Attachment,
    ChannelType,
    Client,
    ClientException,
    Embed,
    FFmpegPCMAudio,
    Interaction,
    Message,
    StageChannel,
    TextChannel,
    VoiceChannel,
    VoiceClient,
    User,
    Member
)
from nextcord.utils import escape_markdown

import config
import discord_utils
import forms
import song_utils


class BustController:
    def __init__(
        self,
        client: Client,
        bust_content: List[Tuple[Message, Attachment, str]],
        message_channel: TextChannel,
    ):

        # The actively connected voice client
        self.voice_client: Optional[VoiceClient] = None
        # Currently pinned "now playing" message ID
        self.now_playing_msg: Optional[Message] = None
        # Keep track of the coroutine used to play the next track, which is active while
        # waiting in the intermission between songs. This task should be interrupted if
        # stopping playback is requested.
        self.play_song_task: Optional[asyncio.Task] = None

        # The nickname of the bot. We need to store it as it will be
        # changed while songs are being played.
        self.original_bot_nickname: Optional[str] = None

        # The channel to send messages in
        self.message_channel: TextChannel = message_channel
        # The media in the current channel
        self.bust_content: List[Tuple[Message, Attachment, str]] = bust_content
        # Whether bust has been manually stopped
        self.bust_stopped: bool = False
        # Client object
        self.client: Client = client

        # Calculate total length of all songs in seconds
        self.total_song_len: float = 0.0
        for _, _, local_filepath in self.bust_content:
            song_len = song_utils.get_song_length(local_filepath)
            if song_len:
                self.total_song_len += song_len

        self._finished: bool = False

    def is_active(self) -> bool:
        return self.voice_client and self.voice_client.is_connected()

    def finished(self) -> bool:
        # TODO: This function should become unnecessary once for-refactor is done
        # See comment in main.py
        return self._finished

    async def stop(self) -> None:
        """Stop playing music."""
        self.bust_stopped = True
        if self.play_song_task:
            self.play_song_task.cancel()

    def skip_song(self) -> None:
        """Skip current track."""
        if self.play_song_task:
            self.play_song_task.cancel()
            
    def embed_song(self, submit_message, local_filepath, attachment, user) -> None:
        # Associate a random emoji with this song
        random_emoji = random.choice(config.emoji_list).encode("Latin1").decode()

        # Build and send "Now Playing" embed
        embed_title = f"{random_emoji} Now Playing {random_emoji}"
        if submit_message is not str:
            list_format = "{0}: [{1}]({2})"
            embed_content = list_format.format(
                user.mention,
                escape_markdown(
                    song_utils.song_format(local_filepath, attachment.filename)
                ),
                attachment.url
            )
        else:
            list_format = "{0}: [{1}]({2}) [`↲jump`]({3})"
            embed_content = list_format.format(
                user.mention,
                escape_markdown(
                    song_utils.song_format(local_filepath, attachment.filename)
                ),
                attachment.url,
                submit_message.jump_url,
            )
        embed = Embed(
            title=embed_title, description=embed_content, color=config.PLAY_EMBED_COLOR
        )
        
        return embed
            
    async def play(self, interaction: Interaction, skip_count: int = 0) -> None:
        # Join active voice call
        voice_channels: List[Union[VoiceChannel, StageChannel]] = list(
            interaction.guild.voice_channels
        )
        voice_channels.extend(interaction.guild.stage_channels)

        if not voice_channels:
            await interaction.response.send_message(
                "You need to be in an active voice or stage channel.", ephemeral=True
            )
            return

        # Get a reference to the bot's Member object
        bot_member = interaction.guild.get_member(self.client.user.id)

        for voice_channel in voice_channels:
            if interaction.user not in voice_channel.members:
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
            await interaction.response.send_message(
                "You need to be in an active voice channel.", ephemeral=True
            )
            return

        # Save the bot's current display name (nick or name)
        # We'll restore it after songs have finished playing.
        self.original_bot_nickname = bot_member.display_name

        await interaction.channel.send("Let's get **BUSTY**.")

        # Play songs
        for index in range(skip_count, len(self.bust_content)):
            if self.bust_stopped:
                break

            # wrap play_song() in a coroutine so it is cancellable
            self.play_song_task = asyncio.create_task(self.play_song(index))
            try:
                await self.play_song_task
            except asyncio.CancelledError:
                # Voice client playback must be manually stopped
                self.voice_client.stop()

        # tidy up
        await self.finish(say_goodbye=not self.bust_stopped)

    async def finish(self, say_goodbye: bool = True) -> None:
        """End the current bust.

        Args:
            say_goodbye: If True, a goodbye message will be posted to `message_channel`. If False, the bust
                will be ended silently.
        """
        # Disconnect from voice if necessary
        if self.voice_client and self.voice_client.is_connected():
            await self.voice_client.disconnect()

        # Restore the bot's original guild nickname (if it had one)
        if self.original_bot_nickname and self.message_channel:
            bot_member = self.message_channel.guild.get_member(self.client.user.id)
            await bot_member.edit(nick=self.original_bot_nickname)

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
            await self.message_channel.send(embed=embed)

        # Clear variables relating to current bust
        self.voice_client = None
        self.original_bot_nickname = None
        self._finished = True
        
    async def show_preview(self, submit_message: str, song: Attachment, user: User | Member) -> None:
        local_filepath = song.url
        embed = self.embed_song(submit_message, local_filepath, song, user)
        
        # Add message content as "More Info", truncating to the embed field.value character limit
        if submit_message:
            if len(submit_message) > config.EMBED_FIELD_VALUE_LIMIT:
                more_info = submit_message[: config.EMBED_FIELD_VALUE_LIMIT - 1] + "…"
                embed.add_field(name="More Info", value=more_info, inline=False)
            else:
                embed.add_field(name="More Info", value=submit_message, inline=False)

        # Add cover art and send
        cover_art = song_utils.get_cover_art(local_filepath)
        if cover_art is not None:
            embed.set_image(url=f"attachment://{cover_art.filename}")
            self.now_playing_msg = await self.message_channel.send(
                file=cover_art, embed=embed
            )
        else:
            self.now_playing_msg = await self.message_channel.send(embed=embed)

    async def play_song(self, index: int) -> None:
        # Wait some time between songs
        if config.seconds_between_songs:
            embed_title = "Currently Chilling"
            embed_content = "Waiting for {} second{}...\n\n**REMEMBER TO VOTE ON THE GOOGLE FORM!**".format(
                config.seconds_between_songs,
                "s" if config.seconds_between_songs != 1 else "",
            )
            embed = Embed(title=embed_title, description=embed_content)
            await self.message_channel.send(embed=embed)
            await asyncio.sleep(config.seconds_between_songs)

        # Pop a song off the front of the queue and play it
        submit_message, attachment, local_filepath = self.bust_content[index]
        
        self.embed_song(submit_message, local_filepath, attachment, submit_message.author)

        # Associate a random emoji with this song
        random_emoji = random.choice(config.emoji_list)

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
            self.now_playing_msg = await self.message_channel.send(
                file=cover_art, embed=embed
            )
        else:
            self.now_playing_msg = await self.message_channel.send(embed=embed)

        await discord_utils.try_set_pin(self.now_playing_msg, True)

        # Called when song finishes playing
        async def ffmpeg_post_hook(e: Exception = None):
            if e is not None:
                print("Song playback quit with error:", e)
            # Unpin now playing message
            if self.now_playing_msg:
                await discord_utils.try_set_pin(self.now_playing_msg, False)
                self.now_playing_msg = None
            await play_lock.release()

        # Play song
        play_lock = asyncio.Lock()
        # Acquire the lock during playback so that on release, play_song() returns
        await play_lock.acquire()
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

        # If necessary, truncate name to max length allowed by Discord,
        # appending an ellipsis on the end.
        if len(new_nick) > config.NICKNAME_CHAR_LIMIT:
            new_nick = new_nick[: config.NICKNAME_CHAR_LIMIT - 1] + "…"

        # Set the new nickname
        bot_member = self.message_channel.guild.get_member(self.client.user.id)
        await bot_member.edit(nick=new_nick)

        # Wait for song to finish playing
        await play_lock.acquire()

    def get_google_form_url(self, image_url: Optional[str] = None) -> Optional[str]:
        """Create a Google form for voting on this bust

        Args:
            image_url: If passed, the image at this url will be placed at the start of the form.

        Returns:
            the URL of the Google Form, or None if form creation fails.
        """
        if config.google_form_folder is None:
            print("Skipping form generation as BUSTY_GOOGLE_FORM_FOLDER is unset...")
            return None

        song_list = [
            "{}: {}".format(
                submit_message.author.display_name,
                song_utils.song_format(local_filepath, attachment.filename),
            )
            for submit_message, attachment, local_filepath in self.bust_content
        ]

        # Extract bust number from channel name
        bust_number = "".join([c for c in self.message_channel.name if c.isdigit()])
        if bust_number:
            bust_number = bust_number + " "

        form_url = forms.create_remote_form(
            f"Busty's {bust_number}Voting",
            song_list,
            low_val=0,
            high_val=7,
            low_label="OK",
            high_label="Masterpiece",
            image_url=image_url,
        )
        return form_url

    async def send_stats(self, interaction: Interaction) -> None:
        songs_len = int(self.total_song_len)
        num_songs = len(self.bust_content)
        bust_len = songs_len + config.seconds_between_songs * num_songs

        # Compute map of submitter --> total length of all submissions
        submitter_to_len = defaultdict(lambda: 0.0)

        errors = False
        for submit_message, attachment, local_filepath in self.bust_content:
            song_len = song_utils.get_song_length(local_filepath)
            if song_len is None:
                errors = True
                # Even if song length is an error, we still add 0 to submitter_to_len
                # to ensure len(submitter_to_len) equals the number of submitters
                song_len = 0.0
            submitter_to_len[submit_message.author] += song_len

        # User with longest total submission length
        longest_submitter = max(submitter_to_len, key=submitter_to_len.get)
        longest_submitter_time = int(submitter_to_len[longest_submitter])

        embed_text = "\n".join(
            [
                f"*Number of tracks:* {num_songs}",
                f"*Total track length:* {song_utils.format_time(songs_len)}",
                f"*Total bust length:* {song_utils.format_time(bust_len)}",
                f"*Unique submitters:* {len(submitter_to_len)}",
                f"*Longest submitter:* {longest_submitter.mention} - "
                + f"{song_utils.format_time(longest_submitter_time)}",
            ]
        )
        if errors:
            embed_text += (
                "\n\n**There were some errors. Statistics may be inaccurate.**"
            )
        embed = Embed(
            title="Listed Statistics",
            description=embed_text,
            color=config.INFO_EMBED_COLOR,
        )
        await interaction.response.send_message(embed=embed)


async def create_controller(
    client: Client,
    interaction: Interaction,
    list_channel: TextChannel,
    image_url: Optional[str] = None,
) -> Optional[BustController]:
    """Attempt to create a BustController given a channel list command"""
    # Scrape all tracks in the target channel and list them
    channel_media_attachments = await discord_utils.scrape_channel_media(list_channel)
    if not channel_media_attachments:
        await interaction.edit_original_message(
            content="\N{WARNING SIGN} No valid media files found."
        )
        return None

    bc = BustController(client, channel_media_attachments, interaction.channel)

    # Title of /list embed
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
        list_message = await interaction.channel.send(embed=embed)
        message_list.append(list_message)

    # If message channel == target channel,
    # pin messages in reverse order and generate Google Form
    pin_and_form = list_channel == interaction.channel
    if pin_and_form:
        for list_message in reversed(message_list):
            await discord_utils.try_set_pin(list_message, True)
        # Wrap form generation in try/catch so we don't block a list command if it fails
        form_url = None
        try:
            form_url = bc.get_google_form_url(image_url)
        except Exception as e:
            print("Unknown error generating form:", e)

        if form_url is not None:
            vote_emoji = "\N{BALLOT BOX WITH BALLOT}"
            form_message = await interaction.channel.send(
                f"{vote_emoji} **Voting Form** {vote_emoji}\n{form_url}"
            )
            await discord_utils.try_set_pin(form_message, True)

    # Return controller
    return bc
