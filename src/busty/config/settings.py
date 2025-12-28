"""Runtime settings for Busty bot.

Settings loaded from environment variables and provided to components via dependency injection.
"""

import logging
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class BustySettings:
    """Runtime settings for Busty bot."""

    # Bot configuration
    discord_token: str | None
    dj_role_name: str
    testing_guild: str | None

    # File paths
    attachment_directory_filepath: str
    bot_state_file: str
    llm_context_file: str

    # Google Forms integration
    google_form_folder: str | None
    google_auth_file: str

    # OpenAI integration
    openai_api_key: str | None
    openai_model: str

    # Playback settings
    seconds_between_songs: int
    num_longest_submitters: int

    # Emoji list (derived from emoji module)
    emoji_list: list[str]

    @staticmethod
    def from_environment() -> "BustySettings":
        """Load settings from environment variables.

        Returns:
            BustySettings instance with values from environment variables.
        """
        # Load emoji module dynamically
        emoji_filepath = os.environ.get(
            "BUSTY_CUSTOM_EMOJI_FILEPATH", "busty.emoji_list"
        )
        emoji_module = __import__(emoji_filepath, fromlist=["DISCORD_TO_UNICODE"])
        emoji_list = list(emoji_module.DISCORD_TO_UNICODE.values())

        return BustySettings(
            discord_token=os.environ.get("BUSTY_DISCORD_TOKEN"),
            dj_role_name=os.environ.get("BUSTY_DJ_ROLE", "bangermeister"),
            testing_guild=os.environ.get("BUSTY_TESTING_GUILD_ID", None),
            attachment_directory_filepath=os.environ.get(
                "BUSTY_ATTACHMENT_DIR", "attachments"
            ),
            bot_state_file=os.environ.get("BUSTY_BOT_STATE_FILE", "bot_state.json"),
            llm_context_file=os.environ.get(
                "BUSTY_LLM_CONTEXT_FILE", "llm_context.json"
            ),
            google_form_folder=os.environ.get("BUSTY_GOOGLE_FORM_FOLDER"),
            google_auth_file=os.environ.get(
                "BUSTY_GOOGLE_AUTH_FILE", "auth/oauth_token.json"
            ),
            openai_api_key=os.environ.get("BUSTY_OPENAI_API_KEY", None),
            openai_model=os.environ.get("BUSTY_OPENAI_MODEL", "gpt-3.5-turbo"),
            seconds_between_songs=int(os.environ.get("BUSTY_COOLDOWN_SECS", "10")),
            num_longest_submitters=int(
                os.environ.get("BUSTY_NUM_LONGEST_SUBMITTERS", "3")
            ),
            emoji_list=emoji_list,
        )

    def validate(self, logger: logging.Logger) -> None:
        """Log warnings for missing optional configuration.

        Args:
            logger: Logger instance to use for warnings.
        """
        if self.google_form_folder is None:
            logger.warning(
                "BUSTY_GOOGLE_FORM_FOLDER is not set, Google Forms generation will be disabled"
            )
        elif not os.path.isfile(self.google_auth_file):
            logger.warning(
                f"{self.google_auth_file} is not a valid file, Google Forms generation will be disabled"
            )

        if self.openai_api_key is None:
            logger.warning(
                "BUSTY_OPENAI_API_KEY is not set, natural language abilities will be disabled"
            )
