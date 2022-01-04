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

You'll need to create a Discord app, add a bot component, and copy the bot token. Replace the
`YOUR_BOT_TOKEN_HERE` at the bottom of `main.py` with that token.

Then, add the bot to your desired Discord server.

You can optionally tweak some of the bot's settings and behaviour by modifying the variables
at the top of `main.py`.

## Run

Start the bot with:

```
python main.py
```

It should connect to Discord and display the currently logged-in application name.

## Command reference

1. `!list` - download and list all media files in the text channel this is used in. This needs to be run before `!bust` can be.
2. `!bust` - Join the vc/stage that the user who ran this command is currently in, and plays the tracks in the channel in order. The user must be in a vc or stage for this to work.
3. `!skip` - skips the current track :scream: 
4. `!stop` - stop busting early :scream: :scream: :scream: 

Users must have the `bangermeister` role to use commands. This can be modified by
editing the appropriate variable at the top of `main.py`.
