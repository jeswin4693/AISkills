"""The definition check of an MCP server: a `server.py` that creates an `MCPServer`, registers tools and runs.

It plays the part for a server that the `SKILL.md` check plays for a skill; every other static check still runs on the folder.
Nothing here runs anything: the file is read with `ast`, by syntax only.

A server is code that starts on the person's own machine, so this is the one place where being wrong is expensive, and it is
written to be hard to get round. Every import is resolved first (`from os import system`, `import os as o`, `importlib` and the
rest all end up as the name they really are), and every name and attribute the code touches is then classified by what it is,
the import itself included: it is the import that is flagged, not only the call. What can run a command, build code from text,
load native code or reach into Python's internals FAILS; network, file writes, other packages, an environment variable read by
a computed name and a name that is never defined WARN. A key written into the code fails (also when written in pieces or as
bytes); the report never repeats it. Python reads more than `server.py`, so an encoding declaration that changes how the file
is read, and any other code beside it that `python server.py` would import (`colorsys.py`, `mcp/__init__.py`, `sitecustomize.py`),
fail too, and `requirements.txt` may name only the pinned SDK.

This is a best-effort reading by syntax. It cannot prove a file safe and says so wherever it reports: read what you install.
"""

from __future__ import annotations

import ast
import builtins
import io
import re
import sys
import tokenize
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from ..results import FAILED, PASSED, WARNING, CheckResult
from .static import MAX_NAME, SLUG

DEFINITION_FILE = "server.py"
DEFINITION_CHECK = "server.py is a Python MCP server that can be started"
FOLDER_CHECK = "folder name matches the server name"
DESCRIBED_CHECK = "every tool has a description"
UNDEFINED_CHECK = "every name the code uses is defined or imported"
COMMANDS_CHECK = "no commands, code built from text or native code"
SECRETS_CHECK = "no key or token written into the code"
NETWORK_CHECK = "no use of the network (found by syntax)"
WRITES_CHECK = "no writing or deleting of files (found by syntax)"
IMPORTS_CHECK = "only the standard library and mcp are imported"
ENV_CHECK = "environment variables are read by a plain name only"
EXTRA_CODE_CHECK = "server.py is the only code in the folder"
REQUIREMENTS_CHECK = "requirements.txt installs only the pinned SDK"

SDK_MODULE = "mcp"
_BUILTIN_NAMES = frozenset(dir(builtins)) | {"__name__", "__file__", "__doc__", "__spec__", "__package__", "__loader__", "__builtins__", "__path__"}

# ---- what a name can be -------------------------------------------------------------------------------------------------
# A reference matches an entry when it is that name or something inside it ("os.system" matches "os.system.x"), after aliases are resolved.

