"""What is configured, which keys nothing uses, and a one-call check per model. Never a key value, only names and results.

`describe` makes no call. `check_models` makes one tiny call to each distinct model, so it uses a little quota: it runs only
when a person asks (`skillforge models --test`, or the check in the web app).
"""

from __future__ import annotations

import time
from collections.abc import Mapping

from pydantic import BaseModel, Field

from ..providers.base import CallOptions, Generation, LLMProvider, ProviderError
from ..providers.factory import key_variables
from .redact import redact
from .service import AIService

PROMPT = "Reply with the single word ok."


class Ping(BaseModel):
    reply: str = Field(description='The single word "ok".')


def keys_present(env: Mapping[str, str]) -> list[str]:
    """The providers whose key is set, by name. A custom endpoint counts only when its address is set too."""
    found = []
    for name, variable in sorted(key_variables().items()):
        if not env.get(variable, "").strip():
            continue
        if name == "custom" and not env.get("LLM_BASE_URL", "").strip():
            continue
        found.append(name)
    return found


def _service(provider: LLMProvider) -> AIService:
    return provider if isinstance(provider, AIService) else AIService.single(provider)


def describe(provider: LLMProvider, env: Mapping[str, str]) -> dict:
    """The routing as configured, and the keys that are set but used by nothing (with how to use them). No call is made."""
    profiles = _service(provider).profiles
    used = {p.provider.name for p in profiles.all()}
    variables = key_variables()
    present = keys_present(env)
    return {
        "default": {"provider": profiles.default.provider.name, "model": profiles.default.provider.model},
        "tiers": [{"tier": t.value, "provider": p.provider.name, "model": p.provider.model} for t, p in profiles.tiers.items()],
        "fallbacks": [{"provider": p.provider.name, "model": p.provider.model} for p in profiles.fallbacks],
        "escalation": (
            {"provider": profiles.escalation.provider.name, "model": profiles.escalation.provider.model}
            if profiles.escalation else None
        ),
        "keys_present": present,
        "unused": [
            {
                "provider": name,
                "hint": f"{variables[name]} is set but {name} is not used. To use it as a backup, add "
                        f"LLM_FALLBACKS={name}:<a model your key can use>.",
            }
            for name in present if name not in used
        ],
    }


def check_models(provider: LLMProvider) -> list[dict]:
    """One tiny structured call to each distinct model, with what it was used for, how long it took and what it cost. A model
    that fails is reported with its error kind: this never raises."""
    service = _service(provider)
    profiles = service.profiles
    secrets = profiles.secrets()
    roles: dict[tuple[str, str], list[str]] = {}
    entries = []

    def add(label: str, profile) -> None:
        key = (profile.provider.name, profile.provider.model)
        if key not in roles:
            roles[key] = []
            entries.append(profile)
        if label not in roles[key]:
            roles[key].append(label)

    add("default", profiles.default)
    for tier, profile in profiles.tiers.items():
        add(tier.value, profile)
    for profile in profiles.fallbacks:
        add("fallback", profile)
    if profiles.escalation is not None:
        add("escalation", profiles.escalation)

    rows = []
    for profile in entries:
        name, model = profile.provider.name, profile.provider.model
        label = roles[(name, model)]
        row = {"provider": name, "model": model, "roles": label if len(label) == 1 else [r for r in label if r != "default"]}
        started = time.monotonic()
        try:
            generate = getattr(profile.provider, "generate", None)
            generation = (
                generate(Ping, PROMPT, options=profile.options if isinstance(profile.options, CallOptions) else CallOptions())
                if callable(generate) else Generation(profile.provider.generate_structured(Ping, PROMPT))
            )
            rows.append({**row, "ok": True, "kind": "", "detail": "", "latency_ms": round((time.monotonic() - started) * 1000),
                         "input_tokens": generation.usage.input_tokens, "output_tokens": generation.usage.output_tokens})
        except ProviderError as exc:
            rows.append({**row, "ok": False, "kind": exc.kind, "detail": redact(service.reword(str(exc)) if service.reword else str(exc), secrets)[:300],
                         "latency_ms": round((time.monotonic() - started) * 1000), "input_tokens": None, "output_tokens": None})
    return rows
