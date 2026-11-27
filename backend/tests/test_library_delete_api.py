"""Deleting a library entry over HTTP (slice AK, task 4): `DELETE /api/library/{name}?kind=&confirm=`.

The server checks the typed name itself (a script that leaves it out is refused), a person can only ever delete from their own library, and nothing is deleted
while that person has work running. The hosted-world helpers are those of the isolation tests.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from test_accounts_isolation import World, world  # noqa: F401  (world is a pytest fixture)
from test_builder import make  # noqa: F401  (make is a pytest fixture)

from skillforge.db import BuildSession, EvalRun, ScanRun, SuggestRun, now_text
from skillforge.library import Library


def put(lib: Library, name: str = "foo", versions: int = 1) -> None:
    for n in range(versions):
        lib.add(name, {"SKILL.md": f"{name} v{n + 1}\n".encode()}, source_kind="test", source_label="t")


def delete(client, name: str, confirm: str | None = None, kind: str | None = None):
    params = {}
    if confirm is not None:
        params["confirm"] = confirm
    if kind is not None:
        params["kind"] = kind
    return client.delete(f"/api/library/{name}", params=params)


def names(client, kind: str | None = None) -> list[str]:
    return [s["name"] for s in client.get("/api/library", params={"kind": kind} if kind else {}).json()]


# ---- rows that say "something is working", shared with the erase tests ---------------------------------------------------------------------------


def add_build(w: World, uid: str, sid: str, status: str = "working") -> None:
    stamp = now_text()
    with w.db.session() as s:
        s.add(BuildSession(id=sid, created_at=stamp, updated_at=stamp, status=status, description="d", words="d", round=1, with_scripts=False, questions=[],
                           error="", retryable=False, model_calls=0, notes=[], saved_name="", saved_version="", user_id=uid))


def add_lab_run(w: World, uid: str, rid: str, status: str = "working", name: str = "foo", kind: str = "skill") -> None:
    stamp = now_text()
    with w.db.session() as s:
        s.add(EvalRun(id=rid, created_at=stamp, updated_at=stamp, status=status, kind=kind, name=name, version=1, content_hash="h", runs=1, baseline=True,
                      cases_total=1, cases_done=0, result=None, error="", retryable=False, user_id=uid))


def add_scan_run(w: World, uid: str, rid: str, status: str = "working", name: str = "foo", kind: str = "skill") -> None:
    stamp = now_text()
    with w.db.session() as s:
        s.add(ScanRun(id=rid, created_at=stamp, updated_at=stamp, status=status, kind=kind, name=name, version=1, content_hash="h", runs=1, scenarios=5, control=True,
                      draft=True, tasks_total=5, tasks_done=0, result=None, error="", retryable=False, user_id=uid))


def add_suggest_run(w: World, uid: str, rid: str, status: str = "working") -> None:
    stamp = now_text()
    with w.db.session() as s:
        s.add(SuggestRun(id=rid, created_at=stamp, updated_at=stamp, status=status, repo="/r", repo_name="r", focus=None, with_ideas=True, result=None,
                         error="", retryable=False, user_id=uid))


# ---- the route --------------------------------------------------------------------------------------------------------------------------------


def test_the_owner_deletes_with_the_typed_name_and_the_answer_counts_what_went(world):
    w = world()
    put(w.library, "foo", versions=2)
    put(w.library, "bar")
    owner = w.owner()
    r = delete(owner, "foo", "foo")
    assert r.status_code == 200, r.text
    assert r.json() == {"deleted": True, "name": "foo", "kind": "skill", "versions": 2, "backups": 0, "leftover": False}
    assert names(owner) == ["bar"] and str(w.tmp) not in r.text  # no path of this server in the answer


@pytest.mark.parametrize("confirm", [None, "", "FOO", "foo ", " foo", "bar"])
def test_no_confirmation_or_a_different_one_is_refused_and_nothing_is_deleted(world, confirm):
    w = world()
    put(w.library, "foo")
    owner = w.owner()
    r = delete(owner, "foo", confirm)
    assert r.status_code == 400 and "Type the name" in r.json()["detail"]
    assert names(owner) == ["foo"]


def test_a_person_deletes_only_from_their_own_library(world):
    w = world()
    ada, bob = w.person(1), w.person(2)
    for lib in (w.library, w.libraries.for_user(w.uid(1)), w.libraries.for_user(w.uid(2))):
        put(lib, "foo")
    assert delete(ada, "foo", "foo").status_code == 200
    assert names(ada) == [] and names(bob) == ["foo"] and names(w.owner()) == ["foo"]


def test_another_person_cannot_reach_it_by_any_name_and_the_answer_is_the_same_as_for_a_missing_one(world):
    w = world()
    ada, bob = w.person(1), w.person(2)
    put(w.libraries.for_user(w.uid(1)), "foo")
    seen, never = delete(bob, "foo", "foo"), delete(bob, "nothing-here", "nothing-here")
    assert seen.status_code == never.status_code == 404 and seen.json()["detail"].replace("foo", "x") == never.json()["detail"].replace("nothing-here", "x")
    assert names(ada) == ["foo"]


def test_every_kind_can_be_deleted_and_only_that_kind(world):
    w = world()
    owner = w.owner()
    kinds = ["skill", "agent", "plugin", "mcp", "mcp-node"]
    for kind in kinds:
        put(w.library.for_kind(kind), "foo")
    remaining = list(kinds)
    for kind in kinds:
        r = delete(owner, "foo", "foo", kind=None if kind == "skill" else kind)
        assert r.status_code == 200 and r.json()["kind"] == kind, r.text
        remaining.remove(kind)
        assert [k for k in kinds if names(owner, None if k == "skill" else k) == ["foo"]] == remaining


def test_delete_is_refused_while_the_person_has_work_running_and_another_persons_work_does_not_count(world):
    w = world()
    put(w.library, "foo")
    owner = w.owner()
    w.person(1)
    add_build(w, w.uid(1), "b" * 32)  # somebody else's build is working: it does not block the owner
    assert delete(owner, "foo", "foo").status_code == 200
    put(w.library, "foo")
    add_build(w, "local", "c" * 32)
    r = delete(owner, "foo", "foo")
    assert r.status_code == 409 and "work running" in r.json()["detail"] and names(owner) == ["foo"]


@pytest.mark.parametrize("name,kind", [("Foo", None), ("foo..", None), ("foo", "nope")])
def test_an_odd_name_or_an_unknown_kind_is_a_400_and_deletes_nothing(world, name, kind):
    w = world()
    put(w.library, "foo")
    owner = w.owner()
    assert delete(owner, name, name, kind).status_code == 400
    assert names(owner) == ["foo"]


def test_working_for_counts_builds_lab_runs_suggestion_runs_and_scan_runs_of_that_person_only(world):
    w = world()
    w.person(1)
    w.person(2)
    ada, bob = w.uid(1), w.uid(2)
    add_build(w, ada, "a" * 32)
    add_build(w, ada, "b" * 32)
    add_build(w, ada, "c" * 32, status="done")
    add_lab_run(w, ada, "d" * 32)
    add_lab_run(w, ada, "e" * 32, status="failed")
    add_suggest_run(w, ada, "f" * 32)
    add_scan_run(w, ada, "9" * 32)
    add_scan_run(w, ada, "8" * 32, status="done")
    add_build(w, bob, "1" * 32)
    assert (w.builder.working_for(ada), w.builder.working_for(bob), w.builder.working_for("local")) == (5, 1, 0)


def lab_ids(w: World, uid: str, name: str, kind: str = "skill") -> list[str]:
    with w.db.session() as s:
        return sorted(s.execute(select(EvalRun.id).where(EvalRun.user_id == uid, EvalRun.name == name, EvalRun.kind == kind)).scalars())


def scan_ids(w: World, uid: str, name: str, kind: str) -> list[str]:
    with w.db.session() as s:
        return sorted(s.execute(select(ScanRun.id).where(ScanRun.user_id == uid, ScanRun.name == name, ScanRun.kind == kind)).scalars())


def test_deleting_an_entry_removes_its_testing_lab_and_scan_runs_so_a_new_entry_of_that_name_starts_clean(world):
    """The review's Important finding: version numbers start again at v1 for a new entry of the same name, and the quality report matches Lab runs by name and
    version, so a finished run of the DELETED entry would have been shown as the new entry's tested result."""
    w = world()
    w.person(1)
    owner = w.owner()
    put(w.library, "foo")
    put(w.library.for_kind("agent"), "foo")
    add_lab_run(w, "local", "d" * 32, status="done")
    add_lab_run(w, "local", "e" * 32, status="failed")
    add_lab_run(w, "local", "f" * 32, status="done", name="bar")
    add_lab_run(w, w.uid(1), "1" * 32, status="done")  # another person's run of THEIR foo
    add_scan_run(w, "local", "5" * 32, status="done")  # the behaviour scan's runs have the same problem: a new entry must not show the old verdict
    add_scan_run(w, "local", "6" * 32, status="done", kind="agent")
    add_scan_run(w, "local", "7" * 32, status="done", name="bar")
    add_scan_run(w, w.uid(1), "4" * 32, status="done")
    assert delete(owner, "foo", "foo", kind="agent").status_code == 200  # another kind's foo: the skill's runs are not its runs
    assert lab_ids(w, "local", "foo") == ["d" * 32, "e" * 32]
    assert scan_ids(w, "local", "foo", "skill") == ["5" * 32] and scan_ids(w, "local", "foo", "agent") == []
    assert delete(owner, "foo", "foo").status_code == 200
    assert lab_ids(w, "local", "foo") == [] and lab_ids(w, "local", "bar") == ["f" * 32] and lab_ids(w, w.uid(1), "foo") == ["1" * 32]
    assert scan_ids(w, "local", "foo", "skill") == [] and scan_ids(w, "local", "bar", "skill") == ["7" * 32] and scan_ids(w, w.uid(1), "foo", "skill") == ["4" * 32]


def test_a_local_server_with_no_sign_in_deletes_too(make):
    env = make([])
    put(env.library, "foo")
    r = delete(env.client, "foo", "foo")
    assert r.status_code == 200 and env.library.names() == []
