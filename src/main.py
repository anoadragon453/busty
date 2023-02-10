import asyncio
import os
import random
from typing import Dict, Optional

from nextcord import Attachment, Embed, Intents, Interaction, SlashOption, TextChannel
from nextcord.ext import application_checks, commands

import config
import discord_utils
import persistent_state
import song_utils
from bust import BustController, create_controller

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

controllers: Dict[int, BustController] = {}


def get_controller(guild_id: int) -> Optional[BustController]:
    """Get current bust controller for current guild, if it exists"""
    # TODO: Put these lines inside of `/bust` handler.
    # Once https://github.com/anoadragon453/busty/issues/123 is done, we can
    # keep the controllers map up to date by just deleting from
    # the controllers map directly when bc.play() returns
    bc = controllers.get(guild_id)
    if bc and bc.finished():
        bc = None
    return bc


@client.event
async def on_ready() -> None:
    print(f"We have logged in as {client.user}.")


@client.event
async def on_close() -> None:
    # Finish all running busts on close
    for bc in controllers.values():
        await bc.finish(say_goodbye=False)


# Allow only one async routine to calculate list at a time
list_task_control_lock = asyncio.Lock()


# List command
@client.slash_command(name="list", dm_permission=False)
@application_checks.has_role(config.dj_role_name)
async def on_list(
    interaction: Interaction,
    list_channel: Optional[TextChannel] = SlashOption(
        required=False, description="Target channel to list."
    ),
) -> None:
    """Download and list all media sent in a chosen text channel."""
    bc = get_controller(interaction.guild_id)

    if bc and bc.is_active():
        await interaction.response.send_message("We're busy busting.", ephemeral=True)
        return

    # Give up if locked
    if list_task_control_lock.locked():
        await interaction.response.send_message(
            "A list is already in progress.", ephemeral=True
        )
        return

    if list_channel is None:
        list_channel = interaction.channel

    async with list_task_control_lock:
        # Notify user that "Busty is thinking"
        await interaction.response.defer(ephemeral=True)
        bc = await create_controller(client, interaction, list_channel)
        global controllers
        controllers[interaction.guild_id] = bc
        # If bc is None, something went wrong and we already edited the
        # interaction response to inform the user.
        if bc is not None:
            await interaction.delete_original_message()


# Bust command
@client.slash_command(dm_permission=False)
@application_checks.has_role(config.dj_role_name)
async def bust(
    interaction: Interaction,
    index: int = SlashOption(
        required=False,
        min_value=1,
        default=1,
        description="Track number to start from.",
    ),
) -> None:
    """Begin a bust."""
    bc = get_controller(interaction.guild_id)

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


# Skip command
@client.slash_command(dm_permission=False)
@application_checks.has_role(config.dj_role_name)
async def skip(interaction: Interaction) -> None:
    """Skip currently playing song."""
    bc = get_controller(interaction.guild_id)

    if not bc or not bc.is_active():
        await interaction.response.send_message("Nothing is playing.", ephemeral=True)
        return

    await interaction.response.send_message("I didn't like that track anyways.")
    bc.skip_song()


# Stop command
@client.slash_command(dm_permission=False)
@application_checks.has_role(config.dj_role_name)
async def stop(interaction: Interaction) -> None:
    """Stop playback."""
    bc = controllers.get(interaction.guild_id)

    if not bc or not bc.is_active():
        await interaction.response.send_message("Nothing is playing.", ephemeral=True)
        return

    await interaction.response.send_message("Alright I'll shut up.")
    await bc.stop()


# Image command
@client.slash_command(dm_permission=False)
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

    await interaction.response.send_message(
        f"\N{WHITE HEAVY CHECK MARK} Image set to {image_file.url}."
    )


@image.subcommand(name="url")
@application_checks.has_role(config.dj_role_name)
async def image_by_url(interaction: Interaction, image_url: str) -> None:
    """Set a Google Forms image by pasting a URL."""
    # TODO: Some basic validity filtering
    # Persist the image URL
    if not await persistent_state.save_form_image_url(interaction, image_url):
        return

    await interaction.response.send_message(
        f"\N{WHITE HEAVY CHECK MARK} Image set to {image_url}."
    )


@image.subcommand(name="clear")
@application_checks.has_role(config.dj_role_name)
async def image_clear(interaction: Interaction) -> None:
    """Clear the loaded Google Forms image."""
    image_existed = persistent_state.clear_form_image_url(interaction)
    if not image_existed:
        await interaction.response.send_message("No image is loaded.", ephemeral=True)
        return

    await interaction.response.send_message("\N{WASTEBASKET} Image cleared.")


@image.subcommand(name="view")
@application_checks.has_role(config.dj_role_name)
async def image_view(interaction: Interaction) -> None:
    """View the loaded Google Forms image."""
    loaded_image_url = persistent_state.get_form_image_url(interaction)
    if loaded_image_url is None:
        await interaction.response.send_message(
            "No image is currently loaded.", ephemeral=True
        )
        return

    await interaction.response.send_message(f"The loaded image is {loaded_image_url}.")


# Info command
@client.slash_command(dm_permission=False)
@application_checks.has_role(config.dj_role_name)
async def info(interaction: Interaction) -> None:
    """Get info about currently listed songs."""
    bc = controllers.get(interaction.guild_id)

    if bc is None:
        await interaction.response.send_message(
            "You need to use /list first.", ephemeral=True
        )
        return

    await bc.send_stats(interaction)


# Preview command
@client.slash_command(dm_permission=False)
async def preview(
    interaction: Interaction,
    uploaded_file: Attachment = SlashOption(description="The file to submit."),
    submit_message: Optional[str] = SlashOption(
        required=False, description="The submission message text."
    ),
) -> None:
    """Show a preview of a submission's "Now Playing" embed."""
    attachment_filepath = discord_utils.attachment_local_filepath(
        interaction.id, uploaded_file
    )
    random_emoji = random.choice(config.emoji_list)
    await uploaded_file.save(fp=attachment_filepath)

    if not discord_utils.is_valid_media(uploaded_file.content_type):
        await interaction.response.send_message(
            "You didn't send a valid media type. \nTry again.",
            ephemeral=True,
        )
        return

    embed = song_utils.embed_song(
        submit_message,
        attachment_filepath,
        uploaded_file,
        interaction.user,
        random_emoji,
        config.DEFAULT_JUMP_URL,
    )

    cover_art = song_utils.get_cover_art(attachment_filepath)

    if cover_art is not None:
        embed.set_image(url=f"attachment://{cover_art.filename}")
        await interaction.response.send_message(
            file=cover_art, embed=embed, ephemeral=True
        )

    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)
    os.remove(attachment_filepath)


@client.slash_command(dm_permission=False)
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
        await interaction.response.send_message(
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
    await interaction.response.send_message(interaction_reply, ephemeral=True)


@client.event
async def on_application_command_error(
    interaction: Interaction, error: Exception
) -> None:
    # Catch insufficient permissions exception, ignore all others
    if isinstance(error, application_checks.errors.ApplicationMissingRole):
        await interaction.response.send_message(
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
