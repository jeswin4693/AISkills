"""The gate: a check that runs before EVERY attempt at a model and can stop it (slice AI: a person's daily allowance on the server's model).

Only fakes: no network, no key.
"""

from __future__ import annotations

import pytest
from test_ai_service import OK, Answer, Fake, Recorder, boom, gen, service

from skillforge.ai.profiles import Profile
from skillforge.ai.tasks import Task
from skillforge.providers import CallOptions, ProviderError


def stop() -> None:
    raise ProviderError("The allowance is used up.", kind="allowance", retryable=True)


def test_the_gate_runs_before_every_attempt_not_once_per_call():
    seen: list[int] = []
    fake = Fake([boom("overloaded"), boom("overloaded"), gen()])
    value, made = service(fake, gate=lambda: seen.append(1)).generate(Task.DESIGN, Answer, "p")
    assert value == OK and made == 3
    assert len(seen) == 3  # the two failed attempts and the good one: each is a model call somebody pays for


def test_a_gate_that_raises_stops_the_call_before_the_provider_is_asked():
    fake = Fake([gen()])
    svc = service(fake, gate=stop)
    with pytest.raises(ProviderError) as caught:
        svc.generate(Task.DESIGN, Answer, "p")
    assert caught.value.kind == "allowance" and "used up" in str(caught.value)
    assert fake.calls == []  # nothing was sent
    assert svc.usage.calls == 0  # and a blocked attempt is not counted as a call


def test_a_blocked_attempt_leaves_no_usage_row():
    recorder = Recorder()
    svc = service(Fake([gen()]), gate=stop).with_recorder(recorder)
    with pytest.raises(ProviderError):
        svc.generate(Task.DESIGN, Answer, "p")
    assert recorder.rows == []  # a row is an attempt that was made; this one was not


def test_a_gate_error_is_never_handed_to_a_backup_model():
    # The backup model would use the same server key: stopping the first model and asking the second would walk round the allowance.
    first, backup = Fake([gen()]), Fake([gen()], name="backup")
    with pytest.raises(ProviderError) as caught:
        service(first, fallbacks=[backup], gate=stop).generate(Task.DESIGN, Answer, "p")
    assert first.calls == [] and backup.calls == []
    assert caught.value.kind == "allowance" and "No model could answer" not in str(caught.value)


def test_a_gate_that_lets_two_calls_through_and_then_stops_is_enforced_exactly():
    state = {"n": 0}

    def gate() -> None:
        state["n"] += 1
        if state["n"] > 2:
            stop()

    fake = Fake([gen(), gen(), gen()])
    svc = service(fake, gate=gate)
    svc.generate(Task.DESIGN, Answer, "p1")
    svc.generate(Task.DESIGN, Answer, "p2")
    with pytest.raises(ProviderError):
        svc.generate(Task.DESIGN, Answer, "p3")
    assert len(fake.calls) == 2


def test_with_recorder_and_escalated_keep_the_gate():
    escalation = Profile("escalation", Fake([gen()]), CallOptions())
    svc = service(Fake([gen()]), escalation=escalation, gate=stop)
    with pytest.raises(ProviderError):
        svc.with_recorder(Recorder()).generate(Task.DESIGN, Answer, "p")
    escalated = svc.escalated()
    assert escalated is not None
    with pytest.raises(ProviderError):
        escalated.generate(Task.DESIGN, Answer, "p")


def test_with_recorder_can_hand_over_a_different_gate():
    fake = Fake([gen()])
    svc = service(fake, gate=stop).with_recorder(Recorder(), gate=lambda: None)
    assert svc.generate(Task.DESIGN, Answer, "p")[0] == OK  # the new gate replaced the one that stopped everything


def test_no_gate_changes_nothing():
    assert service(Fake([gen()])).generate(Task.DESIGN, Answer, "p")[0] == OK
