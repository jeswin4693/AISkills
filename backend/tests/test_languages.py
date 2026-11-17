"""Cross-language support. Grammars come from tree-sitter-language-pack (downloaded on first use);
a test is skipped when its grammar cannot be loaded, e.g. offline."""

from __future__ import annotations

import pytest

from skillforge.graph import languages, query
from skillforge.graph.build import build_graph


def need(*names: str) -> None:
    for name in names:
        parser, why = languages.get_parser(name)
        if parser is None:
            pytest.skip(f"no {name} grammar here: {why}")


def calls(g, conf=None):
    return {(e.src, e.dst) for e in g.edges if e.kind == "calls" and (conf is None or e.conf == conf)}


def imports(g):
    return {(e.src, e.dst) for e in g.edges if e.kind == "imports"}


# ---- the registry ------------------------------------------------------------------------------------


def test_levels_and_extensions_are_declared_honestly():
    assert [languages.level_of(n) for n in ("python", "tsx", "java", "go", "lua", "swift")] == [
        "full", "full", "standard", "standard", "basic", "basic",
    ]
    assert languages.language_of_path("a/B.java") == "java" and languages.language_of_path("x.HPP") == "cpp"
    assert languages.language_of_path("types/x.d.ts") is None and languages.language_of_path("app.min.js") is None
    assert languages.language_of_path("data.json") is None and languages.language_of_path("README.md") is None
    assert languages.info("java").scope == "directory" and languages.info("c").import_style == "relative"
    assert set(languages.EXTENSIONS.values()) >= {"java", "go", "rust", "c", "cpp", "csharp", "ruby", "php", "kotlin", "al"}


def test_every_language_in_the_table_has_a_grammar_in_the_pack():
    pack = languages._pack()
    if pack is None:
        pytest.skip("grammar pack not installed")
    missing = [n for n in set(languages.EXTENSIONS.values()) if n not in languages.BUILT_IN and n != "python"
               and n not in languages._manifest()]
    assert missing == []


# ---- standard languages: the links that matter -------------------------------------------------------


def test_java_imports_static_calls_implicit_this_and_constructors(graph):
    need("java")
    g = graph({
        "src/com/acme/Util.java": "package com.acme;\npublic class Util {\n  public static int twice(int x) { return x * 2; }\n}\n",
        "src/com/acme/App.java": (
            "package com.acme;\nimport com.acme.Util;\npublic class App {\n"
            "  public int run() { return helper() + Util.twice(2); }\n  private int helper() { return 1; }\n}\n"
        ),
        "src/com/other/Svc.java": (
            "package com.other;\nimport com.acme.App;\npublic class Svc {\n  void go() { App a = new App(); a.run(); }\n}\n"
        ),
    })
    resolved = calls(g, "resolved")
    assert ("src/com/acme/App.java::App.run", "src/com/acme/App.java::App.helper") in resolved  # implicit this
    assert ("src/com/acme/App.java::App.run", "src/com/acme/Util.java::Util.twice") in resolved  # static call via import
    assert ("src/com/other/Svc.java::Svc.go", "src/com/acme/App.java::App") in resolved  # `new App()` via import
    assert ("src/com/other/Svc.java::Svc.go", "src/com/acme/App.java::App.run") in calls(g, "guess")  # `a.run()`: type unknown
    assert {("src/com/acme/App.java", "src/com/acme/Util.java"), ("src/com/other/Svc.java", "src/com/acme/App.java")} <= imports(g)
    assert g.symbols["src/com/acme/App.java::App.run"].exported and not g.symbols["src/com/acme/App.java::App.helper"].exported


def test_go_packages_are_directories_and_receivers_call_their_own_methods(graph):
    need("go")
    g = graph({
        "main.go": 'package main\nimport u "example.com/proj/util"\nfunc Run() { helper(); u.Do() }\nfunc helper() {}\n',
        "util/util.go": "package util\nfunc Do() { inner() }\nfunc inner() {}\ntype S struct{}\nfunc (s *S) A() { s.B() }\nfunc (s *S) B() {}\n",
    })
    resolved = calls(g, "resolved")
    assert ("main.go::Run", "main.go::helper") in resolved  # same package
    assert ("main.go::Run", "util/util.go::Do") in resolved  # through the import alias `u` (a directory)
    assert ("util/util.go::Do", "util/util.go::inner") in resolved
    assert ("util/util.go::S.A", "util/util.go::S.B") in resolved  # receiver `s` is the method's own type
    assert ("main.go", "util/util.go") in imports(g)
    assert g.symbols["util/util.go::Do"].exported and not g.symbols["util/util.go::inner"].exported


