"""AIService: the one place that calls a model for every builder.

It routes a task to a model (by tier), makes one attempt at a time, decides by the error's kind whether to try again (one
policy, in `policy.py`), counts every real attempt, records what each cost, and cleans keys out of any error. It is also an
`LLMProvider` (`name`, `model`, `generate_structured`), so a builder that holds a `provider` keeps working unchanged.

Nothing here asks a model whether its own answer is good: callers check answers with code, and ask for a stronger model
(`escalate=True`) only when those checks fail.
"""

from __future__ import annotations

import logging
import os
import random
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ValidationError

from ..graph.store import data_dir
from ..providers.base import CallOptions, Generation, LLMProvider, ProviderError, T, Usage
from .cache import FileCache, ResponseCache, cache_key
from .policy import NO_WAIT, Policy, decide
from .profiles import Profile, ProfileSet, load_profiles, positive_number
from .redact import redact
from .tasks import TIER_OF, Task

log = logging.getLogger(__name__)


@dataclass
class UsageRecord:
    """One HTTP attempt. Never any prompt or reply text."""

    task: str
    tier: str
    provider: str
    model: str
    attempt: int
    status: str  # "ok" or "error"
    error_kind: str  # "" when ok
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int


class UsageRecorder(Protocol):
    def record(self, rec: UsageRecord) -> None: ...


@dataclass(frozen=True)
class UsageTotals:
    calls: int
    input_tokens: int  # tokens the providers reported; a provider that reports none adds 0
    output_tokens: int


