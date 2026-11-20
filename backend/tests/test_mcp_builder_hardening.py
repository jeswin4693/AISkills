"""The MCP builder after an independent review: model-written tool bodies may use only an allow-list of safe standard-library
modules, tool names cannot be spliced into the file as code, and what is written into server.py and the README is exact and honest."""

from __future__ import annotations

import ast

import pytest
from test_mcp_build import NOW, defn_and_files, draft, extra_cases, failed, spec, with_tool

from skillforge.build.mcp import McpDesignError, McpParam, McpTool, assemble_mcp, render_mcp_files
from skillforge.build.mcp_pipeline import build_mcp_from_spec, check_mcp
from skillforge.build.pipeline import BuildError
from skillforge.providers import MockProvider
from skillforge.results import FAILED

ALLOW = "allow-listed"


def one_tool(body: list[str], **kw):
    return draft(tools=[with_tool(body=body)], cases=extra_cases(), **kw)


def decorator_of(source: str, tool: str) -> str:
    return source[: source.index(f"def {tool}(")].splitlines()[-1]


# ---- the allow-list ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("body", [
    ["import json", "return json.dumps({'a': text})"], ["import re", "return re.sub('a', 'b', text)"], ["import math", "return str(math.sqrt(4))"],
    ["from datetime import datetime", "return datetime(2020, 1, 1).isoformat()"], ["import urllib.parse", "return urllib.parse.quote(text)"],
    ["from collections import Counter", "return str(Counter(text))"], ["import io", "return io.StringIO(text).read()"],
    ["from xml.etree import ElementTree", "return ElementTree.fromstring(text).tag"], ["import hashlib", "return hashlib.sha256(text.encode()).hexdigest()"],
    ["return text.upper()"],
])
def test_ordinary_safe_standard_library_code_is_allowed(body):
    assert not [n for n in failed(one_tool(body)) if ALLOW in n]


@pytest.mark.parametrize("body", [
    ["import logging", "logging.info(text)", "return text"], ["import tempfile", "return tempfile.gettempdir()"], ["import sys", "return sys.platform"],
    ["import platform", "return platform.system()"], ["import socket", "return socket.gethostname()"], ["import types", "return str(types.ModuleType)"],
    ["import os", "return os.path.join(text, 'a')"], ["import os", "return str(os.listdir('.'))"], ["from os import system", "return str(system)"],
    ["import io", "return str(io.open)"], ["from pathlib import Path", "return str(Path(text).read_text())"],
    ["print(text)", "return text"], ["return str(getattr(text, 'upper')())"], ["import inspect", "return str(inspect.stack())"],
    ["import glob", "return str(glob.glob(text))"], ["import gzip", "return str(gzip.open)"],
])
def test_anything_off_the_list_fails_in_the_builder(body):
    assert any(ALLOW in n for n in failed(one_tool(body))), body


def test_the_environment_may_be_read_but_nothing_else_of_os():
    ok = one_tool(["import os", 'return os.environ.get("API_TOKEN", "")'], env_vars=["API_TOKEN"])
    assert not [n for n in failed(ok) if ALLOW in n]
    from_import = one_tool(["from os import environ", 'return environ["API_TOKEN"]'], env_vars=["API_TOKEN"])
    assert not [n for n in failed(from_import) if ALLOW in n]


def test_network_modules_need_the_network_permission_and_files_need_read_files():
    net = ["import urllib.request", "return urllib.request.urlopen(text).read().decode()"]
    assert any(ALLOW in n for n in failed(one_tool(net)))
    assert not [n for n in failed(one_tool(net, permissions=["network"])) if ALLOW in n]
    read = ["from pathlib import Path", "return Path(text).read_text()"]
    assert any(ALLOW in n for n in failed(one_tool(read)))
    assert not [n for n in failed(one_tool(read, permissions=["read_files"])) if ALLOW in n]
    pure = ["from pathlib import PurePosixPath", "return PurePosixPath(text).name"]
    assert not [n for n in failed(one_tool(pure)) if ALLOW in n]


# ---- names are data, never code --------------------------------------------------------------------------------------------


EVIL_NAME = "extra(text: str) -> str:\n    return text\n\nfrom os import system\nsystem('calc')\n\n\ndef other"


def test_a_tool_name_that_is_code_cannot_be_written_into_the_file():
    defn = assemble_mcp(draft(tools=[with_tool(name=EVIL_NAME)], cases=extra_cases()), spec(), MockProvider([]), NOW)
    with pytest.raises(McpDesignError, match="not a valid"):
        render_mcp_files(defn, spec())


