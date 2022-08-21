from typing import Dict, Optional

from nextcord import Client, Intents, Member, Message, TextChannel

import bust
import config
import voting
from bust import BustController

# STARTUP

# This is necessary to query server members
intents = Intents.default()
# To fetch guild member information.
# Privileged intent. Requires enabling in Discord Developer Portal.
intents.members = True
# To be able to read message content.
intents.message_content = True

# Set up the Discord client. Connecting to Discord is done at
# the bottom of this file.
client = Client(intents=intents)

controllers: Dict[int, BustController] = {}


@client.event
async def on_ready() -> None:
    print("We have logged in as {0.user}.".format(client))


@client.event
async def on_close() -> None:
    # Finish all running busts on close
    for _, bc in controllers.items():
        await bc.finish(say_goodbye=False)


@client.event
async def on_message(message: Message) -> None:
    global controllers

    if message.author == client.user:
        return

    # Do not process messages outside of guild text channels
    if not isinstance(message.channel, TextChannel):
        return

    # The message author must be a guild member, so that we can
    # check if they have the appropriate role below
    if not isinstance(message.author, Member):
        return

    for role in message.author.roles:
        if role.name == config.dj_role_name:
            break
    else:
        # This message's author does not have appropriate permissions
        # to control the bot
        return

    # Allow commands to be case-sensitive and contain leading/following spaces
    message_text = message.content.lower().strip()

    bc: Optional[BustController] = controllers.get(message.guild.id, None)
    # TODO: Put these lines inside of `!bust` handler.
    # Once https://github.com/anoadragon453/busty/issues/123 is done, we can
    # keep the controllers map up to date by just deleting from
    # the controllers map directly when bc.play() returns
    if bc and bc.finished():
        del controllers[message.guild.id]
        bc = None

    # Determine if the message was a command
    if message_text.startswith("!list"):
        if bc and bc.active():
            await message.channel.send("We're busy busting.")
            return

        bc = await bust.create_controller(client, message)
        if bc:
            controllers[message.guild.id] = bc

    elif message_text.startswith("!bust"):
        if not bc:
            await message.channel.send("You need to use !list first.")
            return
        elif bc.active():
            await message.channel.send("We're already busting.")
            return

        command_args = message.content.split()[1:]
        skip_count = 0
        if command_args:
            try:
                # Expects a positive integer
                bust_index = int(command_args[0])
            except ValueError:
                await message.channel.send("That isn't a number.")
                return
            if bust_index < 0:
                await message.channel.send("That isn't possible.")
                return
            if bust_index == 0:
                await message.channel.send("We start from 1 around here.")
                return
            if bust_index > len(bc.current_channel_content):
                await message.channel.send("There aren't that many tracks.")
                return
            skip_count = bust_index - 1

        await bc.play(message, skip_count)

    elif message_text.startswith("!form"):
        if not bc:
            await message.channel.send("You need to use !list first.")
            return

        # Pull the Google Drive link to the form image from the message (if it exists)
        command_args = message.content.split()[1:]
        if command_args:
            await voting.generate_form(
                bc, message, google_drive_image_link=command_args[0]
            )
        else:
            await voting.generate_form(bc, message)

    elif message_text.startswith("!skip"):
        if not bc or not bc.active():
            await message.channel.send("Nothing is playing.")
            return

        await message.channel.send("I didn't like that track anyways.")
        bc.skip_song()

    elif message_text.startswith("!stop"):
        if not bc or not bc.active():
            await message.channel.send("I'm not busting.")
            return

        await message.channel.send("Alright I'll shut up.")
        await bc.stop()


# Connect to discord
if config.discord_token:
    client.run(config.discord_token)
else:
    print(
        "Please pass in a Discord bot token via the BUSTY_DISCORD_TOKEN environment variable."
    )
