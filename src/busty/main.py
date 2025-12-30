"""Busty Discord bot main entry point."""

import logging
import sys

import colorlog
from discord import Intents

from busty.bot import BustyBot
from busty.commands import register_all_commands
from busty.config.settings import BustySettings
from busty.config.validation import validate_and_setup_directories
from busty.events import register_events

logger = logging.getLogger(__name__)


def setup_logging(log_level: int) -> None:
    """Configure colored logging for the application."""
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

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(handler)


def run_bot() -> None:
    """Entry point for the busty script."""
    # Setup logging
    setup_logging(logging.INFO)
    logger.info("Starting Busty bot")

    # Load settings
    settings = BustySettings.from_environment()
    settings.validate(logger)

    if settings.testing_guild:
        logger.info(f"Using testing guild {settings.testing_guild}")

    # Validate directories
    validation_errors = validate_and_setup_directories(settings)
    if validation_errors:
        for error in validation_errors:
            logger.error(error)
        logger.critical("Startup validation failed, exiting")
        sys.exit(1)

    # Configure intents
    intents = Intents.default()
    intents.members = True
    intents.message_content = True

    # Create bot instance
    client = BustyBot(settings=settings, intents=intents, command_prefix="!")

    # Register all event handlers and commands
    register_events(client)
    register_all_commands(client)

    # Connect to Discord
    if client.settings.discord_token:
        # Disable built-in log handler as we set our own
        client.run(client.settings.discord_token, log_handler=None)
    else:
        logger.error(
            "Please pass in a Discord bot token via the BUSTY_DISCORD_TOKEN environment variable."
        )


if __name__ == "__main__":
    run_bot()
