"""Slice AA: the command line takes the link of a public GitHub repository wherever it takes a repository. Offline: the page's fake download
stands in for GitHub, and the real `cli.main` runs."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from test_github_link import LINK, REPO, served, zip_of  # noqa: F401  (served is a pytest fixture: the archive GitHub 'serves')
from test_library import NAME, write_skill
from test_skill_build import ANSWERS, FIRST, draft, round_one, round_two

from skillforge import cli
from skillforge.builder import UpstreamError
from skillforge.builder import github as gh
from skillforge.evidence import EVIDENCE_FILE, read_evidence
from skillforge.providers import MockProvider

BACKEND = Path(__file__).resolve().parents[1]


def run(capsys, *argv: str):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


# ---- a link is read like a folder, and the note says where it came from -----------------------------------------


def test_a_link_is_read_by_graph_stats_and_the_note_says_where_it_came_from(served, capsys):
    code, out, err = run(capsys, "graph", "stats", LINK, "--no-history")
    assert code == 0 and "Files: 3" in out and served["calls"] == 1
    assert "Read acme/shop-api from GitHub" in err and "Nothing was run" in err and "Git history is not downloaded" in err
    for text in (out, err):
        assert str(gh.snapshot_root()) not in text and "codeload" not in text  # where the copy is kept is not shown


def test_graph_stats_names_the_repository_and_not_the_folder_of_its_copy(served, capsys):
    _, out, _ = run(capsys, "graph", "stats", LINK, "--no-history")
    assert "Repository: acme/shop-api" in out
    _, branch_out, _ = run(capsys, "graph", "stats", LINK + "/tree/dev", "--no-history")
    assert "Repository: acme/shop-api (branch dev)" in branch_out


def test_a_young_copy_is_reused_by_graph(served, capsys):
    run(capsys, "graph", "stats", LINK, "--no-history")
    code, _, err = run(capsys, "graph", "stats", LINK, "--no-history")
    assert code == 0 and served["calls"] == 1 and "a copy from" in err


def test_json_output_stays_json_and_the_note_goes_to_stderr(served, capsys):
    code, out, err = run(capsys, "graph", "stats", LINK, "--json", "--no-history")
    assert code == 0 and json.loads(out)["files"] == 3 and "Read acme/shop-api" in err and "Read acme" not in out


def test_suggest_facts_only_reads_a_link(served, capsys):
    code, out, err = run(capsys, "suggest", LINK, "--facts-only", "--no-history")
    assert code == 0 and out.strip() and "Read acme/shop-api from GitHub" in err


def test_a_branch_link_names_the_branch_in_the_note(served, capsys):
    code, _, err = run(capsys, "graph", "stats", LINK + "/tree/dev", "--no-history")
    assert code == 0 and "branch dev" in err


# ---- what goes wrong is one plain line ----------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["https://gitlab.com/acme/shop-api", "http://github.com/acme/shop-api", "https://user@github.com/acme/shop-api",
                                 "https://github.com:8443/acme/shop-api"])
def test_a_link_that_is_refused_is_one_error_line_and_exit_2(served, capsys, bad):
    code, out, err = run(capsys, "graph", "stats", bad)
    assert code == 2 and err.startswith("error:") and "Traceback" not in err and out == ""
    assert "gitlab" not in err and "user@" not in err and "8443" not in err and served["calls"] == 0  # what was typed is not repeated


def test_a_missing_repository_and_an_unreachable_github_are_one_error_line(served, capsys):
    served["error"] = gh.NotFound(gh.NOT_FOUND)
    code, _, err = run(capsys, "graph", "stats", LINK)
    assert code == 2 and "Private repositories cannot be read" in err and "Traceback" not in err
    served["error"] = UpstreamError("Could not reach GitHub (TimeoutError).")
    code, _, err = run(capsys, "suggest", LINK, "--facts-only")
    assert code == 2 and "Could not reach GitHub" in err and "Traceback" not in err


# ---- a folder is exactly what it was ---------------------------------------------------------------------------------


def test_a_folder_argument_is_unchanged(repo, capsys):
    folder = repo(REPO)
    assert cli._repo_arg(str(folder)) == str(folder)
    assert cli._repo_arg(None) is None and cli._repo_arg("") is None
    code, out, err = run(capsys, "graph", "stats", str(folder), "--no-history")
    assert code == 0 and err == "" and f"Repository: {folder.resolve()}" in out and "Files: 3" in out


def test_a_path_with_github_in_it_is_still_a_folder(repo, capsys):
    folder = repo({"github.com/x/a.py": "def a():\n    return 1\n"}) / "github.com" / "x"
    code, out, err = run(capsys, "graph", "stats", str(folder), "--no-history")
    assert code == 0 and "Files: 1" in out and err == ""


def test_reading_a_folder_does_not_import_the_builder():
    """The builder package pulls in the database layer: a plain folder must not pay for that."""
    child = (
        "import sys; from skillforge import cli; before = 'skillforge.builder' in sys.modules; "
        "cli._repo_arg('C:/some/folder'); print(before, 'skillforge.builder' in sys.modules)"
    )
    done = subprocess.run([sys.executable, "-c", child], cwd=BACKEND, capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(BACKEND)})
    assert done.stdout.split() == ["False", "False"], done.stderr  # not by importing the CLI, and not by a folder argument either


@pytest.mark.parametrize("text", [
    "https://github.com/a/b", "http://github.com/a/b", "github.com/a/b", "www.github.com/a/b", "GITHUB.COM/a/b", "  https://github.com/a/b  ", "ftp://example.org/x",
    "https://gitlab.com/a/b", "github.com", "www.github.com", "ssh://git@github.com/a/b.git",
    "C:" + chr(92) + "code" + chr(92) + "repo", "/home/me/repo", "relative/path", chr(92) * 2 + "server" + chr(92) + "share", "//server/share/repo", "", "github.company.com/x", "git@github.com:a/b.git",
])
def test_the_cheap_link_check_agrees_with_the_builders_own(text):
    """The CLI repeats the builder's check so that a folder never imports the builder. They must not drift apart."""
    assert cli._looks_like_link(text) == gh.looks_like_link(text), text


