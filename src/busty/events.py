"""Discord bot event handlers."""

import logging
import random

import discord
from discord import Interaction, Message, TextChannel
from discord.app_commands import AppCommandError

from busty import discord_utils, song_utils
from busty.ai import ChatService
from busty.bot import BustyBot
from busty.config import constants
from busty.track import Track
from busty.user_preferences import UserPreferences

logger = logging.getLogger(__name__)


async def _send_preview_dm_for_attachment(
    client: BustyBot,
    message: Message,
    attachment: discord.Attachment,
) -> None:
    """Send DM preview for a valid media attachment.

    Args:
        client: Bot instance with settings.
        message: Discord message containing the attachment.
        attachment: The attachment to preview.
    """
    # guild is guaranteed to exist by caller check
    assert message.guild is not None

    # Create UserPreferences instance for this guild
    user_prefs = UserPreferences(message.guild.id, client.persistent_state)

    # Check if user has enabled preview DMs
    if not user_prefs.should_show_mailbox_preview(message.author.id):
        logger.debug(
            f"Skipping preview for user {message.author.id} - preference disabled"
        )
        return

    # Build temp filepath for this attachment
    attachment_filepath = discord_utils.build_filepath_for_attachment(
        client.settings.temp_dir,
        message.guild.id,
        attachment,
    )

    # Ensure temp directory exists
    attachment_filepath.parent.mkdir(parents=True, exist_ok=True)

    try:
        # Download attachment
        await attachment.save(fp=attachment_filepath)

        # Create Track
        preview_track = Track.from_attachment(
            attachment_filepath,
            attachment,
            message.author.id,
            message.author.display_name,
            message.content,
            message.jump_url,
        )

        # Get cover art
        cover_art_bytes = song_utils.get_cover_art_bytes(attachment_filepath)

        # Send DM preview using new utility function
        random_emoji = random.choice(client.settings.emoji_list)
        dm_content = f"Here's what your submission {message.jump_url} will look like when playing:"

        # Add nag message if no cover art
        if cover_art_bytes is None:
            # Check if AI art will be generated during the bust
            if (
                user_prefs.should_generate_ai_album_art(message.author.id)
                and client.ai_service.is_configured
            ):
                dm_content += "\n\n**Note**: AI-generated art will be used during the bust. Consider adding custom album art to your track!"
            else:
                dm_content += "\n\n**Tip**: Consider adding custom album art to your track, it will show up during the bust!"

        await song_utils.send_track_embed_with_cover_art(
            message.author,  # Send to DM
            preview_track,
            random_emoji,
            cover_art_bytes,
            content=dm_content,
        )

        logger.info(
            f"Sent preview DM for attachment {attachment.filename} "
            f"from user {message.author.id} in guild {message.guild.id}"
        )

    except discord.Forbidden:
        # User has DMs disabled - log and continue silently
        logger.info(
            f"Could not send preview DM to user {message.author.id} - DMs disabled"
        )
    except Exception as e:
        # Log error but don't notify user (silent failure for convenience feature)
        logger.error(
            f"Failed to generate preview for {attachment.filename}: {e}",
            exc_info=True,
        )
    finally:
        # Always clean up temp file
        attachment_filepath.unlink(missing_ok=True)


def register_events(client: BustyBot) -> None:
    """Register all event handlers for the bot."""

    @client.event
    async def on_ready() -> None:
        logger.info(f"We have logged in as {client.user}")

        if client.settings.openai_api_key:
            logger.info("OpenAI API key detected, initializing chat service")
            client.chat_service = ChatService(
                client.ai_service, client, client.settings
            )
            logger.info("Chat service initialized")
        else:
            logger.info("OpenAI API key not configured, chat features disabled")

        # Sync slash commands
        try:
            synced = await client.tree.sync()
            logger.info(f"Synced {len(synced)} command(s)")
        except Exception as e:
            logger.error(f"Failed to sync commands: {e}")

    @client.event
    async def on_message(message: Message) -> None:
        # Check for mailbox attachments first
        if (
            message.guild  # Must be in a guild
            and isinstance(message.channel, TextChannel)  # Must be text channel
            and message.channel.name.startswith(client.settings.mailbox_channel_prefix)
            and message.attachments  # Has attachments
            and message.author != client.user  # Not from bot itself
        ):
            # Process first valid media attachment
            for attachment in message.attachments:
                if discord_utils.is_valid_media(attachment.content_type):
                    await _send_preview_dm_for_attachment(client, message, attachment)
                    break  # Only process first valid attachment

        # Existing chatbot logic
        if (
            client.chat_service is not None
            and message.guild
            and client.user
            and (
                client.user in message.mentions
                or any(role.name == client.user.name for role in message.role_mentions)
                or random.random() < constants.RESPOND_TO_MESSAGE_PROBABILITY
            )
            and message.author != client.user
        ):
            await client.chat_service.respond(message)

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
