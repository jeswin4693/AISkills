"""LLM providers behind one small interface: `generate_structured(schema, prompt)`."""

from .base import LLMProvider, ProviderError
from .factory import provider_from_env
from .mock import MockProvider
from .openai_compat import OpenAICompatibleProvider

__all__ = ["LLMProvider", "ProviderError", "provider_from_env", "MockProvider", "OpenAICompatibleProvider"]
