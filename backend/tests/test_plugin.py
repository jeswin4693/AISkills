"""Composing a plugin from skills and agents already in the library, and keeping it. Offline: no model is involved at all."""

from __future__ import annotations

import json

import pytest
from test_agent_kind import agent_files
from test_library import NAME as SKILL, write_skill

from skillforge.library import Library, LibraryError, NotFound, import_skill
from skillforge.library.plugin import ComponentRef, PluginError, compose_plugin
from skillforge.results import FAILED, PASSED
from skillforge.validate import validate_files

AGENT = "demo-agent"
BOTH = [ComponentRef("skill", SKILL), ComponentRef("agent", AGENT)]


def make_library(tmp_path, skill_extra: dict[str, str] | None = None, agent_tools: str = "Read, Grep, Glob") -> Library:
    """A library holding one skill (demo-skill) and one agent (demo-agent)."""
    lib = Library(tmp_path / "library")
    assert not import_skill(write_skill(tmp_path / SKILL, **(skill_extra or {})), lib).refused
    src = tmp_path / AGENT
    src.mkdir()
    (src / "AGENT.md").write_bytes(agent_files(agent_tools)["AGENT.md"])
    assert not import_skill(src, lib.for_kind("agent")).refused
    return lib


def compose(lib: Library, components=None, **kw):
    args = dict(name="my-plugin", description="Two helpers.", version="0.1.0", author="Jeswin")
    args.update(kw)
    return compose_plugin(lib, BOTH if components is None else components, **args)


def test_a_plugin_has_exactly_these_files_and_leaves_out_the_requesters_words(tmp_path):
    plan = compose(make_library(tmp_path, {"spec.json": "{}"}))
    assert sorted(plan.files) == [
        ".claude-plugin/marketplace.json", ".claude-plugin/plugin.json", "README.md", f"agents/{AGENT}.md",
        f"skills/{SKILL}/README.md", f"skills/{SKILL}/SKILL.md",
    ]  # spec.json holds the requester's own words, so it stays in the library
    lib_files = make_library(tmp_path / "again").for_kind("agent").read(AGENT)[1]
    assert plan.files[f"agents/{AGENT}.md"] == lib_files["AGENT.md"]  # the agent is written as agents/<name>.md, as it is
    assert plan.files[f"skills/{SKILL}/SKILL.md"].startswith(b"---\nname: demo-skill\n")


def test_the_manifest_and_the_local_marketplace_carry_the_name_and_point_at_the_folder_itself(tmp_path):
    plan = compose(make_library(tmp_path))
    assert json.loads(plan.files[".claude-plugin/plugin.json"]) == {
        "name": "my-plugin", "version": "0.1.0", "description": "Two helpers.", "author": {"name": "Jeswin"},
    }
    assert json.loads(plan.files[".claude-plugin/marketplace.json"]) == {
        "name": "my-plugin-local", "description": "Two helpers.", "owner": {"name": "Jeswin"},
        "plugins": [{"name": "my-plugin", "source": "./", "description": "Two helpers."}],
    }
    anonymous = compose(make_library(tmp_path / "x"), author="")
    assert "author" not in json.loads(anonymous.files[".claude-plugin/plugin.json"])
    assert json.loads(anonymous.files[".claude-plugin/marketplace.json"])["owner"] == {"name": "me"}


def test_the_readme_says_what_is_inside_what_it_can_do_and_how_to_add_it(tmp_path):
    readme = compose(make_library(tmp_path)).files["README.md"].decode("utf-8")
    assert "my-plugin" in readme and SKILL in readme and AGENT in readme
    assert "claude plugin marketplace add" in readme and "claude plugin install my-plugin@my-plugin-local" in readme
    assert "only read and search files" in readme


@pytest.mark.parametrize("bad", ["claude-helpers", "anthropic-x", "Bad Name", "UPPER", "a" * 65, "", "-x", "x-", "a_b", "../x"])
def test_a_reserved_or_invalid_plugin_name_is_refused(tmp_path, bad):
    with pytest.raises(PluginError):
        compose(make_library(tmp_path), name=bad)


