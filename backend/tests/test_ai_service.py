"""AIService: routing by task, one retry policy, budgets, usage, redaction. Only fakes: no network, no real key."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from skillforge.ai.policy import NO_WAIT, Policy
from skillforge.ai.profiles import Profile, ProfileSet
from skillforge.ai.service import AIService, UsageRecord
from skillforge.ai.tasks import Task, Tier
from skillforge.providers import CallOptions, Capabilities, Generation, MockProvider, ProviderError, Usage
from skillforge.providers.retry import generate_with_retry


class Answer(BaseModel):
    word: str
    count: int


OK = Answer(word="ok", count=1)


def boom(kind="overloaded", retryable=True, **kw):
    return ProviderError(f"{kind} failure", kind=kind, retryable=retryable, **kw)


class Fake:
    """A provider that reports usage, like the real adapters. `results` holds Generation objects or errors, in order."""

    capabilities = Capabilities()

    def __init__(self, results, name="fake", model="fake-1", secrets=()):
        self.results, self.name, self.model, self.secrets, self.calls = list(results), name, model, tuple(secrets), []

    def generate(self, schema, prompt, *, system=None, options=CallOptions()):
        self.calls.append({"prompt": prompt, "system": system, "options": options})
        item = self.results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def generate_structured(self, schema, prompt, *, system=None):
        return self.generate(schema, prompt, system=system).value


def gen(value=OK, tokens=(11, 7)):
    return Generation(value, Usage(*tokens), 0.01, "served")


def service(provider, *, tiers=None, escalation=None, fallbacks=(), **kw):
    default = Profile("default", provider, CallOptions(timeout_s=90.0))
    profiles = ProfileSet(default, tiers or {}, escalation, tuple(Profile("fallback", f, CallOptions()) for f in fallbacks))
    kw.setdefault("sleep", lambda s: None)
    kw.setdefault("rng", lambda: 0.0)
    return AIService(profiles, **kw)


class Recorder:
    def __init__(self):
        self.rows: list[UsageRecord] = []

    def record(self, rec):
        self.rows.append(rec)


def test_routes_each_task_to_its_tier_and_passes_the_tiers_options():
    default, fast, code = Fake([gen()], "d"), Fake([gen()], "f"), Fake([gen()], "c")
    svc = service(default, tiers={
        Tier.FAST: Profile("fast", fast, CallOptions(timeout_s=30.0)), Tier.CODE: Profile("code", code, CallOptions(timeout_s=180.0)),
    })
    svc.generate(Task.EXTRACT, Answer, "p1", "s")
    svc.generate(Task.DESIGN, Answer, "p2")
    svc.generate(Task.CODE, Answer, "p3")
    assert [len(x.calls) for x in (fast, default, code)] == [1, 1, 1]
    assert fast.calls[0]["options"].timeout_s == 30.0 and fast.calls[0]["system"] == "s" and code.calls[0]["options"].timeout_s == 180.0


def test_transient_errors_back_off_then_succeed_and_every_attempt_is_counted():
    waits = []
    p = Fake([boom(), boom(), gen()])
    svc = service(p, sleep=waits.append)
    value, calls = svc.generate(Task.DESIGN, Answer, "q")
    assert value == OK and calls == 3 and waits == [1.5, 3.0]
    assert svc.usage.calls == 3 and svc.usage.input_tokens == 11 and svc.usage.output_tokens == 7


def test_invalid_output_is_tried_again_with_what_was_wrong():
    p = Fake([boom("invalid_output", detail="count is missing"), gen()])
    waits = []
    svc = service(p, sleep=waits.append)
    assert svc.generate(Task.DESIGN, Answer, "original prompt")[1] == 2
    assert p.calls[0]["prompt"] == "original prompt"
    assert p.calls[1]["prompt"].startswith("original prompt") and "count is missing" in p.calls[1]["prompt"] and waits == []


def test_a_rate_limit_asking_for_a_long_wait_stops_without_sleeping():
    waits = []
    svc = service(Fake([boom("rate_limit", False, retry_after_s=45.0)]), sleep=waits.append)
    with pytest.raises(ProviderError, match="45") as info:
        svc.generate(Task.DESIGN, Answer, "q")
    assert waits == [] and info.value.kind == "rate_limit"


def test_a_rate_limit_with_a_short_wait_waits_exactly_that_long():
    waits = []
    assert service(Fake([boom("rate_limit", False, retry_after_s=7.0), gen()]), sleep=waits.append).generate(Task.DESIGN, Answer, "q")[1] == 2
    assert waits == [7.0]


def test_errors_are_redacted_before_they_leave_or_are_recorded():
    secret = "sk-secret-value-123456789012345"
    rec = Recorder()
    svc = service(Fake([ProviderError(f"401 for {secret}", kind="auth", detail=secret)], secrets=[secret]), recorder=rec)
    with pytest.raises(ProviderError) as info:
        svc.generate(Task.DESIGN, Answer, "q")
    assert secret not in str(info.value) and secret not in info.value.detail and "[redacted]" in str(info.value)
    assert all(secret not in repr(r) for r in rec.rows)


def test_one_usage_row_per_attempt_including_the_failures():
    rec = Recorder()
    p = Fake([boom(), gen(tokens=(11, 7))], name="gemini", model="m1")
    service(p, recorder=rec).generate(Task.EXTRACT, Answer, "q")
    first, second = rec.rows
    assert (first.attempt, first.status, first.error_kind, first.input_tokens) == (1, "error", "overloaded", None)
    assert (second.attempt, second.status, second.error_kind, second.input_tokens, second.output_tokens) == (2, "ok", "", 11, 7)
    assert (second.task, second.tier, second.provider, second.model) == ("extract", "fast", "gemini", "m1")
    assert isinstance(second.latency_ms, int) and second.latency_ms >= 0


def test_the_tier_name_is_recorded_for_a_tier_with_its_own_profile():
    rec = Recorder()
    svc = service(Fake([gen()]), tiers={Tier.CODE: Profile("code", Fake([gen()], "c", "cm"), CallOptions())}, recorder=rec)
    svc.generate(Task.CODE, Answer, "q")
    assert (rec.rows[0].tier, rec.rows[0].provider, rec.rows[0].model) == ("code", "c", "cm")


def test_a_recorder_that_fails_never_breaks_the_call():
    class Broken:
        def record(self, rec):
            raise RuntimeError("database is gone")

    assert service(Fake([gen()]), recorder=Broken()).generate(Task.DESIGN, Answer, "q")[0] == OK


def test_a_call_budget_stops_before_the_call():
    p = Fake([gen(), gen(), gen()])
    svc = service(p, max_calls=2)
    svc.generate(Task.DESIGN, Answer, "a")
    svc.generate(Task.DESIGN, Answer, "b")
    with pytest.raises(ProviderError) as info:
        svc.generate(Task.DESIGN, Answer, "c")
    assert info.value.kind == "budget" and len(p.calls) == 2


def test_a_retry_cannot_go_past_the_call_budget():
    p = Fake([boom(), boom(), gen()])
    with pytest.raises(ProviderError) as info:
        service(p, max_calls=2).generate(Task.DESIGN, Answer, "q")
    assert info.value.kind == "budget" and len(p.calls) == 2


def test_preflight_refuses_a_prompt_over_the_input_limit_without_calling():
    p = Fake([gen()])
    profiles = ProfileSet(Profile("default", p, CallOptions(), max_input_tokens=10))
    svc = AIService(profiles, sleep=lambda s: None)
    with pytest.raises(ProviderError, match="LLM_MAX_INPUT_TOKENS") as info:
        svc.generate(Task.DESIGN, Answer, "x" * 200)
    assert info.value.kind == "too_long" and p.calls == []
    svc.generate(Task.DESIGN, Answer, "x" * 20)  # 5 tokens: fine
    assert len(p.calls) == 1


def test_single_wraps_a_bare_provider_with_no_waiting(monkeypatch):
    import time

    monkeypatch.setattr(time, "sleep", lambda s: pytest.fail("a bare provider must never wait"))
    mock = MockProvider([boom(), OK])
    svc = AIService.single(mock)
    assert (svc.name, svc.model) == ("mock", "mock-1")
    assert svc.generate(Task.DESIGN, Answer, "q") == (OK, 2) and svc.usage.calls == 2


def test_the_service_is_itself_a_provider():
    svc = service(Fake([gen()], "gemini", "m1"))
    assert (svc.name, svc.model) == ("gemini", "m1")
    assert svc.generate_structured(Answer, "q", system="s") == OK


def test_escalated_is_none_without_a_profile_and_shares_the_budget_with_one():
    assert service(Fake([])).escalated() is None
    big = Fake([gen(), gen()], "big", "bigger")
    svc = service(Fake([gen()]), escalation=Profile("escalation", big, CallOptions()), max_calls=2)
    svc.generate(Task.DESIGN, Answer, "q")
    up = svc.escalated()
    assert up is not None and (up.name, up.model) == ("big", "bigger")
    up.generate(Task.DESIGN, Answer, "q")
    assert svc.usage.calls == 2 and len(big.calls) == 1
    with pytest.raises(ProviderError) as info:
        svc.generate(Task.DESIGN, Answer, "q")
    assert info.value.kind == "budget"


def test_with_recorder_starts_fresh_counters_on_the_same_profiles():
    base = service(Fake([gen(), gen()]), max_calls=1)
    base.generate(Task.DESIGN, Answer, "q")
    rec = Recorder()
    fresh = base.with_recorder(rec)
    assert fresh.usage.calls == 0
    fresh.generate(Task.DESIGN, Answer, "q")
    assert len(rec.rows) == 1 and fresh.usage.calls == 1


# ---- generate_with_retry keeps working for any provider, as before -----------------------------------


def test_the_old_function_retries_a_retryable_failure_once_and_does_not_retry_others():
    mock = MockProvider([ProviderError("schema mismatch", retryable=True), OK])
    assert generate_with_retry(mock, Answer, "q", None) == (OK, 2)
    key = MockProvider([ProviderError("key was rejected")])
    with pytest.raises(ProviderError, match="key was rejected"):
        generate_with_retry(key, Answer, "q", None)
    assert len(key.calls) == 1


def test_the_old_function_gives_up_with_the_old_message_when_attempts_run_out():
    mock = MockProvider([ProviderError("again", retryable=True), ProviderError("again", retryable=True)])
    with pytest.raises(ProviderError, match="No usable answer after 2"):
        generate_with_retry(mock, Answer, "q", None, attempts=2)
    assert len(mock.calls) == 2


def test_the_old_function_honours_an_explicit_cap_and_takes_a_task():
    mock = MockProvider([boom(), boom(), OK])
    with pytest.raises(ProviderError, match="No usable answer after 2"):
        generate_with_retry(mock, Answer, "q", None, attempts=2, task=Task.EXTRACT)


def test_the_old_function_uses_a_service_as_it_is():
    code = Fake([gen()], "c")
    svc = service(Fake([]), tiers={Tier.CODE: Profile("code", code, CallOptions())})
    assert generate_with_retry(svc, Answer, "q", None, task=Task.CODE)[0] == OK and len(code.calls) == 1


# ---- fallbacks: another model answers when the first cannot -------------------------------------------------


def test_a_rate_limited_first_model_hands_over_at_once_without_waiting():
    waits, rec = [], Recorder()
    first, second = Fake([boom("rate_limit", False, retry_after_s=5.0)], "gemini", "m1"), Fake([gen()], "groq", "g1")
    svc = service(first, fallbacks=[second], sleep=waits.append, recorder=rec)
    assert svc.generate(Task.EXTRACT, Answer, "q") == (OK, 2)
    assert waits == [] and len(first.calls) == 1 and len(second.calls) == 1
    assert [(r.provider, r.model, r.tier, r.status, r.error_kind) for r in rec.rows] == [
        ("gemini", "m1", "fast", "error", "rate_limit"), ("groq", "g1", "fallback", "ok", ""),
    ]


def test_an_overloaded_first_model_gets_one_more_try_then_the_fallback():
    waits = []
    first, second = Fake([boom(), boom(), gen()], "gemini", "m1"), Fake([gen()], "groq", "g1")
    svc = service(first, fallbacks=[second], sleep=waits.append)
    assert svc.generate(Task.DESIGN, Answer, "q") == (OK, 3)
    assert len(first.calls) == 2 and len(second.calls) == 1 and waits == [1.5]  # without a fallback it would have tried three times


def test_a_bad_key_or_a_bad_request_never_goes_to_a_fallback():
    for kind in ("auth", "bad_request", "model_missing", "refused"):
        second = Fake([gen()], "groq", "g1")
        with pytest.raises(ProviderError) as info:
            service(Fake([boom(kind, False)]), fallbacks=[second]).generate(Task.DESIGN, Answer, "q")
        assert info.value.kind == kind and second.calls == []


def test_answers_that_keep_failing_the_format_go_to_the_next_model():
    first = Fake([boom("invalid_output", detail="count is missing"), boom("invalid_output")], "gemini", "m1")
    second = Fake([gen()], "groq", "g1")
    assert service(first, fallbacks=[second]).generate(Task.DESIGN, Answer, "q") == (OK, 3)
    assert "count is missing" in first.calls[1]["prompt"] and second.calls[0]["prompt"] == "q"  # a new model starts from the plain prompt


def test_every_fallback_is_tried_in_order_and_the_last_error_names_each_model():
    a = Fake([boom(), boom()], "gemini", "m1")
    b = Fake([boom("rate_limit", False)], "groq", "g1")
    c = Fake([boom("quota", False)], "openai", "o1")
    with pytest.raises(ProviderError) as info:
        service(a, fallbacks=[b, c]).generate(Task.DESIGN, Answer, "q")
    text = str(info.value)
    assert info.value.kind == "quota" and "No model could answer" in text
    assert text.index("gemini/m1") < text.index("groq/g1") < text.index("openai/o1")


def test_a_third_model_can_answer_after_two_fail():
    a, b, c = Fake([boom("quota", False)], "gemini", "m1"), Fake([boom("quota", False)], "groq", "g1"), Fake([gen()], "openai", "o1")
    assert service(a, fallbacks=[b, c]).generate(Task.DESIGN, Answer, "q") == (OK, 3)


def test_the_call_budget_covers_the_fallbacks_too():
    first, second = Fake([boom("quota", False)], "gemini", "m1"), Fake([gen()], "groq", "g1")
    with pytest.raises(ProviderError) as info:
        service(first, fallbacks=[second], max_calls=1).generate(Task.DESIGN, Answer, "q")
    assert info.value.kind == "budget" and second.calls == []


def test_a_fallbacks_key_is_redacted_from_its_errors_too():
    secret = "gsk_" + "Z" * 40
    first = Fake([boom("quota", False)], "gemini", "m1")
    second = Fake([ProviderError(f"401 for {secret}", kind="auth")], "groq", "g1", secrets=[secret])
    with pytest.raises(ProviderError) as info:
        service(first, fallbacks=[second]).generate(Task.DESIGN, Answer, "q")
    assert secret not in str(info.value)


def test_an_escalated_call_does_not_use_the_fallbacks():
    big = Fake([boom("quota", False)], "gemini", "big")
    other = Fake([gen()], "groq", "g1")
    svc = service(Fake([]), escalation=Profile("escalation", big, CallOptions()), fallbacks=[other])
    with pytest.raises(ProviderError):
        svc.escalated().generate(Task.DESIGN, Answer, "q")
    assert other.calls == []
