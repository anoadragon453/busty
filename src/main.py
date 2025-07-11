import asyncio
import logging
import os
import random
import sys
from typing import Optional

from nextcord import (
    Attachment,
    Embed,
    Intents,
    Interaction,
    InteractionContextType,
    Message,
    SlashOption,
    TextChannel,
)
from nextcord.ext import application_checks, commands

import bust
import config
import discord_utils
import llm
import persistent_state
import song_utils


def setup_logging(log_level):
    logger = logging.getLogger("nextcord")
    logger.setLevel(log_level)
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s:%(levelname)s:%(name)s: %(message)s")
    )
    logger.addHandler(handler)


setup_logging(logging.INFO)

# This is necessary to query guild members
intents = Intents.default()
# To fetch guild member information.
# Privileged intent. Requires enabling in Discord Developer Portal.
intents.members = True
# To be able to read message content.
intents.message_content = True

# Set up the Discord client. Connecting to Discord is done at
# the bottom of this file.
if config.testing_guild:
    print(f"Using testing guild {config.testing_guild}")
    ids = [int(config.testing_guild)]
    client = commands.Bot(intents=intents, default_guild_ids=ids)
else:
    client = commands.Bot(intents=intents)


@client.event
async def on_ready() -> None:
    print(f"We have logged in as {client.user}.")
    if config.openai_api_key:
        llm.initialize(client)


@client.event
async def on_close() -> None:
    # Finish all running busts on close
    for bc in bust.controllers.values():
        await bc.finish(say_goodbye=False)


@client.event
async def on_message(message: Message) -> None:
    if (
        config.openai_api_key
        # Ignore DMs to the bot.
        and message.guild
        and (
            client.user in message.mentions
            # For the case where a user accidentally mentions the bot's role
            # instead of their nick (which are typically named the same).
            or any(role.name == client.user.name for role in message.role_mentions)
            # Randomly respond to some messages, even if the bot is not mentioned.
            or random.random() < 1 / 150
        )
        and message.author != client.user
    ):
        await llm.respond(message)


# Allow only one async routine to calculate list at a time
list_task_control_lock = asyncio.Lock()


# List command
@client.slash_command(name="list", contexts=[InteractionContextType.guild])
@application_checks.has_role(config.dj_role_name)
async def on_list(
    interaction: Interaction,
    list_channel: Optional[TextChannel] = SlashOption(
        required=False, description="Target channel to list."
    ),
) -> None:
    """Download and list all media sent in a chosen text channel."""
    bc = bust.controllers.get(interaction.guild_id)

    if bc and bc.is_active():
        await interaction.send("We're busy busting.", ephemeral=True)
        return

    # Give up if locked
    if list_task_control_lock.locked():
        await interaction.send("A list is already in progress.", ephemeral=True)
        return

    if list_channel is None:
        list_channel = interaction.channel

    async with list_task_control_lock:
        bc = await bust.create_controller(client, interaction, list_channel)
        bust.controllers[interaction.guild_id] = bc


# Bust command
@client.slash_command(name="bust", contexts=[InteractionContextType.guild])
@application_checks.has_role(config.dj_role_name)
async def on_bust(
    interaction: Interaction,
    index: int = SlashOption(
        required=False,
        min_value=1,
        default=1,
        description="Track number to start from.",
    ),
) -> None:
    """Begin a bust."""
    bc = bust.controllers.get(interaction.guild_id)

    if bc is None:
        await interaction.send("You need to use `/list` first.", ephemeral=True)
        return

    elif bc.is_active():
        await interaction.send("We're already busting.", ephemeral=True)
        return

    if index > len(bc.bust_content):
        await interaction.send("There aren't that many tracks.", ephemeral=True)
        return
    await bc.play(interaction, index - 1)
    del bust.controllers[interaction.guild_id]


# Skip command
@client.slash_command(contexts=[InteractionContextType.guild])
@application_checks.has_role(config.dj_role_name)
async def skip(interaction: Interaction) -> None:
    """Skip currently playing song."""
    bc = bust.controllers.get(interaction.guild_id)

    if not bc or not bc.is_active():
        await interaction.send("Nothing is playing.", ephemeral=True)
        return

    await interaction.send("I didn't like that track anyways.")
    bc.skip_to_track(bc.playing_index + 1)


# Seek command
@client.slash_command(name="seek", contexts=[InteractionContextType.guild])
@application_checks.has_role(config.dj_role_name)
async def seek(
    interaction: Interaction,
    timestamp: str = SlashOption(
        required=True,
        default="",
        description="Timestamp to seek song with.",
    ),
) -> None:
    """Seek to time in currently playing song."""
    # Get seek offset
    seek_to_seconds = song_utils.convert_timestamp_to_seconds(timestamp)
    if seek_to_seconds is None:
        await interaction.send("Invalid seek time.", ephemeral=True)
        return

    bc = bust.controllers.get(interaction.guild_id)

    if not bc or not bc.is_active():
        await interaction.send("Nothing is playing.", ephemeral=True)
        return

    if bc.is_seeking():
        await interaction.send("Still seeking, chill a sec.", ephemeral=True)
        return

    await interaction.send("Let's skip to the good part.")
    bc.seek_current_track(interaction, seek_to_seconds)


# Replay command
@client.slash_command(contexts=[InteractionContextType.guild])
@application_checks.has_role(config.dj_role_name)
async def replay(interaction: Interaction) -> None:
    """Replay currently playing song from the beginning."""
    bc = bust.controllers.get(interaction.guild_id)

    if not bc or not bc.is_active():
        await interaction.send("Nothing is playing.", ephemeral=True)
        return

    await interaction.send("Replaying this track.")
    bc.skip_to_track(bc.playing_index)


