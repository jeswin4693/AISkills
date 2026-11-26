"""Slice AJ, task 2: per-person limits on a hosted server (docs/person-limits.md): disk, kept builds, background runs at the same time.

A person is limited, the owner never is, and one person's limit never touches another. Offline: a mock model, nothing real.
"""

from __future__ import annotations

import os
import subprocess
import threading

import pytest
from test_accounts_auth import env
from test_accounts_isolation import Parked, World, put_skill, start
from test_builder import FULL
from test_skill_build import round_one, round_two

from skillforge.api import create_app
from skillforge.api.hosted import Hosted, HostedConfigError
from skillforge.builder import Builder, JobRunner
from skillforge.builder.limits import LimitReached, PersonLimits
from skillforge.db import BuildSession, EvalRun, now_text

MB = 1024 * 1024


@pytest.fixture
def lw(tmp_path):
    """A hosted server with limits: lw(limits=PersonLimits(...), runner=Parked()) -> World."""
    made: list[World] = []

    def make(responses=None, **kw) -> World:
        folder = tmp_path / f"w{len(made)}"
        folder.mkdir()
        w = World(folder, responses or [round_two()] * 80, service=True, **kw)
        made.append(w)
        return w

    yield make
    for w in made:
        w.close()


def post_build(client):
    return client.post("/api/builds", json={"description": FULL})


def make_link(link, target) -> bool:
    """A symbolic link, or on Windows (where that needs special rights) a directory junction. False when neither can be made here."""
    try:
        link.symlink_to(target, target_is_directory=True)
        return True
    except OSError:
        pass
    if os.name == "nt":
        return subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True).returncode == 0
    return False


def fill(w: World, uid: str, size: int, name: str = "filler.bin") -> None:
    folder = w.libraries.for_user(uid).root
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(b"x" * size)


# ---- the settings -------------------------------------------------------------------------------------------------------------------------------


def test_the_limits_are_server_settings_with_safe_defaults_that_refuse_nonsense():
    default = Hosted.from_env(env()).person_limits
    assert (default.disk_bytes, default.max_builds, default.max_active) == (500 * MB, 50, 2)
    chosen = Hosted.from_env(env(SKILLFORGE_PERSON_DISK_MB="64", SKILLFORGE_PERSON_MAX_BUILDS="7", SKILLFORGE_PERSON_MAX_ACTIVE="1")).person_limits
    assert (chosen.disk_bytes, chosen.max_builds, chosen.max_active) == (64 * MB, 7, 1)
    none = Hosted.from_env(env(SKILLFORGE_PERSON_DISK_MB="0", SKILLFORGE_PERSON_MAX_BUILDS="0", SKILLFORGE_PERSON_MAX_ACTIVE="0")).person_limits
    assert none == PersonLimits() and not none.any
    for name in ("SKILLFORGE_PERSON_DISK_MB", "SKILLFORGE_PERSON_MAX_BUILDS", "SKILLFORGE_PERSON_MAX_ACTIVE"):
        for bad in ("-1", "abc", "1.5", "10000001"):
            with pytest.raises(HostedConfigError, match=name):
                Hosted.from_env(env(**{name: bad}))


# ---- kept builds --------------------------------------------------------------------------------------------------------------------------------


def test_a_person_at_the_build_cap_cannot_start_another_until_they_discard_one(lw):
    w = lw(limits=PersonLimits(max_builds=2))
    ada = w.person(1)
    first, second = start(ada), start(ada)
    refused = post_build(ada)
    assert refused.status_code == 429
    body = refused.json()
    assert body["limit"] == "builds" and "Discard" in body["detail"]
    assert ada.delete(f"/api/builds/{first}").status_code == 200
    assert post_build(ada).status_code == 201  # exactly one more
    assert post_build(ada).status_code == 429
    assert ada.get(f"/api/builds/{second}").status_code == 200  # nothing else was touched


def test_the_owner_is_never_limited(lw):
    w = lw(limits=PersonLimits(max_builds=1, max_active=1, disk_bytes=1))
    owner = w.owner()
    for _ in range(3):
        start(owner)


def test_one_persons_limit_does_not_use_up_anothers(lw):
    w = lw(limits=PersonLimits(max_builds=1))
    ada, bob = w.person(1), w.person(2)
    start(ada)
    assert post_build(ada).status_code == 429
    assert post_build(bob).status_code == 201


# ---- disk ---------------------------------------------------------------------------------------------------------------------------------------


def test_a_person_at_the_disk_cap_cannot_start_a_build(lw):
    w = lw(limits=PersonLimits(disk_bytes=1000))
    ada = w.person(1)
    assert post_build(ada).status_code == 201  # nothing used yet
    fill(w, w.uid(1), 2000)
    refused = post_build(ada)
    assert refused.status_code == 429 and refused.json()["limit"] == "disk" and "Discard" in refused.json()["detail"]