def test_a_plugin_needs_a_description_and_at_least_one_component_and_no_component_twice(tmp_path):
    lib = make_library(tmp_path)
    with pytest.raises(PluginError, match="description"):
        compose(lib, description="  ")
    with pytest.raises(PluginError, match="at least one"):
        compose(lib, components=[])
    with pytest.raises(PluginError, match="twice"):
        compose(lib, components=[ComponentRef("skill", SKILL), ComponentRef("skill", SKILL)])
    with pytest.raises(PluginError, match="skill or an agent"):
        compose(lib, components=[ComponentRef("plugin", "x")])


def test_a_component_that_is_not_in_the_library_is_not_found(tmp_path):
    lib = make_library(tmp_path)
    with pytest.raises(NotFound):
        compose(lib, components=[ComponentRef("skill", "no-such-skill")])
    with pytest.raises(NotFound):
        compose(lib, components=[ComponentRef("agent", SKILL)])  # the skill's name is not an agent's name
    with pytest.raises(NotFound):
        compose(lib, components=[ComponentRef("skill", SKILL, version=9)])


def test_a_damaged_component_can_never_end_up_inside_a_plugin(tmp_path):
    lib = make_library(tmp_path)
    stored = lib.root / SKILL / "v1" / "skill" / "SKILL.md"
    stored.write_bytes(stored.read_bytes() + b"\nSneaked in after import.\n")
    with pytest.raises(LibraryError, match="changed after import"):
        compose(lib)


def test_what_the_plugin_can_do_is_computed_from_its_tools_and_its_scripts(tmp_path):
    skill = {
        "SKILL.md": "---\nname: demo-skill\ndescription: Reads a file.\nallowed-tools: Read Bash\n---\n# Demo\n\nBody\n",
        "scripts/fetch.py": "import requests\n", "skill.sdm.json": json.dumps({"permissions": ["network"]}),
    }
    caps = compose(make_library(tmp_path, skill, agent_tools="Read, Grep, Glob, Write")).capabilities
    assert caps.tools == ["Bash", "Glob", "Grep", "Read", "Write"]
    assert caps.scripts == [f"skills/{SKILL}/scripts/fetch.py"] and caps.script_capabilities == ["network"]
    assert caps.hooks == [] and caps.mcp_servers == []  # a v1 plugin has neither
    by = {(c["kind"], c["name"]): c for c in caps.by_component}
    assert by[("skill", SKILL)]["tools"] == ["Bash", "Read"] and by[("agent", AGENT)]["tools"] == ["Glob", "Grep", "Read", "Write"]
    text = " ".join(caps.notes)
    assert "run any shell command" in text and "Bash" in text and "demo-skill" in text
    assert "create or overwrite files" in text and "demo-agent" in text
    assert "1 script" in text and "network" in text


def test_a_read_only_plugin_says_so(tmp_path):
    caps = compose(make_library(tmp_path)).capabilities
    assert caps.tools == ["Glob", "Grep", "Read"] and caps.scripts == [] and caps.notes == ["It can only read and search files."]


def test_the_composed_plugin_passes_its_own_checks_and_a_failing_one_is_reported(tmp_path):
    plan = compose(make_library(tmp_path))
    assert not [c for c in plan.checks if c.status == FAILED]
    assert any(c.name == "plugin.json exists and is a valid plugin manifest" and c.status == PASSED for c in plan.checks)
    assert plan.checks == validate_files(plan.files, folder="my-plugin", kind="plugin")  # the same checks an import would run
    assert [c["name"] for c in plan.components] == [SKILL, AGENT] and [c["version"] for c in plan.components] == ["v1", "v1"]


def test_composing_the_same_things_twice_gives_the_same_bytes(tmp_path):
    lib = make_library(tmp_path)
    assert compose(lib).files == compose(lib).files
