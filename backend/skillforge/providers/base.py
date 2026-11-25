"""The provider interface. Nothing outside this package knows which vendor is behind it.

`LLMProvider.generate_structured` is the original, small interface and still all that a builder needs. A provider that can
also report what a call cost implements `generate`, which returns a `Generation`; the AI service (`skillforge.ai`) uses that
when it exists and falls back to `generate_structured` when it does not (a test double, for instance).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, Literal, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)
V = TypeVar("V")

# What kind of failure it was. The retry policy (ai/policy.py) is decided by this, not by parsing messages.
# `too_long` is about the ANSWER (cut off) or the engine's own input limit; `input_too_large` is a MODEL saying the request is too big for it
# (HTTP 413, a context-length error): the caller can send less, and trying again with the same request cannot help.
ErrorKind = Literal[
    "auth", "model_missing", "bad_request", "rate_limit", "quota", "overloaded", "timeout", "connection",
    "invalid_output", "too_long", "input_too_large", "refused", "budget", "other",
]


class ProviderError(Exception):
    """A provider call failed in a way the user can act on. `retryable` means asking again may succeed.

    `kind` says what went wrong, `retry_after_s` is how long the provider asked us to wait (when it said), and `detail` is a
    short machine-readable reason (for invalid output: what was wrong) that may be shown back to the model."""

    def __init__(
        self, message: str, *, retryable: bool = False, kind: ErrorKind = "other",
        retry_after_s: float | None = None, detail: str = "",
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.kind: ErrorKind = kind
        self.retry_after_s = retry_after_s
        self.detail = detail


@dataclass(frozen=True)
class Usage:
    """Tokens a call used, as the provider reported them. None means the provider did not say."""

    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class CallOptions:
    """Per-call limits. None means the provider's own default."""

    timeout_s: float | None = None
    max_output_tokens: int | None = None


@dataclass(frozen=True)
class Capabilities:
    """What an adapter declares about itself (decision D1)."""

    structured_output: str = "json_schema"
    max_input_tokens: int | None = None  # None: not declared


@dataclass
class Generation(Generic[V]):
    """One successful call: the validated value and what it cost."""

    value: V
    usage: Usage = field(default_factory=Usage)
    latency_s: float = 0.0
    model: str = ""  # the model the provider says served the call, when it says


class LLMProvider(Protocol):
    name: str
    model: str

    def generate_structured(self, schema: type[T], prompt: str, *, system: str | None = None) -> T:
        """Return an instance of `schema` validated by Pydantic, or raise ProviderError."""
        ...


class GeneratingProvider(LLMProvider, Protocol):
    """An adapter that makes exactly one attempt and reports usage. Secrets it holds are listed so errors can be redacted."""

    capabilities: Capabilities
    secrets: tuple[str, ...]

    def generate(
        self, schema: type[T], prompt: str, *, system: str | None = None, options: CallOptions = CallOptions()
    ) -> Generation[T]:
        ...
