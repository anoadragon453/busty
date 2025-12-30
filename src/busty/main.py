import logging
import random
import sys
from typing import cast

import colorlog
import discord
from discord import (
    Attachment,
    ClientException,
    Embed,
    Intents,
    Interaction,
    Member,
    Message,
    StageChannel,
    TextChannel,
    VoiceChannel,
    app_commands,
)
from discord.app_commands import AppCommandError
from discord.ext import commands

from busty import (
    bust,
    discord_utils,
    llm,
    persistent_state,
    song_utils,
)
from busty.bust.discord_impl import DiscordAudioPlayer
from busty.config import constants
from busty.config.settings import BustySettings
from busty.config.validation import validate_and_setup_directories

logger = logging.getLogger(__name__)


def setup_logging(log_level: int) -> None:
    formatter = colorlog.ColoredFormatter(
        "%(cyan)s%(asctime)s%(reset)s %(log_color)s%(levelname)-8s%(reset)s %(light_purple)s%(name)s:%(reset)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        log_colors={
            "DEBUG": "purple",
            "INFO": "blue",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "red,bg_white",
        },
    )

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(formatter)

    logger = logging.getLogger()
    logger.setLevel(log_level)
    logger.addHandler(handler)


class BustyBot(commands.Bot):
    """Custom Busty bot class."""

    def __init__(self, settings: BustySettings, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.settings = settings
        self.bust_registry = bust.BustRegistry()
        self.persistent_state = persistent_state.PersistentState(
            settings.bot_state_file
        )


# This is necessary to query guild members
intents = Intents.default()
intents.members = True
intents.message_content = True

# Setup logging
setup_logging(logging.INFO)

# Load settings once at startup
settings = BustySettings.from_environment()
settings.validate(logger)

if settings.testing_guild:
    logger.info(f"Using testing guild {settings.testing_guild}")
    ids = [int(settings.testing_guild)]
client = BustyBot(settings=settings, intents=intents, command_prefix="!")


def has_dj_role():
    """Decorator that checks for DJ role using bot's settings.

    This decorator defers the role lookup to runtime, allowing it to access
    the bot's settings which are not available at module import time.
    """

    async def predicate(interaction: Interaction) -> bool:
        if not hasattr(interaction.client, "settings"):
            return False
        dj_role = interaction.client.settings.dj_role_name
        # Check if user is a Member (has roles attribute)
        if not isinstance(interaction.user, Member):
            return False
        return any(role.name == dj_role for role in interaction.user.roles)

    return app_commands.check(predicate)


@client.event
async def on_ready() -> None:
    logger.info(f"We have logged in as {client.user}")

    if client.settings.openai_api_key:
        logger.info("OpenAI API key detected, initializing LLM features")
        llm.initialize(client, client.settings)
    else:
        logger.info("OpenAI API key not configured, LLM features disabled")

    # Sync slash commands
    try:
        synced = await client.tree.sync()
        logger.info(f"Synced {len(synced)} command(s)")
    except Exception as e:
        logger.error(f"Failed to sync commands: {e}")


@client.event
async def on_message(message: Message) -> None:
    if (
        client.settings.openai_api_key
        and message.guild
        and client.user
        and (
            client.user in message.mentions
            or any(role.name == client.user.name for role in message.role_mentions)
            or random.random() < constants.RESPOND_TO_MESSAGE_PROBABILITY
        )
        and message.author != client.user
    ):
        await llm.respond(message)


# List command
@client.tree.command(name="list")
@has_dj_role()
async def on_list(
    interaction: Interaction, list_channel: TextChannel | None = None
) -> None:
    """Download and list all media sent in a chosen text channel."""
    if interaction.guild_id is None:
        await interaction.response.send_message(
            "This command can only be used in a server.", ephemeral=True
        )
        return

    bc = client.bust_registry.get(interaction.guild_id)
    if bc and bc.is_playing:
        await interaction.response.send_message("We're busy busting.", ephemeral=True)
        return

    list_lock = client.bust_registry.get_list_lock(interaction.guild_id)
    if list_lock.locked():
        await interaction.response.send_message(
            "A list is already in progress.", ephemeral=True
        )
        return
    if list_channel is None:
        if not isinstance(interaction.channel, TextChannel):
            await interaction.response.send_message(
                "This command can only be used in a text channel.", ephemeral=True
            )
            return
        list_channel = interaction.channel

    logger.info(
        f"User {interaction.user} issued /list command in guild {interaction.guild_id}, channel {list_channel.name}"
    )
    async with list_lock:
        bc = await bust.list_bust(client, client.settings, interaction, list_channel)
        if bc is not None:
            client.bust_registry.register(interaction.guild_id, bc)


# Bust command
@client.tree.command(name="bust")
@has_dj_role()
async def on_bust(interaction: Interaction, index: int = 1) -> None:
    """Begin a bust."""
    await interaction.response.defer(ephemeral=True)

    # Validate context
    if not isinstance(interaction.channel, TextChannel):
        await interaction.followup.send(
            "This command can only be used in a text channel.", ephemeral=True
        )
        return
    if interaction.guild is None:
        await interaction.followup.send(
            "This command can only be used in a server.", ephemeral=True
        )
        return

    # Get controller
    bc = client.bust_registry.get(interaction.guild.id)
    if bc is None:
        await interaction.followup.send(
            "You need to use `/list` first.", ephemeral=True
        )
        return
    elif bc.is_playing:
        await interaction.followup.send("We're already busting.", ephemeral=True)
        return
    if index > len(bc.tracks):
        await interaction.followup.send(
            "There aren't that many tracks.", ephemeral=True
        )
        return

    # Find user's voice channel
    voice_channels: list[VoiceChannel | StageChannel] = list(
        interaction.guild.voice_channels
    )
    voice_channels.extend(interaction.guild.stage_channels)

    target_channel = None
    for voice_channel in voice_channels:
        if interaction.user in voice_channel.members:
            target_channel = voice_channel
            break

    if target_channel is None:
        await interaction.followup.send(
            "You need to be in an active voice channel.", ephemeral=True
        )
        return

    logger.info(
        f"User {interaction.user} issued /bust command in guild {interaction.guild.id}, starting at track {index}"
    )

    # Create and connect audio player
    audio_player = DiscordAudioPlayer(interaction.guild.id, settings)
    try:
        await audio_player.connect(target_channel)
        await interaction.delete_original_response()

        await bc.play(audio_player, index - 1)
    except ClientException as e:
        logger.error(f"Failed to connect to voice channel: {e}")
        await interaction.followup.send(
            "Failed to connect to voice channel.", ephemeral=True
        )
    finally:
        await audio_player.disconnect()
    # Registry auto-cleans finished controllers


# Skip command
@client.tree.command(name="skip")
@has_dj_role()
async def skip(interaction: Interaction) -> None:
    """Skip currently playing song."""
    if interaction.guild_id is None:
        await interaction.response.send_message(
            "This command can only be used in a server.", ephemeral=True
        )
        return

    bc = client.bust_registry.get(interaction.guild_id)

    if not bc or not bc.is_playing:
        await interaction.response.send_message("Nothing is playing.", ephemeral=True)
        return

    logger.info(
        f"User {interaction.user} issued /skip command in guild {interaction.guild_id}"
    )
    await interaction.response.send_message("I didn't like that track anyways.")
    # Skip to next track (current_index will be incremented in playback loop)
    if bc._playback:
        bc.skip_to(bc._playback.current_index + 1)


# Seek command
@client.tree.command(name="seek")
@has_dj_role()
async def seek(
    interaction: Interaction,
    timestamp: str | None = None,
) -> None:
    """Seek to time in the currently playing song."""
    if interaction.guild_id is None:
        await interaction.response.send_message(
            "This command can only be used in a server.", ephemeral=True
        )
        return

    # Get seek offset
    seek_to_seconds = song_utils.convert_timestamp_to_seconds(timestamp)
    if seek_to_seconds is None:
        await interaction.response.send_message("Invalid seek time.", ephemeral=True)
        return

    bc = client.bust_registry.get(interaction.guild_id)

    if not bc or not bc.is_playing:
        await interaction.response.send_message("Nothing is playing.", ephemeral=True)
        return

    logger.info(
        f"User {interaction.user} issued /seek command in guild {interaction.guild_id}, timestamp {seek_to_seconds}s"
    )
    await interaction.response.send_message("Let's skip to the good part.")
    bc.seek(seek_to_seconds)


# Replay command
@client.tree.command(name="replay")
@has_dj_role()
async def replay(interaction: Interaction) -> None:
    """Replay currently playing song from the beginning."""
    if interaction.guild_id is None:
        await interaction.response.send_message(
            "This command can only be used in a server.", ephemeral=True
        )
        return

    bc = client.bust_registry.get(interaction.guild_id)

    if not bc or not bc.is_playing:
        await interaction.response.send_message("Nothing is playing.", ephemeral=True)
        return

    logger.info(
        f"User {interaction.user} issued /replay command in guild {interaction.guild_id}"
    )
    await interaction.response.send_message("Replaying this track.")
    if bc._playback:
        bc.skip_to(bc._playback.current_index)


# Stop command
@client.tree.command(name="stop")
@has_dj_role()
async def stop(interaction: Interaction) -> None:
    """Stop playback."""
    if interaction.guild_id is None:
        await interaction.response.send_message(
            "This command can only be used in a server.", ephemeral=True
        )
        return

    bc = client.bust_registry.get(interaction.guild_id)

    if not bc or not bc.is_playing:
        await interaction.response.send_message("Nothing is playing.", ephemeral=True)
        return

    logger.info(
        f"User {interaction.user} issued /stop command in guild {interaction.guild_id}"
    )
    await interaction.response.send_message("Alright I'll shut up.")
    bc.stop()


class ImageGroup(app_commands.Group):
    def __init__(self) -> None:
        super().__init__(name="image", description="Manage saved Google Forms image.")

    @app_commands.command(
        name="upload", description="Upload a Google Forms image as attachment."
    )
    async def upload(
        self, interaction: discord.Interaction, image_file: discord.Attachment
    ) -> None:
        # TODO: Some basic validity filtering
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "This command must be used in a server.", ephemeral=True
            )
            return

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
        # TODO: Some basic validity filtering
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "This command must be used in a server.", ephemeral=True
            )
            return

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
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "This command must be used in a server.", ephemeral=True
            )
            return

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
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "This command must be used in a server.", ephemeral=True
            )
            return

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


