"""The behaviour scan over HTTP (slice AK, task 5): `/api/scans`.

The bookkeeping is tested in test_scan_runs.py; here is the HTTP surface: the routes, the bounds on what a person may ask for, and that one person's runs are invisible to another.
"""

from __future__ import annotations

import pytest
from test_accounts_isolation import MISSING, World, world  # noqa: F401  (world is a pytest fixture)
from test_canary_runner import SKILL, Agent, clean, exfiltrate
from test_scan_runs import NAME, put

from skillforge.builder.scans import DEFAULT_SCENARIOS, RUN_CAP, SCENARIO_CAP


def scan_world(world, policy=clean, **kw) -> World:
    w = world(Agent(policy), service=True, **kw)
    w.person(1)
    w.person(2)
    put(w.libraries.for_user(w.uid(1)))
    return w


def start(client, **body):
    return client.post("/api/scans", json={"name": NAME, "draft": False, **body})


def test_a_person_previews_starts_reads_lists_and_cannot_retry_a_finished_scan(world):
    w = scan_world(world)
    ada = w.person(1)
    preview = ada.get("/api/scans/preview", params={"name": NAME})
    assert preview.status_code == 200, preview.text  # the static path is not read as a run id
    p = preview.json()
    assert (p["name"], p["tag"], len(p["tasks"]), p["max_calls"]) == (NAME, "v1", DEFAULT_SCENARIOS, DEFAULT_SCENARIOS * 6 * 2 + 1)
    started = start(ada)
    assert started.status_code == 201, started.text
    run = started.json()
    assert run["status"] == "done" and run["result"]["outcome"] == "nothing_observed" and str(w.tmp) not in started.text
    assert ada.get(f"/api/scans/{run['id']}").json()["status"] == "done"
    listed = ada.get("/api/scans", params={"name": NAME}).json()
    assert [r["id"] for r in listed] == [run["id"]] and "result" not in listed[0] and listed[0]["summary"]["outcome"] == "nothing_observed"
    assert ada.get("/api/scans", params={"name": "other-name"}).json() == [] and ada.get("/api/scans", params={"version": 2}).json() == []
    assert ada.post(f"/api/scans/{run['id']}/retry").status_code == 409


def test_a_flagged_scan_carries_its_findings_over_http(world):
    w = scan_world(world, exfiltrate)
    run = start(w.person(1)).json()
    assert run["result"]["outcome"] == "flagged" and "likely cause" in run["result"]["verdict"]


def test_the_owner_scans_the_owners_library(world):
    w = scan_world(world)
    put(w.library)
    owner = w.owner()
    run = start(owner)
    assert run.status_code == 201 and run.json()["status"] == "done" and owner.get("/api/scans").json()[0]["id"] == run.json()["id"]
    assert w.person(1).get("/api/scans").json() == []  # the owner's run is not a person's


def test_another_person_sees_nothing_and_every_answer_is_the_one_for_something_that_never_existed(world):
    w = scan_world(world)
    ada, bob = w.person(1), w.person(2)
    rid = start(ada).json()["id"]
    for method, path in (("GET", f"/api/scans/{rid}"), ("POST", f"/api/scans/{rid}/retry")):
        seen = bob.request(method, path)
        never = bob.request(method, path.replace(rid, MISSING))
        assert seen.status_code == never.status_code == 404 and seen.json() == never.json()
    assert bob.get("/api/scans").json() == [] and bob.get(f"/api/scans/{rid}").status_code == 404
    seen_entry = bob.get("/api/scans/preview", params={"name": NAME})
    never_entry = bob.get("/api/scans/preview", params={"name": "nothing-here"})
    assert seen_entry.status_code == never_entry.status_code == 404
    assert seen_entry.json()["detail"].replace(NAME, "x") == never_entry.json()["detail"].replace("nothing-here", "x")
    assert start(bob).status_code == 404  # Bob has no such entry to scan
    assert [r["id"] for r in ada.get("/api/scans").json()] == [rid]


def test_a_run_id_that_is_not_an_id_is_the_same_404(world):
    w = scan_world(world)
    ada = w.person(1)
    assert ada.get("/api/scans/not-an-id").status_code == 404 and ada.get(f"/api/scans/{MISSING}").status_code == 404


@pytest.mark.parametrize("body", [{"runs": 0}, {"runs": RUN_CAP + 1}, {"scenarios": 0}, {"scenarios": SCENARIO_CAP + 1}, {"runs": "many"}, {"version": 0}, {"name": "x" * 65}])
def test_numbers_and_text_out_of_bounds_are_a_422_and_start_nothing(world, body):
    w = scan_world(world)
    ada = w.person(1)
    assert start(ada, **body).status_code == 422
    assert ada.get("/api/scans").json() == []


@pytest.mark.parametrize("params", [{"runs": 0}, {"runs": RUN_CAP + 1}, {"scenarios": 0}, {"scenarios": SCENARIO_CAP + 1}])
def test_the_preview_has_the_same_bounds(world, params):
    w = scan_world(world)
    assert w.person(1).get("/api/scans/preview", params={"name": NAME, **params}).status_code == 422


def test_the_options_reach_the_run_and_the_preview(world):
    w = scan_world(world)
    ada = w.person(1)
    p = ada.get("/api/scans/preview", params={"name": NAME, "runs": 2, "scenarios": 3, "control": "false", "draft": "false"}).json()
    assert len(p["tasks"]) == 3 and p["max_calls"] == 3 * 2 * 6
    run = start(ada, runs=2, scenarios=3, control=False).json()
    assert (run["runs"], run["scenarios"], run["control"], run["progress"]["total"]) == (2, 3, False, 6)


def test_a_plugin_an_unknown_kind_and_a_missing_version_are_refused_with_a_reason(world):
    w = scan_world(world)
    ada = w.person(1)
    assert ada.get("/api/scans/preview", params={"name": NAME, "kind": "plugin"}).status_code == 400
    assert ada.get("/api/scans/preview", params={"name": NAME, "kind": "nope"}).status_code == 400
    assert start(ada, kind="plugin").status_code == 400
    assert ada.get("/api/scans/preview", params={"name": NAME, "version": 9}).status_code == 404
    assert ada.get("/api/scans/preview", params={"name": "Bad_Name"}).status_code == 400


def test_a_signed_out_request_is_refused(world):
    w = scan_world(world)
    stranger = w.person_client()
    assert stranger.get("/api/scans").status_code == 401 and stranger.post("/api/scans", json={"name": NAME}).status_code == 401
    assert stranger.get("/api/scans/preview", params={"name": NAME}).status_code == 401


def test_the_skill_text_in_the_preview_answer_is_only_what_the_engine_reports(world):
    w = scan_world(world)
    p = w.person(1).get("/api/scans/preview", params={"name": NAME}).json()
    assert SKILL.split("---")[2].strip() not in str(p)  # the skill's own body is not sent to the page: the tasks, what it declares and its scripts are
