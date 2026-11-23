"""Composing a plugin from MCP servers in the library (Component Factory, Phase 4a, task 2). Offline: nothing is run."""

from __future__ import annotations

import json

import pytest
from test_library import NAME as SKILL
from test_mcp_validate import GOOD as SERVER
from test_plugin import AGENT, make_library
from test_plugin_mcp import KEYED, NAME, ROOT

from skillforge.library import Library, NotFound
from skillforge.library.plugin import ComponentRef, PluginError, compose_for_keeping, compose_plugin
from skillforge.results import FAILED, WARNING
from skillforge.validate.plugin import MANIFEST, MCP_CONFIG

REQUIREMENTS = b"mcp==2.3.0\n"
SERVER_REF = ComponentRef("mcp", NAME)
NETWORK = SERVER.replace("return text.upper()", "import urllib.request\n    return urllib.request.urlopen(text).read().decode()")
EVERYTHING = SERVER.replace("return text.upper()", "import os\n    return str(len(os.environ))")


def server_files(source: str = SERVER) -> dict[str, bytes]:
    return {"server.py": source.encode("utf-8"), "requirements.txt": REQUIREMENTS, "README.md": b"# Word tools\n", "spec.json": b"{}"}


def library_with_servers(tmp_path, **servers: str) -> Library:
    """A library holding the given MCP servers (name -> source). Underscores in the keyword become hyphens: `word_tools`."""
    lib = Library(tmp_path / "library")
    for key, source in servers.items():
        name = key.replace("_", "-")
        lib.for_kind("mcp").add(name, server_files(source.replace('"word-tools"', f'"{name}"')), source_kind="test", source_label="test")
    return lib


def compose(lib: Library, refs=None, **kw):
    args = dict(name="my-plugin", description="Word tools for Claude.", version="0.1.0", author="Jeswin")
    args.update(kw)
    return compose_plugin(lib, [SERVER_REF] if refs is None else refs, **args)


def test_a_plugin_with_a_server_has_exactly_these_files_and_leaves_out_the_requesters_words(tmp_path):
    plan = compose(library_with_servers(tmp_path, word_tools=SERVER))
    assert sorted(plan.files) == [
        ".claude-plugin/marketplace.json", ".claude-plugin/plugin.json", ".mcp.json", "README.md",
        f"servers/{NAME}/README.md", f"servers/{NAME}/requirements.txt", f"servers/{NAME}/server.py",
    ]  # spec.json holds the requester's own words, so it stays in the library
    assert plan.files[f"servers/{NAME}/server.py"] == SERVER.encode("utf-8")
    assert plan.components == [{"kind": "mcp", "name": NAME, "version": "v1"}]


def test_mcp_json_starts_the_shipped_server_and_a_server_that_reads_nothing_gets_no_env_and_no_options(tmp_path):
    plan = compose(library_with_servers(tmp_path, word_tools=SERVER))
    assert json.loads(plan.files[MCP_CONFIG]) == {"mcpServers": {NAME: {"command": "python", "args": [f"{ROOT}/servers/{NAME}/server.py"]}}}
    assert json.loads(plan.files[MANIFEST]) == {"name": "my-plugin", "version": "0.1.0", "description": "Word tools for Claude.", "author": {"name": "Jeswin"}}


def test_each_variable_a_server_reads_becomes_a_required_secret_option_and_only_a_reference_is_written(tmp_path):
    plan = compose(library_with_servers(tmp_path, word_tools=KEYED))
    entry = json.loads(plan.files[MCP_CONFIG])["mcpServers"][NAME]
    assert entry["env"] == {"WEATHER_API_KEY": "${user_config.word_tools_weather_api_key}"}
    options = json.loads(plan.files[MANIFEST])["userConfig"]
    assert options == {"word_tools_weather_api_key": {
        "type": "string", "title": "WEATHER_API_KEY for word-tools", "required": True, "sensitive": True,
        "description": "Read by the MCP server word-tools. Claude Code asks for it when the plugin is enabled and keeps it as a secret.",
    }}
    assert not plan.failed and not [c for c in plan.checks if c.status in (FAILED, WARNING)]  # a "not run" row is the shared script check leaving it to the components


def test_two_servers_that_read_the_same_variable_ask_for_it_separately(tmp_path):
    lib = library_with_servers(tmp_path, word_tools=KEYED, other_tools=KEYED)
    plan = compose(lib, [SERVER_REF, ComponentRef("mcp", "other-tools")])
    assert sorted(json.loads(plan.files[MANIFEST])["userConfig"]) == ["other_tools_weather_api_key", "word_tools_weather_api_key"]
    assert not plan.failed


