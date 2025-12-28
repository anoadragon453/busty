"""Configuration module for Busty bot.

This module provides a two-tier configuration system:
- constants: Pure constants that never change (Discord limits, colors, etc.)
- settings: Runtime settings loaded from environment variables
"""

# Re-export all constants
from busty.config.constants import (
    ATTACHMENT_BYTE_LIMIT,
    EMBED_DESCRIPTION_LIMIT,
    EMBED_FIELD_VALUE_LIMIT,
    INFO_EMBED_COLOR,
    JSON_DATA_TYPE,
    LIST_EMBED_COLOR,
    MAXIMUM_CONCURRENT_DOWNLOADS,
    MAXIMUM_MESSAGES_TO_SCAN,
    MAXIMUM_SONG_METADATA_CHARACTERS,
    MESSAGE_LIMIT,
    NICKNAME_CHAR_LIMIT,
    PLAY_EMBED_COLOR,
    PREVIEW_JUMP_URL,
    RESPOND_TO_MESSAGE_PROBABILITY,
    VOLUME_MULTIPLIER,
)

# Re-export settings class
from busty.config.settings import BustySettings

__all__ = [
    # Constants
    "ATTACHMENT_BYTE_LIMIT",
    "EMBED_DESCRIPTION_LIMIT",
    "EMBED_FIELD_VALUE_LIMIT",
    "INFO_EMBED_COLOR",
    "JSON_DATA_TYPE",
    "LIST_EMBED_COLOR",
    "MAXIMUM_CONCURRENT_DOWNLOADS",
    "MAXIMUM_MESSAGES_TO_SCAN",
    "MAXIMUM_SONG_METADATA_CHARACTERS",
    "MESSAGE_LIMIT",
    "NICKNAME_CHAR_LIMIT",
    "PLAY_EMBED_COLOR",
    "PREVIEW_JUMP_URL",
    "RESPOND_TO_MESSAGE_PROBABILITY",
    "VOLUME_MULTIPLIER",
    # Settings class
    "BustySettings",
]
