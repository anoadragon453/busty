"""Discord implementations of BustController protocols."""

import asyncio
import logging
import os
import random
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

import requests
from discord import (
    ChannelType,
    Embed,
    FFmpegOpusAudio,
    FFmpegPCMAudio,
    File,
    Message,
    StageChannel,
    TextChannel,
    VoiceChannel,
    VoiceClient,
)
from discord.voice_client import AudioSource

from busty import discord_utils, llm, song_utils
from busty.config import constants
from busty.config.settings import BustySettings
from busty.track import Track

if TYPE_CHECKING:
    from busty.main import BustyBot

logger = logging.getLogger(__name__)


class OpenAIService:
    """OpenAI implementation of AIService protocol."""

    def __init__(self, settings: BustySettings):
        self.settings = settings

    async def get_cover_art(self, track: Track) -> bytes | None:
        """Generate cover art for a track using OpenAI.

        Returns None if OpenAI is not configured, generation fails, or times out.
        """
        # Skip if OpenAI is not configured
        if not self.settings.openai_api_key:
            return None

        # Extract metadata for generation
        artist, title = song_utils.get_song_metadata_with_fallback(
            track.local_filepath, track.attachment_filename, track.submitter_name
        )

        try:
            # Generate cover art URL using OpenAI
            cover_art_url = await asyncio.wait_for(
                llm.generate_album_art(
                    artist or "Unknown Artist", title, track.message_content or ""
                ),
                timeout=constants.COVER_ART_GENERATE_TIMEOUT,
            )

            # Fetch the generated image
            if cover_art_url:
                response = requests.get(
                    cover_art_url, timeout=constants.COVER_ART_FETCH_TIMEOUT
                )
                response.raise_for_status()
                return response.content

            return None

        except asyncio.TimeoutError:
            logger.warning("Cover art generation timed out")
            return None
        except requests.RequestException as e:
            logger.error(f"Failed to fetch generated cover art: {e}")
            return None


class DiscordBustOutput:
    """Discord implementation of BustOutput protocol."""

    def __init__(
        self, channel: TextChannel, client: "BustyBot", settings: BustySettings
    ):
        self.channel = channel
        self.client = client
        self.settings = settings
        self._now_playing_msg: Message | None = None

    async def send_bust_started(self, total_tracks: int, start_index: int) -> None:
        """Notify users that the bust session is beginning."""
        guild_id = self.channel.guild.id if self.channel.guild else "unknown"
        logger.info(
            f"Starting bust playback in guild {guild_id}, "
            f"{total_tracks} tracks total, starting at track {start_index + 1}"
        )
        await self.channel.send("Let's get **BUSTY**.")

    async def send_cooldown_notice(self) -> None:
        """Display a notice during the cooldown period before a track plays."""
        embed = Embed(
            title="Currently Chilling",
            description="The track will start soon...\n\n**REMEMBER TO VOTE ON THE GOOGLE FORM!**",
        )
        await self.channel.send(embed=embed)

    async def display_now_playing(
        self,
        track: Track,
        cover_art_data: bytes | None,
    ) -> None:
        """Update all UI elements to show the track is now playing."""
        # Choose random emoji for display
        random_emoji = random.choice(self.settings.emoji_list)

        # Build "Now Playing" embed
        embed = song_utils.embed_song(track, random_emoji)

        # Send embed with cover art if available
        if cover_art_data:
            # Convert bytes to Discord File
            image_fp = BytesIO(cover_art_data)
            cover_art_file = File(image_fp, filename="cover.jpg")
            embed.set_image(url=f"attachment://{cover_art_file.filename}")
            self._now_playing_msg = await self.channel.send(
                file=cover_art_file, embed=embed
            )
        else:
            self._now_playing_msg = await self.channel.send(embed=embed)

        # Pin the message
        await discord_utils.try_set_pin(self._now_playing_msg, True)

        # Update bot nickname to show current track
        new_nick = f"{random_emoji}{track.formatted_title}"
        await self.set_bot_nickname(new_nick)

    async def unpin_now_playing(self) -> None:
        """Unpin the currently pinned now-playing message."""
        if self._now_playing_msg:
            await discord_utils.try_set_pin(self._now_playing_msg, False)
            self._now_playing_msg = None

    async def send_bust_finished(
        self, total_duration: float, completed_naturally: bool
    ) -> None:
        """Notify users that the bust session has ended."""
        guild_id = self.channel.guild.id if self.channel.guild else "unknown"

        if completed_naturally:
            logger.info(f"Bust playback completed in guild {guild_id}")
            goodbye_emoji = ":heart_on_fire:"
            embed = Embed(
                title=f"{goodbye_emoji} That's it everyone {goodbye_emoji}",
                description=(
                    "Hope ya had a good **BUST!**\n"
                    f"*Total length of all submissions: {song_utils.format_time(int(total_duration))}*"
                ),
                color=constants.LIST_EMBED_COLOR,
            )
            await self.channel.send(embed=embed)
        else:
            logger.info(f"Bust playback stopped early in guild {guild_id}")
            # Don't send a goodbye message when stopped early

    async def get_bot_nickname(self) -> str | None:
        """Get the bot's current display nickname."""
        if not self.client.user or not self.channel.guild:
            return None

        bot_member = self.channel.guild.get_member(self.client.user.id)
        return bot_member.display_name if bot_member else None

    async def set_bot_nickname(self, nickname: str | None) -> None:
        """Set the bot's display nickname."""
        if not self.client.user or not self.channel.guild:
            return

        bot_member = self.channel.guild.get_member(self.client.user.id)
        if not bot_member:
            return

        # Truncate to Discord's limit if nickname provided
        if nickname and len(nickname) > constants.NICKNAME_CHAR_LIMIT:
            nickname = nickname[: constants.NICKNAME_CHAR_LIMIT - 1] + "…"

        await bot_member.edit(nick=nickname)


