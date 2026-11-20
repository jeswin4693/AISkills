"""The definition check of an MCP server: a `server.py` that creates an `MCPServer`, registers tools and runs.

It plays the part for a server that the `SKILL.md` check plays for a skill; every other static check still runs on the
folder. Nothing here runs anything: the file is read with `ast`, by syntax only. A server is code that starts on the
person's own machine, so what can run a command, run code built from text, load native code or carry a hard-coded key
FAILS. What is only worth reading (network, writing files, packages outside the standard library, an environment variable
read by a computed name) warns, the way a skill's scripts are treated. The report never repeats a secret it found.
"""

from __future__ import annotations

import ast
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field

from ..results import FAILED, PASSED, WARNING, CheckResult
from .static import MAX_NAME, SLUG, python_capabilities

DEFINITION_FILE = "server.py"
DEFINITION_CHECK = "server.py is a Python MCP server that can be started"
FOLDER_CHECK = "folder name matches the server name"
DESCRIBED_CHECK = "every tool has a description"
COMMANDS_CHECK = "no commands, code built from text or native code"
SECRETS_CHECK = "no key or token written into the code"
NETWORK_CHECK = "no use of the network (found by syntax)"
WRITES_CHECK = "no writing or deleting of files (found by syntax)"
IMPORTS_CHECK = "only the standard library and mcp are imported"
ENV_CHECK = "environment variables are read by a plain name only"

SDK_MODULE = "mcp"
_READ_ATTRS = {"read_text", "read_bytes", "iterdir", "glob", "rglob", "listdir", "scandir", "walk", "open"}

