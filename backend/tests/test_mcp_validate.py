"""The checks on an MCP server's own file, `server.py`. They read the code and run nothing."""

from __future__ import annotations

import pytest

from skillforge.results import FAILED, PASSED, WARNING
from skillforge.validate import DEFINITION_CHECKS, validate_files
from skillforge.validate.mcp import (
    COMMANDS_CHECK, DEFINITION_CHECK, DESCRIBED_CHECK, ENV_CHECK, FOLDER_CHECK, IMPORTS_CHECK, NETWORK_CHECK, SECRETS_CHECK,
    WRITES_CHECK, analyze_server, check_server_py, mcp_name_of,
)

GOOD = '''"""Word tools."""
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

mcp = MCPServer("word-tools")


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
def count_words(text: str) -> str:
    """Count the words in a text."""
    return str(len(text.split()))


@mcp.tool()
def shout(text: str) -> str:
    """Return the text in capital letters."""
    return text.upper()


if __name__ == "__main__":
    mcp.run()
'''


def files(source: str) -> dict[str, bytes]:
    return {"server.py": source.encode("utf-8")}


def rows(source: str, folder: str | None = "word-tools") -> dict[str, tuple[str, str]]:
    return {c.name: (c.status, c.detail) for c in check_server_py(files(source), folder)}


def status(source: str, name: str, folder: str | None = "word-tools") -> str:
    return rows(source, folder)[name][0]


def with_body(extra: str, imports: str = "") -> str:
    """GOOD with one more tool whose body is `extra`, and optional extra imports at the top."""
    tool = f'\n\n@mcp.tool()\ndef extra(text: str) -> str:\n    """Do one more thing."""\n' + "".join(f"    {line}\n" for line in extra.splitlines())
    return GOOD.replace('if __name__', tool.lstrip("\n") + '\n\nif __name__').replace("from mcp.types", imports + "from mcp.types")


# ---- a good server -------------------------------------------------------------------------------------


def test_a_well_formed_server_passes_every_check():
    got = rows(GOOD)
    assert {s for s, _ in got.values()} == {PASSED}
    assert {DEFINITION_CHECK, FOLDER_CHECK, DESCRIBED_CHECK, COMMANDS_CHECK, SECRETS_CHECK, NETWORK_CHECK, WRITES_CHECK, IMPORTS_CHECK, ENV_CHECK} <= set(got)


def test_the_facts_read_from_the_code():
    facts = analyze_server(GOOD)
    assert facts.server_name == "word-tools"
    assert [t.name for t in facts.tools] == ["count_words", "shout"] and all(t.described for t in facts.tools)
    assert facts.capabilities == set() and facts.env_names == set() and not facts.env_dynamic and facts.secrets == []
    assert facts.calls_run and {"mcp"} <= facts.imports


def test_the_name_comes_from_the_server_and_must_be_a_safe_name():
    assert mcp_name_of(files(GOOD)) == "word-tools"
    assert mcp_name_of(files(GOOD.replace('"word-tools"', '"Word Tools"'))) is None
    assert mcp_name_of(files("not python (")) is None
    assert mcp_name_of({}) is None


# ---- what makes it not a server -----------------------------------------------------------------------


@pytest.mark.parametrize("source,why", [
    ("def broken(:\n", "syntax"),
    ("print('hello')\n", "MCPServer"),
    ('from mcp.server.mcpserver import MCPServer\nmcp = MCPServer("word-tools")\nmcp.run()\n', "tool"),
    ('from mcp.server.mcpserver import MCPServer\nmcp = MCPServer("word-tools")\n@mcp.tool()\ndef a() -> str:\n    """x"""\n    return "x"\n', "run"),
])
def test_a_file_that_is_not_a_runnable_server_fails_with_a_reason(source, why):
    assert status(source, DEFINITION_CHECK) == FAILED
    assert why.lower() in rows(source)[DEFINITION_CHECK][1].lower()


def test_a_missing_or_unreadable_file_fails():
    assert check_server_py({}, "x")[0].status == FAILED
    assert check_server_py({"server.py": b"\xff\xfe\x00"}, "x")[0].status == FAILED


def test_the_folder_must_have_the_servers_name():
    assert status(GOOD, FOLDER_CHECK, folder="other-name") == FAILED
    assert status(GOOD, FOLDER_CHECK, folder=None) == PASSED  # a zip or a memory copy has no folder name to compare


def test_a_tool_without_a_description_is_a_warning():
    bare = GOOD.replace('    """Count the words in a text."""\n', "")
    assert status(bare, DESCRIBED_CHECK) == WARNING and "count_words" in rows(bare)[DESCRIBED_CHECK][1]


