import asyncio
import logging
import os
import random
import sys
from typing import Optional

import discord
from discord import (
    Attachment,
    Embed,
    Intents,
    Interaction,
    Message,
    TextChannel,
    app_commands,
)
from discord.ext import commands
from discord.ext.commands import has_role

from busty import bust, config, discord_utils, llm, persistent_state, song_utils


def setup_logging(log_level):
    logger = logging.getLogger("discord")
    logger.setLevel(log_level)
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s:%(levelname)s:%(name)s: %(message)s")
    )
    logger.addHandler(handler)


setup_logging(logging.INFO)

# Get logger for this module
logger = logging.getLogger(__name__)

# This is necessary to query guild members
intents = Intents.default()
intents.members = True
intents.message_content = True

if config.testing_guild:
    logger.info(f"Using testing guild {config.testing_guild}")
    ids = [int(config.testing_guild)]
client = commands.Bot(intents=intents, command_prefix="!")


@client.event
async def on_ready() -> None:
    logger.info(f"We have logged in as {client.user}.")
    if config.openai_api_key:
        llm.initialize(client)
    try:
        synced = await client.tree.sync()
        logger.info(f"Synced {len(synced)} command(s)")
    except Exception as e:
        logger.error(f"Failed to sync commands: {e}")


@client.event
async def on_message(message: Message) -> None:
    if (
        config.openai_api_key
        and message.guild
        and (
            client.user in message.mentions
            or any(role.name == client.user.name for role in message.role_mentions)
            or random.random() < config.RESPOND_TO_MESSAGE_PROBABILITY
        )
        and message.author != client.user
    ):
        await llm.respond(message)


list_task_control_lock = asyncio.Lock()


# List command
@client.tree.command(name="list")
@has_role(config.dj_role_name)
async def on_list(
    interaction: Interaction, list_channel: Optional[TextChannel] = None
) -> None:
    """Download and list all media sent in a chosen text channel."""
    bc = bust.controllers.get(interaction.guild_id)
    if bc and bc.is_active():
        await interaction.response.send_message("We're busy busting.", ephemeral=True)
        return
    if list_task_control_lock.locked():
        await interaction.response.send_message(
            "A list is already in progress.", ephemeral=True
        )
        return
    if list_channel is None:
        list_channel = interaction.channel
    async with list_task_control_lock:
        bc = await bust.create_controller(client, interaction, list_channel)
        if bc is not None:
            bust.controllers[interaction.guild_id] = bc


# Bust command
@client.tree.command(name="bust")
@has_role(config.dj_role_name)
async def on_bust(interaction: Interaction, index: int = 1) -> None:
    """Begin a bust."""
    bc = bust.controllers.get(interaction.guild_id)
    if bc is None:
        await interaction.response.send_message(
            "You need to use `/list` first.", ephemeral=True
        )
        return
    elif bc.is_active():
        await interaction.response.send_message(
            "We're already busting.", ephemeral=True
        )
        return
    if index > len(bc.bust_content):
        await interaction.response.send_message(
            "There aren't that many tracks.", ephemeral=True
        )
        return
    await bc.play(interaction, index - 1)
    del bust.controllers[interaction.guild_id]


# Skip command
@client.tree.command(name="skip")
@has_role(config.dj_role_name)
async def skip(interaction: Interaction) -> None:
    """Skip currently playing song."""
    bc = bust.controllers.get(interaction.guild_id)

    if not bc or not bc.is_active():
        await interaction.response.send_message("Nothing is playing.", ephemeral=True)
        return

    await interaction.response.send_message("I didn't like that track anyways.")
    if bc._playing_index is not None:
        bc.skip_to_track(bc._playing_index + 1)


# Seek command
@client.tree.command(name="seek")
@has_role(config.dj_role_name)
async def seek(
    interaction: Interaction,
    timestamp: Optional[str] = None,
) -> None:
    """Seek to time in the currently playing song."""
    # Get seek offset
    seek_to_seconds = song_utils.convert_timestamp_to_seconds(timestamp)
    if seek_to_seconds is None:
        await interaction.response.send_message("Invalid seek time.", ephemeral=True)
        return

    bc = bust.controllers.get(interaction.guild_id)

    if not bc or not bc.is_active():
        await interaction.response.send_message("Nothing is playing.", ephemeral=True)
        return

    if bc.is_seeking():
        await interaction.response.send_message(
            "Still seeking, chill a sec.", ephemeral=True
        )
        return

    await interaction.response.send_message("Let's skip to the good part.")
    bc.seek_current_track(interaction, seek_to_seconds)


# Replay command
@client.tree.command(name="replay")
@has_role(config.dj_role_name)
async def replay(interaction: Interaction) -> None:
    """Replay currently playing song from the beginning."""
    bc = bust.controllers.get(interaction.guild_id)

    if not bc or not bc.is_active():
        await interaction.response.send_message("Nothing is playing.", ephemeral=True)
        return

    await interaction.response.send_message("Replaying this track.")
    if bc._playing_index is not None:
        bc.skip_to_track(bc._playing_index)