class DiscordAudioPlayer:
    """Discord implementation of AudioPlayer protocol.

    Handles voice connection lifecycle and FFmpeg audio processing.
    connect() and disconnect() are implementation details, not part of
    the AudioPlayer protocol - the controller never sees them.
    """

    def __init__(self, guild_id: int, settings: BustySettings):
        self._guild_id = guild_id
        self._settings = settings
        self._voice_client: VoiceClient | None = None
        self._play_done: asyncio.Event = asyncio.Event()

    async def connect(self, voice_channel: VoiceChannel | StageChannel) -> None:
        """Connect to voice channel. Called by command layer, not controller."""
        self._voice_client = await voice_channel.connect()

        # If stage channel, ensure bot is speaking
        if voice_channel.type == ChannelType.stage_voice:
            if voice_channel.guild:
                bot_member = voice_channel.guild.me
                if bot_member:
                    await bot_member.edit(suppress=False)

    async def disconnect(self) -> None:
        """Disconnect from voice. Called by command layer, not controller."""
        if self._voice_client and self._voice_client.is_connected():
            await self._voice_client.disconnect()

    async def play(self, filepath: Path, seek_seconds: int | None = None) -> None:
        """Play audio file. Awaits until complete or stop() called."""
        if self._voice_client is None:
            raise RuntimeError("AudioPlayer not connected")

        audio_source = self._prepare_audio(filepath, seek_seconds)

        self._play_done.clear()

        def on_complete(error: Exception | None) -> None:
            if error:
                logger.error(f"Playback error: {error}")
            self._play_done.set()

        self._voice_client.play(audio_source, after=on_complete)
        await self._play_done.wait()

    def stop(self) -> None:
        """Stop current playback (causes play() to return)."""
        if self._voice_client and self._voice_client.is_playing():
            self._voice_client.stop()  # Triggers on_complete callback

    def _prepare_audio(self, filepath: Path, seek_seconds: int | None) -> AudioSource:
        """Prepare audio source, handling seek if needed."""
        # Normal playback
        if seek_seconds is None:
            return FFmpegPCMAudio(
                str(filepath),
                options=f"-filter:a volume={constants.VOLUME_MULTIPLIER}",
            )

        # Seek playback - convert to Opus at timestamp
        # Create guild-specific temp directory
        guild_temp_dir = self._settings.temp_dir / str(self._guild_id)
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
            str(filepath),
            "-ss",
            str(seek_seconds),
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
                str(filepath),
                options=f"-filter:a volume={constants.VOLUME_MULTIPLIER}",
            )
