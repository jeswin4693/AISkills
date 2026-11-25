"""Slice AD: the Testing Lab over HTTP. A preview of what would run, then a run that is kept in the database and polled, always about one version
of one skill. Offline: a scripted model and inline jobs (or a runner that holds the work, to look at a run while it is still working)."""

from __future__ import annotations

import json

import pytest
from test_builder import make  # noqa: F401  (make is a pytest fixture)
from test_evaluate import CASES, SKILL_MD, a, case, replier

from skillforge.evaluate.runner import Reply
from skillforge.providers import ProviderError


def put_skill(env, name="commit-writer", tests=CASES, perms=(), scripts=False, skill_md=SKILL_MD):
    """Keep a skill in the test library the way a build would: its text, its cases, and (when asked) permissions or a script."""
    files = {"SKILL.md": skill_md.encode(), "tests/cases.json": json.dumps([t.model_dump() for t in tests]).encode()}
    if perms:
        files["skill.sdm.json"] = json.dumps({"permissions": list(perms)}).encode()
    if scripts:
        files["scripts/x.py"] = b"print(1)\n"
    version, _ = env.library.add(name, files, source_kind="folder", source_label="test")
    return version


class Parked:
    """A job runner that holds the work instead of doing it, so a run can be looked at while it is still 'working'."""

    inline = False

    def __init__(self):
        self.jobs = []

    def submit(self, fn, *args):
        self.jobs.append((fn, args))

    def shutdown(self):
        pass

    def run_all(self):
        while self.jobs:
            fn, args = self.jobs.pop(0)
            fn(*args)


def start(env, name="commit-writer", **body):
    return env.client.post("/api/evals", json={"name": name, **body})


# ---- the preview: what would run, before anything is asked of a model -------------------------------------------


def test_the_preview_lists_what_would_run_and_asks_no_model(make):
    env = make(replier())
    version = put_skill(env)
    r = env.client.get("/api/evals/preview", params={"name": "commit-writer"})
    doc = r.json()
    assert r.status_code == 200 and env.mock.calls == []
    assert doc["runnable"] is True and doc["blocker"] == "" and doc["reason"] == "" and doc["version"] == 1 and doc["tag"] == "v1"
    assert doc["content_hash"] == version.content_hash and doc["skill_tokens"] > 0
    assert [c["name"] for c in doc["cases"]] == ["short change", "no description", "many changes"]
    first = doc["cases"][0]
    assert first["kind"] == "positive" and first["message"] == "fixed the login button alignment on mobile"
    assert first["checks"] == [
        {"kind": "first_line_max_chars", "value": "50", "why": "rule"}, {"kind": "regex", "value": r"^[A-Z][a-z]+ ", "why": "rule"},
    ]
    assert doc["calls"] == {"per_run": 3, "per_run_with_baseline": 6} and doc["limits"]["max_runs"] == 5


@pytest.mark.parametrize("kw, blocker, words", [
    ({"perms": ["read_files"]}, "needs_tools", "needs tools (it asks for read_files)"),
    ({"scripts": True}, "needs_tools", "it has scripts"),
    ({"tests": []}, "no_cases", "no test cases"),
    ({"tests": [case("old", "positive", "", a("contains", "x")), case("unchecked", "edge", "hi")]}, "nothing_runnable", "none of its 2 test case(s)"),
])
def test_a_skill_that_cannot_be_run_says_why_with_a_code_for_the_page(make, kw, blocker, words):
    env = make(replier())
    put_skill(env, **kw)
    doc = env.client.get("/api/evals/preview", params={"name": "commit-writer"}).json()
    assert doc["runnable"] is False and doc["blocker"] == blocker and words in doc["reason"] and doc["cases"] == [] and env.mock.calls == []


