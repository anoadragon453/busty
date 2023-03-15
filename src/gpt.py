import json
import re
from typing import Optional

import openai
from nextcord import Member, Message

import config

openai.api_key = config.openai_api_key

with open("context.json") as f:
    context_data = json.load(f)


def get_name(user):
    user_info = context_data["user_info"]
    id = str(user.id)
    if id in user_info and "name" in user_info[id]:
        return user_info[id]["name"]
    return user.name


async def get_author_context(message: Message) -> str:
    result = []
    # Load server event info
    if message.guild and message.guild.scheduled_events:
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

    # Bespoke user info
    user_info = context_data["user_info"]
    id = str(message.author.id)
    if id in user_info and "info" in user_info[id]:
        result.append(f"User info: {user_info[id]['info']}")

    result.append(f"Talking to user: {get_name(message.author)}")

    return result


def get_optional_context(content):
    # tokenize into successive strings of alphanumeric characters
    tokens = set(re.split(r"\W+", content.lower()))
    context = []
    for token in tokens:
        if token in context_data["word_triggers"]:
            context.append(context_data["word_triggers"][token])
    return context


async def query_api(message: Message) -> Optional[str]:
    # Replace mentions with names
    content = message.content
    for user in message.mentions:
        content = content.replace(user.mention, get_name(user))

    # build contexts
    static_context = context_data["static_context"]
    author_context = await get_author_context(message)
    optional_context = get_optional_context(content)
    context = "\n".join(static_context + author_context + optional_context)

    # Send data to API
    print(f"{context}\n{content}\n============\n")
    data = [
        {"role": "system", "content": context},
        {"role": "user", "content": content},
    ]

    response = openai.ChatCompletion.create(model=config.OPENAI_MODEL, messages=data)
    try:
        return response["choices"][0]["message"]["content"]
    except Exception as e:
        print(e)
    return None


async def reply(message: Message):
    async with message.channel.typing():
        # Preprocess message
        response = await query_api(message)

    if response:
        await message.reply(response)
    else:
        await message.reply("busy rn")
