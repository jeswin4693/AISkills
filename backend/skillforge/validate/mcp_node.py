"""The definition check of a Node MCP server: a `server.ts` that creates an `McpServer`, registers tools and connects a transport.

It plays for a Node server the part `validate/mcp.py` plays for a Python one, and it is just as careful about being hard to get round,
because a server is code that starts on the person's own machine. The file is read with tree-sitter's TypeScript grammar, by syntax, and
never run. Every import is resolved first (`import * as fs from "node:fs"`, `import { exec as e } from "child_process"`, `const w = fs.writeFileSync`,
`const { exec } = cp`), then every name the code touches is classified by what it really is. What starts a program, builds code from
text (`eval`, `Function`, `import()`, `require`, `vm`), loads native code or reaches into the language's internals (`.constructor`,
`__proto__`) FAILS; network, writing and reading files, another package, an environment variable read by a computed name, a name that is
never defined and writing to the protocol stream (`console.log`) WARN. A key written into the code fails, also when written in pieces.

`node server.ts` reads more than `server.ts`: a `package.json` beside it (whose `scripts` run when it is installed), a lockfile, other
`.js`/`.ts` files, a `node_modules` folder, an `.npmrc`. Those are checked too. Nothing here can prove a file safe; the report says so.
Node's permission model (`node --permission`, see mcpnode.start_command) is what stops a server writing files or starting programs even
when this reading misses something. It does not limit the network or environment variables.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterator, Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from ..graph import languages
from ..mcpnode import LOCK_FILE, PACKAGE_FILE, PINNED, SERVER_FILE, SERVER_SDK, is_our_lock
from ..results import FAILED, PASSED, WARNING, CheckResult
from .mcp import SECRET_PATTERNS
from .static import MAX_NAME, SLUG

DEFINITION_FILE = SERVER_FILE
DEFINITION_CHECK = "server.ts is a TypeScript MCP server that can be started"
FOLDER_CHECK = "folder name matches the server name"
DESCRIBED_CHECK = "every tool has a description"
UNDEFINED_CHECK = "every name the code uses is defined or imported"
COMMANDS_CHECK = "no commands, code built from text or native code"
SECRETS_CHECK = "no key or token written into the code"
NETWORK_CHECK = "no use of the network (found by syntax)"
WRITES_CHECK = "no writing or deleting of files (found by syntax)"
IMPORTS_CHECK = "only Node's own modules, the MCP SDK and zod are imported"
ENV_CHECK = "environment variables are read by a plain name only"
STDOUT_CHECK = "nothing is written to the protocol stream"
READS_CHECK = "no reading of files (found by syntax)"
UNREADABLE_CHECK = "no property is reached by a name the checks cannot read"
SYNTAX_CHECK = "only syntax that `node server.ts` can run"
EXTRA_CODE_CHECK = "server.ts is the only code in the folder"
PACKAGE_CHECK = "package.json runs nothing when installed and names only the pinned packages"
LOCK_CHECK = "package-lock.json is the pinned lockfile"

FOLD_LIMIT = 4096
MAX_NODES = 400_000

# ---- what a name can be -------------------------------------------------------------------------------------------------
# A reference matches an entry when it is that name or something inside it ("fs.promises" matches "fs.promises.writeFile"), after aliases
# are resolved and a leading `node:` or `globalThis.` is dropped.

COMMAND_REFS = frozenset({
    "child_process", "cluster", "worker_threads", "repl", "wasi", "process.kill", "process.dlopen", "process.binding", "process._linkedBinding", "process.execve",
    "Bun.spawn", "Bun.spawnSync", "Deno.Command", "Deno.run", "execa", "cross-spawn", "shelljs", "node-pty", "Worker", "SharedWorker",
})
DYNAMIC_REFS = frozenset({
    "vm", "module", "v8", "inspector", "inspector/promises", "eval", "Function", "AsyncFunction", "GeneratorFunction", "WebAssembly", "require",
    "createRequire", "process.mainModule", "process.moduleLoadList", "process.report", "process.getBuiltinModule", "Reflect", "Proxy", "globalThis", "global", "self", "window", "Atomics",
})
DYNAMIC_PROPS = frozenset({"constructor", "__proto__", "__defineGetter__", "__defineSetter__", "__lookupGetter__", "__lookupSetter__"})
NETWORK_REFS = frozenset({
    "http", "https", "http2", "net", "tls", "dgram", "dns", "dns/promises", "fetch", "XMLHttpRequest", "WebSocket", "EventSource", "navigator.sendBeacon",
    "Bun.fetch", "Deno.connect", "Deno.listen", "axios", "node-fetch", "got", "undici", "ws", "request", "superagent", "ky", "needle", "socket.io", "socket.io-client",
})
FS_MODULES = ("fs", "fs/promises")
WRITE_MEMBERS = frozenset({
    "writeFile", "writeFileSync", "appendFile", "appendFileSync", "createWriteStream", "mkdir", "mkdirSync", "mkdtemp", "mkdtempSync", "rm", "rmSync", "rmdir",
    "rmdirSync", "unlink", "unlinkSync", "rename", "renameSync", "copyFile", "copyFileSync", "cp", "cpSync", "symlink", "symlinkSync", "link", "linkSync",
    "truncate", "truncateSync", "ftruncate", "ftruncateSync", "chmod", "chmodSync", "chown", "chownSync", "lchown", "lchownSync", "utimes", "utimesSync",
    "futimes", "futimesSync", "lutimes", "lutimesSync", "write", "writeSync", "writev", "writevSync", "fchmod", "fchmodSync", "fchown", "fchownSync", "lchmod", "lchmodSync", "WriteStream", "mkdtempDisposable",
})
READ_MEMBERS = frozenset({
    "readFile", "readFileSync", "readdir", "readdirSync", "stat", "statSync", "lstat", "lstatSync", "readlink", "readlinkSync", "access", "accessSync",
    "exists", "existsSync", "opendir", "opendirSync", "createReadStream", "realpath", "realpathSync", "glob", "globSync", "watch", "watchFile", "read", "readSync",
    "readv", "readvSync", "statfs", "statfsSync", "fstat", "fstatSync", "ReadStream",
})
OPEN_MEMBERS = frozenset({"open", "openSync"})  # read or write depending on the flags
WRITE_REFS = frozenset({"sqlite", "Bun.write", "Deno.writeFile", "Deno.writeTextFile", "Deno.remove", "Deno.mkdir", "Deno.rename", "Deno.copyFile", "Deno.symlink", "Deno.truncate"})
READ_REFS = frozenset({"Bun.file", "Deno.readFile", "Deno.readTextFile", "Deno.readDir", "Deno.stat", "Deno.lstat", "Deno.readLink"})
GLOBAL_PREFIXES = ("globalThis.", "global.", "self.", "window.")
STDOUT_REFS = frozenset({"console.log", "console.info", "console.debug", "console.dir", "console.table", "console.trace", "console.group", "console.dirxml", "process.stdout", "process.stdin"})
# not erasable: `node server.ts` refuses these (it only strips types), so a file that uses them would fail to start
NON_ERASABLE = {
    "enum_declaration": "an enum", "internal_module": "a namespace", "module": "a namespace", "import_require_clause": "`import x = require()`",
    "export_assignment": "`export =`", "decorator": "a decorator", "import_alias": "an import alias",
}

KNOWN_GLOBALS = frozenset({
    "undefined", "NaN", "Infinity", "Object", "Array", "String", "Number", "Boolean", "BigInt", "Symbol", "Math", "JSON", "Date", "RegExp", "Map", "Set", "WeakMap",
    "WeakSet", "WeakRef", "Promise", "Error", "TypeError", "RangeError", "SyntaxError", "EvalError", "ReferenceError", "URIError", "AggregateError", "Intl", "parseInt",
    "parseFloat", "isNaN", "isFinite", "encodeURIComponent", "decodeURIComponent", "encodeURI", "decodeURI", "escape", "unescape", "ArrayBuffer", "SharedArrayBuffer",
    "DataView", "Int8Array", "Uint8Array", "Uint8ClampedArray", "Int16Array", "Uint16Array", "Int32Array", "Uint32Array", "Float32Array", "Float64Array", "BigInt64Array",
    "BigUint64Array", "TextEncoder", "TextDecoder", "URL", "URLSearchParams", "Buffer", "atob", "btoa", "structuredClone", "queueMicrotask", "setTimeout", "setInterval",
    "setImmediate", "clearTimeout", "clearInterval", "clearImmediate", "AbortController", "AbortSignal", "Event", "EventTarget", "Blob", "Headers", "Request", "Response",
    "FormData", "performance", "crypto", "console", "process", "fetch", "WebAssembly", "globalThis", "global", "eval", "Function", "Reflect", "Proxy", "Atomics",
    "arguments", "Iterator", "FinalizationRegistry", "XMLHttpRequest", "WebSocket", "EventSource", "navigator", "Worker", "SharedWorker", "self", "window", "module",
    "exports", "require", "__dirname", "__filename", "Bun", "Deno", "Error", "DOMException", "MessageChannel", "BroadcastChannel", "ReadableStream", "WritableStream",
})
UNDEFINED_IN_ESM = frozenset({"require", "module", "exports", "__dirname", "__filename"})  # known to JavaScript, but not defined in an ES module


def _hit(name: str, refs: frozenset[str]) -> bool:
    return any(name == r or name.startswith(r + ".") for r in refs)


def _plain(module: str) -> str:
    return module[5:] if module.startswith("node:") else module


@dataclass
class NodeToolFact:
    name: str
    described: bool
    line: int
    capabilities: set[str] = field(default_factory=set)
    dynamic: set[str] = field(default_factory=set)
    free: set[str] = field(default_factory=set)  # names the tool uses that it does not define itself (what the builder holds to an allow-list)
    props: set[str] = field(default_factory=set)  # every property name it reaches, by dot or by a literal key
    strings: set[str] = field(default_factory=set)  # every string literal in it (short ones), for the builder's deny-list
    calls_outside: bool = False  # calls something defined elsewhere in the file: what that does is not followed
    process_other: bool = False
    stdout: bool = False
    computed: bool = False
    unsafe_index: list[str] = field(default_factory=list)  # computed property names that are not provably numbers: how a program reaches `constructor`
    declared: set[str] = field(default_factory=set)  # every name declared anywhere inside the handler (a declaration can hide a built-in name)
    mutates: list[str] = field(default_factory=list)  # built-ins it assigns to or deletes from: `JSON.stringify = ...`
    meta: bool = False  # uses import.meta


@dataclass
class NodeFacts:
    server_name: str | None = None
    has_server: bool = False
    server_count: int = 0
    tools: list[NodeToolFact] = field(default_factory=list)
    connects: bool = False
    imports: set[str] = field(default_factory=set)  # every module specifier, `node:` dropped; "." marks a relative one
    imported: set[str] = field(default_factory=set)  # `module.name` for every name an import binds
    refs: set[str] = field(default_factory=set)
    capabilities: set[str] = field(default_factory=set)  # read_files, write_files, network, run_commands
    dynamic: set[str] = field(default_factory=set)
    env_names: set[str] = field(default_factory=set)
    env_dynamic: bool = False
    process_other: bool = False  # `process` used for anything but reading an environment variable by name
    unsafe_index: list[str] = field(default_factory=list)  # computed property names that are not provably numbers, anywhere in the file
    secrets: list[tuple[int, str]] = field(default_factory=list)
    undefined: set[str] = field(default_factory=set)
    unused_imports: set[str] = field(default_factory=set)
    stdout: bool = False
    non_erasable: set[str] = field(default_factory=set)
    computed: bool = False  # reaches a property by a computed name somewhere


# ---- reading the tree ----------------------------------------------------------------------------------------------------

_CTX: ContextVar[Any] = ContextVar("mcp_node_tree", default=None)
MAX_REGISTERED = 64  # registerTool calls read; more than this is refused (each one is read together with everything inside it)


class _Tree:
    """What is looked up again and again about one parsed file, worked out once: each node's parent (`node.parent` takes time in proportion to the depth, which made a
    long sum take quadratic time) and the nodes that sit inside an import statement."""

    def __init__(self, nodes: list[Any]) -> None:
        self.parents: dict[int, Any] = {}
        for node in nodes:
            for child in node.children:
                self.parents[child.id] = node
        self.imports: set[int] = set()
        for node in nodes:
            if node.type == "import_statement" or (node.type == "export_statement" and _field(node, "source") is not None):
                stack = [node]
                while stack:
                    inner = stack.pop()
                    self.imports.add(inner.id)
                    stack.extend(inner.children)


def _parent(node: Any) -> Any:
    tree = _CTX.get()
    return tree.parents.get(node.id) if tree is not None else node.parent


def _parse(source: str) -> Any:
    parser, why = languages.get_parser("typescript")
    if parser is None:
        raise ValueError(f"the TypeScript grammar is not available ({why}), so this file cannot be read")
    tree = parser.parse(source.encode("utf-8"))
    root = tree.root_node
    if root.has_error:
        bad = next((n for n in _walk(root) if n.type == "ERROR" or n.is_missing), None)
        line = (bad.start_point[0] + 1) if bad is not None else 1
        raise SyntaxError(f"it has a syntax error near line {line}")
    return root


def _walk(root: Any) -> Iterator[Any]:
    stack = [root]
    seen = 0
    while stack:
        node = stack.pop()
        seen += 1
        if seen > MAX_NODES:
            raise ValueError("the file is too large to read")
        yield node
        stack.extend(reversed(node.children))


_IDENT_NODES = frozenset({"identifier", "property_identifier", "shorthand_property_identifier", "shorthand_property_identifier_pattern", "private_property_identifier"})
_UNICODE_ESCAPE = re.compile(r"\\u\{([0-9A-Fa-f]+)\}|\\u([0-9A-Fa-f]{4})")
_LINE_CONTINUATION = re.compile("\\\\(?:\r\n|\n|\r|\u2028|\u2029)")


def _text(node: Any) -> str:
    """The source text of a node. An identifier may be written with unicode escapes (`\\u0065val` IS `eval`, also with any number of leading zeros inside the braces), so it is read as the name it means."""
    raw = node.text.decode("utf-8", "replace")
    if "\\u" in raw and node.type in _IDENT_NODES:
        def one(match: re.Match[str]) -> str:
            try:
                return chr(int(match.group(1) or match.group(2), 16))
            except (ValueError, OverflowError):
                return match.group(0)
        return _UNICODE_ESCAPE.sub(one, raw)
    return raw


def _field(node: Any, name: str) -> Any:
    return node.child_by_field_name(name)


_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0", "\\": "\\", "'": "'", '"': '"', "`": "`", "$": "$"}
_LINE_ENDINGS = ("\n", "\r\n", "\r", "\u2028", "\u2029")


def _unescape(raw: str) -> str:
    if raw[1:] in _LINE_ENDINGS:  # a backslash before a line ending joins the lines: it adds nothing to the string
        return ""
    if len(raw) == 2 and raw[1] in _ESCAPES:
        return _ESCAPES[raw[1]]
    try:
        if raw[:2] == "\\x" and len(raw) == 4:
            return chr(int(raw[2:], 16))
        if raw[:3] == "\\u{" and raw.endswith("}"):
            return chr(int(raw[3:-1], 16))
        if raw[:2] == "\\u" and len(raw) == 6:
            return chr(int(raw[2:], 16))
    except (ValueError, OverflowError):
        pass
    return raw[1:] if raw.startswith("\\") else raw


def _string_value(node: Any) -> str | None:
    """The value of a string literal or a template without substitutions, or None for anything else."""
    if node.type == "string" or (node.type == "template_string" and not any(c.type == "template_substitution" for c in node.children)):
        parts = []
        for child in node.children:
            if child.type == "string_fragment":
                parts.append(_LINE_CONTINUATION.sub("", _text(child)))
            elif child.type == "escape_sequence":
                parts.append(_unescape(_text(child)))
        return "".join(parts)
    return None


def _unwrap(node: Any) -> Any:
    while node is not None and node.type in ("parenthesized_expression", "as_expression", "non_null_expression", "satisfies_expression", "type_assertion", "sequence_expression"):
        if node.type == "sequence_expression":  # `(0, process)` is `process`: a sequence is worth its last part
            inner = node.named_children[-1] if node.named_children else None
        elif node.type == "as_expression":
            inner = node.named_children[0]
        else:
            inner = next((c for c in node.named_children if c.type not in ("type_annotation",)), None)
        if inner is None:
            break
        node = inner
    return node


def _fold(node: Any, consts: dict[str, str] | None = None) -> str | None:
    """A string built only of literals (and constants that are themselves such strings) joined with `+`, or None. Iterative and bounded."""
    pieces: list[str] = []
    stack = [node]
    visited = 0
    while stack:
        current = _unwrap(stack.pop())
        visited += 1
        if visited > 2000 or current is None:
            return None
        if current.type == "binary_expression":
            op = _field(current, "operator")
            if op is None or _text(op) != "+":
                return None
            stack.append(_field(current, "right"))
            stack.append(_field(current, "left"))
            continue
        if current.type == "identifier" and consts and _text(current) in consts:
            value: str | None = consts[_text(current)]
        else:
            value = _string_value(current)
        if value is None:
            return None
        pieces.append(value)
        if sum(map(len, pieces)) > FOLD_LIMIT:
            return None
    return "".join(pieces)


def _binding_names(pattern: Any) -> list[Any]:
    """Every identifier node a binding pattern declares or assigns (not the default values or computed keys inside it)."""
    out: list[Any] = []
    stack = [pattern]
    while stack:
        node = stack.pop()
        if node is None:
            continue
        if node.type in ("identifier", "shorthand_property_identifier_pattern"):
            out.append(node)
        elif node.type in ("object_pattern", "array_pattern", "rest_pattern"):
            stack.extend(node.named_children)
        elif node.type == "pair_pattern":
            stack.append(_field(node, "value"))
        elif node.type in ("assignment_pattern", "object_assignment_pattern"):
            stack.append(_field(node, "left"))
        elif node.type in ("required_parameter", "optional_parameter"):
            stack.append(_field(node, "pattern"))
    return out


def _declared_names(nodes: Iterator[Any]) -> Iterator[str]:
    """Names declared by the nodes given, one per declaration: variables, parameters, functions, classes, imports, catch and loop variables."""
    for node in nodes:
        kind = node.type
        if kind == "variable_declarator":
            yield from (_text(n) for n in _binding_names(_field(node, "name")))
        elif kind in ("required_parameter", "optional_parameter"):
            yield from (_text(n) for n in _binding_names(node))
        elif kind in ("function_declaration", "generator_function_declaration", "class_declaration", "function_expression", "generator_function", "class", "enum_declaration", "internal_module"):
            name = _field(node, "name")
            if name is not None:
                yield _text(name)
        elif kind == "arrow_function":
            single = _field(node, "parameter")
            if single is not None:
                yield _text(single)
        elif kind == "catch_clause":
            param = _field(node, "parameter")
            if param is not None:
                yield from (_text(n) for n in _binding_names(param))
        elif kind == "for_in_statement" and _field(node, "kind") is not None:
            yield from (_text(n) for n in _binding_names(_field(node, "left")))
        elif kind == "import_specifier":
            yield _text(_field(node, "alias") or _field(node, "name"))
        elif kind in ("namespace_import", "import_clause"):
            yield from (_text(c) for c in node.named_children if c.type == "identifier")


def _declared_in(nodes: Iterator[Any]) -> set[str]:
    return set(_declared_names(nodes))


# ---- names ---------------------------------------------------------------------------------------------------------------


class _Names:
    """What a local name can stand for. A name keeps EVERY meaning it is given anywhere in the file (an import, `const w = fs.writeFileSync`, `const { exec } = cp`, and a
    decoy `const Function = o` in some other function) and always keeps its own spelling too, so a declaration somewhere else can add a meaning to a name but never take
    one away. A constant that is a string built of literals is remembered, so `x[k]` with `const k = "con" + "structor"` is read as `x.constructor`."""

    def __init__(self, nodes: list[Any]) -> None:
        self.alias: dict[str, list[str]] = {}
        self.consts: dict[str, str] = {}
        counts = Counter(_declared_names(iter(nodes)))
        for node in nodes:
            if node.type != "import_statement":
                continue
            source = _field(node, "source")
            module = _plain(_string_value(source) or "") if source is not None else ""
            builtin = module in KNOWN_NODE_MODULES  # a Node module's default import IS the module (`import fs from "node:fs"`), not a `default` member of it
            for clause in node.named_children:
                if clause.type != "import_clause":
                    continue
                for part in clause.named_children:
                    if part.type == "identifier":
                        self._add(_text(part), module if builtin else f"{module}.default")
                    elif part.type == "namespace_import":
                        for ident in part.named_children:
                            if ident.type == "identifier":
                                self._add(_text(ident), module)
                    elif part.type == "named_imports":
                        for spec in part.named_children:
                            if spec.type == "import_specifier":
                                name, alias = _field(spec, "name"), _field(spec, "alias")
                                self._add(_text(alias or name), module if (builtin and _text(name) == "default") else f"{module}.{_text(name)}")
        for _ in range(3):  # a constant built of other constants takes a pass more
            for node in nodes:
                if node.type != "variable_declarator":
                    continue
                target, value = _field(node, "name"), _field(node, "value")
                if target is None or value is None or target.type != "identifier" or counts[_text(target)] != 1 or _text(target) in self.consts:
                    continue
                parent = _parent(node)
                if parent is not None and parent.type == "lexical_declaration" and parent.children and parent.children[0].type == "const":
                    folded = _fold(value, self.consts)
                    if folded is not None:
                        self.consts[_text(target)] = folded
        for _ in range(2):  # a second pass lets an alias of an alias resolve
            for node in nodes:
                if node.type != "variable_declarator":
                    continue
                target, value = _field(node, "name"), _field(node, "value")
                if target is None or value is None:
                    continue
                wholes = self.quals(value)
                if wholes:
                    self._bind(target, wholes)

    def _add(self, name: str, whole: str) -> None:
        meanings = self.alias.setdefault(name, [])
        if whole not in meanings:
            meanings.append(whole)

    def _bind(self, target: Any, wholes: list[str]) -> None:
        if target is None:
            return
        kind = target.type
        if kind == "identifier":
            for whole in wholes:
                self._add(_text(target), whole)
        elif kind == "assignment_pattern":
            self._bind(_field(target, "left"), wholes)
        elif kind == "object_pattern":
            for child in target.named_children:
                if child.type == "shorthand_property_identifier_pattern":
                    for whole in wholes:
                        self._add(_text(child), f"{whole}.{_text(child)}")
                elif child.type == "object_assignment_pattern":
                    left = _field(child, "left")
                    if left is not None:
                        for whole in wholes:
                            self._add(_text(left), f"{whole}.{_text(left)}")
                elif child.type == "pair_pattern":
                    key, inner = self.key_of(_field(child, "key")), _field(child, "value")
                    if key is not None and inner is not None:
                        self._bind(inner, [f"{whole}.{key}" for whole in wholes])

    def key_of(self, key: Any) -> str | None:
        """The name a property key spells (`constructor`, `"constructor"`, `["con" + "structor"]`), or None when it cannot be read."""
        if key is None:
            return None
        if key.type in ("property_identifier", "private_property_identifier"):
            return _text(key)
        literal = _string_value(key)
        if literal is not None:
            return literal
        if key.type == "computed_property_name":
            inner = next(iter(key.named_children), None)
            return self.literal(inner) if inner is not None else None
        return None

    def literal(self, node: Any) -> str | None:
        return _fold(node, self.consts)

    def heads(self, name: str) -> list[str]:
        """Every meaning a name has, and its own spelling too (a decoy declaration elsewhere adds a meaning; it never removes one)."""
        meanings = list(self.alias.get(name, []))
        if name not in meanings:
            meanings.append(name)
        return meanings

    def quals(self, node: Any) -> list[str]:
        """Every dotted name an identifier or a member chain can stand for (after each meaning its first name has anywhere in the file), or [] when it starts from something else."""
        parts: list[str] = []
        node = _unwrap(node)
        name = ""
        while node is not None:
            if node.type in ("identifier", "shorthand_property_identifier"):
                name = _text(node)
                break
            if node.type == "member_expression":
                prop = _field(node, "property")
                if prop is None:
                    return []
                parts.append(_text(prop))
                node = _unwrap(_field(node, "object"))
            elif node.type == "subscript_expression":
                index = _field(node, "index")
                literal = self.literal(index) if index is not None else None
                if literal is None:
                    return []
                parts.append(literal)
                node = _unwrap(_field(node, "object"))
            else:
                return []
        else:
            return []
        out: list[str] = []
        for head in self.heads(name):
            full = ".".join([head, *reversed(parts)])
            for prefix in GLOBAL_PREFIXES:
                while full.startswith(prefix):
                    full = full[len(prefix):]
            full = _plain(full)
            if full not in out:
                out.append(full)
        return out

    def qual(self, node: Any) -> str | None:
        found = self.quals(node)
        return found[0] if found else None


# ---- the analysis --------------------------------------------------------------------------------------------------------


def _object_text(node: Any, key: str) -> str | None:
    """The string value of `key` in an object literal, or None."""
    if node is None or node.type != "object":
        return None
    for pair in node.named_children:
        if pair.type == "pair":
            k = _field(pair, "key")
            if k is not None and (_text(k) == key or _string_value(k) == key):
                return _string_value(_unwrap(_field(pair, "value"))) if _field(pair, "value") is not None else None
    return None


def _is_object_of(node: Any) -> bool:
    """True when `node` is the thing a property is taken from (`node.x`, `node["x"]`): the chain it starts is classified as a whole."""
    parent = _parent(node)
    return parent is not None and parent.type in ("member_expression", "subscript_expression") and _field(parent, "object") is not None and _field(parent, "object").id == node.id


def _in_import(node: Any) -> bool:
    """Inside an import statement, where a name is declared or named, not used."""
    tree = _CTX.get()
    return tree is not None and node.id in tree.imports


def _is_declared_name(node: Any) -> bool:
    parent = _parent(node)
    return parent is not None and parent.type == "variable_declarator" and _field(parent, "name") is not None and _field(parent, "name").id == node.id


def _is_alias_value(node: Any) -> bool:
    """`const f = fs` or `const { rmSync } = fs`: the module is given another name, which the reading follows, not passed somewhere it cannot follow."""
    parent = _parent(node)
    if parent is None or parent.type != "variable_declarator" or _field(parent, "value") is None or _field(parent, "value").id != node.id:
        return False
    target = _field(parent, "name")
    return target is not None and target.type in ("identifier", "object_pattern")


def _root(node: Any) -> Any:
    """The identifier a chain of `.x` and `[x]` starts from, or None."""
    node = _unwrap(node)
    while node is not None and node.type in ("member_expression", "subscript_expression"):
        node = _unwrap(_field(node, "object"))
    return node if node is not None and node.type == "identifier" else None


_ARITHMETIC = frozenset({"+", "-", "*", "/", "%", "**"})


def _assigned(node: Any) -> list[Any]:
    """The identifier nodes this node assigns a new value to (`i = 1`, `i += 1`, `i++`, `[i] = x`, `({ i } = x)`, `for (i of x)`)."""
    kind = node.type
    if kind in ("assignment_expression", "augmented_assignment_expression"):
        left = _field(node, "left")
        return _binding_names(left) if left is not None else []
    if kind == "update_expression":
        argument = _field(node, "argument")
        return [argument] if argument is not None and argument.type == "identifier" else []
    if kind == "for_in_statement" and _field(node, "kind") is None:
        left = _field(node, "left")
        return _binding_names(left) if left is not None else []
    return []


def _inside(node: Any, ancestor: Any) -> bool:
    current = node
    while current is not None:
        if current.id == ancestor.id:
            return True
        current = _parent(current)
    return False


def _loop_counters(nodes: list[Any]) -> set[str]:
    """Names that are only ever numbers: declared ONLY as `for (let i = 0; ...; i++)` counters (every declaration of the name anywhere is one) and never assigned to
    anywhere but a loop's own update clause (`i++`, `i -= 2`). A name declared once more, or assigned in a pattern, in a `for (i of ...)` or in the body, is not one."""
    loops: dict[str, list[Any]] = {}
    for node in nodes:
        if node.type != "for_statement":
            continue
        init = _field(node, "initializer")
        if init is None:
            continue
        for decl in (c for c in init.named_children if c.type == "variable_declarator"):
            target, value = _field(decl, "name"), _field(decl, "value")
            if target is not None and target.type == "identifier" and value is not None and value.type == "number":
                loops.setdefault(_text(target), []).append(_field(node, "increment"))
    if not loops:
        return set()
    declared = Counter(_declared_names(iter(nodes)))
    candidates = {name: updates for name, updates in loops.items() if declared[name] == len(updates)}
    for node in nodes:
        for target in _assigned(node):
            name = _text(target)
            if name not in candidates:
                continue
            numeric = node.type == "update_expression" or (
                node.type == "augmented_assignment_expression" and _field(node, "right") is not None and _field(node, "right").type == "number" and _field(node, "operator") is not None
                and _text(_field(node, "operator")) in ("+=", "-=")
            )
            if not (numeric and any(update is not None and _inside(node, update) for update in candidates[name])):
                candidates.pop(name, None)
    return set(candidates)


