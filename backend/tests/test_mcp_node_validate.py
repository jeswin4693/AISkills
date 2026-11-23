"""The reader of a Node MCP server (`validate/mcp_node.py`, Component Factory Phase 3b). Offline: the file is parsed, never run."""

from __future__ import annotations

import json

import pytest

from skillforge.mcpnode import package_json, package_lock
from skillforge.results import FAILED, PASSED, WARNING
from skillforge.validate.mcp_node import analyze_node_server, check_server_ts, node_name_of, other_node_code

NAME = "word-tools"
HEAD = '''import { McpServer } from "@modelcontextprotocol/server";
import { StdioServerTransport } from "@modelcontextprotocol/server/stdio";
import * as z from "zod";
%IMPORTS%
const server = new McpServer({ name: "word-tools", version: "0.1.0" }, { capabilities: { tools: {} } });
server.registerTool("t", { description: "Counts words.", inputSchema: z.object({ text: z.string() }) }, async ({ text }: { text: string }) => {
%BODY%
  return { content: [{ type: "text" as const, text: String(text) }] };
});
await server.connect(new StdioServerTransport());
'''


def source(body: str = "", imports: str = "") -> str:
    return HEAD.replace("%BODY%", body).replace("%IMPORTS%", imports)


def files(src: str | None = None, **extra: str) -> dict[str, bytes]:
    out = {"server.ts": (src if src is not None else source()).encode("utf-8"), "package.json": package_json(NAME).encode(), "package-lock.json": package_lock(NAME).encode()}
    out.update({k.replace("__", "/").replace("_dot_", "."): v.encode() for k, v in extra.items()})
    return out


def by_name(checks):
    return {c.name: c for c in checks}


def facts(body: str = "", imports: str = ""):
    return analyze_node_server(source(body, imports))


FS = 'import * as fs from "node:fs";'
CP = 'import * as cp from "node:child_process";'


# what each spelling is read as: (body, imports, capabilities it must have, dynamic constructs it must report)
HOSTILE = [
    ("cp.execSync('ls');", CP, {"run_commands"}, False),
    ("e('ls');", 'import { exec as e } from "child_process";', {"run_commands"}, False),
    ("const { execSync } = cp; execSync('ls');", 'import cp from "child_process";', {"run_commands"}, False),
    ("const run = cp.spawn; run('ls');", CP, {"run_commands"}, False),
    ("fs.writeFileSync('a', 'b');", FS, {"write_files"}, False),
    ("const w = fs.writeFileSync; w('a', 'b');", FS, {"write_files"}, False),
    ("const { rmSync } = fs; rmSync('a');", FS, {"write_files"}, False),
    ("await fsp.writeFile('a', 'b');", 'import * as fsp from "node:fs/promises";', {"write_files"}, False),
    ("await fs.promises.unlink('a');", FS, {"write_files"}, False),
    ("fs.openSync('a', 'w');", FS, {"write_files", "read_files"}, False),
    ("fs.openSync('a', flags);", FS, {"write_files", "read_files"}, False),
    ("fs.openSync('a', 'r');", FS, {"read_files"}, False),
    ("fs.readFileSync('a');", FS, {"read_files"}, False),
    ("await fetch('http://x');", "", {"network"}, False),
    ("await globalThis.fetch('http://x');", "", {"network"}, False),
    ("const h = await import('node:http');", "", {"network"}, True),
    ("net.connect(1);", 'import * as net from "node:net";', {"network"}, False),
    ("new WebSocket('ws://x');", "", {"network"}, False),
    ("new Worker('x');", "", {"run_commands"}, False),
    ("process.binding('spawn_sync');", "", {"run_commands"}, False),
    ("eval(text);", "", set(), True),
    ("(0, eval)(text);", "", set(), True),
    ("new Function('return 1')();", "", set(), True),
    ("[].constructor.constructor('return 1')();", "", set(), True),
    ("[]['constructor']['constructor']('return 1')();", "", set(), True),
    ("({}).__proto__.x = 1;", "", set(), True),
    ("await import('node:child_process');", "", {"run_commands"}, True),
    ("await import(text);", "", set(), True),
    ("require('fs');", "", set(), True),
    ("globalThis[text]();", "", set(), True),
    ("fs[text]();", FS, set(), True),
    ("use(fs);", FS, set(), True),
    ("vm.runInNewContext(text);", 'import * as vm from "node:vm";', set(), True),
    ("setTimeout('x', 1);", "", set(), True),
    ("new WebAssembly.Module(x);", "", set(), True),
]


