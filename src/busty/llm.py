import asyncio
import datetime
import json
import logging
import re
from typing import TYPE_CHECKING, Any, cast

import openai
import tiktoken
from discord import ClientUser, Member, Message, User

from busty.config import constants

if TYPE_CHECKING:
    from busty.config.settings import BustySettings
    from busty.main import BustyBot

logger = logging.getLogger(__name__)

# Global variables
gpt_lock: asyncio.Lock | None = None
context_data: dict | None = None
encoding: tiktoken.Encoding | None = None
self_user: User | Member | ClientUser | None = None
self_client: "BustyBot | None" = None
banned_word_pattern: re.Pattern | None = None
word_trigger_pattern: re.Pattern | None = None
user_trigger_pattern: re.Pattern | None = None
user_info_map: dict[str, str] | None = None
openai_async_client: openai.AsyncOpenAI | None = None
openai_model: str | None = None


# Initialize globals
def initialize(client: "BustyBot", settings: "BustySettings") -> None:
    """Initialize LLM features with the given settings.

    Args:
        client: The BustyBot client instance.
        settings: The bot settings containing OpenAI configuration.
    """
    global gpt_lock
    global context_data
    global encoding
    global self_user
    global self_client
    global banned_word_pattern
    global word_trigger_pattern
    global user_trigger_pattern
    global user_info_map
    global openai_async_client
    global openai_model

    # Global lock for message response
    gpt_lock = asyncio.Lock()
    # Load manual hidden data
    try:
        with open(settings.llm_context_file) as f:
            context_data = json.load(f)
    except (FileNotFoundError, json.decoder.JSONDecodeError) as e:
        logger.error(
            f"Issue loading {settings.llm_context_file}. GPT capabilities will be disabled: {e}"
        )
        context_data = None
        return
    # Initialize OpenAI client
    openai_async_client = openai.AsyncOpenAI(api_key=settings.openai_api_key)

    # Store OpenAI model
    openai_model = settings.openai_model

    # Preload tokenizer
    encoding = tiktoken.encoding_for_model(openai_model)
    # Store bot user and client
    self_user = client.user
    self_client = client
    # Cache regex for banned words
    if context_data is not None:
        banned_word_pattern = re.compile(
            rf"\b{'|'.join(context_data['banned_phrases'])}\b"
        )

        # Cache regex for word triggers
        word_trigger_pattern = re.compile(
            rf"\b({'|'.join(context_data['word_triggers'].keys())})\b"
        )

        # Cache regex for user info triggers
        user_trigger_pattern = re.compile(
            rf"\b({'|'.join([user['name'].lower() for user in context_data['user_info'].values() if 'info' in user])})\b"
        )
        # Store map for user info triggers
        user_info_map = {
            user["name"].lower(): user["info"].lower()
            for user in context_data["user_info"].values()
            if "info" in user and "name" in user
        }
    else:
        banned_word_pattern = None
        word_trigger_pattern = None
        user_trigger_pattern = None
        user_info_map = None

    logger.info(f"LLM features initialized successfully with model {openai_model}")


# Check if a message's content should be allowed when feeding message history to the model
# Currently this is just if it contains banned phrases
def disallowed_message(message: Message) -> bool:
    if banned_word_pattern is None:
        return False
    return banned_word_pattern.search(message.content.lower()) is not None


# Get the name we should call the user
def get_name(user: User | Member | ClientUser) -> str:
    if context_data is None:
        return cast(str, user.name)
    user_info = context_data["user_info"]
    id = str(user.id)
    if id in user_info and "name" in user_info[id]:
        return cast(str, user_info[id]["name"])
    return cast(str, user.name)


# Get context about the server
async def get_server_context(message: Message) -> list[str]:
    result = []

    # Detect if song is currently playing
    if hasattr(message, "guild") and message.guild and self_client:
        bc = self_client.bust_registry.get(message.guild.id)
        if bc and bc.is_playing:
            result.append("The bust is going on right now!")
            current_track = bc.current_track
            if current_track:
                result.append(f"Now playing: {current_track.formatted_title}")
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
    if encoding is None:
        return len(data.split())  # Fallback to word count
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
    return cast(str, content)


# Fetch message content from history up to a certain token allowance
async def fetch_history(
    token_limit: int, speaking_turn_limit: int, message: Message
) -> list[tuple[str, bool]]:
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
async def get_message_context(message: Message) -> list[str]:
    if context_data is None:
        return []
    # build contexts
    static_context = context_data["static_context"]
    author_context = await get_server_context(message)
    return cast(list[str], static_context + author_context)


# Query the OpenAI API and return response
async def query_api(data: list[dict[str, str]]) -> str | None:
    if openai_async_client is None:
        return None
    try:
        # Convert the data to the proper format for OpenAI API
        messages: list[Any] = []
        for item in data:
            messages.append({"role": item["role"], "content": item["content"]})

        response = await openai_async_client.chat.completions.create(
            model=openai_model if openai_model else "gpt-3.5-turbo",
            messages=messages,
            timeout=10.0,
        )
        return cast(str, response.choices[0].message.content)

    except Exception as e:
        logger.error(f"OpenAI API exception: {e}")
        return None


def get_history_context(history: list[tuple[str, bool]]) -> list[str]:
    if (
        context_data is None
        or word_trigger_pattern is None
        or user_trigger_pattern is None
        or user_info_map is None
    ):
        return []
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
async def get_response_text(message: Message) -> str | None:
    if context_data is None or self_user is None:
        return None
    context = await get_message_context(message)
    if disallowed_message(message):
        # If message is disallowed (or the user is unlucky), pass a special instruction

        # Get user info (if available) as we're not passing history which would trigger it
        user = get_name(message.author)
        if user_info_map and user.lower() in user_info_map:
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
            return None

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
    if gpt_lock is None or gpt_lock.locked() or context_data is None:
        raised_hand_emoji = "\N{RAISED HAND}\U0001f3ff"
        await message.add_reaction(raised_hand_emoji)
        return

    # Respond to message
    async with gpt_lock:
        async with message.channel.typing():
            response = await get_response_text(message)
        if response:
            response_split = [
                response[i : i + constants.MESSAGE_LIMIT]
                for i in range(0, len(response), constants.MESSAGE_LIMIT)
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
    artist: str, title: str, description: str | None
) -> str | None:
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
async def generate_image(prompt: str) -> str | None:
    """Generate any image with DALL-E 3 given a text prompt"""
    if openai_async_client is None:
        return None
    try:
        response = await openai_async_client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size="1024x1024",
            quality="standard",
            n=1,
        )
    except Exception as e:
        logger.error(f"OpenAI API exception: {e}")
        return None
    return cast(str, response.data[0].url) if response.data else None
