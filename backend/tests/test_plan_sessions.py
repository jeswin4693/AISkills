"""Slice AN: a Task Plan that is kept, answered and approved, over HTTP. Offline: a mock model, SQLite in a temp folder, small repositories in a temp folder.

The pure rules (what counts as an answer, what stops an approval, the fingerprint, the Markdown) are in test_plan_approval.py. Here: that a plan is kept as made, that
nothing identifying is kept, that a save or an approval always names the state the person saw, that an approval cannot drift, and that one person's plan is invisible
to another."""

from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, update
from test_builder import make  # noqa: F401  (a pytest fixture)
from test_conductor import reading
from test_github_link import served  # noqa: F401  (a pytest fixture)
from test_hosted import TOKEN, hosted
from test_plan_api import TASK, broken, leaks, root  # noqa: F401  (root is a pytest fixture)

import skillforge.builder.plan_sessions as plan_sessions
from skillforge.api import create_app
from skillforge.builder import SessionNotFound
from skillforge.conductor.approval import Answers, fingerprint
from skillforge.conductor.models import AssumptionMade, GapAsked, RuleSelection, TaskReading
from skillforge.db import Database, PlanSession
from skillforge.providers import MockProvider, ProviderError

GAPS = [
    GapAsked(question="What should the JSON look like?", why="It cannot be tested without it.", blocking=True),
    GapAsked(question="Which file holds the command?", why="The size cannot be measured.", blocking=True),
    GapAsked(question="Should the old output stay the default?", why="Scripts may read it.", blocking=False),
]
ASSUMPTIONS = [
    AssumptionMade(text="The option is off by default.", why="Nothing said otherwise."),
    AssumptionMade(text="The output goes to the terminal.", why="No file was named."),
]


def answers_for(n: int = 1):
    """What a model says about TASK, n times, for a plan with no repository (one call each): three questions, two of them blocking, and two assumptions."""
    return [reading(gaps=GAPS, assumptions=ASSUMPTIONS) for _ in range(n)]


def by_schema(schema, prompt, system):
    """A model for plans made WITH a repository: the reading, and then (the repository has a CLAUDE.md) which of its rules apply: none."""
    return reading(gaps=GAPS, assumptions=ASSUMPTIONS) if schema is TaskReading else RuleSelection(applicable=[])


def keep(env, **body) -> dict:
    r = env.client.post("/api/plans", json={"task": TASK, **body})
    assert r.status_code == 201, r.text
    return r.json()


def save(env, pid, rev, questions=None, assumptions=None):
    return env.client.post(f"/api/plans/{pid}/answers", json={"rev": rev, "questions": questions or {}, "assumptions": assumptions or {}})


def approve(env, pid, rev):
    return env.client.post(f"/api/plans/{pid}/approve", json={"rev": rev})


COMPLETE_Q = {"0": "A list of names, one per line.", "1": "cli.py"}
COMPLETE_A = {"0": "approve", "1": "reject"}


def ready(env) -> dict:
    """A kept plan with everything that blocks an approval answered; returns the view after the save."""
    plan = keep(env)
    r = save(env, plan["id"], plan["rev"], COMPLETE_Q, COMPLETE_A)
    assert r.status_code == 200, r.text
    return r.json()


def stored(env, pid) -> PlanSession:
    with env.db.session() as s:
        return s.get(PlanSession, pid)


# ---- the database ---------------------------------------------------------------------------------------------


def test_a_database_from_before_this_slice_upgrades_and_gets_an_empty_plan_table(tmp_path):
    db = Database(f"sqlite:///{(tmp_path / 'm.db').as_posix()}")
    db.migrate("0010")  # the schema as it was before plans were kept
    with db.engine.connect() as c:
        assert "plan_sessions" not in inspect(c).get_table_names()
    db.migrate()
    with db.engine.connect() as c:
        assert "plan_sessions" in inspect(c).get_table_names()
    with db.session() as s:
        assert s.execute(select(PlanSession)).first() is None
    db.close()


# ---- keeping a plan -------------------------------------------------------------------------------------------


