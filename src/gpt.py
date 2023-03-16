import datetime
import json
import re
from typing import List, Optional, Tuple

import openai
import tiktoken
from nextcord import Member, Message, TextChannel

import config


def initialize(client):
    global context_data
    global encoding
    global self_user

    openai.api_key = config.openai_api_key
    with open("context.json") as f:
        context_data = json.load(f)
    encoding = tiktoken.encoding_for_model(config.OPENAI_MODEL)
    self_user = client.user


def get_name(user):
    user_info = context_data["user_info"]
    id = str(user.id)
    if id in user_info and "name" in user_info[id]:
        return user_info[id]["name"]
    return user.name


async def get_author_context(message: Message) -> str:
    result = []
    # Load server event info if message.guild and message.guild.scheduled_events:
    # No idea if these are sorted by time
    next_event = message.guild.scheduled_events[0]
    result.append(f"Next bust number and topic: {next_event.name}")
    result.append(f"Next bust time: {next_event.start_time.strftime('%b %d')}")

    # Role-based info
    if isinstance(message.author, Member):
        roles = {role.name for role in message.author.roles}

        # Provide pronoun info
        pronouns = ["he/him", "they/them", "she/her", "any pronouns"]
        pronouns = [p for p in pronouns if p in roles]
        if pronouns:
            result.append("User's pronouns: " + (", ".join(pronouns)))

        # Provide champion info
        champ = ["Defending Champion", "Runner-up", "Bronzer"]
        for place, role in enumerate(champ, 1):
            if role in roles:
                result.append(f"User's place last bust: {place}")
                break

    user = get_name(message.author)
    result.append(f"Talking to: {user}")
    # Bespoke user info
    user_info = context_data["user_info"]
    id = str(message.author.id)
    if id in user_info and "info" in user_info[id]:
        result.append(f"About {user}: {user_info[id]['info']}")

    return result


def get_optional_context(content):
    # tokenize into successive strings of alphanumeric characters
    tokens = set(re.split(r"\W+", content.lower()))
    context = []
    for token in tokens:
        if token in context_data["word_triggers"]:
            context.append(context_data["word_triggers"][token])
    return context


# Count tokens in a string
def token_count(data: str) -> int:
    return len(encoding.encode(data))


# Replace Discord-style mentions with names
def strip_mentions(message: Message) -> str:
    content = message.content
    for user in message.mentions:
        content = content.replace(user.mention, get_name(user))
    return content


# Fetch messages from history up to a certain token allowance
async def fetch_history(
    token_allowance: int, channel: TextChannel
) -> List[Tuple[str, bool]]:
    total_tokens = 0
    messages = []
    async for idx, message in enumerate(channel.history()):
        # Don't include messages which are both more than 3 back and an hour old
        if idx >= 3 and (datetime.datetime.now() - message.created_at) > 3600:
            break
        msg = f"{get_name(message.author)}: {strip_mentions(message)}"
        total_tokens += token_count(msg)
        if total_tokens > token_allowance:
            break
        else:
            is_self = message.author == self_user
            messages.append((msg, is_self))
    return messages


async def query_api(message: Message) -> Optional[str]:
    # Replace mentions with names
    content = strip_mentions(message)

    # build contexts
    static_context = context_data["static_context"]
    author_context = await get_author_context(message)
    optional_context = get_optional_context(content)
    context = "\n".join(static_context + author_context + optional_context)

    token_allowance = config.GPT_REQUEST_TOKEN_LIMIT - token_count(context)
    history = await fetch_history(token_allowance, message.channel)
    # We couldn't git even a single message in history
    if not history:
        message.reply("I'm not reading all that.")

    # Send data to API
    data = [
        {"role": "system", "content": context},
    ]
    for message, is_self in reversed(history):
        role = "assistant" if is_self else "user"
        data.append({"role": role, "content": message})

    print(data)
    print("=================")
    try:
        response = await openai.ChatCompletion.acreate(
            model=config.OPENAI_MODEL, messages=data
        )
        text = response["choices"][0]["message"]["content"]
        # Remove "Busty: " prefix
        prefix = f"{get_name(self_user)}: "
        if text.startswith(prefix):
            text = text[len(prefix) :]
        return text
    except Exception as e:
        message.reply("busy rn")
        print(e)
    return None


async def reply(message: Message):
    async with message.channel.typing():
        response = await query_api(message)

    if response:
        await message.reply(response)
