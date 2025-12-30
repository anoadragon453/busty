"""Chat service for Discord bot LLM interactions.

This module handles high-level chat orchestration including:
- Message context building
- History fetching and token management
- Response formatting and delivery
- Concurrent request handling
"""

import asyncio
import datetime
import json
import logging
import re
from typing import TYPE_CHECKING, cast

import tiktoken
from discord import ClientUser, Member, Message, User

from busty.ai.protocols import AIService
from busty.config import constants
from busty.config.settings import BustySettings

if TYPE_CHECKING:
    from busty.bot import BustyBot

logger = logging.getLogger(__name__)


class ChatService:
    """Manages LLM chat interactions."""

    def __init__(
        self,
        ai_service: AIService,
        client: "BustyBot",
        settings: BustySettings,
    ):
        """Initialize the chat service.

        Args:
            ai_service: AI backend for chat completions.
            client: Discord bot client.
            settings: Bot configuration.
        """
        self._ai_service = ai_service
        self._client = client
        self._settings = settings

        # Concurrency lock for response handling
        self._lock = asyncio.Lock()

        # Token counter
        self._encoding = tiktoken.encoding_for_model(settings.openai_tokenizer_model)

        # Load context data
        self._context_data = self._load_context_data()

        # Compile regex patterns
        self._banned_word_pattern: re.Pattern | None = None
        self._word_trigger_pattern: re.Pattern | None = None
        self._user_trigger_pattern: re.Pattern | None = None
        self._user_info_map: dict[str, str] = {}

        if self._context_data:
            self._compile_patterns()

    @property
    def is_configured(self) -> bool:
        """Check if chat service is properly configured."""
        return self._context_data is not None

    def _load_context_data(self) -> dict | None:
        """Load context data from configuration file."""
        try:
            with open(self._settings.llm_context_file) as f:
                return json.load(f)
        except (FileNotFoundError, json.decoder.JSONDecodeError) as e:
            logger.error(
                f"Issue loading {self._settings.llm_context_file}. "
                f"Chat capabilities will be disabled: {e}"
            )
            return None

    def _compile_patterns(self) -> None:
        """Compile regex patterns from context data."""
        if self._context_data is None:
            return

        self._banned_word_pattern = re.compile(
            rf"\b{'|'.join(self._context_data['banned_phrases'])}\b"
        )

        self._word_trigger_pattern = re.compile(
            rf"\b({'|'.join(self._context_data['word_triggers'].keys())})\b"
        )

        self._user_trigger_pattern = re.compile(
            rf"\b({'|'.join([user['name'].lower() for user in self._context_data['user_info'].values() if 'info' in user])})\b"
        )

        self._user_info_map = {
            user["name"].lower(): user["info"].lower()
            for user in self._context_data["user_info"].values()
            if "info" in user and "name" in user
        }

    async def respond(self, message: Message) -> None:
        """Respond to a Discord message.

        Handles concurrency (only one response at a time) and
        all the Discord-specific response formatting.
        """
        if not self.is_configured:
            return

        # React with "stop" hand if we're already responding
        if self._lock.locked():
            raised_hand_emoji = "\N{RAISED HAND}\U0001f3ff"
            await message.add_reaction(raised_hand_emoji)
            return

        async with self._lock:
            async with message.channel.typing():
                response = await self._get_response_text(message)
            if response:
                await self._send_response(message, response)

    async def _get_response_text(self, message: Message) -> str | None:
        """Generate response text for a message."""
        if self._context_data is None or self._client.user is None:
            return None

        context = await self._get_message_context(message)

        if self._disallowed_message(message):
            # If message is disallowed, pass a special instruction
            user = self._get_name(message.author)
            if self._user_info_map and user.lower() in self._user_info_map:
                context.append(f"{user}: {self._user_info_map[user.lower()]}")
            # Pass special instruction
            context.append(self._context_data["banned_phrase_instruction"])
            # Make up empty history so the bot understands how to format the response
            history = [(f"{self._client.user.name}:", True), (f"{user}:", False)]
        else:
            # Load history with 512 token limit and 5 speaking turn limit
            history = await self._fetch_history(512, 5, message)
            # We couldn't fit even a single message in history
            if not history:
                await message.reply("I'm not reading all that.")
                return None

            context += self._get_history_context(history)

        # Send data to API
        data = []
        data.append({"role": "system", "content": "\n".join(context)})

        for msg, is_self in reversed(history):
            role = "assistant" if is_self else "user"
            data.append({"role": role, "content": msg})

        response = await self._ai_service.complete_chat(data)
        if response:
            # Remove "Busty: " prefix (or bot's custom name prefix)
            prefix = f"{self._get_name(self._client.user)}: "
            if response.startswith(prefix):
                response = response[len(prefix) :]

            return response

        await message.reply("busy rn")
        return None

    async def _send_response(self, message: Message, response: str) -> None:
        """Send response to Discord, handling length limits."""
        response_split = [
            response[i : i + constants.MESSAGE_LIMIT]
            for i in range(0, len(response), constants.MESSAGE_LIMIT)
        ]

        most_recent_message = [msg async for msg in message.channel.history(limit=1)][0]

        for idx, text in enumerate(response_split):
            if idx == 0 and message != most_recent_message:
                await message.reply(text)
            else:
                await message.channel.send(text)

    def _disallowed_message(self, message: Message) -> bool:
        """Check if message content is disallowed.

        Currently checks if it contains banned phrases.
        """
        if self._banned_word_pattern is None:
            return False
        return self._banned_word_pattern.search(message.content.lower()) is not None

    def _get_name(self, user: User | Member | ClientUser) -> str:
        """Get the name we should call the user."""
        if self._context_data is None:
            return cast(str, user.name)

        user_info = self._context_data["user_info"]
        user_id = str(user.id)
        if user_id in user_info and "name" in user_info[user_id]:
            return cast(str, user_info[user_id]["name"])
        return cast(str, user.name)

    async def _get_server_context(self, message: Message) -> list[str]:
        """Build context about server state (bust status, events, user roles)."""
        result = []

        # Detect if song is currently playing
        if hasattr(message, "guild") and message.guild:
            bc = self._client.bust_registry.get(message.guild.id)
            if bc and bc.is_playing:
                result.append("The bust is going on right now!")
                current_track = bc.current_track
                if current_track:
                    result.append(f"Now playing: {current_track.formatted_title}")
                result.append(
                    "Tell everyone you can't respond since you're busy busting."
                )

        # Load server event info
        if message.guild and message.guild.scheduled_events:
            # Get earliest scheduled event by start time
            next_event = min(
                message.guild.scheduled_events, key=lambda event: event.start_time
            )
            if ":" in next_event.name:
                event_num, event_topic = next_event.name.split(":", maxsplit=1)
                result.append(f"Next bust event: {event_num.strip()}")
                result.append(
                    f"Next bust time: {next_event.start_time.strftime('%b %d')}"
                )
                result.append(f"Bust topic: {event_topic.strip()}")
            else:
                result.append(f"Next event: {next_event.name}")
                result.append(
                    f"Next event time: {next_event.start_time.strftime('%b %d')}"
                )

            result.append(f"Today's date: {datetime.date.today().strftime('%b %d')}")

        user = self._get_name(message.author)

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

    def _token_count(self, data: str) -> int:
        """Count tokens in a string."""
        if self._encoding is None:
            return len(data.split())  # Fallback to word count
        return len(self._encoding.encode(data))

    def _substitute_mentions(self, message: Message) -> str:
        """Replace Discord-style mentions with names."""
        content = message.content
        for user in message.mentions:
            content = content.replace(user.mention, self._get_name(user))
        for channel in message.channel_mentions:
            content = content.replace(channel.mention, channel.name)
        for role in message.role_mentions:
            content = content.replace(role.mention, role.name)
        return cast(str, content)

    async def _fetch_history(
        self, token_limit: int, speaking_turn_limit: int, message: Message
    ) -> list[tuple[str, bool]]:
        """Fetch message content from history up to a certain token allowance.

        Args:
            token_limit: Maximum tokens to include from history.
            speaking_turn_limit: Maximum number of speaking turns to include.
            message: The message being responded to.

        Returns:
            List of (message_text, is_self) tuples.
        """
        total_tokens = 0
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
            if self._disallowed_message(msg):
                continue

            # Don't include messages which are both more than 3 back and an hour old
            # as the discussion has likely moved on
            idx += 1
            timezone = message.created_at.tzinfo
            now = datetime.datetime.now(timezone)
            if idx > 3 and (now - message.created_at) > one_hour:
                break

            # Break if maximum number of speaking turns has been reached
            if msg.author != last_author:
                speaking_turn_count += 1
                if speaking_turn_count > speaking_turn_limit:
                    break
                last_author = msg.author

            # Add this message's author and content to the returned history
            msg_text = f"{self._get_name(msg.author)}: {self._substitute_mentions(msg)}"
            total_tokens += self._token_count(msg_text)
            if total_tokens > token_limit:
                break

            is_self = msg.author == self._client.user
            history.append((msg_text, is_self))

        return history

    async def _get_message_context(self, message: Message) -> list[str]:
        """Build full context for a message."""
        if self._context_data is None:
            return []

        static_context = self._context_data["static_context"]
        author_context = await self._get_server_context(message)
        return cast(list[str], static_context + author_context)

    def _get_history_context(self, history: list[tuple[str, bool]]) -> list[str]:
        """Extract additional context from history (word triggers, user triggers)."""
        if (
            self._context_data is None
            or self._word_trigger_pattern is None
            or self._user_trigger_pattern is None
            or self._user_info_map is None
        ):
            return []

        # Load additional context from history
        word_triggers = set()
        user_triggers = set()
        for content, _ in history:
            for word in self._word_trigger_pattern.findall(content):
                word_triggers.add(word)
            for user in self._user_trigger_pattern.findall(content):
                user_triggers.add(user)

        # Return context about users + word triggers from history
        return [
            f"{user} info: {self._user_info_map[user]}" for user in user_triggers
        ] + [self._context_data["word_triggers"][word] for word in word_triggers]
