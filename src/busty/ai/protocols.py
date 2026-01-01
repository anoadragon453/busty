"""Protocol definitions for AI services."""

from typing import Any, Protocol

from busty.track import Track


class AIService(Protocol):
    """Protocol for AI-powered features (low-level AI operations)."""

    async def get_cover_art(self, track: Track) -> bytes | None:
        """Generate cover art for a track using AI.

        Args:
            track: The track to generate cover art for.

        Returns:
            Generated cover art image data as bytes, or None if AI is not
            configured, generation fails, or times out.
        """
        ...

    async def complete_chat(
        self, messages: list[dict[str, str]], max_tokens: int = 512
    ) -> str | None:
        """Send messages to AI and return completion text.

        Args:
            messages: List of {"role": ..., "content": ...} dicts.
            max_tokens: Maximum tokens in response.

        Returns:
            Response text, or None if AI unavailable or error occurs.
        """
        ...

    async def complete_chat_with_tools(
        self, messages: list[dict[str, str]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Send messages to AI with tool/function calling.

        Args:
            messages: List of {"role": ..., "content": ...} dicts.
            tools: List of tool definitions for function calling.

        Returns:
            Response dict with 'content' and 'tool_calls' keys.
            Raises exception if error occurs.
        """
        ...

    async def generate_image(self, prompt: str) -> str | None:
        """Generate an image from a text prompt.

        Args:
            prompt: Text description of desired image.

        Returns:
            URL of generated image, or None if unavailable or error occurs.
        """
        ...