def test_the_preview_names_the_cases_it_will_skip_and_the_ones_cut_by_the_cap(make):
    env = make(replier())
    put_skill(env, tests=[case("blank", "edge", "", a("contains", "x")), *CASES * 5])  # 15 that could run, one that cannot
    doc = env.client.get("/api/evals/preview", params={"name": "commit-writer"}).json()
    assert len(doc["cases"]) == 12 and doc["calls"] == {"per_run": 12, "per_run_with_baseline": 24}
    assert doc["skipped"][0].startswith("blank: it has no message") and sum("only the first 12 cases are run" in s for s in doc["skipped"]) == 3


def test_the_preview_picks_a_version_and_refuses_unknown_things_in_plain_words(make):
    env = make(replier())
    put_skill(env)
    put_skill(env, tests=CASES[:2])  # v2, with two cases
    assert env.client.get("/api/evals/preview", params={"name": "commit-writer"}).json()["version"] == 2
    assert len(env.client.get("/api/evals/preview", params={"name": "commit-writer", "version": 1}).json()["cases"]) == 3
    assert env.client.get("/api/evals/preview", params={"name": "commit-writer", "version": 9}).status_code == 404
    assert env.client.get("/api/evals/preview", params={"name": "nothing-here"}).status_code == 404
    r = env.client.get("/api/evals/preview", params={"name": "commit-writer", "kind": "agent"})
    assert r.status_code == 400 and "Only skills" in r.json()["detail"]
    assert env.client.get("/api/evals/preview", params={"name": "commit-writer", "kind": "nonsense"}).status_code == 400


def test_a_version_changed_on_disk_is_refused_not_tested(make):
    env = make(replier())
    put_skill(env)
    (env.library.root / "commit-writer" / "v1" / "skill" / "SKILL.md").write_text("tampered", encoding="utf-8")
    r = env.client.get("/api/evals/preview", params={"name": "commit-writer"})
    assert r.status_code == 400 and "was changed after import" in r.json()["detail"]
    assert start(env).status_code == 400 and env.mock.calls == []


# ---- a run: kept, polled, and always about one version ------------------------------------------------------------


def test_a_run_is_kept_with_the_comparison_per_case_and_each_failed_check_in_words(make):
    env = make(replier())
    version = put_skill(env)
    r = start(env)
    run = r.json()
    assert r.status_code == 201 and len(env.mock.calls) == 6
    assert (run["status"], run["name"], run["version"], run["tag"], run["kind"]) == ("done", "commit-writer", 1, "v1", "skill")
    assert run["content_hash"] == version.content_hash and run["progress"] == {"done": 3, "total": 3} and run["error"] == ""
    res = run["result"]
    assert res["outcome"] == "helped" and res["with_skill"] == {"passed": 3, "total": 3} and res["baseline"] == {"passed": 1, "total": 3}
    assert res["calls"] == 6 and res["runs"] == 1 and res["verdict"].startswith("The skill helped:") and "Passing is evidence, not proof" in res["limits"]
    assert res["min_cases"] == 3  # how many cases it takes to say anything: the page never guesses the number
    first = res["cases"][0]
    assert first["name"] == "short change" and first["kind"] == "positive" and first["message"] == "fixed the login button alignment on mobile"
    assert first["with_skill"]["passed"] == 1 and first["with_skill"]["runs"] == 1
    base = first["baseline"]["tries"][0]
    assert base["passed"] is False and base["reply"].startswith("Here is a commit message you could use")
    failed = [c for c in base["checks"] if not c["passed"]]
    assert failed and failed[0]["kind"] == "first_line_max_chars" and failed[0]["detail"].startswith("the first line is")
    assert first["with_skill"]["tries"][0]["checks"][0]["passed"] is True


def test_it_survives_a_reload_and_is_listed_newest_first_without_the_heavy_result(make):
    env = make(replier())
    put_skill(env)
    first = start(env).json()
    second = start(env, baseline=False).json()
    assert first["id"] != second["id"]
    assert env.client.get(f"/api/evals/{first['id']}").json()["result"]["outcome"] == "helped"
    rows = env.client.get("/api/evals", params={"name": "commit-writer"}).json()
    assert [r["id"] for r in rows] == [second["id"], first["id"]] and all("result" not in r for r in rows)
    assert rows[0]["summary"] == {"outcome": "with_only", "with_skill": {"passed": 3, "total": 3}, "baseline": None, "calls": 3}
    assert rows[1]["summary"]["outcome"] == "helped" and rows[1]["summary"]["baseline"] == {"passed": 1, "total": 3}


