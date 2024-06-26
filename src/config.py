import os
from typing import Iterable, Mapping, Union

# CONSTANTS
# See https://discord.com/developers/docs/resources/channel#embed-limits for LIMIT values
# Max number of characters in an embed description
EMBED_DESCRIPTION_LIMIT = 4096
# Max number of characters in an embed field.value
EMBED_FIELD_VALUE_LIMIT = 1024
# Max number of characters in a normal Disord message
MESSAGE_LIMIT = 2000
# Max number of characters in a Discord nickname
NICKNAME_CHAR_LIMIT = 32
# (A safe lower bound for) max allowed bytes in a Discord attachment
ATTACHMENT_BYTE_LIMIT = 8000000
# Color of list embed
LIST_EMBED_COLOR = 0xDD2E44
# Color of "Now Playing" embed
PLAY_EMBED_COLOR = 0x33B86B
# Color of info embed
INFO_EMBED_COLOR = 0x219ECC
# The maximum character length of any song title or artist name
MAXIMUM_SONG_METADATA_CHARACTERS = 1000
# The maximum number of messages to scan for song submissions
MAXIMUM_MESSAGES_TO_SCAN = 1000
# Volume multiplier to avoid clipping on Discord
VOLUME_MULTIPLIER = 0.5
# The maximum number of songs to download concurrently
MAXIMUM_CONCURRENT_DOWNLOADS = 8
# The URL that the '↲jump' link will lead to when using the /preview command.
PREVIEW_JUMP_URL = "https://youtu.be/J45GvH2_Ato"

# SETTINGS
# How many seconds to wait in-between songs
seconds_between_songs = int(os.environ.get("BUSTY_COOLDOWN_SECS", 10))
# Where to save media files locally
attachment_directory_filepath = os.environ.get("BUSTY_ATTACHMENT_DIR", "attachments")
# The Discord role needed to perform bot commands
dj_role_name = os.environ.get("BUSTY_DJ_ROLE", "bangermeister")
# Number of longest submitters to show on /info
num_longest_submitters = int(os.environ.get("BUSTY_NUM_LONGEST_SUBMITTERS", 3))
# The Discord bot token to use
discord_token = os.environ.get("BUSTY_DISCORD_TOKEN")
# The remote folder to move Google Forms to
google_form_folder = os.environ.get("BUSTY_GOOGLE_FORM_FOLDER")
# The service account auth file to use
google_auth_file = os.environ.get("BUSTY_GOOGLE_AUTH_FILE", "auth/service_key.json")
# The location of the file to store persistent bot state
bot_state_file = os.environ.get("BUSTY_BOT_STATE_FILE", "bot_state.json")
# The location of the file to store context for the GPT bot
llm_context_file = os.environ.get("BUSTY_LLM_CONTEXT_FILE", "llm_context.json")
# For developers only. Specify a testing guild id to avoid 1 hour command update delay
testing_guild = os.environ.get("BUSTY_TESTING_GUILD_ID", None)
# OpenAI API Key
openai_api_key = os.environ.get("BUSTY_OPENAI_API_KEY", None)
# The OpenAI model to use for GPT abilities
openai_model = os.environ.get("BUSTY_OPENAI_MODEL", "gpt-3.5-turbo")

# TYPES
# Acceptable data types to store in a JSON representation.
JSON_DATA_TYPE = Union[str, int, float, bool, Mapping, Iterable, None]

# Warn about disabled Google Forms generation
if google_form_folder is None:
    print(
        "Warning: BUSTY_GOOGLE_FORM_FOLDER is not set, Google Forms generation will be disabled"
    )
elif not os.path.isfile(google_auth_file):
    print(
        f"Warning: {google_auth_file} is not a valid file, Google Forms generation will be disabled"
    )

if openai_api_key is None:
    print(
        "Warning: BUSTY_OPENAI_API_KEY is not set, natural language abilities will be disabled"
    )

# Import list of emojis from either a custom or the default list.
# The default list is expected to be stored at `./emoji_list.py`.
emoji_filepath = os.environ.get("BUSTY_CUSTOM_EMOJI_FILEPATH", "emoji_list")
# List of emoji for pulling random emoji
emoji_list = list(__import__(emoji_filepath).DISCORD_TO_UNICODE.values())
