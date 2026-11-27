"""The owner erases a turned-off person's data (slice AK, task 4): `POST /api/admin/people/{id}/erase`.

It removes the person's folder (their library of every kind), their builds (folders and rows), suggestion runs, Testing Lab runs and saved model key. It KEEPS the account
row (the person stays turned off) and EVERY usage row: those are the ledger a daily allowance is counted from, and `model_calls.session_id` cascades from a build, so a plain bulk
delete of the builds would have deleted them. The typed address is checked by the server. Nothing is erased for a person who is not turned off or has work running.
"""

from __future__ import annotations

import shutil

import pytest
from sqlalchemy import func, select
from test_accounts_isolation import World
from test_library_delete import make_link, outside
from test_library_delete_api import add_build, add_lab_run, add_scan_run, add_suggest_run, put

from skillforge.db import BuildSession, EvalRun, Job, ModelCall, ScanRun, SuggestRun, now_text
from skillforge.db.models import UserModelRow, UserRow
from skillforge.db.user_models import ModelStore
from skillforge.library import remove as remove_module


@pytest.fixture
def ew(tmp_path):
    made: list[World] = []

    def make() -> World:
        folder = tmp_path / f"w{len(made)}"
        folder.mkdir()
        w = World(folder)
        made.append(w)
        return w

    yield make
    for w in made:
        w.close()


def block(owner, uid):
    assert owner.post(f"/api/admin/people/{uid}/block").status_code == 200


def erase(owner, uid, confirm=None):
    return owner.post(f"/api/admin/people/{uid}/erase", json={} if confirm is None else {"confirm": confirm})


def usage(w: World) -> list[tuple]:
    with w.db.session() as s:
        return sorted(s.execute(select(ModelCall.id, ModelCall.user_id, ModelCall.session_id)).all())


def seed_person(w: World, n: int) -> dict:
    """Everything a person can have: a library of two kinds with a backup, a finished build (rows, a job and a folder), a suggestion run, a Lab run, a saved key, usage rows."""
    uid = w.uid(n)
    lib = w.libraries.for_user(uid)
    put(lib, "foo")
    put(lib.for_kind("agent"), "foo")
    (lib.backups / "foo-20261127-101500").mkdir(parents=True)
    (lib.backups / "foo-20261127-101500" / "SKILL.md").write_text("a copy", encoding="utf-8")
    sid = str(n) * 32
    add_build(w, uid, sid, status="done")
    folder = w.builder.builds_root / sid
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("built", encoding="utf-8")
    add_suggest_run(w, uid, f"s{n}".ljust(32, "0"), status="done")
    add_lab_run(w, uid, f"e{n}".ljust(32, "0"), status="done")
    add_scan_run(w, uid, f"c{n}".ljust(32, "0"), status="done")
    ModelStore(w.db).put(uid, "groq", "model-x", b"sealed", b"n" * 12)
    with w.db.session() as s:
        s.add(Job(session_id=sid, kind="build", status="succeeded", created_at=now_text(), events=[], error=""))
        for session in (sid, sid, None):
            s.add(ModelCall(created_at=now_text(), task="act", tier="actor", provider="p", model="m", attempt=1, status="ok", error_kind="", latency_ms=1,
                            user_id=uid, key_source="server", session_id=session))
    return {"uid": uid, "sid": sid, "folder": folder, "lib": lib}


def counts(w: World, uid: str) -> dict[str, int]:
    with w.db.session() as s:
        def n(model, column):
            return s.execute(select(func.count()).select_from(model).where(column == uid)).scalar_one()

        return {
            "builds": n(BuildSession, BuildSession.user_id), "suggestions": n(SuggestRun, SuggestRun.user_id), "labs": n(EvalRun, EvalRun.user_id),
            "scans": n(ScanRun, ScanRun.user_id), "keys": n(UserModelRow, UserModelRow.user_id), "users": n(UserRow, UserRow.id), "usage": n(ModelCall, ModelCall.user_id),
        }


def untouched(w: World, a: dict) -> bool:
    """Whether everything of this seeded person is still there."""
    return (w.libraries.users_root / a["uid"]).exists() and a["folder"].exists() and counts(w, a["uid"]) == {
        "builds": 1, "suggestions": 1, "labs": 1, "scans": 1, "keys": 1, "users": 1, "usage": 3,
    }


def test_erasing_removes_the_persons_folder_builds_runs_and_key_and_nothing_of_anybody_elses(ew):
    w = ew()
    w.person(1)
    w.person(2)
    a, b = seed_person(w, 1), seed_person(w, 2)
    put(w.library, "foo")  # the owner's own library
    owner = w.owner()
    block(owner, a["uid"])
    r = erase(owner, a["uid"], "p1@example.com")
    assert r.status_code == 200, r.text
    assert r.json() == {"erased": True, "builds": 1, "suggestion_runs": 1, "lab_runs": 1, "scan_runs": 1, "key_removed": True, "files_left": False}
    assert str(w.tmp) not in r.text
    assert not (w.libraries.users_root / a["uid"]).exists() and not a["folder"].exists()
    assert counts(w, a["uid"]) == {"builds": 0, "suggestions": 0, "labs": 0, "scans": 0, "keys": 0, "users": 1, "usage": 3}
    with w.db.session() as s:
        assert s.execute(select(func.count()).select_from(Job).where(Job.session_id == a["sid"])).scalar_one() == 0
    assert untouched(w, b) and b["lib"].names() == ["foo"] and w.library.names() == ["foo"]
    assert (b["lib"].backups / "foo-20261127-101500" / "SKILL.md").exists()


