from typing import Dict, Optional

from nextcord import Client, Intents, Member, Message, TextChannel

import bust
import config
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

# Cached image to use for next bust
loaded_image: Optional[str] = None


@client.event
async def on_ready() -> None:
    print("We have logged in as {0.user}.".format(client))


@client.event
async def on_close() -> None:
    # Finish all running busts on close
    for bc in controllers.values():
        await bc.finish(say_goodbye=False)


@client.event
async def on_message(message: Message) -> None:
    global controllers
    global loaded_image

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

    bc = controllers.get(message.guild.id, None)
    # TODO: Put these lines inside of `!bust` handler.
    # Once https://github.com/anoadragon453/busty/issues/123 is done, we can
    # keep the controllers map up to date by just deleting from
    # the controllers map directly when bc.play() returns
    if bc and bc.finished():
        del controllers[message.guild.id]
        bc = None

    # Determine if the message was a command
    if message_text.startswith("!list"):
        if bc and bc.is_active():
            await message.channel.send("We're busy busting.")
            return

        bc = await bust.create_controller(client, message, loaded_image)
        if bc:
            controllers[message.guild.id] = bc

    elif message_text.startswith("!bust"):
        if not bc:
            await message.channel.send("You need to use !list first.")
            return
        elif bc.is_active():
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

    elif message_text.startswith("!image"):
        message_split = message.content.split()
        if len(message_split) > 1:
            arg1 = message_split[1]
            # See if it's a clear command or giving a URL
            if arg1 == "clear":
                loaded_image = None
            else:
                loaded_image = arg1
            await message.add_reaction(config.COMMAND_SUCCESS_EMOJI)
        elif len(message.attachments) > 0:
            # TODO: Some basic validity filtering
            loaded_image = message.attachments[0].url
            await message.add_reaction(config.COMMAND_SUCCESS_EMOJI)
        else:
            if loaded_image is not None:
                message_reply_content = (
                    f"Loaded image: {loaded_image}\n\nTo change this image, "
                    "either run `!image <image_url>` or"
                    " just `!image` with a valid media attachment. "
                    "To clear this image, run `!image clear`"
                )
            else:
                message_reply_content = (
                    "No image is currently loaded.\n\nTo add an image, "
                    "either run `!image <image_url>` or"
                    " just `!image` with a valid media attachment.\n"
                )
            await message.channel.send(message_reply_content)

    elif message_text.startswith("!skip"):
        if not bc or not bc.is_active():
            await message.channel.send("Nothing is playing.")
            return

        await message.channel.send("I didn't like that track anyways.")
        bc.skip_song()

    elif message_text.startswith("!stop"):
        if not bc or not bc.is_active():
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
