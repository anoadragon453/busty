"""Admin commands for the Discord bot."""

from discord import Embed, Interaction, TextChannel, app_commands

from busty.bot import BustyBot
from busty.config import constants


def register_commands(client: BustyBot) -> None:
    """Register admin commands."""

    @client.tree.command(name="announce")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def announce(
        interaction: Interaction,
        title: str,
        body: str,
        channel: TextChannel | None = None,
    ) -> None:
        """Send a message as the bot into a channel wrapped in an embed."""
        assert interaction.guild_id is not None  # Guaranteed by @guild_only()
        await interaction.response.defer(ephemeral=True)
        if channel is None:
            if not isinstance(interaction.channel, TextChannel):
                await interaction.response.send_message(
                    "This command can only be used in a text channel.", ephemeral=True
                )
                return
            channel = interaction.channel

        # Build the announcement embed
        embed = Embed(
            title=title,
            description=body,
            color=constants.INFO_EMBED_COLOR,
        )

        # Disallow sending announcements from one guild into another.
        if channel.guild.id != interaction.guild_id:
            await interaction.response.send_message(
                "Sending announcements to a guild outside of this channel is not allowed.",
                ephemeral=True,
            )
            return

        await channel.send(embed=embed)

        if channel.id == interaction.channel_id:
            interaction_reply = "Announcement has been sent."
        else:
            interaction_reply = f"Announcement has been sent in {channel.mention}."
        await interaction.response.send_message(interaction_reply, ephemeral=True)

    @client.tree.command(name="say")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def say(
        interaction: Interaction,
        message: str,
        channel: TextChannel | None = None,
    ) -> None:
        """Send a message as the bot into a channel."""
        assert interaction.guild_id is not None  # Guaranteed by @guild_only()
        await interaction.response.defer(ephemeral=True)
        if channel is None:
            if not isinstance(interaction.channel, TextChannel):
                await interaction.followup.send(
                    "This command can only be used in a text channel.", ephemeral=True
                )
                return
            channel = interaction.channel

        # Disallow sending messages from one guild into another.
        if channel.guild.id != interaction.guild_id:
            await interaction.followup.send(
                "Sending messages to a guild outside of this channel is not allowed.",
                ephemeral=True,
            )
            return

        await channel.send(message)

        if channel.id == interaction.channel_id:
            interaction_reply = "Message has been sent."
        else:
            interaction_reply = f"Message has been sent in {channel.mention}."
        await interaction.followup.send(interaction_reply, ephemeral=True)
