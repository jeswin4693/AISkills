"""Where the builder gets its model. Keys come only from the environment or the git-ignored .env, and are never shown."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

from ..providers import LLMProvider, ProviderError, provider_from_env

REPO_ROOT = Path(__file__).resolve().parents[3]


def env_provider() -> LLMProvider:
    load_dotenv(REPO_ROOT / ".env")  # real environment variables win over the file
    return provider_from_env()


def provider_status(factory=env_provider) -> dict:
    """Whether a model is set up, and which one. Never includes a key, and makes no network call."""
    try:
        p = factory()
    except ProviderError as exc:
        return {"configured": False, "provider": "", "model": "", "detail": str(exc)}
    return {"configured": True, "provider": p.name, "model": p.model, "detail": ""}
