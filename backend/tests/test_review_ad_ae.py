"""The independent review of slices AD and AE (2026-11-25). Each test reproduces one finding the reviewer confirmed, and failed on the code as it was.

Findings: 1 a regex check could freeze the server (the guard missed alternation and refused harmless patterns); 2 a retry could run a second copy of the
same version; 4 a skill that declares its tools only in SKILL.md was run as text-only; 5 a stale save could overwrite a newer version; 6 a unicode digit
crashed a check with a 500; 7 a case with an unrunnable check looked runnable and gave a misleading verdict; 8 a stored result could be megabytes;
9 a retry was offered for an error it cannot help; 11 a skill with no cases that needs tools got an editor. (3, 10 and 14 are in the page's own tests.)
"""

from __future__ import annotations

import importlib
import json
import threading
import time

import pytest
from test_builder import make  # noqa: F401  (make is a pytest fixture)
from test_case_editor import draft, save, stored_cases
from test_evaluate import CASES, SKILL_MD, a, case, loaded, replier
from test_testing_lab_api import Parked, put_skill, start

from skillforge.build.models import Assertion
from skillforge.evaluate import LoadedSkill, Reply, assertion_problem, blocker, check_assertion, grade, load_files, plan_cases, run_eval

# `skillforge.evaluate` re-exports a FUNCTION called grade, which hides the module of the same name: ask for the module by its full name.
grade_module = importlib.import_module("skillforge.evaluate.grade")
from skillforge.providers import MockProvider, ProviderError


def regex(value: str) -> Assertion:
    return Assertion(kind="regex", value=value, why="")


# ---- 1. a regex check can no longer freeze the server --------------------------------------------------------------


@pytest.mark.parametrize("pattern", [r"(a|aa)+$", r"(a|a)*b", r"(\d|\d\d)+x", r"(?:ab|a)+c", r"(a+)+$", r"(a*)*b", r"(\w+\s?)*$", r"(\d+){2,}"])
def test_a_pattern_that_can_backtrack_exponentially_is_refused_in_plain_words(pattern):
    problem = assertion_problem(regex(pattern))
    assert problem is not None and "repeats a repeat" in problem and "write it more simply" in problem


@pytest.mark.parametrize("pattern", [
    r"^[A-Z]\w+( \w+)?$", r"(\d+)?kg", r"^(Add|Fix|Update)\b", r"\?|please|describe", r"^[A-Z][a-z]+ ", r"(a|b)+", r"\d{3}-\d{4}",
    r"^(?:feat|fix)(\(\w+\))?: ", r"(?i)^what changed", r"^\s*[-*] .+",
])
def test_an_ordinary_pattern_is_not_refused_just_because_a_group_has_a_repeat_in_it(pattern):
    assert assertion_problem(regex(pattern)) is None


def test_a_pattern_the_guard_cannot_see_is_stopped_by_a_time_limit_and_fails_instead_of_freezing(monkeypatch):
    monkeypatch.setattr(grade_module, "REGEX_TIMEOUT", 0.5)
    slow = regex(r"\w*\w*\w*\w*\w*\w*x")  # no repeat inside a repeat, so no guard on the text of it can tell: it is just slow
    assert assertion_problem(slow) is None
    started = time.time()
    result = check_assertion(slow, "a" * 3000)
    assert not result.passed and "too long" in result.detail and "write it more simply" in result.detail
    assert time.time() - started < 5


def test_the_server_keeps_working_while_a_pattern_is_being_stopped(monkeypatch):
    monkeypatch.setattr(grade_module, "REGEX_TIMEOUT", 0.5)
    ticks = []
    stop = threading.Event()

    def ticker():
        while not stop.is_set():
            ticks.append(time.time())
            time.sleep(0.02)

    t = threading.Thread(target=ticker)
    t.start()
    try:
        check_assertion(regex(r"\w*\w*\w*\w*\w*\w*x"), "a" * 3000)
    finally:
        stop.set()
        t.join()
    gaps = [b - a_ for a_, b in zip(ticks, ticks[1:])]
    assert len(ticks) > 5 and max(gaps) < 0.4  # the process was never held while the pattern ran (it ran in a child that was killed)


