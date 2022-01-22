# Busty

Discord bot used for the Busty server.

## Install

You'll need at least Python 3.6 and [ffmpeg](https://ffmpeg.org/) installed.

Create a python virtual environment to install python dependencies in.

```
python3 -m venv env
source env/bin/activate
```

And install the dependencies:

```
pip install -r requirements.txt
```

## Configure

You'll need to create a Discord app, add a bot component, and copy the bot token.
Ensure that the environment variable `BUSTY_DISCORD_TOKEN` contains the bot token when running the bot.
Then, add the bot to your desired Discord server.

The complete list of environment variable configuration options is
1. `BUSTY_DISCORD_TOKEN` - Discord bot API token (required)
2. `BUSTY_COOLDOWN_SECS` - Number of seconds between songs (default = 10)
3. `BUSTY_ATTACHMENT_DIR` - Directory to save attachments (default = attachments)
4. `BUSTY_DJ_ROLE` - Name of role with permissions to run commands (default = bangermeister)
5. `BUSTY_CUSTOM_EMOJI_FILEPATH` - The path to a file containing a custom list of emoji to display.

A random emoji is displayed for each song played during a bust. The list of possible
emoji is defined in [emoji_list.py](emoji_list.py). If you would like to customize
this list, simply copy the file, edit it, and set `BUSTY_CUSTOM_EMOJI_FILEPATH` to
the path of the new file.

## Run

With the proper environment variables set, start the bot with:

```
python main.py
```

It should connect to Discord and display the currently logged-in application name.

## Command reference

1. `!list [<channel>]` - download and list all media sent in the current text channel. Specifying a channel will cause songs to be pulled from that channel instead. This must be run before `!bust`.
1. `!bust` - Join the vc/stage that the user who ran this command is currently in, and plays the tracks in the channel in order. The user must be in a vc or stage for this to work.
1. `!skip` - skips the current track :scream: 
1. `!stop` - stop busting early :scream: :scream: :scream: 

Users must have the `bangermeister` role to use commands by default, though this role can
be modified by passing the `BUSTY_DJ_ROLE` environment variable.