@pytest.mark.parametrize(("body", "imports", "caps", "dynamic"), HOSTILE)
def test_every_spelling_is_read_as_what_it_is(body, imports, caps, dynamic):
    found = facts(body, imports)
    assert caps <= found.capabilities, (found.capabilities, found.dynamic)
    assert bool(found.dynamic) == dynamic or (dynamic and found.dynamic), found.dynamic


def test_a_plain_server_does_nothing_dangerous():
    found = facts("return;")
    assert found.server_name == NAME and found.has_server and found.connects and [t.name for t in found.tools] == ["t"]
    assert not found.capabilities and not found.dynamic and not found.undefined and not found.secrets and not found.env_names


@pytest.mark.parametrize(("body", "names", "dynamic"), [
    ("const k = process.env.KEY;", {"KEY"}, False),
    ("const k = process.env['KEY'];", {"KEY"}, False),
    ("const { A, B: b } = process.env;", {"A", "B"}, False),
    ("const k = globalThis.process.env.KEY;", {"KEY"}, False),
    ("const { env } = process; const k = env.KEY;", {"KEY"}, False),
    ("const { A, ...rest } = process.env;", {"A"}, True),
    ("const n = 'K'; const k = process.env[n];", {"K"}, False),  # a constant is a plain name
    ("const k = process.env[text];", set(), True),
    ("const e = process.env; use(e);", set(), True),
    ("Object.keys(process.env);", set(), True),
    ("const all = { ...process.env };", set(), True),
])
def test_environment_variables_by_name_or_not(body, names, dynamic):
    found = facts(body)
    assert found.env_names == names
    assert found.env_dynamic is dynamic


def test_reading_an_environment_variable_by_a_computed_name_warns_but_is_not_called_building_code():
    out = by_name(check_server_ts(files(source("const k = process.env[text];")), NAME))
    assert out["environment variables are read by a plain name only"].status == WARNING
    assert out["no commands, code built from text or native code"].status == PASSED


def test_a_key_written_in_the_code_fails_even_in_pieces_and_is_never_repeated():
    key = "sk-" + "a" * 30
    for body in (f"const k = '{key}';", "const k = 'sk-' + 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';", "const k = `sk-` + \"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\";"):
        row = by_name(check_server_ts(files(source(body)), NAME))["no key or token written into the code"]
        assert row.status == FAILED
        assert "aaaaaaaaaa" not in row.detail


def test_names_used_but_never_defined_warn_and_imported_names_are_not_undefined():
    assert facts("return nothing(text);").undefined == {"nothing"}
    assert not facts("e('x');", 'import { exec as e } from "child_process";').undefined
    assert "require" in facts("require('x');").undefined  # known to JavaScript, but not defined in an ES module
    assert "__dirname" in facts("use(__dirname);").undefined


def test_writing_to_the_protocol_stream_is_found():
    assert facts("console.log(text);").stdout
    assert not facts("console.error(text);").stdout
    assert facts("process.stdout.write(text);").stdout


def test_a_tool_registered_on_something_else_is_reported():
    found = facts("other.registerTool('x', {}, () => 1);")
    assert any("not the server variable" in d for d in found.dynamic)


def test_syntax_that_node_cannot_strip_is_found():
    for body_imports, label in (("enum E { A }", "enum"), ("namespace N { export const x = 1 }", "namespace"), ("class C { constructor(private x: number) {} }", "modifier")):
        found = analyze_node_server(source("", body_imports))
        assert found.non_erasable, label
    row = by_name(check_server_ts(files(source("", "enum E { A }")), NAME))["only syntax that `node server.ts` can run"]
    assert row.status == FAILED


def test_a_file_that_does_not_parse_is_a_failure_not_a_pass():
    out = check_server_ts(files("const = ;"), NAME)
    assert len(out) == 1 and out[0].status == FAILED and "syntax error" in out[0].detail


def test_a_file_that_is_not_utf8_or_missing_fails():
    assert check_server_ts({"server.ts": b"\xff\xfe\x00"}, NAME)[0].status == FAILED
    assert check_server_ts({"package.json": b"{}"}, NAME)[0].status == FAILED


def test_a_deeply_nested_file_does_not_crash_the_reader():
    deep = "(" * 3000 + "1" + ")" * 3000
    try:
        out = check_server_ts(files(source(f"const x = {deep};")), NAME)
    except RecursionError:  # pragma: no cover
        pytest.fail("a nested file crashed the reader")
    assert out


