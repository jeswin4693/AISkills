"""The pure parts of the AI engine: which task uses which tier, when a failed call is tried again, and redaction."""

from __future__ import annotations

import pytest

from skillforge.ai.policy import FALLBACK_KINDS, NO_WAIT, Policy, decide, feedback_text
from skillforge.ai.redact import redact
from skillforge.ai.tasks import TIER_OF, Task, Tier
from skillforge.providers import ProviderError


def test_tasks_map_to_tiers():
    assert TIER_OF[Task.EXTRACT] is Tier.FAST and TIER_OF[Task.SELECT] is Tier.FAST
    assert TIER_OF[Task.DESIGN] is Tier.DESIGN and TIER_OF[Task.SUGGEST] is Tier.DESIGN
    assert TIER_OF[Task.CODE] is Tier.CODE and TIER_OF[Task.ACT] is Tier.ACTOR
    assert TIER_OF[Task.GUIDE] is Tier.DESIGN  # reading documents and drafting parts and routes, like a suggestion
    assert set(TIER_OF) == set(Task) and {t.value for t in Tier} == {"fast", "design", "code", "actor"}


def test_a_request_too_big_for_a_model_is_reported_and_not_handed_to_another_model():
    """The caller can send less; handing a request that was too big for one model to the next would only spend another call."""
    assert "input_too_large" not in FALLBACK_KINDS
    assert FALLBACK_KINDS == {"rate_limit", "quota", "overloaded", "timeout", "connection", "invalid_output"}  # nothing else changed


def err(kind="other", retryable=False, **kw):
    return ProviderError("x", kind=kind, retryable=retryable, **kw)


@pytest.mark.parametrize(
    "error, attempts",
    [
        (err("overloaded", True), 3), (err("timeout", True), 3), (err("connection", True), 3), (err("rate_limit"), 3),
        (err("invalid_output", True), 2), (err("other", True), 2), (err("other", False), 1),
        (err("auth"), 1), (err("model_missing"), 1), (err("bad_request"), 1), (err("quota"), 1), (err("refused"), 1),
        (err("too_long"), 1), (err("input_too_large"), 1), (err("budget"), 1),
    ],
)
def test_attempts_per_kind(error, attempts):
    made = 0
    while True:
        made += 1
        if not decide(error, made, Policy(), rng=lambda: 0.0).retry:
            break
    assert made == attempts


def test_backoff_doubles_and_jitter_stays_within_a_quarter():
    low = decide(err("overloaded", True), 1, Policy(), rng=lambda: 0.0)
    high = decide(err("overloaded", True), 1, Policy(), rng=lambda: 1.0)
    assert (low.wait_s, high.wait_s) == (1.5, 1.875)
    assert (decide(err("overloaded", True), 2, Policy(), rng=lambda: 0.0).wait_s, decide(err("overloaded", True), 2, Policy(), rng=lambda: 1.0).wait_s) == (3.0, 3.75)


def test_no_wait_policy_never_waits():
    assert decide(err("overloaded", True), 1, NO_WAIT).wait_s == 0.0


def test_an_explicit_cap_wins():
    assert decide(err("overloaded", True), 1, Policy(), cap=2, rng=lambda: 0.0).retry
    assert not decide(err("overloaded", True), 2, Policy(), cap=2, rng=lambda: 0.0).retry
    assert not decide(err("overloaded", True), 1, Policy(), cap=1).retry


def test_rate_limit_uses_the_wait_it_was_given_and_refuses_long_ones():
    assert decide(err("rate_limit", retry_after_s=7.0), 1, Policy()).wait_s == 7.0
    long = decide(err("rate_limit", retry_after_s=45.0), 1, Policy())
    assert not long.retry and "45" in long.reason
    assert decide(err("rate_limit"), 1, Policy(), rng=lambda: 0.0).wait_s == 1.5  # no wait given: back off


def test_invalid_output_retries_at_once_with_feedback_capped_at_600_characters():
    d = decide(err("invalid_output", True, detail="x" * 2000), 1, Policy())
    assert d.retry and d.wait_s == 0.0
    assert "x" * 600 in d.feedback and "x" * 601 not in d.feedback
    assert feedback_text(err("invalid_output", True, detail="count is missing")).count("count is missing") == 1


def test_redact_removes_exact_secrets_and_common_key_shapes():
    key = "my-very-secret-value"
    text = f"401 for {key}; AIza{'a' * 35}; sk-{'b' * 24}; sk-ant-{'c' * 20}; Authorization: Bearer {'d' * 30}"
    out = redact(text, [key])
    assert key not in out and "AIza" not in out and "sk-" not in out and "d" * 30 not in out
    assert out.count("[redacted]") == 5


def test_a_groq_shaped_key_is_removed_even_when_it_was_never_configured():
    fake = "gsk_" + "X" * 52  # made up for this test: never a real key
    out = redact(f"Invalid API Key: {fake} was rejected")
    assert fake not in out and "gsk_" not in out and out.count("[redacted]") == 1


def test_short_values_are_not_treated_as_secrets():
    assert redact("the word key appears", ["key", ""]) == "the word key appears"
