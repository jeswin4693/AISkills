"""Every place a model is needed asks for the right person's model (slice AI): a build, a suggestion run, a Testing Lab run, and the two status routes.

The rules themselves (own key, shared allowance, the gate) are test_model_access.py; this proves each call site really goes through them.
"""

from __future__ import annotations

import json

from sqlalchemy import select
from test_accounts_auth import TOKEN
from test_accounts_isolation import World, start
from test_accounts_review import _fill
from test_skill_build import draft, round_two

from skillforge.ai import AIService
from skillforge.ai.doctor import Ping
from skillforge.builder import JobRunner, ModelOptions
from skillforge.builder.evals import EvalRuns
from skillforge.builder.keybox import KeyBox
from skillforge.builder.suggestions import SuggestRuns
from skillforge.db import Database, EvalRun, ModelCall, SuggestRun, now_text
from skillforge.library import Library
from skillforge.providers import MockProvider, ProviderError

ADA_KEY = "KEY-FOR-ADA-0123456789"
BOB_KEY = "KEY-FOR-BOB-0123456789"


def keyed_world(tmp_path, mocks: dict[str, MockProvider], server_responses=(), **options):
    """A server whose people can save keys. `mocks` is what each key's provider answers; `built` records what the provider builder was handed."""
    built: list[dict] = []

    def build(env):
        built.append(dict(env))
        return AIService.single(mocks[env["GROQ_API_KEY"]])

    return World(tmp_path, list(server_responses), service=True, options=ModelOptions(keybox=KeyBox(TOKEN), build=build, **options)), built


def usage_rows(w: World) -> list[tuple]:
    with w.db.session() as s:
        return [(r.user_id, r.key_source, r.session_id) for r in s.execute(select(ModelCall).order_by(ModelCall.id)).scalars()]


# ---- a build -------------------------------------------------------------------------------------------


def test_a_persons_build_uses_their_own_model_and_nobody_elses(tmp_path):
    ada_mock, bob_mock = MockProvider([round_two(), draft()]), MockProvider([round_two(), draft()])
    w, built = keyed_world(tmp_path, {ADA_KEY: ada_mock, BOB_KEY: bob_mock})
    ada = w.person(1)
    w.person(2)
    w.builder.access.save(w.uid(1), "groq", "m-ada", ADA_KEY)
    w.builder.access.save(w.uid(2), "groq", "m-bob", BOB_KEY)
    sid = start(ada)
    assert len(ada_mock.calls) >= 1 and bob_mock.calls == [] and w.mock.calls == []  # Ada's key paid; Bob's and the server's were never asked
    assert built == [{"LLM_PROVIDER": "groq", "LLM_MODEL": "m-ada", "GROQ_API_KEY": ADA_KEY}]  # nothing of anybody else's, nor the server's environment
    rows = usage_rows(w)
    assert rows and all(row == (w.uid(1), "own", sid) for row in rows)
    w.close()


def test_a_person_with_no_key_and_no_sharing_gets_a_failed_build_that_says_what_to_do(tmp_path):
    w, built = keyed_world(tmp_path, {})
    ada = w.person(1)
    session = ada.get(f"/api/builds/{start(ada)}").json()
    assert session["status"] == "failed" and session["retryable"] is True and "Settings" in session["error"]
    assert w.mock.calls == [] and built == []  # the owner's model was not borrowed
    w.close()


def test_the_owner_still_uses_the_servers_model_and_it_is_recorded_as_the_servers(tmp_path):
    w, built = keyed_world(tmp_path, {}, server_responses=[round_two(), draft()])
    sid = start(w.owner())
    assert len(w.mock.calls) >= 1 and built == []
    rows = usage_rows(w)
    assert rows and all(row == ("local", "server", sid) for row in rows)
    w.close()


def test_a_key_the_provider_refuses_fails_the_build_without_the_key_in_what_is_stored_or_shown(tmp_path):
    class Refuser(MockProvider):
        secrets = (ADA_KEY,)  # what a real adapter reports, so the engine can clean it out of any error text

    refusing = Refuser([ProviderError(f"401: the key {ADA_KEY} is not valid", kind="auth")])
    w, _ = keyed_world(tmp_path, {ADA_KEY: refusing})
    ada = w.person(1)
    w.builder.access.save(w.uid(1), "groq", "m-ada", ADA_KEY)
    session = ada.get(f"/api/builds/{start(ada)}").json()
    assert session["status"] == "failed" and "not valid" in session["error"]  # the person is told it was refused ...
    assert ADA_KEY not in json.dumps(session) and ADA_KEY not in repr(w.builder.get(session["id"], user=w.uid(1)))  # ... without the key being repeated
    w.close()