def test_rust_modules_use_paths_and_self_calls(graph):
    need("rust")
    g = graph({
        "src/main.rs": "mod util;\nuse crate::util::helper;\nfn run() { helper(); util::other(); }\n",
        "src/util.rs": "pub fn helper() {}\npub fn other() {}\npub struct S;\nimpl S { pub fn m(&self) { self.n(); } pub fn n(&self) {} }\n",
    })
    resolved = calls(g, "resolved")
    assert ("src/main.rs::run", "src/util.rs::helper") in resolved  # `use crate::util::helper`
    assert ("src/main.rs::run", "src/util.rs::other") in resolved  # `util::other()` through `mod util;`
    assert ("src/util.rs::S.m", "src/util.rs::S.n") in resolved  # methods of an impl block
    assert ("src/main.rs", "src/util.rs") in imports(g)
    assert g.symbols["src/util.rs::helper"].exported and not g.symbols["src/main.rs::run"].exported


def test_c_includes_link_files_and_cross_file_calls_are_labelled_guesses(graph):
    need("c")
    g = graph({
        "util.h": "int helper(int a);\n",
        "util.c": '#include "util.h"\nint helper(int a) { return a; }\nstatic int hidden() { return 1; }\n',
        "main.c": '#include "util.h"\n#include <stdio.h>\nint main() { return helper(1); }\n',
    })
    assert {("main.c", "util.h"), ("util.c", "util.h")} <= imports(g)
    assert ("main.c::main", "util.c::helper") in calls(g, "guess")  # no import ties the name to a file: name only
    assert not any("stdio" in dst for _, dst in imports(g))  # system headers are external
    assert g.symbols["util.c::helper"].exported and not g.symbols["util.c::hidden"].exported


def test_cpp_methods_call_each_other_without_this(graph):
    need("cpp")
    g = graph({"k.cpp": "class K {\npublic:\n  void run() { step(); this->step(); }\n  void step() {}\n};\n"})
    assert ("k.cpp::K.run", "k.cpp::K.step") in calls(g, "resolved")


def test_csharp_methods_constructors_and_global_class_names(graph):
    need("csharp")
    g = graph({
        "A.cs": "namespace N {\n  public class A {\n    public void Run() { Helper(); new B().Go(); }\n    void Helper() {}\n  }\n}\n",
        "B.cs": "namespace N {\n  public class B {\n    public void Go() {}\n  }\n}\n",
    })
    assert ("A.cs::A.Run", "A.cs::A.Helper") in calls(g, "resolved")
    assert ("A.cs::A.Run", "B.cs::B") in calls(g, "guess")  # no import maps a namespace to a file: name only
    assert ("A.cs::A.Run", "B.cs::B.Go") in calls(g, "guess")


def test_ruby_requires_and_bare_method_calls(graph):
    need("ruby")
    g = graph({
        "util.rb": "def helper\n  1\nend\n",
        "app.rb": "require_relative 'util'\nclass K\n  def run\n    step\n    helper\n  end\n  def step\n  end\nend\n",
    })
    assert ("app.rb::K.run", "app.rb::K.step") in calls(g, "resolved")
    assert ("app.rb::K.run", "util.rb::helper") in calls(g, "guess")
    assert ("app.rb", "util.rb") in imports(g)


def test_php_namespaces_this_and_static_calls(graph):
    need("php")
    g = graph({
        "src/Util.php": "<?php\nnamespace App;\nclass Util {\n  public static function twice($x) { return $x * 2; }\n}\n",
        "src/Svc.php": (
            "<?php\nnamespace App;\nuse App\\Util;\nclass Svc {\n"
            "  public function go() { $this->helper(); return Util::twice(2); }\n  private function helper() {}\n}\n"
        ),
    })
    resolved = calls(g, "resolved")
    assert ("src/Svc.php::Svc.go", "src/Svc.php::Svc.helper") in resolved
    assert ("src/Svc.php::Svc.go", "src/Util.php::Util.twice") in resolved  # `use App\Util;` then Util::twice()
    assert ("src/Svc.php", "src/Util.php") in imports(g)