def test_a_persons_build_folders_count_toward_their_disk(lw):
    w = lw(limits=PersonLimits(disk_bytes=1000))
    ada = w.person(1)
    sid = start(ada)
    folder = w.builder.builds_root / sid
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "big.bin").write_bytes(b"x" * 3000)
    assert post_build(ada).status_code == 429
    assert ada.delete(f"/api/builds/{sid}").status_code == 200  # a discard removes the folder and so the bytes
    assert post_build(ada).status_code == 201


def test_one_persons_files_never_count_against_another(lw):
    w = lw(limits=PersonLimits(disk_bytes=1000))
    ada, bob = w.person(1), w.person(2)
    fill(w, w.uid(1), 5000)
    assert post_build(ada).status_code == 429
    assert post_build(bob).status_code == 201


def test_the_size_of_a_persons_folder_never_follows_a_link_out_of_it(lw, tmp_path):
    w = lw(limits=PersonLimits(disk_bytes=1000))
    ada = w.person(1)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "huge.bin").write_bytes(b"x" * 50_000)
    inside = w.libraries.for_user(w.uid(1)).root
    inside.mkdir(parents=True, exist_ok=True)
    if not make_link(inside / "link", outside):
        pytest.skip("this machine can make neither a symbolic link nor a junction")
    assert post_build(ada).status_code == 201  # the 50 KB it points at is not theirs


def test_an_upload_is_refused_at_the_disk_cap_before_it_is_read(lw):
    w = lw(limits=PersonLimits(disk_bytes=1000))
    ada = w.person(1)
    assert ada.post("/api/library/import", content=b"not a zip").status_code != 429  # under the cap: refused for being no zip, not for room
    fill(w, w.uid(1), 2000)
    refused = ada.post("/api/library/import", content=b"not a zip")
    assert refused.status_code == 429 and refused.json()["limit"] == "disk"


def test_saving_to_the_library_is_refused_at_the_disk_cap(lw):
    w = lw(limits=PersonLimits(disk_bytes=1000))
    ada = w.person(1)
    sid = start(ada)
    fill(w, w.uid(1), 2000)
    with pytest.raises(LimitReached) as caught:
        w.builder.save(sid, user=w.uid(1))
    assert caught.value.limit == "disk"


def test_the_other_library_writes_are_refused_at_the_disk_cap_too(lw):
    w = lw(limits=PersonLimits(disk_bytes=1000))
    ada = w.person(1)
    fill(w, w.uid(1), 2000)
    for path, body in (("/api/plugins", {"name": "x", "skills": [], "agents": []}), ("/api/library/some-skill/rollback", {"to": 1}),
                       ("/api/library/some-skill/tests", {"tests": []})):
        refused = ada.post(path, json=body)
        assert refused.status_code == 429 and refused.json()["limit"] == "disk", path


# ---- runs working at the same time --------------------------------------------------------------------------------------------------------------


def test_a_person_cannot_have_more_runs_working_than_the_cap_and_a_finished_one_frees_a_place(lw):
    runner = Parked()
    w = lw(runner=runner, limits=PersonLimits(max_active=2))
    ada, bob = w.person(1), w.person(2)
    start(ada)
    start(ada)
    refused = post_build(ada)
    assert refused.status_code == 429 and refused.json()["limit"] == "active"
    assert post_build(bob).status_code == 201  # not Bob's problem
    for fn, args in list(runner.jobs):  # the held work finishes
        fn(*args)
    assert post_build(ada).status_code == 201


def test_a_person_at_the_active_cap_cannot_answer_approve_or_retry_either(lw):
    runner = Parked()
    w = lw(runner=runner, limits=PersonLimits(max_active=1))
    ada = w.person(1)
    waiting = start(ada)
    for fn, args in list(runner.jobs):  # the first build runs its understanding step and now waits for approval or answers
        fn(*args)
    runner.jobs.clear()
    assert ada.get(f"/api/builds/{waiting}").json()["status"] in ("awaiting_approval", "awaiting_answers")
    other = start(ada)  # takes the one place
    assert ada.get(f"/api/builds/{other}").json()["status"] == "working"
    status = ada.get(f"/api/builds/{waiting}").json()["status"]
    blocked = ada.post(f"/api/builds/{waiting}/approve") if status == "awaiting_approval" else ada.post(f"/api/builds/{waiting}/answers", json={"answers": {}})
    assert blocked.status_code == 429 and blocked.json()["limit"] == "active"