def test_ordinary_patterns_still_judge_replies_correctly_through_the_child_process():
    assert check_assertion(regex(r"^[A-Z][a-z]+ "), "Fix the login").passed
    assert not check_assertion(regex(r"^[A-Z][a-z]+ "), "42 is the answer").passed
    assert check_assertion(regex(r"\?|please"), "What changed? ").passed
    assert check_assertion(regex("café"), "un CAFÉ noir").passed  # unicode and case survive the trip
    assert check_assertion(regex("a"), "x\ud800a").passed  # a lone surrogate in a reply is data, not a crash
    assert [r.passed for r in grade([regex("fix"), regex("zzz")], "Fix it")] == [True, False]


def test_a_pattern_that_cannot_be_started_in_a_child_fails_the_check_and_says_so(monkeypatch):
    def cannot(*args, **kwargs):
        raise OSError("no process for you")

    monkeypatch.setattr(grade_module.subprocess, "run", cannot)
    result = check_assertion(regex("fix"), "Fix it")
    assert not result.passed and "could not be run" in result.detail  # never a pass that did not run


# ---- 6. odd digits ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["²", "①", "٣", "9" * 5000, "1" * 8, "0"])
def test_a_number_that_only_looks_like_one_is_refused_and_never_crashes_a_check(value):
    check = Assertion(kind="max_chars", value=value, why="")
    assert "whole number" in (assertion_problem(check) or "")
    result = check_assertion(check, "some reply")
    assert not result.passed and result.detail.startswith("could not be checked")


def test_saving_a_case_with_a_unicode_digit_is_a_400_in_words_not_a_500(make):
    env = make(replier())
    put_skill(env)
    r = save(env, [draft(checks=[{"kind": "max_chars", "value": "²", "why": ""}])])
    assert r.status_code == 400 and "whole number" in r.json()["detail"]


def test_a_stored_skill_with_such_a_number_is_listed_as_not_runnable_and_costs_no_model_call(make):
    env = make(replier())
    put_skill(env, tests=[case("odd", "positive", "hi there", a("max_chars", "²")), *CASES[:2]])
    plan = env.client.get("/api/evals/preview", params={"name": "commit-writer"}).json()
    assert [c["name"] for c in plan["cases"]] == ["short change", "no description"]
    assert any(s.startswith("odd: a check cannot be run") for s in plan["skipped"])


# ---- 7. a case whose check cannot be run is not run ------------------------------------------------------------------


def test_a_case_with_a_check_that_cannot_be_run_is_skipped_with_the_reason_so_the_preview_and_the_run_agree():
    broken = [case("bad regex", "edge", "hello", a("regex", "(")), case("zero", "edge", "hello", a("max_chars", "0")), case("loop", "edge", "hello", a("regex", "(a+)+$"))]
    runnable, skipped = plan_cases(loaded([*broken, *CASES]), max_cases=12)
    assert [t.name for t in runnable] == [c.name for c in CASES]
    assert len(skipped) == 3 and all("a check cannot be run" in s for s in skipped)
    assert "not a valid regular expression" in skipped[0] and "whole number" in skipped[1] and "repeats a repeat" in skipped[2]


def test_the_model_is_never_asked_about_a_case_whose_check_cannot_be_run():
    mock = MockProvider(lambda schema, prompt, system: (_ for _ in ()).throw(AssertionError("the model must not be asked")))
    report = run_eval(mock, loaded([case("bad", "edge", "hello", a("regex", "("))]))
    assert report.cases == [] and mock.calls == [] and report.outcome() == "not_run"


def test_a_skill_whose_only_cases_have_broken_checks_is_not_runnable(make):
    env = make(replier())
    put_skill(env, tests=[case("bad", "edge", "hello", a("regex", "("))])
    plan = env.client.get("/api/evals/preview", params={"name": "commit-writer"}).json()
    assert plan["runnable"] is False and plan["blocker"] == "nothing_runnable"
    assert start(env).status_code == 400 and env.mock.calls == []


# ---- 8. a stored result stays small ----------------------------------------------------------------------------------


