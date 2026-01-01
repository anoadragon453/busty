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

If you'd like automatic Google Form generation, you need to set up Google OAuth credentials.

### Setting up Google Forms Integration

1. **Create a Google Cloud Project** (or use an existing one):
   - Go to [Google Cloud Console](https://console.cloud.google.com)
   - Create a new project or select an existing one

2. **Enable Required APIs**:
   - Enable [Google Forms API](https://console.developers.google.com/apis/api/forms.googleapis.com/overview)
   - Enable [Google Drive API](https://console.cloud.google.com/apis/api/drive.googleapis.com/metrics)

3. **Create OAuth 2.0 Credentials**:
   - Create the auth directory: `mkdir -p auth/`
   - Go to **APIs & Services** > **Credentials**
   - Click **Create Credentials** > **OAuth 2.0 Client ID**
   - If prompted, configure the OAuth consent screen:
     - User type: **External** (or Internal if you have Google Workspace)
     - App name: **Busty Bot**
     - Add your support email
     - Scopes: Click **Save and Continue** (scopes are set in code)
     - **Test users** (may be called "Audience"): Click **Add Users** and add the email of the Google account you'll use for the bot
     - Click **Save and Continue**
   - Back on the Credentials page, click **Create Credentials** > **OAuth 2.0 Client ID** again
   - Choose **Desktop app** as the application type
   - Name it **Busty Bot**
   - Click **Create** and download the JSON file
   - Save it as `auth/oauth_credentials.json` in your project directory

4. **Run the OAuth Setup Script**:
   ```bash
   uv run python scripts/setup_oauth.py
   ```
   - A browser window will open
   - Sign in with the Google account you want the bot to use
   - Grant the requested permissions
   - The script will save your token to `auth/oauth_token.json`

5. **Create a Google Drive Folder** for forms:
   - Create a folder in Google Drive (using the same account from step 4)
   - Navigate inside the folder in your browser
   - Copy the folder ID from the URL (the part after `/folders/`)
   - Set `BUSTY_GOOGLE_FORM_FOLDER` to this ID

Finally, add the bot to your desired Discord server.

The complete list of environment variable configuration options is:

1. `BUSTY_DISCORD_TOKEN` - Discord bot API token (required)
1. `BUSTY_GOOGLE_FORM_FOLDER` - Google Drive folder ID for voting form (optional, enables form generation)
1. `BUSTY_APPS_SCRIPT_URL` - Apps Script web app URL for automated sheet setup (optional)
1. `BUSTY_COOLDOWN_SECS` - Number of seconds between songs (default = 10)
1. `BUSTY_DATA_DIR` - Base directory for all bot data (default = data)
1. `BUSTY_AUTH_DIR` - Directory for authentication files (default = auth)
1. `BUSTY_DJ_ROLE` - Name of role with permissions to run commands (default = bangermeister)
1. `BUSTY_MAILBOX_PREFIX` - Channel name prefix for automatic preview detection. When users post audio/video attachments in channels whose names start with this prefix, the bot will automatically send a DM preview (unless the user has opted out via `/preferences mailbox-preview false`) showing what their "Now Playing" message will look like (default = bustys-mailbox-)
1. `BUSTY_CUSTOM_EMOJI_FILEPATH` - The Python module to import containing the emoji list (default = emoji_list)
1. `BUSTY_OPENAI_API_KEY` - OpenAI API key for AI features (optional)
1. `BUSTY_OPENAI_MODEL` - OpenAI model to use (default = gpt-3.5-turbo)
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
1. `/preview <attachment> [<submit_message>]` - Show a preview of the attachment's artist, title and artwork. Works in DMs and servers.
1. `/image upload <attachment>` - Upload an image to be used in the Google Form generated when running `/list`.
1. `/image url <url>` - Queue an image to be used in the Google Form generated when running `/list`.
1. `/image view` - View currently loaded image to be used in the Google Form generated when running `/list`.
1. `/image clear` - Clear currently loaded image to be used in the Google Form generated when running `/list`.
1. `/skip` - Skips the current track :scream:
1. `/stop` - Stop busting early :scream: :scream: :scream:

Users must have the `bangermeister` role to use commands by default, though this role can
be modified by passing the `BUSTY_DJ_ROLE` environment variable. Most commands are restricted
to servers only (won't appear in DMs), except `/preview` which works in both servers and DMs.
It is highly recommended that you disable command visibility for those without permissions to
run them in the Integrations section of your server's settings.

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
