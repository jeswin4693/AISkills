"""What an independent review of the plugin builder found, as tests. Each one failed before the fix.

Components are stored in the library through `Library.add` (which does not gate) so a component that no longer passes the
current checks can be tested: the library gates imports, but a version stored earlier, or by an older program, still has to be
refused when it is composed into a plugin."""

from __future__ import annotations

import json

import pytest
from test_library import NAME as SKILL, write_skill
from test_plugin import AGENT, BODY, client_for, compose

from skillforge.library import Library, import_skill, rollback
from skillforge.library.plugin import ComponentRef, PluginError, compose_for_keeping
from skillforge.results import FAILED, PASSED, WARNING
from skillforge.validate.plugin import EXTRAS_CHECK, MARKETPLACE, MARKETPLACE_CHECK, MANIFEST, check_plugin_json

SKILL_REF, AGENT_REF = ComponentRef("skill", SKILL), ComponentRef("agent", AGENT)


def skill_files(tools: str = "", front: str = "", extra: dict[str, str] | None = None, head: str | None = None) -> dict[str, bytes]:
    text = head if head is not None else (
        f"---\nname: {SKILL}\ndescription: Reads a file and says what it holds.\n"
        + (f"allowed-tools: {tools}\n" if tools else "") + front + "---\n# Demo\n\nRead the file.\n"
    )
    return {"SKILL.md": text.encode(), **{path: body.encode() for path, body in (extra or {}).items()}}


def agent_files(tools: str | None = "Read, Grep, Glob", front: str = "") -> dict[str, bytes]:
    line = f"tools: {tools}\n" if tools is not None else ""
    return {"AGENT.md": f"---\nname: {AGENT}\ndescription: Reviews a diff.\n{line}{front}---\n\nYou are a reviewer.\n".encode()}


def library_with(tmp_path, skill: dict[str, bytes] | None = None, agent: dict[str, bytes] | None = None) -> Library:
    lib = Library(tmp_path / "library")
    if skill is not None:
        lib.add(SKILL, skill, source_kind="test", source_label="test")
    if agent is not None:
        lib.for_kind("agent").add(AGENT, agent, source_kind="test", source_label="test")
    return lib


def rows(plan) -> dict[str, tuple[str, str]]:
    return {c.name: (c.status, c.detail) for c in plan.checks}


def own_checks(plan, kind: str, name: str) -> tuple[str, str]:
    return rows(plan)[f"{kind} '{name}' passes its own checks"]


# ---- 1. a component that fails its own checks cannot end up inside a plugin -------------------------------------------


def test_a_skill_that_fails_its_own_checks_makes_the_plugin_fail(tmp_path):
    broken = skill_files(head="no front matter at all\n", extra={"scripts/x.py": "def broken(:\n"})
    plan = compose(library_with(tmp_path, skill=broken), [SKILL_REF])
    status, detail = own_checks(plan, "skill", SKILL)
    assert plan.failed and status == FAILED and "front matter" in detail and "syntax" in detail


def test_a_script_that_imports_the_network_in_a_stored_skill_is_shown_not_hidden(tmp_path):
    net = skill_files(extra={"scripts/net.py": "import requests\nrequests.get('http://x')\n"}, front="allowed-tools: Read\n"[:0])
    plan = compose(library_with(tmp_path, skill=net), [SKILL_REF])
    assert "network" in plan.capabilities.script_capabilities
    assert any("network" in note for note in plan.capabilities.notes)


def test_an_agent_without_a_tools_line_makes_the_plugin_fail(tmp_path):
    plan = compose(library_with(tmp_path, agent=agent_files(tools=None)), [AGENT_REF])
    status, detail = own_checks(plan, "agent", AGENT)
    assert plan.failed and status == FAILED and "tools" in detail


def test_an_agent_that_skips_approval_or_runs_code_is_flagged_for_the_person_to_read(tmp_path):
    risky = agent_files(front="permissionMode: bypassPermissions\nhooks:\n  PreToolUse: x\nmcpServers: {a: {command: x}}\n")
    plan = compose(library_with(tmp_path, agent=risky), [AGENT_REF])
    status, detail = own_checks(plan, "agent", AGENT)
    assert status == WARNING and "skips approval" in detail and not plan.failed