# ---- a suggestion run and a Testing Lab run (no builder session) ------------------------------------------


def test_a_background_suggestion_run_asks_for_the_model_of_the_person_whose_run_it_is(tmp_path):
    db = Database(f"sqlite:///{(tmp_path / 's.db').as_posix()}")
    db.migrate()
    seen: list[str] = []

    def provider_for(user: str):
        seen.append(user)
        raise ProviderError("the test stops here", retryable=True)

    stamp, uid = now_text(), "u" * 32
    with db.session() as s:
        s.add(SuggestRun(id="b" * 32, created_at=stamp, updated_at=stamp, status="working", repo="/r", repo_name="r", focus=None, with_ideas=True,
                         result=None, error="", retryable=False, user_id=uid))
    SuggestRuns(db, JobRunner(inline=True), provider_for)._execute("b" * 32)
    assert seen == [uid]  # the person on the run's own row, not whoever asks next
    with db.session() as s:
        row = s.get(SuggestRun, "b" * 32)
        assert (row.status, row.retryable) == ("failed", True) and "stops here" in row.error
    db.close()


def test_a_background_lab_run_asks_for_the_model_of_the_person_whose_run_it_is(tmp_path):
    db = Database(f"sqlite:///{(tmp_path / 'e.db').as_posix()}")
    db.migrate()
    seen: list[str] = []

    def provider_for(user: str):
        seen.append(user)
        raise ProviderError("the test stops here")

    uid = "v" * 32
    with db.engine.begin() as c:
        _fill(c, "eval_runs", {"id": "c" * 32, "user_id": uid, "status": "working"})
    EvalRuns(db, JobRunner(inline=True), provider_for, Library(tmp_path / "lib"))._execute("c" * 32)
    assert seen == [uid]
    with db.session() as s:
        row = s.get(EvalRun, "c" * 32)
        assert (row.status, row.retryable) == ("failed", True)  # a refusal kind that fixing the key can cure stays retryable
    db.close()


def test_a_suggestion_run_started_through_the_builder_by_a_person_with_no_key_fails_asking_for_one(tmp_path):
    w, _ = keyed_world(tmp_path, {})
    w.person(1)
    uid = w.uid(1)
    folder = tmp_path / "repo"
    folder.mkdir()
    (folder / "a.py").write_text("def f():\n    return 1\n")
    runs = w.builder.suggestions
    run = runs.get(runs.start(str(folder), user=uid)["id"], user=uid)  # the runner is inline: it has already run
    assert run["status"] == "failed" and run["retryable"] is True and "Settings" in run["error"]
    assert w.mock.calls == []
    w.close()


# ---- the two routes the pages read -------------------------------------------------------------------------


def test_the_provider_status_is_per_person_and_never_shows_a_key(tmp_path):
    w, _ = keyed_world(tmp_path, {ADA_KEY: MockProvider([])})
    ada, owner = w.person(1), w.owner()
    none = ada.get("/api/provider").json()
    assert none["configured"] is False and none["source"] == "none" and "Settings" in none["detail"]
    w.builder.access.save(w.uid(1), "groq", "m-ada", ADA_KEY)
    own = ada.get("/api/provider")
    assert own.json()["configured"] is True and own.json()["source"] == "own" and ADA_KEY not in own.text
    assert owner.get("/api/provider").json()["source"] == "server"  # the owner sees the server's own model, as before
    w.close()


def test_the_model_check_tries_only_the_persons_own_model(tmp_path):
    mock = MockProvider([Ping(reply="ok")])
    w, _ = keyed_world(tmp_path, {ADA_KEY: mock})
    ada = w.person(1)
    nothing = ada.post("/api/provider/check").json()
    assert nothing["configured"] is False and nothing["checks"] == [] and w.mock.calls == []  # the server's model is never tried for a person
    w.builder.access.save(w.uid(1), "groq", "m-ada", ADA_KEY)
    result = ada.post("/api/provider/check").json()
    assert result["configured"] is True and len(result["checks"]) == 1 and result["checks"][0]["ok"] is True
    assert len(mock.calls) == 1 and w.mock.calls == []
    w.close()