# ---- what runs on the person's machine: these fail ------------------------------------------------------


@pytest.mark.parametrize("extra,imports", [
    ('import subprocess\nreturn subprocess.run(["ls"], capture_output=True, text=True).stdout', ""),
    ("import os\nos.system('ls')\nreturn 'x'", ""),
    ("return str(eval(text))", ""),
    ("exec(text)\nreturn 'x'", ""),
    ("return str(__import__('os').listdir('.'))", ""),
    ("return str(ctypes.c_int(1))", "import ctypes\n"),
])
def test_commands_dynamic_code_and_native_code_fail(extra, imports):
    assert status(with_body(extra, imports), COMMANDS_CHECK) == FAILED


@pytest.mark.parametrize("literal", [
    "sk-" + "a1" * 12,
    "AIza" + "B" * 35,
    "ghp_" + "c" * 36,
    "xoxb-" + "1234567890-abcdef",
    "AKIA" + "Z" * 16,
    "-----BEGIN RSA PRIVATE KEY-----",
    "Bearer " + "q" * 30,
])
def test_a_key_shaped_literal_fails(literal):
    source = with_body(f'return "{literal}"')
    assert status(source, SECRETS_CHECK) == FAILED
    assert literal not in rows(source)[SECRETS_CHECK][1]  # the report must not repeat the secret


def test_ordinary_text_is_not_a_secret():
    assert status(with_body('return "The quick brown fox jumps over the lazy dog"'), SECRETS_CHECK) == PASSED


# ---- what is only worth reading: these warn --------------------------------------------------------------


def test_network_use_warns_and_names_the_tool_that_needs_it():
    source = with_body('import urllib.request\nreturn urllib.request.urlopen(text).read().decode()')
    assert status(source, NETWORK_CHECK) == WARNING
    assert analyze_server(source).capabilities == {"network"}


def test_writing_files_warns():
    assert status(with_body('open("out.txt", "w").write(text)\nreturn "x"'), WRITES_CHECK) == WARNING
    assert status(with_body('from pathlib import Path\nPath("o").write_text(text)\nreturn "x"'), WRITES_CHECK) == WARNING


def test_reading_files_is_seen_but_does_not_warn():
    source = with_body('from pathlib import Path\nreturn Path(text).read_text()')
    assert "read_files" in analyze_server(source).capabilities
    assert {s for s, _ in rows(source).values()} == {PASSED}


def test_a_package_outside_the_standard_library_warns():
    source = with_body("return requests.get(text).text", "import requests\n")
    assert status(source, IMPORTS_CHECK) == WARNING and "requests" in rows(source)[IMPORTS_CHECK][1]
    assert status(with_body("return 'x'", "import json\nimport re\n"), IMPORTS_CHECK) == PASSED


def test_environment_variables_are_read_by_literal_name_only():
    named = with_body('import os\nreturn os.environ.get("WEATHER_API_KEY", "")', "")
    facts = analyze_server(named)
    assert facts.env_names == {"WEATHER_API_KEY"} and not facts.env_dynamic
    assert status(named, ENV_CHECK) == PASSED and "WEATHER_API_KEY" in rows(named)[ENV_CHECK][1]
    for body in ('import os\nreturn os.environ.get(text, "")', 'import os\nreturn str(dict(os.environ))', 'import os\nreturn os.environ[text]'):
        assert analyze_server(with_body(body)).env_dynamic
        assert status(with_body(body), ENV_CHECK) == WARNING
    assert analyze_server(with_body('import os\nreturn os.getenv("A_B")')).env_names == {"A_B"}
    assert analyze_server(with_body('import os\nreturn os.environ["A_B"]')).env_names == {"A_B"}


# ---- wired into the kind-wide checks -------------------------------------------------------------------


def test_the_server_check_is_registered_and_runs_with_every_other_check():
    assert DEFINITION_CHECKS["mcp"] is check_server_py
    names = {c.name for c in validate_files(files(GOOD), folder="word-tools", kind="mcp")}
    assert DEFINITION_CHECK in names and "no symbolic links or paths that leave the folder" in names
    assert all(c.status == PASSED for c in validate_files(files(GOOD), folder="word-tools", kind="mcp"))


def test_a_hostile_server_fails_the_whole_folder_check():
    bad = with_body("import os\nos.system('ls')\nreturn 'x'")
    assert any(c.status == FAILED for c in validate_files(files(bad), folder="word-tools", kind="mcp"))