COMMAND_REFS = frozenset({
    "subprocess", "pty", "multiprocessing", "_multiprocessing", "_posixsubprocess", "_winapi", "webbrowser", "posix", "nt", "pexpect", "plumbum", "sh",
    "asyncio.subprocess", "asyncio.create_subprocess_exec", "asyncio.create_subprocess_shell", "concurrent.futures.ProcessPoolExecutor",
    "os.system", "os.popen", "os.startfile", "os.fork", "os.forkpty", "os.kill", "os.killpg", "os.abort", "mcp.client",
})
COMMAND_PREFIXES = ("os.exec", "os.spawn", "os.posix_spawn")  # os.execv, os.spawnl, os.posix_spawnp ...
DYNAMIC_REFS = frozenset({
    "importlib", "builtins", "runpy", "code", "codeop", "pickle", "cPickle", "marshal", "shelve", "dill", "ctypes", "_ctypes", "cffi", "timeit",
    "pdb", "bdb", "cProfile", "profile", "trace", "imp", "zipimport", "pkgutil", "gc", "inspect", "sys.modules", "sys.settrace", "sys.setprofile",
    "sys._getframe", "sys._current_frames",
})
DYNAMIC_NAMES = frozenset({"eval", "exec", "compile", "__import__", "breakpoint", "globals", "locals", "vars", "__builtins__", "__loader__", "__spec__"})
BANNED_ATTRS = frozenset({"sys", "os", "subprocess", "builtins", "importlib", "modules", "posix", "nt"})  # reaching another module through an attribute
OK_DUNDER = frozenset({"__name__", "__doc__", "__file__", "__version__", "__all__", "__class__", "__init__"})
NETWORK_REFS = frozenset({
    "socket", "_socket", "ssl", "http.client", "http.server", "urllib.request", "ftplib", "smtplib", "poplib", "imaplib", "nntplib", "telnetlib",
    "xmlrpc", "socketserver", "smtpd", "asyncio.open_connection", "asyncio.start_server", "asyncio.open_unix_connection", "asyncio.start_unix_server",
    "asyncio.streams", "requests", "httpx", "aiohttp", "urllib3", "websockets", "websocket", "paramiko", "grpc", "mcp.client",
})
WRITE_REFS = frozenset({
    "os.write", "os.remove", "os.unlink", "os.rmdir", "os.removedirs", "os.rename", "os.renames", "os.replace", "os.mkdir", "os.makedirs", "os.chmod",
    "os.chown", "os.lchown", "os.fchmod", "os.symlink", "os.link", "os.truncate", "os.ftruncate", "os.utime", "os.mkfifo", "os.mknod", "os.fdopen",
    "shutil", "sqlite3.connect", "logging.FileHandler", "logging.handlers", "logging.config", "tempfile", "gzip.open", "bz2.open", "lzma.open",
})
WRITE_SAFE = frozenset({"shutil.which", "shutil.disk_usage", "shutil.get_terminal_size", "shutil.get_archive_formats", "shutil.get_unpack_formats"})
READ_REFS = frozenset({"os.listdir", "os.scandir", "os.walk", "os.stat", "os.lstat", "os.readlink", "os.access", "glob", "fileinput", "os.open"})
WRITE_ATTRS = frozenset({"write_text", "write_bytes", "mkdir", "unlink", "rmdir", "rename", "touch", "symlink_to", "hardlink_to", "chmod", "lchmod"})
READ_ATTRS = frozenset({"read_text", "read_bytes", "iterdir", "glob", "rglob", "listdir", "scandir", "walk"})
OPEN_FUNCTIONS = frozenset({"open", "io.open", "codecs.open"})
ARCHIVE_FUNCTIONS = frozenset({"zipfile.ZipFile", "tarfile.open", "tarfile.TarFile", "tarfile.TarFile.open"})
TRACKED_BUILTINS = DYNAMIC_NAMES | {"open", "getattr", "setattr", "delattr", "print", "input"}

