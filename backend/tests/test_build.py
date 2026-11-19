from __future__ import annotations


def calls(g, conf=None):
    return {(e.src, e.dst) for e in g.edges if e.kind == "calls" and (conf is None or e.conf == conf)}


def imports(g):
    return {(e.src, e.dst) for e in g.edges if e.kind == "imports"}


def test_python_imports_relative_absolute_and_reexports(graph):
    g = graph({
        "pkg/__init__.py": "from .core import run\n",
        "pkg/core.py": "def run():\n    return helper()\n\ndef helper():\n    return 1\n",
        "pkg/util.py": "def tool():\n    pass\n",
        "app.py": (
            "from pkg import run\nfrom pkg import util\nimport pkg.util as pu\n\n"
            "def main():\n    run()\n    util.tool()\n    pu.tool()\n"
        ),
    })
    assert ("app.py::main", "pkg/core.py::run") in calls(g, "resolved")  # through the package re-export
    assert ("app.py::main", "pkg/util.py::tool") in calls(g, "resolved")
    assert ("pkg/core.py::run", "pkg/core.py::helper") in calls(g, "resolved")
    assert {("app.py", "pkg/__init__.py"), ("app.py", "pkg/util.py"), ("pkg/__init__.py", "pkg/core.py")} <= imports(g)
    tool_edge = next(e for e in g.edges if e.dst == "pkg/util.py::tool")
    assert tool_edge.count == 2  # util.tool() and pu.tool()


def test_self_and_super_calls_follow_inheritance_across_files(graph):
    g = graph({
        "base.py": "class Base:\n    def helper(self):\n        return 1\n",
        "child.py": (
            "from base import Base\n\nclass Child(Base):\n"
            "    def go(self):\n        return self.helper()\n"
            "    def up(self):\n        return super().helper()\n"
        ),
    })
    assert ("child.py::Child.go", "base.py::Base.helper") in calls(g, "resolved")
    assert ("child.py::Child.up", "base.py::Base.helper") in calls(g, "resolved")


def test_name_matches_are_labelled_and_never_invented(graph):
    g = graph({
        "a.py": "class Svc:\n    def process(self):\n        pass\n    def get(self):\n        pass\n",
        "b.py": (
            "import os\n\nclass One:\n    def clash(self):\n        pass\n"
            "class Two:\n    def clash(self):\n        pass\n\n"
            "def use(x, d):\n    x.process()\n    x.clash()\n    d.get()\n    os.getcwd()\n"
        ),
    })
    assert ("b.py::use", "a.py::Svc.process") in calls(g, "guess")  # one method has that name: a labelled guess
    assert not any(dst.endswith("clash") for _, dst in calls(g))  # two methods share the name: no edge at all
    assert not any(dst.endswith("Svc.get") for _, dst in calls(g))  # `get` on an unknown receiver is not guessed
    assert g.call_stats["guess"] == 1 and g.call_stats["ambiguous"] == 1
    assert "clash" in g.loose_names and "process" in g.loose_names


def test_a_repo_file_named_like_a_stdlib_module_does_not_hijack_the_import(graph):
    g = graph({
        "config/logging.py": "def info():\n    pass\n",
        "app/main.py": "import logging\n\ndef run():\n    logging.info('x')\n",
    })
    assert ("app/main.py", "config/logging.py") not in imports(g)
    assert not calls(g)


def test_circular_imports_resolve_without_looping(graph):
    g = graph({
        "a.py": "from b import fb\n\ndef fa():\n    return fb()\n",
        "b.py": "from a import fa\n\ndef fb():\n    return fa()\n",
    })
    assert calls(g, "resolved") == {("a.py::fa", "b.py::fb"), ("b.py::fb", "a.py::fa")}


def test_typescript_modules_defaults_namespaces_and_star_reexports(graph):
    g = graph({
        "src/util.ts": "export function helper() { return 1 }\n",
        "src/single.ts": "export default function only() { return 1 }\n",
        "src/lib/index.ts": "export function lib() {}\n",
        "src/reexport.ts": "export * from './util';\n",
        "src/app.ts": (
            "import only from './single.js';\nimport { helper } from './util';\nimport * as L from './lib';\n"
            "export function run() { helper(); only(); L.lib(); }\n"
        ),
        "src/use.ts": "import { helper } from './reexport';\nexport function go() { helper(); }\n",
    })
    resolved = calls(g, "resolved")
    assert ("src/app.ts::run", "src/util.ts::helper") in resolved
    assert ("src/app.ts::run", "src/single.ts::only") in resolved  # default import, and `.js` mapped to `.ts`
    assert ("src/app.ts::run", "src/lib/index.ts::lib") in resolved  # namespace import of an index file
    assert ("src/use.ts::go", "src/util.ts::helper") in resolved  # through `export *`
    assert ("src/app.ts", "src/lib/index.ts") in imports(g)


