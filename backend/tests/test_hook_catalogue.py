"""The hook catalogue (Component Factory, Phase 4b, task 1): the fixed scripts a plugin's hooks may run, run here with real input; the
options that may be chosen; and proofs that no script can do more than its entry says. The scripts are SkillForge's own, hand-written
and short, so they run on this machine in a test, with temporary folders only."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from skillforge.hookcatalog.catalogue import (
    CATALOGUE, SCRIPTS, CatalogueError, accepts, entry_for_script_path, get_entry, hook_group, parse_args, render_args, script_bytes, script_hash,
)
from skillforge.validate.plugin import PLUGIN_ROOT, START_COMMAND
from skillforge.validate.static import script_capabilities

SECRETS = get_entry("block-secret-files")
FORCE = get_entry("block-force-push")
LOG = get_entry("log-tool-calls")


def run(entry_id: str, event: object, *args: str, env: dict | None = None, raw: bytes | None = None) -> subprocess.CompletedProcess:
    """Run a catalogue script the way Claude Code does: the event as JSON on stdin, options as arguments, no shell."""
    entry = get_entry(entry_id)
    data = raw if raw is not None else json.dumps(event).encode("utf-8")
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPTS / entry.script), *args], input=data, capture_output=True, timeout=30,
        env={"PATH": "", "SystemRoot": "C:\\Windows", **(env or {})},
    )


def tool(name: str, **tool_input: object) -> dict:
    return {"hook_event_name": "PreToolUse", "tool_name": name, "tool_input": tool_input, "cwd": "/work", "session_id": "s"}


def text(out: bytes) -> str:
    return out.decode("utf-8", "replace")


# ---- block-secret-files ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", [
    "/proj/.env", "/proj/.env.local", "C:\\proj\\sub\\.ENV", "~/.ssh/id_rsa", "/etc/ssl/server.PEM", "/a/b/key.pfx", "/a/.env ", "/a/.env.",
    "C:\\a\\.env::$DATA", "/home/u/.aws/credentials", "/home/u/.netrc", "/x/release.keystore", ".env",
])
def test_a_file_that_usually_holds_a_secret_is_blocked_with_the_reason_on_stderr(path):
    done = run("block-secret-files", tool("Read", file_path=path))
    assert done.returncode == 2, (path, done.stderr)
    assert "block-secret-files" in text(done.stderr) and "secret" in text(done.stderr) and done.stdout == b""


@pytest.mark.parametrize("path", [
    "/proj/main.py", "/proj/.env.example", "/proj/.env.sample", "/proj/environment.md", "/home/u/.ssh/id_rsa.pub", "/proj/keys.md", "/proj/src/env.py",
    "C:\\proj\\README.md", "/proj/.environment",
])
def test_an_ordinary_file_and_the_example_env_files_are_allowed(path):
    done = run("block-secret-files", tool("Edit", file_path=path))
    assert done.returncode == 0 and done.stdout == b"" and done.stderr == b""


def test_a_notebook_is_judged_by_its_notebook_path():
    assert run("block-secret-files", tool("NotebookEdit", notebook_path="/p/.env")).returncode == 2
    assert run("block-secret-files", tool("NotebookEdit", notebook_path="/p/a.ipynb")).returncode == 0


def test_the_extra_names_the_person_chose_are_blocked_too_and_can_name_an_example_file():
    assert run("block-secret-files", tool("Write", file_path="/p/secrets.json")).returncode == 0
    assert run("block-secret-files", tool("Write", file_path="/p/secrets.json"), "--also", "secrets.json").returncode == 2
    assert run("block-secret-files", tool("Read", file_path="/p/a.token"), "--also", "*.token").returncode == 2
    assert run("block-secret-files", tool("Read", file_path="/p/.env.example"), "--also", ".env.example").returncode == 2


@pytest.mark.parametrize("raw", [b"", b"not json", b"[1, 2]", b"\xff\xfe\x00", b'"text"'])
def test_input_it_cannot_read_blocks_to_be_safe_and_says_why(raw):
    done = run("block-secret-files", None, raw=raw)
    assert done.returncode == 2 and "blocked this to be safe" in text(done.stderr)  # exit 2 blocks, whatever the Claude Code version: a guard that cannot see does not wave things through


@pytest.mark.parametrize("event", [{"tool_name": "Read"}, {"tool_name": "Read", "tool_input": "x"}, {"tool_name": "Read", "tool_input": {"offset": 1}}])
def test_an_event_with_no_file_path_in_it_blocks_to_be_safe_instead_of_being_silently_allowed(event):
    done = run("block-secret-files", event)
    assert done.returncode == 2 and "blocked this to be safe" in text(done.stderr)


# ---- block-force-push -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("command", [
    "git push --force", "git push -f origin main", "git push origin +main", "cd repo && git push --force-with-lease", "git -C repo push -fu origin b",
    "echo hi; git push -f", "GIT_TRACE=1 git push --force-if-includes", "git   push   origin   main   --force", "git push origin HEAD:+main",
    "/usr/bin/git push -f", "git.exe push -f", "git add . && git commit -m x && git push -f origin b",
    "git push --forc", "git push --for origin main", "git push --force-w", "git push --force-with-lease=main:abc123",  # git accepts an unambiguous start of a long option
])
def test_a_forced_push_is_blocked(command):
    done = run("block-force-push", tool("Bash", command=command))
    assert done.returncode == 2, (command, done.stderr)
    assert "block-force-push" in text(done.stderr) and done.stdout == b""


@pytest.mark.parametrize("command", [
    "git push", "git push -u origin feature", "git push --follow-tags", "git pull --force", "git commit -m 'fix the -f flag'", "git status",
    "echo force", "git push origin main --tags", "ls -f", "git fetch -f", "git push --set-upstream origin a+b",
    "git push --follow", "git push --fol", "git push --f", "git push --dry-run", "git push --atomic",
])
def test_an_ordinary_push_and_other_commands_are_allowed(command):
    done = run("block-force-push", tool("Bash", command=command))
    assert done.returncode == 0 and done.stdout == b"" and done.stderr == b"", (command, done.stderr)


def test_the_powershell_tool_is_read_the_same_way():
    assert run("block-force-push", tool("PowerShell", command="git push --force")).returncode == 2


@pytest.mark.parametrize("raw", [b"", b"nope", b"[]"])
def test_a_force_push_hook_that_cannot_read_its_input_blocks_to_be_safe_and_says_why(raw):
    done = run("block-force-push", None, raw=raw)
    assert done.returncode == 2 and "blocked this to be safe" in text(done.stderr)


def test_an_event_without_a_command_blocks_to_be_safe():
    done = run("block-force-push", tool("Bash", description="x"))
    assert done.returncode == 2 and "blocked this to be safe" in text(done.stderr)


def test_a_script_that_only_observes_never_blocks_whatever_it_is_given(tmp_path):
    # the logging hook is not a guard: when it cannot do its job it says so (exit 1, a non-blocking error) and the action goes ahead
    done = run("log-tool-calls", None, raw=b"garbage", env={"CLAUDE_PLUGIN_DATA": str(tmp_path / "d")})
    assert done.returncode == 1 and done.returncode != 2


# ---- log-tool-calls -------------------------------------------------------------------------------------------------------


def post(name: str = "Bash", **tool_input: object) -> dict:
    return {"hook_event_name": "PostToolUse", "tool_name": name, "tool_input": tool_input, "tool_response": "result text", "session_id": "s"}


def test_a_line_with_the_time_and_the_tools_name_is_added_to_the_data_folder_and_nothing_else_is_recorded(tmp_path):
    data = tmp_path / "plugin-data"
    env = {"CLAUDE_PLUGIN_DATA": str(data)}
    assert run("log-tool-calls", post("Bash", command="curl https://example.test/?token=hunter2"), env=env).returncode == 0
    assert run("log-tool-calls", post("Read", file_path="/p/a.txt"), env=env).returncode == 0
    lines = (data / "tool-calls.log").read_text(encoding="utf-8").splitlines()  # the folder was created
    first, second = json.loads(lines[0]), json.loads(lines[1])
    assert set(first) == {"time", "tool"} and first["tool"] == "Bash" and second["tool"] == "Read" and first["time"].endswith("Z")
    assert "hunter2" not in "".join(lines) and "result text" not in "".join(lines)  # never what the tool was given or returned


def test_a_log_that_reaches_a_megabyte_is_rotated_once(tmp_path):
    data = tmp_path / "d"
    data.mkdir()
    (data / "tool-calls.log").write_bytes(b"x" * 1_000_001)
    assert run("log-tool-calls", post("Write"), env={"CLAUDE_PLUGIN_DATA": str(data)}).returncode == 0
    assert (data / "tool-calls.log.1").stat().st_size == 1_000_001
    assert len((data / "tool-calls.log").read_text(encoding="utf-8").splitlines()) == 1


def test_without_a_data_folder_or_with_input_it_cannot_read_it_writes_nothing_and_says_so(tmp_path):
    assert "CLAUDE_PLUGIN_DATA" in text(run("log-tool-calls", post(), env={}).stderr)
    assert run("log-tool-calls", post(), env={}).returncode == 1
    done = run("log-tool-calls", None, raw=b"garbage", env={"CLAUDE_PLUGIN_DATA": str(tmp_path / "d")})
    assert done.returncode == 1 and not (tmp_path / "d").exists()


def test_a_tool_name_that_is_not_plain_text_is_cut_and_cleaned_before_it_is_written(tmp_path):
    env = {"CLAUDE_PLUGIN_DATA": str(tmp_path)}
    assert run("log-tool-calls", post("x" * 500 + "\nforged line"), env=env).returncode == 0
    lines = (tmp_path / "tool-calls.log").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and len(json.loads(lines[0])["tool"]) <= 100


# ---- the options -----------------------------------------------------------------------------------------------------------


def test_options_become_separate_arguments_after_the_scripts_path_and_come_back_the_same():
    args = render_args(SECRETS, {"also": ["secrets.json", "*.token", "secrets.json"]})
    assert args == [f"{PLUGIN_ROOT}/hooks/block-secret-files.py", "--also", "secrets.json", "--also", "*.token"]  # each once, in order, never one string
    assert parse_args(SECRETS, args) == {"also": ["secrets.json", "*.token"]}
    assert render_args(SECRETS, None) == [SECRETS.command_path] and parse_args(SECRETS, [SECRETS.command_path]) == {}


@pytest.mark.parametrize("options,why", [
    ({"also": ["a;rm -rf /"]}, "not allowed"), ({"also": ["$(whoami)"]}, "not allowed"), ({"also": ["a b"]}, "not allowed"), ({"also": ["../x"]}, "not allowed"),
    ({"also": ["--force"]}, "not allowed"), ({"also": ["-x"]}, "not allowed"), ({"also": ["*"]}, "not allowed"), ({"also": ["??"]}, "not allowed"),
    ({"also": ["*.*"]}, "not allowed"), ({"also": [""]}, "not allowed"), ({"also": ["a" * 61]}, "not allowed"), ({"also": [str(i) for i in range(11)]}, "at most 10"),
    ({"also": "secrets.json"}, "list"), ({"also": [1]}, "not allowed"), ({"nope": ["x"]}, "no option"),
])
def test_an_option_that_could_be_more_than_a_name_is_refused(options, why):
    with pytest.raises(CatalogueError, match=why):
        render_args(SECRETS, options)


def test_a_hook_without_options_refuses_any():
    with pytest.raises(CatalogueError, match="no option"):
        render_args(FORCE, {"also": ["x"]})


@pytest.mark.parametrize("args", [
    None, "x", [], [1], ["wrong/path.py"], [SECRETS.command_path, "--also"], [SECRETS.command_path, "--bogus", "x"], [SECRETS.command_path, "--also", "a;b"],
    [SECRETS.command_path, "--also", "a", "--also", "a"], [SECRETS.command_path, "extra"],
])
def test_arguments_that_are_not_exactly_what_the_catalogue_writes_are_not_recognised(args):
    assert parse_args(SECRETS, args) is None


def test_a_hook_is_written_as_one_exec_form_group_and_the_matcher_is_left_out_when_it_is_every_tool():
    assert hook_group(SECRETS, {"also": ["a.key"]}) == {
        "matcher": "Read|Write|Edit|NotebookEdit",
        "hooks": [{"type": "command", "command": "python", "args": [SECRETS.command_path, "--also", "a.key"], "timeout": 10, "onFailure": "block"}],
    }
    assert "matcher" not in hook_group(LOG) and hook_group(LOG)["hooks"][0]["args"] == [LOG.command_path]
    assert START_COMMAND == "python" and PLUGIN_ROOT == "${CLAUDE_PLUGIN_ROOT}"  # the catalogue and the validator say the same words


def test_a_hook_that_can_block_fails_closed_and_one_that_only_looks_does_not():
    # Checked in real Claude Code 2.1.325: without onFailure a hook that cannot start (python missing from the PATH) or that exits 1 lets the
    # action go ahead and nothing tells the person; with onFailure "block" the action is stopped and the reason is shown.
    assert (SECRETS.on_failure, FORCE.on_failure, LOG.on_failure) == ("block", "block", None)
    assert hook_group(FORCE)["hooks"][0]["onFailure"] == "block" and "onFailure" not in hook_group(LOG)["hooks"][0]
    assert all(e.on_failure == ("block" if e.effect == "blocks" else None) for e in CATALOGUE.values())


def test_the_blocking_scripts_are_a_new_revision_because_the_first_one_failed_open_and_is_not_accepted():
    assert (SECRETS.revision, FORCE.revision, LOG.revision) == (2, 2, 1)
    assert SECRETS.earlier == frozenset() and FORCE.earlier == frozenset()  # the revision that let an unreadable event through is deliberately not described any more


def test_the_catalogue_is_found_by_id_and_by_the_path_a_hooks_file_names():
    assert [e.id for e in CATALOGUE.values()] == ["block-secret-files", "block-force-push", "log-tool-calls"]
    assert entry_for_script_path(FORCE.command_path) is FORCE and entry_for_script_path("${CLAUDE_PLUGIN_ROOT}/hooks/other.py") is None
    assert entry_for_script_path(None) is None
    with pytest.raises(CatalogueError, match="not a hook in the catalogue"):
        get_entry("run-anything")


# ---- the scripts themselves are fixed and cannot do more than their entry says ---------------------------------------------

def test_every_script_is_pinned_so_a_change_has_to_be_made_on_purpose():
    # When a script changes on purpose: add its old hash to the entry's `earlier` (a plugin made before still counts as described),
    # bump `revision`, and update hook_catalogue_hashes.json.
    pinned = json.loads((Path(__file__).parent / "hook_catalogue_hashes.json").read_text(encoding="utf-8"))
    assert {entry_id: script_hash(script_bytes(e)) for entry_id, e in CATALOGUE.items()} == pinned


def test_a_script_is_accepted_when_it_is_the_catalogues_whatever_the_line_endings_and_not_when_it_changed():
    data = script_bytes(FORCE)
    assert accepts(FORCE, data) and accepts(FORCE, data.replace(b"\n", b"\r\n"))
    assert not accepts(FORCE, data + b"\n# one more line\n") and not accepts(FORCE, script_bytes(SECRETS)) and not accepts(FORCE, b"")


def test_the_scripts_in_the_folder_are_exactly_the_scripts_of_the_catalogue():
    assert sorted(p.name for p in SCRIPTS.glob("*.py")) == sorted(e.script for e in CATALOGUE.values())


@pytest.mark.parametrize("entry", list(CATALOGUE.values()), ids=list(CATALOGUE))
def test_a_script_can_do_only_what_its_entry_declares(entry):
    caps, dynamic = script_capabilities(entry.script, script_bytes(entry))
    assert caps == set(entry.powers) and dynamic == set()  # no network, no started programs, no code built from text; writes only where declared


STANDARD = {"datetime", "fnmatch", "json", "ntpath", "os", "re", "shlex", "sys"}


@pytest.mark.parametrize("entry", list(CATALOGUE.values()), ids=list(CATALOGUE))
def test_a_script_imports_only_a_short_list_of_standard_modules(entry):
    tree = ast.parse(script_bytes(entry).decode("utf-8"))
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert imported <= STANDARD, imported - STANDARD


@pytest.mark.parametrize("entry", list(CATALOGUE.values()), ids=list(CATALOGUE))
def test_a_script_is_plain_text_with_no_hidden_characters(entry):
    body = script_bytes(entry).decode("utf-8")
    assert body.isascii() and "\t" not in body and body.startswith('"""')
