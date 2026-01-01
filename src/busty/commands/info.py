"""Info and preview commands for the Discord bot."""

import random

from discord import Attachment, Embed, Interaction, app_commands

from busty import discord_utils, song_utils
from busty.bot import BustyBot
from busty.config import constants
from busty.decorators import has_dj_role
from busty.track import Track


def register_commands(client: BustyBot) -> None:
    """Register info-related commands."""

    @client.tree.command(name="info")
    @has_dj_role()
    @app_commands.guild_only()
    async def info(interaction: Interaction) -> None:
        """Get info about currently listed songs."""
        assert interaction.guild_id is not None  # Guaranteed by @guild_only()
        bc = client.bust_registry.get(interaction.guild_id)

        if bc is None:
            await interaction.response.send_message(
                "You need to use /list first.", ephemeral=True
            )
            return

        await interaction.response.defer()

        # Get statistics from controller
        stats = bc.get_stats()

        # Format submitter statistics
        longest_submitters = [
            f"{i + 1}. <@{stat.user_id}> - {song_utils.format_time(int(stat.total_duration))}"
            for i, stat in enumerate(
                stats.submitter_stats[: client.settings.num_longest_submitters]
            )
        ]

        # Build embed text
        embed_text = "\n".join(
            [
                f"*Number of tracks:* {stats.num_tracks}",
                f"*Total track length:* {song_utils.format_time(int(stats.total_duration))}",
                f"*Total bust length:* {song_utils.format_time(int(stats.total_bust_time))}",
                f"*Unique submitters:* {len(stats.submitter_stats)}",
                "*Longest submitters:*",
            ]
            + longest_submitters
        )

        if stats.has_errors:
            embed_text += (
                "\n\n**There were some errors. Statistics may be inaccurate.**"
            )

        embed = Embed(
            title="Listed Statistics",
            description=embed_text,
            color=constants.INFO_EMBED_COLOR,
        )
        await interaction.followup.send(embed=embed)

    @client.tree.command(name="preview")
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def preview(
        interaction: Interaction,
        uploaded_file: Attachment,
        submit_message: str | None = None,
    ) -> None:
        """Show a preview of a submission's 'Now Playing' embed."""
        await interaction.response.defer(ephemeral=True)

        if not discord_utils.is_valid_media(uploaded_file.content_type):
            await interaction.response.send_message(
                "You uploaded an invalid media file, please try again.",
                ephemeral=True,
            )
            return

        # Use guild_id if in guild, otherwise use user_id for DM preview cache
        cache_id = interaction.guild_id if interaction.guild_id is not None else interaction.user.id
        attachment_filepath = discord_utils.build_filepath_for_attachment(
            client.settings.attachment_cache_dir,
            cache_id,
            uploaded_file,
        )

        # Save attachment to disk for processing
        await uploaded_file.save(fp=attachment_filepath)

        # Create Track
        preview_track = Track.from_attachment(
            attachment_filepath,
            uploaded_file,
            interaction.user.id,
            interaction.user.display_name,
            submit_message,
            constants.PREVIEW_JUMP_URL,
        )

        # Get cover art
        cover_art_bytes = song_utils.get_cover_art_bytes(attachment_filepath)

        # Send preview using new utility function
        random_emoji = random.choice(client.settings.emoji_list)
        # interaction.followup is a Webhook which implements Messageable protocol
        await song_utils.send_track_embed_with_cover_art(
            interaction.followup,  # type: ignore[arg-type]
            preview_track,
            random_emoji,
            cover_art_bytes,
        )

        # Delete the attachment from disk after processing
        attachment_filepath.unlink()