def _safe_index(index: Any, counters: set[str]) -> bool:
    """True when a computed property name is provably a number: a number, a name that is only a loop counter, or arithmetic with a number in it (`s.length - 1`, `i + 1`)."""
    node = _unwrap(index)
    if node is None:
        return False
    if node.type == "number":
        return True
    if node.type == "identifier":
        return _text(node) in counters
    if node.type == "unary_expression" and _field(node, "operator") is not None and _text(_field(node, "operator")) in ("-", "+"):
        return _safe_index(_field(node, "argument"), counters)
    if node.type == "binary_expression":
        op = _field(node, "operator")
        if op is None or _text(op) not in _ARITHMETIC:
            return False
        left, right = _unwrap(_field(node, "left")), _unwrap(_field(node, "right"))
        numeric = any(n is not None and n.type == "number" for n in (left, right))
        stringy = any(n is not None and n.type in ("string", "template_string") for n in (left, right))
        return numeric and not stringy
    return False


def _pattern_key(node: Any, names: _Names) -> tuple[str | None, bool]:
    """(the property a destructuring pattern takes, or None; whether it is taken by a computed name that cannot be read)."""
    if node.type == "shorthand_property_identifier_pattern":
        return _text(node), False
    key = _field(node, "key")
    if key is None or key.type == "number":
        return None, False
    name = names.key_of(key)
    if name is not None:
        return name, False
    if key.type == "computed_property_name":
        inner = next(iter(key.named_children), None)
        if inner is None or _unwrap(inner).type == "number":
            return None, False
        return None, True
    return None, False


