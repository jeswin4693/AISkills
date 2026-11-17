from __future__ import annotations

import pytest

from skillforge.graph import query

APP = {
    "svc.py": (
        "HANDLERS = [callback]\n\n"
        "def callback():\n    pass\n\n"
        "def parse(raw):\n    return clean(raw)\n\n"
        "def clean(raw):\n    return raw.strip()\n\n"
        "def unused_helper():\n    return 42\n\n"
        "def _private_unused():\n    return 7\n"
    ),
    "api.py": "from svc import parse\n\ndef handler(req):\n    return parse(req)\n\ndef other(req):\n    return parse(req)\n",
    "tests/test_api.py": "from api import handler\n\ndef test_handler():\n    handler(1)\n",
    "main.py": "from api import handler\n\ndef main():\n    handler(1)\n\nif __name__ == '__main__':\n    main()\n",
}


@pytest.fixture
def g(graph):
    return graph(APP)


def names(rows):
    return {r["name"] for r in rows}


def test_callers_and_callees_with_depth(g):
    assert names(query.callers(g, "parse")["results"]) == {"handler", "other"}
    deep = names(query.callers(g, "parse", depth=2)["results"])
    assert {"handler", "other", "main", "test_handler"} <= deep
    assert names(query.callees(g, "handler")["results"]) == {"parse"}
    assert names(query.callees(g, "handler", depth=2)["results"]) == {"parse", "clean"}


def test_ambiguous_names_need_a_file_qualifier(graph):
    g = graph({
        "a.py": "def run():\n    pass\n",
        "b.py": "def run():\n    pass\n",
        "c.py": "from a import run\n\ndef go():\n    run()\n",
    })
    with pytest.raises(query.QueryError, match="ambiguous"):
        query.callers(g, "run")
    assert names(query.callers(g, "a.py::run")["results"]) == {"go"}
    with pytest.raises(query.QueryError, match="Nothing matches"):
        query.callers(g, "does_not_exist")


def test_impact_of_a_file_counts_only_proven_dependents(g):
    r = query.impact(g, "svc.py")
    by_path = {d["path"]: d for d in r["dependents"]}
    assert by_path["api.py"]["depth"] == 1
    assert by_path["main.py"]["depth"] == 2
    assert by_path["tests/test_api.py"]["test"]
    assert r["tests_tied"] == ["tests/test_api.py"]
    assert r["risk"]["factors"]["non_test_dependents"] == 2
    assert r["risk"]["level"] == "low"


def test_impact_of_a_function_follows_callers_across_files(g):
    r = query.impact(g, "clean")
    assert {d["path"] for d in r["dependents"]} == {"api.py", "main.py", "tests/test_api.py"}


def test_impact_without_tests_raises_the_risk(graph):
    g = graph({"core.py": "def core():\n    pass\n", "user.py": "from core import core\n\ndef f():\n    core()\n"})
    r = query.impact(g, "core.py")
    assert r["tests_tied"] == [] and r["risk"]["factors"]["no_test_tied"]
    assert r["risk"]["score"] == 1 + 4


def test_path_between_functions_and_between_files(g):
    p = query.find_path(g, "main", "clean")
    assert p["found"] and p["hops"] == 3
    assert [n["name"] for n in p["path"]] == ["main", "handler", "parse", "clean"]
    assert not query.find_path(g, "clean", "main")["found"]
    fp = query.find_path(g, "main.py", "svc.py")
    assert fp["found"] and fp["kind"] == "imports" and fp["hops"] == 2


def test_hotspots_rank_by_distinct_callers(g):
    top = query.hotspots(g)["core_symbols"]
    assert top[0]["name"] == "parse" and top[0]["fan_in"] == 2