# ---- the note, as a pure function ------------------------------------------------------------------------------------


def view(**over):
    base = {"kind": "github", "owner": "acme", "repo": "shop-api", "ref": None, "url": LINK, "files": 12, "bytes": 3_400_000, "skipped": {}, "reused": False,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(1_800_000_000))}
    return base | over


def test_source_lines_for_a_fresh_copy_and_for_one_that_was_reused():
    now = 1_800_000_000 + 4 * 60
    fresh = cli._source_lines(view(), now=now)
    assert fresh[0] == "Read acme/shop-api from GitHub (default branch): 12 source files kept (3.4 MB), downloaded just now."
    reused = cli._source_lines(view(reused=True), now=now)
    assert "a copy from 4 minutes ago" in reused[0]
    assert fresh[-1].startswith("Nothing was run.") and "Git history is not downloaded" in fresh[-1]


def test_source_lines_say_what_was_left_out_in_words():
    lines = cli._source_lines(view(skipped={"not_source": 2, "too_large": 1, "path_too_long": 3}), now=1_800_000_000)
    left_out = next(line for line in lines if line.startswith("Left out:"))
    assert "2 files in languages or formats the graph does not read" in left_out and "1 file over 1 MB" in left_out and "3 paths too long for this disk" in left_out
    assert not any(line.startswith("Left out:") for line in cli._source_lines(view(skipped={}), now=1_800_000_000))


# ---- plan, build and the evidence commands -----------------------------------------------------------------------------