def test_a_parameter_name_that_is_code_cannot_be_written_into_the_file():
    bad = with_tool(params=[McpParam(name="text: str = __import__('os').system('calc')", type="str", description="x")])
    defn = assemble_mcp(draft(tools=[bad], cases=extra_cases()), spec(), MockProvider([]), NOW)
    with pytest.raises(McpDesignError):
        render_mcp_files(defn, spec())


def test_a_build_with_such_a_name_writes_nothing_and_a_repair_can_fix_it(tmp_path):
    evil = draft(tools=[with_tool(name=EVIL_NAME)], cases=extra_cases())
    with pytest.raises(BuildError, match="not a valid"):
        build_mcp_from_spec(spec(), MockProvider([evil, evil]), out_root=tmp_path, now=NOW)
    assert list(tmp_path.iterdir()) == []  # not even a DRAFT folder with the code in it
    built = build_mcp_from_spec(spec(), MockProvider([evil, draft()]), out_root=tmp_path, now=NOW)
    assert built.definition.tools[0].name == "count_words"


# ---- what is written is exact ----------------------------------------------------------------------------------------------


def test_a_description_that_ends_in_a_quote_still_makes_a_valid_server():
    d = draft(tools=[with_tool(description='Return the word "hello"', params=[])], cases=[])
    _, files = defn_and_files(d)
    tree = ast.parse(files["server.py"])
    doc = next(ast.get_docstring(n) for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "extra")
    assert doc == 'Return the word "hello"'


def test_a_multi_line_string_in_a_tool_body_keeps_its_exact_value():
    body = ['out = """first line', 'line at column zero', '  indented line"""', "return out"]
    _, files = defn_and_files(one_tool(body))
    values = [n.value for n in ast.walk(ast.parse(files["server.py"])) if isinstance(n, ast.Constant) and isinstance(n.value, str) and "first line" in n.value]
    assert values == ["first line\nline at column zero\n  indented line"]


def test_comments_in_a_tool_body_do_not_reach_the_file():
    _, files = defn_and_files(one_tool(["# a comment that could carry anything", "return text"]))
    assert "a comment that could carry anything" not in files["server.py"]


# ---- the hints the file publishes are true, and the README says what was found ----------------------------------------------


def test_a_tool_that_writes_by_any_spelling_is_not_marked_read_only():
    d = draft(tools=[with_tool(body=["import os as o", "o.write(1, b'x')", "return text"]), with_tool(name="pure", body=["return text"])], cases=extra_cases())
    _, files = defn_and_files(d)
    assert "read_only_hint=False" in decorator_of(files["server.py"], "extra")
    assert "read_only_hint=True" in decorator_of(files["server.py"], "pure")


def test_a_tool_the_analysis_cannot_follow_gets_no_hints_at_all():
    d = draft(tools=[with_tool(body=["return str(getattr(text, text))"])], cases=extra_cases())
    _, files = defn_and_files(d)
    assert decorator_of(files["server.py"], "extra").strip() == "@mcp.tool()"


def test_the_readme_reports_what_was_found_in_the_file_and_never_claims_a_proof():
    _, clean = defn_and_files()
    text = clean["README.md"]
    assert "by reading the code" in text.lower() and "cannot prove" in text
    risky = draft(tools=[with_tool(body=["open(text, 'w').write(text)", "return text"])], cases=extra_cases())
    _, files = defn_and_files(risky)
    assert "does not write or delete files" not in files["README.md"] and "can write or delete files" in files["README.md"]


# ---- the rest of the folder ---------------------------------------------------------------------------------------------------


def test_extra_code_or_a_foreign_requirement_in_the_folder_fails_the_builder_check():
    defn, files = defn_and_files()
    checks = {c.name: c for c in check_mcp(defn, spec(), {**files, "colorsys.py": "import subprocess\n"})}
    assert checks["server.py is the only code in the folder"].status == FAILED
    checks = {c.name: c for c in check_mcp(defn, spec(), {**files, "requirements.txt": "mcp==2.3.0\nevil-helper\n"})}
    assert checks["requirements.txt installs only the pinned SDK"].status == FAILED
    checks = {c.name: c for c in check_mcp(defn, spec(), {**files, "requirements.txt": "mcp==9.9.9\n"})}
    assert checks["requirements.txt installs only the pinned SDK"].status == FAILED


def test_the_design_prompt_tells_the_model_exactly_what_it_may_import():
    from skillforge.build.mcp import MCP_DESIGN_SYSTEM
    from skillforge.validate.mcp import SAFE_MODULES

    assert "<<ALLOWED>>" not in MCP_DESIGN_SYSTEM
    for module in sorted(SAFE_MODULES - {"__future__", "os", "io", "pathlib"}):
        assert module in MCP_DESIGN_SYSTEM, module
    for rule in ("os.environ.get", "io.StringIO", "PurePath", "print", "getattr", "subprocess"):
        assert rule in MCP_DESIGN_SYSTEM
