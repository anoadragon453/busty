"""Discord bot commands package."""

from busty.bot import BustyBot


def register_all_commands(client: BustyBot) -> None:
    """Register all commands for the bot."""
    from busty.commands import admin, bust, image, info, preferences

    bust.register_commands(client)
    info.register_commands(client)
    admin.register_commands(client)
    image.register_commands(client)
    preferences.register_commands(client)
