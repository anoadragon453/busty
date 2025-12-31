"""BustyBot Discord bot class and initialization."""

from discord.ext import commands

from busty import bust, persistent_state
from busty.ai import ChatService, OpenAIService
from busty.config.settings import BustySettings


class BustyBot(commands.Bot):
    """Custom Busty bot class."""

    def __init__(self, settings: BustySettings, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.settings = settings
        self.bust_registry = bust.BustRegistry()
        self.persistent_state = persistent_state.PersistentState(
            settings.bot_state_file
        )

        # AI service (created at init, doesn't need Discord client)
        self.ai_service = OpenAIService(settings)

        # Chat service (None until on_ready, needs self.user)
        self.chat_service: ChatService | None = None