def test_every_usage_row_survives_including_those_of_the_erased_builds(ew):
    w = ew()
    w.person(1)
    w.person(2)
    a, b = seed_person(w, 1), seed_person(w, 2)
    before = usage(w)
    owner = w.owner()
    block(owner, a["uid"])
    assert erase(owner, a["uid"], "p1@example.com").status_code == 200
    after = usage(w)
    assert [(i, u) for i, u, _ in after] == [(i, u) for i, u, _ in before]  # the same rows, none lost
    assert all(session is None for _, u, session in after if u == a["uid"])  # no longer tied to a build that is gone
    assert [(i, session) for i, u, session in after if u == b["uid"]] == [(i, session) for i, u, session in before if u == b["uid"]]


def test_the_account_row_stays_and_the_person_is_still_turned_off_and_starts_empty_if_turned_on(ew):
    w = ew()
    ada = w.person(1)
    a = seed_person(w, 1)
    owner = w.owner()
    block(owner, a["uid"])
    assert erase(owner, a["uid"], "p1@example.com").status_code == 200
    person = {p["id"]: p for p in owner.get("/api/admin/people").json()["people"]}[a["uid"]]
    assert person["blocked"] is True and person["builds"] == 0 and person["disk_used"] == 0 and person["has_key"] is False
    assert ada.get("/api/library").status_code in (401, 403)  # still turned off
    assert owner.post(f"/api/admin/people/{a['uid']}/unblock").status_code == 200
    assert ada.get("/api/library").json() == [] and ada.get("/api/builds").json() == []


def test_a_person_who_is_not_turned_off_is_refused_and_nothing_is_touched(ew):
    w = ew()
    w.person(1)
    a = seed_person(w, 1)
    r = erase(w.owner(), a["uid"], "p1@example.com")
    assert r.status_code == 409 and "Turn this person off first" in r.json()["detail"] and str(w.tmp) not in r.text
    assert untouched(w, a)


@pytest.mark.parametrize("adder", [add_build, add_lab_run, add_suggest_run, add_scan_run])
def test_a_person_with_work_running_is_refused_and_nothing_is_touched(ew, adder):
    w = ew()
    w.person(1)
    a = seed_person(w, 1)
    owner = w.owner()
    block(owner, a["uid"])
    adder(w, a["uid"], "f" * 32)
    r = erase(owner, a["uid"], "p1@example.com")
    assert r.status_code == 409 and "work running" in r.json()["detail"]
    assert a["folder"].exists() and (w.libraries.users_root / a["uid"]).exists()


@pytest.mark.parametrize("confirm", [None, "", "p2@example.com", "a@b", "p1@example.co"])
def test_a_wrong_or_missing_confirmation_is_refused_and_nothing_is_touched(ew, confirm):
    w = ew()
    w.person(1)
    w.person(2)
    a = seed_person(w, 1)
    owner = w.owner()
    block(owner, a["uid"])
    r = erase(owner, a["uid"], confirm)
    assert r.status_code == 400 and "Type the person's address" in r.json()["detail"]
    assert untouched(w, a)


def test_a_request_with_no_body_at_all_is_refused_and_nothing_is_touched(ew):
    w = ew()
    w.person(1)
    a = seed_person(w, 1)
    owner = w.owner()
    block(owner, a["uid"])
    assert owner.post(f"/api/admin/people/{a['uid']}/erase").status_code == 422
    assert untouched(w, a)


def test_the_right_address_is_accepted_whatever_its_case_and_the_spaces_around_it(ew):
    w = ew()
    w.person(1)
    a = seed_person(w, 1)
    owner = w.owner()
    block(owner, a["uid"])
    assert erase(owner, a["uid"], "  P1@Example.COM ").status_code == 200


@pytest.mark.parametrize("who,status", [("local", 400), ("0" * 32, 404), ("zz", 404), ("a" * 31, 404), ("a" * 33, 404), ("A" * 32, 404)])
def test_the_owner_an_unknown_id_and_a_malformed_id_cannot_be_erased(ew, who, status):
    w = ew()
    w.person(1)
    a = seed_person(w, 1)
    r = erase(w.owner(), who, "p1@example.com")
    assert r.status_code == status and "owner cannot be erased" in r.text if who == "local" else r.status_code == status
    assert untouched(w, a)