def test_plan_on_a_link_says_the_rules_files_are_not_downloaded(served, capsys):
    """A copy holds only source files, so a repository's CLAUDE.md and AGENTS.md are not in it: the plan must not quietly report 'no rules'."""
    code, out, err = run(capsys, "plan", "rename the function shared in core.py to shared_value", "--repo", LINK, "--no-ai")
    assert code == 0 and "Read acme/shop-api from GitHub" in err
    assert "CLAUDE.md" in err and "not downloaded" in err and "core.py" in out


@pytest.fixture
def skill_in_library(tmp_path, capsys):
    skill = write_skill(tmp_path / NAME, "Use `core.py::shared`.\n")
    assert run(capsys, "library", "import", str(skill))[0] == 0


def test_cite_recheck_and_refresh_download_a_fresh_copy_each_time_and_graph_does_not(served, skill_in_library, capsys):
    run(capsys, "graph", "stats", LINK, "--no-history")
    run(capsys, "graph", "stats", LINK, "--no-history")
    assert served["calls"] == 1  # a young copy is reused
    code, out, err = run(capsys, "library", "cite", NAME, "--repo", LINK, "--ref", "core.py::shared")
    assert code == 0 and served["calls"] == 2 and "downloaded just now" in err and f"--repo {LINK}" in out  # what changed is asked of the code as it is now
    code, _, err = run(capsys, "library", "recheck", NAME, "--repo", LINK)
    assert code == 0 and served["calls"] == 3 and "downloaded just now" in err
    code, _, _ = run(capsys, "library", "refresh", NAME, "--repo", LINK)
    assert code == 0 and served["calls"] == 4


def test_recheck_of_a_link_names_what_changed(served, skill_in_library, capsys):
    run(capsys, "library", "cite", NAME, "--repo", LINK, "--ref", "core.py::shared")
    served["files"] = {**REPO, "core.py": "def other():\n    return 1\n"}
    code, out, _ = run(capsys, "library", "recheck", NAME, "--repo", LINK)
    assert code == 1 and "MISSING" in out and "core.py::shared" in out


@pytest.fixture
def link_idea(tmp_path):
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"repo": "shop-api", "suggestions": [{
        "title": "Duplicate finder", "skill_requirement": FIRST, "evidence_nodes": ["core.py::shared", "a.py", "gone.py"],
    }]}), encoding="utf-8")
    answers = tmp_path / "a.json"
    answers.write_text(json.dumps(ANSWERS), encoding="utf-8")
    return report, answers


def test_build_with_a_link_records_the_ideas_evidence(served, link_idea, monkeypatch, capsys, tmp_path):
    report, answers = link_idea
    monkeypatch.setattr(cli, "provider_from_env", lambda: MockProvider([round_one(), round_two(), draft()]))
    code, out, err = run(capsys, "build", "--from-suggestions", str(report), "--pick", "1", "--answers", str(answers), "--yes",
                         "--out", str(tmp_path / "skills"), "--repo", LINK)
    assert code == 0 and "evidence.json" in out and "2 place" in out and "gone.py" in out and "Read acme/shop-api" in err
    folder = tmp_path / "skills" / "duplicate-function-finder"
    ev = read_evidence({EVIDENCE_FILE: (folder / EVIDENCE_FILE).read_bytes()})
    assert [r.id for r in ev.refs] == ["core.py::shared", "a.py"] and ev.repo == "acme__shop-api"


def test_a_refused_link_stops_build_before_a_model_is_asked(served, link_idea, monkeypatch, capsys, tmp_path):
    report, answers = link_idea
    mock = MockProvider([round_one(), round_two(), draft()])
    monkeypatch.setattr(cli, "provider_from_env", lambda: mock)
    code, _, err = run(capsys, "build", "--from-suggestions", str(report), "--pick", "1", "--answers", str(answers), "--yes",
                       "--out", str(tmp_path / "s"), "--repo", "https://gitlab.com/a/b")
    assert code == 2 and "error:" in err and "gitlab" not in err and mock.calls == [] and served["calls"] == 0