def test_a_clean_component_passes_its_own_checks(tmp_path):
    plan = compose(library_with(tmp_path, skill=skill_files(), agent=agent_files()))
    assert own_checks(plan, "skill", SKILL)[0] == PASSED and own_checks(plan, "agent", AGENT)[0] == PASSED


def test_a_plugin_from_outside_with_a_failing_nested_skill_is_refused(tmp_path):
    good = compose(library_with(tmp_path, skill=skill_files(), agent=agent_files())).files
    broken = {**good, f"skills/{SKILL}/SKILL.md": b"no front matter\n"}
    assert any(c.status == FAILED and c.name == f"skill '{SKILL}' passes its own checks" for c in check_plugin_json(broken, "my-plugin"))


def test_the_shared_script_rows_do_not_claim_a_pass_for_scripts_they_never_looked_at(tmp_path):
    net = skill_files(extra={"scripts/x.py": "def broken(:\n"})
    plan = compose(library_with(tmp_path, skill=net), [SKILL_REF])
    claims = [(n, d) for n, (s, d) in rows(plan).items() if s == PASSED and "this skill has no scripts" in d]
    assert claims == []


# ---- 2. what the plugin can do is described honestly -------------------------------------------------------------------


def notes_for(tmp_path, skill: dict[str, bytes] | None = None, agent: dict[str, bytes] | None = None):
    refs = [r for r, files in ((SKILL_REF, skill), (AGENT_REF, agent)) if files is not None]
    return compose(library_with(tmp_path, skill=skill, agent=agent), refs).capabilities


@pytest.mark.parametrize("tools", ["Bash(*)", "Bash(rm *)", "Read Bash(git push *)"])
def test_a_scoped_bash_is_still_bash(tmp_path, tools):
    caps = notes_for(tmp_path, skill=skill_files(tools=tools))
    assert "Bash" in caps.tools and any("shell command" in n for n in caps.notes)
    assert not any("only read" in n for n in caps.notes)


def test_an_agent_tools_line_with_a_scoped_tool_is_split_on_commas_not_inside_the_brackets(tmp_path):
    caps = notes_for(tmp_path, agent=agent_files(tools="Read, Bash(git *), Grep"))
    assert caps.tools == ["Bash", "Grep", "Read"]
    assert any("shell command" in n for n in caps.notes)


@pytest.mark.parametrize("tools,named", [("mcp__x__delete NotebookEdit", ["mcp__x__delete", "NotebookEdit"]), ("bash write", ["bash", "write"]), ("PowerShell Task", ["PowerShell", "Task"])])
def test_a_tool_that_is_not_described_is_named_never_called_read_only(tmp_path, tools, named):
    caps = notes_for(tmp_path, skill=skill_files(tools=tools))
    text = " ".join(caps.notes)
    assert all(n in text for n in named) and "only read" not in text


def test_only_reading_tools_and_nothing_else_is_called_read_only(tmp_path):
    caps = notes_for(tmp_path, skill=skill_files(tools="Read Grep Glob"), agent=agent_files())
    assert caps.notes == ["It can only read and search files."]


def test_hooks_and_mcp_servers_in_a_components_front_matter_are_listed_and_noted(tmp_path):
    skill = skill_files(front="hooks:\n  PreToolUse:\n    - command: whoami\n")
    agent = agent_files(front="mcpServers: {a: {command: x}}\npermissionMode: bypassPermissions\n")
    caps = notes_for(tmp_path, skill=skill, agent=agent)
    assert caps.hooks == [f"skill {SKILL}"] and caps.mcp_servers == [f"agent {AGENT}"]
    text = " ".join(caps.notes).lower()
    assert "hooks" in text and "mcp server" in text and "bypass" in text and "only read" not in text


def test_code_anywhere_in_a_skill_is_shipped_code_not_only_a_scripts_folder(tmp_path):
    skill = skill_files(extra={"helpers/run.py": "import subprocess\nsubprocess.run(['ls'])\n", "bin/tool.sh": "echo hi\n"})
    caps = notes_for(tmp_path, skill=skill)
    assert sorted(caps.scripts) == [f"skills/{SKILL}/bin/tool.sh", f"skills/{SKILL}/helpers/run.py"]
    assert "run_commands" in caps.script_capabilities
    assert not any("only read" in n for n in caps.notes)
    assert any("bin/tool.sh" in n for n in caps.notes)  # a shell script cannot be analysed, so it is named for the person to read


# ---- 3. a plugin zip from outside: what it carries is shown, and a remote source is refused -----------------------------