def test_the_list_can_be_narrowed_to_one_version_and_one_skill(make):
    env = make(replier())
    put_skill(env)
    put_skill(env, tests=CASES + [case("another", "edge", "fixed the login again", a("max_lines", "5"))])  # v2
    put_skill(env, name="other-skill")
    start(env, version=1)
    start(env, version=2)
    start(env, name="other-skill")
    assert len(env.client.get("/api/evals").json()) == 3
    assert [r["version"] for r in env.client.get("/api/evals", params={"name": "commit-writer"}).json()] == [2, 1]
    assert [r["version"] for r in env.client.get("/api/evals", params={"name": "commit-writer", "version": 1}).json()] == [1]


def test_repeats_and_the_comparison_choice_change_how_many_calls_are_made(make):
    env = make(replier())
    put_skill(env)
    run = start(env, runs=3).json()
    assert run["runs"] == 3 and run["result"]["calls"] == 18 and len(env.mock.calls) == 18
    env.mock.calls.clear()
    only = start(env, baseline=False).json()
    assert only["baseline"] is False and only["result"]["calls"] == 3 and only["result"]["outcome"] == "with_only"


@pytest.mark.parametrize("body", [{"runs": 0}, {"runs": 6}, {"runs": "many"}, {"version": 0}, {"name": "x" * 65}])
def test_the_amount_of_work_is_bounded_before_any_model_is_asked(make, body):
    env = make(replier())
    put_skill(env)
    assert start(env, **body).status_code == 422 and env.mock.calls == []


def test_a_skill_that_cannot_be_run_is_refused_with_its_reason_and_nothing_is_stored_or_asked(make):
    env = make(replier())
    put_skill(env, perms=["network"])
    r = start(env)
    assert r.status_code == 400 and "needs tools (it asks for network)" in r.json()["detail"]
    assert env.mock.calls == [] and env.client.get("/api/evals").json() == []
    assert start(env, name="nothing-here").status_code == 404


def test_a_second_click_while_a_run_is_working_gets_that_run_not_another(make):
    env = make(replier())
    put_skill(env)
    parked = env.builder.runner = Parked()
    first = start(env).json()
    again = start(env, runs=3, baseline=False).json()
    assert first["status"] == "working" and again["id"] == first["id"] and first["progress"] == {"done": 0, "total": 3}
    assert len(parked.jobs) == 1 and env.mock.calls == []
    parked.run_all()
    done = env.client.get(f"/api/evals/{first['id']}").json()
    assert done["status"] == "done" and done["runs"] == 1  # the second click's choices did not change the run that was already going
    assert start(env).json()["id"] != first["id"]  # once it is finished, a click starts a new one


def test_progress_is_visible_while_the_model_is_still_being_asked(make):
    seen = []

    def respond(schema, prompt, system):
        rows = env.builder.evals.list()
        seen.append((rows[0]["status"], rows[0]["progress"]))
        return replier()(schema, prompt, system)

    env = make(respond)
    put_skill(env)
    start(env)
    assert seen[0] == ("working", {"done": 0, "total": 3}) and ("working", {"done": 1, "total": 3}) in seen and ("working", {"done": 2, "total": 3}) in seen


def test_a_run_stays_about_the_version_it_tested_when_a_newer_one_arrives(make):
    env = make(replier())
    v1 = put_skill(env)
    run = start(env).json()
    v2 = put_skill(env, tests=CASES[:2])
    kept = env.client.get(f"/api/evals/{run['id']}").json()
    assert kept["version"] == 1 and kept["content_hash"] == v1.content_hash != v2.content_hash and kept["result"]["outcome"] == "helped"


