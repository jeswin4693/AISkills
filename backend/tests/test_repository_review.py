"""What the independent review of slice W found, each as a test that failed before the fix. Offline: a mock model, small repositories."""

from __future__ import annotations

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from test_builder import FULL, Env, finished, make  # noqa: F401  (make is a pytest fixture)
from test_hosted import TOKEN, hosted
from test_repository_api import IDEAS, REVIEW, root, seeded  # noqa: F401  (root is a pytest fixture)
from test_skill_build import draft, round_two
from test_suggest import REPO

from skillforge.api import create_app
from skillforge.builder import BadRequest, Builder, JobRunner
from skillforge.db import BuildSession, Database, SuggestRun, now_text
from skillforge.evidence import EVIDENCE_FILE, read_evidence
from skillforge.library import Library
from skillforge.providers import MockProvider
from skillforge.suggest.prompt import IDEAS_SYSTEM

BS = chr(92)  # a backslash, written this way so no tool can change it


def post(env: Env, url: str, **body):
    return env.client.post(url, json=body)


# ---- a path is never sent back, not even in an error ---------------------------------------------------


def test_errors_about_a_folder_never_repeat_the_path(make, tmp_path):
    env = make([])
    missing = str(tmp_path / "SECRETDIR" / "nowhere")
    for path, body in (
        ("/api/repos/analyze", {"path": missing}),
        ("/api/suggestions", {"path": missing}),
        ("/api/builds", {"description": FULL, "repo": missing, "evidence_nodes": ["a.py"]}),
        ("/api/library/some-skill/recheck", {"repo": missing}),
    ):
        r = post(env, path, **body)
        assert r.status_code == 400 and "SECRETDIR" not in r.text, (path, r.text)
        assert "directory" in r.json()["detail"].lower()


def test_a_run_that_fails_because_the_folder_vanished_never_repeats_the_path(make, tmp_path):
    env = make([])
    with env.db.session() as s:
        s.add(SuggestRun(id="a" * 32, created_at=now_text(), updated_at=now_text(), status="working", repo=str(tmp_path / "SECRETDIR" / "vanished"),
                         repo_name="vanished", focus=None, with_ideas=True, result=None, error="", retryable=False))
    env.builder.suggestions._execute("a" * 32)
    run = env.client.get("/api/suggestions/" + "a" * 32).json()
    assert run["status"] == "failed" and "SECRETDIR" not in json.dumps(run) and "SECRETDIR" not in json.dumps(env.client.get("/api/suggestions").json())


def test_network_paths_are_not_read(make):
    env = make([])
    for p in (BS + BS + "server" + BS + "share" + BS + "repo", "//server/share/repo", BS + BS + "?" + BS + "C:" + BS + "x"):
        r = post(env, "/api/repos/analyze", path=p)
        assert r.status_code == 400 and "network" in r.json()["detail"].lower(), p


def test_a_folder_with_dot_dot_is_named_by_the_folder_it_is(make, root):
    (root / "sub").mkdir()
    doc = post(make([]), "/api/repos/analyze", path=str(root / "sub") + BS + "..").json()
    assert doc["name"] == root.name


# ---- a second click does not ask the model twice ------------------------------------------------------


def test_a_second_click_while_a_run_is_working_returns_that_run(make, root):
    gate = threading.Event()

    def slow(schema, prompt, system):
        gate.wait(15)
        return IDEAS if system == IDEAS_SYSTEM else REVIEW

    env = make(slow, inline=False)
    first = post(env, "/api/suggestions", path=str(root)).json()
    second = post(env, "/api/suggestions", path=str(root)).json()
    assert first["id"] == second["id"] and len(env.client.get("/api/suggestions").json()) == 1
    gate.set()
    end = time.time() + 15
    while time.time() < end and env.client.get("/api/suggestions/" + first["id"]).json()["status"] == "working":
        time.sleep(0.1)
    assert env.client.get("/api/suggestions/" + first["id"]).json()["status"] == "done" and len(env.mock.calls) == 2  # two calls, not four
    assert post(env, "/api/suggestions", path=str(root)).json()["id"] != first["id"]  # a finished run does not block a new one


def test_a_different_folder_or_focus_is_a_different_run(make, root):
    gate = threading.Event()
    env = make(lambda schema, prompt, system: (gate.wait(15), IDEAS if system == IDEAS_SYSTEM else REVIEW)[1], inline=False)
    a = post(env, "/api/suggestions", path=str(root)).json()["id"]
    b = post(env, "/api/suggestions", path=str(root), focus="sub").json()["id"]
    assert a != b
    gate.set()


# ---- a build from a stored run takes the folder and the places from the run ----------------------------


def a_done_run(env: Env, root) -> str:
    rid = post(env, "/api/suggestions", path=str(root)).json()["id"]
    assert env.client.get("/api/suggestions/" + rid).json()["status"] == "done"
    return rid


def test_a_build_from_a_run_uses_the_runs_folder_and_the_ideas_own_places(make, root):
    env = make([REVIEW, IDEAS, round_two(), draft()])
    rid = a_done_run(env, root)
    sid = finished(env, from_run=rid, idea=1)  # idea 1 is the skill idea; the page sends no folder and no places
    session = env.get(sid)
    assert session["seed"] == {"repo": root.name, "focus": None, "places": 1} and session["status"] == "done"
    assert session["result"]["evidence"] == {"repo": root.name, "places": 1, "skipped": []}
    ev = read_evidence({EVIDENCE_FILE: env.client.get(f"/api/builds/{sid}/files/{EVIDENCE_FILE}").json()["text"].encode()})
    assert [r.id for r in ev.refs] == ["core.py::shared"]


