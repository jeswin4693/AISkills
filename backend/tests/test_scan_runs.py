"""The behaviour scan as a kept, polled run (slice AK, task 5): `Builder.scans`, over the real engine with scripted models.

The engine itself is tested in test_canary_*.py; what is tested here is the bookkeeping around it: a preview that asks no model, a run that is a row (so a reload
keeps it and a second click cannot spend the quota twice), whose it is, what it counts toward, how it ends, and that a stored result stays small.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from test_accounts_isolation import MISSING, Parked, World, world  # noqa: F401  (world is a pytest fixture)
from test_canary_runner import SKILL, Agent, c, clean, exfiltrate, finish, step

from skillforge.builder import BadRequest, PersonLimits, SessionNotFound, WrongState
from skillforge.builder.limits import LimitReached
from skillforge.builder.scans import DEFAULT_SCENARIOS, RUN_CAP, SCENARIO_CAP, report_view
from skillforge.canary.runner import LIMITS, MAX_TURNS, CanaryReport, ScenarioRun, Turn
from skillforge.db import LOCAL_USER_ID, ModelCall
from skillforge.library import NotFound
from skillforge.providers import ProviderError

NAME = "invoice-summary"
AGENT = "---\nname: reviewer\ndescription: Reviews a change.\ntools: Read, Grep\n---\nReview the change and report what you found.\n"


def put(lib, name: str = NAME, text: str = SKILL, file: str = "SKILL.md") -> None:
    lib.add(name, {file: text.encode()}, source_kind="test", source_label="t")


def owner_world(world, policy=clean, **kw) -> tuple[World, Agent]:
    agent = Agent(policy)
    w = world(agent, service=True, **kw)
    put(w.library)
    return w, agent


# ---- what would run -----------------------------------------------------------------------------------------------------------------------------


def test_a_preview_lists_the_tasks_and_the_most_it_could_cost_and_asks_no_model(world):
    w, agent = owner_world(world)
    p = w.builder.scans.preview(NAME)
    assert [t["source"] for t in p["tasks"]] == ["fixed"] * DEFAULT_SCENARIOS and all(t["message"] and t["id"] for t in p["tasks"])
    assert p["max_calls"] == DEFAULT_SCENARIOS * 1 * MAX_TURNS * 2 + 1  # with a control run, and one more call for the task a model drafts
    assert (p["name"], p["kind"], p["version"], p["tag"], p["draft"], p["control"]) == (NAME, "skill", 1, "v1", True, True)
    assert p["limits_text"] == LIMITS and p["limits"] == {"max_runs": RUN_CAP, "max_scenarios": SCENARIO_CAP, "default_scenarios": DEFAULT_SCENARIOS}
    assert agent.prompts == []  # nothing was asked of a model


def test_the_preview_follows_the_options_the_same_way_the_run_will(world):
    w, _ = owner_world(world)
    p = w.builder.scans.preview(NAME, runs=2, scenarios=3, control=False, draft=False)
    assert len(p["tasks"]) == 3 and p["max_calls"] == 3 * 2 * MAX_TURNS and p["draft"] is False and p["control"] is False


def test_only_skills_and_agents_with_instructions_can_be_scanned(world):
    w, _ = owner_world(world)
    put(w.library, "readme-only", "just a readme", file="README.md")
    for call in (lambda: w.builder.scans.preview(NAME, kind="plugin"), lambda: w.builder.scans.preview(NAME, kind="nope"), lambda: w.builder.scans.preview("readme-only")):
        with pytest.raises(BadRequest):
            call()
    with pytest.raises(BadRequest, match="no SKILL.md or AGENT.md"):
        w.builder.scans.preview("readme-only")
    with pytest.raises(NotFound):
        w.builder.scans.preview("nothing-here")
    with pytest.raises(NotFound):
        w.builder.scans.preview(NAME, version=9)


# ---- a run --------------------------------------------------------------------------------------------------------------------------------------


def test_a_run_ends_done_with_the_engines_outcome_and_never_says_safe(world):
    w, _ = owner_world(world)
    run = w.builder.scans.start(NAME, draft=False)
    assert run["status"] == "done" and run["progress"] == {"done": 5, "total": 5} and run["error"] == "" and run["retryable"] is False
    result = run["result"]
    assert result["outcome"] == "nothing_observed" and len(result["runs"]) == 5 and result["controls"] == [] and result["limits"] == LIMITS
    assert all(r["finished"] for r in result["runs"]) and result["runs"][0]["turns"]
    text = (result["verdict"] + result["limits"]).lower()
    assert "not proof" in text and "is safe" not in text and "no risk" not in text


def test_a_skill_that_sends_a_secret_away_is_flagged_with_its_findings_and_a_control(world):
    w, _ = owner_world(world, exfiltrate)
    result = w.builder.scans.start(NAME, draft=False)["result"]
    assert result["outcome"] == "flagged" and "likely cause" in result["verdict"]
    assert {"reads_secret", "canary_sent"} <= {o["kind"] for r in result["runs"] for o in r["observations"]}
    assert len(result["controls"]) == len(result["runs"])  # the same tasks without the skill, so a finding is not blamed on the wrong thing


def test_a_run_that_never_ends_is_incomplete_and_never_clean(world):
    def never_ends(side, message, n, prompt):
        return step(c("list_files", "/work"))

    w, _ = owner_world(world, never_ends)
    result = w.builder.scans.start(NAME, draft=False)["result"]
    assert result["outcome"] == "incomplete" and all(not r["finished"] for r in result["runs"]) and "too little" in result["verdict"].lower()


def test_an_agent_can_be_scanned_too(world):
    w, _ = owner_world(world)
    put(w.library.for_kind("agent"), "reviewer", AGENT, "AGENT.md")
    run = w.builder.scans.start("reviewer", kind="agent", draft=False)
    assert run["status"] == "done" and run["kind"] == "agent" and run["result"]["outcome"] == "nothing_observed"


def test_the_list_shows_a_short_summary_without_the_heavy_result(world):
    w, _ = owner_world(world)
    clean_run = w.builder.scans.start(NAME, draft=False)
    (item,) = w.builder.scans.list(NAME)
    assert item["id"] == clean_run["id"] and "result" not in item
    assert item["summary"] == {"outcome": "nothing_observed", "calls": clean_run["result"]["calls"], "findings": 0, "finished": 5, "total": 5}


def test_the_summary_counts_the_serious_findings(world):
    w, _ = owner_world(world, exfiltrate)
    w.builder.scans.start(NAME, draft=False)
    summary = w.builder.scans.list(NAME)[0]["summary"]
    assert summary["outcome"] == "flagged" and summary["findings"] >= 5


def test_the_options_are_kept_with_the_run(world):
    w, _ = owner_world(world)
    run = w.builder.scans.start(NAME, runs=2, scenarios=3, control=False, draft=False)
    assert (run["runs"], run["scenarios"], run["control"], run["draft"]) == (2, 3, False, False) and run["progress"]["total"] == 6


# ---- how a run fails ------------------------------------------------------------------------------------------------------------------------------


def test_a_model_that_cannot_answer_fails_the_run_and_it_can_be_retried_when_that_is_fixed(world):
    state = {"ok": False}

    def policy(side, message, n, prompt):
        if not state["ok"]:
            raise ProviderError("the key was rejected", kind="auth")
        return clean(side, message, n, prompt)

    w, _ = owner_world(world, policy)
    run = w.builder.scans.start(NAME, draft=False)
    assert run["status"] == "failed" and run["retryable"] is True and "key was rejected" in run["error"] and run["result"] is None
    state["ok"] = True
    again = w.builder.scans.retry(run["id"])
    assert again["id"] == run["id"] and again["status"] == "done" and again["error"] == "" and again["result"]["outcome"] == "nothing_observed"


def test_a_refusal_cannot_be_retried_and_an_unexpected_error_hides_its_text(world):
    def refuses(side, message, n, prompt):
        raise ProviderError("the model refused", kind="refused")

    w, _ = owner_world(world, refuses)
    refused = w.builder.scans.start(NAME, draft=False)
    assert refused["status"] == "failed" and refused["retryable"] is False

    def explodes(side, message, n, prompt):
        raise RuntimeError("C:\\secret\\place\\file.txt")

    w2, _ = owner_world(world, explodes)
    broken = w2.builder.scans.start(NAME, draft=False)
    assert broken["status"] == "failed" and "RuntimeError" in broken["error"] and "secret" not in broken["error"] and broken["retryable"] is False


def test_only_a_failed_run_can_be_retried(world):
    w, _ = owner_world(world)
    done = w.builder.scans.start(NAME, draft=False)
    with pytest.raises(WrongState):
        w.builder.scans.retry(done["id"])


# ---- a second click, whose it is, what it counts toward -----------------------------------------------------------------------------------------------


def test_a_second_click_on_a_running_scan_gets_that_run_and_not_another(world):
    w, _ = owner_world(world, runner=Parked())
    first = w.builder.scans.start(NAME, draft=False)
    second = w.builder.scans.start(NAME, draft=False)
    assert first["status"] == second["status"] == "working" and first["id"] == second["id"] and len(w.builder.scans.list(NAME)) == 1


def test_another_persons_run_is_a_404_identical_to_one_that_never_existed(world):
    w = world(Agent(clean), service=True)
    w.person(1)
    w.person(2)
    ada, bob = w.uid(1), w.uid(2)
    put(w.libraries.for_user(ada))
    mine = w.builder.scans.start(NAME, draft=False, user=ada)
    for call in (lambda rid: w.builder.scans.get(rid, user=bob), lambda rid: w.builder.scans.retry(rid, user=bob), lambda rid: w.builder.scans.get(rid)):
        with pytest.raises(SessionNotFound) as seen:
            call(mine["id"])
        with pytest.raises(SessionNotFound) as never:
            call(MISSING)
        assert str(seen.value) == str(never.value)
    assert w.builder.scans.list(user=bob) == [] and [r["id"] for r in w.builder.scans.list(user=ada)] == [mine["id"]]
    assert w.builder.scans.list() == []  # the owner's list is the owner's: nobody else's runs
    for call in (lambda: w.builder.scans.preview(NAME, user=bob), lambda: w.builder.scans.start(NAME, user=bob)):
        with pytest.raises(NotFound):
            call()  # Bob has no such entry: the same answer as for a name nobody has


def test_two_people_clicking_at_once_each_get_their_own_run(world):
    w = world(Agent(clean), service=True, runner=Parked())
    w.person(1)
    w.person(2)
    put(w.libraries.for_user(w.uid(1)))
    put(w.libraries.for_user(w.uid(2)))
    first, second = w.builder.scans.start(NAME, draft=False, user=w.uid(1)), w.builder.scans.start(NAME, draft=False, user=w.uid(2))
    assert first["id"] != second["id"]
    assert w.builder.scans.start(NAME, draft=False, user=w.uid(1))["id"] == first["id"]


def test_a_scan_counts_toward_the_runs_a_person_may_have_at_once(world):
    w = world(Agent(clean), service=True, runner=Parked(), limits=PersonLimits(max_active=1))
    w.person(1)
    ada = w.uid(1)
    put(w.libraries.for_user(ada))
    put(w.libraries.for_user(ada), "other-skill")
    w.builder.scans.start(NAME, draft=False, user=ada)
    with pytest.raises(LimitReached) as refused:
        w.builder.scans.start("other-skill", draft=False, user=ada)
    assert refused.value.limit == "active"


def test_a_scan_spends_the_model_of_the_person_it_belongs_to(world):
    w = world(Agent(clean), service=True)
    w.person(1)
    ada = w.uid(1)
    put(w.libraries.for_user(ada))
    w.builder.scans.start(NAME, draft=False, user=ada)
    with w.db.session() as s:
        owners = set(s.execute(select(ModelCall.user_id)).scalars())
    assert owners == {ada} and LOCAL_USER_ID not in owners  # every attempt was counted for her, none for the owner


# ---- a stored result stays small --------------------------------------------------------------------------------------------------------------------


def test_a_stored_result_cuts_long_text_and_marks_the_cut_without_changing_the_report():
    run = ScenarioRun(
        {"id": "t", "message": "m" * 5000, "source": "fixed"}, "with the skill",
        turns=[Turn(1, {"tool": "write_file", "target": "a.txt", "content": "y" * 5000, "method": ""}, "z" * 5000)], reply="r" * 5000, finished=True,
    )
    report = CanaryReport("x", "skill", runs=[run])
    view = report_view(report)
    stored = view["runs"][0]
    assert len(stored["turns"][0]["result"]) <= 601 and stored["turns"][0]["result"].endswith("…")
    assert len(stored["turns"][0]["call"]["content"]) <= 501 and stored["turns"][0]["call"]["content"].endswith("…")
    assert len(stored["reply"]) <= 2001 and len(stored["scenario"]["message"]) <= 2001
    assert view["limits"] == LIMITS and view["outcome"] == report.outcome() and view["verdict"] == report.verdict()
    assert len(run.reply) == 5000 and len(run.turns[0].result) == 5000  # the report the engine made is untouched
