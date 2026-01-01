"""Image management commands for the Discord bot."""

from typing import cast

import discord
from discord import app_commands

from busty.bot import BustyBot


class ImageGroup(app_commands.Group):
    """Command group for managing Google Forms images."""

    def __init__(self) -> None:
        super().__init__(
            name="image",
            description="Manage saved Google Forms image.",
            allowed_contexts=app_commands.AppCommandContext(
                guilds=True, dms=False, private_channels=False
            ),
        )

    @app_commands.command(
        name="upload", description="Upload a Google Forms image as attachment."
    )
    async def upload(
        self, interaction: discord.Interaction, image_file: discord.Attachment
    ) -> None:
        assert interaction.guild_id is not None  # Guaranteed by @guild_only()
        # TODO: Some basic validity filtering
        # Persist the image URL
        bot = cast(BustyBot, interaction.client)
        try:
            bot.persistent_state.save_form_image_url(
                interaction.guild_id, image_file.url
            )
        except Exception as e:
            await interaction.response.send_message(
                f"Failed to upload image: ({e}).",
                ephemeral=True,
            )
            return

        # No period so image preview shows
        await interaction.response.send_message(
            f":white_check_mark: Image set to {image_file.url}"
        )

    @app_commands.command(
        name="url", description="Set a Google Forms image by pasting a URL."
    )
    async def url(self, interaction: discord.Interaction, image_url: str) -> None:
        assert interaction.guild_id is not None  # Guaranteed by @guild_only()
        # TODO: Some basic validity filtering

        # Persist the image URL
        bot = cast(BustyBot, interaction.client)
        try:
            bot.persistent_state.save_form_image_url(interaction.guild_id, image_url)
        except Exception as e:
            await interaction.response.send_message(
                f"Failed to save image URL: {e}",
                ephemeral=True,
            )
            return

        # No period so image preview shows
        await interaction.response.send_message(
            f":white_check_mark: Image set to {image_url}"
        )

    @app_commands.command(
        name="clear", description="Clear the loaded Google Forms image."
    )
    async def clear(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None  # Guaranteed by @guild_only()
        bot = cast(BustyBot, interaction.client)
        image_existed = bot.persistent_state.clear_form_image_url(interaction.guild_id)
        if not image_existed:
            await interaction.response.send_message(
                "No image is loaded.", ephemeral=True
            )
            return

        await interaction.response.send_message(":wastebasket: Image cleared.")

    @app_commands.command(
        name="view", description="View the loaded Google Forms image."
    )
    async def view(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None  # Guaranteed by @guild_only()
        bot = cast(BustyBot, interaction.client)
        loaded_image_url = bot.persistent_state.get_form_image_url(interaction.guild_id)
        if loaded_image_url is None:
            await interaction.response.send_message(
                "No image is currently loaded.", ephemeral=True
            )
            return

        # No period so image preview shows
        await interaction.response.send_message(
            f"The loaded image is {loaded_image_url}"
        )


def register_commands(client: BustyBot) -> None:
    """Register image-related commands."""
    client.tree.add_command(ImageGroup())