def test_a_plan_is_made_kept_and_returned_with_its_questions_assumptions_and_what_stops_an_approval(make):
    env = make(answers_for())
    doc = keep(env)
    assert re.fullmatch(r"[0-9a-f]{32}", doc["id"]) and doc["status"] == "open" and doc["rev"] == 0 and doc["approval"] is None
    assert doc["plan"]["prompt"] == TASK and doc["plan"]["mode"] == "model" and doc["plan"]["markdown"].startswith("# Task plan")
    assert [(q["index"], q["blocking"], q["answer"]) for q in doc["questions"]] == [(0, True, None), (1, True, None), (2, False, None)]
    assert [(a["index"], a["decision"]) for a in doc["assumptions"]] == [(0, None), (1, None)]
    assert doc["missing"] == [
        "Answer: What should the JSON look like?", "Answer: Which file holds the command?",
        "Decide: The option is off by default.", "Decide: The output goes to the terminal.",
    ]
    assert doc["unanswered"] == ["Should the old output stay the default?"] and doc["can_approve"] is False
    assert [e["what"] for e in doc["events"]] == ["made"]


def test_the_kept_plan_is_the_one_the_plain_plan_route_makes_with_the_same_fields_and_the_same_text(make, root):
    env = make(by_schema)
    kept = keep(env, repo=str(root))
    plain = env.client.post("/api/plan", json={"task": TASK, "repo": str(root)}).json()
    for key in ("prompt", "mode", "repo", "tier", "phases", "rules", "token_plan", "mentions", "reach", "tier_name", "source"):
        assert kept["plan"][key] == plain[key], key
    assert "## 6. Your answers and approval" in kept["plan"]["markdown"] and "## 6." not in plain["markdown"]


def test_a_kept_plan_can_be_read_again_and_is_the_same_as_when_it_was_made(make):
    env = make(answers_for())
    made = keep(env)
    assert env.client.get(f"/api/plans/{made['id']}").json() == made


def test_plans_are_listed_newest_first_with_a_short_summary_and_no_plan(make, monkeypatch):
    ticks = iter(f"2026-11-27T10:00:{n:02d}.000+00:00" for n in range(60))
    env = make(answers_for(2))
    monkeypatch.setattr(plan_sessions, "now_text", lambda: next(ticks))
    first = keep(env)
    second = keep(env, task=TASK + " Second.")
    r = env.client.get("/api/plans")
    rows = r.json()
    assert r.status_code == 200 and [x["id"] for x in rows] == [second["id"], first["id"]]
    row = rows[1]
    assert row["task"] == TASK and row["status"] == "open" and row["mode"] == "model" and "plan" not in row and "markdown" not in row
    assert row["questions"] == {"total": 3, "blocking": 2, "answered": 0, "blocking_answered": 0}
    assert row["assumptions"] == {"total": 2, "decided": 0}


def test_the_summary_counts_follow_the_answers(make):
    env = make(answers_for())
    plan = keep(env)
    save(env, plan["id"], 0, {"0": "names", "2": "yes"}, {"1": "approve"})
    row = env.client.get("/api/plans").json()[0]
    assert row["questions"] == {"total": 3, "blocking": 2, "answered": 2, "blocking_answered": 1} and row["assumptions"] == {"total": 2, "decided": 1}


def test_a_long_request_is_cut_in_the_list_and_whole_when_opened(make):
    long_task = "Add a --json option to the library list command. " + "More detail here. " * 40
    env = make(answers_for())
    made = keep(env, task=long_task)
    row = env.client.get("/api/plans").json()[0]
    assert len(row["task"]) <= 201 and row["task"].endswith("…")
    assert env.client.get(f"/api/plans/{made['id']}").json()["plan"]["prompt"] == long_task.strip()


def test_a_plan_that_cannot_be_made_is_not_kept(make):
    env = make([ProviderError("The model is not reachable.")])
    r = env.client.post("/api/plans", json={"task": TASK})
    assert r.status_code == 502 and env.client.get("/api/plans").json() == []
    assert env.client.post("/api/plans", json={"task": "hi"}).status_code == 400 and env.client.get("/api/plans").json() == []
    env.builder.provider_factory = broken()
    assert env.client.post("/api/plans", json={"task": TASK}).status_code == 502 and env.client.get("/api/plans").json() == []


def test_a_plan_with_no_model_is_kept_too_and_its_questions_come_from_the_graph(make, root):
    env = make([])
    env.builder.provider_factory = broken()
    doc = keep(env, repo=str(root), no_ai=True)
    assert doc["plan"]["mode"] == "facts only" and doc["assumptions"] == [] and env.mock.calls == []
    assert doc["can_approve"] is True and "**Not read.**" in doc["plan"]["markdown"]


