import os

# CONSTANTS
# See https://discord.com/developers/docs/resources/channel#embed-limits for LIMIT values
# Max number of characters in an embed description
EMBED_DESCRIPTION_LIMIT = 4096
# Max number of characters in an embed field.value
EMBED_FIELD_VALUE_LIMIT = 1024
# Max number of characters in a normal Disord message
MESSAGE_LIMIT = 2000
# Color of !list embed
LIST_EMBED_COLOR = 0xDD2E44
# Color of "Now Playing" embed
PLAY_EMBED_COLOR = 0x33B86B
# The maximum character length of any song title or artist name
MAXIMUM_SONG_METADATA_CHARACTERS = 1000
# The maximum number of messages to scan for song submissions
MAXIMUM_MESSAGES_TO_SCAN = 1000
# Volume multiplier to avoid clipping on Discord
VOLUME_MULTIPLIER = 0.5
# The maximum number of songs to download concurrently
MAXIMUM_CONCURRENT_DOWNLOADS = 8
# Emoji to signify command success
COMMAND_SUCCESS_EMOJI = "\N{THUMBS UP SIGN}"
# Emoji to signify command failure
COMMAND_FAIL_EMOJI = "\N{OCTAGONAL SIGN}"

# SETTINGS
# How many seconds to wait in-between songs
seconds_between_songs = int(os.environ.get("BUSTY_COOLDOWN_SECS", 10))
# Where to save media files locally
attachment_directory_filepath = os.environ.get("BUSTY_ATTACHMENT_DIR", "attachments")
# The Discord role needed to perform bot commands
dj_role_name = os.environ.get("BUSTY_DJ_ROLE", "bangermeister")
# The Discord bot token to use
discord_token = os.environ.get("BUSTY_DISCORD_TOKEN")
# The remote folder to move Google Forms to
google_form_folder = os.environ.get("BUSTY_GOOGLE_FORM_FOLDER")
# The service account auth file to use
google_auth_file = os.environ.get("BUSTY_GOOGLE_AUTH_FILE", "auth/service_key.json")

# Warn about disabled Google Forms generation
if google_form_folder is None:
    print(
        "Warning: BUSTY_GOOGLE_FORM_FOLDER is not set, Google Forms generation will be disabled"
    )
elif not os.path.isfile(google_auth_file):
    print(
        f"Warning: {google_auth_file} is not a valid file, Google Forms generation will be disabled"
    )

# Import list of emojis from either a custom or the default list.
# The default list is expected to be stored at `./emoji_list.py`.
emoji_filepath = os.environ.get("BUSTY_CUSTOM_EMOJI_FILEPATH", "emoji_list")
# List of emoji for pulling random emoji
emoji_list = list(__import__(emoji_filepath).DISCORD_TO_UNICODE.values())
