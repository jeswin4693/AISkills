"""When a failed model call is tried again, and how long to wait. Pure code: no clock, no network, nothing random unless asked.

The decision rests on the error's `kind` (set by the adapter), never on parsing its message.

    overloaded, timeout, connection   3 attempts, waiting 1.5 s then 3 s (plus up to 25 % jitter)
    rate_limit                        3 attempts, waiting the time the provider gave (or backing off); over 30 s: stop
    invalid_output                    2 attempts, at once, and the second prompt says what was wrong
    other, marked retryable           2 attempts, with backoff
    everything else                   1 attempt: trying again cannot help (a bad key, no quota, a refusal, a cut-off)
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass

from ..providers.base import ProviderError
from ..providers._errors import MAX_DETAIL, short

_ATTEMPTS = {"overloaded": 3, "timeout": 3, "connection": 3, "rate_limit": 3, "invalid_output": 2}

# Failures that are not the request's fault: another model may well answer. A bad key, a bad request, a missing model or a
# refusal would fail the same way elsewhere (or hide a mistake in the settings), so they never hand over.
FALLBACK_KINDS = frozenset({"rate_limit", "quota", "overloaded", "timeout", "connection", "invalid_output"})


@dataclass(frozen=True)
class Policy:
    base_delay_s: float = 1.5
    max_wait_s: float = 30.0  # a longer wait than this is refused: the person should be told, not left hanging
    jitter: float = 0.25  # up to this fraction is added to every backoff wait


NO_WAIT = Policy(base_delay_s=0.0, max_wait_s=1e9, jitter=0.0)  # a bare provider (tests): the old behaviour, no pauses


@dataclass(frozen=True)
class Decision:
    retry: bool
    wait_s: float = 0.0
    reason: str = ""
    feedback: str = ""  # text to add to the next prompt (invalid output only)


def feedback_text(error: ProviderError) -> str:
    """What the model is told when its answer did not match the format: what was wrong, capped, nothing of anyone's words."""
    return (
        "Your previous answer did not match the required format. What was wrong: "
        f"{short(error.detail or str(error), MAX_DETAIL)} Return a corrected answer in the required format."
    )


def _limit(error: ProviderError) -> int:
    if error.kind in _ATTEMPTS:
        return _ATTEMPTS[error.kind]
    return 2 if error.kind == "other" and error.retryable else 1


def _backoff(attempts_made: int, policy: Policy, rng: Callable[[], float]) -> float:
    return policy.base_delay_s * 2 ** (attempts_made - 1) * (1 + policy.jitter * rng())


def decide(
    error: ProviderError, attempts_made: int, policy: Policy, *, cap: int | None = None,
    rng: Callable[[], float] = random.random,
) -> Decision:
    """Try again? `attempts_made` counts the attempts so far, including the one that just failed. `cap` is a caller's hard
    limit on attempts in total (it can only lower the kind's own limit)."""
    limit = _limit(error) if cap is None else min(_limit(error), cap)
    if attempts_made >= limit:
        return Decision(False, reason=f"gave up after {attempts_made} attempt(s)" if limit > 1 else "")
    if error.kind == "invalid_output":
        return Decision(True, 0.0, "the answer did not match the required format", feedback_text(error))
    if error.kind == "rate_limit":
        wait = error.retry_after_s if error.retry_after_s is not None else _backoff(attempts_made, policy, rng)
        if wait > policy.max_wait_s:
            return Decision(False, reason=f"the provider asked to wait about {round(wait)} s, which is too long to wait here")
        return Decision(True, wait, "rate limited")
    return Decision(True, _backoff(attempts_made, policy, rng), error.kind)
