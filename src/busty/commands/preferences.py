"""User preference commands for the Discord bot."""

import discord
from discord import Interaction

from busty.bot import BustyBot
from busty.decorators import guild_only


def register_commands(client: BustyBot) -> None:
    """Register preference-related commands."""

    # Create a group for preferences
    preferences_group = discord.app_commands.Group(
        name="preferences",
        description="Manage your personal Busty preferences",
    )

    @preferences_group.command(name="ai-art")
    @guild_only()
    async def ai_art(
        interaction: Interaction,
        enabled: bool,
    ) -> None:
        """Enable or disable AI-generated album art for your submissions.

        Args:
            enabled: True to enable AI art generation, False to disable.
        """
        assert interaction.guild_id is not None  # Guaranteed by @guild_only()

        user_id = interaction.user.id
        guild_id = interaction.guild_id

        # Update the user's preference for this guild
        client.persistent_state.set_ai_art_enabled(guild_id, user_id, enabled)

        # Send confirmation
        status = "enabled" if enabled else "disabled"
        await interaction.response.send_message(
            f"AI-generated album art has been **{status}** for your submissions in this server.",
            ephemeral=True,
        )

    @preferences_group.command(name="mailbox-preview")
    @guild_only()
    async def mailbox_preview(
        interaction: Interaction,
        enabled: bool,
    ) -> None:
        """Enable or disable automatic preview DMs when posting in mailbox channels.

        Args:
            enabled: True to enable preview DMs, False to disable.
        """
        assert interaction.guild_id is not None  # Guaranteed by @guild_only()

        user_id = interaction.user.id
        guild_id = interaction.guild_id

        # Update the user's preference for this guild
        client.persistent_state.set_mailbox_preview_enabled(guild_id, user_id, enabled)

        # Send confirmation
        status = "enabled" if enabled else "disabled"
        await interaction.response.send_message(
            f"Mailbox preview DMs have been **{status}** for this server.",
            ephemeral=True,
        )

    # Add the group to the command tree
    client.tree.add_command(preferences_group)
