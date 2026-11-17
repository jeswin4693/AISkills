"""Build the configured provider from environment variables (loaded from .env by the command line)."""

from __future__ import annotations

import os
from collections.abc import Mapping

from .base import LLMProvider, ProviderError
from .openai_compat import GEMINI_BASE_URL, OpenAICompatibleProvider

# provider name -> (key variable, base URL or None for the vendor default)
SUPPORTED = {
    "gemini": ("GOOGLE_API_KEY", GEMINI_BASE_URL),
    "openai": ("OPENAI_API_KEY", None),
}


def provider_from_env(env: Mapping[str, str] | None = None) -> LLMProvider:
    env = os.environ if env is None else env
    name = env.get("LLM_PROVIDER", "").strip().lower()
    if name not in SUPPORTED:
        raise ProviderError(f"LLM_PROVIDER is '{name}'. Supported: {', '.join(sorted(SUPPORTED))}. Set it in .env.")
    model = env.get("LLM_MODEL", "").strip()
    if not model:
        raise ProviderError("LLM_MODEL is empty. Set a model your key can use in .env.")
    key_env, base_url = SUPPORTED[name]
    api_key = env.get(key_env, "").strip()
    if not api_key:
        raise ProviderError(f"{key_env} is empty. Add it to .env (never commit that file).")
    return OpenAICompatibleProvider(
        name=name, model=model, api_key=api_key, key_env=key_env, base_url=base_url
    )
