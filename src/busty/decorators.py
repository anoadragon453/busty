"""Decorators for Discord bot commands."""

from functools import wraps

from discord import Interaction, Member, TextChannel, app_commands


def text_channel_only():
    """Decorator that ensures a command can only be used in a text channel.

    This prevents the command from being used in voice channels, DMs, or other non-text contexts.

    Note: After using this decorator, you should add `assert isinstance(interaction.channel, TextChannel)`
    in the function body to help the type checker understand the channel type is guaranteed.

    Works with both standalone commands and commands in app_commands.Group classes.
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(first_arg, *args, **kwargs):
            # Handle both standalone commands and Group methods
            # If first_arg is an Interaction, it's a standalone command
            # Otherwise, it's 'self' from a Group method, and interaction is in args[0]
            if isinstance(first_arg, Interaction):
                interaction = first_arg
            else:
                # first_arg is 'self', interaction is args[0]
                interaction = args[0]

            if not isinstance(interaction.channel, TextChannel):
                await interaction.response.send_message(
                    "This command can only be used in a text channel.", ephemeral=True
                )
                return
            return await func(first_arg, *args, **kwargs)

        return wrapper

    return decorator


def has_dj_role():
    """Decorator that checks for DJ role using bot's settings.

    This decorator defers the role lookup to runtime, allowing it to access
    the bot's settings which are not available at module import time.

    Raises CheckFailure with a descriptive message if the check fails.
    """

    async def predicate(interaction: Interaction) -> bool:
        if not hasattr(interaction.client, "settings"):
            raise app_commands.CheckFailure("Bot settings not available.")

        dj_role = interaction.client.settings.dj_role_name

        # Check if user is a Member (has roles attribute)
        if not isinstance(interaction.user, Member):
            raise app_commands.CheckFailure(
                "This command can only be used in a server."
            )

        # Check if user has the DJ role
        if not any(role.name == dj_role for role in interaction.user.roles):
            raise app_commands.CheckFailure(
                f"This command requires the **{dj_role}** role."
            )

        return True

    return app_commands.check(predicate)