# What a key looks like. The label is what a report says; the value is never repeated.
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("an OpenAI-style key", re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}")),
    ("a Google API key", re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    ("a Google access token", re.compile(r"ya29\.[0-9A-Za-z_-]{20,}")),
    ("a GitHub token", re.compile(r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{40,}")),
    ("a GitLab token", re.compile(r"glpat-[A-Za-z0-9_-]{20,}")),
    ("a Slack token", re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}|xapp-[A-Za-z0-9-]{10,}")),
    ("an AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("a Stripe key", re.compile(r"(?:sk|pk|rk)_(?:live|test)_[0-9A-Za-z]{16,}")),
    ("a PyPI token", re.compile(r"pypi-[A-Za-z0-9_-]{20,}")),
    ("a Hugging Face token", re.compile(r"(?<![A-Za-z0-9])hf_[A-Za-z0-9]{30,}")),
    ("an npm token", re.compile(r"npm_[A-Za-z0-9]{30,}")),
    ("a private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("a bearer token", re.compile(r"Bearer [A-Za-z0-9._~+/=-]{20,}")),
    ("a signed web token", re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
)

CODE_EXTENSIONS = frozenset({
    ".py", ".pyw", ".pyc", ".pyo", ".pyd", ".so", ".dll", ".dylib", ".pth", ".egg", ".whl", ".zip", ".sh", ".bash", ".zsh", ".bat", ".cmd", ".ps1",
    ".exe", ".js", ".mjs", ".cjs", ".ts", ".rb", ".php", ".pl",
})
PINNED_SDK = re.compile(r"^mcp==[0-9][0-9A-Za-z.+!-]*$")


def _hit(name: str, refs: frozenset[str]) -> bool:
    return any(name == r or name.startswith(r + ".") for r in refs)


@dataclass
class ToolFact:
    name: str
    described: bool  # has a docstring, which is the description Claude reads
    line: int
    capabilities: set[str] = field(default_factory=set)  # what this one tool's own code can do: read_files, write_files, network, run_commands
    dynamic: set[str] = field(default_factory=set)  # constructs in this tool that cannot be followed


@dataclass
class ServerFacts:
    server_name: str | None = None
    has_server: bool = False
    server_count: int = 0
    tools: list[ToolFact] = field(default_factory=list)
    calls_run: bool = False
    imports: set[str] = field(default_factory=set)  # top-level module names; "." marks a relative import
    imported: set[str] = field(default_factory=set)  # every module and `module.name` an import statement names, aliases resolved
    refs: set[str] = field(default_factory=set)  # every dotted name the code touches, aliases resolved
    capabilities: set[str] = field(default_factory=set)  # read_files, write_files, network, run_commands
    dynamic: set[str] = field(default_factory=set)  # code built from text, native code, reaching into Python's internals
    env_names: set[str] = field(default_factory=set)
    env_dynamic: bool = False  # an environment variable read by a computed name, or all of them
    secrets: list[tuple[int, str]] = field(default_factory=list)  # (line, label); never the value
    undefined: set[str] = field(default_factory=set)  # names that are used but never defined or imported anywhere in the file
    unused_imports: set[str] = field(default_factory=set)  # names an import binds that nothing in the file ever reads


# ---- resolving names ----------------------------------------------------------------------------------------------------


class _Names:
    """Maps a name in the file to what it really is, after `import x as y` and `from m import n as k`."""

    def __init__(self, tree: ast.AST) -> None:
        self.alias: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.asname:
                        self.alias[a.asname] = a.name
                    else:
                        top = a.name.split(".")[0]
                        self.alias[top] = top
            elif isinstance(node, ast.ImportFrom):
                base = "." * node.level + (node.module or "")
                for a in node.names:
                    if a.name != "*":
                        self.alias[a.asname or a.name] = f"{base}.{a.name}"

    def qual(self, node: ast.AST) -> str | None:
        """The dotted name a Name or Attribute chain stands for, or None when it starts from something unknown (a local variable)."""
        if isinstance(node, ast.Name):
            if node.id in self.alias:
                return self.alias[node.id]
            return node.id if node.id in TRACKED_BUILTINS else None
        if isinstance(node, ast.Attribute):
            base = self.qual(node.value)
            return f"{base}.{node.attr}" if base else None
        return None


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


def _mode_is_read(call: ast.Call, positional: int) -> bool:
    """Whether a call that opens something names a read-only mode. No mode means read; a mode we cannot read means write."""
    mode_node = call.args[positional] if len(call.args) > positional else next((k.value for k in call.keywords if k.arg == "mode"), None)
    if mode_node is None:
        return True
    mode = _literal(mode_node)
    return mode is not None and not any(c in mode for c in "wax+")


# ---- classifying what a piece of code can do ----------------------------------------------------------------------------


def _classify_ref(name: str, caps: set[str], dynamic: set[str]) -> None:
    if name in DYNAMIC_NAMES:
        dynamic.add(f"{name}()")
    elif _hit(name, DYNAMIC_REFS):
        dynamic.add(next(r for r in sorted(DYNAMIC_REFS) if name == r or name.startswith(r + ".")))
    if _hit(name, COMMAND_REFS) or name.startswith(COMMAND_PREFIXES):
        caps.add("run_commands")
    if _hit(name, NETWORK_REFS):
        caps.add("network")
    if _hit(name, WRITE_REFS) and name not in WRITE_SAFE:
        caps.add("write_files")
    if _hit(name, READ_REFS):
        caps.add("read_files")
    if name == "os.open" or name == "os.fdopen":
        caps.update({"read_files", "write_files"})  # the flags are a number: it may write


def _classify_call(call: ast.Call, names: _Names, caps: set[str], dynamic: set[str]) -> None:
    fq = names.qual(call.func)
    if fq in OPEN_FUNCTIONS:
        caps.add("read_files" if _mode_is_read(call, 1) else "write_files")
        if not _mode_is_read(call, 1):
            caps.add("write_files")
    elif fq in ARCHIVE_FUNCTIONS:
        caps.add("read_files" if _mode_is_read(call, 1) else "write_files")
    elif isinstance(call.func, ast.Attribute) and call.func.attr == "open" and fq is None:
        caps.add("read_files" if _mode_is_read(call, 0) else "write_files")  # Path(...).open(mode)
    if fq in ("getattr", "setattr", "delattr") and len(call.args) >= 2:
        attr = _literal(call.args[1])
        if attr is None:
            dynamic.add(f"{fq}() with a computed name")
        else:
            base = names.qual(call.args[0])
            if base:
                _classify_ref(f"{base}.{attr}", caps, dynamic)
            if attr in BANNED_ATTRS or (attr.startswith("__") and attr.endswith("__") and attr not in OK_DUNDER):
                dynamic.add(f"{fq}() reaching {attr}")


def _classify(root: ast.AST, names: _Names) -> tuple[set[str], set[str], set[str]]:
    """(capabilities, constructs that cannot be followed, every dotted name touched) for a piece of code."""
    caps: set[str] = set()
    dynamic: set[str] = set()
    refs: set[str] = set()
    for node in ast.walk(root):
        if isinstance(node, (ast.Name, ast.Attribute)):
            q = names.qual(node)
            if q:
                refs.add(q)
                _classify_ref(q, caps, dynamic)
        if isinstance(node, ast.Attribute):
            if node.attr in BANNED_ATTRS:
                dynamic.add(f"the attribute .{node.attr}")
            elif node.attr.startswith("__") and node.attr.endswith("__") and node.attr not in OK_DUNDER:
                dynamic.add(f"the internal attribute .{node.attr}")
            if node.attr in WRITE_ATTRS:
                caps.add("write_files")
            if node.attr in READ_ATTRS:
                caps.add("read_files")
        elif isinstance(node, ast.Call):
            _classify_call(node, names, caps, dynamic)
        elif isinstance(node, ast.Import):
            for a in node.names:
                refs.add(a.name)
                _classify_ref(a.name, caps, dynamic)
        elif isinstance(node, ast.ImportFrom):
            base = "." * node.level + (node.module or "")
            if base:
                refs.add(base)
                _classify_ref(base, caps, dynamic)
            for a in node.names:
                if a.name != "*":
                    refs.add(f"{base}.{a.name}")
                    _classify_ref(f"{base}.{a.name}", caps, dynamic)
    return caps, dynamic, refs


def _environment(tree: ast.AST, names: _Names, facts: ServerFacts) -> None:
    """Which environment variables are read, by a name written in the code or not. Aliases are followed (`from os import environ`)."""
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}

    def seen(name: str | None) -> None:
        if name:
            facts.env_names.add(name)
        else:
            facts.env_dynamic = True  # a computed name, bytes, or the whole environment

    for node in ast.walk(tree):
        q = names.qual(node) if isinstance(node, (ast.Name, ast.Attribute)) else None
        if q in ("os.environb", "os.getenvb", "os.putenv", "os.unsetenv", "posix.environ", "nt.environ"):
            facts.env_dynamic = True
        elif q == "os.getenv" and isinstance(parents.get(node), ast.Call) and parents[node].func is node:
            call = parents[node]
            seen(_literal(call.args[0]) if call.args else None)
        elif q == "os.environ":
            parent = parents.get(node)
            grand = parents.get(parent) if parent is not None else None
            if isinstance(parent, ast.Attribute) and parent.attr == "get" and isinstance(grand, ast.Call) and grand.func is parent:
                seen(_literal(grand.args[0]) if grand.args else None)
            elif isinstance(parent, ast.Subscript) and parent.value is node:
                seen(_literal(parent.slice))
            else:
                seen(None)  # any other use may hand out the whole environment, including `g = os.environ.get` and `map(os.environ.get, names)`
        elif q == "os.getenv" and not (isinstance(parents.get(node), ast.Call) and parents[node].func is node):
            facts.env_dynamic = True  # the function passed around: it can read any name


FOLD_LIMIT = 4096  # the longest piece of text built from constants that is still looked at: a key is far shorter


def _folded(node: ast.AST) -> str | None:
    """The text an expression is made of when that is plain text written in the code: a string, bytes, a sum of them, a repeat, an f-string's
    written parts. A key split into pieces is still a key."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return node.value
        if isinstance(node.value, bytes):
            return node.value.decode("latin-1")
        return None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _folded(node.left), _folded(node.right)
        if left is None or right is None or len(left) + len(right) > FOLD_LIMIT:
            return None
        return left + right
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        base, count = (node.left, node.right) if isinstance(node.right, ast.Constant) else (node.right, node.left)
        text = _folded(base)
        if text is not None and isinstance(count, ast.Constant) and isinstance(count.value, int) and 0 <= count.value <= 200 and len(text) * count.value <= FOLD_LIMIT:
            return text * count.value
        return None  # too long to be a key, and building it would let a few bytes of source take gigabytes
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else "" for v in node.values)
    return None


def _secrets(tree: ast.AST, facts: ServerFacts) -> None:
    found: set[tuple[int, str]] = set()
    for node in ast.walk(tree):
        text = _folded(node) if isinstance(node, (ast.Constant, ast.BinOp, ast.JoinedStr)) else None
        if text:
            for label, pattern in SECRET_PATTERNS:
                if pattern.search(text):
                    found.add((getattr(node, "lineno", 0), label))
                    break
    facts.secrets = sorted(found)


def _undefined_names(tree: ast.AST) -> set[str]:
    """Names that are read but never assigned, imported, defined or built in anywhere in the file: a NameError for certain, the
    first time a call reaches them. Scopes are merged on purpose (a name defined anywhere counts), so this finds only the sure ones."""
    defined: set[str] = set(_BUILTIN_NAMES)
    loaded: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            (loaded if isinstance(node.ctx, ast.Load) else defined).add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.arg):
            defined.add(node.arg)
        elif isinstance(node, ast.Import):
            defined.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if any(alias.name == "*" for alias in node.names):
                return set()  # a star import hides what is defined, so nothing can be claimed
            defined.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            defined.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            defined.update(node.names)
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            defined.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            defined.add(node.rest)
    return loaded - defined


def _unused_imports(tree: ast.AST) -> set[str]:
    """Names an import statement binds that nothing reads. In a generated tool this is the mark of a stub: the code imports what the
    job needs and then does not do the job."""
    bound: set[str] = set()
    loaded: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            bound.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module != "__future__":
            if any(alias.name == "*" for alias in node.names):
                return set()
            bound.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            loaded.add(node.id)
    return bound - loaded


def analyze_server(source: str) -> ServerFacts:
    """What the code says about itself, by syntax only. Raises SyntaxError when it does not parse."""
    tree = ast.parse(source)
    names = _Names(tree)
    facts = ServerFacts()
    server_var = ""
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.setdefault(node.name, node)
        if isinstance(node, ast.Assign) and (call := _server_call(node.value)) is not None:
            facts.server_count += 1
            if not facts.has_server:
                facts.has_server = True
                targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
                server_var = targets[0] if targets else ""
                facts.server_name = _literal(call.args[0]) if call.args else next((_literal(k.value) for k in call.keywords if k.arg == "name"), None)
    registered: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(_is_tool_decorator(d, server_var) for d in node.decorator_list):
            registered.append(node)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Call) and _is_tool_decorator(node.func, server_var) and node.args:
            target = node.args[0]
            if isinstance(target, ast.Name) and target.id in functions:  # mcp.tool()(fn): the same thing written another way
                registered.append(functions[target.id])
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "run" and isinstance(node.func.value, ast.Name) and node.func.value.id == server_var:
            facts.calls_run = True
        elif isinstance(node, ast.Import):
            facts.imports.update(a.name.split(".")[0] for a in node.names)
            facts.imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = "." * node.level + (node.module or "")
            facts.imports.add("." if node.level else (node.module or "").split(".")[0])
            if base:
                facts.imported.add(base)
            facts.imported.update(f"{base}.{a.name}" for a in node.names if a.name != "*")
    seen_tools: set[int] = set()
    for node in registered:
        if id(node) in seen_tools:
            continue
        seen_tools.add(id(node))
        own_caps, own_dynamic, _ = _classify(node, names)
        facts.tools.append(ToolFact(node.name, bool(ast.get_docstring(node)), node.lineno, own_caps, own_dynamic))
    facts.tools.sort(key=lambda t: t.line)
    facts.capabilities, facts.dynamic, facts.refs = _classify(tree, names)
    _environment(tree, names, facts)
    _secrets(tree, facts)
    facts.undefined = _undefined_names(tree)
    facts.unused_imports = _unused_imports(tree)
    return facts


# ---- reading the files --------------------------------------------------------------------------------------------------


def _parse(files: Mapping[str, bytes]) -> tuple[ServerFacts | None, str]:
    """(facts, why not). The facts are None when the file is missing, not read the way Python reads it, or not Python."""
    if DEFINITION_FILE not in files:
        return None, f"there is no {DEFINITION_FILE} at the top of the folder"
    data = files[DEFINITION_FILE]
    if data.startswith(b"\xef\xbb\xbf"):
        return None, f"{DEFINITION_FILE} starts with a byte-order mark: it must be plain UTF-8"
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
    except (SyntaxError, LookupError) as exc:
        return None, f"its encoding declaration is not valid ({exc})"
    if encoding.lower().replace("_", "-") not in ("utf-8", "utf8"):
        return None, (
            f"it declares the encoding '{encoding}'. Python reads the file in that encoding, but these checks read it as UTF-8, "
            "so what they see is not what would run. Remove the declaration"
        )
    try:
        source = data.decode("utf-8")
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


def other_code(files: Mapping[str, bytes]) -> list[str]:
    """Files beside server.py that Python (or something it starts) would load: `python server.py` puts its own folder first on the
    import path, so a `colorsys.py` or an `mcp/__init__.py` there replaces the real module, and the checks never read it."""
    found: list[str] = []
    for rel in sorted(files):
        if rel == DEFINITION_FILE:
            continue
        path = PurePosixPath(rel)
        if path.suffix.lower() in CODE_EXTENSIONS or path.name == "__init__.py" or "scripts" in path.parts[:-1] or "bin" in path.parts[:-1]:
            found.append(rel)
    return found


def requirements_problems(files: Mapping[str, bytes]) -> tuple[list[str], list[str]]:
    """(lines that would fetch from somewhere else or change how pip runs, other packages). Only `mcp==<version>` is expected."""
    raw = files.get("requirements.txt")
    if raw is None:
        return [], []
    risky: list[str] = []
    other: list[str] = []
    for line in raw.decode("utf-8", "replace").splitlines():
        entry = line.split(" #")[0].strip()
        if not entry or entry.startswith("#") or PINNED_SDK.match(entry):
            continue
        if entry.startswith(("-", ".", "/", "git+", "http", "file:")) or "://" in entry or " @ " in entry or "@" in entry:
            risky.append(entry[:60])
        else:
            other.append(entry[:60])
    return risky, other


# ---- the builder's allow-list -------------------------------------------------------------------------------------------
# A blacklist can never be complete, so for a server the BUILDER writes the rule is the other way round: a tool body may import only
# what is listed here. `os` is only for reading environment variables, `io` only for in-memory text and bytes, and `pathlib` only for
# names (with `read_files` declared, for files). Nothing that can start a program, load code or reach another module is on the list.

SAFE_MODULES = frozenset({
    "json", "re", "math", "cmath", "datetime", "calendar", "zoneinfo", "time", "statistics", "decimal", "fractions", "random", "secrets", "uuid",
    "hashlib", "hmac", "base64", "binascii", "zlib", "string", "textwrap", "difflib", "unicodedata", "html", "html.parser", "html.entities",
    "urllib.parse", "collections", "collections.abc", "itertools", "functools", "operator", "heapq", "bisect", "copy", "dataclasses", "enum", "typing",
    "abc", "numbers", "contextlib", "pprint", "array", "struct", "csv", "shlex", "ipaddress", "xml.etree.ElementTree", "email.utils", "mimetypes",
    "fnmatch", "io", "os", "pathlib", "__future__",
})
NETWORK_MODULES_OK = frozenset({"urllib.request", "urllib.error", "urllib.response", "http.client", "http", "ssl"})
FILE_MODULES_OK = frozenset({"glob"})
HEADER_IMPORTS = frozenset({"mcp", "mcp.server", "mcp.server.mcpserver", "mcp.server.mcpserver.MCPServer", "mcp.types", "mcp.types.ToolAnnotations"})
PURE_PATHS = ("pathlib.PurePath", "pathlib.PurePosixPath", "pathlib.PureWindowsPath")
IN_MEMORY_IO = ("io.StringIO", "io.BytesIO")
BUILDER_BANNED_BUILTINS = frozenset({"print", "input", "getattr", "setattr", "delattr"})  # eval, exec, compile ... already fail everywhere


def _prefixes(module: str) -> set[str]:
    parts = module.split(".")
    return {".".join(parts[:i]) for i in range(1, len(parts))}


def allow_list_problems(facts: ServerFacts, *, network: bool, read_files: bool) -> list[str]:
    """What a tool body written by the builder uses that is not on the allow-list ([] when it keeps to the list)."""
    allowed = set(SAFE_MODULES)
    if network:
        allowed |= NETWORK_MODULES_OK
    if read_files:
        allowed |= FILE_MODULES_OK
    parents = {p for module in allowed for p in _prefixes(module)}
    problems: list[str] = []
    for entry in sorted(facts.imported):
        if entry in HEADER_IMPORTS or entry in allowed or entry in parents or any(entry.startswith(m + ".") for m in allowed):
            continue
        problems.append(f"imports '{entry}', which is not on the allow-list of safe standard-library modules")
    for ref in sorted(facts.refs):
        top = ref.split(".")[0]
        if top == "os" and ref != "os" and ref not in ("os.environ", "os.getenv") and not ref.startswith(("os.environ.", "os.getenv.")):
            problems.append(f"uses {ref}: os may only be used to read environment variables")
        elif top == "io" and ref != "io" and not any(ref == m or ref.startswith(m + ".") for m in IN_MEMORY_IO):
            problems.append(f"uses {ref}: io may only be used for in-memory text and bytes (StringIO, BytesIO)")
        elif top == "pathlib" and ref != "pathlib" and not read_files and not any(ref == m or ref.startswith(m + ".") for m in PURE_PATHS):
            problems.append(f"uses {ref}: without read_files, pathlib may only be used for names (PurePath)")
        elif ref in BUILDER_BANNED_BUILTINS:
            problems.append(f"uses {ref}(): " + ("print would write into the protocol stream the server talks over" if ref == "print" else "it cannot be followed by the checks"))
    return problems[:12]


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
    if facts.server_count > 1:
        structure.append("it creates more than one MCPServer: tools on the second one are not seen by these checks")
    if facts.has_server and not facts.tools:
        structure.append("it defines no tool (a function decorated with @mcp.tool())")
    if facts.has_server and not facts.calls_run:
        structure.append("it never calls mcp.run(), so starting it would do nothing")
    row(DEFINITION_CHECK, structure, f"{len(facts.tools)} tool(s)")
    row(FOLDER_CHECK, [] if folder is None or folder == facts.server_name else [f"the folder is '{folder}' but the server calls itself '{facts.server_name}'"])
    bare = [t.name for t in facts.tools if not t.described]
    row(DESCRIBED_CHECK, [f"no description (docstring) on: {', '.join(bare)}. Claude decides when to use a tool from it"] if bare else [], status=WARNING)
    missing = sorted(facts.undefined)
    row(UNDEFINED_CHECK, [f"it uses {', '.join(missing)} but never defines or imports it, so the first call that reaches it fails with a NameError"] if missing else [], "none found", status=WARNING)
    dangerous = sorted(facts.dynamic | ({"starts other programs"} if "run_commands" in facts.capabilities else set()))
    row(COMMANDS_CHECK, [f"it uses {', '.join(dangerous)}"] if dangerous else [], "none found by syntax (a reading by syntax cannot prove there is none)")
    found = sorted({f"line {line}: {label}" for line, label in facts.secrets})
    row(SECRETS_CHECK, [f"it contains what looks like {'; '.join(found)}. Read the key from an environment variable instead"] if found else [], "none found")
    row(NETWORK_CHECK, ["it can reach other computers: read what it calls"] if "network" in facts.capabilities else [], status=WARNING)
    row(WRITES_CHECK, ["it can create, change or delete files: read what it touches"] if "write_files" in facts.capabilities else [], status=WARNING)
    extra = third_party(facts)
    row(IMPORTS_CHECK, [f"it also imports {', '.join(extra)}: install them yourself and read what they do"] if extra else [], status=WARNING)
    env_problems = ["it reads an environment variable whose name is not written in the code (or all of them), so what a secret could reach cannot be listed"] if facts.env_dynamic else []
    row(ENV_CHECK, env_problems, ("reads " + ", ".join(sorted(facts.env_names))) if facts.env_names else "reads none", status=WARNING)
    beside = other_code(files)
    row(EXTRA_CODE_CHECK, [f"{', '.join(beside[:6])}{' and more' if len(beside) > 6 else ''} would be loaded or run beside it and is never read by these checks: a server is one file"] if beside else [], "only server.py")
    risky, other = requirements_problems(files)
    if risky:
        out.append(CheckResult(REQUIREMENTS_CHECK, FAILED, f"{'; '.join(risky)}: pip would fetch from somewhere else or change how it runs"))
    elif other:
        out.append(CheckResult(REQUIREMENTS_CHECK, WARNING, f"it also installs {', '.join(other)}: read them, they run when installed"))
    else:
        out.append(CheckResult(REQUIREMENTS_CHECK, PASSED, "only the pinned SDK" if "requirements.txt" in files else "no requirements.txt"))
    return out