def test_a_stored_result_cuts_what_a_stored_skill_could_make_huge_and_marks_the_cut(make):
    env = make(lambda schema, prompt, system: Reply(text="Fix login " + "w" * 10))
    big = "x" * 90_000
    put_skill(env, tests=[case(f"big{i}", "edge", "fixed the login", a("contains", big, big)) for i in range(3)])
    run = start(env, baseline=False).json()
    check = run["result"]["cases"][0]["with_skill"]["tries"][0]["checks"][0]
    assert len(check["value"]) <= 301 and len(check["why"]) <= 301 and len(check["detail"]) <= 301 and check["value"].endswith("…")
    assert len(json.dumps(run)) < 30_000
    shown = env.client.get("/api/evals/preview", params={"name": "commit-writer"}).json()["cases"][0]["checks"][0]
    assert len(shown["value"]) <= 301 and len(shown["why"]) <= 301


# ---- 2. one run per version, retry included --------------------------------------------------------------------------


def test_run_it_again_cannot_start_a_second_copy_while_another_run_of_the_version_is_going(make):
    env = make(lambda schema, prompt, system: (_ for _ in ()).throw(ProviderError("busy", retryable=True)))
    put_skill(env)
    failed = start(env).json()
    assert failed["status"] == "failed"
    parked = env.builder.runner = Parked()
    second = start(env).json()  # a new run of the same version, now working
    assert second["status"] == "working" and second["id"] != failed["id"]
    r = env.client.post(f"/api/evals/{failed['id']}/retry")
    assert r.status_code == 409 and "already going" in r.json()["detail"]
    working = [x for x in env.client.get("/api/evals", params={"name": "commit-writer"}).json() if x["status"] == "working"]
    assert [x["id"] for x in working] == [second["id"]] and len(parked.jobs) == 1
    assert env.client.get(f"/api/evals/{failed['id']}").json()["status"] == "failed"  # the failed run was left as it was


def test_a_failed_run_can_still_be_retried_when_nothing_else_of_that_version_is_going(make):
    answers = {"fail": True}

    def respond(schema, prompt, system):
        if answers["fail"]:
            raise ProviderError("busy", retryable=True)
        return replier()(schema, prompt, system)

    env = make(respond)
    put_skill(env)
    run = start(env).json()
    answers["fail"] = False
    assert env.client.post(f"/api/evals/{run['id']}/retry").json()["status"] == "done"


def test_a_run_of_another_version_does_not_block_a_retry(make):
    env = make(lambda schema, prompt, system: (_ for _ in ()).throw(ProviderError("busy", retryable=True)))
    put_skill(env)
    failed = start(env).json()
    put_skill(env, tests=CASES + [case("another", "edge", "fixed the login again", a("max_lines", "5"))])  # v2
    env.builder.runner = Parked()
    assert start(env, version=2).json()["status"] == "working"
    assert env.client.post(f"/api/evals/{failed['id']}/retry").json()["status"] == "working"  # v1 and v2 are different versions


# ---- 9. a retry is offered only where it can help --------------------------------------------------------------------


@pytest.mark.parametrize("error, retryable", [
    (ProviderError("The model refused to answer", kind="refused"), False),
    (ProviderError("The request was malformed", kind="bad_request"), False),
    (ProviderError("The model's answer did not fit the format", kind="invalid_output"), False),
    (ProviderError("The call budget is used up", kind="budget"), False),
    (ProviderError("The key was refused", kind="auth"), True),  # fix the key in Settings, then run it again
    (ProviderError("No model is set up."), True),
    (ProviderError("The model is busy", retryable=True, kind="overloaded"), True),
    (ProviderError("The model timed out", retryable=True, kind="timeout"), True),
])
def test_run_it_again_is_offered_only_for_a_failure_that_asking_again_or_a_fix_can_help(make, error, retryable):
    def respond(schema, prompt, system):
        raise error

    env = make(respond)
    put_skill(env)
    run = start(env).json()
    assert run["status"] == "failed" and run["retryable"] is retryable


# ---- 4 and 11. what makes a skill need tools ---------------------------------------------------------------------------

