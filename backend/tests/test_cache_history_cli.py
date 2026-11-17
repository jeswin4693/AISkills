from __future__ import annotations

import json
import re

import pytest

from conftest import commit_all, git, touch_later, write_files
from skillforge import cli
from skillforge.graph import query, store
from skillforge.graph.build import build_graph


def counts(g) -> tuple[int, int]:
    m = re.match(r"(\d+) files parsed, (\d+) reused", g.notes[0])
    return int(m.group(1)), int(m.group(2))


# ---- the cache is the graph's memory -----------------------------------------------------------------


def test_unchanged_files_are_reused_and_changed_files_are_reparsed(repo):
    root = repo({"a.py": "def a():\n    pass\n", "b.py": "def b():\n    pass\n"})
    assert counts(build_graph(root, with_history=False)) == (2, 0)
    assert counts(build_graph(root, with_history=False)) == (0, 2)

    (root / "a.py").write_text("def a():\n    return 1\n\ndef a2():\n    pass\n", encoding="utf-8")
    touch_later(root / "a.py")
    g = build_graph(root, with_history=False)
    assert counts(g) == (1, 1)
    assert "a.py::a2" in g.symbols  # the new function is visible after the incremental refresh


def test_deleted_files_leave_the_graph(repo):
    root = repo({"a.py": "def a():\n    pass\n", "b.py": "def b():\n    pass\n"})
    build_graph(root, with_history=False)
    (root / "b.py").unlink()
    g = build_graph(root, with_history=False)
    assert "b.py" not in g.files and "b.py::b" not in g.symbols


def test_nothing_is_written_inside_the_analysed_repository(repo):
    root = repo({"a.py": "def a():\n    pass\n"})
    before = sorted(p.name for p in root.iterdir())
    build_graph(root, with_history=False)
    assert sorted(p.name for p in root.iterdir()) == before
    assert store.cache_path(root).exists()


def test_a_corrupt_or_foreign_cache_is_ignored(repo):
    root = repo({"a.py": "def a():\n    pass\n"})
    build_graph(root, with_history=False)
    cache = store.cache_path(root)
    cache.write_text("{not json", encoding="utf-8")
    assert counts(build_graph(root, with_history=False)) == (1, 0)
    cache.write_text(json.dumps({"schema": -1, "files": {}}), encoding="utf-8")
    assert counts(build_graph(root, with_history=False)) == (1, 0)


def test_focus_limits_the_scan_and_skips_the_cache(repo):
    root = repo({"x/a.py": "def a():\n    pass\n", "y/b.py": "def b():\n    pass\n"})
    g = build_graph(root, focus="x", with_history=False)
    assert set(g.files) == {"x/a.py"}
    assert not store.cache_path(root).exists()


# ---- git history -------------------------------------------------------------------------------------


@pytest.fixture
def git_repo(tmp_path):
    root = write_files(tmp_path / "g", {
        "a.py": "def a():\n    pass\n", "b.py": "def b():\n    pass\n", "c.py": "def c():\n    pass\n",
    })
    git(root, "init", "-q")
    commit_all(root, "init")
    for i in range(3):  # a and b always change together; they never import each other
        (root / "a.py").write_text(f"def a():\n    return {i}\n", encoding="utf-8")
        (root / "b.py").write_text(f"def b():\n    return {i}\n", encoding="utf-8")
        commit_all(root, f"change {i}")
    (root / "c.py").write_text("def c():\n    return 1\n", encoding="utf-8")
    commit_all(root, "c alone")
    return root


def test_churn_and_co_change_come_from_git(git_repo):
    g = build_graph(git_repo, use_cache=False)
    assert g.commits == 5
    assert g.churn == {"a.py": 4, "b.py": 4, "c.py": 2}
    assert g.co_change == [("a.py", "b.py", 4, 1.0)]


def test_hidden_coupling_raises_the_impact_risk(git_repo):
    g = build_graph(git_repo, use_cache=False)
    r = query.impact(g, "a.py")
    assert [h["path"] for h in r["hidden_coupling"]] == ["b.py"]
    assert r["risk"]["factors"]["strong_hidden_coupling"] == 1
    assert r["risk"]["score"] == 0 + 2 + 4  # no dependents, one strong coupling, no test tied


def test_without_git_history_is_unknown_not_zero(repo):
    g = build_graph(repo({"a.py": "def a():\n    pass\n"}), use_cache=False)
    assert g.commits is None and g.churn == {} and g.co_change == []
    assert any("No git history" in n for n in query.impact(g, "a.py")["notes"])


# ---- command line ------------------------------------------------------------------------------------


def run_cli(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


@pytest.fixture
def cli_repo(repo):
    return repo({
        "svc.py": "def parse(raw):\n    return raw\n",
        "api.py": "from svc import parse\n\ndef handler(r):\n    return parse(r)\n",
        "other.py": "def parse(x):\n    return x\n",
    })


def test_cli_text_and_json_output(capsys, cli_repo):
    code, out, _ = run_cli(capsys, "graph", "stats", str(cli_repo), "--no-cache", "--no-history")
    assert code == 0 and "Files: 3" in out

    code, out, _ = run_cli(capsys, "graph", "callers", str(cli_repo), "svc.py::parse", "--json", "--no-cache")
    assert code == 0
    assert [r["name"] for r in json.loads(out)["results"]] == ["handler"]

    code, out, _ = run_cli(capsys, "graph", "impact", str(cli_repo), "svc.py", "--no-cache", "--no-history")
    assert code == 0 and "api.py" in out and "risk" in out.lower()


def test_cli_reports_errors_without_a_traceback(capsys, cli_repo):
    code, _, err = run_cli(capsys, "graph", "callers", str(cli_repo), "parse", "--no-cache")
    assert code == 2 and "ambiguous" in err
    code, _, err = run_cli(capsys, "graph", "stats", str(cli_repo / "nope"), "--no-cache")
    assert code == 2 and "Not a directory" in err


def test_default_cache_location_is_a_per_user_folder_never_the_repo(monkeypatch, tmp_path):
    monkeypatch.delenv("SKILLFORGE_DATA_DIR")
    for var in ("LOCALAPPDATA", "XDG_DATA_HOME", "HOME", "USERPROFILE"):
        monkeypatch.setenv(var, str(tmp_path))
    where = store.data_dir()
    assert tmp_path in where.parents and where.name == "skillforge"
