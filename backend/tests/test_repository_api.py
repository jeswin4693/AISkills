"""Slice W: the repository in the web API. Analyze a folder, run suggestions as a polled job, seed a build with the code an idea
cites so the built skill carries evidence. Offline: a mock model, inline jobs, small repositories in a temp folder."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from test_builder import FULL, Env, finished, make  # noqa: F401  (make is a pytest fixture)
from test_hosted import TOKEN, hosted
from test_skill_build import draft, round_two
from test_suggest import REPO, sug

from skillforge.api import create_app
from skillforge.builder import BadRequest
from skillforge.db import Database
from skillforge.evidence import EVIDENCE_FILE, read_evidence
from skillforge.providers import ProviderError
from skillforge.suggest.models import SuggestionSet

REVIEW = SuggestionSet(suggestions=[sug()])
IDEAS = SuggestionSet(suggestions=[sug(
    title="Explain what a change to shared touches", category="skill", evidence=["core.py::shared"],
    skill_requirement="A skill that, given a function name, lists the files a change to it would touch.",
)])


@pytest.fixture
def root(repo):
    return repo(REPO)


def leaks(root, doc) -> bool:
    """Whether the folder the repository sits in (a person's own path) appears in a response. Compared as JSON text, so a Windows
    path with backslashes is not missed."""
    return json.dumps(str(root.parent))[1:-1] in json.dumps(doc)


# ---- analyze -----------------------------------------------------------------------------------------


def test_analyze_gives_the_facts_the_graph_computed(make, root):
    env = make([])
    r = env.client.post("/api/repos/analyze", json={"path": str(root)})
    doc = r.json()
    assert r.status_code == 200 and doc["name"] == root.name
    assert doc["stats"]["files"] == 3 and doc["stats"]["language_levels"] == {"python": "full"} and "root" not in doc["stats"]
    assert any(s["name"] == "shared" for s in doc["hotspots"]["core_symbols"])
    assert doc["dead_code"]["internal"] >= 1 and isinstance(doc["notes"], list) and not leaks(root, doc)


@pytest.mark.parametrize("path, why", [("relative/path", "absolute"), ("", "absolute")])
def test_analyze_wants_an_absolute_path(make, path, why):
    r = make([]).client.post("/api/repos/analyze", json={"path": path})
    assert r.status_code == 400 and why in r.json()["detail"]


def test_analyze_of_a_missing_folder_or_a_file_is_a_plain_400(make, root, tmp_path):
    env = make([])
    assert "Not a directory" in env.client.post("/api/repos/analyze", json={"path": str(tmp_path / "nowhere")}).json()["detail"]
    assert env.client.post("/api/repos/analyze", json={"path": str(root / "core.py")}).status_code == 400


def test_everything_that_reads_a_folder_is_off_in_the_hosted_version(tmp_path, root):
    env_db = Database(f"sqlite:///{(tmp_path / 'h.db').as_posix()}")
    env_db.migrate()
    from skillforge.builder import Builder, JobRunner
    from skillforge.library import Library
    from skillforge.providers import MockProvider

    lib = Library(tmp_path / "library")
    builder = Builder(env_db, lib, tmp_path / "builds", provider_factory=lambda: MockProvider([]), runner=JobRunner(inline=True))
    client = TestClient(create_app(lib, builder=builder, hosted=hosted()), base_url="http://localhost")
    assert client.post("/api/auth/login", json={"token": TOKEN}).status_code == 200
    for path, body in (
        ("/api/repos/analyze", {"path": str(root)}),
        ("/api/suggestions", {"path": str(root)}),
        ("/api/builds", {"description": FULL, "repo": str(root), "evidence_nodes": ["core.py"]}),
    ):
        r = client.post(path, json=body)
        assert r.status_code == 403 and "hosted" in r.json()["detail"], path
    assert client.post("/api/builds", json={"description": FULL}).status_code == 201  # a plain build is untouched
    builder.runner.shutdown()
    env_db.close()


# ---- suggestions: a persisted run that is polled -----------------------------------------------------


def test_a_suggestion_run_keeps_what_grounding_kept(make, root):
    env = make([REVIEW, IDEAS])
    r = env.client.post("/api/suggestions", json={"path": str(root)})
    assert r.status_code == 201
    run = env.client.get(f"/api/suggestions/{r.json()['id']}").json()
    assert run["status"] == "done" and run["repo"] == root.name and run["error"] == "" and not leaks(root, run)
    titles = {s["title"]: s for s in run["result"]["suggestions"]}
    assert set(titles) == {"Merge the duplicate normalisers", "Explain what a change to shared touches"}
    idea = titles["Explain what a change to shared touches"]
    assert idea["evidence_nodes"] == ["core.py::shared"] and idea["skill_requirement"].startswith("A skill that")
    assert [x["id"] for x in env.client.get("/api/suggestions").json()] == [run["id"]]


def test_the_model_is_asked_only_after_the_folder_is_checked(make, tmp_path):
    env = make([REVIEW, IDEAS])
    assert env.client.post("/api/suggestions", json={"path": str(tmp_path / "nowhere")}).status_code == 400
    assert env.mock.calls == []


def test_a_model_that_cannot_answer_is_a_failed_run_with_a_reason(make, root):
    env = make([ProviderError("No model is set up. Add LLM_PROVIDER to .env.")])
    run = env.client.get(f"/api/suggestions/{env.client.post('/api/suggestions', json={'path': str(root)}).json()['id']}").json()
    assert run["status"] == "failed" and "No model is set up" in run["error"] and run["retryable"] is True and run["result"] is None


def test_a_failed_run_can_be_retried_and_only_a_failed_one(make, root):
    env = make([ProviderError("down"), REVIEW, IDEAS])
    sid = env.client.post("/api/suggestions", json={"path": str(root)}).json()["id"]
    assert env.client.post(f"/api/suggestions/{sid}/retry").json()["status"] == "done"
    assert env.client.post(f"/api/suggestions/{sid}/retry").status_code == 409


def test_an_unknown_run_is_a_404(make):
    env = make([])
    assert env.client.get("/api/suggestions/" + "0" * 32).status_code == 404
    assert env.client.get("/api/suggestions/not-an-id").status_code == 404


def test_a_run_can_skip_the_ideas_pass(make, root):
    env = make([REVIEW])
    run = env.client.get(f"/api/suggestions/{env.client.post('/api/suggestions', json={'path': str(root), 'with_ideas': False}).json()['id']}").json()
    assert run["status"] == "done" and len(env.mock.calls) == 1


# ---- a build seeded with the code an idea cites ------------------------------------------------------


def seeded(env: Env, root, nodes=("core.py::shared", "a.py", "gone.py"), **extra) -> str:
    return finished(env, repo=str(root), evidence_nodes=list(nodes), **extra)


def test_a_seeded_build_carries_evidence_of_the_places_the_idea_cited(make, root):
    env = make([round_two(), draft()])
    sid = seeded(env, root)
    session = env.get(sid)
    assert session["status"] == "done" and session["seed"] == {"repo": root.name, "focus": None, "places": 3}
    result = session["result"]
    assert EVIDENCE_FILE in result["files"] and result["evidence"] == {"repo": root.name, "places": 2, "skipped": ["gone.py"]}
    text = env.client.get(f"/api/builds/{sid}/files/{EVIDENCE_FILE}").json()["text"]
    ev = read_evidence({EVIDENCE_FILE: text.encode()})
    assert [r.id for r in ev.refs] == ["core.py::shared", "a.py"] and ev.repo == root.name
    saved = env.post(sid, "save").json()
    assert saved["created"]  # imported through the same checked import
    stored = read_evidence(env.library.read("duplicate-function-finder")[1])
    assert stored is not None and len(stored.refs) == 2
    recheck = env.client.post("/api/library/duplicate-function-finder/recheck", json={"repo": str(root)}).json()
    assert recheck["ok"] is True and recheck["counts"] == {"holds": 2}


def test_a_build_without_a_repository_is_exactly_what_it_was(make):
    env = make([round_two(), draft()])
    sid = finished(env)
    session = env.get(sid)
    assert session["seed"] is None and "evidence" not in session["result"] and EVIDENCE_FILE not in session["result"]["files"]


def test_the_session_never_shows_the_path_only_the_folders_name(make, root):
    env = make([round_two(), draft()])
    assert not leaks(root, env.get(seeded(env, root)))


def test_a_repository_that_is_gone_when_the_build_ends_does_not_fail_the_build(make, root):
    env = make([round_two(), draft()])
    sid = env.start(FULL, repo=str(root), evidence_nodes=["core.py"])["id"]
    for p in sorted(root.rglob("*"), reverse=True):
        p.unlink() if p.is_file() else p.rmdir()
    root.rmdir()
    session = env.post(sid, "approve").json()
    assert session["status"] == "done" and EVIDENCE_FILE not in session["result"]["files"]
    assert any("evidence was not recorded" in n.lower() for n in session["notes"])


def test_bad_seeds_are_refused_before_anything_starts(make, root, tmp_path):
    env = make([])
    for body, why in (
        ({"repo": "relative", "evidence_nodes": ["a.py"]}, "absolute"),
        ({"repo": str(tmp_path / "nowhere"), "evidence_nodes": ["a.py"]}, "Not a directory"),
        ({"repo": str(root), "evidence_nodes": []}, "place"),
        ({"evidence_nodes": ["a.py"]}, "repo"),
        ({"repo": str(root), "evidence_nodes": ["a.py"], "kind": "mcp"}, "skills and agents"),
    ):
        r = env.client.post("/api/builds", json={"description": FULL, **body})
        assert r.status_code == 400 and why in r.json()["detail"], body


def test_the_seed_is_bounded(make, root):
    env = make([])
    r = env.client.post("/api/builds", json={"description": FULL, "repo": str(root), "evidence_nodes": [f"n{i}" for i in range(300)]})
    assert r.status_code == 422  # more than a skill may cite is refused by the request's own limits


def test_the_service_refuses_what_the_route_would(make, root):
    env = make([])
    with pytest.raises(BadRequest):
        env.builder.start(FULL, False, "skill", seed={"repo": "relative", "focus": None, "nodes": ["a.py"]})


# ---- the database ------------------------------------------------------------------------------------


def test_the_migration_adds_the_seed_column_and_the_suggestion_table(tmp_path):
    db = Database(f"sqlite:///{(tmp_path / 'm.db').as_posix()}")
    db.migrate()
    insp = inspect(db.engine)
    assert "seed" in {c["name"] for c in insp.get_columns("build_sessions")}
    assert {c["name"] for c in insp.get_columns("suggest_runs")} >= {"id", "status", "repo", "repo_name", "focus", "with_ideas", "result", "error", "retryable"}
    db.migrate()  # safe to repeat
    db.close()


def test_a_run_that_a_stop_left_half_done_is_marked_failed(tmp_path):
    from skillforge.db import SuggestRun, now_text

    db = Database(f"sqlite:///{(tmp_path / 'r.db').as_posix()}")
    db.migrate()
    with db.session() as s:
        s.add(SuggestRun(id="a" * 32, created_at=now_text(), updated_at=now_text(), status="working", repo="/x", repo_name="x", focus=None,
                         with_ideas=True, result=None, error="", retryable=False))
    assert db.recover_interrupted() >= 1
    with db.session() as s:
        row = s.get(SuggestRun, "a" * 32)
        assert row.status == "failed" and row.retryable and "stopped" in row.error
    db.close()


def test_an_unexpected_failure_while_recording_evidence_never_fails_the_build(make, root, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("the graph blew up")

    monkeypatch.setattr("skillforge.builder.service.record_evidence", boom)
    env = make([round_two(), draft()])
    session = env.get(seeded(env, root))
    assert session["status"] == "done" and session["result"]["status"] == "ok" and EVIDENCE_FILE not in session["result"]["files"]
    assert any("evidence was not recorded" in n.lower() and "RuntimeError" in n for n in session["notes"])
