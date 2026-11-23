"""Composing a plugin that carries hooks from the catalogue (Component Factory, Phase 4b, task 2). Offline: nothing is run."""

from __future__ import annotations

import json

import pytest
from test_plugin import AGENT, make_library
from test_library import NAME as SKILL

from skillforge.hookcatalog.catalogue import get_entry, script_bytes
from skillforge.library import Library
from skillforge.library.plugin import ComponentRef, PluginError, compose_for_keeping, compose_plugin
from skillforge.results import FAILED
from skillforge.validate.plugin import MANIFEST

FORCE = ComponentRef("hook", "block-force-push")
SECRETS = ComponentRef("hook", "block-secret-files", options={"also": ["secrets.json", "*.token"]})
LOG = ComponentRef("hook", "log-tool-calls")
HOOKS = "hooks/hooks.json"
ROOT = "${CLAUDE_PLUGIN_ROOT}"


def compose(tmp_path, refs, **kw):
    args = dict(name="my-plugin", description="Safety hooks.", version="0.1.0", author="Jeswin")
    args.update(kw)
    return compose_plugin(Library(tmp_path / "library"), refs, **args)


def test_a_plugin_with_one_hook_has_the_hooks_file_and_the_catalogues_script_unchanged(tmp_path):
    plan = compose(tmp_path, [FORCE])
    assert sorted(plan.files) == [".claude-plugin/marketplace.json", ".claude-plugin/plugin.json", "README.md", "hooks/block-force-push.py", HOOKS]
    assert plan.files["hooks/block-force-push.py"] == script_bytes(get_entry("block-force-push"))
    assert json.loads(plan.files[HOOKS]) == {"hooks": {"PreToolUse": [{
        "matcher": "Bash|PowerShell",
        "hooks": [{"type": "command", "command": "python", "args": [f"{ROOT}/hooks/block-force-push.py"], "timeout": 10}],
    }]}}
    assert plan.components == [{"kind": "hook", "name": "block-force-push", "version": "r1"}]
    assert json.loads(plan.files[MANIFEST]) == {"name": "my-plugin", "version": "0.1.0", "description": "Safety hooks.", "author": {"name": "Jeswin"}}


def test_hooks_on_one_event_stay_separate_groups_in_the_order_given_and_options_are_separate_arguments(tmp_path):
    plan = compose(tmp_path, [LOG, SECRETS, FORCE])
    hooks = json.loads(plan.files[HOOKS])["hooks"]
    assert list(hooks) == ["PostToolUse", "PreToolUse"]  # events in the order they first appear
    assert [g.get("matcher") for g in hooks["PreToolUse"]] == ["Read|Write|Edit|NotebookEdit", "Bash|PowerShell"]
    assert hooks["PreToolUse"][0]["hooks"][0]["args"] == [f"{ROOT}/hooks/block-secret-files.py", "--also", "secrets.json", "--also", "*.token"]
    assert "matcher" not in hooks["PostToolUse"][0]  # every tool
    assert sorted(p for p in plan.files if p.startswith("hooks/")) == [
        "hooks/block-force-push.py", "hooks/block-secret-files.py", HOOKS, "hooks/log-tool-calls.py",
    ]


def test_what_a_hook_does_is_said_plainly_and_a_hook_is_never_read_only(tmp_path):
    caps = compose(tmp_path, [SECRETS, LOG]).capabilities
    assert [h["id"] for h in caps.hook_entries] == ["block-secret-files", "log-tool-calls"]
    first = caps.hook_entries[0]
    assert (first["event"], first["matcher"], first["effect"], first["options"]) == (
        "PreToolUse", "Read|Write|Edit|NotebookEdit", "blocks", {"also": ["secrets.json", "*.token"]},
    ) and first["powers"] == [] and first["command"] == "python hooks/block-secret-files.py"
    assert caps.hook_entries[1]["powers"] == ["write_files"] and caps.hook_entries[1]["effect"] == "observes"
    text = " ".join(caps.notes)
    assert "block-secret-files" in text and "outside any sandbox" in text and "every time Claude Code is about to use Read, Write, Edit or NotebookEdit" in text
    assert "can stop what Claude is about to do" in text and "only looks" in text
    assert "secrets.json, *.token" in text  # the options that were chosen are said
    assert "log-tool-calls" in text and "has used any tool" in text and "write files" in text
    assert "policy aid" in text and "does not block" in text  # a hook matches names and text, and if it cannot read the event it lets it through
    assert "only read" not in text


