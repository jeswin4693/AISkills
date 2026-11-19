"""Build the configured provider from environment variables (loaded from .env by the command line)."""

from __future__ import annotations

import os
from collections.abc import Mapping

from .anthropic_native import AnthropicProvider
from .base import GeneratingProvider, ProviderError
from .openai_compat import GEMINI_BASE_URL, OpenAICompatibleProvider

# OpenAI-compatible endpoints: provider name -> (key variable, base URL or None for the vendor default). Gemini and OpenAI
# are verified live; the rest share the same adapter and have only been checked with a mock.
SUPPORTED = {
    "gemini": ("GOOGLE_API_KEY", GEMINI_BASE_URL),
    "openai": ("OPENAI_API_KEY", None),
    "groq": ("GROQ_API_KEY", "https://api.groq.com/openai/v1"),
    "openrouter": ("OPENROUTER_API_KEY", "https://openrouter.ai/api/v1"),
    "mistral": ("MISTRAL_API_KEY", "https://api.mistral.ai/v1"),
    "custom": ("LLM_API_KEY", None),  # any OpenAI-compatible endpoint; its address comes from LLM_BASE_URL
}
ANTHROPIC = "anthropic"  # its own adapter (native structured output); key variable ANTHROPIC_API_KEY


def supported_names() -> list[str]:
    return sorted([*SUPPORTED, ANTHROPIC])


def build_provider(
    name: str, model: str, env: Mapping[str, str], *, timeout_s: float | None = None
) -> GeneratingProvider:
    """One adapter for `name` and `model`, with its key read from `env`. Raises ProviderError saying what is missing."""
    name = name.strip().lower()
    if name not in supported_names():
        raise ProviderError(f"LLM_PROVIDER is '{name}'. Supported: {', '.join(supported_names())}. Set it in .env.")
    model = model.strip()
    if not model:
        raise ProviderError("LLM_MODEL is empty. Set a model your key can use in .env.")
    extra: dict = {} if timeout_s is None else {"timeout_s": timeout_s}
    if name == ANTHROPIC:
        api_key = env.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            raise ProviderError("ANTHROPIC_API_KEY is empty. Add it to .env (never commit that file).")
        return AnthropicProvider(name=name, model=model, api_key=api_key, key_env="ANTHROPIC_API_KEY", **extra)
    key_env, base_url = SUPPORTED[name]
    if name == "custom":
        base_url = env.get("LLM_BASE_URL", "").strip()
        if not base_url:
            raise ProviderError("LLM_BASE_URL is empty. For provider 'custom', set the address of an OpenAI-compatible API.")
    api_key = env.get(key_env, "").strip()
    if not api_key:
        raise ProviderError(f"{key_env} is empty. Add it to .env (never commit that file).")
    return OpenAICompatibleProvider(name=name, model=model, api_key=api_key, key_env=key_env, base_url=base_url, **extra)


def provider_from_env(env: Mapping[str, str] | None = None) -> GeneratingProvider:
    env = os.environ if env is None else env
    return build_provider(env.get("LLM_PROVIDER", ""), env.get("LLM_MODEL", ""), env)