def test_starts_at_the_same_instant_cannot_all_take_the_last_places(lw):
    w = lw(runner=Parked(), limits=PersonLimits(max_active=2, max_builds=0))
    w.person(1)
    uid = w.uid(1)
    outcomes: list[str] = []
    gate = threading.Barrier(8)

    def go():
        gate.wait()
        try:
            w.builder.start(FULL, user=uid)
            outcomes.append("ok")
        except LimitReached:
            outcomes.append("refused")

    threads = [threading.Thread(target=go) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert outcomes.count("ok") == 2 and outcomes.count("refused") == 6


def test_a_working_testing_lab_run_counts_toward_the_active_cap(lw):
    w = lw(runner=Parked(), limits=PersonLimits(max_active=1))
    ada = w.person(1)
    uid = w.uid(1)
    put_skill(w, uid)
    stamp = now_text()
    with w.db.session() as s:
        s.add(EvalRun(id="e" * 32, created_at=stamp, updated_at=stamp, status="working", kind="skill", name="other-skill", version=1, content_hash="h", runs=1,
                      baseline=True, cases_total=1, cases_done=0, result=None, error="", retryable=False, user_id=uid))
    assert post_build(ada).status_code == 429  # a Lab run is working, so there is no place for a build
    refused = ada.post("/api/evals", json={"name": "commit-writer"})
    assert refused.status_code == 429 and refused.json()["limit"] == "active"


def test_a_second_click_on_the_same_lab_run_still_gets_that_run_and_is_not_a_new_one(lw):
    w = lw(runner=Parked(), limits=PersonLimits(max_active=1))
    ada = w.person(1)
    put_skill(w, w.uid(1))
    first = ada.post("/api/evals", json={"name": "commit-writer"})
    again = ada.post("/api/evals", json={"name": "commit-writer"})
    assert first.status_code == 201 and again.status_code == 201 and again.json()["id"] == first.json()["id"]


# ---- what a person can see ----------------------------------------------------------------------------------------------------------------------


def test_a_person_sees_only_their_own_space_and_the_owner_is_told_there_are_no_limits(lw):
    w = lw(limits=PersonLimits(disk_bytes=10 * MB, max_builds=5, max_active=2))
    ada, bob = w.person(1), w.person(2)
    start(ada)
    start(ada)
    fill(w, w.uid(1), 2000)
    mine = ada.get("/api/me/space").json()
    assert mine["mode"] == "person" and mine["builds"] == {"kept": 2, "limit": 5} and mine["active"]["limit"] == 2
    assert mine["disk"]["limit"] == 10 * MB and mine["disk"]["used"] >= 2000
    theirs = bob.get("/api/me/space").json()
    assert theirs["builds"]["kept"] == 0 and theirs["disk"]["used"] == 0
    assert w.owner().get("/api/me/space").json()["mode"] == "owner"


def test_a_limit_of_zero_means_none_and_is_shown_that_way(lw):
    w = lw(limits=PersonLimits())
    ada = w.person(1)
    start(ada)
    shown = ada.get("/api/me/space").json()
    assert shown["builds"]["limit"] == 0 and shown["disk"]["limit"] == 0 and shown["active"]["limit"] == 0


# ---- the real `serve` command gives a hosted server its limits (the lesson of the model options) -------------------------------------------------


def test_a_server_started_by_the_serve_command_has_the_limits_its_settings_say(monkeypatch, tmp_path):
    from test_model_review import HOSTED, run_serve

    app = run_serve(monkeypatch, tmp_path, SKILLFORGE_PERSON_MAX_BUILDS="3", SKILLFORGE_PERSON_DISK_MB="9", **HOSTED)
    try:
        limits = app.state.builder.space.limits
        assert (limits.max_builds, limits.disk_bytes) == (3, 9 * MB)
    finally:
        app.state.builder.close()


def test_a_local_serve_has_no_limits(monkeypatch, tmp_path):
    from test_model_review import run_serve

    app = run_serve(monkeypatch, tmp_path)
    try:
        assert not app.state.builder.space.limits.any
    finally:
        app.state.builder.close()


def test_a_builder_made_with_no_limits_asks_nothing_of_anyone(tmp_path):
    from skillforge.db import Database
    from skillforge.library import Library

    db = Database(f"sqlite:///{(tmp_path / 'n.db').as_posix()}")
    db.migrate()
    builder = Builder(db, Library(tmp_path / "library"), tmp_path / "builds", runner=JobRunner(inline=True))
    try:
        builder.space.admit("0" * 32, new_build=True)  # no limits: nothing to refuse, and no such person needed
    finally:
        db.close()


def test_the_app_does_not_open_the_database_for_a_local_library_upload(tmp_path):
    from fastapi.testclient import TestClient

    from skillforge.library import Library

    app = create_app(Library(tmp_path / "library"))
    client = TestClient(app, base_url="http://localhost")
    refused = client.post("/api/library/import", content=b"not a zip")
    assert refused.status_code in (400, 422)  # refused for being no zip: the route ran, and no limit came into it
    assert app.state.builder is None  # a server used only for the library still never opens the database



# ---- found by the deliberate breaks: the edges and the paths the first tests did not walk -------------------------------------------------------


def test_a_person_exactly_at_the_disk_cap_is_refused_and_one_byte_under_is_not(lw):
    w = lw(limits=PersonLimits(disk_bytes=1000))
    ada = w.person(1)
    fill(w, w.uid(1), 999)
    assert post_build(ada).status_code == 201  # 999 of 1000: room
    fill(w, w.uid(1), 1000)
    refused = post_build(ada)
    assert refused.status_code == 429 and refused.json()["limit"] == "disk"  # 1000 of 1000: full


def test_a_person_at_the_active_cap_cannot_answer_a_question_either(lw):
    runner = Parked()
    w = lw(responses=[round_one()] * 40, runner=runner, limits=PersonLimits(max_active=1))
    ada = w.person(1)
    asking = start(ada)
    for fn, args in list(runner.jobs):  # the first build reads the words and now waits for answers
        fn(*args)
    runner.jobs.clear()
    session = ada.get(f"/api/builds/{asking}").json()
    assert session["status"] == "awaiting_answers" and session["questions"]
    start(ada)  # takes the one place and stays working
    answers = {q["slot"]: "It must never edit any file, and it stops when the input is empty." for q in session["questions"]}
    blocked = ada.post(f"/api/builds/{asking}/answers", json={"answers": answers})
    assert blocked.status_code == 429 and blocked.json()["limit"] == "active"
    assert ada.get(f"/api/builds/{asking}").json()["status"] == "awaiting_answers"  # nothing moved


def test_a_person_at_the_active_cap_cannot_retry_a_failed_build(lw):
    runner = Parked()
    w = lw(runner=runner, limits=PersonLimits(max_active=1))
    ada = w.person(1)
    failed = start(ada)
    for fn, args in list(runner.jobs):
        fn(*args)
    runner.jobs.clear()
    with w.db.session() as s:  # a step that failed for a reason that can pass (a busy model, say)
        row = s.get(BuildSession, failed)
        row.status, row.retryable, row.error = "failed", True, "The model was busy."
    start(ada)  # takes the one place
    blocked = ada.post(f"/api/builds/{failed}/retry")
    assert blocked.status_code == 429 and blocked.json()["limit"] == "active"
    assert ada.get(f"/api/builds/{failed}").json()["status"] == "failed"  # still failed: nothing was claimed


def failed_lab_run(w: World, uid: str, rid: str = "f" * 32) -> str:
    stamp = now_text()
    with w.db.session() as s:
        s.add(EvalRun(id=rid, created_at=stamp, updated_at=stamp, status="failed", kind="skill", name="commit-writer", version=1, content_hash="h", runs=1,
                      baseline=True, cases_total=1, cases_done=0, result=None, error="The model was busy.", retryable=True, user_id=uid))
    return rid


def test_a_person_at_the_active_cap_cannot_retry_a_failed_lab_run(lw):
    w = lw(runner=Parked(), limits=PersonLimits(max_active=1))
    ada = w.person(1)
    rid = failed_lab_run(w, w.uid(1))
    start(ada)  # a build takes the one place
    blocked = ada.post(f"/api/evals/{rid}/retry")
    assert blocked.status_code == 429 and blocked.json()["limit"] == "active"
    assert ada.get(f"/api/evals/{rid}").json()["status"] == "failed"
    assert w.owner().get("/api/me/space").json()["mode"] == "owner"  # (the owner is never held up by any of this)


def test_a_failed_lab_run_can_be_retried_when_there_is_a_place(lw):
    w = lw(runner=Parked(), limits=PersonLimits(max_active=1))
    ada = w.person(1)
    rid = failed_lab_run(w, w.uid(1))
    again = ada.post(f"/api/evals/{rid}/retry")
    assert again.status_code in (200, 201) and again.json()["status"] == "working"


def test_a_person_at_the_disk_cap_can_still_run_the_tests_of_what_they_have(lw):
    w = lw(runner=Parked(), limits=PersonLimits(disk_bytes=1000))
    ada = w.person(1)
    put_skill(w, w.uid(1))
    fill(w, w.uid(1), 5000)
    assert post_build(ada).status_code == 429  # full: no new build
    started = ada.post("/api/evals", json={"name": "commit-writer"})
    assert started.status_code == 201  # but a test run writes next to nothing, so it is allowed