def plugin_files(tmp_path) -> dict[str, bytes]:
    return dict(compose(library_with(tmp_path, skill=skill_files(), agent=agent_files())).files)


def result_rows(files):
    return {c.name: c for c in check_plugin_json(files, "my-plugin")}


def test_a_composed_plugin_has_none_of_the_extras(tmp_path):
    assert result_rows(plugin_files(tmp_path))[EXTRAS_CHECK].status == PASSED


@pytest.mark.parametrize("path,body", [
    ("hooks/hooks.json", '{"hooks": {"PreToolUse": []}}'), (".mcp.json", '{"mcpServers": {}}'), ("bin/tool", "#!/bin/sh\necho hi\n"),
    ("settings.json", "{}"), ("skills/demo-skill/hooks/hooks.json", "{}"),
])
def test_hooks_mcp_servers_executables_and_settings_in_a_plugin_from_outside_are_warned_about(tmp_path, path, body):
    files = {**plugin_files(tmp_path), path: body.encode()}
    got = result_rows(files)[EXTRAS_CHECK]
    assert got.status == WARNING and path in got.detail


def test_hooks_or_mcp_servers_written_in_the_manifest_are_warned_about(tmp_path):
    files = plugin_files(tmp_path)
    manifest = json.loads(files[MANIFEST])
    manifest["hooks"] = {"PreToolUse": []}
    manifest["mcpServers"] = {"a": {"command": "x"}}
    files[MANIFEST] = json.dumps(manifest).encode()
    got = result_rows(files)[EXTRAS_CHECK]
    assert got.status == WARNING and "hooks" in got.detail and "mcpServers" in got.detail


@pytest.mark.parametrize("source,ok", [("./", True), ({"source": "github", "repo": "evil/payload"}, False), ("./other", False), ("https://x.test/p.git", False)])
def test_a_marketplace_entry_must_point_at_this_folder_itself(tmp_path, source, ok):
    files = plugin_files(tmp_path)
    market = json.loads(files[MARKETPLACE])
    market["plugins"][0]["source"] = source
    files[MARKETPLACE] = json.dumps(market).encode()
    got = result_rows(files)[MARKETPLACE_CHECK]
    assert (got.status == PASSED) is ok
    assert ok or "this folder" in got.detail


# ---- 4. versions never repeat, and the manifest always has an author -------------------------------------------------


def manifest_version(lib: Library, number: int) -> str:
    return json.loads(lib.for_kind("plugin").read("my-plugin", number)[1][MANIFEST])["version"]


def test_a_new_version_after_a_rollback_never_reuses_a_plugin_version_number(tmp_path):
    client, lib = client_for(tmp_path)
    client.post("/api/plugins", json=BODY)  # v1 = 0.1.0
    import_skill(write_skill(tmp_path / SKILL, body="Second body.\n"), lib)
    client.post("/api/plugins", json=BODY)  # v2 = 0.1.1
    rollback(lib.for_kind("plugin"), "my-plugin", 1)  # v3 has the content of v1
    import_skill(write_skill(tmp_path / SKILL, body="Third body.\n"), lib)
    client.post("/api/plugins", json=BODY)  # must not be 0.1.1 again: Claude Code pins a version
    versions = [manifest_version(lib, n) for n in range(1, len(lib.for_kind("plugin").versions("my-plugin")) + 1)]
    assert versions[:3] == ["0.1.0", "0.1.1", "0.1.0"] and versions[3] == "0.1.2"
    assert len(versions) == 4


def test_composing_after_a_rollback_never_reuses_the_version_that_means_something_else(tmp_path):
    client, lib = client_for(tmp_path)
    client.post("/api/plugins", json=BODY)
    import_skill(write_skill(tmp_path / SKILL, body="Second body.\n"), lib)
    client.post("/api/plugins", json=BODY)
    rollback(lib.for_kind("plugin"), "my-plugin", 1)
    plan = compose_for_keeping(lib, [SKILL_REF, AGENT_REF], name="my-plugin", description="Two helpers.", author="Jeswin")
    assert plan.version in ("0.1.0", "0.1.2")  # never 0.1.1, which already means something else


