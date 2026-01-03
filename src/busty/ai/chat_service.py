"""Chat service for Discord bot LLM interactions.

This module handles high-level chat orchestration including:
- Message context building with inline metadata
- Function calling for action selection (respond/react/both/ignore)
- History fetching and token management
- Response formatting and delivery
- Concurrent request handling
"""

import asyncio
import datetime
import json
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import tiktoken
import yaml
from discord import ClientUser, Member, Message, User

from busty.ai.protocols import AIService
from busty.config import constants
from busty.config.settings import BustySettings

if TYPE_CHECKING:
    from busty.bot import BustyBot

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UserInfo:
    """Information about a Discord user."""

    name: str
    info: str | None = None


@dataclass(frozen=True)
class LLMContextData:
    """Structured context data loaded from llm_context.yaml."""

    static_context: list[str]
    word_triggers: dict[str, str]
    user_info: dict[str, UserInfo]

    @staticmethod
    def from_dict(data: dict) -> "LLMContextData":
        """Parse raw YAML dict into structured context data.

        Args:
            data: Raw dict loaded from YAML file.

        Returns:
            Structured LLMContextData instance.

        Raises:
            ValueError: If required fields are missing or invalid.
        """
        # Validate required fields
        required_fields = [
            "static_context",
            "word_triggers",
            "user_info",
        ]
        missing = [f for f in required_fields if f not in data]
        if missing:
            raise ValueError(
                f"Missing required fields in llm_context.yaml: {', '.join(missing)}"
            )

        # Parse user_info dict
        user_info = {}
        for user_id, user_data in data["user_info"].items():
            if not isinstance(user_data, dict):
                logger.warning(
                    f"Invalid user_info entry for {user_id}: expected dict, got {type(user_data)}"
                )
                continue

            # User must have a name
            if "name" not in user_data:
                logger.warning(f"User {user_id} missing 'name' field, skipping")
                continue

            user_info[user_id] = UserInfo(
                name=user_data["name"], info=user_data.get("info")
            )

        return LLMContextData(
            static_context=data["static_context"],
            word_triggers=data["word_triggers"],
            user_info=user_info,
        )