def _sensitive(head: str) -> bool:
    """A name that, reached by a computed property, could be anything dangerous: a module that runs programs, writes, reads or reaches the network, or a way to build code."""
    return (
        _hit(head, DYNAMIC_REFS) or _hit(head, COMMAND_REFS) or _hit(head, NETWORK_REFS) or _hit(head, WRITE_REFS) or _hit(head, READ_REFS)
        or head in FS_MODULES or head.split(".")[0] in ("fs", "process", "fs/promises")
    )


def _classify(nodes: list[Any], names: _Names, into: NodeFacts | NodeToolFact) -> None:
    """Add what `nodes` do to `into`. The same rules run over the whole file and over each tool."""
    caps, dynamic = into.capabilities, into.dynamic
    counters = _loop_counters(nodes)
    tool = into if isinstance(into, NodeToolFact) else None
    for node in nodes:
        kind = node.type
        if kind in ("member_expression", "subscript_expression", "identifier", "shorthand_property_identifier") and not _is_object_of(node) and not _in_import(node) and not (kind == "identifier" and _is_declared_name(node)):
            wholes = names.quals(node)
            if not wholes and kind not in ("identifier", "shorthand_property_identifier"):
                root = _root(node)
                if root is not None:  # a computed name (`globalThis[k]`, `fs[k]`): what it starts from is still known
                    wholes = names.heads(_text(root))
                    if kind == "subscript_expression" and "process.env" not in names.quals(_field(node, "object")) and any(_sensitive(h) for h in wholes):
                        dynamic.add(f"a property of {wholes[0].split('.')[0]} chosen by a computed name")
            aliased = _is_alias_value(node)
            for whole in wholes:
                _ref(whole, node, into, alias=aliased)
        if kind == "member_expression":
            prop = _field(node, "property")
            if prop is not None:
                name = _text(prop)
                if tool is not None:
                    tool.props.add(name)
                if name in DYNAMIC_PROPS:
                    dynamic.add(f"the property .{name}")
        elif kind in ("pair_pattern", "shorthand_property_identifier_pattern"):
            # destructuring takes a property by name just as `.name` does: `const { constructor: A } = []` reaches Array, and `A.constructor` Function
            name, unsafe = _pattern_key(node, names)
            if name is not None:
                if tool is not None:
                    tool.props.add(name)
                if name in DYNAMIC_PROPS:
                    dynamic.add(f"the property {name}, taken by destructuring")
            elif unsafe:
                into.computed = True
                key = _field(node, "key") if node.type == "pair_pattern" else None
                inner = next(iter(key.named_children), None) if key is not None else None
                if inner is None or not _safe_index(inner, counters):
                    into.unsafe_index.append(("{ [" + (_text(inner) if inner is not None else "?") + "]: ... }")[:40])
        elif kind == "subscript_expression":
            index = _field(node, "index")
            literal = names.literal(index) if index is not None else None
            if literal is not None:
                if tool is not None:
                    tool.props.add(literal)
                if literal in DYNAMIC_PROPS:
                    dynamic.add(f'the property ["{literal}"]')
            elif index is not None and index.type != "number":
                into.computed = True
                if not _safe_index(index, counters) and "process.env" not in names.quals(_field(node, "object")):
                    into.unsafe_index.append(_text(index)[:40])
        elif kind == "call_expression":
            function = _field(node, "function")
            args = _field(node, "arguments")
            first = args.named_children[0] if args is not None and args.named_children else None
            if function is not None and function.type == "import":
                dynamic.add("import() of a module chosen while running")
                literal = _string_value(_unwrap(first)) if first is not None else None
                if literal is not None:
                    _ref(_plain(literal), node, into)
            for whole in (names.quals(function) if function is not None else []):
                if whole in ("setTimeout", "setInterval", "setImmediate") and first is not None and _unwrap(first).type in ("string", "template_string"):
                    dynamic.add(f"{whole} with a string (it is run as code)")
                head, _, member = whole.rpartition(".")
                if member in OPEN_MEMBERS and head in FS_MODULES + tuple(f"{m}.promises" for m in FS_MODULES):
                    flags = args.named_children[1] if args is not None and len(args.named_children) > 1 else None
                    value = _string_value(_unwrap(flags)) if flags is not None else "r"
                    caps.add("read_files")
                    if value is None or not value.startswith("r") or "+" in value:
                        caps.add("write_files")
                if tool is not None and whole in ("Object.assign", "Object.defineProperties") and first is not None and _unwrap(first).type == "identifier" and _text(_unwrap(first)) in KNOWN_GLOBALS:
                    tool.mutates.append(_text(_unwrap(first)))
        elif kind == "new_expression":
            ctor = _field(node, "constructor")
            for whole in (names.quals(ctor) if ctor is not None else []):
                _ref(whole, node, into)
        elif kind == "meta_property" and tool is not None:
            tool.meta = True
        elif isinstance(into, NodeFacts) and (kind in NON_ERASABLE or (kind == "accessibility_modifier" and _parent(node) is not None and _parent(node).type in ("required_parameter", "optional_parameter"))):
            into.non_erasable.add(NON_ERASABLE.get(kind, "a constructor parameter with a modifier"))
        if tool is not None and kind in ("assignment_expression", "augmented_assignment_expression", "update_expression", "unary_expression"):
            target = None
            if kind == "unary_expression":
                op = _field(node, "operator")
                target = _field(node, "argument") if op is not None and _text(op) == "delete" else None
            elif kind == "update_expression":
                target = _field(node, "argument")
            else:
                target = _field(node, "left")
            if target is not None:
                inner = _unwrap(target)
                root = _root(inner) if inner.type in ("member_expression", "subscript_expression") else (inner if inner.type == "identifier" else None)
                if root is not None and _text(root) in KNOWN_GLOBALS:  # `JSON.stringify = ...`, `delete Map.get`, `Math.max++`: a built-in every tool and the SDK share
                    tool.mutates.append(_text(root))