def test_unresolved_relative_imports_are_recorded_but_packages_are_not(graph):
    g = graph({
        "src/a.ts": "import { x } from './missing';\nimport React from 'react';\nexport const y = () => x();\n",
        "pkg/m.py": "from .nowhere import thing\nimport requests\n",
    })
    assert g.gaps["src/a.ts"] == ["./missing"]
    assert g.gaps["pkg/m.py"] == [".nowhere"]


def test_parse_problems_are_reported_and_do_not_stop_the_build(graph):
    g = graph({"good.py": "def ok():\n    pass\n", "bad.py": "def broken(:\n"})
    assert "good.py::ok" in g.symbols
    assert g.files["bad.py"].error
    assert any("parse problems" in n for n in g.notes)


def test_tests_and_ignored_folders_are_recognised(graph):
    g = graph({
        "src/a.py": "def a():\n    pass\n",
        "tests/test_a.py": "def test_a():\n    pass\n",
        "node_modules/dep/x.js": "function x() {}\n",
        "dist/bundle.js": "function y() {}\n",
        "types/x.d.ts": "export declare function z(): void;\n",
    })
    assert set(g.files) == {"src/a.py", "tests/test_a.py"}
    assert g.files["tests/test_a.py"].is_test and not g.files["src/a.py"].is_test


def test_a_python_package_named_build_is_source_but_real_build_output_is_still_skipped(graph):
    """This project's own builder lives in `skillforge/build/`. A folder named build, dist or out is output in most
    projects, so it is skipped unless it is a Python package (an `__init__.py` directly inside)."""
    g = graph({
        "pkg/build/__init__.py": "",
        "pkg/build/pipeline.py": "def build_from_spec():\n    pass\n",
        "build/lib/pkg/__init__.py": "",  # what setuptools writes: a copy, one folder deeper
        "build/lib/pkg/old.py": "def stale():\n    pass\n",
        "dist/bundle.js": "function y() {}\n",
        "out/generated.py": "def gen():\n    pass\n",  # no __init__.py: output
        "node_modules/dep/__init__.py": "",  # never source, whatever it contains
        "src/a.py": "def a():\n    pass\n",
    })
    assert set(g.files) == {"pkg/build/__init__.py", "pkg/build/pipeline.py", "src/a.py"}
    assert "pkg/build/pipeline.py::build_from_spec" in g.symbols


def test_closures_can_call_their_siblings_and_enclosing_functions_in_python(graph):
    g = graph({
        "m.py": (
            "def outer():\n"
            "    def helper():\n        return 1\n"
            "    def first():\n        return helper()\n"  # sibling closure
            "    def second():\n        def deep():\n            return helper()\n        return deep()\n"  # two levels down
            "    return first() + second()\n"
            "class K:\n"
            "    def m(self):\n        return other()\n"
            "    def other(self):\n        return 1\n"  # a class member is not visible by bare name
            "def other():\n    return 2\n"
        ),
    })
    resolved = calls(g, "resolved")
    assert ("m.py::outer.first", "m.py::outer.helper") in resolved
    assert ("m.py::outer.second.deep", "m.py::outer.helper") in resolved
    assert ("m.py::outer.second", "m.py::outer.second.deep") in resolved
    assert ("m.py::K.m", "m.py::other") in resolved and ("m.py::K.m", "m.py::K.other") not in resolved


def test_closures_can_call_their_siblings_in_typescript(graph):
    g = graph({
        "a.ts": (
            "export function extract() {\n"
            "  const requireImport = (x: string) => x;\n"
            "  function handleCall(n: string) { return requireImport(n); }\n"
            "  return handleCall('a');\n"
            "}\n"
        ),
    })
    assert ("a.ts::extract.handleCall", "a.ts::extract.requireImport") in calls(g, "resolved")
