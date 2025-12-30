"""Info and preview commands for the Discord bot."""

import random

from discord import Attachment, Embed, Interaction

from busty import discord_utils, song_utils
from busty.bot import BustyBot
from busty.config import constants
from busty.decorators import guild_only, has_dj_role
from busty.track import Track


def register_commands(client: BustyBot) -> None:
    """Register info-related commands."""

    @client.tree.command(name="info")
    @has_dj_role()
    @guild_only()
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
    @guild_only()
    async def preview(
        interaction: Interaction,
        uploaded_file: Attachment,
        submit_message: str | None = None,
    ) -> None:
        """Show a preview of a submission's 'Now Playing' embed."""
        assert interaction.guild_id is not None  # Guaranteed by @guild_only()
        await interaction.response.defer(ephemeral=True)

        if not discord_utils.is_valid_media(uploaded_file.content_type):
            await interaction.response.send_message(
                "You uploaded an invalid media file, please try again.",
                ephemeral=True,
            )
            return

        attachment_filepath = discord_utils.build_filepath_for_attachment(
            client.settings.attachment_cache_dir,
            interaction.guild_id,
            uploaded_file,
        )

        # Save attachment to disk for processing
        await uploaded_file.save(fp=attachment_filepath)
        random_emoji = random.choice(client.settings.emoji_list)

        # Create a temporary Track for preview
        preview_track = Track(
            local_filepath=attachment_filepath,
            attachment_filename=uploaded_file.filename,
            submitter_id=interaction.user.id,
            submitter_name=interaction.user.display_name,
            message_content=submit_message,
            message_jump_url=constants.PREVIEW_JUMP_URL,
            attachment_url=uploaded_file.url,
            duration=song_utils.get_song_length(attachment_filepath),
        )

        embed = song_utils.embed_song(preview_track, random_emoji)

        cover_art = song_utils.get_cover_art(attachment_filepath)

        if cover_art is not None:
            embed.set_image(url=f"attachment://{cover_art.filename}")
            await interaction.response.send_message(
                file=cover_art, embed=embed, ephemeral=True
            )

        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)

        # Delete the attachment from disk after processing
        attachment_filepath.unlink()
