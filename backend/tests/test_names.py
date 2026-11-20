"""Names are folder names and command arguments, so a name check must be exact: a trailing newline is not a name, and
Windows device names (nul, con, aux, ...) cannot be a folder at all. Found by an independent review of the plugin builder."""

from __future__ import annotations

import json

import pytest

from skillforge.build.checks import SLUG as BUILD_SLUG
from skillforge.build.mcp_pipeline import ENV_NAME, IDENT
from skillforge.build.scriptfiles import CASE_SLUG, FIXTURE_PATH, SCRIPT_NAME
from skillforge.kinds import get_kind
from skillforge.sandbox.docker import IMAGE, NAME
from skillforge.validate.mcp import mcp_name_of
from skillforge.validate.plugin import name_problem
from skillforge.validate.static import SLUG

GOOD = ["my-plugin", "a", "a1-b2", "console", "nul-helper", "com10", "lpt0", "auxiliary"]
DEVICE = ["con", "prn", "aux", "nul", "com1", "com9", "lpt1", "lpt9"]


@pytest.mark.parametrize("name", GOOD)
def test_ordinary_names_are_accepted(name):
    assert SLUG.match(name) and BUILD_SLUG.match(name) and not name_problem(name)


@pytest.mark.parametrize("name", ["my-plugin\n", "x\n\n", "\n", "my-plugin\r\n", "a b", "A", "a--b", "-a", "a-"])
def test_a_trailing_newline_or_a_bad_shape_is_not_a_name(name):
    assert not SLUG.match(name) and not BUILD_SLUG.match(name)
    assert name_problem(name) != ""


@pytest.mark.parametrize("name", DEVICE)
def test_a_windows_device_name_is_not_a_name(name):
    assert not SLUG.match(name) and not BUILD_SLUG.match(name)
    assert "reserved" in name_problem(name) or name_problem(name) != ""


def test_every_kind_refuses_a_newline_and_a_device_name_from_its_own_files():
    skill = get_kind("skill")
    for bad in ("nul", "my-skill\n"):
        text = f"---\nname: {json.dumps(bad)}\ndescription: x\n---\n"  # JSON quoting is valid YAML, and keeps the newline in the name
        assert skill.name_of({"SKILL.md": text.encode()}) is None
    assert skill.name_of({"SKILL.md": b"---\nname: fine\ndescription: x\n---\n"}) == "fine"
    source = 'from mcp.server.mcpserver import MCPServer\nmcp = MCPServer("%s")\n'
    assert mcp_name_of({"server.py": (source % "nul").encode()}) is None
    assert mcp_name_of({"server.py": (source % "ok-name").encode()}) == "ok-name"


@pytest.mark.parametrize("pattern,text", [
    (IDENT, "tool_name\n"), (ENV_NAME, "API_KEY\n"), (SCRIPT_NAME, "count_it\n"), (CASE_SLUG, "a-case\n"),
    (FIXTURE_PATH, "dir/file.txt\n"), (NAME, "skillforge-abc\n"), (IMAGE, "python:3.13-slim\n"),
])
def test_the_other_identifier_patterns_are_exact_too(pattern, text):
    assert pattern.match(text.rstrip("\n")) and not pattern.match(text)