TOOLS_MD = SKILL_MD.replace("description: Writes commit messages.\n", "description: Writes commit messages.\nallowed-tools: Bash, Read, Write\n")


def test_a_skill_that_declares_its_tools_only_in_its_front_matter_needs_tools():
    skill = load_files({"SKILL.md": TOOLS_MD})
    assert "allowed-tools" in skill.needs_tools and "Bash" in skill.needs_tools


def test_allowed_tools_can_be_a_list_and_an_empty_one_asks_for_nothing():
    listed = SKILL_MD.replace("description: Writes commit messages.\n", "description: Writes commit messages.\nallowed-tools:\n  - Read\n  - Grep\n")
    assert "Read, Grep" in load_files({"SKILL.md": listed}).needs_tools
    empty = SKILL_MD.replace("description: Writes commit messages.\n", "description: Writes commit messages.\nallowed-tools: []\n")
    assert load_files({"SKILL.md": empty}).needs_tools == "" and load_files({"SKILL.md": SKILL_MD}).needs_tools == ""


def test_a_built_skill_that_says_it_twice_is_described_once():
    files = {"SKILL.md": TOOLS_MD, "skill.sdm.json": json.dumps({"permissions": ["read_files"]})}
    assert load_files(files).needs_tools == "it asks for read_files"


def test_the_lab_refuses_a_skill_whose_front_matter_asks_for_tools(make):
    env = make(replier())
    put_skill(env, skill_md=TOOLS_MD)
    plan = env.client.get("/api/evals/preview", params={"name": "commit-writer"}).json()
    assert plan["runnable"] is False and plan["blocker"] == "needs_tools" and "Bash" in plan["reason"]
    assert start(env).status_code == 400 and env.mock.calls == []


def test_a_skill_with_no_cases_that_needs_tools_is_told_it_needs_tools_not_to_write_cases(make):
    assert blocker(LoadedSkill("s", "text", [], "it asks for network"))[0] == "needs_tools"
    env = make(replier())
    put_skill(env, tests=[], perms=["read_files"])
    assert env.client.get("/api/evals/preview", params={"name": "commit-writer"}).json()["blocker"] == "needs_tools"


# ---- 5. two saves from the same version cannot both win --------------------------------------------------------------


def test_a_save_made_from_a_version_that_stopped_being_the_latest_while_it_was_being_checked_is_refused(make, monkeypatch):
    import skillforge.library.service as service

    env = make(replier())
    put_skill(env)
    real_check = service.check_source
    parked, release, calls = threading.Event(), threading.Event(), []

    def slow_check(src, kind="skill"):
        calls.append(1)
        if len(calls) == 1:  # save A stops here, inside the static checks, after it looked and saw v1 as the latest
            parked.set()
            assert release.wait(20)
        return real_check(src, kind)

    monkeypatch.setattr(service, "check_source", slow_check)
    outcome: dict = {}
    worker = threading.Thread(target=lambda: outcome.update(a=save(env, [draft("from A")])))
    worker.start()
    assert parked.wait(20)
    b = save(env, [draft("from B")])  # B, also made from v1, is kept as v2 while A is still being checked
    release.set()
    worker.join(30)
    assert b.status_code == 200 and b.json()["version"]["tag"] == "v2"
    assert outcome["a"].status_code == 409 and "not the latest" in outcome["a"].json()["detail"]
    assert [v.tag for v in env.library.versions("commit-writer")] == ["v1", "v2"]
    assert stored_cases(env)[0]["name"] == "from B"  # nothing newer was overwritten


def test_the_library_will_not_store_a_version_on_top_of_a_latest_it_did_not_expect(make):
    from skillforge.library import Conflict

    env = make(replier())
    put_skill(env)
    put_skill(env, tests=CASES[:2])  # v2
    with pytest.raises(Conflict, match="v2"):
        env.library.add("commit-writer", {"SKILL.md": b"x"}, source_kind="folder", source_label="t", expect_latest=1)
    assert [v.tag for v in env.library.versions("commit-writer")] == ["v1", "v2"]
    version, created = env.library.add("commit-writer", {"SKILL.md": b"x"}, source_kind="folder", source_label="t", expect_latest=2)
    assert created and version.tag == "v3"
