"""BustController for managing bust playback sessions."""

import asyncio
import logging
import os
import random
import subprocess
import tempfile
import time
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from io import BytesIO

import requests
from discord import (
    ChannelType,
    Client,
    ClientException,
    Embed,
    FFmpegOpusAudio,
    FFmpegPCMAudio,
    File,
    Interaction,
    Member,
    StageChannel,
    TextChannel,
    User,
    VoiceChannel,
    VoiceClient,
)
from discord.voice_client import AudioSource

from busty import discord_utils, forms, llm, song_utils
from busty.bust.models import BustPhase, PlaybackState, Track
from busty.config import constants
from busty.config.settings import BustySettings

logger = logging.getLogger(__name__)


class BustController:
    """Manages a bust session for a guild."""

    def __init__(
        self,
        client: Client,
        settings: BustySettings,
        tracks: list[Track],
        message_channel: TextChannel,
    ):
        self.client = client
        self.settings = settings
        self.tracks = tracks
        self.channel = message_channel
        self.phase = BustPhase.LISTED
        self._playback: PlaybackState | None = None

    @property
    def is_playing(self) -> bool:
        """Check if currently in PLAYING phase."""
        return self.phase == BustPhase.PLAYING

    @property
    def current_track(self) -> Track | None:
        """Get currently playing track, if any."""
        if self._playback is None:
            return None
        return self.tracks[self._playback.current_index]

    @property
    def total_duration(self) -> float:
        """Calculate total duration of all tracks in seconds."""
        return sum(track.duration or 0.0 for track in self.tracks)

    def stop(self) -> None:
        """Request playback to stop."""
        if self._playback is None:
            return

        self._playback.stop_requested = True
        if self._playback.current_task:
            self._playback.current_task.cancel()

    def skip_to(self, track_index: int) -> None:
        """Skip to a specific track (0-indexed)."""
        if self._playback is None or self._playback.current_task is None:
            return

        # Set index to one before target (will be incremented after cancel)
        self._playback.current_index = max(0, track_index - 1)
        self._playback.current_task.cancel()

    def seek(self, interaction: Interaction, timestamp: int) -> None:
        """Seek current track to timestamp in seconds."""
        if self._playback is None:
            logger.warning("No track is currently playing. Ignoring seek.")
            return

        if interaction.guild is None:
            logger.error("No guild found for seek operation.")
            return

        self._playback.seek_timestamp = timestamp
        # Skip to current track (will restart with seek timestamp)
        self.skip_to(self._playback.current_index)

    @asynccontextmanager
    async def _voice_session(
        self, voice_channel: VoiceChannel | StageChannel
    ) -> AsyncIterator[VoiceClient]:
        """Connect to voice, yield client, then disconnect and restore nickname."""
        voice_client: VoiceClient = await voice_channel.connect()

        # If stage channel, ensure bot is speaking
        if voice_channel.type == ChannelType.stage_voice:
            if self.client.user and voice_channel.guild:
                bot_member = voice_channel.guild.get_member(self.client.user.id)
                if bot_member:
                    await bot_member.edit(suppress=False)

        # Save original nickname
        original_nickname = None
        if self.client.user and voice_channel.guild:
            bot_member = voice_channel.guild.get_member(self.client.user.id)
            if bot_member:
                original_nickname = bot_member.display_name

        try:
            yield voice_client
        finally:
            # Disconnect from voice
            if voice_client.is_connected():
                await voice_client.disconnect()

            # Restore original nickname
            if original_nickname and self.client.user and voice_channel.guild:
                bot_member = voice_channel.guild.get_member(self.client.user.id)
                if bot_member:
                    await bot_member.edit(nick=original_nickname)

    async def play(self, interaction: Interaction, start_index: int = 0) -> None:
        """Begin playback starting from the specified track index (0-indexed).

        Args:
            interaction: An interaction which has not yet been responded to.
            start_index: Track index to start playback from.
        """
        await interaction.response.defer(ephemeral=True)

        # Update message channel to where command was issued
        if not isinstance(interaction.channel, TextChannel):
            await interaction.followup.send(
                "This command can only be used in a text channel.", ephemeral=True
            )
            return
        self.channel = interaction.channel

        # Find the voice channel the user is in
        if interaction.guild is None:
            await interaction.followup.send(
                "This command can only be used in a server.", ephemeral=True
            )
            return

        voice_channels: list[VoiceChannel | StageChannel] = list(
            interaction.guild.voice_channels
        )
        voice_channels.extend(interaction.guild.stage_channels)

        target_voice_channel = None
        for voice_channel in voice_channels:
            if interaction.user in voice_channel.members:
                target_voice_channel = voice_channel
                break

        if target_voice_channel is None:
            await interaction.followup.send(
                "You need to be in an active voice channel.", ephemeral=True
            )
            return

        # Connect to voice and play
        try:
            async with self._voice_session(target_voice_channel) as voice_client:
                await self.channel.send("Let's get **BUSTY**.")
                await interaction.delete_original_response()

                logger.info(
                    f"Starting bust playback in guild {interaction.guild_id}, "
                    f"{len(self.tracks)} tracks total, starting at track {start_index + 1}"
                )

                # Initialize playback state
                self._playback = PlaybackState(
                    voice_client=voice_client,
                    original_nickname=None,  # Managed by context manager
                    current_index=start_index,
                )
                self.phase = BustPhase.PLAYING

                # Main playback loop
                while self._playback.current_index < len(self.tracks):
                    if self._playback.stop_requested:
                        break

                    # Wrap play_track in a task so it can be cancelled for skip/seek
                    self._playback.current_task = asyncio.create_task(
                        self._play_track(self._playback.current_index)
                    )

                    try:
                        await self._playback.current_task
                    except asyncio.CancelledError:
                        # Stop voice playback when task cancelled
                        if voice_client.is_playing():
                            voice_client.stop()

                    self._playback.current_index += 1

                # Playback finished
                await self._finish_playback(
                    say_goodbye=not self._playback.stop_requested
                )

        except ClientException as e:
            logger.error(f"Failed to connect to voice channel: {e}")
            await interaction.followup.send(
                "Failed to connect to voice channel.", ephemeral=True
            )

    async def _play_track(self, index: int) -> None:
        """Play a single track.

        Args:
            index: Index of track to play.
        """
        if self._playback is None:
            return

        track = self.tracks[index]

        # Send chilling message
        embed = Embed(
            title="Currently Chilling",
            description="The track will start soon...\n\n**REMEMBER TO VOTE ON THE GOOGLE FORM!**",
        )
        await self.channel.send(embed=embed)

        # Begin album art generation timer
        start_time = time.time()

        # Get or generate cover art
        cover_art = song_utils.get_cover_art(track.filepath)
        if cover_art is None and self.settings.openai_api_key:
            artist, title = song_utils.get_song_metadata_with_fallback(
                track.filepath, track.attachment.filename, track.submitter.display_name
            )
            try:
                cover_art_url = await asyncio.wait_for(
                    llm.generate_album_art(
                        artist or "Unknown Artist", title, track.message.content or ""
                    ),
                    timeout=20.0,
                )
                if cover_art_url:
                    image_data = requests.get(cover_art_url).content
                    image_bytes_fp = BytesIO(image_data)
                    cover_art = File(image_bytes_fp, "ai_cover.png")
            except asyncio.TimeoutError:
                logger.warning("Cover art generation timed out")

        # Wait remaining cooldown time
        elapsed = time.time() - start_time
        remaining = max(0, self.settings.seconds_between_songs - elapsed)
        await asyncio.sleep(remaining)

        # Build "Now Playing" embed
        random_emoji = random.choice(self.settings.emoji_list)
        embed = song_utils.embed_song(
            track.message.content,
            track.filepath,
            track.attachment,
            track.submitter,
            random_emoji,
            track.message.jump_url,
        )

        # Send embed with cover art
        if cover_art:
            embed.set_image(url=f"attachment://{cover_art.filename}")
            self._playback.now_playing_msg = await self.channel.send(
                file=cover_art, embed=embed
            )
        else:
            self._playback.now_playing_msg = await self.channel.send(embed=embed)

        await discord_utils.try_set_pin(self._playback.now_playing_msg, True)

        # Update bot nickname to show current track
        await self._set_bot_nickname(random_emoji, track.formatted_title)

        # Prepare audio source
        audio_source = await self._prepare_audio(track)

        # Play the track
        play_lock = asyncio.Lock()
        await play_lock.acquire()

        def on_playback_complete(error: Exception | None = None) -> None:
            if error:
                logger.error(f"Song playback error: {error}")
            play_lock.release()

        self._playback.voice_client.play(audio_source, after=on_playback_complete)

        # Wait for playback to complete
        await play_lock.acquire()

        # Clean up after track
        if self._playback.now_playing_msg:
            await discord_utils.try_set_pin(self._playback.now_playing_msg, False)
            self._playback.now_playing_msg = None

    async def _prepare_audio(self, track: Track) -> AudioSource:
        """Prepare audio source for playback, handling seek if needed.

        Args:
            track: Track to prepare.

        Returns:
            Audio source ready for playback.
        """
        if self._playback is None or self._playback.seek_timestamp is None:
            # Normal playback
            return FFmpegPCMAudio(
                str(track.filepath),
                options=f"-filter:a volume={constants.VOLUME_MULTIPLIER}",
            )

        # Seek playback - convert to Opus at timestamp
        seek_to = self._playback.seek_timestamp
        self._playback.seek_timestamp = None  # Clear for next track

        # Validate seek timestamp
        if track.duration and seek_to >= track.duration:
            logger.warning("Seek timestamp beyond track duration, seeking to start")
            seek_to = 0

        # Create temp file for seeked audio
        if self.channel.guild is None:
            # Fallback to normal playback
            return FFmpegPCMAudio(
                str(track.filepath),
                options=f"-filter:a volume={constants.VOLUME_MULTIPLIER}",
            )

        # Create guild-specific temp directory
        guild_temp_dir = self.settings.temp_dir / str(self.channel.guild.id)
        guild_temp_dir.mkdir(parents=True, exist_ok=True)

        # Create unique temp file
        fd, temp_file_str = tempfile.mkstemp(
            suffix=".ogg", dir=guild_temp_dir, prefix="seek_"
        )
        os.close(fd)  # Close fd, we just need the path

        # Convert to Opus starting at seek point
        ffmpeg_command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(track.filepath),
            "-ss",
            str(seek_to),
            "-c:a",
            "libopus",
            "-b:a",
            "128k",
            "-y",
            temp_file_str,
        ]

        try:
            subprocess.run(ffmpeg_command, check=True)
            # Note: temp file will remain until manually cleaned or bot restarts
            # Could add cleanup in finally block if needed
            return FFmpegOpusAudio(
                temp_file_str,
                options=f"-filter:a volume={constants.VOLUME_MULTIPLIER}",
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to seek audio: {e}")
            # Clean up temp file on failure
            try:
                os.unlink(temp_file_str)
            except OSError:
                pass
            # Fallback to normal playback
            return FFmpegPCMAudio(
                str(track.filepath),
                options=f"-filter:a volume={constants.VOLUME_MULTIPLIER}",
            )

    async def _set_bot_nickname(self, emoji: str, title: str) -> None:
        """Update bot's nickname to show current track.

        Args:
            emoji: Random emoji to prefix.
            title: Formatted track title.
        """
        if not self.client.user or not self.channel.guild:
            return

        bot_member = self.channel.guild.get_member(self.client.user.id)
        if not bot_member:
            return

        new_nick = f"{emoji}{title}"

        # Truncate to Discord's limit
        if len(new_nick) > constants.NICKNAME_CHAR_LIMIT:
            new_nick = new_nick[: constants.NICKNAME_CHAR_LIMIT - 1] + "…"

        await bot_member.edit(nick=new_nick)

    async def _finish_playback(self, say_goodbye: bool = True) -> None:
        """Finish playback and transition to FINISHED phase.

        Args:
            say_goodbye: Whether to post goodbye message.
        """
        self.phase = BustPhase.FINISHED
        self._playback = None

        if say_goodbye:
            goodbye_emoji = ":heart_on_fire:"
            embed = Embed(
                title=f"{goodbye_emoji} That's it everyone {goodbye_emoji}",
                description=(
                    "Hope ya had a good **BUST!**\n"
                    f"*Total length of all submissions: {song_utils.format_time(int(self.total_duration))}*"
                ),
                color=constants.LIST_EMBED_COLOR,
            )
            await self.channel.send(embed=embed)

            logger.info(f"Bust playback completed in guild {self.channel.guild.id}")
        else:
            logger.info(f"Bust playback stopped early in guild {self.channel.guild.id}")

    def get_google_form_url(self, image_url: str | None = None) -> str | None:
        """Create a Google form for voting on this bust.

        Args:
            image_url: Optional image URL to display at start of form.

        Returns:
            Form URL, or None if form creation fails.
        """
        if self.settings.google_form_folder is None:
            logger.info("Skipping form generation as BUSTY_GOOGLE_FORM_FOLDER is unset")
            return None

        song_list = [
            f"{track.submitter.display_name}: {song_utils.song_format(track.filepath, track.attachment.filename)}"
            for track in self.tracks
        ]

        # Extract bust number from channel name
        bust_number = "".join([c for c in self.channel.name if c.isdigit()])
        if bust_number:
            bust_number = bust_number + " "

        form_url = forms.create_remote_form(
            f"Busty's {bust_number}Voting",
            song_list,
            low_val=0,
            high_val=7,
            low_label="OK",
            high_label="Masterpiece",
            google_auth_file=self.settings.google_auth_file,
            google_form_folder=self.settings.google_form_folder,
            image_url=image_url,
        )
        return form_url

    async def send_stats(self, interaction: Interaction) -> None:
        """Send statistics about current bust.

        Args:
            interaction: An interaction which has not yet been responded to.
        """
        await interaction.response.defer()

        total_duration = int(self.total_duration)
        num_tracks = len(self.tracks)
        total_bust_time = (
            total_duration + self.settings.seconds_between_songs * num_tracks
        )

        # Compute submitter statistics
        submitter_durations: dict[int, float] = defaultdict(lambda: 0.0)
        submitter_map: dict[int, User | Member] = {}

        errors = False
        for track in self.tracks:
            duration = track.duration
            if duration is None:
                errors = True
                duration = 0.0
            submitter_durations[track.submitter.id] += duration
            submitter_map[track.submitter.id] = track.submitter

        # Sort submitters by total duration
        sorted_submitters = sorted(
            [(duration, user_id) for user_id, duration in submitter_durations.items()],
            reverse=True,
        )

        longest_submitters = [
            f"{i + 1}. {submitter_map[user_id].mention} - {song_utils.format_time(int(duration))}"
            for i, (duration, user_id) in enumerate(
                sorted_submitters[: self.settings.num_longest_submitters]
            )
        ]

        embed_text = "\n".join(
            [
                f"*Number of tracks:* {num_tracks}",
                f"*Total track length:* {song_utils.format_time(total_duration)}",
                f"*Total bust length:* {song_utils.format_time(total_bust_time)}",
                f"*Unique submitters:* {len(submitter_durations)}",
                "*Longest submitters:*",
            ]
            + longest_submitters
        )

        if errors:
            embed_text += (
                "\n\n**There were some errors. Statistics may be inaccurate.**"
            )

        embed = Embed(
            title="Listed Statistics",
            description=embed_text,
            color=constants.INFO_EMBED_COLOR,
        )
        await interaction.followup.send(embed=embed)


async def create_controller(
    client: Client,
    settings: BustySettings,
    interaction: Interaction,
    list_channel: TextChannel,
) -> BustController | None:
    """Create a BustController by scraping and listing a channel.

    Args:
        client: Discord client.
        settings: Bot settings.
        interaction: An interaction which has not yet been responded to.
        list_channel: Channel to scrape for media.

    Returns:
        New BustController, or None if no media found or error.
    """
    await interaction.response.defer(ephemeral=True)

    # Scrape channel for media
    channel_media = await discord_utils.scrape_channel_media(
        list_channel, settings.attachment_cache_dir
    )
    if not channel_media:
        await interaction.edit_original_response(
            content=":warning: No valid media files found."
        )
        return None

    if not isinstance(interaction.channel, TextChannel):
        await interaction.edit_original_response(
            content="This command can only be used in a text channel."
        )
        return None

    # Convert to Track objects
    tracks = [Track(msg, att, path) for msg, att, path in channel_media]

    # Create controller
    controller = BustController(client, settings, tracks, interaction.channel)

    # Build list embeds
    bust_emoji = ":heart_on_fire:"
    embed_title = f"{bust_emoji} AIGHT. IT'S BUSTY TIME {bust_emoji}"
    embed_prefix = "**Track Listing**\n"

    # Split into multiple embeds if needed (Discord char limit)
    embed_descriptions: list[str] = []
    current_description = ""

    for index, track in enumerate(tracks):
        entry = (
            f"**{index + 1}.** {track.submitter.mention}: "
            f"[{song_utils.song_format(track.filepath, track.attachment.filename)}]"
            f"({track.attachment.url}) [`↲jump`]({track.message.jump_url})\n"
        )

        # Check if adding entry would exceed limit
        prefix_len = len(embed_prefix) if len(embed_descriptions) == 0 else 0
        if (
            prefix_len + len(current_description) + len(entry)
            > constants.EMBED_DESCRIPTION_LIMIT
        ):
            embed_descriptions.append(current_description)
            current_description = entry
        else:
            current_description += entry

    embed_descriptions.append(current_description)

    # Send embeds
    messages = []
    for i, description in enumerate(embed_descriptions):
        if i == 0:
            embed = Embed(
                title=embed_title,
                description=embed_prefix + description,
                color=constants.LIST_EMBED_COLOR,
            )
        else:
            embed = Embed(description=description, color=constants.LIST_EMBED_COLOR)

        message = await interaction.channel.send(embed=embed)
        messages.append(message)

    # Pin messages and generate form if listing in same channel
    if list_channel == interaction.channel:
        for message in reversed(messages):
            await discord_utils.try_set_pin(message, True)

        # Generate Google Form
        try:
            image_url = controller.client.persistent_state.get_form_image_url(interaction)
            form_url = controller.get_google_form_url(image_url)

            if form_url:
                vote_emoji = ":ballot_box_with_ballot:"
                form_message = await interaction.channel.send(
                    f"{vote_emoji} **Voting Form** {vote_emoji}\n{form_url}"
                )
                await discord_utils.try_set_pin(form_message, True)
        except Exception as e:
            logger.error(f"Failed to generate Google Form: {e}")

    await interaction.delete_original_response()

    logger.info(
        f"Created bust list with {len(tracks)} tracks from channel "
        f"{list_channel.name} (guild {interaction.guild_id})"
    )

    return controller
