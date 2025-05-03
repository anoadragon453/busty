import asyncio
import datetime
import json
import re
from typing import Dict, List, Optional, Tuple

import openai
import tiktoken
from nextcord import Client, Member, Message

import busty.bust as bust
import busty.config as config


# Initialize globals
def initialize(client: Client) -> None:
    global gpt_lock
    global context_data
    global encoding
    global self_user
    global banned_word_pattern
    global word_trigger_pattern
    global user_trigger_pattern
    global user_info_map
    global openai_async_client

    # Global lock for message response
    gpt_lock = asyncio.Lock()
    # Load manual hidden data
    try:
        with open(config.llm_context_file) as f:
            context_data = json.load(f)
    except (FileNotFoundError, json.decoder.JSONDecodeError) as e:
        print(
            f"ERROR: Issue loading {config.llm_context_file}. GPT capabilities will be disabled.\n{e}"
        )
        context_data = None
        return
    # Initialize OpenAI client
    openai_async_client = openai.AsyncOpenAI(api_key=config.openai_api_key)

    # Preload tokenizer
    encoding = tiktoken.encoding_for_model(config.openai_model)
    # Store bot user
    self_user = client.user
    # Cache regex for banned words
    banned_word_pattern = re.compile(
        r"\b{}\b".format("|".join(context_data["banned_phrases"]))
    )

    # Cache regex for word triggers
    word_trigger_pattern = re.compile(
        r"\b({})\b".format("|".join(context_data["word_triggers"].keys()))
    )

    # Cache regex for user info triggers
    user_trigger_pattern = re.compile(
        r"\b({})\b".format(
            "|".join(
                [
                    user["name"].lower()
                    for user in context_data["user_info"].values()
                    if "info" in user
                ]
            )
        )
    )
    # Store map for user info triggers
    user_info_map = {
        user["name"].lower(): user["info"].lower()
        for user in context_data["user_info"].values()
        if "info" in user and "name" in user
    }


# Check if a message's content should be allowed when feeding message history to the model
# Currently this is just if it contains banned phrases
def disallowed_message(message: Message) -> bool:
    return banned_word_pattern.search(message.content.lower()) is not None


# Get the name we should call the user
def get_name(user: Member) -> str:
    user_info = context_data["user_info"]
    id = str(user.id)
    if id in user_info and "name" in user_info[id]:
        return user_info[id]["name"]
    return user.name


# Get context about the server
async def get_server_context(message: Message) -> List[str]:
    result = []

    # Detect if song is currently playing
    if hasattr(message, "guild"):
        bc = bust.controllers.get(message.guild.id)
        if bc and bc.is_active():
            result.append("The bust is going on right now!")
            result.append(f"Now playing: {bc.current_song()}")
            result.append("Tell everyone you can't respond since you're busy busting.")

    # Load server event info
    if message.guild and message.guild.scheduled_events:
        # Get earliest scheduled event by start time
        # API doesn't seem to mention anywhere if they come sorted already
        next_event = min(
            message.guild.scheduled_events, key=lambda event: event.start_time
        )
        if ":" in next_event.name:
            event_num, event_topic = next_event.name.split(":", maxsplit=1)
            result.append(f"Next bust event: {event_num.strip()}")
            result.append(f"Next bust time: {next_event.start_time.strftime('%b %d')}")
            result.append(f"Bust topic: {event_topic.strip()}")
        else:
            result.append(f"Next event: {next_event.name}")
            result.append(f"Next event time: {next_event.start_time.strftime('%b %d')}")

        result.append(f"Today's date: {datetime.date.today().strftime('%b %d')}")

    user = get_name(message.author)

    # Role-based info
    if isinstance(message.author, Member):
        roles = {role.name for role in message.author.roles}

        # Provide champion info
        champ = [
            ("Defending Champion", "first"),
            ("Runner-up", "second"),
            ("Bronzer", "third"),
        ]
        for role, place in champ:
            if role in roles:
                result.append(f"{user}'s place last bust: {place}")
                break

    result.append(f"Talking to: {user}")

    return result


# Count tokens in a string
def token_count(data: str) -> int:
    return len(encoding.encode(data))


# Replace Discord-style mentions with names
def substitute_mentions(message: Message) -> str:
    content = message.content
    for user in message.mentions:
        content = content.replace(user.mention, get_name(user))
    for channel in message.channel_mentions:
        content = content.replace(channel.mention, channel.name)
    for role in message.role_mentions:
        content = content.replace(role.mention, role.name)
    return content


