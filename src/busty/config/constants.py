"""Constants for Busty bot.

These are true constants that never change - Discord API limits, application defaults, etc.
"""

from typing import Any, Final, Iterable, Mapping

# Discord API limits
# See https://discord.com/developers/docs/resources/channel#embed-limits
EMBED_DESCRIPTION_LIMIT: Final = 4096
EMBED_FIELD_VALUE_LIMIT: Final = 1024
MESSAGE_LIMIT: Final = 2000
NICKNAME_CHAR_LIMIT: Final = 32
ATTACHMENT_BYTE_LIMIT: Final = 8000000

# Embed colors
LIST_EMBED_COLOR: Final = 0xDD2E44
PLAY_EMBED_COLOR: Final = 0x33B86B
INFO_EMBED_COLOR: Final = 0x219ECC

# Application constants
MAXIMUM_SONG_METADATA_CHARACTERS: Final = 1000
MAXIMUM_MESSAGES_TO_SCAN: Final = 1000
VOLUME_MULTIPLIER: Final = 0.5
MAXIMUM_CONCURRENT_DOWNLOADS: Final = 8
PREVIEW_JUMP_URL: Final = "https://youtu.be/J45GvH2_Ato"
RESPOND_TO_MESSAGE_PROBABILITY: Final = 1 / 150

# Type aliases
JSON_DATA_TYPE = str | int | float | bool | Mapping[str, Any] | Iterable[Any] | None