# ---- when it goes wrong -------------------------------------------------------------------------------------------


def test_a_model_that_cannot_be_reached_fails_the_run_and_it_can_be_run_again(make):
    answers = {"fail": True}

    def respond(schema, prompt, system):
        if answers["fail"]:
            raise ProviderError("the model is busy", retryable=True)
        return replier()(schema, prompt, system)

    env = make(respond)
    put_skill(env)
    run = start(env).json()
    assert run["status"] == "failed" and run["retryable"] is True and "the model is busy" in run["error"] and run["result"] is None
    answers["fail"] = False
    again = env.client.post(f"/api/evals/{run['id']}/retry").json()
    assert again["id"] == run["id"] and again["status"] == "done" and again["error"] == "" and again["result"]["outcome"] == "helped"


def test_no_model_set_up_is_a_failed_run_that_can_be_retried_never_a_crash(make):
    env = make(replier())
    put_skill(env)

    def no_model():
        raise ProviderError("No model is set up.", retryable=True)

    env.builder.provider_factory = no_model
    run = start(env).json()
    assert run["status"] == "failed" and run["retryable"] is True and "No model is set up." in run["error"]


def test_an_unexpected_error_is_named_by_type_only_and_never_repeats_its_text(make):
    def respond(schema, prompt, system):
        raise RuntimeError("secret text from C:\\Users\\someone\\file")

    env = make(respond)
    put_skill(env)
    run = start(env).json()
    assert run["status"] == "failed" and "RuntimeError" in run["error"] and "secret" not in run["error"] and "Users" not in run["error"]
    assert run["retryable"] is False


def test_only_a_failed_run_can_be_run_again_and_unknown_runs_are_not_found(make):
    env = make(replier())
    put_skill(env)
    run = start(env).json()
    assert env.client.post(f"/api/evals/{run['id']}/retry").status_code == 409
    for rid in ("0" * 32, "nonsense", "..%2Fetc"):
        assert env.client.get(f"/api/evals/{rid}").status_code == 404
    assert env.client.post(f"/api/evals/{'0' * 32}/retry").status_code == 404


def test_a_restart_marks_a_run_that_was_working_as_failed_and_retryable(make):
    env = make(replier())
    put_skill(env)
    parked = env.builder.runner = Parked()
    run = start(env).json()
    assert run["status"] == "working"
    env.db.recover_interrupted()
    after = env.client.get(f"/api/evals/{run['id']}").json()
    assert after["status"] == "failed" and after["retryable"] is True and "server stopped" in after["error"]
    parked.jobs.clear()
    assert env.client.post(f"/api/evals/{run['id']}/retry").json()["status"] == "working"


def test_a_long_reply_is_kept_cut_and_marked_so_the_page_never_holds_a_book(make):
    env = make(lambda schema, prompt, system: Reply(text="Fix login " + "word " * 2000))
    put_skill(env)
    run = start(env, baseline=False).json()
    reply = run["result"]["cases"][0]["with_skill"]["tries"][0]
    assert reply["cut"] is True and 3000 <= len(reply["reply"]) <= 3100 and reply["reply"].startswith("Fix login")
    short = make(replier())
    put_skill(short)
    assert start(short, baseline=False).json()["result"]["cases"][0]["with_skill"]["tries"][0]["cut"] is False


def test_a_very_long_message_is_cut_in_the_result_and_in_the_preview(make):
    long_message = "fixed the login " + "x" * 5000
    env = make(lambda schema, prompt, system: Reply(text="Fix it. What changed?"))
    put_skill(env, tests=[case(f"long{i}", "edge", long_message, a("contains", "fix")) for i in range(3)])
    shown = start(env, baseline=False).json()["result"]["cases"][0]["message"]
    assert shown.startswith("fixed the login") and len(shown) <= 2100
    preview = env.client.get("/api/evals/preview", params={"name": "commit-writer"}).json()["cases"][0]["message"]
    assert len(preview) <= 2100
