"""Bust-related commands for the Discord bot."""

import logging

from discord import (
    ClientException,
    Interaction,
    StageChannel,
    TextChannel,
    VoiceChannel,
)

from busty import bust, song_utils
from busty.bot import BustyBot
from busty.bust.discord_impl import DiscordAudioPlayer
from busty.decorators import guild_only, has_dj_role, text_channel_only

logger = logging.getLogger(__name__)


def register_commands(client: BustyBot) -> None:
    """Register bust-related commands."""

    @client.tree.command(name="list")
    @has_dj_role()
    @guild_only()
    async def on_list(
        interaction: Interaction, list_channel: TextChannel | None = None
    ) -> None:
        """Download and list all media sent in a chosen text channel."""
        assert interaction.guild_id is not None  # Guaranteed by @guild_only
        bc = client.bust_registry.get(interaction.guild_id)
        if bc and bc.is_playing:
            await interaction.response.send_message(
                "We're busy busting.", ephemeral=True
            )
            return

        list_lock = client.bust_registry.get_list_lock(interaction.guild_id)
        if list_lock.locked():
            await interaction.response.send_message(
                "A list is already in progress.", ephemeral=True
            )
            return
        if list_channel is None:
            if not isinstance(interaction.channel, TextChannel):
                await interaction.response.send_message(
                    "This command can only be used in a text channel.", ephemeral=True
                )
                return
            list_channel = interaction.channel

        logger.info(
            f"User {interaction.user} issued /list command in guild {interaction.guild_id}, channel {list_channel.name}"
        )
        async with list_lock:
            bc = await bust.list_bust(
                client, client.settings, interaction, list_channel
            )
            if bc is not None:
                client.bust_registry.register(interaction.guild_id, bc)

    @client.tree.command(name="bust")
    @has_dj_role()
    @text_channel_only()
    @guild_only()
    async def on_bust(interaction: Interaction, index: int = 1) -> None:
        """Begin a bust."""
        # Type narrowing assertions (guaranteed by decorators)
        assert isinstance(interaction.channel, TextChannel)
        assert interaction.guild is not None

        await interaction.response.defer(ephemeral=True)

        # Get controller
        bc = client.bust_registry.get(interaction.guild.id)
        if bc is None:
            await interaction.followup.send(
                "You need to use `/list` first.", ephemeral=True
            )
            return
        elif bc.is_playing:
            await interaction.followup.send("We're already busting.", ephemeral=True)
            return
        if index > len(bc.tracks):
            await interaction.followup.send(
                "There aren't that many tracks.", ephemeral=True
            )
            return

        # Find user's voice channel
        voice_channels: list[VoiceChannel | StageChannel] = list(
            interaction.guild.voice_channels
        )
        voice_channels.extend(interaction.guild.stage_channels)

        target_channel = None
        for voice_channel in voice_channels:
            if interaction.user in voice_channel.members:
                target_channel = voice_channel
                break

        if target_channel is None:
            await interaction.followup.send(
                "You need to be in an active voice channel.", ephemeral=True
            )
            return

        logger.info(
            f"User {interaction.user} issued /bust command in guild {interaction.guild.id}, starting at track {index}"
        )

        # Create and connect audio player
        audio_player = DiscordAudioPlayer(interaction.guild.id, client.settings)
        try:
            await audio_player.connect(target_channel)
            await interaction.delete_original_response()

            await bc.play(audio_player, index - 1)
        except ClientException as e:
            logger.error(f"Failed to connect to voice channel: {e}")
            await interaction.followup.send(
                "Failed to connect to voice channel.", ephemeral=True
            )
        finally:
            await audio_player.disconnect()
        # Registry auto-cleans finished controllers

    @client.tree.command(name="skip")
    @has_dj_role()
    @guild_only()
    async def skip(interaction: Interaction) -> None:
        """Skip currently playing song."""
        assert interaction.guild_id is not None  # Guaranteed by @guild_only
        bc = client.bust_registry.get(interaction.guild_id)

        if not bc or not bc.is_playing:
            await interaction.response.send_message(
                "Nothing is playing.", ephemeral=True
            )
            return

        logger.info(
            f"User {interaction.user} issued /skip command in guild {interaction.guild_id}"
        )
        await interaction.response.send_message("I didn't like that track anyways.")
        # Skip to next track
        bc.skip_next()

    @client.tree.command(name="seek")
    @has_dj_role()
    @guild_only()
    async def seek(
        interaction: Interaction,
        timestamp: str | None = None,
    ) -> None:
        """Seek to time in the currently playing song."""
        assert interaction.guild_id is not None  # Guaranteed by @guild_only
        # Get seek offset
        seek_to_seconds = song_utils.convert_timestamp_to_seconds(timestamp)
        if seek_to_seconds is None:
            await interaction.response.send_message(
                "Invalid seek time.", ephemeral=True
            )
            return

        bc = client.bust_registry.get(interaction.guild_id)

        if not bc or not bc.is_playing:
            await interaction.response.send_message(
                "Nothing is playing.", ephemeral=True
            )
            return

        logger.info(
            f"User {interaction.user} issued /seek command in guild {interaction.guild_id}, timestamp {seek_to_seconds}s"
        )
        await interaction.response.send_message("Let's skip to the good part.")
        bc.seek(seek_to_seconds)

    @client.tree.command(name="replay")
    @has_dj_role()
    @guild_only()
    async def replay(interaction: Interaction) -> None:
        """Replay currently playing song from the beginning."""
        assert interaction.guild_id is not None  # Guaranteed by @guild_only
        bc = client.bust_registry.get(interaction.guild_id)

        if not bc or not bc.is_playing:
            await interaction.response.send_message(
                "Nothing is playing.", ephemeral=True
            )
            return

        logger.info(
            f"User {interaction.user} issued /replay command in guild {interaction.guild_id}"
        )
        await interaction.response.send_message("Replaying this track.")
        bc.replay()

    @client.tree.command(name="stop")
    @has_dj_role()
    @guild_only()
    async def stop(interaction: Interaction) -> None:
        """Stop playback."""
        assert interaction.guild_id is not None  # Guaranteed by @guild_only
        bc = client.bust_registry.get(interaction.guild_id)

        if not bc or not bc.is_playing:
            await interaction.response.send_message(
                "Nothing is playing.", ephemeral=True
            )
            return

        logger.info(
            f"User {interaction.user} issued /stop command in guild {interaction.guild_id}"
        )
        await interaction.response.send_message("Alright I'll shut up.")
        bc.stop()