def _ref(whole: str | None, node: Any, into: NodeFacts | NodeToolFact, alias: bool = False) -> None:
    if whole is None:
        return
    caps, dynamic = into.capabilities, into.dynamic
    if isinstance(into, NodeFacts):
        into.refs.add(whole)
    if _hit(whole, COMMAND_REFS):
        caps.add("run_commands")
    if _hit(whole, DYNAMIC_REFS):
        top = whole.split(".")[0]
        dynamic.add(top if top in DYNAMIC_REFS else whole)
    if _hit(whole, NETWORK_REFS):
        caps.add("network")
    if _hit(whole, WRITE_REFS):
        caps.add("write_files")
    if _hit(whole, READ_REFS):
        caps.add("read_files")
    if not alias and (whole in FS_MODULES or whole in tuple(f"{m}.promises" for m in FS_MODULES)):
        dynamic.add(f"the {whole} module used as a value, so what is called on it cannot be followed")
    for module in FS_MODULES:
        for base in (module, f"{module}.promises"):
            if whole.startswith(base + "."):
                member = whole[len(base) + 1:].split(".")[0]
                if member in WRITE_MEMBERS:
                    caps.add("write_files")
                elif member in READ_MEMBERS:
                    caps.add("read_files")
    if _hit(whole, STDOUT_REFS):
        into.stdout = True
    if whole.split(".")[0] == "process" and not (whole == "process.env" or whole.startswith("process.env.")):
        into.process_other = True