def test_a_good_server_passes_every_check():
    out = check_server_ts(files(), NAME)
    assert all(c.status == PASSED for c in out), [(c.name, c.detail) for c in out if c.status != PASSED]


def test_structure_is_required():
    no_tool = source().split("server.registerTool")[0] + "await server.connect(new StdioServerTransport());\n"
    assert "registers no tool" in check_server_ts(files(no_tool), NAME)[0].detail
    no_connect = source().replace("await server.connect(new StdioServerTransport());", "")
    assert "never connects" in check_server_ts(files(no_connect), NAME)[0].detail
    no_server = "const x = 1;\n"
    assert "never creates an McpServer" in check_server_ts(files(no_server), NAME)[0].detail
    two = source() + 'const second = new McpServer({ name: "other", version: "1" }, {});\n'
    assert "more than one" in check_server_ts(files(two), NAME)[0].detail


def test_the_folder_must_match_the_server_name_and_the_name_must_be_safe():
    assert by_name(check_server_ts(files(), "other-name"))["folder name matches the server name"].status == FAILED
    assert node_name_of(files()) == NAME
    assert node_name_of(files(source().replace('"word-tools"', '"../etc"'))) is None
    assert node_name_of({"server.ts": b"nope("}) is None


def test_a_package_json_with_scripts_fails_because_npm_runs_them_when_it_installs():
    bad = json.loads(package_json(NAME))
    bad["scripts"] = {"postinstall": "node -e 1"}
    row = by_name(check_server_ts({**files(), "package.json": json.dumps(bad).encode()}, NAME))["package.json runs nothing when installed and names only the pinned packages"]
    assert row.status == FAILED and "postinstall" in row.detail


def test_a_package_json_that_is_not_a_module_or_is_missing_fails():
    row_name = "package.json runs nothing when installed and names only the pinned packages"
    bad = json.loads(package_json(NAME))
    del bad["type"]
    assert by_name(check_server_ts({**files(), "package.json": json.dumps(bad).encode()}, NAME))[row_name].status == FAILED
    no_package = {k: v for k, v in files().items() if k != "package.json"}
    assert by_name(check_server_ts(no_package, NAME))[row_name].status == FAILED
    assert by_name(check_server_ts({**files(), "package.json": b"not json"}, NAME))[row_name].status == FAILED


def test_other_packages_and_overrides_warn():
    row_name = "package.json runs nothing when installed and names only the pinned packages"
    more = json.loads(package_json(NAME))
    more["dependencies"]["left-pad"] = "1.3.0"
    more["overrides"] = {"zod": "3.0.0"}
    row = by_name(check_server_ts({**files(), "package.json": json.dumps(more).encode()}, NAME))[row_name]
    assert row.status == WARNING and "left-pad" in row.detail and "overrides" in row.detail


def test_a_lockfile_that_is_not_ours_warns_and_a_missing_one_warns():
    row_name = "package-lock.json is the pinned lockfile"
    assert by_name(check_server_ts(files(), NAME))[row_name].status == PASSED
    other = json.loads(package_lock(NAME))
    other["packages"]["node_modules/zod"]["resolved"] = "https://evil.example/zod.tgz"
    assert by_name(check_server_ts({**files(), "package-lock.json": json.dumps(other).encode()}, NAME))[row_name].status == WARNING
    assert by_name(check_server_ts({k: v for k, v in files().items() if k != "package-lock.json"}, NAME))[row_name].status == WARNING


@pytest.mark.parametrize("path", ["helper.js", "lib/x.mjs", "other.ts", "x.cjs", "native.node", "run.sh", "node_modules/zod/index.js", ".npmrc", "scripts/x.txt", "bin/x"])
def test_any_other_code_or_npm_config_beside_the_server_fails(path):
    all_files = {**files(), path: b"x"}
    assert other_node_code(all_files) == [path]
    assert by_name(check_server_ts(all_files, NAME))["server.ts is the only code in the folder"].status == FAILED


def test_other_files_are_fine():
    assert other_node_code({**files(), "README.md": b"x", "spec.json": b"{}", "tests/cases.json": b"[]"}) == []


def test_third_party_imports_warn_and_node_modules_and_the_sdk_do_not():
    assert by_name(check_server_ts(files(source("", 'import _ from "lodash";')), NAME))["only Node's own modules, the MCP SDK and zod are imported"].status == WARNING
    assert by_name(check_server_ts(files(source("", 'import { createHash } from "node:crypto";')), NAME))["only Node's own modules, the MCP SDK and zod are imported"].status == PASSED
    assert by_name(check_server_ts(files(source("", 'import x from "./helper.js";')), NAME))["only Node's own modules, the MCP SDK and zod are imported"].status == WARNING