# Fetch message content from history up to a certain token allowance
async def fetch_history(
    token_limit: int, speaking_turn_limit: int, message: Message
) -> List[Tuple[str, bool]]:
    total_tokens = 0
    # A list of (str, bool) tuples containing:
    #     - "{message author}: {message content}"
    #     - True if the message was sent by the bot user, False otherwise
    history = []
    idx = 0
    one_hour = datetime.timedelta(hours=1)
    seen_message = False
    speaking_turn_count = 0
    last_author = None
    async for msg in message.channel.history():
        # Skip messages newer than what we're replying to
        seen_message = seen_message or (msg == message)
        if not seen_message:
            continue

        # Skip if message is disallowed
        if disallowed_message(msg):
            continue

        # Don't include messages which are both more than 3 back and an hour old
        # as the discussion has likely moved on.
        idx += 1
        timezone = message.created_at.tzinfo
        now = datetime.datetime.now(timezone)
        if idx > 3 and (now - message.created_at) > one_hour:
            break

        # Break if maximum number of speaking turns has been reached
        # We use turns instead of a simple message count as some people like to
        # break up their thoughts into many separate messages.
        if msg.author != last_author:
            speaking_turn_count += 1
            if speaking_turn_count > speaking_turn_limit:
                break
            last_author = msg.author

        # Add this message's author and content to the returned history
        msg_text = f"{get_name(msg.author)}: {substitute_mentions(msg)}"
        total_tokens += token_count(msg_text)
        if total_tokens > token_limit:
            break

        is_self = msg.author == self_user
        history.append((msg_text, is_self))
    return history


# Build context around a message
async def get_message_context(message: Message) -> List[str]:
    # build contexts
    static_context = context_data["static_context"]
    author_context = await get_server_context(message)
    return static_context + author_context


# Query the OpenAI API and return response
async def query_api(data: Dict) -> Optional[str]:
    try:
        response = await openai_async_client.chat.completions.create(
            model=config.openai_model,
            messages=data,
            timeout=10.0,
        )
        return response.choices[0].message.content

    except Exception as e:
        print("OpenAI API exception:", e)
        return None


def get_history_context(history: List[Tuple[str, bool]]) -> List[str]:
    # Load additional context from history
    word_triggers = set()
    user_triggers = set()
    for content, _ in history:
        for word in word_trigger_pattern.findall(content):
            word_triggers.add(word)
        for user in user_trigger_pattern.findall(content):
            user_triggers.add(user)
    # Return context about users + word triggers from history
    return [f"{user} info: {user_info_map[user]}" for user in user_triggers] + [
        context_data["word_triggers"][word] for word in word_triggers
    ]


# Make an api query
async def get_response_text(message: Message) -> Optional[str]:
    context = await get_message_context(message)
    if disallowed_message(message):
        # If message is disallowed (or the user is unlucky), pass a special instruction

        # Get user info (if available) as we're not passing history which would trigger it
        user = get_name(message.author)
        if user.lower() in user_info_map:
            context.append(f"{user}: {user_info_map[user.lower()]}")
        # Pass special instruction
        context.append(context_data["banned_phrase_instruction"])
        # Make up empty history so the bot understands how to format the response
        history = [(f"{self_user.name}:", True), (f"{user}:", False)]
    else:
        # Load history with 512 token limit and 5 speaking turn limit
        history = await fetch_history(512, 5, message)
        # We couldn't fit even a single message in history
        if not history:
            await message.reply("I'm not reading all that.")
            return

        context += get_history_context(history)

    # Send data to API
    data = []
    data.append({"role": "system", "content": "\n".join(context)})

    for msg, is_self in reversed(history):
        role = "assistant" if is_self else "user"
        data.append({"role": role, "content": msg})

    response = await query_api(data)
    if response:
        # Remove "Busty: " prefix
        prefix = f"{get_name(self_user)}: "
        if response.startswith(prefix):
            response = response[len(prefix) :]

        return response

    await message.reply("busy rn")
    return None


async def respond(message: Message) -> None:
    # React with a "stop" hand, we're responding to someone else
    if gpt_lock.locked() or not context_data:
        raised_hand_emoji = "\N{RAISED HAND}\U0001f3ff"
        await message.add_reaction(raised_hand_emoji)
        return

    # Respond to message
    async with gpt_lock:
        async with message.channel.typing():
            response = await get_response_text(message)
        if response:
            response_split = [
                response[i : i + config.MESSAGE_LIMIT]
                for i in range(0, len(response), config.MESSAGE_LIMIT)
            ]
            # Reply to the message if it's not the most recent one in the chat history
            most_recent_message = [
                msg async for msg in message.channel.history(limit=1)
            ][0]
            for idx, text in enumerate(response_split):
                if idx == 0 and message != most_recent_message:
                    await message.reply(response)
                else:
                    await message.channel.send(response)


async def generate_album_art(
    artist: str, title: str, description: Optional[str]
) -> Optional[str]:
    """Generate album art given song metadata"""
    prompt = [
        "Generate bizarre photorealistic album art for the following song.",
        f"{artist} - {title}\n",
    ]
    if description:
        prompt.append(
            # Cap the description to 1000 characters, to avoid going over any token limits.
            f"Here is how the artist describes the song: {description[:1000]}"
        )
    return await generate_image("\n".join(prompt))


# Generate any image with DALL-E 3 given a text prompt
async def generate_image(prompt: str) -> Optional[str]:
    """Generate any image with DALL-E 3 given a text prompt"""
    try:
        response = await openai_async_client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size="1024x1024",
            quality="standard",
            n=1,
        )
    except Exception as e:
        print("OpenAI API exception:", e)
        return None
    return response.data[0].url
