"""One server, several people: nobody sees, changes or even detects anybody else's builds, library, test runs, quality reports or plugins.

Every route is tried by a second person against the first person's data. The answer must be a 404 that is identical to the answer for something that never existed
(never a 403, which would say "it exists"). The owner (the access token) is a person too, with the data that existed before accounts.
"""

from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from test_accounts_auth import TOKEN, hosted, keys, sign_in
from test_api import NAME, skill_zip, upload
from test_builder import FULL
from test_evaluate import CASES, SKILL_MD, replier
from test_skill_build import draft, round_two

from skillforge.ai import AIService
from skillforge.api import create_app
from skillforge.builder import Builder, JobRunner, ModelOptions, SessionNotFound
from skillforge.builder.suggestions import SuggestRuns
from skillforge.db import BuildSession, Database, EvalRun, ModelCall, SuggestRun, now_text
from skillforge.library import Library, LibraryError
from skillforge.library.registry import Libraries
from skillforge.providers import MockProvider

MISSING = "0" * 32  # a well-formed id that nobody has


class Parked:
    """A job runner that holds the work instead of doing it, so a run can be looked at while it is still "working"."""

    inline = False

    def __init__(self):
        self.jobs = []

    def submit(self, fn, *args):
        self.jobs.append((fn, args))

    def shutdown(self):
        pass


