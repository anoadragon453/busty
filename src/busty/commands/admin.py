"""Admin commands for the Discord bot."""

from discord import Embed, Interaction, TextChannel

from busty.bot import BustyBot
from busty.config import constants
from busty.decorators import guild_only, has_dj_role


def register_commands(client: BustyBot) -> None:
    """Register admin commands."""

    @client.tree.command(name="announce")
    @has_dj_role()
    @guild_only()
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