def test_a_manifest_always_names_an_author_because_claude_code_validate_wants_one(tmp_path):
    plan = compose(library_with(tmp_path, skill=skill_files(), agent=agent_files()), author="")
    manifest = json.loads(plan.files[MANIFEST])
    assert manifest["author"]["name"] and manifest["author"] == {"name": json.loads(plan.files[MARKETPLACE])["owner"]["name"]}


# ---- 5. bad input is a plain error, never a crash -----------------------------------------------------------------------


def test_a_description_that_cannot_be_written_as_text_is_a_plain_error(tmp_path):
    lib = library_with(tmp_path, skill=skill_files())
    with pytest.raises(PluginError, match="text"):
        compose(lib, [SKILL_REF], description="broken \ud800 text")
    with pytest.raises(PluginError, match="text"):
        compose(lib, [SKILL_REF], author="broken \ud800 text")


def test_a_plugin_that_could_not_be_imported_back_because_it_is_too_big_is_refused_when_composed(tmp_path):
    many = skill_files(extra={f"refs/f{i}.md": "x\n" for i in range(1001)})
    with pytest.raises(PluginError, match="1000"):
        compose(library_with(tmp_path, skill=many), [SKILL_REF])


def test_the_api_refuses_a_name_with_a_newline_and_a_text_that_cannot_be_encoded(tmp_path):
    client, lib = client_for(tmp_path)
    for body in ({**BODY, "name": "my-plugin\n"}, {**BODY, "description": "broken \ud800"}):
        for route in ("/api/plugins/preview", "/api/plugins"):
            sent = client.post(route, content=json.dumps(body), headers={"content-type": "application/json"})  # the lone character goes out as an escape
            assert sent.status_code in (400, 422), (body, route, sent.status_code)
    assert lib.for_kind("plugin").names() == []


# ---- 6. the risk diff between two versions of a plugin looks inside its components ---------------------------------------


def plugin_files_for(tmp_path, name: str, **kw) -> dict[str, bytes]:
    return dict(compose(library_with(tmp_path / name, **kw), [r for r, f in ((SKILL_REF, kw.get("skill")), (AGENT_REF, kw.get("agent"))) if f is not None]).files)


def test_a_plugin_version_whose_skill_gained_bash_and_hooks_is_riskier(tmp_path):
    from skillforge.library import risk_diff

    v1 = plugin_files_for(tmp_path, "one", skill=skill_files(tools="Read"))
    v2 = plugin_files_for(tmp_path, "two", skill=skill_files(tools="Read Bash Write", front="hooks:\n  PreToolUse:\n    - command: whoami\n"))
    report = risk_diff(v1, v2, "v1", "v2", kind="plugin")
    tools = [c for c in report.changes if c.kind == "tool"]
    assert tools and tools[0].direction == "riskier" and SKILL in tools[0].detail and "Bash" in tools[0].detail
    assert tools[0].path == f"skills/{SKILL}/SKILL.md"
    assert report.level == "more_risk"


def test_a_plugin_version_that_only_bumps_its_number_is_not_flagged(tmp_path):
    from skillforge.library import risk_diff

    lib = library_with(tmp_path, skill=skill_files(), agent=agent_files())
    a = compose(lib, version="0.1.0").files
    b = compose(lib, version="0.1.1").files
    report = risk_diff(a, b, "v1", "v2", kind="plugin")
    assert report.level == "no_new_risk" and not any("agent follows" in c.detail for c in report.changes)


def test_a_component_added_to_a_plugin_is_reported_and_a_removed_one_is_safer(tmp_path):
    from skillforge.library import risk_diff

    only_skill = plugin_files_for(tmp_path, "one", skill=skill_files(tools="Read"))
    both = plugin_files_for(tmp_path, "two", skill=skill_files(tools="Read"), agent=agent_files(tools="Read, Bash"))
    added = [c for c in risk_diff(only_skill, both, "v1", "v2", kind="plugin").changes if c.kind == "component_added"]
    assert len(added) == 1 and added[0].direction == "riskier" and AGENT in added[0].detail and "Bash" in added[0].detail
    removed = [c for c in risk_diff(both, only_skill, "v2", "v3", kind="plugin").changes if c.kind == "component_removed"]
    assert len(removed) == 1 and removed[0].direction == "safer"
    harmless = plugin_files_for(tmp_path, "three", skill=skill_files(tools="Read"), agent=agent_files())
    assert [c.direction for c in risk_diff(only_skill, harmless, "v1", "v2", kind="plugin").changes if c.kind == "component_added"] == ["look"]
