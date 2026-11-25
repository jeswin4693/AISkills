"""Slice Z: the architecture map. Folders become boxes, proven imports between them become arrows. Graphs are built by hand here so a
guess link, a test file that imports, a language whose imports are not read and a hundred folders are exact, not hoped for."""

from __future__ import annotations

from skillforge.graph import languages
from skillforge.graph.architecture import MAX_BOXES, MAX_FILES_LISTED, MAX_FUNCTIONS_LISTED, architecture
from skillforge.graph.model import Edge, FileRecord, RepoGraph, Symbol

ONE_PLACE = "Everything sits in one place, so the map is a single box."


def mini(files, edges=(), tests=(), lines=None, funcs=()):
    """A RepoGraph made by hand. files: path -> language. edges: (src, dst) or (src, dst, conf) import edges between files.
    tests: paths that are test files. lines: path -> line count (10 otherwise). funcs: (file, name, size) functions."""
    g = RepoGraph(root="")
    for path, lang in files.items():
        n = (lines or {}).get(path, 10)
        g.files[path] = FileRecord(path=path, lang=lang, lines=n, size=n * 20, mtime_ns=0, is_test=path in tests)
    for file, name, size in funcs:
        sym = Symbol(id=f"{file}::{name}", kind="function", name=name, qualname=name, file=file, line=1, end_line=size, size=size)
        g.symbols[sym.id] = sym
        g.files[file].symbols.append(sym)
    for edge in edges:
        src, dst, conf = (*edge, "resolved")[:3]
        g.edges.append(Edge(src=src, dst=dst, kind="imports", conf=conf))
    return g


def py(*paths):
    return {p: "python" for p in paths}


def by_label(res):
    return {m["label"]: m for m in res["modules"]}


def drawn(res):
    """The arrows as (from label, to label, count), in the order the answer gives them."""
    names = {m["id"]: m["label"] for m in res["modules"]}
    return [(names[a["from"]], names[a["to"]], a["count"]) for a in res["arrows"]]


# ---- boxes and arrows ----------------------------------------------------------------------------------------


def test_folders_become_boxes_and_proven_imports_become_arrows():
    res = architecture(mini(py("web/app.py", "api/routes.py", "pricing/core.py"), [("web/app.py", "api/routes.py"), ("api/routes.py", "pricing/core.py")]))
    assert sorted(by_label(res)) == ["api", "pricing", "web"]
    assert drawn(res) == [("api", "pricing", 1), ("web", "api", 1)]
    cols = {label: m["column"] for label, m in by_label(res).items()}
    assert cols == {"web": 0, "api": 1, "pricing": 2} and res["columns"] == 3


def test_a_column_is_the_longest_chain_of_arrows():
    res = architecture(mini(py("a/x.py", "b/x.py", "c/x.py"), [("a/x.py", "b/x.py"), ("b/x.py", "c/x.py"), ("a/x.py", "c/x.py")]))
    assert {label: m["column"] for label, m in by_label(res).items()} == {"a": 0, "b": 1, "c": 2}


def test_arrow_count_is_distinct_importing_file_pairs():
    files = py("a/x.py", "a/y.py", "b/z.py")
    res = architecture(mini(files, [("a/x.py", "b/z.py"), ("a/y.py", "b/z.py"), ("a/x.py", "b/z.py")]))
    assert drawn(res) == [("a", "b", 2)]


def test_imports_inside_a_folder_are_not_arrows():
    res = architecture(mini(py("a/x.py", "a/y.py", "b/z.py"), [("a/x.py", "a/y.py")]))
    assert res["arrows"] == [] and res["cycles"] == []


def test_a_flat_repository_is_one_root_box():
    res = architecture(mini(py("a.py", "b.py"), [("a.py", "b.py")]))
    assert len(res["modules"]) == 1 and res["arrows"] == [] and res["base"] == ""
    only = res["modules"][0]
    assert only["kind"] == "root" and only["label"] == "(root)" and only["files"] == 2
    assert ONE_PLACE in res["notes"]


def test_a_common_folder_is_stripped_and_reported():
    res = architecture(mini(py("src/api/x.py", "src/db/y.py")))
    assert res["base"] == "src" and sorted(by_label(res)) == ["api", "db"]
    res = architecture(mini(py("src/api/x.py", "src/db/y.py", "setup.py")))
    assert res["base"] == "" and sorted(by_label(res)) == ["(root)", "src"]


def test_each_box_says_what_is_in_it():
    g = mini({"a/x.py": "python", "a/y.ts": "typescript", "a/test_x.py": "python"}, tests=("a/test_x.py",), lines={"a/x.py": 30, "a/y.ts": 5, "a/test_x.py": 15},
             funcs=[("a/x.py", "f", 4), ("a/y.ts", "g", 6)])
    a = architecture(g)["modules"][0]
    assert (a["files"], a["lines"], a["test_files"], a["symbols"]) == (3, 50, 1, 2)
    assert a["languages"] == {"python": 2, "typescript": 1} and a["tests_only"] is False and a["measured"] is True


# ---- what is left out, said out loud ---------------------------------------------------------------------------


def test_guess_imports_are_never_drawn_and_are_counted():
    res = architecture(mini(py("a/x.py", "b/y.py"), [("a/x.py", "b/y.py", "guess")]))
    assert res["arrows"] == [] and res["left_out"] == {"guess": 1, "from_tests": 0}


