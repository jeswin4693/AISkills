"""Where the builder gets its model. Keys come only from the environment or the git-ignored .env, and are never shown."""

from __future__ import annotations

from ..ai import AIService, Tier, service_from_env
from ..providers import LLMProvider, ProviderError
from ..settings import default_settings


def env_provider() -> LLMProvider:
    # real environment variables win over the file; a changed .env is seen now, with no restart. One copy, taken under the lock that
    # every save holds, so a lookup never sees half of a save.
    return service_from_env(default_settings().snapshot())


def provider_status(factory=env_provider) -> dict:
    """Whether a model is set up, which one, and which model serves each tier. Never includes a key, and makes no network call."""
    try:
        p = factory()
    except ProviderError as exc:
        return {"configured": False, "provider": "", "model": "", "detail": str(exc), "tiers": [], "escalation": None, "capabilities": None, "fallbacks": []}
    tiers: list[dict] = []
    escalation = None
    capabilities = None
    fallbacks: list[dict] = []
    if isinstance(p, AIService):
        tiers = [
            {"tier": t.value, "provider": p.profiles.profile_for(t).provider.name, "model": p.profiles.profile_for(t).provider.model}
            for t in Tier
        ]
        fallbacks = [{"provider": f.provider.name, "model": f.provider.model} for f in p.profiles.fallbacks]
        if p.profiles.escalation is not None:
            escalation = {"provider": p.profiles.escalation.provider.name, "model": p.profiles.escalation.provider.model}
        found = getattr(p.profiles.default.provider, "capabilities", None)
        if found is not None:
            capabilities = {"structured_output": found.structured_output, "max_input_tokens": found.max_input_tokens}
    return {
        "configured": True, "provider": p.name, "model": p.model, "detail": "", "tiers": tiers, "escalation": escalation,
        "capabilities": capabilities, "fallbacks": fallbacks,
    }