def test_what_a_server_can_do_is_reported_as_warnings_and_failures():
    out = by_name(check_server_ts(files(source("await fetch(text); fs.writeFileSync('a', 'b'); cp.execSync('ls');", FS + CP)), NAME))
    assert out["no use of the network (found by syntax)"].status == WARNING
    assert out["no writing or deleting of files (found by syntax)"].status == WARNING
    assert out["no commands, code built from text or native code"].status == FAILED


def test_a_tool_without_a_description_warns():
    bare = source().replace('description: "Counts words.", ', "")
    assert by_name(check_server_ts(files(bare), NAME))["every tool has a description"].status == WARNING


BS = chr(92)  # a backslash


@pytest.mark.parametrize(("body", "imports", "caps", "dynamic"), [
    (BS + "u0065val(text);", "", set(), True),
    (BS + "u{65}val(text);", "", set(), True),
    ("[]." + BS + "u0063onstructor.constructor('x')();", "", set(), True),
    ("cp." + BS + "u0065xecSync('ls');", CP, {"run_commands"}, False),
    (BS + "u0063p.execSync('ls');", CP, {"run_commands"}, False),
])
def test_a_name_written_with_unicode_escapes_is_read_as_the_name_it_means(body, imports, caps, dynamic):
    found = facts(body, imports)
    assert caps <= found.capabilities and bool(found.dynamic) == dynamic, (found.capabilities, found.dynamic)


def test_an_environment_variable_read_through_an_escaped_name_is_still_found():
    assert facts("const k = process." + BS + "u0065nv.KEY;").env_names == {"KEY"}


@pytest.mark.parametrize("path", ["PACKAGE.JSON", "Package-Lock.json", "sub/package.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock", ".NPMRC"])
def test_another_spelling_of_a_checked_file_or_another_lockfile_is_other_code(path):
    assert other_node_code({**files(), path: b"{}"}) == [path]


def test_the_checked_files_themselves_are_not_other_code():
    assert other_node_code(files()) == []


# ---- found by the first independent review: destructuring reaches `constructor` as well as `.constructor` does -----------------------------------

DESTRUCTURING_LITERAL = [
    "const { constructor: A } = [];",
    "const { constructor } = [];",
    "const { 'constructor': A } = [];",
    "const { [`constructor`]: A } = [];",
    "function f({ constructor: A }) { return A; } f([]);",
    "let A; ({ constructor: A } = []);",
    "for (const { constructor: A } of [[]]) { use(A); }",
    "const { __proto__: P } = [];",
    "const { constructor: { constructor: F } } = [];",
    "const [{ constructor: A }] = [[]];",
    "const k = 'con' + 'structor'; const { [k]: A } = [];",  # a constant built of literals is the name it spells
]
DESTRUCTURING_COMPUTED = [
    "const k = ['con', 'structor'].join(''); const { [k]: A } = [];",
    "const k = text; const { [k]: A } = [];",
]


@pytest.mark.parametrize("body", DESTRUCTURING_LITERAL)
def test_a_destructuring_key_that_reaches_the_internals_is_read_as_the_property_it_is(body):
    assert facts(body).dynamic, body


@pytest.mark.parametrize("body", DESTRUCTURING_COMPUTED)
def test_a_destructuring_key_chosen_by_a_computed_name_is_noticed(body):
    assert facts(body).computed, body


@pytest.mark.parametrize("body", [
    "const { length } = text;", "const { a, b } = { a: 1, b: 2 };", "const { 0: first } = [1];", "const [x, y] = [1, 2];", "const { ...rest } = { a: 1 };",
    "function f({ text: t }) { return t; } f({ text });",
])
def test_an_ordinary_destructuring_is_not_flagged(body):
    found = facts(body)
    assert not found.dynamic and not found.computed, (body, found.dynamic)


@pytest.mark.parametrize("name", ["sqlite"])
def test_a_module_that_node_s_permission_model_does_not_cover_counts_as_writing_files(name):
    """node:sqlite creates and writes a database file even under `node --permission` with no write grant (found by a real run in the container)."""
    found = facts("return;", f'import {{ DatabaseSync }} from "node:{name}";')
    assert "write_files" in found.capabilities


def test_getting_a_builtin_module_by_name_is_code_loaded_while_running():
    assert facts("process.getBuiltinModule('node:fs');").dynamic