# Tool definitions for function calling
# NOTE: These descriptions are intentionally casual/lowercase to match Busty's personality.
# The LLM reads these descriptions when choosing actions, so formal tool descriptions
# would make it "think" in a formal/robotic way. Casual descriptions reinforce the
# human-like Discord user persona and influence more natural action selection.
CHAT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "send_message",
            "strict": True,
            "description": "just send a normal message, like you're chatting casually on discord",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "what you want to say",
                    }
                },
                "required": ["content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_reactions",
            "strict": True,
            "description": "just react with emoji(s), no words. like when someone says something and you just hit them with a 👍 or whatever. good for quick vibes without typing",
            "parameters": {
                "type": "object",
                "properties": {
                    "emojis": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "emoji to react with, like ['👍', '❤️'] or whatever fits",
                        "minItems": 1,
                    }
                },
                "required": ["emojis"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_message_and_react",
            "strict": True,
            "description": "send a message AND react to really emphasize. like when you reply to something funny/exciting and also add emojis for extra energy",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "what you want to say"},
                    "emojis": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "emoji to react with",
                        "minItems": 1,
                    },
                },
                "required": ["content", "emojis"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ignore",
            "strict": True,
            "description": "don't respond or react at all. just lurk. use this when people are having their own conversation, or when the message doesn't really need your input, or you just don't feel like saying anything",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
]


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
        self._word_trigger_pattern: re.Pattern | None = None
        self._user_trigger_pattern: re.Pattern | None = None
        self._user_info_map: dict[str, str] = {}

        if self._context_data:
            self._compile_patterns()

    @property
    def is_configured(self) -> bool:
        """Check if chat service is properly configured."""
        return self._context_data is not None

    def _load_context_data(self) -> LLMContextData | None:
        """Load and parse context data from YAML configuration file.

        Returns:
            Structured LLMContextData if successful, None if loading/parsing failed.
        """
        try:
            with open(self._settings.llm_context_file) as f:
                raw_data = yaml.safe_load(f)

            if raw_data is None:
                logger.error(f"{self._settings.llm_context_file} is empty")
                return None

            return LLMContextData.from_dict(raw_data)

        except FileNotFoundError:
            logger.error(
                f"Config file not found: {self._settings.llm_context_file}. "
                "Chat capabilities will be disabled."
            )
            return None
        except yaml.YAMLError as e:
            logger.error(
                f"YAML parsing error in {self._settings.llm_context_file}: {e}. "
                "Chat capabilities will be disabled."
            )
            return None
        except ValueError as e:
            logger.error(
                f"Invalid config format in {self._settings.llm_context_file}: {e}. "
                "Chat capabilities will be disabled."
            )
            return None

    def _compile_patterns(self) -> None:
        """Compile regex patterns from context data."""
        if self._context_data is None:
            return

        self._word_trigger_pattern = re.compile(
            rf"\b({'|'.join(self._context_data.word_triggers.keys())})\b"
        )

        # Build pattern for user names that have info
        user_names_with_info = [
            user.name.lower()
            for user in self._context_data.user_info.values()
            if user.info is not None
        ]
        if user_names_with_info:
            self._user_trigger_pattern = re.compile(
                rf"\b({'|'.join(user_names_with_info)})\b"
            )

        self._user_info_map = {
            user.name.lower(): user.info.lower()
            for user in self._context_data.user_info.values()
            if user.info is not None
        }

    async def respond(self, message: Message) -> None:
        """Respond to a Discord message.

        Handles concurrency (only one response at a time) and
        all the Discord-specific response formatting.
        Uses function calling to decide action: message, reaction, both, or ignore.
        """
        if not self.is_configured:
            return

        # React with "stop" hand if we're already responding
        if self._lock.locked():
            await message.add_reaction(constants.CHAT_BUSY_EMOJI)
            return

        async with self._lock:
            async with message.channel.typing():
                message_content, reaction_emojis = await self._get_response_action(
                    message
                )

            # Execute the action(s)
            if message_content:
                await self._send_response(message, message_content)

            if reaction_emojis:
                for emoji in reaction_emojis:
                    try:
                        await message.add_reaction(emoji)
                    except Exception as e:
                        logger.warning(f"Failed to add reaction {emoji}: {e}")

    async def _get_response_action(
        self, message: Message
    ) -> tuple[str | None, list[str] | None]:
        """Generate response action via function calling.

        Error handling pattern:
        - User-visible errors (context too long, API failures): Reply to user and return (None, None)
        - Internal errors (missing config): Log warning and return (None, None) silently

        Returns:
            Tuple of (message_content, reaction_emojis) where either can be None.
            Returns (None, None) if should ignore or if error occurs.
        """
        if self._context_data is None or self._client.user is None:
            logger.debug(
                "LLM response disabled: context data or client user not available"
            )
            return None, None

        # Fetch conversation history with inline metadata
        history = await self._fetch_history(512, 5, message)

        # Check if we got any history
        if not history:
            # Message too long to fit in context
            await message.reply(constants.CHAT_MESSAGE_TOO_LONG_REPLY)
            return None, None

        # Build system message with markdown formatting, filtered by conversation context
        system_msg = await self._build_system_message(message, history)
        if system_msg is None:
            logger.warning("Cannot generate response: failed to build system message")
            return None, None

        # Build messages array
        messages = [system_msg] + list(reversed(history))

        logger.debug(f"Calling LLM with {len(messages)} total messages (1 system + {len(history)} history)")
        logger.debug(f"Temperature: {constants.CHAT_TEMPERATURE}")
        tool_names = [tool["function"]["name"] for tool in CHAT_TOOLS]  # type: ignore
        logger.debug(f"Tools available: {tool_names}")

        # Call OpenAI with function calling
        try:
            response = await self._ai_service.complete_chat_with_tools(
                messages, CHAT_TOOLS, temperature=constants.CHAT_TEMPERATURE
            )

            # Safety check: model shouldn't generate content when calling tools
            if response.get("content"):
                logger.warning(
                    f"Model generated unexpected content alongside tool call: {response['content']}"
                )

            # Extract tool call
            tool_calls = response.get("tool_calls")
            if not tool_calls:
                logger.error(
                    "Model didn't call any tools despite tool_choice='required'"
                )
                return None, None

            tool_call = tool_calls[0]
            function_name = tool_call["function"]["name"]
            arguments = json.loads(tool_call["function"]["arguments"])

            logger.debug(f"LLM chose action: {function_name}")
            logger.debug(f"Arguments: {arguments}")

            # Handle different action types
            if function_name == "send_message":
                logger.debug(f"Sending message: {arguments['content'][:100]}...")
                return arguments["content"], None

            elif function_name == "add_reactions":
                logger.debug(f"Adding reactions: {arguments['emojis']}")
                return None, arguments["emojis"]

            elif function_name == "send_message_and_react":
                logger.debug(f"Sending message + reactions: {arguments['emojis']}")
                return arguments["content"], arguments["emojis"]

            elif function_name == "ignore":
                logger.debug("Ignoring message (no response)")
                return None, None

            else:
                logger.error(f"Unknown function call: {function_name}")
                return None, None

        except Exception as e:
            logger.error(f"Error calling LLM with tools: {e}", exc_info=True)
            await message.reply(constants.CHAT_ERROR_REPLY)
            return None, None

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

    def _get_name(self, user: User | Member | ClientUser) -> str:
        """Get the name we should call the user.

        Always returns "Busty" for the bot itself, regardless of actual Discord username.
        This ensures consistency between the bot's persona name in static_context and
        how she appears in conversation history.
        """
        # Always use "Busty" for the bot itself
        if user == self._client.user:
            return "Busty"

        if self._context_data is None:
            return cast(str, user.name)

        user_id = str(user.id)
        if user_id in self._context_data.user_info:
            return self._context_data.user_info[user_id].name
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
                    "Tell anyone who tries to speak to you that you can't respond since you're busy busting."
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
            # NOTE: This is a poor estimate - word count can be 2-3x off from actual token count.
            # Tokens often split words (e.g., "running" → ["run", "ning"]) and include punctuation.
            # This may cause context window issues if encoding is unavailable.
            logger.warning(
                "Token encoding not available, using word count as fallback (inaccurate estimate)"
            )
            return len(data.split())
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
    ) -> list[dict[str, str]]:
        """Fetch message content from history up to a certain token allowance.

        Uses inline metadata format: [Name] or [Name → Target] content [img: file]

        Args:
            token_limit: Maximum tokens to include from history.
            speaking_turn_limit: Maximum number of speaking turns to include.
            message: The message being responded to.

        Returns:
            List of message dicts with 'role' and 'content' keys.
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

            # Build message with inline metadata format
            msg_text = await self._format_message_with_metadata(msg)
            total_tokens += self._token_count(msg_text)
            if total_tokens > token_limit:
                break

            # Determine role
            role = "assistant" if msg.author == self._client.user else "user"
            history.append({"role": role, "content": msg_text})

        return history

    async def _format_message_with_metadata(self, msg: Message) -> str:
        """Format a Discord message with inline metadata tags.

        Format: [Name] content or [Name → Target] content [img: file]

        Args:
            msg: Discord message to format.

        Returns:
            Formatted message string with inline metadata.
        """
        content_parts = []

        # Build name/reply prefix
        name = self._get_name(msg.author)
        prefix = f"[{name}"

        # Add reply indicator if replying to someone
        if msg.reference and msg.reference.message_id:
            try:
                replied_msg = await msg.channel.fetch_message(msg.reference.message_id)
                replied_to = self._get_name(replied_msg.author)
                prefix += f" → {replied_to}"
            except Exception:
                # If we can't fetch the referenced message, just skip the reply indicator
                pass

        prefix += "]"
        content_parts.append(prefix)

        # Add main message content
        msg_content = self._substitute_mentions(msg)
        if msg_content.strip():
            content_parts.append(msg_content)

        # Add attachment metadata
        for att in msg.attachments:
            if att.content_type:
                if att.content_type.startswith("image/"):
                    content_parts.append(f"[img: {att.filename}]")
                elif att.content_type.startswith("audio/"):
                    content_parts.append(f"[audio: {att.filename}]")
                elif att.content_type.startswith("video/"):
                    content_parts.append(f"[video: {att.filename}]")

        # Add reaction metadata (limit to top 3 most common)
        if msg.reactions:
            reaction_strs = []
            for reaction in sorted(msg.reactions, key=lambda r: r.count, reverse=True)[
                :3
            ]:
                if reaction.count > 1:
                    reaction_strs.append(f"{reaction.emoji}({reaction.count})")
                else:
                    reaction_strs.append(str(reaction.emoji))

            if reaction_strs:
                content_parts.append(f"[reactions: {' '.join(reaction_strs)}]")

        return " ".join(content_parts)

    async def _build_system_message(
        self, message: Message, history: list[dict[str, str]]
    ) -> dict[str, str] | None:
        """Build structured system message with markdown formatting.

        Only includes user info and word triggers that are relevant to the
        current conversation (mentioned in history), reducing token usage.

        Args:
            message: The message being responded to.
            history: Conversation history to extract relevant context from.

        Returns:
            System message dict with markdown-formatted context, or None if
            context data is not available.
        """
        if self._context_data is None:
            logger.warning("Cannot build system message: context data not loaded")
            return None

        sections = []

        # Identity and personality (from static_context) - always included
        identity_section = "# Identity and Personality\n" + "\n".join(
            f"- {line}" if not line.startswith("You are") else line
            for line in self._context_data.static_context
        )
        sections.append(identity_section)

        # Current context (server state, bust status, etc.) - always included
        server_context = await self._get_server_context(message)
        if server_context:
            context_section = "# Current Context\n" + "\n".join(
                f"- {line}" for line in server_context
            )
            sections.append(context_section)

        # Extract relevant context from conversation history
        mentioned_triggers, mentioned_users = self._extract_history_context(history)
        logger.debug(
            f"Extracted context from history: {len(mentioned_users)} users, {len(mentioned_triggers)} triggers"
        )
        if mentioned_users:
            logger.debug(f"Mentioned users: {mentioned_users}")
        if mentioned_triggers:
            logger.debug(f"Mentioned triggers: {mentioned_triggers}")

        # People info - only include users mentioned in conversation
        if self._context_data.user_info and mentioned_users:
            people_lines = []
            for user in self._context_data.user_info.values():
                if user.info and user.name.lower() in mentioned_users:
                    people_lines.append(f"- {user.name}: {user.info}")
            if people_lines:
                sections.append("# People You Know\n" + "\n".join(people_lines))

        # Topic knowledge - only include triggers mentioned in conversation
        if self._context_data.word_triggers and mentioned_triggers:
            trigger_lines = [
                f"- {word}: {info}"
                for word, info in self._context_data.word_triggers.items()
                if word in mentioned_triggers
            ]
            if trigger_lines:
                sections.append("# Topic Knowledge\n" + "\n".join(trigger_lines))

        # Response guidelines
        guidelines = """# How to Respond
