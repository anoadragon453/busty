"""Decorators for Discord bot commands."""

from functools import wraps

from discord import Interaction, Member, TextChannel, app_commands


def guild_only():
    """Decorator that ensures a command can only be used in a guild/server.

    This prevents the command from being used in DMs or other non-guild contexts.

    Note: After using this decorator, you should add `assert interaction.guild_id is not None`
    in the function body to help the type checker understand that guild_id is guaranteed to be non-None.
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(interaction: Interaction, *args, **kwargs):
            if interaction.guild_id is None:
                await interaction.response.send_message(
                    "This command can only be used in a server.", ephemeral=True
                )
                return
            return await func(interaction, *args, **kwargs)

        return wrapper

    return decorator


def text_channel_only():
    """Decorator that ensures a command can only be used in a text channel.

    This prevents the command from being used in voice channels, DMs, or other non-text contexts.

    Note: After using this decorator, you should add `assert isinstance(interaction.channel, TextChannel)`
    in the function body to help the type checker understand the channel type is guaranteed.
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(interaction: Interaction, *args, **kwargs):
            if not isinstance(interaction.channel, TextChannel):
                await interaction.response.send_message(
                    "This command can only be used in a text channel.", ephemeral=True
                )
                return
            return await func(interaction, *args, **kwargs)

        return wrapper

    return decorator


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