# What a key looks like. The label is what a report says; the value is never repeated.
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("an OpenAI-style key", re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}")),
    ("a Google API key", re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    ("a GitHub token", re.compile(r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{40,}")),
    ("a Slack token", re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}")),
    ("an AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("a private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("a bearer token", re.compile(r"Bearer [A-Za-z0-9._~+/=-]{20,}")),
    ("a signed web token", re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
)


@dataclass
class ToolFact:
    name: str
    described: bool  # has a docstring, which is the description Claude reads
    line: int


@dataclass
class ServerFacts:
    server_name: str | None = None
    has_server: bool = False
    tools: list[ToolFact] = field(default_factory=list)
    calls_run: bool = False
    imports: set[str] = field(default_factory=set)  # top-level module names; "." marks a relative import
    capabilities: set[str] = field(default_factory=set)  # read_files, write_files, network, run_commands
    dynamic: set[str] = field(default_factory=set)  # eval, exec, __import__, native code
    env_names: set[str] = field(default_factory=set)
    env_dynamic: bool = False  # an environment variable read by a computed name, or all of them
    secrets: list[tuple[int, str]] = field(default_factory=list)  # (line, label); never the value


def _dotted(node: ast.AST) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _literal(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _server_call(node: ast.AST) -> ast.Call | None:
    if isinstance(node, ast.Call) and _dotted(node.func).split(".")[-1] == "MCPServer":
        return node
    return None


def _is_tool_decorator(dec: ast.expr, server_var: str) -> bool:
    target = dec.func if isinstance(dec, ast.Call) else dec
    return isinstance(target, ast.Attribute) and target.attr == "tool" and isinstance(target.value, ast.Name) and target.value.id == server_var


def _environment(tree: ast.AST, facts: ServerFacts) -> None:
    """Which environment variables are read, by a name written in the code or not."""
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}

    def seen(name: str | None) -> None:
        if name:
            facts.env_names.add(name)
        else:
            facts.env_dynamic = True  # a computed name, or the whole environment

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _dotted(node.func) in ("os.getenv", "getenv"):
            seen(_literal(node.args[0]) if node.args else None)
        elif isinstance(node, ast.Attribute) and _dotted(node) == "os.environ":
            parent = parents.get(node)
            grand = parents.get(parent) if parent is not None else None
            if isinstance(parent, ast.Attribute) and parent.attr == "get" and isinstance(grand, ast.Call) and grand.func is parent:
                seen(_literal(grand.args[0]) if grand.args else None)
            elif isinstance(parent, ast.Subscript) and parent.value is node:
                seen(_literal(parent.slice))
            else:
                seen(None)


def analyze_server(source: str) -> ServerFacts:
    """What the code says about itself, by syntax only. Raises SyntaxError when it does not parse."""
    tree = ast.parse(source)
    facts = ServerFacts()
    server_var = ""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and (call := _server_call(node.value)) is not None and not facts.has_server:
            facts.has_server = True
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            server_var = targets[0] if targets else ""
            facts.server_name = _literal(call.args[0]) if call.args else next((_literal(k.value) for k in call.keywords if k.arg == "name"), None)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(_is_tool_decorator(d, server_var) for d in node.decorator_list):
            facts.tools.append(ToolFact(node.name, bool(ast.get_docstring(node)), node.lineno))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "run" and isinstance(node.func.value, ast.Name) and node.func.value.id == server_var:
            facts.calls_run = True
        elif isinstance(node, ast.Import):
            facts.imports.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            facts.imports.add("." if node.level else (node.module or "").split(".")[0])
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            for label, pattern in SECRET_PATTERNS:
                if pattern.search(node.value):
                    facts.secrets.append((node.lineno, label))
                    break
        if isinstance(node, ast.Call):
            fn = _dotted(node.func)
            if fn == "open":
                mode = _literal(node.args[1]) if len(node.args) > 1 else next((_literal(k.value) for k in node.keywords if k.arg == "mode"), None)
                if not (mode and any(c in mode for c in "wax+")):
                    facts.capabilities.add("read_files")
            elif isinstance(node.func, ast.Attribute) and node.func.attr in _READ_ATTRS:
                facts.capabilities.add("read_files")
    caps, dynamic = python_capabilities(source)
    facts.capabilities |= caps
    facts.dynamic |= dynamic
    _environment(tree, facts)
    return facts


def _parse(files: Mapping[str, bytes]) -> tuple[ServerFacts | None, str]:
    """(facts, why not). The facts are None when the file is missing, not text or not Python."""
    if DEFINITION_FILE not in files:
        return None, f"there is no {DEFINITION_FILE} at the top of the folder"
    try:
        source = files[DEFINITION_FILE].decode("utf-8")
    except UnicodeDecodeError:
        return None, f"{DEFINITION_FILE} is not valid UTF-8"
    try:
        return analyze_server(source), ""
    except SyntaxError as exc:
        return None, f"it has a syntax error at line {exc.lineno}: {exc.msg}"
    except (ValueError, RecursionError) as exc:
        return None, f"it could not be read as Python: {exc}"


def mcp_name_of(files: Mapping[str, bytes]) -> str | None:
    """The safe name the server gives itself, or None when there is none or it is not a safe name."""
    facts, _ = _parse(files)
    name = facts.server_name if facts else None
    return name if name and SLUG.match(name) and len(name) <= MAX_NAME else None


def third_party(facts: ServerFacts) -> list[str]:
    """Imports that are neither the standard library nor the MCP SDK."""
    return sorted(
        ("a module next to server.py" if m == "." else m) for m in facts.imports
        if m and m != SDK_MODULE and (m == "." or m not in sys.stdlib_module_names)
    )


def check_server_py(files: Mapping[str, bytes], folder: str | None) -> list[CheckResult]:
    facts, why = _parse(files)
    if facts is None:
        return [CheckResult(DEFINITION_CHECK, FAILED, why)]
    out: list[CheckResult] = []

    def row(name: str, problems: list[str], ok_detail: str = "", status: str = FAILED) -> None:
        out.append(CheckResult(name, status, "; ".join(problems)) if problems else CheckResult(name, PASSED, ok_detail))

    structure: list[str] = []
    if not facts.has_server:
        structure.append("it never creates an MCPServer (from mcp.server.mcpserver import MCPServer)")
    elif not facts.server_name:
        structure.append("the MCPServer has no name written in the code")
    elif not SLUG.match(facts.server_name) or len(facts.server_name) > MAX_NAME:
        structure.append(f"the server name must be lowercase letters, digits and hyphens, at most {MAX_NAME} characters")
    if facts.has_server and not facts.tools:
        structure.append("it defines no tool (a function decorated with @mcp.tool())")
    if facts.has_server and not facts.calls_run:
        structure.append("it never calls mcp.run(), so starting it would do nothing")
    row(DEFINITION_CHECK, structure, f"{len(facts.tools)} tool(s)")
    row(FOLDER_CHECK, [] if folder is None or folder == facts.server_name else [f"the folder is '{folder}' but the server calls itself '{facts.server_name}'"])
    bare = [t.name for t in facts.tools if not t.described]
    row(DESCRIBED_CHECK, [f"no description (docstring) on: {', '.join(bare)}. Claude decides when to use a tool from it"] if bare else [], status=WARNING)
    dangerous = sorted(facts.dynamic | ({"starts other programs"} if "run_commands" in facts.capabilities else set()))
    row(COMMANDS_CHECK, [f"it uses {', '.join(dangerous)}"] if dangerous else [], "none found by syntax")
    found = sorted({f"line {line}: {label}" for line, label in facts.secrets})
    row(SECRETS_CHECK, [f"it contains what looks like {'; '.join(found)}. Read the key from an environment variable instead"] if found else [], "none found")
    row(NETWORK_CHECK, ["it can reach other computers: read what it calls"] if "network" in facts.capabilities else [], status=WARNING)
    row(WRITES_CHECK, ["it can create, change or delete files: read what it touches"] if "write_files" in facts.capabilities else [], status=WARNING)
    extra = third_party(facts)
    row(IMPORTS_CHECK, [f"it also imports {', '.join(extra)}: install them yourself and read what they do"] if extra else [], status=WARNING)
    env_problems = ["it reads an environment variable whose name is not written in the code (or all of them), so what a secret could reach cannot be listed"] if facts.env_dynamic else []
    row(ENV_CHECK, env_problems, ("reads " + ", ".join(sorted(facts.env_names))) if facts.env_names else "reads none", status=WARNING)
    return out
