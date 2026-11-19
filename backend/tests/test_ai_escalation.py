"""A stronger model is asked once, and only when the checks still fail after the one repair. Never by default."""

from __future__ import annotations

from test_skill_build import FIRST, NOW, ask_answers, draft, round_one, round_two, uncovered_tests

from skillforge.ai import AIService, Profile, ProfileSet
from skillforge.build.models import SkillTest
from skillforge.build.pipeline import build_skill
from skillforge.providers import CallOptions, MockProvider, ProviderError


def named(mock, name, model):
    mock.name, mock.model = name, model
    return mock


def service(main, big=None):
    default = Profile("default", named(main, "gemini", "main-model"), CallOptions())
    escalation = Profile("escalation", named(big, "gemini", "big-model"), CallOptions()) if big is not None else None
    return AIService(ProfileSet(default, {}, escalation), sleep=lambda s: None)


def build(tmp_path, svc):
    return build_skill(FIRST, svc, ask=ask_answers, approve=lambda spec: True, out_root=tmp_path / "out", now=NOW)


def worse():  # fails three structural checks: an unknown criterion, an uncovered one, and no negative test
    return draft(tests=[SkillTest(name="p", kind="positive", input_description="x", expected_result="y", covers=["AC9"])])


def test_no_escalation_by_default_so_the_calls_are_exactly_as_before(tmp_path):
    main = MockProvider([round_one(), round_two(), uncovered_tests(), uncovered_tests()])
    result = build(tmp_path, service(main))
    assert result.status == "draft" and len(main.calls) == 4 and result.model_calls == 4


def test_a_configured_stronger_model_fixes_a_design_that_still_fails_after_the_repair(tmp_path):
    main = MockProvider([round_one(), round_two(), uncovered_tests(), uncovered_tests()])
    big = MockProvider([draft()])
    result = build(tmp_path, service(main, big))
    assert result.status == "ok" and len(main.calls) == 4 and len(big.calls) == 1 and result.model_calls == 5
    assert "tests only cite acceptance criteria that exist" in big.calls[0]["prompt"]  # it is shown the real failures
    assert any("stronger model" in n for n in result.notes)
    assert (result.sdm.provenance.provider, result.sdm.provenance.model) == ("gemini", "big-model")  # the file says who wrote it


def test_the_stronger_model_never_makes_it_worse(tmp_path):
    main = MockProvider([round_one(), round_two(), uncovered_tests(), uncovered_tests()])
    result = build(tmp_path, service(main, MockProvider([worse()])))
    assert result.status == "draft" and result.sdm.provenance.model == "main-model"
    assert any("stronger model" in n and "kept" in n for n in result.notes)


def test_no_escalation_when_the_repair_already_fixed_it(tmp_path):
    bad = draft(tests=[SkillTest(name="p", kind="positive", input_description="x", expected_result="y", covers=[])])
    main = MockProvider([round_one(), round_two(), bad, draft()])
    big = MockProvider([])  # asking it at all would raise
    result = build(tmp_path, service(main, big))
    assert result.status == "ok" and big.calls == []


def test_a_stronger_model_that_cannot_be_reached_never_destroys_the_design(tmp_path):
    main = MockProvider([round_one(), round_two(), uncovered_tests(), uncovered_tests()])
    result = build(tmp_path, service(main, MockProvider([ProviderError("model unreachable")])))
    assert result.status == "draft" and any("could not be reached" in n for n in result.notes)
