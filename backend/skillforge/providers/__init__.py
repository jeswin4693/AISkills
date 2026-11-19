"""LLM providers behind one small interface: `generate_structured(schema, prompt)`."""

from .anthropic_native import AnthropicProvider
from .base import CallOptions, Capabilities, ErrorKind, GeneratingProvider, Generation, LLMProvider, ProviderError, Usage
from .factory import build_provider, key_variables, provider_from_env, supported_names
from .mock import MockProvider
from .openai_compat import OpenAICompatibleProvider

__all__ = [
    "AnthropicProvider", "CallOptions", "Capabilities", "ErrorKind", "GeneratingProvider", "Generation", "LLMProvider",
    "MockProvider", "OpenAICompatibleProvider", "ProviderError", "Usage", "build_provider", "key_variables",
    "provider_from_env", "supported_names",
]