def test_imports_from_tests_are_not_drawn_and_are_counted():
    res = architecture(mini(py("src/a.py", "tests/test_a.py"), [("tests/test_a.py", "src/a.py")], tests=("tests/test_a.py",)))
    boxes = by_label(res)
    assert res["arrows"] == [] and res["left_out"] == {"guess": 0, "from_tests": 1}
    assert boxes["tests"]["tests_only"] is True and boxes["tests"]["test_files"] == 1 and boxes["src"]["tests_only"] is False


def test_unmeasured_languages_are_said_not_drawn_as_independent():
    assert languages.level_of("swift") == "basic"  # the assumption this test rests on
    res = architecture(mini({"s/a.swift": "swift", "p/b.py": "python"}))
    boxes = by_label(res)
    assert boxes["s"]["measured"] is False and boxes["p"]["measured"] is True and res["measured"] is True
    assert res["language_levels"] == {"python": "full", "swift": "basic"}
    only = architecture(mini({"s/a.swift": "swift", "t/b.swift": "swift"}))
    assert only["measured"] is False and only["arrows"] == [] and any("not measured" in n for n in only["notes"])


# ---- cycles -------------------------------------------------------------------------------------------------------


def test_a_cycle_through_three_folders_is_one_group():
    res = architecture(mini(py("a/x.py", "b/x.py", "c/x.py"), [("a/x.py", "b/x.py"), ("b/x.py", "c/x.py"), ("c/x.py", "a/x.py")]))
    ids = {m["label"]: m["id"] for m in res["modules"]}
    assert res["cycles"] == [sorted(ids.values())]
    assert {m["column"] for m in res["modules"]} == {0}


def test_a_plain_chain_has_no_cycle():
    res = architecture(mini(py("a/x.py", "b/x.py", "c/x.py"), [("a/x.py", "b/x.py"), ("b/x.py", "c/x.py")]))
    assert res["cycles"] == []


def test_a_cycle_shares_a_column_and_what_imports_it_sits_to_its_left():
    res = architecture(mini(py("a/x.py", "b/x.py", "x/x.py"), [("a/x.py", "b/x.py"), ("b/x.py", "a/x.py"), ("x/x.py", "a/x.py")]))
    cols = {label: m["column"] for label, m in by_label(res).items()}
    assert cols == {"x": 0, "a": 1, "b": 1} and len(res["cycles"]) == 1


# ---- size limits and names ------------------------------------------------------------------------------------


def test_many_folders_fold_into_other():
    files = {}
    for i in range(20):
        for j in range(i + 1):
            files[f"f{i:02d}/m{j}.py"] = "python"
    res = architecture(mini(files, [("f19/m0.py", "f00/m0.py"), ("f01/m0.py", "f02/m0.py")]))
    assert MAX_BOXES == 14 and len(res["modules"]) == 14
    other = [m for m in res["modules"] if m["kind"] == "other"]
    assert len(other) == 1
    assert other[0]["members"] == [f"f{i:02d}" for i in range(7)] and other[0]["files"] == sum(range(1, 8))
    assert [(a["from"], a["to"]) for a in res["arrows"]] == [(by_label(res)["f19"]["id"], other[0]["id"])]  # f01 -> f02 is inside "other": dropped


def test_a_real_folder_named_like_a_synthetic_box_does_not_collide():
    res = architecture(mini(py("(root)/a.py", "(other)/b.py", "top.py")))
    assert len({m["id"] for m in res["modules"]}) == 3
    assert sorted(m["kind"] for m in res["modules"]) == ["folder", "folder", "root"]


def test_top_functions_and_files_are_the_biggest_and_capped():
    files = {f"a/f{n}.py": "python" for n in range(1, 16)}
    files.update({"a/test_x.py": "python", "b/z.py": "python"})
    funcs = [("a/f1.py", "fn5", 5), ("a/f1.py", "fn9", 9), ("a/f2.py", "fn2", 2), ("a/f2.py", "fn7", 7), ("a/f3.py", "fn3", 3), ("a/test_x.py", "fn100", 100)]
    a = by_label(architecture(mini(files, tests=("a/test_x.py",), lines={**{f"a/f{n}.py": n for n in range(1, 16)}, "a/test_x.py": 1}, funcs=funcs)))["a"]
    assert MAX_FILES_LISTED == 12 and MAX_FUNCTIONS_LISTED == 3
    assert [f["path"] for f in a["file_list"]] == [f"a/f{n}.py" for n in range(15, 3, -1)]
    assert [f["name"] for f in a["top_functions"]] == ["fn9", "fn7", "fn5"]
    for text in [f["path"] for f in a["file_list"]] + [f["file"] for f in a["top_functions"]]:
        assert not text.startswith("/") and ":" not in text


# ---- the same answer every time ---------------------------------------------------------------------------------


def test_the_answer_is_the_same_every_time_whatever_the_order():
    files = py("web/app.py", "api/routes.py", "pricing/core.py", "util/x.py", "tests/test_a.py")
    edges = [("web/app.py", "api/routes.py"), ("api/routes.py", "pricing/core.py"), ("api/routes.py", "util/x.py"), ("util/x.py", "api/routes.py")]
    forward = architecture(mini(files, edges, tests=("tests/test_a.py",)))
    backward = architecture(mini(dict(reversed(list(files.items()))), list(reversed(edges)), tests=("tests/test_a.py",)))
    assert forward == backward


def test_an_empty_graph_gives_an_empty_map():
    res = architecture(RepoGraph(root=""))
    assert res["modules"] == [] and res["arrows"] == [] and res["cycles"] == [] and res["columns"] == 0