def test_only_the_owner_may_erase_and_a_local_server_has_no_accounts(ew, tmp_path):
    w = ew()
    ada, bob = w.person(1), w.person(2)
    a = seed_person(w, 1)
    block(w.owner(), a["uid"])
    assert erase(ada, a["uid"], "p1@example.com").status_code in (401, 403)  # not even a turned-off person can erase themselves
    assert erase(bob, a["uid"], "p1@example.com").status_code == 403
    assert untouched(w, a)
    from fastapi.testclient import TestClient

    from skillforge.api import create_app
    from skillforge.library import Library

    local = TestClient(create_app(Library(tmp_path / "library")), base_url="http://localhost")
    assert erase(local, "a" * 32, "x@y.z").status_code == 400


def test_erasing_twice_is_harmless(ew):
    w = ew()
    w.person(1)
    a = seed_person(w, 1)
    owner = w.owner()
    block(owner, a["uid"])
    assert erase(owner, a["uid"], "p1@example.com").status_code == 200
    again = erase(owner, a["uid"], "p1@example.com")
    assert again.status_code == 200 and again.json() == {"erased": True, "builds": 0, "suggestion_runs": 0, "lab_runs": 0, "scan_runs": 0, "key_removed": False, "files_left": False}


def test_a_build_folder_that_cannot_be_removed_keeps_its_row_so_erasing_again_finishes_the_job(ew, monkeypatch):
    """The review's Important finding: the build ids came from rows that were already deleted, so a folder the disk would not give up was lost for good and a second
    erase said "Their files are gone" while private files remained. The row of such a build now stays, so the next erase finds the folder again."""
    w = ew()
    w.person(1)
    a = seed_person(w, 1)
    (a["folder"] / "secret.txt").write_text("private", encoding="utf-8")
    owner = w.owner()
    block(owner, a["uid"])
    real, calls = shutil.rmtree, []

    def flaky(path, *args, **kwargs):
        calls.append(str(path))
        if len(calls) == 1:  # the first removal is the build folder: the disk will not give it up this time
            return None
        return real(path, *args, **kwargs)

    monkeypatch.setattr(remove_module.shutil, "rmtree", flaky)
    first = erase(owner, a["uid"], "p1@example.com").json()
    assert first["files_left"] is True and first["builds"] == 0
    assert (a["folder"] / "secret.txt").exists() and counts(w, a["uid"])["builds"] == 1  # the row stays: it is how the folder is found again
    monkeypatch.undo()
    second = erase(owner, a["uid"], "p1@example.com").json()
    assert second["files_left"] is False and second["builds"] == 1
    assert not a["folder"].exists() and counts(w, a["uid"])["builds"] == 0
    assert counts(w, a["uid"])["usage"] == 3  # the usage rows were never touched, before or after


def test_a_folder_that_cannot_be_removed_is_reported_and_what_has_no_folder_is_still_erased(ew, monkeypatch):
    w = ew()
    w.person(1)
    a = seed_person(w, 1)
    owner = w.owner()
    block(owner, a["uid"])
    monkeypatch.setattr(remove_module.shutil, "rmtree", lambda *args, **kwargs: None)
    r = erase(owner, a["uid"], "p1@example.com")
    assert r.status_code == 200 and r.json()["files_left"] is True
    assert counts(w, a["uid"])["keys"] == 0 and counts(w, a["uid"])["suggestions"] == 0 and counts(w, a["uid"])["labs"] == 0 and counts(w, a["uid"])["scans"] == 0 and str(w.tmp) not in r.text
    assert counts(w, a["uid"])["builds"] == 1 and r.json()["builds"] == 0  # the build whose folder is still there keeps its row, so erasing again can find it


def test_a_link_inside_the_persons_folder_is_removed_as_a_link_and_never_followed(ew, tmp_path):
    w = ew()
    w.person(1)
    a = seed_person(w, 1)
    target = outside(tmp_path)
    make_link(a["lib"].root / "foo" / "v1" / "sneaky", target)
    owner = w.owner()
    block(owner, a["uid"])
    r = erase(owner, a["uid"], "p1@example.com")
    assert r.status_code == 200 and r.json()["files_left"] is False
    assert (target / "precious.txt").read_text(encoding="utf-8") == "keep me" and not (w.libraries.users_root / a["uid"]).exists()


def test_a_persons_folder_that_is_itself_a_link_is_left_alone_and_reported(ew, tmp_path):
    w = ew()
    w.person(1)
    a = seed_person(w, 1)
    target = outside(tmp_path)
    folder = w.libraries.users_root / a["uid"]
    shutil.rmtree(folder)
    make_link(folder, target)
    owner = w.owner()
    block(owner, a["uid"])
    r = erase(owner, a["uid"], "p1@example.com")
    assert r.status_code == 200 and r.json()["files_left"] is True
    assert (target / "precious.txt").read_text(encoding="utf-8") == "keep me" and counts(w, a["uid"])["builds"] == 0


def test_the_disk_number_on_the_people_page_is_not_stale_after_an_erase(ew):
    w = ew()
    w.person(1)
    a = seed_person(w, 1)
    assert w.builder.space.used_for_display(a["uid"]) > 0  # measured and remembered for a few seconds
    owner = w.owner()
    block(owner, a["uid"])
    assert erase(owner, a["uid"], "p1@example.com").status_code == 200
    assert w.builder.space.used_for_display(a["uid"]) == 0
