import asyncio
from typing import Dict, Optional

from nextcord import Attachment, Intents, Interaction, SlashOption, TextChannel
from nextcord.ext import application_checks, commands

import config
from bust import BustController, create_controller
from persistent import PersistentString

# This is necessary to query server members
intents = Intents.default()
# To fetch guild member information.
# Privileged intent. Requires enabling in Discord Developer Portal.
intents.members = True
# To be able to read message content.
intents.message_content = True

# Set up the Discord client. Connecting to Discord is done at
# the bottom of this file.
if config.testing_server:
    print(f"Using testing server {config.testing_server}")
    ids = [int(config.testing_server)]
    client = commands.Bot(intents=intents, default_guild_ids=ids)
else:
    client = commands.Bot(intents=intents)

controllers: Dict[int, BustController] = {}


def get_controller(guild_id: int) -> Optional[BustController]:
    """Get current bust controller for current server, if it exists"""
    # TODO: Put these lines inside of `/bust` handler.
    # Once https://github.com/anoadragon453/busty/issues/123 is done, we can
    # keep the controllers map up to date by just deleting from
    # the controllers map directly when bc.play() returns
    bc = controllers.get(guild_id)
    if bc and bc.finished():
        bc = None
    return bc


# Cached image url to use for next bust
loaded_image: PersistentString = PersistentString(filepath=config.image_state_file)


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
@client.slash_command()
@application_checks.has_role(config.dj_role_name)
async def list(
    interaction: Interaction,
    list_channel: Optional[TextChannel] = SlashOption(required=False),
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
        await interaction.response.defer(ephemeral=True)
        bc = await create_controller(
            client, interaction, list_channel, loaded_image.get()
        )
        global controllers
        controllers[interaction.guild_id] = bc
        # If bc is None, something went wrong and we already edited the
        # interaction response to inform the user.
        if bc is not None:
            await interaction.delete_original_message()


# Bust command
@client.slash_command()
@application_checks.has_role(config.dj_role_name)
async def bust(
    interaction: Interaction,
    index: Optional[int] = SlashOption(required=False, min_value=1, default=1),
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

    if index > len(bc.current_channel_content):
        await interaction.response.send_message(
            "There aren't that many tracks.", ephemeral=True
        )
        return
    await bc.play(interaction, index - 1)


# Skip command
@client.slash_command()
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
@client.slash_command()
@application_checks.has_role(config.dj_role_name)
async def stop(interaction: Interaction) -> None:
    """Stop playback."""
    bc = controllers.get(interaction.guild_id)

    if not bc or not bc.is_active():
        await interaction.response.send_message("Nothing is playing.", ephemeral=True)
        return

    await interaction.response.send_message("Alright I'll shut up")
    await bc.stop()


# Image command
@client.slash_command()
@application_checks.has_role(config.dj_role_name)
async def image(interaction: Interaction) -> None:
    """Manage saved Google Forms image."""
    pass


@image.subcommand(name="upload")
@application_checks.has_role(config.dj_role_name)
async def image_upload(interaction: Interaction, image_file: Attachment) -> None:
    """Upload a Google Forms image as attachment."""
    global loaded_image
    # TODO: Some basic validity filtering
    loaded_image.set(image_file.url)
    await interaction.response.send_message(
        f"\N{WHITE HEAVY CHECK MARK} Image set to: {loaded_image.get()}"
    )


@image.subcommand(name="url")
@application_checks.has_role(config.dj_role_name)
async def image_url(interaction: Interaction, image_url: str) -> None:
    """Set a Google Forms image by pasting a URL."""
    global loaded_image
    # TODO: Some basic validity filtering
    loaded_image.set(image_url)
    await interaction.response.send_message(
        f"\N{WHITE HEAVY CHECK MARK} Image set to: {loaded_image.get()}"
    )


@image.subcommand(name="clear")
@application_checks.has_role(config.dj_role_name)
async def image_clear(interaction: Interaction) -> None:
    """Clear the loaded Google Forms image."""
    global loaded_image
    loaded_image.set(None)
    await interaction.response.send_message("\N{WASTEBASKET} Image cleared.")


@image.subcommand("view")
@application_checks.has_role(config.dj_role_name)
async def image_view(interaction: Interaction) -> None:
    """View the loaded Google Forms image."""
    if loaded_image.get() is not None:
        content = f"Loaded image: {loaded_image.get()}"
    else:
        content = "No image is currently loaded."
    await interaction.response.send_message(content)


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


# Connect to discord
if config.discord_token:
    client.run(config.discord_token)
else:
    print(
        "Please pass in a Discord bot token via the BUSTY_DISCORD_TOKEN environment variable."
    )