# Stop command
@client.tree.command(name="stop")
@has_role(config.dj_role_name)
async def stop(interaction: Interaction) -> None:
    """Stop playback."""
    bc = bust.controllers.get(interaction.guild_id)

    if not bc or not bc.is_active():
        await interaction.response.send_message("Nothing is playing.", ephemeral=True)
        return

    await interaction.response.send_message("Alright I'll shut up.")
    bc.stop()


class ImageGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="image", description="Manage saved Google Forms image.")

    @app_commands.command(
        name="upload", description="Upload a Google Forms image as attachment."
    )
    async def upload(
        self, interaction: discord.Interaction, image_file: discord.Attachment
    ):
        # TODO: Some basic validity filtering
        # Persist the image URL
        if not await persistent_state.save_form_image_url(interaction, image_file.url):
            return

        # No period so image preview shows
        await interaction.response.send_message(
            f":white_check_mark: Image set to {image_file.url}"
        )

    @app_commands.command(
        name="url", description="Set a Google Forms image by pasting a URL."
    )
    async def url(self, interaction: discord.Interaction, image_url: str):
        # TODO: Some basic validity filtering
        # Persist the image URL
        if not await persistent_state.save_form_image_url(interaction, image_url):
            return

        # No period so image preview shows
        await interaction.response.send_message(
            f":white_check_mark: Image set to {image_url}"
        )

    @app_commands.command(
        name="clear", description="Clear the loaded Google Forms image."
    )
    async def clear(self, interaction: discord.Interaction):
        image_existed = persistent_state.clear_form_image_url(interaction)
        if not image_existed:
            await interaction.response.send_message(
                "No image is loaded.", ephemeral=True
            )
            return

        await interaction.response.send_message(":wastebasket: Image cleared.")

    @app_commands.command(
        name="view", description="View the loaded Google Forms image."
    )
    async def view(self, interaction: discord.Interaction):
        loaded_image_url = persistent_state.get_form_image_url(interaction)
        if loaded_image_url is None:
            await interaction.response.send_message(
                "No image is currently loaded.", ephemeral=True
            )
            return

        # No period so image preview shows
        await interaction.response.send_message(
            f"The loaded image is {loaded_image_url}"
        )


client.tree.add_command(ImageGroup())


# Info command
@client.tree.command(name="info")
@has_role(config.dj_role_name)
async def info(interaction: Interaction) -> None:
    """Get info about currently listed songs."""
    bc = bust.controllers.get(interaction.guild_id)

    if bc is None:
        await interaction.response.send_message(
            "You need to use /list first.", ephemeral=True
        )
        return

    await bc.send_stats(interaction)


# Preview command
@client.tree.command(name="preview")
async def preview(
    interaction: Interaction,
    uploaded_file: Attachment,
    submit_message: Optional[str] = None,
) -> None:
    """Show a preview of a submission's 'Now Playing' embed."""
    await interaction.response.defer(ephemeral=True)

    if not discord_utils.is_valid_media(uploaded_file.content_type):
        await interaction.response.send_message(
            "You uploaded an invalid media file, please try again.",
            ephemeral=True,
        )
        return

    attachment_filepath = discord_utils.build_filepath_for_attachment(
        interaction.guild_id, uploaded_file
    )

    # Save attachment to disk for processing
    await uploaded_file.save(fp=attachment_filepath)
    random_emoji = random.choice(config.emoji_list)

    embed = song_utils.embed_song(
        submit_message or "",
        attachment_filepath,
        uploaded_file,
        interaction.user,
        random_emoji,
        config.PREVIEW_JUMP_URL,
    )

    cover_art = song_utils.get_cover_art(attachment_filepath)

    if cover_art is not None:
        embed.set_image(url=f"attachment://{cover_art.filename}")
        await interaction.response.send_message(
            file=cover_art, embed=embed, ephemeral=True
        )

    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # Delete the attachment from disk after processing
    os.remove(attachment_filepath)


@client.tree.command(name="announce")
@has_role(config.dj_role_name)
async def announce(
    interaction: Interaction,
    title: str,
    body: str,
    channel: Optional[TextChannel] = None,
) -> None:
    """Send a message as the bot into a channel wrapped in an embed."""
    await interaction.response.defer(ephemeral=True)
    if channel is None:
        channel = interaction.channel

    # Build the announcement embed
    embed = Embed(
        title=title,
        description=body,
        color=config.INFO_EMBED_COLOR,
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


@client.event
async def on_application_command_error(
    interaction: Interaction, error: Exception
) -> None:
    # Catch insufficient permissions exception, ignore all others
    if isinstance(error, has_role.errors.ApplicationMissingRole):
        await interaction.response.send_message(
            "You don't have permission to use this command.", ephemeral=True
        )
    else:
        logger.error(error)


def run_bot():
    """Entry point for the busty script."""
    # Load the bot state.
    persistent_state.load_state_from_disk()

    # Connect to discord
    if config.discord_token:
        client.run(config.discord_token)
    else:
        logger.error(
            "Please pass in a Discord bot token via the BUSTY_DISCORD_TOKEN environment variable."
        )


if __name__ == "__main__":
    run_bot()
