"""Slice AL: the function-level call graph over HTTP. Two routes next to `repos/analyze`: search a repository's functions, and draw one function's
callers and callees. Offline, small repositories in a temp folder, the real routes through the real app."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from test_builder import make  # noqa: F401  (make is a pytest fixture)
from test_hosted import TOKEN, hosted
from test_suggest import REPO

from skillforge.api import create_app
from skillforge.db import Database


@pytest.fixture
def root(repo):
    return repo(REPO)


def leaks(root, doc) -> bool:
    """Whether the folder the repository sits in (a person's own path) is in a response, compared as JSON text so backslashes are not missed."""
    return json.dumps(str(root.parent))[1:-1] in json.dumps(doc)


def search(env, root, query, **extra):
    return env.client.post("/api/repos/functions", json={"path": str(root), "query": query, **extra})


def calls(env, root, symbol, depth=1, **extra):
    return env.client.post("/api/repos/calls", json={"path": str(root), "symbol": symbol, "depth": depth, **extra})


# ---- search -------------------------------------------------------------------------------------------


def test_the_search_finds_a_function_with_the_numbers_that_help_to_choose_it(make, root):
    r = search(make([]), root, "shared")
    doc = r.json()
    assert r.status_code == 200 and doc["name"] == root.name and doc["query"] == "shared" and doc["total"] >= 1
    first = doc["matches"][0]
    assert first["id"] == "core.py::shared" and first["callers"] == 2 and first["measured"] is True and not leaks(root, doc)


def test_a_search_that_matches_nothing_is_an_empty_list_not_an_error(make, root):
    r = search(make([]), root, "zzz_nothing_like_this")
    assert r.status_code == 200 and r.json()["matches"] == [] and r.json()["total"] == 0


def test_a_blank_search_is_a_plain_400_saying_what_to_type(make, root):
    r = search(make([]), root, "   ")
    assert r.status_code == 400 and "name" in r.json()["detail"]


def test_a_search_text_over_the_limit_is_refused(make, root):
    assert search(make([]), root, "x" * 201).status_code == 422


# ---- one function's calls -----------------------------------------------------------------------------


def test_the_calls_of_a_function_say_who_calls_it(make, root):
    r = calls(make([]), root, "core.py::shared")
    doc = r.json()
    assert r.status_code == 200 and doc["name"] == root.name and doc["subject"]["id"] == "core.py::shared"
    assert sorted(n["name"] for n in doc["nodes"] if n["role"] == "caller") == ["use_a", "use_b"]
    assert doc["measured"] is True and doc["depth"] == 1 and not leaks(root, doc)
    assert {(e["from"], e["to"]) for e in doc["edges"]} == {("a.py::use_a", "core.py::shared"), ("b.py::use_b", "core.py::shared")}


def test_the_depth_is_passed_through_and_must_be_one_or_two(make, root):
    env = make([])
    assert calls(env, root, "core.py::shared", depth=2).json()["depth"] == 2
    assert calls(env, root, "core.py::shared", depth=3).status_code == 422
    assert calls(env, root, "core.py::shared", depth=0).status_code == 422


def test_a_function_that_is_not_in_the_repository_is_a_plain_400_in_words(make, root):
    r = calls(make([]), root, "core.py::not_there")
    assert r.status_code == 400 and "Search for it again" in r.json()["detail"] and not leaks(root, r.json())


def test_a_symbol_is_required_and_is_not_endless(make, root):
    env = make([])
    assert env.client.post("/api/repos/calls", json={"path": str(root)}).status_code == 422
    assert calls(env, root, "x" * 1001).status_code == 422


def test_the_focus_folder_limits_what_is_searched(make, repo):
    folder = repo({"pkg/a.py": "def inside():\n    return 1\n", "other/b.py": "def outside():\n    return 2\n"})
    env = make([])
    assert [m["name"] for m in search(env, folder, "side", focus="pkg").json()["matches"]] == ["inside"]
    assert [m["name"] for m in search(env, folder, "side").json()["matches"]] == ["inside", "outside"]


# ---- bad folders ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("route, body", [
    ("/api/repos/functions", {"query": "x"}),
    ("/api/repos/calls", {"symbol": "a.py::x", "depth": 1}),
])
def test_both_routes_want_an_absolute_folder_that_exists(make, tmp_path, route, body):
    env = make([])
    assert "absolute" in env.client.post(route, json={"path": "relative/path", **body}).json()["detail"]
    r = env.client.post(route, json={"path": str(tmp_path / "nowhere"), **body})
    assert r.status_code == 400 and "Not a directory" in r.json()["detail"]


def test_both_routes_are_off_in_the_hosted_version(tmp_path, root):
    db = Database(f"sqlite:///{(tmp_path / 'h.db').as_posix()}")
    db.migrate()
    from skillforge.builder import Builder, JobRunner
    from skillforge.library import Library
    from skillforge.providers import MockProvider

    lib = Library(tmp_path / "library")
    builder = Builder(db, lib, tmp_path / "builds", provider_factory=lambda: MockProvider([]), runner=JobRunner(inline=True))
    client = TestClient(create_app(lib, builder=builder, hosted=hosted()), base_url="http://localhost")
    assert client.post("/api/auth/login", json={"token": TOKEN}).status_code == 200
    for path, body in (
        ("/api/repos/functions", {"path": str(root), "query": "shared"}),
        ("/api/repos/calls", {"path": str(root), "symbol": "core.py::shared", "depth": 1}),
    ):
        r = client.post(path, json=body)
        assert r.status_code == 403 and "hosted" in r.json()["detail"], path
    builder.runner.shutdown()
    db.close()