def test_dead_code_candidates_are_conservative(graph):
    g = graph({
        **APP,
        "dyn.py": (
            "class A:\n    def run(self):\n        pass\nclass B:\n    def run(self):\n        pass\n"
            "def go(thing):\n    thing.run()\n"
            "import functools\n@functools.cache\ndef cached():\n    pass\n"
        ),
    })
    dead = query.dead_candidates(g)
    internal = {r["name"] for r in dead["internal"]}
    exported = {r["name"] for r in dead["exported"]}
    assert "_private_unused" in internal
    assert {"unused_helper", "other", "go"} <= exported
    flagged = internal | exported
    assert "callback" not in flagged  # used as a value
    assert "clean" not in flagged and "parse" not in flagged  # called
    assert "main" not in flagged  # entry point name
    assert "test_handler" not in flagged  # tests are never candidates
    assert "A.run" not in flagged and "B.run" not in flagged  # `thing.run()` may reach either
    assert "cached" not in flagged  # decorated: a framework may call it


DUP_A = "def normalize_a(items):\n    out = []\n    for item in items:\n        if item:\n            out.append(item.strip().lower())\n    return out\n"
DUP_B = "def tidy(rows):\n    res = []\n    for row in rows:\n        if row:\n            res.append(row.strip().lower())\n    return res\n"
DIFFERENT = (
    "def different(rows):\n    res = []\n    for row in rows:\n        if row:\n            res.append(row.strip().lower())\n"
    "    res.sort()\n    return res\n"
)


def test_duplicates_ignore_names_but_not_structure(graph):
    g = graph({"a.py": DUP_A, "b.py": DUP_B, "c.py": DIFFERENT})
    groups = query.duplicates(g)["groups"]
    assert len(groups) == 1
    grp = groups[0]
    assert grp["copies"] == 2 and grp["cross_file"]
    assert names(grp["members"]) == {"normalize_a", "tidy"}


def test_duplicates_skip_tiny_dunder_and_test_code_by_default(graph):
    g = graph({
        "a.py": "def f(x):\n    return x\n",
        "b.py": "def g(y):\n    return y\n",
        "c.py": "class A:\n" + "".join(f"    def __{n}__(self):\n        return self.v + 1\n" for n in ("add", "sub")),
        "tests/test_a.py": DUP_A,
        "tests/test_b.py": DUP_B,
    })
    assert query.duplicates(g)["groups"] == []  # too small / dunder / tests only
    assert len(query.duplicates(g, include_tests=True)["groups"]) == 1


def test_duplicates_work_for_typescript_too(graph):
    body = (
        "{\n  const out = [];\n  for (const i of items) {\n    if (i) {\n      out.push(i.trim());\n    }\n  }\n"
        "  return out;\n}"
    )
    g = graph({
        "a.ts": f"export function one(items: string[]) {body}\n",
        "b.ts": f"export function two(items: string[]) {body}\n",
    })
    groups = query.duplicates(g)["groups"]
    assert len(groups) == 1 and names(groups[0]["members"]) == {"one", "two"}


def test_search_and_stats(g):
    assert query.search_symbols(g, "pars")[0]["name"] == "parse"
    s = query.stats(g)
    assert s["files"] == 4 and s["test_files"] == 1 and s["languages"] == {"python": 4}
    assert s["commits_read"] is None


def test_names_on_the_builtin_list_still_count_as_possible_uses(graph):
    g = graph({
        "heap.py": (
            "class Heap:\n    def push(self, x):\n        pass\n    def pop(self):\n        pass\n\n"
            "def use():\n    h = Heap()\n    h.push(1)\n    h.pop()\n"
        ),
    })
    dead = query.dead_candidates(g)
    flagged = {r["name"] for r in dead["internal"] + dead["exported"]}
    assert "Heap.push" not in flagged and "Heap.pop" not in flagged  # `h.push()` may be ours
    assert not any(e.dst.endswith("Heap.push") for e in g.edges)  # but it is never turned into an edge


def test_one_line_helpers_are_not_reported_as_duplicates(graph):
    expr = " + ".join(f"x * {n}" for n in range(2, 12))
    g = graph({
        "a.ts": f"export const a = (x: number) => {expr};\n",
        "b.ts": f"export const b = (x: number) => {expr};\n",
    })
    assert query.duplicates(g)["groups"] == []
    assert len(query.duplicates(g, min_lines=1)["groups"]) == 1
