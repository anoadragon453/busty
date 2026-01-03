"""OpenAI implementation of AIService protocol."""

import asyncio
import logging

import openai
import requests

from busty import song_utils
from busty.config import constants
from busty.config.settings import BustySettings
from busty.track import Track

logger = logging.getLogger(__name__)


class OpenAIService:
    """OpenAI implementation of AIService protocol."""

    def __init__(self, settings: BustySettings):
        self.settings = settings
        self._client: openai.AsyncOpenAI | None = None
        if settings.openai_api_key:
            self._client = openai.AsyncOpenAI(api_key=settings.openai_api_key)

    @property
    def is_configured(self) -> bool:
        """Check if OpenAI is configured."""
        return self._client is not None

    async def complete_chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 512,
        temperature: float = 1.0,
    ) -> str | None:
        """Send messages to OpenAI and return completion text.

        Args:
            messages: List of {"role": ..., "content": ...} dicts.
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature (0.0-2.0). Higher = more random/creative.

        Returns:
            Response text, or None if AI unavailable or error occurs.
        """
        if self._client is None:
            return None

        try:
            response = await self._client.chat.completions.create(
                model=self.settings.openai_model,
                messages=messages,  # type: ignore
                temperature=temperature,
                timeout=constants.LLM_RESPONSE_TIMEOUT,
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"OpenAI API exception: {e}")
            return None

    async def complete_chat_with_tools(
        self,
        messages: list[dict[str, str]],
        tools: list[dict],
        temperature: float = 1.0,
    ) -> dict:
        """Send messages to OpenAI with tool/function calling.

        Args:
            messages: List of {"role": ..., "content": ...} dicts.
            tools: List of tool definitions for function calling.
            temperature: Sampling temperature (0.0-2.0). Higher = more random/creative.

        Returns:
            Response dict with 'content' and 'tool_calls' keys.

        Raises:
            Exception: If client not configured or API error occurs.
        """
        if self._client is None:
            raise RuntimeError("OpenAI client not configured")

        response = await self._client.chat.completions.create(
            model=self.settings.openai_model,
            messages=messages,  # type: ignore
            tools=tools,  # type: ignore
            tool_choice="required",  # Force the model to call a function
            temperature=temperature,
            timeout=constants.LLM_RESPONSE_TIMEOUT,
        )

        message = response.choices[0].message

        # Convert to dict format for easier handling
        result = {"content": message.content, "tool_calls": []}

        if message.tool_calls:
            result["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in message.tool_calls
            ]

        return result

    async def generate_image(self, prompt: str) -> str | None:
        """Generate an image from a text prompt.

        Args:
            prompt: Text description of desired image.

        Returns:
            URL of generated image, or None if unavailable or error occurs.
        """
        if self._client is None:
            return None

        try:
            response = await self._client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                size="1024x1024",
                quality="standard",
                n=1,
            )
            return response.data[0].url if response.data else None
        except Exception as e:
            logger.error(f"OpenAI image generation exception: {e}")
            return None

    async def get_cover_art(self, track: Track) -> bytes | None:
        """Generate cover art for a track using OpenAI.

        Returns None if OpenAI is not configured, generation fails, or times out.
        """
        if not self.is_configured:
            return None

        # Extract metadata for generation
        artist, title = song_utils.get_song_metadata_with_fallback(
            track.local_filepath, track.attachment_filename, track.submitter_name
        )

        # Build prompt for album art generation
        prompt = self._build_album_art_prompt(
            artist, title, track.message_content or None
        )

        try:
            # Generate cover art URL using OpenAI
            cover_art_url = await asyncio.wait_for(
                self.generate_image(prompt),
                timeout=constants.COVER_ART_GENERATE_TIMEOUT,
            )

            # Fetch the generated image
            if cover_art_url:
                response = await asyncio.to_thread(
                    requests.get,
                    cover_art_url,
                    timeout=constants.COVER_ART_FETCH_TIMEOUT,
                )
                response.raise_for_status()
                return response.content

            return None

        except asyncio.TimeoutError:
            logger.warning("Cover art generation timed out")
            return None
        except requests.RequestException as e:
            logger.error(f"Failed to fetch generated cover art: {e}")
            return None

    def _build_album_art_prompt(
        self, artist: str | None, title: str, description: str | None
    ) -> str:
        """Build DALL-E prompt for album art generation.

        Args:
            artist: Artist name or None.
            title: Song title.
            description: Optional song description.

        Returns:
            Formatted prompt for DALL-E.
        """
        prompt_parts = [
            "Generate bizarre photorealistic album art for the following song.",
            f"{artist or 'Unknown Artist'} - {title}\n",
        ]
        if description:
            # Cap the description to 1000 characters to avoid token limits
            prompt_parts.append(
                f"Here is how the artist describes the song: {description[:1000]}"
            )
        return "\n".join(prompt_parts)
