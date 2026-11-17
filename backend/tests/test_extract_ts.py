from skillforge.graph.extract_ts import extract


def run(src: str, lang: str = "typescript"):
    symbols, imports, refs, error = extract("m.ts", src.encode(), lang)
    return {s.qualname: s for s in symbols}, imports, refs, error


def test_functions_classes_methods_and_arrow_consts():
    syms, _, _, err = run(
        "export function add(a: number, b: number) { return helper(a) + b }\n"
        "const mul = (a: number) => a * 2;\n"
        "export class K extends Base {\n"
        "  run() { this.step(); }\n"
        "  private step() {}\n"
        "}\n"
        "function hidden() {}\n"
    )
    assert err is None
    assert syms["add"].kind == "function" and syms["add"].exported
    assert syms["mul"].kind == "function" and not syms["mul"].exported
    assert syms["K"].kind == "class" and syms["K"].bases == ["Base"] and syms["K"].exported
    assert syms["K.run"].kind == "method" and syms["K.run"].exported and syms["K.run"].parent == "K"
    assert syms["K.step"].kind == "method" and not syms["K.step"].exported  # private
    assert not syms["hidden"].exported


def test_export_list_marks_names_exported():
    syms, _, _, _ = run("function a() {}\nfunction b() {}\nexport { a };\n")
    assert syms["a"].exported and not syms["b"].exported


def test_call_kinds():
    syms, _, _, _ = run(
        "class K extends B {\n"
        "  m() { foo(); this.bar(); super.baz(); fs.readFile(); new Thing(); a?.b.c(); }\n"
        "}\n"
    )
    calls = {(c.callee, c.kind, c.receiver) for c in syms["K.m"].calls}
    assert ("foo", "name", None) in calls
    assert ("bar", "self", "this") in calls
    assert ("baz", "super", "super") in calls
    assert ("readFile", "attr", "fs") in calls
    assert ("Thing", "name", None) in calls
    assert any(c[0] == "c" and c[1] == "attr" for c in calls)


def test_import_forms():
    _, imports, _, _ = run(
        "import def, { a, b as c } from './x';\n"
        "import * as ns from './y';\n"
        "import './side';\n"
        "export * from './z';\n"
        "export { q as r } from './w';\n"
        "const m = require('./m');\n"
        "const { p, o: l } = require('./n');\n"
        "const lazy = () => import('./lazy');\n"
    )
    by_module = {i.module: i.names for i in imports}
    assert by_module["./x"] == [("default", "def"), ("a", "a"), ("b", "c")]
    assert by_module["./y"] == [("", "ns")]
    assert by_module["./side"] == []
    assert by_module["./z"] == [("*", "*")]
    assert by_module["./w"] == [("q", "r")]
    assert by_module["./m"] == [("", "m")]
    assert by_module["./n"] == [("p", "p"), ("o", "l")]
    assert by_module["./lazy"] == []


def test_arrow_function_class_field_is_a_method():
    syms, _, _, _ = run("export class K { handler = () => { this.go(); }; go() {} }")
    assert syms["K.handler"].kind == "method"
    assert [c.callee for c in syms["K.handler"].calls] == ["go"]


def test_structure_hash_ignores_names_but_not_operators():
    syms, _, _, _ = run(
        "function a(x: number, y: number) { const t = x + y; return t * 2; }\n"
        "function b(p: number, q: number) { const s = p + q; return s * 9; }\n"
        "function c(p: number, q: number) { const s = p - q; return s * 9; }\n"
    )
    assert syms["a"].shape == syms["b"].shape
    assert syms["a"].shape != syms["c"].shape


def test_jsx_component_use_counts_as_a_call():
    syms, _, _, _ = run(
        "function Button() { return <b/>; }\nfunction Page() { return <div><Button /></div>; }\n", "tsx"
    )
    assert ("Button", "name") in {(c.callee, c.kind) for c in syms["Page"].calls}


def test_references_exclude_declarations_and_call_targets():
    _, _, refs, _ = run("function used() {}\nfunction unused() {}\nconst x = [1].map(used);\nunused2();\n")
    assert "used" in refs
    assert "unused" not in refs and "unused2" not in refs


def test_syntax_errors_still_return_a_partial_result():
    syms, _, _, err = run("function ok() {}\nfunction broken( {\n")
    assert "ok" in syms
    assert err and "syntax" in err