def _env(nodes: list[Any], names: _Names, facts: NodeFacts) -> None:
    """Environment variables: `process.env.NAME`, `process.env["NAME"]`, `process["env"].NAME` and `const { NAME } = process.env` are plain reads by name; anything else reads
    them by a computed name or all of them."""
    for node in nodes:
        if node.type not in ("member_expression", "subscript_expression", "identifier") or _in_import(node) or (node.type == "identifier" and _is_declared_name(node)):
            continue
        if "process.env" not in names.quals(node):
            continue
        parent = _parent(node)
        ok = False
        if _is_object_of(node):
            if parent.type == "member_expression":
                prop = _field(parent, "property")
                if prop is not None and prop.type == "property_identifier":
                    facts.env_names.add(_text(prop))
                    ok = True
            else:
                index = _field(parent, "index")
                literal = names.literal(index) if index is not None else None
                if literal is not None:
                    facts.env_names.add(literal)
                    ok = True
        elif parent is not None and parent.type == "variable_declarator" and _field(parent, "value") is not None and _field(parent, "value").id == node.id:
            target = _field(parent, "name")
            if target is not None and target.type == "object_pattern":
                ok = True
                for child in target.named_children:
                    if child.type == "shorthand_property_identifier_pattern":
                        facts.env_names.add(_text(child))
                    elif child.type == "pair_pattern" and _field(child, "key") is not None and _field(child, "key").type == "property_identifier":
                        facts.env_names.add(_text(_field(child, "key")))
                    else:
                        ok = False  # `...rest` or a computed key: all of them
        if not ok:
            facts.env_dynamic = True


