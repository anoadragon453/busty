"""AI services for the Busty bot.

This package provides AI-powered features including:
- Chat completion via language models
- Image generation
- Cover art generation for music tracks
"""

from busty.ai.chat_service import ChatService
from busty.ai.openai_service import OpenAIService
from busty.ai.protocols import AIService

__all__ = ["AIService", "ChatService", "OpenAIService"]