def test_kotlin_imports_and_implicit_this(graph):
    need("kotlin")
    g = graph({
        "a/Util.kt": "package a\nclass Util {\n  fun twice(x: Int): Int { return x * 2 }\n}\n",
        "a/App.kt": "package a\nimport a.Util\nclass App {\n  fun run() { helper(); Util().twice(2) }\n  fun helper() {}\n}\n",
    })
    assert ("a/App.kt::App.run", "a/App.kt::App.helper") in calls(g, "resolved")
    assert ("a/App.kt::App.run", "a/Util.kt::Util") in calls(g, "resolved")  # constructor via import
    assert ("a/App.kt", "a/Util.kt") in imports(g)


# ---- every other language: definitions and duplicates ------------------------------------------------


def test_basic_languages_get_definitions_and_cross_language_duplicate_detection(graph):
    need("lua", "swift")
    body = "  local out = {}\n  for i, v in ipairs(items) do\n    if v then out[#out + 1] = v end\n  end\n  return out\n"
    g = graph({
        "a.lua": f"function collect(items)\n{body}end\n",
        "b.lua": f"function gather(rows)\n{body.replace('items', 'rows')}end\n",
        "s.swift": "class Box {\n  func open() {}\n}\nfunc make() {}\n",
    })
    assert g.files["a.lua"].lang == "lua" and "a.lua::collect" in g.symbols
    assert {"s.swift::Box", "s.swift::Box.open", "s.swift::make"} <= set(g.symbols)
    groups = query.duplicates(g)["groups"]
    assert len(groups) == 1 and {m["name"] for m in groups[0]["members"]} == {"collect", "gather"}
    assert not [e for e in g.edges if e.kind == "calls"]  # basic level: no call edges are claimed


def test_stats_say_how_deeply_each_language_is_understood(graph):
    need("java", "lua")
    g = graph({"A.java": "class A {}\n", "x.lua": "function f() end\n", "m.py": "def a():\n    pass\n"})
    s = query.stats(g)
    assert s["language_levels"] == {"java": "standard", "lua": "basic", "python": "full"}


# ---- failure modes: no grammar, offline --------------------------------------------------------------


def test_a_missing_grammar_degrades_one_language_and_never_breaks_the_run(repo, monkeypatch):
    root = repo({"A.java": "class A {}\n", "m.py": "def a():\n    pass\n"})
    real = languages.get_parser
    monkeypatch.setattr(languages, "get_parser", lambda name: (None, "no network") if name == "java" else real(name))
    g = build_graph(root, use_cache=False, with_history=False)
    assert "m.py::a" in g.symbols  # Python is unaffected
    assert g.files["A.java"].error == "grammar unavailable: no network" and not g.files["A.java"].symbols
    assert any("java file(s) were counted but not parsed: no network" in n for n in g.notes)


def test_a_file_that_could_not_be_parsed_is_retried_after_the_grammar_arrives(repo, monkeypatch):
    need("java")
    root = repo({"A.java": "class A { void f() {} }\n"})
    real = languages.get_parser
    monkeypatch.setattr(languages, "get_parser", lambda name: (None, "offline") if name == "java" else real(name))
    assert not build_graph(root, with_history=False).symbols
    monkeypatch.setattr(languages, "get_parser", real)  # the grammar is available now
    g = build_graph(root, with_history=False)
    assert "A.java::A.f" in g.symbols  # the empty record was not cached, so the file was parsed again


def test_offline_mode_refuses_downloads(monkeypatch):
    pack = languages._pack()
    if pack is None:
        pytest.skip("grammar pack not installed")
    languages._parsers.pop("zig", None)
    languages._failures.pop("zig", None)
    monkeypatch.setenv("SKILLFORGE_OFFLINE", "1")
    monkeypatch.setattr(pack, "downloaded_languages", lambda: [])
    parser, why = languages.get_parser("zig")
    languages._failures.pop("zig", None)
    assert parser is None and "offline mode" in why
    assert languages.grammar_status("zig") == "unavailable offline"