_BARE_PACKAGE = re.compile(r"^(@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*(/[A-Za-z0-9._-]+)*$", re.I)


def _import_spec(raw: str, facts: NodeFacts) -> None:
    """Record an import specifier. A Node module (`node:fs`) or a bare package name is a module the person installs; ANYTHING else (a path, a `data:` or `https:` URL, `#name`) is
    code the checks never read, which is what `other code beside it` is for files, so it is code built while loading."""
    if raw.startswith("node:") or _BARE_PACKAGE.match(raw):
        facts.imports.add(_plain(raw))
        return
    facts.imports.add(".")
    facts.dynamic.add(f"an import of code that is not a package or a Node module ({raw[:40]}), which the checks never read")


def analyze_node_server(source: str) -> NodeFacts:
    """Read `server.ts` by syntax. Raises SyntaxError (it does not parse) or ValueError (it cannot be read at all)."""
    root = _parse(source)
    nodes = list(_walk(root))
    if sum(1 for n in nodes if n.type == "property_identifier" and _text(n) in ("registerTool", "tool")) > MAX_REGISTERED:
        raise ValueError(f"it registers more than {MAX_REGISTERED} tools, which is too many to read")
    token = _CTX.set(_Tree(nodes))
    try:
        return _analyze(source, nodes)
    finally:
        _CTX.reset(token)


def _analyze(source: str, nodes: list[Any]) -> NodeFacts:
    names = _Names(nodes)
    facts = NodeFacts()
    _classify(nodes, names, facts)
    _env(nodes, names, facts)
    declared = _declared_in(iter(nodes))

    for node in nodes:
        if node.type == "import_statement" or (node.type == "export_statement" and _field(node, "source") is not None):
            raw = _string_value(_field(node, "source")) if _field(node, "source") is not None else None
            _import_spec(raw if raw is not None else "", facts)
    facts.imported = {v for meanings in names.alias.values() for v in meanings if "." in v and not v.startswith(".")} | {m for m in facts.imports if m}
    for module in list(facts.imports):
        facts.refs.add(module)
        if _hit(module, COMMAND_REFS):
            facts.capabilities.add("run_commands")
        if _hit(module, DYNAMIC_REFS):
            facts.dynamic.add(module)
        if _hit(module, NETWORK_REFS):
            facts.capabilities.add("network")
        if _hit(module, WRITE_REFS):
            facts.capabilities.add("write_files")

    # the server and its tools
    server_vars: set[str] = set()
    for node in nodes:
        if node.type == "new_expression":
            ctor = _field(node, "constructor")
            whole = names.qual(ctor) if ctor is not None else None
            if whole is not None and whole.split(".")[-1] == "McpServer":
                facts.has_server = True
                facts.server_count += 1
                args = _field(node, "arguments")
                if args is not None and args.named_children and facts.server_name is None:
                    facts.server_name = _object_text(_unwrap(args.named_children[0]), "name")
                parent = _parent(node)
                if parent is not None and parent.type == "variable_declarator" and _field(parent, "name") is not None:
                    server_vars.update(_text(n) for n in _binding_names(_field(parent, "name")))
    for node in nodes:
        if node.type != "call_expression":
            continue
        function = _field(node, "function")
        if function is None:
            continue
        whole = names.qual(function)
        if whole is not None and whole.split(".")[-1] in ("serveStdio",):
            facts.connects = True
        obj, prop = None, None
        if function.type == "member_expression" and _field(function, "property") is not None:
            obj, prop = _field(function, "object"), _text(_field(function, "property"))
        elif function.type == "subscript_expression" and _field(function, "index") is not None:
            obj, prop = _field(function, "object"), names.literal(_field(function, "index"))
        if prop is not None:
            if prop == "connect" and obj is not None and obj.type == "identifier" and _text(obj) in server_vars:
                facts.connects = True
            if prop in ("registerTool", "tool") and obj is not None and obj.type == "identifier" and _text(obj) in server_vars:
                _tool(node, prop, names, declared, facts)
            elif prop in ("registerTool", "tool", "registerResource", "registerPrompt", "resource", "prompt"):
                facts.dynamic.add(f"{prop} called on something that is not the server variable")
        elif function.type == "identifier" and _text(function) in ("registerTool",):
            facts.dynamic.add("registerTool called through another name")

    # names used but never defined; imports nothing reads
    uses: dict[str, int] = {}
    for node in nodes:
        if node.type in ("identifier", "shorthand_property_identifier") and not _in_import(node):
            parent = _parent(node)
            if node.type == "identifier" and parent is not None and parent.type == "member_expression" and _field(parent, "property") is not None and _field(parent, "property").id == node.id:
                continue
            uses[_text(node)] = uses.get(_text(node), 0) + 1
    for name in uses:
        if name not in declared and (name not in KNOWN_GLOBALS or name in UNDEFINED_IN_ESM):
            facts.undefined.add(name)
    for node in nodes:
        if node.type == "import_specifier":
            local = _text(_field(node, "alias") or _field(node, "name"))
            if not uses.get(local):
                facts.unused_imports.add(local)

    # keys: in the raw text, and in strings folded from pieces (only the outermost `+` of a chain is folded: the inner ones are part of it)
    for pattern_label, pattern in SECRET_PATTERNS:
        for match in pattern.finditer(source):
            facts.secrets.append((source.count("\n", 0, match.start()) + 1, pattern_label))
    inner_sums: set[int] = set()
    for node in nodes:
        if node.type == "binary_expression":
            for side in ("left", "right"):
                child = _field(node, side)
                if child is not None and child.type == "binary_expression":
                    inner_sums.add(child.id)
    for node in nodes:
        if node.type == "binary_expression" and node.id not in inner_sums:
            folded = _fold(node, names.consts)
            if folded:
                for pattern_label, pattern in SECRET_PATTERNS:
                    if pattern.search(folded):
                        facts.secrets.append((node.start_point[0] + 1, pattern_label))
    facts.capabilities |= {c for t in facts.tools for c in t.capabilities}
    facts.dynamic |= {d for t in facts.tools for d in t.dynamic if d}
    return facts