@pytest.mark.parametrize("body, status, why", [
    ({"from_run": "{rid}", "idea": 9}, 400, "idea"),
    ({"from_run": "{rid}", "idea": 0}, 400, "skill"),  # a refactoring suggestion cannot start a build
    ({"from_run": "{rid}"}, 400, "idea"),
    ({"idea": 1}, 400, "from_run"),
    ({"from_run": "{rid}", "idea": 1, "repo": "/x", "evidence_nodes": ["a.py"]}, 400, "either"),
    ({"from_run": "{rid}", "idea": 1, "evidence_nodes": ["a.py"]}, 400, "either"),
    ({"from_run": "0" * 32, "idea": 1}, 404, "run"),
    ({"from_run": "not-an-id", "idea": 1}, 404, "run"),
])
def test_a_build_from_a_run_refuses_what_does_not_fit(make, root, body, status, why):
    env = make([REVIEW, IDEAS])
    rid = a_done_run(env, root)
    body = {k: (v.replace("{rid}", rid) if isinstance(v, str) else v) for k, v in body.items()}
    r = post(env, "/api/builds", description=FULL, **body)
    assert r.status_code == status and why in r.json()["detail"].lower(), r.text


def test_a_run_that_is_not_finished_cannot_start_a_build(make):
    env = make([])
    with env.db.session() as s:
        s.add(SuggestRun(id="b" * 32, created_at=now_text(), updated_at=now_text(), status="working", repo="/x", repo_name="x", focus=None,
                         with_ideas=True, result=None, error="", retryable=False))
    r = post(env, "/api/builds", description=FULL, from_run="b" * 32, idea=0)
    assert r.status_code == 400 and "not finished" in r.json()["detail"].lower()


def hosted_client(tmp_path):
    db = Database(f"sqlite:///{(tmp_path / 'h.db').as_posix()}")
    db.migrate()
    lib = Library(tmp_path / "library")
    builder = Builder(db, lib, tmp_path / "builds", provider_factory=lambda: MockProvider([]), runner=JobRunner(inline=True))
    client = TestClient(create_app(lib, builder=builder, hosted=hosted()), base_url="http://localhost")
    assert client.post("/api/auth/login", json={"token": TOKEN}).status_code == 200
    return client, builder, db


def test_the_hosted_version_refuses_every_way_in(tmp_path, root):
    client, builder, db = hosted_client(tmp_path)
    for path, body in (
        ("/api/builds", {"description": FULL, "focus": "src"}),  # a focus alone is already a folder
        ("/api/builds", {"description": FULL, "from_run": "0" * 32, "idea": 0}),
        ("/api/builds", {"description": FULL, "evidence_nodes": ["a.py"]}),
        ("/api/suggestions/" + "0" * 32 + "/retry", {}),
        ("/api/library/some-skill/recheck", {"repo": str(root)}),
    ):
        r = client.post(path, json=body)
        assert r.status_code == 403 and "hosted" in r.json()["detail"], (path, r.text)
    builder.runner.shutdown()
    db.close()


# ---- the graph cache can be written by two requests at once -------------------------------------------


def test_two_threads_saving_the_graph_cache_never_fail(tmp_path):
    from skillforge.graph.store import save_records

    target = tmp_path / "cache" / "graph.json"
    errors: list[Exception] = []

    def work():
        for _ in range(120):
            try:
                save_records(target, {})
            except Exception as exc:  # noqa: BLE001 - what the test is about
                errors.append(exc)

    threads = [threading.Thread(target=work) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == [] and target.exists()
    assert not list(target.parent.glob("*.tmp")), "no half-written file is left behind"


# ---- smaller things -------------------------------------------------------------------------------------


def test_cited_places_that_are_not_in_the_graph_are_shown_escaped(make, root):
    env = make([round_two(), draft()])
    odd = ["core.py::shared", "bad" + chr(0x202E) + ".py", "bell" + chr(7) + ".py"]
    session = env.get(seeded(env, root, nodes=odd))
    skipped = "".join(session["result"]["evidence"]["skipped"])
    assert chr(0x202E) not in skipped and chr(7) not in skipped and "\\u202e" in skipped and "\\x07" in skipped


def test_the_service_checks_the_bounds_itself(make, root):
    env = make([])
    for nodes in ([f"n{i}.py" for i in range(61)], ["x" * 401]):
        with pytest.raises(BadRequest):
            env.builder.start(FULL, False, "skill", seed={"repo": str(root), "focus": None, "nodes": nodes})


def test_a_value_error_in_the_model_step_is_not_called_a_repository_problem(make, root, monkeypatch):
    def odd(*args, **kwargs):
        raise ValueError("something odd in the model's answer")

    monkeypatch.setattr("skillforge.builder.suggestions.run_suggest", odd)
    env = make([])
    run = env.client.get("/api/suggestions/" + post(env, "/api/suggestions", path=str(root)).json()["id"]).json()
    assert run["status"] == "failed" and "Unexpected error (ValueError)" in run["error"] and "repository" not in run["error"].lower() and run["retryable"] is False


def test_a_database_from_before_the_seed_upgrades_and_old_sessions_have_none(tmp_path):
    db = Database(f"sqlite:///{(tmp_path / 's.db').as_posix()}")
    db.migrate("0003")
    with db.session() as s:
        s.execute(text(
            "INSERT INTO build_sessions (id, created_at, updated_at, status, description, words, round, with_scripts, "
            "questions, error, retryable, model_calls, notes, saved_name, saved_version, kind) "
            f"VALUES ('{'c' * 32}', 't', 't', 'done', 'd', 'd', 1, 0, '[]', '', 0, 0, '[]', '', '', 'skill')"
        ))
    db.migrate()
    with db.session() as s:
        row = s.get(BuildSession, "c" * 32)
        assert row.seed is None and row.kind == "skill"
    db.close()