def test_a_variable_that_cannot_be_an_option_or_that_collides_is_refused_by_name(tmp_path):
    odd = SERVER.replace("return text.upper()", 'import os\n    return os.environ.get("MY-KEY", "")')
    with pytest.raises(PluginError, match="MY-KEY"):
        compose(library_with_servers(tmp_path, word_tools=odd))
    twice = SERVER.replace("return text.upper()", 'import os\n    return os.environ.get("API_KEY", "") + os.environ.get("api_key", "")')
    with pytest.raises(PluginError, match="api_key"):
        compose(library_with_servers(tmp_path / "b", word_tools=twice))


def test_what_a_server_can_do_is_computed_by_reading_its_code_and_never_called_read_only(tmp_path):
    caps = compose(library_with_servers(tmp_path, word_tools=KEYED)).capabilities
    assert caps.servers == [{
        "name": NAME, "tools": ["count_words", "shout"], "capabilities": [], "environment": ["WEATHER_API_KEY"],
        "environment_dynamic": False, "dynamic": [], "command": f"python servers/{NAME}/server.py",
    }]
    text = " ".join(caps.notes)
    assert f"'{NAME}'" in text and "starts on this machine" in text and "outside any sandbox" in text
    assert "count_words" in text and "shout" in text and "WEATHER_API_KEY" in text
    assert f"pip install -r servers/{NAME}/requirements.txt" in text
    assert "only read" not in text  # a program that runs is never "read only"
    assert [c for c in caps.by_component if c["kind"] == "mcp"] == [{"kind": "mcp", "name": NAME, "tools": [], "scripts": [], "script_capabilities": []}]


def test_a_server_that_reaches_the_network_or_reads_the_whole_environment_says_so(tmp_path):
    net = compose(library_with_servers(tmp_path, word_tools=NETWORK)).capabilities
    assert net.servers[0]["capabilities"] == ["network"]
    assert "network" in " ".join(net.notes) and "not proof" in " ".join(net.notes)
    everything = compose(library_with_servers(tmp_path / "e", word_tools=EVERYTHING)).capabilities
    assert everything.servers[0]["environment_dynamic"] is True
    assert "not written in the code" in " ".join(everything.notes)


def test_the_readme_says_what_to_install_and_how_to_give_the_options_without_a_dialog(tmp_path):
    readme = compose(library_with_servers(tmp_path, word_tools=KEYED)).files["README.md"].decode("utf-8")
    assert f"MCP server `{NAME}`" in readme
    assert f"pip install -r servers/{NAME}/requirements.txt" in readme
    assert "--config word_tools_weather_api_key=" in readme and "sk-" not in readme  # the option is named, never given a value
    assert "claude plugin install my-plugin@my-plugin-local" in readme


def test_a_server_that_fails_its_checks_fails_the_plugin_and_a_missing_one_is_not_found(tmp_path):
    hostile = SERVER.replace("return text.upper()", "import os\n    os.system('ls')\n    return text.upper()")
    plan = compose(library_with_servers(tmp_path, word_tools=hostile))
    assert plan.failed and any(c.status == FAILED and "mcp 'word-tools'" in c.name for c in plan.checks)
    with pytest.raises(NotFound):
        compose(library_with_servers(tmp_path / "x"), [ComponentRef("mcp", "no-such-server")])


def test_a_plugin_can_hold_a_skill_an_agent_and_a_server_together(tmp_path):
    lib = make_library(tmp_path)
    lib.for_kind("mcp").add(NAME, server_files(), source_kind="test", source_label="test")
    plan = compose(lib, [ComponentRef("skill", SKILL), ComponentRef("agent", AGENT), SERVER_REF])
    assert not plan.failed and [c["kind"] for c in plan.components] == ["skill", "agent", "mcp"]
    assert f"servers/{NAME}/server.py" in plan.files and f"skills/{SKILL}/SKILL.md" in plan.files and f"agents/{AGENT}.md" in plan.files


def test_an_unsupported_kind_is_refused_in_words_that_name_all_three(tmp_path):
    with pytest.raises(PluginError, match="skill, an agent or an MCP server"):
        compose(Library(tmp_path / "library"), [ComponentRef("plugin", "x")])


def test_the_version_moves_only_when_the_server_does(tmp_path):
    lib = library_with_servers(tmp_path, word_tools=SERVER)
    first = compose_for_keeping(lib, [SERVER_REF], name="my-plugin", description="Word tools.")
    assert first.version == "0.1.0"
    lib.for_kind("plugin").add("my-plugin", first.files, source_kind="test", source_label="test")
    again = compose_for_keeping(lib, [SERVER_REF], name="my-plugin", description="Word tools.")
    assert again.version == "0.1.0"  # nothing changed: no second version
    lib.for_kind("mcp").add(NAME, server_files(SERVER.replace("text.upper()", "text.upper() + '!'")), source_kind="test", source_label="test")
    changed = compose_for_keeping(lib, [SERVER_REF], name="my-plugin", description="Word tools.")
    assert changed.version == "0.1.1"