def test_a_hook_that_reaches_nothing_says_so_and_the_python_it_needs(tmp_path):
    text = " ".join(compose(tmp_path, [FORCE]).capabilities.notes)
    assert "does not reach the network, start programs or write files" in text and "python" in text


def test_the_readme_lists_the_hooks_and_what_to_know(tmp_path):
    readme = compose(tmp_path, [SECRETS, FORCE]).files["README.md"].decode("utf-8")
    assert "hook `block-secret-files`" in readme and "hook `block-force-push`" in readme
    assert "## Hooks" in readme and "PreToolUse" in readme and "Bash|PowerShell" in readme and "python" in readme
    assert "claude plugin install my-plugin@my-plugin-local" in readme


@pytest.mark.parametrize("ref,why", [
    (ComponentRef("hook", "run-anything"), "not a hook in the catalogue"),
    (ComponentRef("hook", "block-secret-files", options={"also": ["a;b"]}), "not allowed"),
    (ComponentRef("hook", "block-secret-files", options={"nope": ["x"]}), "no option"),
    (ComponentRef("hook", "block-force-push", options={"also": ["x"]}), "no option"),
    (ComponentRef("hook", "block-force-push", version=2), "no version"),
])
def test_a_hook_that_is_not_in_the_catalogue_or_has_a_bad_option_is_refused(tmp_path, ref, why):
    with pytest.raises(PluginError, match=why):
        compose(tmp_path, [ref])


def test_a_hook_cannot_be_listed_twice(tmp_path):
    with pytest.raises(PluginError, match="twice"):
        compose(tmp_path, [FORCE, FORCE])


def test_options_on_a_skill_or_an_agent_are_refused_because_only_hooks_have_them(tmp_path):
    lib = make_library(tmp_path)
    with pytest.raises(PluginError, match="options"):
        compose_plugin(lib, [ComponentRef("skill", SKILL, options={"also": ["x"]})], name="my-plugin", description="d")


def test_a_plugin_can_hold_a_skill_an_agent_a_hook_together_and_none_of_it_fails_its_checks(tmp_path):
    lib = make_library(tmp_path)
    plan = compose_plugin(lib, [ComponentRef("skill", SKILL), ComponentRef("agent", AGENT), FORCE], name="my-plugin", description="d", author="me")
    assert not plan.failed and not [c for c in plan.checks if c.status == FAILED]
    assert [c["kind"] for c in plan.components] == ["skill", "agent", "hook"]
    assert f"skills/{SKILL}/SKILL.md" in plan.files and f"agents/{AGENT}.md" in plan.files and HOOKS in plan.files


def test_the_version_moves_only_when_the_hooks_do(tmp_path):
    lib = Library(tmp_path / "library")
    kwargs = dict(name="my-plugin", description="Safety hooks.")
    first = compose_for_keeping(lib, [SECRETS], **kwargs)
    assert first.version == "0.1.0"
    lib.for_kind("plugin").add("my-plugin", first.files, source_kind="test", source_label="test")
    assert compose_for_keeping(lib, [SECRETS], **kwargs).version == "0.1.0"  # nothing changed
    changed = compose_for_keeping(lib, [ComponentRef("hook", "block-secret-files", options={"also": ["other.key"]})], **kwargs)
    assert changed.version == "0.1.1"  # a changed option is a changed plugin