pick one of these based on the vibe:
- send_message: just chat normally
- add_reactions: react with emoji, no words
- send_message_and_react: reply AND react for emphasis
- ignore: don't say anything, just lurk

you don't gotta respond to everything. sometimes just vibing is fine"""
        sections.append(guidelines)

        system_message = {"role": "system", "content": "\n\n".join(sections)}
        logger.debug(f"Built system message with {len(sections)} sections")
        logger.debug(f"System message content:\n{system_message['content']}")

        return system_message

    def _extract_history_context(
        self, history: list[dict[str, str]]
    ) -> tuple[set[str], set[str]]:
        """Extract word triggers and user mentions from conversation history.

        This is used to filter the system message to only include relevant context,
        reducing token usage and cost.

        Args:
            history: List of message dicts with 'content' key.

        Returns:
            Tuple of (word_triggers, user_names) sets found in history.
        """
        if self._context_data is None:
            return set(), set()

        word_triggers = set()
        user_names = set()

        for msg in history:
            content = msg["content"].lower()

            # Find word triggers that appear in conversation
            if self._word_trigger_pattern:
                for word in self._word_trigger_pattern.findall(content):
                    word_triggers.add(word)

            # Find user names that appear in conversation
            if self._user_trigger_pattern:
                for user_name in self._user_trigger_pattern.findall(content):
                    user_names.add(user_name)

        return word_triggers, user_names
