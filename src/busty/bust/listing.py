"""Discord-specific listing orchestration for bust sessions.

This module handles the Discord I/O operations for creating a bust list:
- Scraping channels for media
- Building and sending list embeds
- Pinning messages
- Generating Google Forms

The core BustController logic remains in controller.py.
"""

import logging
from typing import TYPE_CHECKING

from discord import Embed, Interaction, TextChannel

from busty import discord_utils, forms, song_utils
from busty.bust.controller import BustController
from busty.bust.discord_impl import DiscordBustOutput, OpenAIService
from busty.config import constants
from busty.config.settings import BustySettings
from busty.track import Track

if TYPE_CHECKING:
    from busty.main import BustyBot

logger = logging.getLogger(__name__)


async def list_bust(
    client: "BustyBot",
    settings: BustySettings,
    interaction: Interaction,
    list_channel: TextChannel,
) -> BustController | None:
    """Create a BustController by scraping and listing a channel.

    This function handles all Discord-specific orchestration:
    - Scrapes channel for media attachments
    - Converts media to Track objects
    - Creates BustController with Discord output implementation
    - Builds and sends formatted list embeds
    - Pins messages in the interaction channel
    - Generates Google Form for voting (if configured)

    Args:
        client: Discord bot client.
        settings: Bot settings.
        interaction: Discord interaction (not yet responded to).
        list_channel: Channel to scrape for media.

    Returns:
        New BustController, or None if no media found or error occurred.
    """
    await interaction.response.defer(ephemeral=True)

    # Scrape channel for media
    channel_media = await discord_utils.scrape_channel_media(
        list_channel, settings.attachment_cache_dir
    )
    if not channel_media:
        await interaction.edit_original_response(
            content=":warning: No valid media files found."
        )
        return None

    if not isinstance(interaction.channel, TextChannel):
        await interaction.edit_original_response(
            content="This command can only be used in a text channel."
        )
        return None

    # Convert media to Track objects
    tracks = [
        Track(
            local_filepath=path,
            attachment_filename=att.filename,
            submitter_id=msg.author.id,
            submitter_name=msg.author.display_name,
            message_content=msg.content,
            message_jump_url=msg.jump_url,
            attachment_url=att.url,
            duration=song_utils.get_song_length(path),
        )
        for msg, att, path in channel_media
    ]

    # Create Discord implementations and controller
    output = DiscordBustOutput(interaction.channel, client, settings)
    ai_service = OpenAIService(settings)
    controller = BustController(settings, tracks, output, ai_service)

    # Build and send list embeds
    await _send_list_embeds(interaction.channel, tracks)

    # Pin messages and generate form if listing in same channel as interaction
    if list_channel == interaction.channel:
        await _handle_form_generation(client, controller, interaction, settings)

    await interaction.delete_original_response()

    logger.info(
        f"Created bust list with {len(tracks)} tracks from channel "
        f"{list_channel.name} (guild {interaction.guild_id})"
    )

    return controller


async def _send_list_embeds(channel: TextChannel, tracks: list[Track]) -> list:
    """Build and send list embeds to the channel.

    Args:
        channel: Channel to send embeds to.
        tracks: List of tracks to display.

    Returns:
        List of sent Message objects.
    """
    bust_emoji = ":heart_on_fire:"
    embed_title = f"{bust_emoji} AIGHT. IT'S BUSTY TIME {bust_emoji}"
    embed_prefix = "**Track Listing**\n"

    # Split into multiple embeds if needed (Discord char limit)
    embed_descriptions: list[str] = []
    current_description = ""

    for index, track in enumerate(tracks):
        entry = (
            f"**{index + 1}.** <@{track.submitter_id}>: "
            f"[{song_utils.song_format(track.local_filepath, track.attachment_filename)}]"
            f"({track.attachment_url}) [`↲jump`]({track.message_jump_url})\n"
        )

        # Check if adding entry would exceed limit
        prefix_len = len(embed_prefix) if len(embed_descriptions) == 0 else 0
        if (
            prefix_len + len(current_description) + len(entry)
            > constants.EMBED_DESCRIPTION_LIMIT
        ):
            embed_descriptions.append(current_description)
            current_description = entry
        else:
            current_description += entry

    embed_descriptions.append(current_description)

    # Send embeds
    messages = []
    for i, description in enumerate(embed_descriptions):
        if i == 0:
            embed = Embed(
                title=embed_title,
                description=embed_prefix + description,
                color=constants.LIST_EMBED_COLOR,
            )
        else:
            embed = Embed(description=description, color=constants.LIST_EMBED_COLOR)

        message = await channel.send(embed=embed)
        messages.append(message)

    # Pin messages in reverse order
    for message in reversed(messages):
        await discord_utils.try_set_pin(message, True)

    return messages


async def _handle_form_generation(
    client: "BustyBot",
    controller: BustController,
    interaction: Interaction,
    settings: BustySettings,
) -> None:
    """Generate and post Google Form for voting.

    Args:
        client: Discord bot client.
        controller: BustController instance.
        interaction: Discord interaction for accessing guild context.
        settings: Bot settings.
    """
    if not isinstance(interaction.channel, TextChannel):
        return

    try:
        if interaction.guild_id is None:
            logger.warning("Cannot create form without guild context")
            return

        image_url = client.persistent_state.get_form_image_url(interaction.guild_id)
        form_url = _create_google_form(
            controller.tracks,
            interaction.channel.name,
            settings,
            image_url,
        )

        if form_url:
            vote_emoji = ":ballot_box_with_ballot:"
            form_message = await interaction.channel.send(
                f"{vote_emoji} **Voting Form** {vote_emoji}\n{form_url}"
            )
            await discord_utils.try_set_pin(form_message, True)
    except Exception as e:
        logger.error(f"Failed to generate Google Form: {e}")


def _create_google_form(
    tracks: list[Track],
    channel_name: str,
    settings: BustySettings,
    image_url: str | None = None,
) -> str | None:
    """Create a Google form for voting on tracks.

    Args:
        tracks: List of tracks to include in the form.
        channel_name: Name of the Discord channel (used to extract bust number).
        settings: Bot settings (for Google auth and folder config).
        image_url: Optional image URL to display at start of form.

    Returns:
        Form URL, or None if form creation fails or is not configured.
    """
    if settings.google_form_folder is None:
        logger.info("Skipping form generation as BUSTY_GOOGLE_FORM_FOLDER is unset")
        return None

    song_list = [
        f"{track.submitter_name}: {song_utils.song_format(track.local_filepath, track.attachment_filename)}"
        for track in tracks
    ]

    # Extract bust number from channel name
    bust_number = "".join([c for c in channel_name if c.isdigit()])
    if bust_number:
        bust_number = bust_number + " "

    form_url = forms.create_remote_form(
        f"Busty's {bust_number}Voting",
        song_list,
        low_val=0,
        high_val=7,
        low_label="OK",
        high_label="Masterpiece",
        google_auth_file=settings.google_auth_file,
        google_form_folder=settings.google_form_folder,
        image_url=image_url,
    )
    return form_url