def test_the_kept_plan_holds_the_folders_name_and_never_its_path(make, root):
    env = make(by_schema)
    doc = keep(env, repo=str(root))
    assert doc["plan"]["repo"] == root.name and not leaks(root, doc)
    row = stored(env, doc["id"])
    assert row.repo_name == root.name
    kept_text = json.dumps([row.plan, row.answers, row.events, row.task, row.repo_name])
    assert json.dumps(str(root.parent))[1:-1] not in kept_text and str(root) not in kept_text


def test_what_is_kept_holds_no_file_content(make, root):
    env = make(by_schema)
    doc = keep(env, repo=str(root))
    kept = json.dumps(stored(env, doc["id"]).plan)
    assert "open(path).read()" not in kept and "return 1" not in kept


def test_a_kept_plan_changes_nothing_in_the_repository(make, root):
    before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    env = make(by_schema)
    doc = keep(env, repo=str(root))
    save(env, doc["id"], 0, COMPLETE_Q, COMPLETE_A)
    approve(env, doc["id"], 1)
    assert {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_the_most_kept_plans_is_a_limit_checked_before_the_model_is_asked(make, monkeypatch):
    monkeypatch.setattr(plan_sessions, "MAX_KEPT", 2)
    env = make(answers_for(3))
    a, _ = keep(env), keep(env)
    calls = len(env.mock.calls)
    r = env.client.post("/api/plans", json={"task": TASK})
    assert r.status_code == 429 and r.json()["limit"] == "plans" and "Delete" in r.json()["detail"]
    assert len(env.mock.calls) == calls  # no model was asked for a plan that could not be kept
    assert env.client.delete(f"/api/plans/{a['id']}").status_code == 200
    assert env.client.post("/api/plans", json={"task": TASK}).status_code == 201


def test_the_old_plan_route_still_keeps_nothing(make):
    env = make(answers_for())
    assert env.client.post("/api/plan", json={"task": TASK}).status_code == 200
    assert env.client.get("/api/plans").json() == []


# ---- answering ------------------------------------------------------------------------------------------------


def test_saving_answers_keeps_them_moves_the_revision_and_writes_them_into_the_markdown(make):
    env = make(answers_for())
    plan = keep(env)
    r = save(env, plan["id"], 0, {"0": "A list of names, one per line."}, {"0": "approve"})
    doc = r.json()
    assert r.status_code == 200 and doc["rev"] == 1 and doc["status"] == "open"
    assert doc["questions"][0]["answer"] == "A list of names, one per line." and doc["questions"][1]["answer"] is None
    assert doc["assumptions"][0]["decision"] == "approve" and doc["assumptions"][1]["decision"] is None
    assert doc["missing"] == ["Answer: Which file holds the command?", "Decide: The output goes to the terminal."]
    assert "A list of names, one per line." in doc["plan"]["markdown"]
    assert [e["what"] for e in doc["events"]] == ["made", "answers saved"]
    assert env.client.get(f"/api/plans/{plan['id']}").json() == doc


def test_saving_replaces_the_whole_set_so_an_answer_left_out_is_removed(make):
    env = make(answers_for())
    plan = keep(env)
    save(env, plan["id"], 0, {"0": "names"}, {"0": "approve"})
    doc = save(env, plan["id"], 1, {"1": "cli.py"}, {}).json()
    assert [q["answer"] for q in doc["questions"]] == [None, "cli.py", None] and [a["decision"] for a in doc["assumptions"]] == [None, None]


def test_a_blank_answer_and_a_null_decision_remove_what_was_there(make):
    env = make(answers_for())
    plan = keep(env)
    save(env, plan["id"], 0, {"0": "names", "1": "cli.py"}, {"0": "approve"})
    doc = save(env, plan["id"], 1, {"0": "   ", "1": "cli.py"}, {"0": None}).json()
    assert [q["answer"] for q in doc["questions"]] == [None, "cli.py", None] and doc["assumptions"][0]["decision"] is None


def test_saving_the_same_answers_again_changes_nothing_not_the_revision_and_not_the_log(make):
    env = make(answers_for())
    plan = keep(env)
    first = save(env, plan["id"], 0, {"0": "names"}, {}).json()
    again = save(env, plan["id"], 1, {"0": "names"}, {})
    assert again.status_code == 200 and again.json()["rev"] == 1 and again.json()["events"] == first["events"]
    assert stored(env, plan["id"]).updated_at == first["updated_at"]


def test_a_save_that_names_an_old_or_a_future_state_is_refused_and_changes_nothing(make):
    env = make(answers_for())
    plan = keep(env)
    save(env, plan["id"], 0, {"0": "mine"}, {})
    for rev in (0, 2, 99):
        r = save(env, plan["id"], rev, {"0": "someone else's"}, {})
        assert r.status_code == 409 and "another window" in r.json()["detail"], rev
    assert env.client.get(f"/api/plans/{plan['id']}").json()["questions"][0]["answer"] == "mine"


def test_a_save_without_the_revision_is_refused_as_a_bad_request(make):
    env = make(answers_for())
    plan = keep(env)
    r = env.client.post(f"/api/plans/{plan['id']}/answers", json={"questions": {"0": "x1"}, "assumptions": {}})
    assert r.status_code == 422


def test_an_answer_that_cannot_be_kept_is_refused_in_words_and_nothing_changes(make):
    env = make(answers_for())
    plan = keep(env)
    for body, words in (
        ({"9": "x1"}, "no question number 9"), ({"0": "a" * 2001}, "too long"), ({"0": "???"}, "no words"),
    ):
        r = save(env, plan["id"], 0, body, {})
        assert r.status_code == 400 and words in r.json()["detail"], body
    r = save(env, plan["id"], 0, {}, {"5": "approve"})
    assert r.status_code == 400 and "no assumption number 5" in r.json()["detail"]
    r = save(env, plan["id"], 0, {}, {"0": "yes"})
    assert r.status_code == 400 and "approve or reject" in r.json()["detail"]
    doc = env.client.get(f"/api/plans/{plan['id']}").json()
    assert doc["rev"] == 0 and [e["what"] for e in doc["events"]] == ["made"]


def test_an_answer_the_refusal_names_is_never_echoed_back(make):
    env = make(answers_for())
    plan = keep(env)
    secret = "hunter2-" + "x" * 2100
    r = save(env, plan["id"], 0, {"0": secret}, {})
    assert r.status_code == 400 and "hunter2" not in r.text


def test_whole_request_bodies_with_the_wrong_shape_are_refused_without_being_echoed(make):
    env = make(answers_for())
    plan = keep(env)
    for body in ({"rev": 0, "questions": ["a"], "assumptions": {}}, {"rev": "zero", "questions": {}, "assumptions": {}}, {"rev": -1, "questions": {}, "assumptions": {}}):
        r = env.client.post(f"/api/plans/{plan['id']}/answers", json=body)
        assert r.status_code == 422 and "zero" not in r.text, body


def test_an_answer_may_be_long_and_have_several_lines_and_comes_back_as_written(make):
    env = make(answers_for())
    plan = keep(env)
    text_in = "First line.\n\nSecond paragraph with `code`.\nThird."
    doc = save(env, plan["id"], 0, {"0": text_in}, {}).json()
    assert doc["questions"][0]["answer"] == text_in


# ---- approving ------------------------------------------------------------------------------------------------


def test_an_approval_with_blocking_questions_unanswered_is_refused_and_lists_each_one(make):
    env = make(answers_for())
    plan = keep(env)
    save(env, plan["id"], 0, {"0": "names"}, {"0": "approve"})
    r = approve(env, plan["id"], 1)
    assert r.status_code == 409 and r.json()["missing"] == ["Answer: Which file holds the command?", "Decide: The output goes to the terminal."]
    assert r.json()["detail"] == "Not ready to approve: 1 blocking question has no answer, and 1 assumption has no decision."
    doc = env.client.get(f"/api/plans/{plan['id']}").json()
    assert doc["status"] == "open" and doc["approval"] is None and [e["what"] for e in doc["events"]] == ["made", "answers saved"]


def test_a_question_that_is_not_blocking_may_stay_unanswered_and_the_approved_plan_says_so(make):
    env = make(answers_for())
    doc = ready(env)
    assert doc["questions"][2]["answer"] is None and doc["can_approve"] is True
    done = approve(env, doc["id"], doc["rev"]).json()
    assert "Left unanswered" in done["plan"]["markdown"] and "Should the old output stay the default?" in done["plan"]["markdown"].split("Left unanswered")[1]


def test_an_approval_records_when_the_tier_the_fingerprint_and_that_it_is_intact(make):
    env = make(answers_for())
    doc = ready(env)
    r = approve(env, doc["id"], doc["rev"])
    done = r.json()
    assert r.status_code == 200 and done["status"] == "approved" and done["can_approve"] is False and done["missing"] == []
    a = done["approval"]
    assert re.fullmatch(r"[0-9a-f]{64}", a["fingerprint"]) and a["tier"] == done["plan"]["tier"]["tier"] and a["intact"] is True
    assert a["approved_at"] and [e["what"] for e in done["events"]] == ["made", "answers saved", "approved"]
    assert "**APPROVED**" in done["plan"]["markdown"] and a["fingerprint"] in done["plan"]["markdown"]
    assert env.client.get("/api/plans").json()[0]["status"] == "approved"


def test_the_fingerprint_is_of_the_stored_plan_and_the_answers_so_anyone_can_recompute_it(make):
    env = make(answers_for())
    doc = ready(env)
    done = approve(env, doc["id"], doc["rev"]).json()
    row = stored(env, doc["id"])
    assert done["approval"]["fingerprint"] == fingerprint(row.plan, Answers.from_json(row.answers))
    assert "markdown" not in row.plan


def test_an_approval_that_names_an_old_state_is_refused_even_when_the_answers_are_complete(make):
    env = make(answers_for())
    plan = keep(env)
    save(env, plan["id"], 0, COMPLETE_Q, COMPLETE_A)
    r = approve(env, plan["id"], 0)  # the person's screen was from before the save
    assert r.status_code == 409 and "another window" in r.json()["detail"]
    assert env.client.get(f"/api/plans/{plan['id']}").json()["status"] == "open"


def test_an_approved_plan_cannot_be_changed_or_approved_again(make):
    env = make(answers_for())
    doc = ready(env)
    approve(env, doc["id"], doc["rev"])
    r = save(env, doc["id"], doc["rev"], {"0": "changed my mind"}, COMPLETE_A)
    assert r.status_code == 409 and "approved" in r.json()["detail"] and "Reopen" in r.json()["detail"]
    r = approve(env, doc["id"], doc["rev"])
    assert r.status_code == 409 and "already" in r.json()["detail"]
    now = env.client.get(f"/api/plans/{doc['id']}").json()
    assert now["questions"][0]["answer"] == COMPLETE_Q["0"] and now["rev"] == doc["rev"]


def test_two_approvals_racing_make_one_approval(make):
    env = make(answers_for())
    doc = ready(env)
    first = approve(env, doc["id"], doc["rev"])
    second = approve(env, doc["id"], doc["rev"])
    assert (first.status_code, second.status_code) == (200, 409)
    assert [e["what"] for e in env.client.get(f"/api/plans/{doc['id']}").json()["events"]].count("approved") == 1


def test_the_approved_plan_says_the_size_was_not_measured_again(make):
    env = make(answers_for())
    doc = ready(env)
    done = approve(env, doc["id"], doc["rev"]).json()
    assert "not measured again" in done["plan"]["markdown"].lower()


def test_the_approved_text_holds_the_answers_word_for_word(make):
    env = make(answers_for())
    doc = ready(env)
    done = approve(env, doc["id"], doc["rev"]).json()
    md = done["plan"]["markdown"]
    assert '"A list of names, one per line."' in md and '"cli.py"' in md
    assert "The option is off by default." in md.split("Assumptions you approved")[1].split("Assumptions you did NOT approve")[0]
    assert "The output goes to the terminal." in md.split("Assumptions you did NOT approve")[1]


# ---- reopening ------------------------------------------------------------------------------------------------


def test_reopening_withdraws_the_approval_keeps_the_answers_and_records_it(make):
    env = make(answers_for())
    doc = ready(env)
    approve(env, doc["id"], doc["rev"])
    r = env.client.post(f"/api/plans/{doc['id']}/reopen")
    back = r.json()
    assert r.status_code == 200 and back["status"] == "open" and back["approval"] is None and back["rev"] == doc["rev"]
    assert [q["answer"] for q in back["questions"]][:2] == list(COMPLETE_Q.values()) and back["can_approve"] is True
    assert [e["what"] for e in back["events"]] == ["made", "answers saved", "approved", "reopened"]
    assert "NOT APPROVED" in back["plan"]["markdown"] and stored(env, doc["id"]).approved_at is None


def test_only_an_approved_plan_can_be_reopened(make):
    env = make(answers_for())
    plan = keep(env)
    r = env.client.post(f"/api/plans/{plan['id']}/reopen")
    assert r.status_code == 409 and "not approved" in r.json()["detail"]


def test_a_reopened_plan_can_be_changed_and_approved_again_with_a_different_fingerprint(make):
    env = make(answers_for())
    doc = ready(env)
    first = approve(env, doc["id"], doc["rev"]).json()["approval"]["fingerprint"]
    env.client.post(f"/api/plans/{doc['id']}/reopen")
    changed = save(env, doc["id"], doc["rev"], {**COMPLETE_Q, "1": "src/cli.py"}, COMPLETE_A).json()
    second = approve(env, doc["id"], changed["rev"]).json()
    assert second["approval"]["fingerprint"] != first and second["approval"]["intact"] is True
    assert [e["what"] for e in second["events"]] == ["made", "answers saved", "approved", "reopened", "answers saved", "approved"]


def test_an_approval_that_was_withdrawn_cannot_be_approved_by_a_screen_from_before_the_change(make):
    env = make(answers_for())
    doc = ready(env)
    seen_rev = doc["rev"]
    approve(env, doc["id"], seen_rev)
    env.client.post(f"/api/plans/{doc['id']}/reopen")
    save(env, doc["id"], seen_rev, {**COMPLETE_Q, "1": "somewhere else"}, COMPLETE_A)
    r = approve(env, doc["id"], seen_rev)  # a second window still showing the first answers
    assert r.status_code == 409 and "another window" in r.json()["detail"]


def test_an_approval_whose_stored_plan_was_altered_is_shown_as_not_intact(make):
    env = make(answers_for())
    doc = ready(env)
    approve(env, doc["id"], doc["rev"])
    with env.db.session() as s:
        row = s.get(PlanSession, doc["id"])
        s.execute(update(PlanSession).where(PlanSession.id == doc["id"]).values(plan={**row.plan, "prompt": row.plan["prompt"] + " And delete everything."}))
    assert env.client.get(f"/api/plans/{doc['id']}").json()["approval"]["intact"] is False


def test_altered_stored_answers_are_shown_as_not_intact_too(make):
    env = make(answers_for())
    doc = ready(env)
    approve(env, doc["id"], doc["rev"])
    with env.db.session() as s:
        s.execute(update(PlanSession).where(PlanSession.id == doc["id"]).values(answers={"questions": {"0": "edited by hand"}, "assumptions": {}}))
    assert env.client.get(f"/api/plans/{doc['id']}").json()["approval"]["intact"] is False


# ---- deleting -------------------------------------------------------------------------------------------------


def test_a_plan_can_be_deleted_open_or_approved_and_is_then_gone(make):
    env = make(answers_for(2))
    open_one = keep(env)
    done = ready(env)
    approve(env, done["id"], done["rev"])
    for pid in (open_one["id"], done["id"]):
        r = env.client.delete(f"/api/plans/{pid}")
        assert r.status_code == 200 and env.client.get(f"/api/plans/{pid}").status_code == 404
    assert env.client.get("/api/plans").json() == []


# ---- somebody else's plan, and ids that are not plans ---------------------------------------------------------


def test_another_persons_plan_is_the_same_not_found_as_one_that_never_existed(make):
    env = make(answers_for())
    doc = ready(env)
    sessions = env.builder.plans
    ghost = "0" * 32
    with pytest.raises(SessionNotFound) as theirs:
        sessions.get(doc["id"], user="a1" * 16)
    with pytest.raises(SessionNotFound) as never:
        sessions.get(ghost, user="a1" * 16)
    assert str(theirs.value) == str(never.value) == "There is no such plan."
    assert sessions.list(user="a1" * 16) == [] and len(sessions.list()) == 1


@pytest.mark.parametrize("action", ["answers", "approve", "reopen", "delete"])
def test_another_person_cannot_change_a_plan_and_nothing_changes(make, action):
    env = make(answers_for())
    doc = ready(env)
    approve(env, doc["id"], doc["rev"])
    sessions, other = env.builder.plans, "b2" * 16
    with pytest.raises(SessionNotFound):
        if action == "answers":
            sessions.save_answers(doc["id"], doc["rev"], {"0": "hijack"}, {}, user=other)
        elif action == "approve":
            sessions.approve(doc["id"], doc["rev"], user=other)
        elif action == "reopen":
            sessions.reopen(doc["id"], user=other)
        else:
            sessions.delete(doc["id"], user=other)
    after = env.client.get(f"/api/plans/{doc['id']}").json()
    assert after["status"] == "approved" and after["questions"][0]["answer"] == COMPLETE_Q["0"]


def test_a_forgotten_person_means_the_owner_never_everybody(make):
    env = make(answers_for())
    doc = ready(env)
    with env.db.session() as s:
        assert s.get(PlanSession, doc["id"]).user_id == "local"
    assert env.builder.plans.get(doc["id"])["id"] == doc["id"]


@pytest.mark.parametrize("pid", ["nope", "../etc", "0" * 31, "0" * 33, "G" * 32, "%2e%2e"])
def test_an_id_that_is_not_a_plan_id_is_not_found(make, pid):
    env = make(answers_for())
    assert env.client.get(f"/api/plans/{pid}").status_code == 404
    assert env.client.post(f"/api/plans/{pid}/answers", json={"rev": 0, "questions": {}, "assumptions": {}}).status_code == 404
    assert env.client.post(f"/api/plans/{pid}/approve", json={"rev": 0}).status_code == 404
    assert env.client.post(f"/api/plans/{pid}/reopen").status_code == 404
    assert env.client.delete(f"/api/plans/{pid}").status_code == 404


# ---- a stored plan that cannot be read ------------------------------------------------------------------------


def test_a_kept_plan_that_an_older_version_made_is_said_to_be_unreadable_and_can_still_be_deleted(make):
    env = make(answers_for())
    doc = keep(env)
    with env.db.session() as s:
        s.execute(update(PlanSession).where(PlanSession.id == doc["id"]).values(plan={"prompt": "an old shape"}))
    r = env.client.get(f"/api/plans/{doc['id']}")
    assert r.status_code == 400 and "cannot be shown" in r.json()["detail"] and "Delete" in r.json()["detail"]
    row = env.client.get("/api/plans").json()[0]
    assert row["id"] == doc["id"] and row["readable"] is False
    assert save(env, doc["id"], 0, {"0": "x1"}, {}).status_code == 400
    assert approve(env, doc["id"], 0).status_code == 400
    assert env.client.delete(f"/api/plans/{doc['id']}").status_code == 200


# ---- hosted ---------------------------------------------------------------------------------------------------


def test_every_plan_route_is_off_in_the_hosted_version(tmp_path, root):
    from skillforge.builder import Builder, JobRunner
    from skillforge.library import Library

    db = Database(f"sqlite:///{(tmp_path / 'h.db').as_posix()}")
    db.migrate()
    lib = Library(tmp_path / "library")
    builder = Builder(db, lib, tmp_path / "builds", provider_factory=lambda: MockProvider(answers_for(3)), runner=JobRunner(inline=True))
    client = TestClient(create_app(lib, builder=builder, hosted=hosted()), base_url="http://localhost")
    assert client.post("/api/auth/login", json={"token": TOKEN}).status_code == 200
    pid = "0" * 32
    calls = [
        client.post("/api/plans", json={"task": TASK, "repo": str(root)}), client.post("/api/plans", json={"task": TASK}), client.get("/api/plans"),
        client.get(f"/api/plans/{pid}"), client.post(f"/api/plans/{pid}/answers", json={"rev": 0, "questions": {}, "assumptions": {}}),
        client.post(f"/api/plans/{pid}/approve", json={"rev": 0}), client.post(f"/api/plans/{pid}/reopen"), client.delete(f"/api/plans/{pid}"),
    ]
    assert [r.status_code for r in calls] == [403] * 8 and all("hosted" in r.json()["detail"] for r in calls)
    with db.session() as s:
        assert s.execute(select(PlanSession)).first() is None
    builder.runner.shutdown()
    db.close()


# ---- the model sees nothing new -------------------------------------------------------------------------------


def test_answering_and_approving_never_ask_a_model(make):
    env = make(answers_for())
    doc = ready(env)
    calls = len(env.mock.calls)
    approve(env, doc["id"], doc["rev"])
    env.client.post(f"/api/plans/{doc['id']}/reopen")
    save(env, doc["id"], doc["rev"], COMPLETE_Q, COMPLETE_A)
    env.client.get(f"/api/plans/{doc['id']}")
    env.client.get("/api/plans")
    assert len(env.mock.calls) == calls
    env.builder.provider_factory = broken()  # not even a key is needed for what comes after the plan is made
    assert env.client.get(f"/api/plans/{doc['id']}").status_code == 200 and approve(env, doc["id"], doc["rev"]).status_code == 200
