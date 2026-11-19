"""Which model does which tier of work, read from an environment mapping (never from `.env` directly).

Nothing set means one model for everything: today's behaviour. A tier that is set up wrongly stops at start-up and names the
variable; it never falls back to the default model quietly (docs/ai-engine.md, "Settings").
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from ..providers.base import CallOptions, GeneratingProvider, ProviderError
from ..providers.factory import build_provider
from .tasks import Tier

DEFAULT_TIMEOUT_S = 90.0
CODE_TIMEOUT_S = 180.0  # a bundle of scripts is a longer answer than a requirement record


@dataclass(frozen=True)
class Profile:
    tier: str  # "default", a Tier value, or "escalation"
    provider: GeneratingProvider
    options: CallOptions
    max_input_tokens: int | None = None


@dataclass(frozen=True)
class ProfileSet:
    default: Profile
    tiers: dict[Tier, Profile] = field(default_factory=dict)
    escalation: Profile | None = None

    def profile_for(self, tier: Tier) -> Profile:
        return self.tiers.get(tier, self.default)

    def all(self) -> list[Profile]:
        return [self.default, *self.tiers.values(), *([self.escalation] if self.escalation else [])]

    def secrets(self) -> tuple[str, ...]:
        """Every key the profiles hold, so any error text can be cleaned before it is stored or shown."""
        return tuple(dict.fromkeys(s for p in self.all() for s in p.provider.secrets))


def _positive(env: Mapping[str, str], name: str, cast: Callable[[str], float]) -> float | None:
    raw = env.get(name, "").strip()
    if not raw:
        return None
    try:
        value = cast(raw)
    except ValueError:
        value = 0
    if value <= 0:
        raise ProviderError(f"{name} is '{raw}', which is not a positive number. Fix it in .env or remove it.")
    return value


def load_profiles(env: Mapping[str, str] | None = None) -> ProfileSet:
    env = os.environ if env is None else env
    global_timeout = _positive(env, "LLM_TIMEOUT_S", float)
    max_input = _positive(env, "LLM_MAX_INPUT_TOKENS", int)
    default_timeout = global_timeout or DEFAULT_TIMEOUT_S
    default_provider = build_provider(env.get("LLM_PROVIDER", ""), env.get("LLM_MODEL", ""), env, timeout_s=default_timeout)
    default = Profile("default", default_provider, CallOptions(timeout_s=default_timeout), int(max_input) if max_input else None)

    def override(prefix: str, label: str, timeout: float) -> GeneratingProvider | None:
        """A provider of its own for LLM_<prefix>_PROVIDER / _MODEL, or None when neither is set."""
        name, model = env.get(f"LLM_{prefix}_PROVIDER", "").strip(), env.get(f"LLM_{prefix}_MODEL", "").strip()
        if not name and not model:
            return None
        name = name or default_provider.name
        if not model:
            if name.lower() != default_provider.name:
                raise ProviderError(
                    f"LLM_{prefix}_MODEL is empty. {label} uses another provider ({name}), so it needs a model of its own."
                )
            model = default_provider.model
        try:
            return build_provider(name, model, env, timeout_s=timeout)
        except ProviderError as exc:
            raise ProviderError(f"For {label} (LLM_{prefix}_*): {exc}") from exc

    tiers: dict[Tier, Profile] = {}
    for tier in Tier:
        prefix = tier.name
        own_timeout = _positive(env, f"LLM_{prefix}_TIMEOUT_S", float)
        timeout = own_timeout or global_timeout or (CODE_TIMEOUT_S if tier is Tier.CODE else DEFAULT_TIMEOUT_S)
        max_out = _positive(env, f"LLM_{prefix}_MAX_OUTPUT_TOKENS", int)
        provider = override(prefix, f"the {tier.value} tier", timeout) or default_provider
        tiers[tier] = Profile(
            tier.value, provider, CallOptions(timeout_s=timeout, max_output_tokens=int(max_out) if max_out else None), default.max_input_tokens
        )
    escalation_provider = override("ESCALATION", "escalation", default_timeout)
    escalation = Profile("escalation", escalation_provider, CallOptions(timeout_s=default_timeout), default.max_input_tokens) if escalation_provider else None
    return ProfileSet(default, tiers, escalation)
