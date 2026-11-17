from skillforge.graph.extract_python import extract


def run(src: str):
    symbols, imports, refs, error = extract("m.py", src)
    return {s.qualname: s for s in symbols}, imports, refs, error


def test_functions_methods_classes_and_nesting():
    syms, _, _, err = run(
        "class A(Base):\n"
        "    def m(self):\n"
        "        def inner():\n"
        "            pass\n"
        "        return inner\n"
        "def top():\n"
        "    pass\n"
        "def _private():\n"
        "    pass\n"
    )
    assert err is None
    assert syms["A"].kind == "class" and syms["A"].bases == ["Base"] and syms["A"].exported
    assert syms["A.m"].kind == "method" and syms["A.m"].parent == "A" and syms["A.m"].exported
    assert syms["A.m.inner"].kind == "function" and not syms["A.m.inner"].exported
    assert syms["top"].exported and not syms["_private"].exported
    assert syms["top"].id == "m.py::top"


def test_call_kinds_are_classified():
    syms, _, _, _ = run(
        "class A(B):\n"
        "    def m(self, x):\n"
        "        foo()\n"
        "        self.bar()\n"
        "        super().baz()\n"
        "        os.path.join(x)\n"
        "        obj.run()\n"
    )
    calls = {(c.callee, c.kind, c.receiver) for c in syms["A.m"].calls}
    assert calls == {
        ("foo", "name", None),
        ("bar", "self", "self"),
        ("baz", "super", "super"),
        ("join", "attr", "os.path"),
        ("run", "attr", "obj"),
    }


def test_module_level_calls_belong_to_a_module_symbol():
    syms, _, _, _ = run("def main():\n    pass\nmain()\n")
    assert [c.callee for c in syms["<module>"].calls] == ["main"]


def test_nested_defs_own_their_calls_but_decorators_belong_to_the_enclosing_scope():
    syms, _, _, _ = run(
        "def outer():\n"
        "    @deco()\n"
        "    def inner():\n"
        "        inside()\n"
        "    return inner\n"
    )
    assert [c.callee for c in syms["outer"].calls] == ["deco"]
    assert [c.callee for c in syms["outer.inner"].calls] == ["inside"]
    assert syms["outer.inner"].decorated


def test_imports_all_forms():
    _, imports, _, _ = run(
        "import os\nimport a.b as ab\nfrom x.y import z, w as v\nfrom . import sib\nfrom ..up import q\nfrom m import *\n"
    )
    flat = [(i.module, i.level, i.names) for i in imports]
    assert ("os", 0, [("", "os")]) in flat
    assert ("a.b", 0, [("", "ab")]) in flat
    assert ("x.y", 0, [("z", "z"), ("w", "v")]) in flat
    assert ("", 1, [("sib", "sib")]) in flat
    assert ("up", 2, [("q", "q")]) in flat
    assert ("m", 0, [("*", "*")]) in flat


def test_structure_hash_ignores_names_literals_and_docstrings_but_not_logic():
    syms, _, _, _ = run(
        "def a(x, y):\n    'doc'\n    total = x + y\n    return total * 2\n"
        "def b(p, q):\n    s = p + q\n    return s * 9\n"
        "def c(p, q):\n    s = p - q\n    return s * 9\n"
    )
    assert syms["a"].shape == syms["b"].shape
    assert syms["a"].shape != syms["c"].shape
    assert syms["a"].size > 5


def test_values_used_but_not_called_are_references():
    _, _, refs, _ = run("def f():\n    pass\nx = map(f, [])\ny = obj.method\nf2 = f\ng()\n")
    assert "f" in refs and "method" in refs
    assert "g" not in refs  # a called name is not a value use


def test_syntax_error_is_reported_not_raised():
    syms, imports, refs, err = run("def broken(:\n")
    assert syms == {} and imports == [] and refs == []
    assert err and "SyntaxError" in err