def _tool(call: Any, how: str, names: _Names, declared_in_file: set[str], facts: NodeFacts) -> None:
    args = _field(call, "arguments")
    items = args.named_children if args is not None else []
    if not items:
        return
    tool_name = _string_value(_unwrap(items[0]))
    config = _unwrap(items[1]) if len(items) > 1 else None
    handler = next((_unwrap(a) for a in reversed(items) if _unwrap(a).type in ("arrow_function", "function_expression", "function")), None)
    described = bool(_object_text(config, "description")) if how == "registerTool" else any(_string_value(_unwrap(a)) for a in items[1:-1])
    sub = list(_walk(call))
    tool = NodeToolFact(name=tool_name or "", described=described, line=call.start_point[0] + 1)
    if tool_name is None:
        facts.dynamic.add("a tool registered under a name that is not written in the code")
    _classify(sub, names, tool)
    inner = _declared_in(iter(sub))
    own = list(_walk(handler)) if handler is not None else []
    inner_handler = _declared_in(iter(own))
    tool.declared = set(inner_handler)
    for node in own:
        if node.type in ("identifier", "shorthand_property_identifier"):
            parent = _parent(node)
            if node.type == "identifier" and parent is not None and parent.type == "member_expression" and _field(parent, "property") is not None and _field(parent, "property").id == node.id:
                continue
            name = _text(node)
            if name not in inner_handler:
                tool.free.add(name)
        elif node.type == "string" or node.type == "template_string":
            value = _string_value(node)
            if value is not None and len(value) <= 80:
                tool.strings.add(value)
    tool.calls_outside = any(n in declared_in_file and n not in inner for n in tool.free if n not in KNOWN_GLOBALS and n not in names.alias)
    if tool.calls_outside:
        tool.dynamic.add("a helper defined elsewhere in the file")
    facts.tools.append(tool)


# ---- the checks ----------------------------------------------------------------------------------------------------------


def _parse_files(files: Mapping[str, bytes]) -> tuple[NodeFacts | None, str]:
    raw = files.get(DEFINITION_FILE)
    if raw is None:
        return None, f"there is no {DEFINITION_FILE}"
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None, f"{DEFINITION_FILE} is not valid UTF-8"
    try:
        return analyze_node_server(source), ""
    except SyntaxError as exc:
        return None, str(exc.msg if getattr(exc, "msg", None) else exc)
    except (ValueError, RecursionError) as exc:
        return None, f"it could not be read as TypeScript: {exc}"


def analyze_for_library(files: Mapping[str, bytes]) -> NodeFacts | None:
    return _parse_files(files)[0]


def node_name_of(files: Mapping[str, bytes]) -> str | None:
    facts, _ = _parse_files(files)
    name = facts.server_name if facts else None
    return name if name and SLUG.match(name) and len(name) <= MAX_NAME else None


CODE_EXTENSIONS = frozenset({".gyp", ".gypi", ".js", ".mjs", ".cjs", ".ts", ".mts", ".cts", ".jsx", ".tsx", ".node", ".wasm", ".sh", ".bash", ".bat", ".cmd", ".ps1", ".exe", ".dll", ".so", ".dylib", ".py", ".rb", ".php", ".pl"})
CONFIG_FILES = frozenset({
    ".npmrc", ".yarnrc", ".yarnrc.yml", ".pnpmfile.cjs", "bunfig.toml", ".node-version", ".env", "npm-shrinkwrap.json", "pnpm-lock.yaml", "pnpm-workspace.yaml", "yarn.lock", "bun.lock", "bun.lockb",
})
CHECKED_FILES = (PACKAGE_FILE, LOCK_FILE)  # read by name: on Windows and macOS `Package.json` IS `package.json`, so another spelling is another way to replace what was checked


def other_node_code(files: Mapping[str, bytes]) -> list[str]:
    """Files beside server.ts that Node, or npm when it installs, would load or run: another code file (`./x.js` is imported without being read here), a
    `node_modules` folder, a config file that changes where npm fetches from."""
    found: list[str] = []
    for rel in sorted(files):
        if rel == DEFINITION_FILE:
            continue
        path = PurePosixPath(rel)
        aliased = path.name.lower() in CHECKED_FILES and rel not in CHECKED_FILES  # `PACKAGE.JSON`, `sub/package.json`
        if path.suffix.lower() in CODE_EXTENSIONS or path.name.lower() in CONFIG_FILES or aliased or "node_modules" in path.parts or "scripts" in path.parts[:-1] or "bin" in path.parts[:-1]:
            found.append(rel)
    return found


DEP_FIELDS = ("devDependencies", "optionalDependencies", "peerDependencies", "bundledDependencies", "bundleDependencies", "overrides", "resolutions", "workspaces", "pnpm")