# Stop command
@client.slash_command(contexts=[InteractionContextType.guild])
@application_checks.has_role(config.dj_role_name)
async def stop(interaction: Interaction) -> None:
    """Stop playback."""
    bc = bust.controllers.get(interaction.guild_id)

    if not bc or not bc.is_active():
        await interaction.send("Nothing is playing.", ephemeral=True)
        return

    await interaction.send("Alright I'll shut up.")
    bc.stop()


# Image command
@client.slash_command(contexts=[InteractionContextType.guild])
@application_checks.has_role(config.dj_role_name)
async def image(interaction: Interaction) -> None:
    """Manage saved Google Forms image."""
    pass


@image.subcommand(name="upload")
@application_checks.has_role(config.dj_role_name)
async def image_upload(interaction: Interaction, image_file: Attachment) -> None:
    """Upload a Google Forms image as attachment."""
    # TODO: Some basic validity filtering
    # Persist the image URL
    if not await persistent_state.save_form_image_url(interaction, image_file.url):
        return

    # No period so image preview shows
    await interaction.send(f":white_check_mark: Image set to {image_file.url}")


@image.subcommand(name="url")
@application_checks.has_role(config.dj_role_name)
async def image_by_url(interaction: Interaction, image_url: str) -> None:
    """Set a Google Forms image by pasting a URL."""
    # TODO: Some basic validity filtering
    # Persist the image URL
    if not await persistent_state.save_form_image_url(interaction, image_url):
        return

    # No period so image preview shows
    await interaction.send(f":white_check_mark: Image set to {image_url}")


@image.subcommand(name="clear")
@application_checks.has_role(config.dj_role_name)
async def image_clear(interaction: Interaction) -> None:
    """Clear the loaded Google Forms image."""
    image_existed = persistent_state.clear_form_image_url(interaction)
    if not image_existed:
        await interaction.send("No image is loaded.", ephemeral=True)
        return

    await interaction.send(":wastebasket: Image cleared.")


@image.subcommand(name="view")
@application_checks.has_role(config.dj_role_name)
async def image_view(interaction: Interaction) -> None:
    """View the loaded Google Forms image."""
    loaded_image_url = persistent_state.get_form_image_url(interaction)
    if loaded_image_url is None:
        await interaction.send("No image is currently loaded.", ephemeral=True)
        return

    # No period so image preview shows
    await interaction.send(f"The loaded image is {loaded_image_url}")


# Info command
@client.slash_command(contexts=[InteractionContextType.guild])
@application_checks.has_role(config.dj_role_name)
async def info(interaction: Interaction) -> None:
    """Get info about currently listed songs."""
    bc = bust.controllers.get(interaction.guild_id)

    if bc is None:
        await interaction.send("You need to use /list first.", ephemeral=True)
        return

    await bc.send_stats(interaction)


# Preview command
@client.slash_command(contexts=[InteractionContextType.guild])
async def preview(
    interaction: Interaction,
    uploaded_file: Attachment = SlashOption(description="The song to submit."),
    submit_message: Optional[str] = SlashOption(
        required=False, description="The submission message text."
    ),
) -> None:
    """Show a preview of a submission's "Now Playing" embed."""
    await interaction.response.defer(ephemeral=True)

    if not discord_utils.is_valid_media(uploaded_file.content_type):
        await interaction.send(
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
        submit_message,
        attachment_filepath,
        uploaded_file,
        interaction.user,
        random_emoji,
        config.PREVIEW_JUMP_URL,
    )

    cover_art = song_utils.get_cover_art(attachment_filepath)

    if cover_art is not None:
        embed.set_image(url=f"attachment://{cover_art.filename}")
        await interaction.send(file=cover_art, embed=embed, ephemeral=True)

    else:
        await interaction.send(embed=embed, ephemeral=True)

    # Delete the attachment from disk after processing
    os.remove(attachment_filepath)


@client.slash_command(contexts=[InteractionContextType.guild])
@application_checks.has_role(config.dj_role_name)
async def announce(
    interaction: Interaction,
    title: str = SlashOption(description="The title of the announcement."),
    body: str = SlashOption(description="The text of the announcement."),
    channel: Optional[TextChannel] = SlashOption(
        required=False, description="Target channel to send message in."
    ),
) -> None:
    """Send a message as the bot into a channel wrapped in an embed."""
    await interaction.response.defer(ephemeral=True)
    if channel is None:
        # Default to the current channel that the command was invoked in.
        channel = interaction.channel

    # Build the announcement embed
    embed = Embed(
        title=title,
        description=body,
        color=config.INFO_EMBED_COLOR,
    )

    # Disallow sending announcements from one guild into another.
    if channel.guild.id != interaction.guild_id:
        await interaction.send(
            "Sending announcements to a guild outside of this channel is not allowed.",
            ephemeral=True,
        )
        return

    await channel.send(embed=embed)
    # Change reply to interaction depending on whether message was sent in current channel, or one in argument
    if channel.id == interaction.channel_id:
        interaction_reply = "Announcement has been sent."
    else:
        interaction_reply = f"Announcement has been sent in {channel.mention}."
    await interaction.send(interaction_reply, ephemeral=True)


@client.event
async def on_application_command_error(
    interaction: Interaction, error: Exception
) -> None:
    # Catch insufficient permissions exception, ignore all others
    if isinstance(error, application_checks.errors.ApplicationMissingRole):
        await interaction.send(
            "You don't have permission to use this command.", ephemeral=True
        )
    else:
        print(error)


# Load the bot state.
persistent_state.load_state_from_disk()

# Connect to discord
if config.discord_token:
    client.run(config.discord_token)
else:
    print(
        "Please pass in a Discord bot token via the BUSTY_DISCORD_TOKEN environment variable."
    )
