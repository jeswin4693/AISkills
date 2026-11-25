"""Slice AD: the Testing Lab. The engine's three small additions (which cases will run, progress, a machine-readable outcome), then the
service and the API that keep a run in the database and let a page poll it. Offline: a scripted model and inline jobs."""

from __future__ import annotations

import pytest
from test_evaluate import CASES, WITH, WITHOUT, a, case, loaded, replier

from skillforge.evaluate import EvalReport, plan_cases, run_eval
from skillforge.providers import MockProvider

# ---- the engine: which cases will run ----------------------------------------------------------------------


def test_the_plan_lists_the_cases_that_will_run_and_why_the_others_will_not():
    tests = [*CASES, case("blank", "edge", "", a("contains", "x")), case("unchecked", "edge", "hi")]
    runnable, skipped = plan_cases(loaded(tests), max_cases=12)
    assert [t.name for t in runnable] == ["short change", "no description", "many changes"]
    assert skipped == ["blank: it has no message to send or no check to run", "unchecked: it has no message to send or no check to run"]


def test_the_plan_cuts_at_the_cap_and_says_so_for_each_case_left_out():
    runnable, skipped = plan_cases(loaded(CASES * 3), max_cases=4)
    assert len(runnable) == 4 and len(skipped) == 5 and all("only the first 4 cases are run" in s for s in skipped)


def test_what_run_eval_runs_is_exactly_what_the_plan_listed():
    tests = [*CASES, case("blank", "edge", "", a("contains", "x"))]
    plan, skipped = plan_cases(loaded(tests), max_cases=12)
    report = run_eval(MockProvider(replier()), loaded(tests))
    assert [c.name for c in report.cases] == [t.name for t in plan] and report.skipped == skipped


# ---- the engine: progress ---------------------------------------------------------------------------------


def test_progress_is_reported_after_each_case_with_how_many_there_will_be():
    seen: list[tuple[int, int]] = []
    run_eval(MockProvider(replier()), loaded(), on_case=lambda done, total: seen.append((done, total)))
    assert seen == [(1, 3), (2, 3), (3, 3)]


def test_progress_counts_only_the_cases_that_run_not_the_skipped_ones():
    seen: list[tuple[int, int]] = []
    tests = [*CASES, case("blank", "edge", "", a("contains", "x"))]
    run_eval(MockProvider(replier()), loaded(tests), on_case=lambda d, t: seen.append((d, t)))
    assert seen[-1] == (3, 3) and len(seen) == 3


def test_a_skill_that_cannot_run_reports_no_progress_and_asks_no_model():
    seen: list[tuple[int, int]] = []
    mock = MockProvider([])
    run_eval(mock, loaded(needs="it asks for read_files"), on_case=lambda d, t: seen.append((d, t)))
    assert seen == [] and mock.calls == []


# ---- the engine: the outcome as a code ----------------------------------------------------------------------


@pytest.mark.parametrize("with_skill, without, expected", [
    (WITH, WITHOUT, "helped"),
    (WITH, WITH, "adds_nothing"),
    (WITHOUT, WITH, "worse"),
    (WITHOUT, WITHOUT, "no_difference"),
])
def test_the_outcome_is_a_code_a_page_can_rely_on(with_skill, without, expected):
    report = run_eval(MockProvider(replier(with_skill, without)), loaded())
    assert report.outcome() == expected


def test_too_few_cases_and_no_comparison_and_not_run_each_have_their_own_code():
    assert run_eval(MockProvider(replier()), loaded(CASES[:2])).outcome() == "too_few"
    assert run_eval(MockProvider(replier()), loaded(), baseline=False).outcome() == "with_only"
    assert run_eval(MockProvider([]), loaded(needs="it asks for network")).outcome() == "not_run"
    assert run_eval(MockProvider([]), loaded([])).outcome() == "not_run"
    assert EvalReport("s", runnable=True).outcome() == "not_run"  # runnable in principle, but no case was run


def test_the_wording_of_the_verdict_still_follows_the_outcome_it_was_written_from():
    # The verdict text did not change when the code was added: each outcome still starts the way the docs say it does.
    starts = {
        "helped": "The skill helped:", "adds_nothing": "The model passed every test run without the skill too",
        "worse": "The skill made it WORSE", "no_difference": "No difference on these tests:",
    }
    for (with_skill, without), code in (((WITH, WITHOUT), "helped"), ((WITH, WITH), "adds_nothing"), ((WITHOUT, WITH), "worse"), ((WITHOUT, WITHOUT), "no_difference")):
        report = run_eval(MockProvider(replier(with_skill, without)), loaded())
        assert report.outcome() == code and report.verdict().startswith(starts[code])
