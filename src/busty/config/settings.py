"""Runtime settings for Busty bot.

Settings loaded from environment variables and provided to components via dependency injection.
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BustySettings:
    """Runtime settings for Busty bot."""

    # Bot configuration
    discord_token: str | None
    dj_role_name: str
    testing_guild: str | None

    # Base directories (Path objects)
    data_dir: Path
    auth_dir: Path

    # Derived directory paths (Path objects)
    state_dir: Path
    config_dir: Path
    cache_dir: Path
    temp_dir: Path
    attachment_cache_dir: Path

    # File paths (Path objects)
    bot_state_file: Path
    llm_context_file: Path
    google_auth_file: Path

    # Google Forms integration
    google_form_folder: str | None

    # OpenAI integration
    openai_api_key: str | None
    openai_model: str
    openai_tokenizer_model: str

    # Playback settings
    seconds_between_songs: int
    num_longest_submitters: int

    # Emoji list (derived from emoji module)
    emoji_list: list[str]

    # Mailbox channel detection
    mailbox_channel_prefix: str

    # Logging
    log_level: int

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

        # Determine base directories
        data_dir = Path(os.environ.get("BUSTY_DATA_DIR", "data"))
        auth_dir = Path(os.environ.get("BUSTY_AUTH_DIR", "auth"))

        # Compute derived paths (hardcoded structure)
        state_dir = data_dir / "state"
        config_dir = data_dir / "config"
        cache_dir = data_dir / "cache"
        temp_dir = data_dir / "temp"
        attachment_cache_dir = cache_dir / "attachments"

        # Compute file paths (hardcoded structure)
        bot_state_file = state_dir / "bot_state.json"
        llm_context_file = config_dir / "llm_context.yaml"
        google_auth_file = auth_dir / "service_account.json"

        # Load OpenAI model (used for both model and tokenizer by default)
        openai_model = os.environ.get("BUSTY_OPENAI_MODEL", "gpt-4o")

        # Load log level
        log_level_name = os.environ.get("BUSTY_LOG_LEVEL", "INFO").upper()
        log_level = getattr(logging, log_level_name, logging.INFO)

        return BustySettings(
            discord_token=os.environ.get("BUSTY_DISCORD_TOKEN"),
            dj_role_name=os.environ.get("BUSTY_DJ_ROLE", "bangermeister"),
            testing_guild=os.environ.get("BUSTY_TESTING_GUILD_ID", None),
            data_dir=data_dir,
            auth_dir=auth_dir,
            state_dir=state_dir,
            config_dir=config_dir,
            cache_dir=cache_dir,
            temp_dir=temp_dir,
            attachment_cache_dir=attachment_cache_dir,
            bot_state_file=bot_state_file,
            llm_context_file=llm_context_file,
            google_auth_file=google_auth_file,
            google_form_folder=os.environ.get("BUSTY_GOOGLE_FORM_FOLDER"),
            openai_api_key=os.environ.get("BUSTY_OPENAI_API_KEY", None),
            openai_model=openai_model,
            openai_tokenizer_model=os.environ.get(
                "BUSTY_OPENAI_TOKENIZER", openai_model
            ),
            seconds_between_songs=int(os.environ.get("BUSTY_COOLDOWN_SECS", "10")),
            num_longest_submitters=int(
                os.environ.get("BUSTY_NUM_LONGEST_SUBMITTERS", "3")
            ),
            emoji_list=emoji_list,
            mailbox_channel_prefix=os.environ.get(
                "BUSTY_MAILBOX_PREFIX", "bustys-mailbox-"
            ),
            log_level=log_level,
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
        elif not self.google_auth_file.is_file():
            logger.warning(
                f"{self.google_auth_file} not found, Google Forms generation will be disabled"
            )

        if self.openai_api_key is None:
            logger.warning(
                "BUSTY_OPENAI_API_KEY is not set, natural language abilities will be disabled"
            )