def package_problems(files: Mapping[str, bytes]) -> tuple[list[str], list[str]]:
    """(problems that fail: it would run something or not start, problems that warn: it would install more than the pinned packages)."""
    raw = files.get(PACKAGE_FILE)
    if raw is None:
        return [f"there is no {PACKAGE_FILE}: without `\"type\": \"module\"` beside it, Node reads server.ts as CommonJS and it does not start"], []
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):
        return [f"{PACKAGE_FILE} is not valid JSON"], []
    if not isinstance(data, dict):
        return [f"{PACKAGE_FILE} is not a JSON object"], []
    fail: list[str] = []
    warn: list[str] = []
    scripts = data.get("scripts")
    if scripts:
        fail.append(f"it has scripts ({', '.join(map(str, list(scripts)[:4])) if isinstance(scripts, dict) else 'scripts'}): npm runs `preinstall`, `install`, `postinstall` and `prepare` by themselves when it installs")
    if data.get("type") != "module":
        fail.append('it does not say "type": "module", so Node reads server.ts as CommonJS and it does not start')
    for key in ("imports", "exports", "main", "bin", "directories", "config"):
        if key in data:
            warn.append(f"it has `{key}`, which changes what Node loads or what npm links")
    deps = data.get("dependencies", {})
    if not isinstance(deps, dict):
        fail.append("dependencies is not an object")
    else:
        extra = sorted(f"{k}@{v}" for k, v in deps.items() if PINNED.get(k) != v)
        missing = sorted(k for k in PINNED if k not in deps)
        if extra:
            warn.append(f"it also installs {', '.join(extra[:6])}: read them, they run when imported")
        if missing:
            warn.append(f"it does not list {', '.join(missing)}, which the server needs")
    for key in DEP_FIELDS:
        if data.get(key):
            warn.append(f"it has `{key}`: packages beyond the pinned ones, or a change to which version is used")
    return fail, warn


def check_server_ts(files: Mapping[str, bytes], folder: str | None) -> list[CheckResult]:
    facts, why = _parse_files(files)
    if facts is None:
        return [CheckResult(DEFINITION_CHECK, FAILED, why)]
    out: list[CheckResult] = []

    def row(name: str, problems: list[str], ok_detail: str = "", status: str = FAILED) -> None:
        out.append(CheckResult(name, status, "; ".join(problems)) if problems else CheckResult(name, PASSED, ok_detail))

    structure: list[str] = []
    if not facts.has_server:
        structure.append(f"it never creates an McpServer (import {{ McpServer }} from \"{SERVER_SDK}\")")
    elif not facts.server_name:
        structure.append("the McpServer has no name written in the code")
    elif not SLUG.match(facts.server_name) or len(facts.server_name) > MAX_NAME:
        structure.append(f"the server name must be lowercase letters, digits and hyphens, at most {MAX_NAME} characters")
    if facts.server_count > 1:
        structure.append("it creates more than one McpServer: tools on the second one are not seen by these checks")
    if facts.has_server and not facts.tools:
        structure.append("it registers no tool (server.registerTool(\"name\", {...}, handler))")
    if facts.has_server and not facts.connects:
        structure.append("it never connects a transport (await server.connect(new StdioServerTransport())), so starting it would do nothing")
    row(DEFINITION_CHECK, structure, f"{len(facts.tools)} tool(s)")
    row(SYNTAX_CHECK, [f"it uses {', '.join(sorted(facts.non_erasable))}: `node server.ts` only removes types, so this stops it from starting"] if facts.non_erasable else [], "types only")
    row(FOLDER_CHECK, [] if folder is None or folder == facts.server_name else [f"the folder is '{folder}' but the server calls itself '{facts.server_name}'"])
    bare = [t.name for t in facts.tools if not t.described]
    row(DESCRIBED_CHECK, [f"no description on: {', '.join(bare)}. Claude decides when to use a tool from it"] if bare else [], status=WARNING)
    missing = sorted(facts.undefined)
    row(UNDEFINED_CHECK, [f"it uses {', '.join(missing)} but never defines or imports it, so the first call that reaches it fails with a ReferenceError"] if missing else [], "none found", status=WARNING)
    dangerous = sorted(facts.dynamic | ({"starts other programs"} if "run_commands" in facts.capabilities else set()))
    row(COMMANDS_CHECK, [f"it uses {', '.join(dangerous)}"] if dangerous else [], "none found by syntax (a reading by syntax cannot prove there is none)")
    found = sorted({f"line {line}: {label}" for line, label in facts.secrets})
    row(SECRETS_CHECK, [f"it contains what looks like {'; '.join(found)}. Read the key from an environment variable instead"] if found else [], "none found")
    row(NETWORK_CHECK, ["it can reach other computers: read what it calls"] if "network" in facts.capabilities else [], status=WARNING)
    row(WRITES_CHECK, ["it can create, change or delete files: read what it touches"] if "write_files" in facts.capabilities else [], status=WARNING)
    row(READS_CHECK, ["it can read files: read which ones"] if "read_files" in facts.capabilities else [], status=WARNING)
    row(UNREADABLE_CHECK, [f"it reaches a property by a name the checks cannot read ({', '.join(sorted(set(facts.unsafe_index))[:3])}): that is how a program reaches `constructor` and builds code from text"] if facts.unsafe_index else [], status=WARNING)
    third = sorted(m for m in facts.imports if m and (m == "." or not (_plain(m) in KNOWN_NODE_MODULES or m == SERVER_SDK or m.startswith(SERVER_SDK + "/") or m == "zod" or m.startswith("zod/"))))
    row(IMPORTS_CHECK, [f"it also imports {', '.join('a file next to server.ts' if m == '.' else m for m in third)}: install them yourself and read what they do"] if third else [], status=WARNING)
    env_problems = ["it reads an environment variable whose name is not written in the code (or all of them), so what a secret could reach cannot be listed"] if facts.env_dynamic else []
    row(ENV_CHECK, env_problems, ("reads " + ", ".join(sorted(facts.env_names))) if facts.env_names else "reads none", status=WARNING)
    row(STDOUT_CHECK, ["it writes to standard output (console.log, process.stdout), which is the channel the protocol uses: a message there breaks the connection. Use console.error"] if facts.stdout else [], status=WARNING)
    beside = other_node_code(files)
    row(EXTRA_CODE_CHECK, [f"{', '.join(beside[:6])}{' and more' if len(beside) > 6 else ''} would be loaded or run beside it and is never read by these checks: a server is one file"] if beside else [], "only server.ts")
    fail, warn = package_problems(files)
    if fail:
        out.append(CheckResult(PACKAGE_CHECK, FAILED, "; ".join(fail)))
    elif warn:
        out.append(CheckResult(PACKAGE_CHECK, WARNING, "; ".join(warn)))
    else:
        out.append(CheckResult(PACKAGE_CHECK, PASSED, "only the pinned packages, no scripts"))
    lock = files.get(LOCK_FILE)
    if lock is None:
        out.append(CheckResult(LOCK_CHECK, WARNING, "there is no package-lock.json: `npm install` would pick the newest packages that fit, not the tested ones"))
    elif facts.server_name and is_our_lock(lock.decode("utf-8", "replace"), facts.server_name):
        out.append(CheckResult(LOCK_CHECK, PASSED, "the pinned lockfile"))
    else:
        out.append(CheckResult(LOCK_CHECK, WARNING, "it is not the lockfile this builder writes: it installs whatever it lists, from wherever it says. Read it, or delete it and use the pinned one"))
    return out


KNOWN_NODE_MODULES = frozenset({
    "assert", "assert/strict", "async_hooks", "buffer", "child_process", "cluster", "console", "constants", "crypto", "dgram", "diagnostics_channel", "dns", "dns/promises",
    "domain", "events", "fs", "fs/promises", "http", "http2", "https", "inspector", "module", "net", "os", "path", "path/posix", "path/win32", "perf_hooks", "process", "punycode",
    "querystring", "readline", "readline/promises", "repl", "stream", "stream/promises", "stream/web", "string_decoder", "sys", "timers", "timers/promises", "tls", "trace_events",
    "tty", "url", "util", "util/types", "v8", "vm", "wasi", "worker_threads", "zlib", "test", "sqlite",
})
