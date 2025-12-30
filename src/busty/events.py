"""Discord bot event handlers."""

import logging
import random

from discord import Interaction, Message
from discord.app_commands import AppCommandError

from busty import llm
from busty.bot import BustyBot
from busty.config import constants

logger = logging.getLogger(__name__)


def register_events(client: BustyBot) -> None:
    """Register all event handlers for the bot."""

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
