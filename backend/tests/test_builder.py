"""The database and the builder conversation over HTTP. Offline: a mock model, a fake sandbox runner, SQLite in a temp folder."""

from __future__ import annotations

import time

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text
from test_scripts import FakeRunner, bundle, design_using_script
from test_skill_build import ANSWERS, FIRST, draft, round_one, round_two

from skillforge.api import create_app
from skillforge.build.models import Extraction, SkillTest
from skillforge.builder import Builder, JobRunner
from skillforge.db import Base, BuildSession, Database, Job, default_url
from skillforge.graph.store import data_dir
from skillforge.library import Library
from skillforge.providers import MockProvider, ProviderError

FULL = FIRST + " " + " ".join(ANSWERS.values())  # every checklist item is in the person's own words, so one round is enough


class Env:
    def __init__(self, tmp_path, responses, *, inline: bool = True, **builder_kw):
        self.db = Database(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
        self.db.migrate()
        self.library = Library(tmp_path / "library")
        self.mock = MockProvider(responses)
        self.builder = Builder(
            self.db, self.library, tmp_path / "builds", provider_factory=lambda: self.mock,
            runner=JobRunner(inline=inline), sandbox_note=lambda: "unavailable. (test)", **builder_kw,
        )
        self.client = TestClient(create_app(self.library, builder=self.builder), base_url="http://localhost")

    def start(self, description: str = FIRST, **body) -> dict:
        r = self.client.post("/api/builds", json={"description": description, **body})
        assert r.status_code == 201, r.text
        return r.json()

    def get(self, sid: str) -> dict:
        return self.client.get(f"/api/builds/{sid}").json()

    def post(self, sid: str, action: str, **body):
        return self.client.post(f"/api/builds/{sid}/{action}", json=body)


@pytest.fixture
def make(tmp_path):
    made: list[Env] = []

    def factory(responses, **kw) -> Env:
        env = Env(tmp_path / f"e{len(made)}", responses, **kw)
        made.append(env)
        return env

    yield factory
    for env in made:
        env.builder.runner.shutdown()
        env.db.close()


def finished(env: Env, description: str = FULL, **body) -> str:
    """Start, approve and finish a build in one go (the model says everything is answered)."""
    sid = env.start(description, **body)["id"]
    assert env.get(sid)["status"] == "awaiting_approval"
    assert env.post(sid, "approve").status_code == 200
    return sid


# ---- the database ------------------------------------------------------------------------------------


def test_the_migration_creates_exactly_what_the_models_describe_and_is_safe_to_repeat(tmp_path):
    db = Database(f"sqlite:///{(tmp_path / 'm.db').as_posix()}")
    db.migrate()
    db.migrate()
    with db.engine.connect() as c:
        assert set(inspect(c).get_table_names()) == {"alembic_version", "build_sessions", "jobs", "model_calls"}
        assert compare_metadata(MigrationContext.configure(c), Base.metadata) == []
    db.close()


def test_a_database_from_before_kinds_upgrades_and_old_sessions_become_skills(tmp_path):
    db = Database(f"sqlite:///{(tmp_path / 'k.db').as_posix()}")
    db.migrate("0002")  # the schema as it was before sessions had a kind
    with db.session() as s:
        s.execute(text(
            "INSERT INTO build_sessions (id, created_at, updated_at, status, description, words, round, with_scripts, "
            "questions, error, retryable, model_calls, notes, saved_name, saved_version) "
            f"VALUES ('{'b' * 32}', 't', 't', 'done', 'd', 'd', 1, 0, '[]', '', 0, 0, '[]', '', '')"
        ))
    db.migrate()
    with db.session() as s:
        row = s.get(BuildSession, "b" * 32)
        assert row.kind == "skill" and row.parent_id is None
    db.close()


def test_deleting_a_session_removes_its_jobs_because_foreign_keys_are_on(tmp_path):
    db = Database(f"sqlite:///{(tmp_path / 'f.db').as_posix()}")
    db.migrate()
    with db.session() as s:
        assert s.execute(text("PRAGMA foreign_keys")).scalar() == 1
        s.add(BuildSession(id="a" * 32, created_at="t", updated_at="t", status="done", description="d", words="d", round=1,
                           with_scripts=False, questions=[], error="", retryable=False, model_calls=0, notes=[],
                           saved_name="", saved_version=""))
        s.add(Job(session_id="a" * 32, kind="build", status="succeeded", created_at="t", events=[], error=""))
    with db.session() as s:
        s.delete(s.get(BuildSession, "a" * 32))
    with db.session() as s:
        assert s.execute(select(Job)).scalars().all() == []
    db.close()


def test_the_database_is_a_file_in_the_data_folder_unless_a_url_says_otherwise(monkeypatch):
    monkeypatch.delenv("SKILLFORGE_DATABASE_URL", raising=False)
    assert default_url().database == str(data_dir() / "skillforge.db")
    monkeypatch.setenv("SKILLFORGE_DATABASE_URL", "sqlite:///elsewhere.db")
    assert default_url() == "sqlite:///elsewhere.db"


def test_work_that_a_stop_left_half_done_is_marked_so_it_can_be_retried(tmp_path):
    db = Database(f"sqlite:///{(tmp_path / 'r.db').as_posix()}")
    db.migrate()
    with db.session() as s:
        for sid, status in (("a" * 32, "working"), ("b" * 32, "done")):
            s.add(BuildSession(id=sid, created_at="t", updated_at="t", status=status, description="d", words="d", round=1,
                               with_scripts=False, questions=[], error="", retryable=False, model_calls=0, notes=[],
                               saved_name="", saved_version=""))
        s.add(Job(session_id="a" * 32, kind="build", status="running", created_at="t", events=[], error=""))
        s.add(Job(session_id="b" * 32, kind="build", status="succeeded", created_at="t", events=[], error=""))
    assert db.recover_interrupted() == 1
    with db.session() as s:
        working, done = s.get(BuildSession, "a" * 32), s.get(BuildSession, "b" * 32)
        assert working.status == "failed" and working.retryable and "stopped" in working.error
        assert done.status == "done"
        assert {j.session_id: j.status for j in s.execute(select(Job)).scalars()} == {"a" * 32: "failed", "b" * 32: "succeeded"}
    db.close()


def test_a_server_used_only_for_the_library_never_opens_the_database(tmp_path):
    client = TestClient(create_app(Library(tmp_path / "library")), base_url="http://localhost")
    assert client.get("/api/health").status_code == 200 and client.get("/api/library").status_code == 200
    assert not (data_dir() / "skillforge.db").exists()


def test_the_default_builder_opens_and_migrates_the_database_in_the_data_folder(tmp_path):
    b = Builder.default(Library(tmp_path / "library"))
    try:
        assert (data_dir() / "skillforge.db").exists() and b.builds_root == data_dir() / "builds"
        assert b.list() == []
    finally:
        b.close()


# ---- the conversation --------------------------------------------------------------------------------


def test_a_whole_conversation_from_a_sentence_to_a_skill_in_the_library(make):
    env = make([round_one(), round_two(), draft()])
    first = env.start()
    sid = first["id"]
    assert first["status"] == "awaiting_answers" and first["round"] == 1
    assert [q["slot"] for q in first["questions"]] == ["constraints", "acceptance_criteria", "failure_behavior"]
    assert first["spec"] is None and first["result"] is None

    answered = env.post(sid, "answers", answers=ANSWERS).json()
    assert answered["status"] == "awaiting_approval" and answered["round"] == 2 and answered["questions"] == []
    spec = answered["spec"]
    assert spec["constraints"] == ["never edit files"] and spec["quotes"]["constraints"] == "It must never edit files"
    assert "must never edit files" in env.mock.calls[1]["prompt"]  # the answers became part of the person's words

    done = env.post(sid, "approve").json()
    assert done["status"] == "done" and done["model_calls"] == 3 and done["error"] == ""
    result = done["result"]
    assert result["status"] == "ok" and result["name"] == "duplicate-function-finder" and result["counts"]["failed"] == 0
    assert "SKILL.md" in result["files"] and "report.md" in result["files"]
    assert result["report_md"].startswith("# Build report: Duplicate Function Finder") and "every check that ran passed" in result["report_md"]
    assert result["checks"] and not env.library.names()  # built, but not in the library until the person saves it

    saved = env.post(sid, "save").json()
    assert saved["created"] and saved["version"]["tag"] == "v1" and saved["session"]["saved"] == {"name": "duplicate-function-finder", "version": "v1"}
    assert env.library.pick("duplicate-function-finder").tag == "v1"
    assert env.client.get("/api/library").json()[0]["name"] == "duplicate-function-finder"
    assert env.post(sid, "save").json()["created"] is False  # saving again changes nothing


def test_the_job_reports_what_it_is_doing(make):
    env = make([round_two(), draft()])
    sid = finished(env)
    events = [e["message"] for e in env.get(sid)["job"]["events"]]
    assert events[0].startswith("Designing the skill") and "Writing the files and running every check" in events
    assert env.get(sid)["job"]["kind"] == "build" and env.get(sid)["job"]["status"] == "succeeded"


def test_a_model_that_claims_answers_the_person_never_gave_is_not_believed(make):
    env = make([round_two()])  # its quotes are not in the person's one sentence
    s = env.start()
    assert s["status"] == "awaiting_answers" and len(s["questions"]) == 3
    assert any("not in your words" in n for n in s["notes"])


def test_only_a_question_that_was_asked_can_be_answered_and_something_must_be_said(make):
    env = make([round_one()])
    sid = env.start()["id"]
    assert env.post(sid, "answers", answers={"goal": "something else"}).status_code == 400
    assert env.post(sid, "answers", answers={"constraints": "   "}).status_code == 400
    assert env.post(sid, "answers", answers={"constraints": "x" * 5001}).status_code == 422
    assert env.get(sid)["status"] == "awaiting_answers" and env.get(sid)["round"] == 1


def test_each_action_is_only_allowed_at_its_own_step(make):
    env = make([round_one()])
    sid = env.start()["id"]
    assert env.post(sid, "approve").status_code == 409  # nothing to approve yet
    assert env.post(sid, "retry").status_code == 409
    assert env.post(sid, "save").status_code == 409
    assert env.client.delete(f"/api/builds/{sid}").status_code == 200  # waiting for answers is not "running"


def test_two_approvals_cannot_both_build(make):
    env = make([round_two(), draft()])
    sid = finished(env)
    again = env.post(sid, "approve")
    assert again.status_code == 409 and len(env.mock.calls) == 2


def test_a_sentence_that_is_too_short_is_refused_before_anything_is_stored(make):
    env = make([])
    assert env.client.post("/api/builds", json={"description": "hi"}).status_code == 400
    assert env.client.post("/api/builds", json={"description": "x" * 10_001}).status_code == 422
    assert env.client.get("/api/builds").json() == [] and env.mock.calls == []


def test_a_request_that_is_not_a_skill_is_explained_and_cannot_be_retried(make):
    agent = round_two().model_copy(update={"kind": "agent"})
    env = make([agent])
    s = env.start(FULL)
    assert s["status"] == "failed" and "not a skill" in s["error"] and s["retryable"] is False
    assert env.post(s["id"], "retry").status_code == 409


def test_after_three_rounds_without_answers_it_stops_and_names_what_is_missing(make):
    env = make([round_one(), round_one(), round_one()])
    sid = env.start()["id"]
    for _ in range(2):
        env.post(sid, "answers", answers={"constraints": "never edit files"})
    s = env.get(sid)
    assert s["status"] == "failed" and "still incomplete after 3 rounds" in s["error"] and "acceptance_criteria" in s["error"]
    assert s["round"] == 3 and s["retryable"] is False


# ---- when the model is not there ---------------------------------------------------------------------


def test_a_missing_model_setup_is_a_clear_message_and_retrying_after_fixing_it_continues(make):
    env = make([round_two(), draft()])
    env.builder.provider_factory = lambda: (_ for _ in ()).throw(ProviderError("GOOGLE_API_KEY is empty. Add it to .env (never commit that file)."))
    s = env.start(FULL)
    assert s["status"] == "failed" and s["retryable"] and "GOOGLE_API_KEY is empty" in s["error"]
    assert s["job"]["status"] == "failed"
    env.builder.provider_factory = lambda: env.mock  # the person fixed .env
    assert env.post(s["id"], "retry").json()["status"] == "awaiting_approval"


def test_a_model_that_fails_while_writing_the_skill_can_be_retried_without_asking_again(make):
    env = make([round_two(), ProviderError("model unreachable"), draft()])
    sid = finished(env)
    s = env.get(sid)
    assert s["status"] == "failed" and s["retryable"] and "model unreachable" in s["error"] and s["spec"] is not None
    retried = env.post(sid, "retry").json()
    assert retried["status"] == "done" and retried["result"]["status"] == "ok"
    assert len(env.mock.calls) == 3  # the requirement was not extracted again


def test_a_surprise_is_recorded_for_the_person_and_logged_not_lost(make, caplog):
    env = make([round_two(), RuntimeError("boom")])
    sid = finished(env)
    s = env.get(sid)
    assert s["status"] == "failed" and "Unexpected error (RuntimeError): boom" in s["error"] and s["retryable"] is False
    assert any("builder job" in r.message for r in caplog.records)


def test_which_model_is_set_up_is_shown_but_never_the_key(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("LLM_MODEL", "some-model")
    monkeypatch.setenv("GOOGLE_API_KEY", "SECRET-VALUE-123")
    client = TestClient(create_app(Library(tmp_path / "library")), base_url="http://localhost")
    body = client.get("/api/provider")
    assert body.json()["configured"] is True and body.json()["provider"] == "gemini" and body.json()["model"] == "some-model"
    assert "SECRET-VALUE-123" not in body.text
    monkeypatch.delenv("GOOGLE_API_KEY")
    missing = client.get("/api/provider").json()
    assert missing["configured"] is False and "GOOGLE_API_KEY" in missing["detail"]


# ---- the result: drafts, files, saving ---------------------------------------------------------------


def uncovered() -> object:
    return draft(tests=[SkillTest(name="t", kind="positive", input_description="x", expected_result="y", covers=[]),
                        SkillTest(name="n", kind="negative", input_description="x", expected_result="y", covers=[])])


def test_a_draft_is_flagged_and_is_only_saved_when_the_person_accepts_it(make):
    env = make([round_two(), uncovered(), uncovered()])
    sid = finished(env)
    s = env.get(sid)
    assert s["status"] == "done" and s["result"]["status"] == "draft" and s["result"]["counts"]["failed"] >= 1
    assert env.client.get("/api/builds").json()[0]["draft"] is True
    refused = env.post(sid, "save")
    assert refused.status_code == 409 and "DRAFT" in refused.json()["detail"] and not env.library.names()
    kept = env.post(sid, "save", accept_draft=True, note="keep for now")
    assert kept.status_code == 200 and kept.json()["version"]["note"] == "keep for now"


def test_scripts_are_built_and_tested_through_the_injected_sandbox_runner(make):
    runner = FakeRunner()
    env = make([round_two(), bundle(), design_using_script()], script_runner=runner)
    sid = finished(env, with_scripts=True)
    result = env.get(sid)["result"]
    assert result["status"] == "ok" and result["scripts"] == 1 and len(runner.calls) == 2
    assert "scripts/count_lines.py" in result["files"]
    events = [e["message"] for e in env.get(sid)["job"]["events"]]
    assert events[0].startswith("Writing helper scripts")


def test_generated_files_can_be_read_before_saving_by_name_only(make):
    env = make([round_two(), draft()])
    sid = finished(env)
    skill = env.client.get(f"/api/builds/{sid}/files/SKILL.md").json()
    assert skill["binary"] is False and skill["text"].startswith("---\nname: duplicate-function-finder")
    for path in ("nope.md", "../../t.db", "..%2F..%2Ft.db", "/etc/passwd"):
        assert env.client.get(f"/api/builds/{sid}/files/{path}").status_code in (404, 400)


def test_discarding_removes_the_session_its_jobs_and_its_files(make, tmp_path):
    env = make([round_two(), draft()])
    sid = finished(env)
    folder = env.builder.builds_root / sid
    assert folder.is_dir()
    assert env.client.delete(f"/api/builds/{sid}").json() == {"discarded": True}
    assert not folder.exists() and env.client.get(f"/api/builds/{sid}").status_code == 404
    with env.db.session() as s:
        assert s.execute(select(Job)).scalars().all() == []


def test_a_session_that_is_running_cannot_be_discarded(make):
    env = make([round_one()])
    sid = env.start()["id"]
    with env.db.session() as s:
        s.get(BuildSession, sid).status = "working"
    assert env.client.delete(f"/api/builds/{sid}").status_code == 409


def test_ids_that_are_not_ids_are_simply_not_found(make):
    env = make([])
    for sid in ("nothing", "A" * 32, "0" * 32, "..", "%2e%2e"):
        assert env.client.get(f"/api/builds/{sid}").status_code == 404, sid
        assert env.client.delete(f"/api/builds/{sid}").status_code == 404, sid


def test_the_list_shows_newest_first_with_what_became_of_each(make):
    env = make([round_two(), draft(), round_one()])
    first = finished(env)
    env.post(first, "save")
    second = env.start("Another skill idea, said in a single sentence.")["id"]
    rows = env.client.get("/api/builds").json()
    assert [r["id"] for r in rows] == [second, first]
    assert rows[1]["saved"] == {"name": "duplicate-function-finder", "version": "v1"} and rows[1]["skill"] == "duplicate-function-finder"
    assert rows[0]["status"] == "awaiting_answers" and rows[0]["saved"] is None


# ---- it is still the local API ------------------------------------------------------------------------


def test_a_web_page_on_another_site_cannot_start_or_discard_a_build(make):
    env = make([round_one()])
    sid = env.start()["id"]
    evil = {"Origin": "https://evil.example"}
    assert env.client.post("/api/builds", json={"description": FIRST}, headers=evil).status_code == 403
    assert env.client.delete(f"/api/builds/{sid}", headers=evil).status_code == 403
    assert env.client.post(f"/api/builds/{sid}/answers", json={"answers": ANSWERS}, headers=evil).status_code == 403
    assert len(env.client.get("/api/builds").json()) == 1
    ok = env.client.delete(f"/api/builds/{sid}", headers={"Origin": "http://localhost:3000"})
    assert ok.status_code == 200


# ---- on real background threads -----------------------------------------------------------------------


def wait_for(env: Env, sid: str, *statuses: str, timeout: float = 20.0) -> dict:
    end, s = time.time() + timeout, {}
    while time.time() < end:
        s = env.get(sid)
        if s["status"] in statuses:
            return s
        time.sleep(0.05)
    raise AssertionError(f"still '{s.get('status')}' after {timeout}s")


def test_the_same_conversation_works_on_real_threads_with_the_browser_polling(make):
    gate_open = False

    def slow_responses(schema, prompt, system):
        while not gate_open:  # hold the model so the test can see the session "working"
            time.sleep(0.01)
        return {Extraction: round_two(), type(draft()): draft()}[schema]

    env = make(slow_responses, inline=False)
    r = env.client.post("/api/builds", json={"description": FULL})
    sid = r.json()["id"]
    assert r.status_code == 201 and r.json()["status"] == "working"  # the request returned while the job was still going
    assert env.get(sid)["job"]["status"] in ("queued", "running")
    gate_open = True
    assert wait_for(env, sid, "awaiting_approval")["spec"]["goal"]
    assert env.post(sid, "approve").json()["status"] == "working"
    done = wait_for(env, sid, "done")
    assert done["result"]["status"] == "ok" and done["job"]["status"] == "succeeded"
    assert any("Designing" in e["message"] for e in done["job"]["events"])
