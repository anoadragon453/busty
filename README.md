# Busty

Busty is a bot for showcasing entries for music competitions hosted on Discord. Users
can submit audio to a channel as file attachments. The bot can then list and queue all
submitted audio, then play each media file sequentially in a Stage or Voice Call for all
to hear. These shows are known as "busts".

## Features

- Display all submitted media in a formatted list on command.
- Support for displaying embedded artist and title tags.
- Automatic pinning of track listing.
- Configurable cooldown period between each song.
- Display currently playing song as well as any text that was sent in the message.
- Display a random emoji per song. The list of emoji can be configured.
- Skip the currently playing song.
- Role-based permissions for using bot commands.

Please see the [issue list](https://github.com/anoadragon453/busty/issues) for planned
features, or to suggest your own.

## Screenshots

![an example of listing tracks](screenshots/listing.png)
![an example of a song playing](screenshots/playing.png)

## Install

You'll need at least Python 3.13 and [ffmpeg](https://ffmpeg.org/) (with opus support) installed.

### Using Nix (Recommended)

If you have Nix installed, you can use the provided flake to get a development environment with all dependencies:

```bash
nix develop
```

This will provide you with Python 3.13, uv (for package management), ruff (for linting/formatting), and all necessary system dependencies.

### Manual Installation

Alternatively, you can install dependencies manually:

1. Install [uv](https://docs.astral.sh/uv/) for Python package management
2. Install [ffmpeg](https://ffmpeg.org/) for audio processing

Then install the dependencies:

```bash
uv sync
```

## Configure

You'll need to create a Discord app, and add a bot component. **Ensure the bot has the
"Server Members Intent" and "Message Content Intent"** options enabled, otherwise the bot
will not function correctly. Note that this will limit your bot to participating in 100
servers maximum, unless you verify your bot with Discord.

Copy the bot token, and ensure that the environment variable `BUSTY_DISCORD_TOKEN` contains
the bot token when running the bot.

If you'd like automatic Google Form generation, you need a [Google service account](https://cloud.google.com/iam/docs/service-accounts).
See [this page](https://console.cloud.google.com/iam-admin/serviceaccounts?walkthrough_id=iam--create-service-account-keys&start_index=1#step_index=1)
to manage and create a service account (and a project if you don't already have one). Once created, go to the
"keys" tab and click "Add Key" -> "Create new key" and download the key in JSON format. The path
to this file is what you should use for the value of `BUSTY_GOOGLE_AUTH_FILE`.

Once you've created an account, ensure the project it is attached to has both the
[Google Forms API](https://console.developers.google.com/apis/api/forms.googleapis.com/overview)
and the
[Google Drive API](https://console.cloud.google.com/apis/api/drive.googleapis.com/metrics)
enabled for form generation.

Next, create (or use an existing) Google Drive folder to store the generated Google forms in. Share this folder with the
email address associated with your service account (typically `account-name@project-id.iam.gserviceaccount.com`).
Set `BUSTY_GOOGLE_FORM_FOLDER` to the ID of this folder when running the bot. To find the ID of a Google Drive folder,
navigate inside it in your web browser. The folder ID is the token at the end of the URL.

Finally, add the bot to your desired Discord server.

The complete list of environment variable configuration options is:

1. `BUSTY_DISCORD_TOKEN` - Discord bot API token (required)
1. `BUSTY_GOOGLE_FORM_FOLDER` - Google Drive folder ID for voting form (required for form generation)
1. `BUSTY_GOOGLE_AUTH_FILE` - Google service account auth file (default = auth/service_key.json)
1. `BUSTY_COOLDOWN_SECS` - Number of seconds between songs (default = 10)
1. `BUSTY_ATTACHMENT_DIR` - Directory to save attachments (default = attachments)
1. `BUSTY_DJ_ROLE` - Name of role with permissions to run commands (default = bangermeister)
1. `BUSTY_CUSTOM_EMOJI_FILEPATH` - The Python module to import containing the emoji list (default = emoji_list)
1. `BUSTY_BOT_STATE_FILE` - The location of the file to store persistent bot state in (default = bot_state.json)
1. `BUSTY_TESTING_GUILD_ID` - For developers only. Specify a testing guild id to avoid 1 hour command update delay (see [this Discord API issue](https://github.com/discord/discord-api-docs/issues/2372#issuecomment-761161082) for details) (default = None)

A random emoji is displayed for each song played during a bust. The list of possible
emoji is defined in [emoji_list.py](src/emoji_list.py). If you would like to customize
this list, simply copy the file, edit it, and set `BUSTY_CUSTOM_EMOJI_FILEPATH` to
the import path (often simply the filename without an extension) of the new module.

## Run

With the proper environment variables set, start the bot with:

```bash
# Using uv
uv run busty

# Or using make
make run
```

It should connect to Discord and display the currently logged-in application name.

## Usage

The expected flow for running a bust is:

- Users submit songs into a channel.
- All users join a voice channel or stage.
- An admin runs `/list` to list all submitted songs and the order they will be played in.
- An admin runs `/bust` to start the show. The bot will join the channel and begin playing songs in the order they were submitted.
- Users comment on songs while they play.
- An admin can run `/skip` at any time to skip the current song, or `/stop` to manually stop the show.
- Once the last song has played, the bot will post a concluding message and leave the call.

### Command Reference

1. `/list [<channel>]` - Download and list all media sent in the current text channel. Specifying a channel will cause songs to be pulled from that channel instead. This must be run before `/bust`.
1. `/bust [<song_num>]` - Join the vc/stage that the user who ran this command is currently in, and plays the tracks in the channel in order. The user must be in a vc or stage for this to work. Specifying a song index will skip to that index before playing.
1. `/info` - Show some statistics about currently listed songs.
1. `/preview <attachment> [<submit_message>]` - Show a preview of the attachment's artist, title and artwork.
1. `/image upload <attachment>` - Upload an image to be used in the Google Form generated when running `/list`.
1. `/image url <url>` - Queue an image to be used in the Google Form generated when running `/list`.
1. `/image view` - View currently loaded image to be used in the Google Form generated when running `/list`.
1. `/image clear` - Clear currently loaded image to be used in the Google Form generated when running `/list`.
1. `/skip` - Skips the current track :scream:
1. `/stop` - Stop busting early :scream: :scream: :scream:

Users must have the `bangermeister` role to use commands by default, though this role can
be modified by passing the `BUSTY_DJ_ROLE` environment variable. It is highly recommended that
you disable command visibility for those without permissions to run them in the Integrations
section of your server's settings.

## Development

If you'd like to help Busty in her quest, consider working on one of the
[currently open issues](https://github.com/anoadragon453/busty). Before you do,
please double-check that a pull request for the issue
[does not already exist](https://github.com/anoadragon453/busty/pulls).

### Installing the development dependencies

Development dependencies are automatically installed when you run `uv sync`. The project uses `pyproject.toml` to manage all dependencies, including development tools like ruff and mypy.

### Testing your changes

Busty does not currently feature any automated testing. Testing is carried out
manually, typically in one's own test Discord guild.

Once you have implemented your change, please ensure that [known commands](#command-reference),
listing tracks and playing songs all work with your change. Pull requests are
additionally tested by reviewers before merging them, but we're only human.

### Linting and Formatting

This project uses [ruff](https://docs.astral.sh/ruff/) for both linting and code formatting. To check your code:

```bash
# Lint the code
uv run ruff check .

# Format the code
uv run ruff format .

# Or use make
make lint
make format
```

The project also uses mypy for type checking:

```bash
uv run mypy src/
# Or
make type-check
```

All linting and formatting issues must be fixed before your PR will be accepted. If you
are unable to figure out how to appease the linter, simply post and mark your
pull request as a draft and ask for help in a comment.