class _Counters:
    """Shared by a service and the escalated service made from it, so one budget covers both."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0


def _clone(exc: ProviderError, message: str, secrets: tuple[str, ...]) -> ProviderError:
    return ProviderError(
        redact(message, secrets), retryable=exc.retryable, kind=exc.kind, retry_after_s=exc.retry_after_s,
        detail=redact(exc.detail, secrets),
    )


def _estimate(*texts: str) -> int:
    from ..build.quality import estimate_tokens  # imported here: the build package is a user of this one, not the reverse

    return estimate_tokens("".join(texts))


class AIService:
    def __init__(
        self,
        profiles: ProfileSet,
        *,
        policy: Policy = Policy(),
        recorder: UsageRecorder | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rng: Callable[[], float] = random.random,
        max_calls: int | None = None,
        cache: ResponseCache | None = None,
        _counters: _Counters | None = None,
    ) -> None:
        self.profiles = profiles
        self.policy = policy
        self.recorder = recorder
        self.max_calls = max_calls
        self.cache = cache
        self._sleep = sleep
        self._rng = rng
        self._counters = _counters or _Counters()

    # ---- the LLMProvider face ---------------------------------------------------------------------

    @property
    def name(self) -> str:
        return self.profiles.default.provider.name

    @property
    def model(self) -> str:
        return self.profiles.default.provider.model

    def generate_structured(self, schema: type[T], prompt: str, *, system: str | None = None) -> T:
        return self.generate(Task.DESIGN, schema, prompt, system)[0]

    # ---- construction helpers ---------------------------------------------------------------------

    @classmethod
    def single(cls, provider: LLMProvider) -> AIService:
        """A bare provider (a test double, or an adapter used directly) behind the same interface: one model for every task,
        the old retry counts, and no pauses between attempts."""
        return cls(ProfileSet(Profile("default", provider, CallOptions())), policy=NO_WAIT, sleep=lambda seconds: None)

    def with_recorder(self, recorder: UsageRecorder) -> AIService:
        """The same models and rules, a recorder for this run, and fresh counters."""
        return AIService(
            self.profiles, policy=self.policy, recorder=recorder, sleep=self._sleep, rng=self._rng, max_calls=self.max_calls,
            cache=self.cache,
        )

    def escalated(self) -> AIService | None:
        """A service that sends every task to the escalation model, or None when none is configured. It shares this service's
        counters, so one call budget covers both."""
        profile = self.profiles.escalation
        if profile is None:
            return None
        return AIService(
            ProfileSet(profile), policy=self.policy, recorder=self.recorder, sleep=self._sleep, rng=self._rng,
            max_calls=self.max_calls, cache=self.cache, _counters=self._counters,
        )

    @property
    def usage(self) -> UsageTotals:
        c = self._counters
        with c.lock:
            return UsageTotals(c.calls, c.input_tokens, c.output_tokens)

    # ---- the call ---------------------------------------------------------------------------------

    def generate(
        self, task: Task, schema: type[T], prompt: str, system: str | None = None, *, attempts: int | None = None,
        escalate: bool = False,
    ) -> tuple[T, int]:
        """(the validated answer, HTTP attempts made). Raises ProviderError with any key removed from its text."""
        tier = TIER_OF[task]
        profile = self.profiles.escalation if escalate and self.profiles.escalation else self.profiles.profile_for(tier)
        tier_name = "escalation" if profile.tier == "escalation" else tier.value
        secrets = self.profiles.secrets()
        key = None
        if self.cache is not None and task is not Task.ACT:  # eval replies must be asked for again, so they are never cached
            key = cache_key(profile.provider.name, profile.provider.model, schema, system, prompt)
            hit = self._cached(key, schema)
            if hit is not None:
                self._record(task, tier_name, profile, 0, "cache", "", Usage(), 0.0)  # not a call: it never reached the model
                return hit, 0
        current = prompt
        made = 0
        while True:
            self._guard(profile, system, current)
            made += 1
            self._count_call()
            started = time.monotonic()
            try:
                generation = self._attempt(profile, schema, current, system)
            except ProviderError as exc:
                error = _clone(exc, str(exc), secrets)
                self._record(task, tier_name, profile, made, "error", error.kind, Usage(), time.monotonic() - started)
                decision = decide(error, made, self.policy, cap=attempts, rng=self._rng)
                if not decision.retry:
                    if made > 1:
                        raise _clone(error, f"No usable answer after {made} attempt(s): {error}", secrets) from exc
                    if decision.reason:
                        raise _clone(error, f"{error} ({decision.reason})", secrets) from exc
                    raise error from exc
                if decision.wait_s > 0:
                    self._sleep(decision.wait_s)
                current = f"{prompt}\n\n{decision.feedback}" if decision.feedback else prompt
                continue
            self._add_tokens(generation.usage)
            self._record(task, tier_name, profile, made, "ok", "", generation.usage, generation.latency_s)
            if key is not None:
                self._store(key, generation.value)
            return generation.value, made

    # ---- internals --------------------------------------------------------------------------------

    def _cached(self, key: str, schema: type[T]) -> T | None:
        """A stored answer that still fits the schema, or None (an old or damaged entry is simply not used)."""
        try:
            text = self.cache.get(key) if self.cache is not None else None
            return schema.model_validate_json(text) if text is not None else None
        except (ValidationError, OSError, ValueError):
            return None

    def _store(self, key: str, value: BaseModel) -> None:
        """Only an answer that already passed schema validation is kept. A cache that cannot write never breaks a call."""
        try:
            if self.cache is not None:
                self.cache.put(key, value.model_dump_json())
        except Exception:  # noqa: BLE001
            log.exception("could not store a model answer in the cache")

    def _attempt(self, profile: Profile, schema: type[T], prompt: str, system: str | None) -> Generation[T]:
        provider = profile.provider
        generate = getattr(provider, "generate", None)
        if callable(generate):
            return generate(schema, prompt, system=system, options=profile.options)
        return Generation(provider.generate_structured(schema, prompt, system=system))  # a bare provider reports no usage

    def _guard(self, profile: Profile, system: str | None, prompt: str) -> None:
        if self.max_calls is not None and self.usage.calls >= self.max_calls:
            raise ProviderError(
                f"Stopped: this run has used its limit of {self.max_calls} model calls (LLM_MAX_CALLS).", kind="budget"
            )
        if profile.max_input_tokens is not None:
            estimate = _estimate(system or "", prompt)
            if estimate > profile.max_input_tokens:
                raise ProviderError(
                    f"Not sent: the request is about {estimate} tokens, over the limit of {profile.max_input_tokens} "
                    "(LLM_MAX_INPUT_TOKENS).", kind="too_long",
                )

    def _count_call(self) -> None:
        with self._counters.lock:
            self._counters.calls += 1

    def _add_tokens(self, usage: Usage) -> None:
        with self._counters.lock:
            self._counters.input_tokens += usage.input_tokens or 0
            self._counters.output_tokens += usage.output_tokens or 0

    def _record(
        self, task: Task, tier: str, profile: Profile, attempt: int, status: str, error_kind: str, usage: Usage, seconds: float
    ) -> None:
        if self.recorder is None:
            return
        try:
            self.recorder.record(UsageRecord(
                task.value, tier, profile.provider.name, profile.provider.model, attempt, status, error_kind,
                usage.input_tokens, usage.output_tokens, max(0, round(seconds * 1000)),
            ))
        except Exception:  # noqa: BLE001 - keeping count must never break the call it is counting
            log.exception("could not record model usage")


def service_from_env(env: Mapping[str, str] | None = None) -> AIService:
    """The model service for this run, built from an environment mapping (`os.environ` when none is given).

    Settings are read here and nowhere else (docs/ai-engine.md). With none of the optional ones set this is one model for every
    task: the behaviour from before tiers existed."""
    env = os.environ if env is None else env
    profiles = load_profiles(env)
    limit = positive_number(env, "LLM_MAX_CALLS", int)
    cache = FileCache(data_dir() / "llm-cache") if env.get("SKILLFORGE_LLM_CACHE", "").strip() == "1" else None  # off unless asked
    return AIService(profiles, max_calls=int(limit) if limit else None, cache=cache)