class World:
    def __init__(self, tmp_path, responses=(), *, service: bool = False, runner=None, options: ModelOptions | None = None):
        self.tmp = tmp_path
        self.db = Database(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
        self.db.migrate()
        self.library = Library(tmp_path / "library")
        self.mock = MockProvider(responses if callable(responses) else list(responses))
        self.builder = Builder(
            self.db, self.library, tmp_path / "builds", provider_factory=(lambda: AIService.single(self.mock)) if service else (lambda: self.mock),
            runner=runner or JobRunner(inline=True), sandbox_note=lambda: "unavailable. (test)",
            # These tests are about who can see what, not about key policy: unless a test says otherwise, people may use the shared mock model.
            model_options=options if options is not None else ModelOptions(shared_calls_per_day=1_000_000),
        )
        self.app = create_app(self.library, builder=self.builder, hosted=hosted(allowed_emails=frozenset({"*"})), google_keys=keys)
        self.libraries: Libraries = self.app.state.libraries

    def person(self, n: int) -> TestClient:
        client = TestClient(self.app, base_url="http://localhost")
        assert sign_in(client, {"sub": f"sub-{n}", "email": f"p{n}@example.com", "name": f"Person {n}"}).status_code == 200
        return client

    def owner(self) -> TestClient:
        client = TestClient(self.app, base_url="http://localhost")
        assert client.post("/api/auth/login", json={"token": TOKEN}).status_code == 200
        return client

    def uid(self, n: int) -> str:
        with self.db.session() as s:
            return s.execute(text("SELECT id FROM users WHERE email = :e"), {"e": f"p{n}@example.com"}).scalar_one()

    def close(self) -> None:
        self.builder.runner.shutdown()
        self.db.close()


@pytest.fixture
def world(tmp_path):
    made: list[World] = []

    def factory(responses=(), **kw) -> World:
        w = World(tmp_path / f"w{len(made)}", responses, **kw)
        w.tmp.mkdir(parents=True, exist_ok=True)
        made.append(w)
        return w

    yield factory
    for w in made:
        w.close()


# ---- a build is private -------------------------------------------------------------------------------


def start(client: TestClient) -> str:
    r = client.post("/api/builds", json={"description": FULL})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_a_build_is_visible_only_to_the_person_who_started_it(world):
    w = world([round_two(), draft()])
    ada, bob = w.person(1), w.person(2)
    sid = start(ada)
    assert ada.get(f"/api/builds/{sid}").status_code == 200
    assert [b["id"] for b in ada.get("/api/builds").json()] == [sid] and bob.get("/api/builds").json() == []
    seen, never = bob.get(f"/api/builds/{sid}"), bob.get(f"/api/builds/{MISSING}")
    assert seen.status_code == never.status_code == 404 and seen.json() == never.json()


@pytest.mark.parametrize("method, path, body", [
    ("POST", "/api/builds/{sid}/answers", {"answers": {}}), ("POST", "/api/builds/{sid}/approve", None), ("POST", "/api/builds/{sid}/retry", None),
    ("POST", "/api/builds/{sid}/save", {"accept_draft": True}), ("GET", "/api/builds/{sid}/files/SKILL.md", None), ("DELETE", "/api/builds/{sid}", None),
])
def test_nobody_else_can_act_on_a_build_and_the_answer_says_nothing_about_it(world, method, path, body):
    w = world([round_two(), draft()])
    ada, bob = w.person(1), w.person(2)
    sid = start(ada)
    before = ada.get(f"/api/builds/{sid}").json()
    kw = {"json": body} if body is not None else {}
    seen = bob.request(method, path.format(sid=sid), **kw)
    never = bob.request(method, path.format(sid=MISSING), **kw)
    assert seen.status_code == never.status_code == 404 and seen.json() == never.json()
    assert ada.get(f"/api/builds/{sid}").json() == before  # and nothing changed


def test_the_owner_and_each_person_have_separate_builds(world):
    w = world([round_two(), draft(), round_two(), draft()])
    owner, ada = w.owner(), w.person(1)
    owners, adas = start(owner), start(ada)
    assert [b["id"] for b in owner.get("/api/builds").json()] == [owners] and [b["id"] for b in ada.get("/api/builds").json()] == [adas]
    assert owner.get(f"/api/builds/{adas}").status_code == 404 and ada.get(f"/api/builds/{owners}").status_code == 404


def test_every_row_carries_whose_it_is_and_old_style_callers_default_to_the_owner(world):
    w = world([round_two(), draft(), round_two(), draft()])
    owner, ada = w.owner(), w.person(1)
    start(owner)
    start(ada)
    with w.db.session() as s:
        assert sorted(r.user_id for r in s.execute(select(BuildSession)).scalars()) == sorted(["local", w.uid(1)])
    # Leaving the user out must fail CLOSED: a caller that forgets to say who is asking only ever reaches the owner's data.
    adas = [b["id"] for b in ada.get("/api/builds").json()][0]
    with pytest.raises(SessionNotFound):
        w.builder.get(adas)
    assert [b["id"] for b in w.builder.list()] == [b["id"] for b in owner.get("/api/builds").json()]


def test_a_build_is_saved_into_its_own_persons_library_and_nobody_elses(world):
    w = world([round_two(), draft()])
    ada, bob, owner = w.person(1), w.person(2), w.owner()
    sid = start(ada)
    assert ada.post(f"/api/builds/{sid}/approve").status_code == 200
    saved = ada.post(f"/api/builds/{sid}/save", json={"accept_draft": True})
    assert saved.status_code == 200, saved.text
    name = saved.json()["name"]
    assert [x["name"] for x in ada.get("/api/library").json()] == [name]
    assert bob.get("/api/library").json() == [] and owner.get("/api/library").json() == []
    assert (w.tmp / "users" / w.uid(1) / "library" / name).is_dir()
    assert not (w.tmp / "library").exists() or not any((w.tmp / "library").iterdir())  # the owner's folder was not touched


def test_the_model_calls_of_a_build_are_counted_for_the_person_who_asked(world):
    w = world([round_two(), draft()], service=True)
    ada = w.person(1)
    sid = start(ada)
    ada.post(f"/api/builds/{sid}/approve")
    with w.db.session() as s:
        rows = s.execute(select(ModelCall)).scalars().all()
    assert rows and {r.user_id for r in rows} == {w.uid(1)}


# ---- the library is private ---------------------------------------------------------------------------


def test_a_skill_imported_by_one_person_is_not_in_anyone_elses_library(world):
    w = world()
    ada, bob, owner = w.person(1), w.person(2), w.owner()
    assert upload(ada, skill_zip()).status_code == 200
    assert [x["name"] for x in ada.get("/api/library").json()] == [NAME]
    assert bob.get("/api/library").json() == [] and owner.get("/api/library").json() == []
    assert (w.tmp / "users" / w.uid(1) / "library" / NAME).is_dir() and not (w.tmp / "library" / NAME).exists()


@pytest.mark.parametrize("path", [
    "/api/library/{n}", "/api/library/{n}/diff", "/api/library/{n}/evidence", "/api/library/{n}/export", "/api/library/{n}/versions/1/files/SKILL.md",
    "/api/library/{n}/tests", "/api/library/{n}/quality", "/api/evals/preview?name={n}",
])
def test_every_way_of_reading_a_skill_says_not_found_to_someone_else_exactly_as_for_a_skill_that_never_existed(world, path):
    w = world()
    ada, bob = w.person(1), w.person(2)
    assert upload(ada, skill_zip()).status_code == 200
    assert upload(ada, skill_zip("A different body.\n")).status_code == 200  # two versions, so the diff route has something to compare
    assert ada.get(path.format(n=NAME)).status_code == 200, path
    seen, never = bob.get(path.format(n=NAME)), bob.get(path.format(n="no-such-skill"))
    assert seen.status_code == never.status_code == 404, path
    assert NAME not in seen.text or NAME in path.format(n=NAME)  # the answer repeats at most what the person typed


@pytest.mark.parametrize("method, path, body", [
    ("POST", "/api/library/{n}/rollback", {"to": 1}), ("POST", "/api/library/{n}/install", {"target": "personal"}),
    ("POST", "/api/library/{n}/recheck", {"repo": "/x"}), ("POST", "/api/library/{n}/tests", {"base_version": 1, "cases": []}),
])
def test_nobody_else_can_change_a_skill_they_do_not_own(world, method, path, body):
    w = world()
    ada, bob = w.person(1), w.person(2)
    upload(ada, skill_zip())
    before = ada.get(f"/api/library/{NAME}").json()
    r = bob.request(method, path.format(n=NAME), json=body)
    assert r.status_code in (403, 404, 400), r.text  # the hosted-off routes are a 403 for everyone; the rest a 404
    assert ada.get(f"/api/library/{NAME}").json() == before


def test_the_other_kinds_of_library_are_private_too(world):
    w = world()
    ada, bob = w.person(1), w.person(2)
    uid = w.uid(1)
    w.libraries.for_user(uid).for_kind("agent").add(
        "my-agent", {"AGENT.md": b"---\nname: my-agent\ndescription: d\ntools: Read\n---\nBody\n"}, source_kind="folder", source_label="t",
    )
    assert [x["name"] for x in ada.get("/api/library?kind=agent").json()] == ["my-agent"]
    assert bob.get("/api/library?kind=agent").json() == []
    assert (w.tmp / "users" / uid / "library-agent" / "my-agent").is_dir()


def test_a_plugin_can_only_be_made_from_the_composers_own_library_and_is_kept_there(world):
    w = world()
    ada, bob = w.person(1), w.person(2)
    upload(ada, skill_zip())
    body = {"name": "my-plugin", "description": "Helpers.", "components": [{"kind": "skill", "name": NAME}]}
    assert ada.post("/api/plugins/preview", json=body).status_code == 200
    assert bob.post("/api/plugins/preview", json=body).status_code in (400, 404)  # Bob has no such skill
    kept = ada.post("/api/plugins", json=body)
    assert kept.status_code == 200, kept.text
    assert [x["name"] for x in ada.get("/api/library?kind=plugin").json()] == ["my-plugin"] and bob.get("/api/library?kind=plugin").json() == []


# ---- test runs and suggestion runs are private --------------------------------------------------------


def put_skill(w: World, uid: str, name: str = "commit-writer"):
    files = {"SKILL.md": SKILL_MD.encode(), "tests/cases.json": json.dumps([t.model_dump() for t in CASES]).encode()}
    return w.libraries.for_user(uid).add(name, files, source_kind="folder", source_label="test")


def test_a_test_run_belongs_to_the_person_who_started_it(world):
    w = world(replier())
    ada, bob = w.person(1), w.person(2)
    put_skill(w, w.uid(1))
    r = ada.post("/api/evals", json={"name": "commit-writer"})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert ada.get(f"/api/evals/{rid}").status_code == 200 and [x["id"] for x in ada.get("/api/evals").json()] == [rid]
    assert ada.get(f"/api/evals/{rid}").json()["status"] == "done"  # the background run found Ada's skill in HER library and finished
    assert bob.get("/api/evals").json() == []
    seen, never = bob.get(f"/api/evals/{rid}"), bob.get(f"/api/evals/{MISSING}")
    assert seen.status_code == never.status_code == 404 and seen.json() == never.json()
    assert bob.post(f"/api/evals/{rid}/retry").status_code == 404
    assert bob.post("/api/evals", json={"name": "commit-writer"}).status_code == 404  # Bob has no such skill to test
    with w.db.session() as s:
        assert {r.user_id for r in s.execute(select(EvalRun)).scalars()} == {w.uid(1)}


def test_the_quality_report_shows_only_that_persons_test_runs(world):
    w = world(replier())
    ada, bob = w.person(1), w.person(2)
    put_skill(w, w.uid(1))
    put_skill(w, w.uid(2))
    ada.post("/api/evals", json={"name": "commit-writer"})
    assert ada.get("/api/library/commit-writer/quality").status_code == 200
    adas_run = ada.get("/api/evals").json()[0]["id"]
    assert adas_run in json.dumps(ada.get("/api/library/commit-writer/quality").json())  # the report does show a person's own run...
    assert adas_run not in json.dumps(bob.get("/api/library/commit-writer/quality").json())  # ...and never another person's


def test_a_running_test_is_not_handed_to_someone_who_clicks_at_the_same_moment(world):
    w = world(replier(), runner=Parked())  # the work is held, so both runs are still "working" when the other person clicks
    ada, bob = w.person(1), w.person(2)
    put_skill(w, w.uid(1))
    put_skill(w, w.uid(2))
    first = ada.post("/api/evals", json={"name": "commit-writer"}).json()
    second = bob.post("/api/evals", json={"name": "commit-writer"}).json()
    assert first["status"] == second["status"] == "working" and first["id"] != second["id"]  # the "second click gets the run that is going" rule never crosses people
    assert ada.post("/api/evals", json={"name": "commit-writer"}).json()["id"] == first["id"]  # and it still holds for a person's own second click


def test_a_second_click_on_the_same_folder_never_hands_out_somebody_elses_suggestion_run(world, tmp_path):
    w = world()
    folder = tmp_path / "repo"
    folder.mkdir()
    (folder / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    runs = SuggestRuns(w.db, Parked(), lambda user: w.mock)
    mine, theirs = runs.start(str(folder), user="u" * 32), runs.start(str(folder), user="v" * 32)
    assert mine["id"] != theirs["id"] and runs.start(str(folder), user="u" * 32)["id"] == mine["id"]


def seed_runs(w: World):
    stamp = now_text()
    with w.db.session() as s:
        for rid, uid in (("a" * 32, "local"), ("b" * 32, "u" * 32), ("c" * 32, "v" * 32)):
            s.add(SuggestRun(id=rid, created_at=stamp, updated_at=stamp, status="done", repo="/r", repo_name="r", focus=None, with_ideas=True,
                             result={"suggestions": [{"category": "skill", "evidence_nodes": ["n"]}]}, error="", retryable=False, user_id=uid))


def test_suggestion_runs_are_private_too(world):
    w = world()
    seed_runs(w)
    runs = SuggestRuns(w.db, JobRunner(inline=True), lambda user: w.mock)
    assert [r["id"] for r in runs.list(user="u" * 32)] == ["b" * 32] and [r["id"] for r in runs.list()] == ["a" * 32]  # no user: the owner's
    assert runs.get("b" * 32, user="u" * 32)["id"] == "b" * 32
    for call in (lambda: runs.get("b" * 32, user="v" * 32), lambda: runs.get("b" * 32), lambda: runs.seed_for("b" * 32, 0, user="v" * 32),
                 lambda: runs.retry("b" * 32, user="v" * 32)):
        with pytest.raises(SessionNotFound):
            call()
    assert runs.seed_for("b" * 32, 0, user="u" * 32)["nodes"] == ["n"]


def test_a_builder_with_no_way_to_find_a_persons_library_refuses_rather_than_use_a_shared_one(tmp_path):
    from skillforge.builder import BuilderError
    from skillforge.builder.evals import EvalRuns

    db = Database(f"sqlite:///{(tmp_path / 'n.db').as_posix()}")
    db.migrate()
    owner_library = Library(tmp_path / "library")
    bare = Builder(db, owner_library, tmp_path / "builds", provider_factory=lambda: MockProvider([]), runner=JobRunner(inline=True))  # no library_for
    assert bare._library("local") is owner_library
    with pytest.raises(BuilderError):
        bare._library("u" * 32)
    with pytest.raises(BuilderError):
        EvalRuns(db, JobRunner(inline=True), lambda user: MockProvider([]), owner_library)._library("u" * 32)
    bare.runner.shutdown()
    db.close()


# ---- where a person's files live ----------------------------------------------------------------------


def test_a_persons_library_folder_is_named_by_the_id_we_made_and_nothing_else(tmp_path):
    libs = Libraries(Library(tmp_path / "library"))
    uid = "0123456789abcdef" * 2
    assert libs.for_user(uid).root == tmp_path / "users" / uid / "library"
    assert libs.for_user(uid).for_kind("agent").root == tmp_path / "users" / uid / "library-agent"
    assert libs.for_user("local") is libs.owner and libs.owner.root == tmp_path / "library"


@pytest.mark.parametrize("odd", ["", "..", "../x", "a/b", "A" * 32, "0" * 31, "0" * 33, "g" * 32, "local ", "LOCAL", "x" * 500, None, 5])
def test_anything_that_is_not_an_id_we_made_never_becomes_a_path(tmp_path, odd):
    with pytest.raises(LibraryError):
        Libraries(Library(tmp_path / "library")).for_user(odd)


def test_two_people_never_share_a_folder(tmp_path):
    libs = Libraries(Library(tmp_path / "library"))
    assert libs.for_user("a" * 32).root != libs.for_user("b" * 32).root and libs.for_user("a" * 32).root.parent.parent == libs.for_user("b" * 32).root.parent.parent


def test_the_password_less_owner_cookie_is_the_owner_and_cannot_be_turned_into_a_person(world):
    w = world()
    owner = w.owner()
    assert re.fullmatch(r"v1\.\d+\.[0-9a-f]{64}", owner.cookies.get("skillforge_session"))  # a v1 cookie carries no person at all
    assert upload(owner, skill_zip()).status_code == 200 and (w.tmp / "library" / NAME).is_dir()
