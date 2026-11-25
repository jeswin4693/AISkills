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

from skillforge import cli
from skillforge.builder import UpstreamError
from skillforge.builder import github as gh

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
    before, after = done.stdout.split()
    assert before == after, done.stderr


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
