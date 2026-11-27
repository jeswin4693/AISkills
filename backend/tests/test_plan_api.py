"""Slice AM: the Task Plan over HTTP. The command line's plan (step C1) behind one route: a task, optionally a repository (a folder or a public GitHub
link), a model that may read the request or not. Offline: a mock model, small repositories in a temp folder, the page's fake download."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from test_builder import make  # noqa: F401  (a pytest fixture)
from test_conductor import SMALL, q, reading
from test_github_link import LINK, managed_path_leaks, served  # noqa: F401  (served is a pytest fixture: the archive GitHub 'serves')
from test_hosted import TOKEN, hosted

from skillforge.api import create_app
from skillforge.conductor import process, render_markdown
from skillforge.conductor.models import GapAsked, RuleRef, RuleSelection, TaskPlan
from skillforge.db import Database
from skillforge.providers import MockProvider, ProviderError

TASK = "Add a --json option to parse_config in src/util.py. Do not change any other command."


def model_answers():
    """What a model says about TASK: the reading, then which rule of CLAUDE.md applies."""
    return [
        reading(
            summary="Add a JSON option.", stated=[q("Add a --json option", "Add a --json option to parse_config")],
            out_of_scope=[q("no other commands", "Do not change any other command.")], named_targets=["parse_config"],
            gaps=[GapAsked(question="What should the JSON look like?", why="Without it the output cannot be tested.", blocking=True)],
        ),
        RuleSelection(applicable=[RuleRef(id="R1", why="The option must not print a secret.")]),
    ]


@pytest.fixture
def root(repo):
    return repo(SMALL)


def leaks(root, doc) -> bool:
    """Whether the folder the repository sits in (a person's own path) appears in a response, compared as JSON text so backslashes are not missed."""
    return json.dumps(str(root.parent))[1:-1] in json.dumps(doc)


def plan(env, root=None, **body):
    payload = {"task": TASK, **({"repo": str(root)} if root is not None else {}), **body}
    return env.client.post("/api/plan", json=payload)


def broken(message="No AI model is set up. Put its settings in the .env file."):
    def factory():
        raise ProviderError(message)

    return factory


def tree(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


# ---- a plan with a model -------------------------------------------------------------------------------------


def test_a_plan_with_a_model_says_what_the_request_contains_and_what_it_does_not_say(make, root):
    env = make(model_answers())
    r = plan(env, root)
    doc = r.json()
    assert r.status_code == 200 and doc["mode"] == "model" and doc["model_calls"] == 2 and doc["repo"] == root.name
    assert [(s["text"], s["quote"]) for s in doc["reading"]["stated"]] == [("Add a --json option", "Add a --json option to parse_config")]
    assert [s["quote"] for s in doc["reading"]["out_of_scope"]] == ["Do not change any other command."]
    assert doc["reading"]["gaps"][0]["blocking"] is True and doc["reading"]["gaps"][0]["source"] == "model"
    assert [(x["id"], x["source"], x["enforcement"]) for x in doc["rules"] if x["source"] == "CLAUDE.md"][0][0] == "R1"
    assert any(m["text"] == "parse_config" and not m["ambiguous"] for m in doc["mentions"]) and doc["source"] == {"kind": "folder"}


def test_the_answer_carries_the_plan_as_markdown_for_pasting(make, root):
    doc = plan(make(model_answers()), root).json()
    assert doc["markdown"].startswith("# Task plan") and TASK in doc["markdown"] and "## 5. Token plan" in doc["markdown"] and "## What was NOT checked" in doc["markdown"]
    again = TaskPlan.model_validate({k: v for k, v in doc.items() if k not in ("markdown", "source")})  # the rest of the answer is the plan, whole
    assert render_markdown(again) == doc["markdown"]


def test_the_model_sees_the_task_and_the_names_of_what_it_mentions_and_never_a_file_or_a_path(make, root):
    env = make(model_answers())
    plan(env, root)
    sent = " ".join(c["prompt"] for c in env.mock.calls)
    assert TASK in sent and "parse_config" in sent
    assert "open(path).read()" not in sent and "return 1" not in sent  # nothing from inside a function body
    assert str(root) not in sent and str(root.parent) not in sent


def test_a_plan_without_a_repository_is_one_model_call_and_says_the_size_could_not_be_measured(make):
    env = make([model_answers()[0]])
    doc = plan(env).json()
    assert doc["mode"] == "model" and doc["model_calls"] == 1 and doc["repo"] == "" and doc["source"] == {"kind": "none"}
    assert any("No repository was given" in n for n in doc["not_checked"]) and doc["tier"]["measured"] is False


# ---- a plan with no model ------------------------------------------------------------------------------------


def test_a_plan_with_no_model_sends_nothing_and_says_the_request_was_not_read(make, root):
    env = make([])
    env.builder.provider_factory = broken()  # not even a key is needed when nothing is sent
    doc = plan(env, root, no_ai=True).json()
    assert doc["mode"] == "facts only" and doc["model"] == "" and doc["model_calls"] == 0 and env.mock.calls == []
    assert "not read" in doc["reading"]["summary"] and doc["reading"]["stated"] == []
    assert any(m["text"] == "parse_config" for m in doc["mentions"]) and "was not read" in doc["markdown"].replace("**Not read.**", "was not read")
    assert any("No model was used" in n for n in doc["not_checked"]) and not leaks(root, doc)


def test_a_plan_changes_nothing_in_the_repository(make, root):
    before = tree(root)
    plan(make(model_answers()), root)
    plan(make([]), root, no_ai=True)
    assert tree(root) == before


def test_every_rule_is_marked_as_not_enforced_yet(make, root):
    doc = plan(make(model_answers()), root).json()
    assert doc["rules"] and all("not enforced" in x["enforcement"].lower() for x in doc["rules"])
    assert any("No rule is enforced yet" in n for n in doc["not_checked"])


# ---- the options ---------------------------------------------------------------------------------------------


def test_a_kind_of_task_given_by_the_person_replaces_the_one_the_model_guessed(make, root):
    assert plan(make(model_answers()), root, kind="bugfix").json()["reading"]["task_type"] == "bugfix"


def test_a_tier_can_be_raised_and_a_sensitive_path_makes_it_the_highest(make, root):
    env = make([])
    raised = plan(env, root, no_ai=True, tier=3).json()
    assert raised["tier"]["tier"] == 3 and raised["tier_name"] == "Complex or risky"
    doc = plan(env, root, no_ai=True, sensitive=["src/util.py"]).json()
    assert doc["tier"]["tier"] == 3 and any(s["name"] == "sensitive code" for s in doc["tier"]["signals"])


def test_the_tier_comes_with_its_name_so_the_page_and_the_markdown_cannot_disagree(make, root):
    doc = plan(make([]), root, no_ai=True).json()
    assert doc["tier_name"] in doc["markdown"] and doc["tier_name"] == process.TIER_NAMES[doc["tier"]["tier"]]


def test_a_budget_is_the_budget_the_token_plan_is_made_against(make, root):
    assert plan(make([]), root, no_ai=True, budget=5000).json()["token_plan"]["budget"] == 5000


@pytest.mark.parametrize("body", [
    {"tier": 4}, {"tier": -1}, {"budget": 0}, {"kind": "poem"}, {"task": ""}, {"task": "x" * 8001}, {"repo": "x" * 4097},
    {"sensitive": ["a"] * 11}, {"sensitive": ["x" * 201]},
])
def test_a_value_out_of_range_is_refused_before_anything_is_read(make, root, body):
    env = make(model_answers())
    r = plan(env, root, **body)
    assert r.status_code == 422 and env.mock.calls == []


def test_a_task_that_is_too_short_is_refused_in_words_before_a_model_is_asked_or_a_link_is_downloaded(served, make):
    env = make([])
    env.builder.provider_factory = broken()
    r = env.client.post("/api/plan", json={"task": "fix it", "repo": LINK})
    assert r.status_code == 400 and "at least a sentence" in r.json()["detail"] and served["calls"] == 0 and env.mock.calls == []
    assert env.client.post("/api/plan", json={"task": "      "}).status_code == 400


# ---- what goes wrong ---------------------------------------------------------------------------------------


def test_without_a_model_the_person_is_told_and_no_plan_is_made(make, root):
    env = make([])
    env.builder.provider_factory = broken("No AI model is set up. Put its settings in the .env file.")
    r = plan(env, root)
    assert r.status_code == 502 and "No AI model is set up" in r.json()["detail"]


def test_a_model_that_cannot_answer_is_a_plain_message_and_not_an_empty_plan(make, root):
    r = plan(make([ProviderError("The model has no quota left.")] * 3), root)
    assert r.status_code == 502 and "quota" in r.json()["detail"] and not leaks(root, r.json())


@pytest.mark.parametrize("path", ["relative/folder", "//server/share"])
def test_a_repository_that_is_not_a_folder_on_this_computer_is_refused_in_plain_words(make, tmp_path, path):
    r = make([]).client.post("/api/plan", json={"task": TASK, "repo": path, "no_ai": True})
    assert r.status_code == 400 and str(tmp_path) not in r.json()["detail"]


def test_a_folder_that_does_not_exist_is_refused_without_repeating_its_path(make, tmp_path):
    r = make([]).client.post("/api/plan", json={"task": TASK, "repo": str(tmp_path / "nowhere"), "no_ai": True})
    assert r.status_code == 400 and "Not a directory" in r.json()["detail"] and "nowhere" not in r.json()["detail"]


def test_a_folder_that_cannot_be_read_is_a_plain_400_that_does_not_repeat_the_operating_systems_words_or_the_path(make, root, monkeypatch):
    from skillforge.conductor import plan as plan_module

    def unreadable(*args, **kwargs):
        raise PermissionError(13, "Permission denied", str(root / "secret-place"))

    monkeypatch.setattr(plan_module, "build_graph", unreadable)
    r = plan(make([]), root, no_ai=True)
    assert r.status_code == 400 and "secret-place" not in r.json()["detail"] and str(root.parent) not in r.json()["detail"]
    assert "could not be read" in r.json()["detail"]


def test_an_empty_repository_box_means_no_repository(make):
    doc = make([]).client.post("/api/plan", json={"task": TASK, "repo": "   ", "no_ai": True}).json()
    assert doc["repo"] == "" and doc["source"] == {"kind": "none"}


# ---- a GitHub link ---------------------------------------------------------------------------------------------


def test_a_link_is_downloaded_named_by_owner_and_repo_and_says_its_rule_files_were_not_read(served, make):
    served["files"] = dict(SMALL)
    r = make([]).client.post("/api/plan", json={"task": TASK, "repo": LINK, "no_ai": True})
    doc = r.json()
    assert r.status_code == 200 and doc["repo"] == "acme/shop-api" and doc["source"]["kind"] == "github" and served["calls"] == 1
    assert any("CLAUDE.md and AGENTS.md are not downloaded" in n for n in doc["notes"])
    assert any(m["text"] == "parse_config" and not m["ambiguous"] for m in doc["mentions"])
    assert not managed_path_leaks(doc) and "acme/shop-api" in doc["markdown"]


# ---- hosted ------------------------------------------------------------------------------------------------


def test_the_plan_is_off_in_the_hosted_version(tmp_path, root):
    from skillforge.builder import Builder, JobRunner
    from skillforge.library import Library

    db = Database(f"sqlite:///{(tmp_path / 'h.db').as_posix()}")
    db.migrate()
    lib = Library(tmp_path / "library")
    builder = Builder(db, lib, tmp_path / "builds", provider_factory=lambda: MockProvider(model_answers()), runner=JobRunner(inline=True))
    client = TestClient(create_app(lib, builder=builder, hosted=hosted()), base_url="http://localhost")
    assert client.post("/api/auth/login", json={"token": TOKEN}).status_code == 200
    for body in ({"task": TASK, "repo": str(root)}, {"task": TASK}, {"task": TASK, "no_ai": True}):
        r = client.post("/api/plan", json=body)
        assert r.status_code == 403 and "hosted" in r.json()["detail"], body
    builder.runner.shutdown()
    db.close()