client.tree.add_command(ImageGroup())


# Info command
@client.tree.command(name="info")
@has_dj_role()
async def info(interaction: Interaction) -> None:
    """Get info about currently listed songs."""
    if interaction.guild_id is None:
        await interaction.response.send_message(
            "This command can only be used in a server.", ephemeral=True
        )
        return

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
            stats.submitter_stats[: settings.num_longest_submitters]
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
        embed_text += "\n\n**There were some errors. Statistics may be inaccurate.**"

    embed = Embed(
        title="Listed Statistics",
        description=embed_text,
        color=constants.INFO_EMBED_COLOR,
    )
    await interaction.followup.send(embed=embed)


# Preview command
@client.tree.command(name="preview")
async def preview(
    interaction: Interaction,
    uploaded_file: Attachment,
    submit_message: str | None = None,
) -> None:
    """Show a preview of a submission's 'Now Playing' embed."""
    if interaction.guild_id is None:
        await interaction.response.send_message(
            "This command can only be used in a server.", ephemeral=True
        )
        return

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
    from busty.track import Track

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


@client.tree.command(name="announce")
@has_dj_role()
async def announce(
    interaction: Interaction,
    title: str,
    body: str,
    channel: TextChannel | None = None,
) -> None:
    """Send a message as the bot into a channel wrapped in an embed."""
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


@client.event
async def on_application_command_error(
    interaction: Interaction, error: Exception
) -> None:
    # Catch insufficient permissions exception, ignore all others
    if isinstance(error, AppCommandError):
        await interaction.response.send_message(
            "You don't have permission to use this command.", ephemeral=True
        )
    else:
        logger.error(error)


def run_bot() -> None:
    """Entry point for the busty script."""
    logger.info("Starting Busty bot")

    # Validate directories
    validation_errors = validate_and_setup_directories(client.settings)
    if validation_errors:
        for error in validation_errors:
            logger.error(error)
        logger.critical("Startup validation failed, exiting")
        sys.exit(1)

    # Connect to discord
    if client.settings.discord_token:
        # Disable built-in log handler as we set our own
        client.run(client.settings.discord_token, log_handler=None)
    else:
        logger.error(
            "Please pass in a Discord bot token via the BUSTY_DISCORD_TOKEN environment variable."
        )


if __name__ == "__main__":
    run_bot()
