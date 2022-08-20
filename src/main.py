import os

from nextcord import Client, Intents, Member, Message, TextChannel

import bust
import config
import voting

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
bust.client = client


@client.event
async def on_ready() -> None:
    print("We have logged in as {0.user}.".format(client))


@client.event
async def on_close() -> None:
    # Unpin current "now playing" message if it exists
    if bust.now_playing_msg:
        await bust.try_set_pin(bust.now_playing_msg, False)
    # Finish current bust (if exists) as if it were stopped
    await bust.finish_bust(say_goodbye=False)


@client.event
async def on_message(message: Message) -> None:
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

    # Determine if the message was a command
    if message_text.startswith("!list"):
        if bust.active_voice_client and bust.active_voice_client.is_connected():
            await message.channel.send("We're busy busting.")
            return

        command_success = "\N{THUMBS UP SIGN}"
        command_fail = "\N{OCTAGONAL SIGN}"

        # Ensure two scrapes aren't making/deleting files at the same time
        if bust.list_task_control_lock.locked():
            await message.add_reaction(command_fail)
            return

        await message.add_reaction(command_success)
        async with bust.list_task_control_lock:
            await bust.command_list(message)

    elif message_text.startswith("!bust"):
        if bust.active_voice_client and bust.active_voice_client.is_connected():
            await message.channel.send("We're already busting.")
            return

        if not bust.current_channel_content or not bust.current_channel:
            await message.channel.send("You need to use !list first.")
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
            if bust_index > len(bust.current_channel_content):
                await message.channel.send("There aren't that many tracks.")
                return
            skip_count = bust_index - 1

        await bust.command_play(message, skip_count)

    elif message_text.startswith("!form"):
        if not bust.current_channel_content or not bust.current_channel:
            await message.channel.send("You need to use !list first, sugar.")
            return

        # Pull the google drive link to the form image from the message (if it exists)
        command_args = message.content.split()[1:]
        if command_args:
            await voting.command_form(message, google_drive_image_link=command_args[0])
        else:
            await voting.command_form(message)

    elif message_text.startswith("!skip"):
        if not bust.active_voice_client or not bust.active_voice_client.is_playing():
            await message.channel.send("Nothing is playing.")
            return

        await message.channel.send("I didn't like that track anyways.")
        bust.command_skip()

    elif message_text.startswith("!stop"):
        if not bust.active_voice_client or not bust.active_voice_client.is_connected():
            await message.channel.send("I'm not busting.")
            return

        await message.channel.send("Alright I'll shut up.")
        await bust.command_stop()


# Connect to Discord. YOUR_BOT_TOKEN_HERE must be replaced with
# a valid Discord bot access token.
if "BUSTY_DISCORD_TOKEN" in os.environ:
    client.run(os.environ["BUSTY_DISCORD_TOKEN"])
else:
    print(
        "Please pass in a Discord bot token via the BUSTY_DISCORD_TOKEN environment variable."
    )
