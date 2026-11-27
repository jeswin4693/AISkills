"""Slice AL: the function-level call graph. One function, the functions that call it and the functions it calls, one level or two.

Graphs are built by hand so every rule is exact: a guess call is never drawn, a test that calls a function is counted and not drawn, a language
whose calls are not measured says so, the caps cut the weakest first, and the same graph always gives the same answer."""

from __future__ import annotations

import pytest

from skillforge.graph.callgraph import MAX_MATCHES, MAX_SIDE, call_graph, search_functions
from skillforge.graph.model import CallSite, Edge, FileRecord, RepoGraph, Symbol
from skillforge.graph.query import QueryError


def sid(file, name):
    return f"{file}::{name}"


def build(funcs, calls=(), tests=(), langs=None, kinds=None, sites=None):
    """A RepoGraph made by hand. funcs: (file, qualname) pairs. calls: (src, dst[, conf[, count]]) with src and dst written as `file::name`.
    tests: file paths that are test files. langs: file -> language (python otherwise). kinds: id -> kind (function otherwise).
    sites: id -> how many call sites that function writes (0 otherwise)."""
    g = RepoGraph(root="")
    for file, name in funcs:
        if file not in g.files:
            g.files[file] = FileRecord(path=file, lang=(langs or {}).get(file, "python"), lines=50, size=1000, mtime_ns=0, is_test=file in tests)
        i = sid(file, name)
        sym = Symbol(id=i, kind=(kinds or {}).get(i, "function"), name=name.split(".")[-1], qualname=name, file=file, line=3, end_line=12)
        sym.calls = [CallSite(callee="x", line=4, kind="name") for _ in range((sites or {}).get(i, 0))]
        g.symbols[i] = sym
        g.files[file].symbols.append(sym)
    for src, dst, *rest in calls:
        conf = rest[0] if rest else "resolved"
        count = rest[1] if len(rest) > 1 else 1
        g.edges.append(Edge(src=src, dst=dst, kind="calls", conf=conf, count=count))
    return g


def names(res, role=None):
    return sorted(n["name"] for n in res["nodes"] if role is None or n["role"] == role)


def by_name(res):
    return {n["name"]: n for n in res["nodes"]}


def pairs(res):
    short = lambda i: i.split("::")[1]  # noqa: E731
    return sorted((short(e["from"]), short(e["to"])) for e in res["edges"])


# a small shop: web -> checkout -> price -> tax, and checkout -> audit
SHOP = [("web.py", "handle"), ("shop.py", "checkout"), ("shop.py", "price"), ("shop.py", "tax"), ("shop.py", "audit")]
SHOP_CALLS = [
    (sid("web.py", "handle"), sid("shop.py", "checkout")),
    (sid("shop.py", "checkout"), sid("shop.py", "price")),
    (sid("shop.py", "price"), sid("shop.py", "tax")),
    (sid("shop.py", "checkout"), sid("shop.py", "audit")),
]


def shop():
    return build(SHOP, SHOP_CALLS)


# ---- the neighbourhood ---------------------------------------------------------------------------------------


def test_one_level_has_the_callers_on_the_left_and_the_callees_on_the_right():
    res = call_graph(shop(), sid("shop.py", "checkout"))
    assert res["subject"]["name"] == "checkout" and res["subject"]["role"] == "subject" and res["subject"]["column"] == 0
    assert names(res, "caller") == ["handle"] and by_name(res)["handle"]["column"] == -1
    assert names(res, "callee") == ["audit", "price"] and {by_name(res)[n]["column"] for n in ("audit", "price")} == {1}
    assert pairs(res) == [("checkout", "audit"), ("checkout", "price"), ("handle", "checkout")]
    assert res["depth"] == 1


def test_two_levels_add_what_the_neighbours_call_and_what_calls_them():
    g = build(
        [*SHOP, ("jobs.py", "nightly")],
        [*SHOP_CALLS, (sid("jobs.py", "nightly"), sid("web.py", "handle"))],
    )
    one = call_graph(g, sid("shop.py", "checkout"), depth=1)
    two = call_graph(g, sid("shop.py", "checkout"), depth=2)
    assert "tax" not in names(one) and "nightly" not in names(one)
    assert by_name(two)["tax"]["column"] == 2 and by_name(two)["nightly"]["column"] == -2
    assert ("price", "tax") in pairs(two) and ("nightly", "handle") in pairs(two)
    assert two["depth"] == 2


@pytest.mark.parametrize(("asked", "used"), [(0, 1), (1, 1), (2, 2), (3, 2), (99, 2), (-5, 1)])
def test_the_depth_is_one_or_two(asked, used):
    assert call_graph(shop(), sid("shop.py", "checkout"), depth=asked)["depth"] == used


def test_a_function_with_no_neighbours_is_drawn_alone_and_is_still_measured():
    res = call_graph(build([("a.py", "lonely")]), sid("a.py", "lonely"))
    assert names(res) == ["lonely"] and res["edges"] == [] and res["measured"] is True


def test_a_node_two_steps_away_that_is_also_one_step_away_is_drawn_once_at_the_nearer_column():
    g = build(
        [("a.py", "root"), ("a.py", "mid"), ("a.py", "leaf")],
        [(sid("a.py", "root"), sid("a.py", "mid")), (sid("a.py", "root"), sid("a.py", "leaf")), (sid("a.py", "mid"), sid("a.py", "leaf"))],
    )
    res = call_graph(g, sid("a.py", "root"), depth=2)
    assert [n["name"] for n in res["nodes"]].count("leaf") == 1 and by_name(res)["leaf"]["column"] == 1
    assert pairs(res) == [("mid", "leaf"), ("root", "leaf"), ("root", "mid")]


def test_a_call_between_two_drawn_neighbours_is_an_edge_too():
    g = build(
        [("a.py", "me"), ("a.py", "up"), ("a.py", "down")],
        [(sid("a.py", "up"), sid("a.py", "me")), (sid("a.py", "me"), sid("a.py", "down")), (sid("a.py", "up"), sid("a.py", "down"))],
    )
    assert ("up", "down") in pairs(call_graph(g, sid("a.py", "me")))


def test_two_functions_that_call_each_other_are_one_node_on_the_callee_side_with_both_edges():
    g = build([("a.py", "ping"), ("a.py", "pong")], [(sid("a.py", "ping"), sid("a.py", "pong")), (sid("a.py", "pong"), sid("a.py", "ping"))])
    res = call_graph(g, sid("a.py", "ping"))
    assert names(res) == ["ping", "pong"] and by_name(res)["pong"]["role"] == "both" and by_name(res)["pong"]["column"] == 1
    assert pairs(res) == [("ping", "pong"), ("pong", "ping")]


def test_the_edge_says_how_many_call_sites_there_are():
    g = build(SHOP, [(sid("shop.py", "checkout"), sid("shop.py", "price"), "resolved", 4)])
    (edge,) = call_graph(g, sid("shop.py", "checkout"))["edges"]
    assert edge["count"] == 4


# ---- only proven calls are drawn -----------------------------------------------------------------------------


def test_a_guess_is_never_drawn_and_is_counted():
    g = build(SHOP, [*SHOP_CALLS, (sid("shop.py", "checkout"), sid("shop.py", "tax"), "guess"), (sid("shop.py", "audit"), sid("shop.py", "checkout"), "guess")])
    res = call_graph(g, sid("shop.py", "checkout"))
    assert "tax" not in names(res) and all(e["from"] != sid("shop.py", "audit") for e in res["edges"])
    assert res["left_out"]["guess"] == 2


def test_every_drawn_edge_is_proven_even_between_neighbours():
    g = build(SHOP, [*SHOP_CALLS, (sid("shop.py", "price"), sid("shop.py", "audit"), "guess")])
    res = call_graph(g, sid("shop.py", "checkout"), depth=2)
    assert ("price", "audit") not in pairs(res)


def test_a_guess_next_to_a_function_two_steps_away_is_counted_too():
    g = build(SHOP, [*SHOP_CALLS, (sid("shop.py", "price"), sid("shop.py", "audit"), "guess")])
    assert call_graph(g, sid("shop.py", "checkout"), depth=2)["left_out"]["guess"] == 1
    assert call_graph(g, sid("shop.py", "checkout"), depth=1)["left_out"]["guess"] == 0  # price is not looked at in one level


def test_a_guess_only_neighbour_does_not_count_in_the_totals():
    g = build(SHOP, [(sid("shop.py", "checkout"), sid("shop.py", "tax"), "guess")])
    node = call_graph(g, sid("shop.py", "checkout"))["subject"]
    assert node["callees_total"] == 0 and node["callers_total"] == 0


# ---- test code is counted, not drawn -------------------------------------------------------------------------


def test_functions_in_test_files_that_call_it_are_counted_and_not_drawn():
    g = build([*SHOP, ("tests/test_shop.py", "test_a"), ("tests/test_shop.py", "test_b")],
              [*SHOP_CALLS, (sid("tests/test_shop.py", "test_a"), sid("shop.py", "checkout")), (sid("tests/test_shop.py", "test_b"), sid("shop.py", "checkout"))],
              tests=("tests/test_shop.py",))
    res = call_graph(g, sid("shop.py", "checkout"))
    assert names(res, "caller") == ["handle"] and res["left_out"]["from_tests"] == 2
    assert res["subject"]["tests_total"] == 2 and res["subject"]["callers_total"] == 1


def test_a_test_function_chosen_on_purpose_shows_what_it_calls_and_who_calls_it():
    g = build([("shop.py", "checkout"), ("tests/t.py", "helper"), ("tests/t.py", "test_a")],
              [(sid("tests/t.py", "test_a"), sid("tests/t.py", "helper")), (sid("tests/t.py", "test_a"), sid("shop.py", "checkout"))],
              tests=("tests/t.py",))
    res = call_graph(g, sid("tests/t.py", "helper"))
    assert names(res, "caller") == ["test_a"] and res["left_out"]["from_tests"] == 0
    assert "checkout" in names(call_graph(g, sid("tests/t.py", "test_a")))


def test_a_test_that_calls_a_caller_two_steps_away_is_counted_not_drawn():
    g = build([*SHOP, ("tests/t.py", "test_p")], [*SHOP_CALLS, (sid("tests/t.py", "test_p"), sid("web.py", "handle"))], tests=("tests/t.py",))
    two = call_graph(g, sid("shop.py", "checkout"), depth=2)
    assert "test_p" not in names(two) and two["left_out"]["from_tests"] == 1
    assert call_graph(g, sid("shop.py", "checkout"), depth=1)["left_out"]["from_tests"] == 0  # handle is not looked at in one level


# ---- languages whose calls are not measured ------------------------------------------------------------------


def test_a_basic_language_says_not_measured_and_draws_no_edges():
    g = build([("a.lua", "run"), ("a.lua", "helper")], [(sid("a.lua", "run"), sid("a.lua", "helper"))], langs={"a.lua": "lua"})
    res = call_graph(g, sid("a.lua", "run"))
    assert res["measured"] is False and res["language"] == "lua" and res["level"] == "basic"
    assert names(res) == ["run"] and res["edges"] == []


@pytest.mark.parametrize(("lang", "level"), [("python", "full"), ("typescript", "full"), ("java", "standard"), ("go", "standard")])
def test_a_full_or_standard_language_is_measured(lang, level):
    res = call_graph(build([("a.x", "f")], langs={"a.x": lang}), sid("a.x", "f"))
    assert res["measured"] is True and res["level"] == level


# ---- what is asked for ---------------------------------------------------------------------------------------


def test_something_that_is_not_in_the_graph_is_refused_with_words():
    with pytest.raises(QueryError):
        call_graph(shop(), "nothing.py::nope")


def test_a_module_is_not_a_function():
    g = build([("a.py", "<module>")], kinds={sid("a.py", "<module>"): "module"})
    with pytest.raises(QueryError):
        call_graph(g, sid("a.py", "<module>"))


@pytest.mark.parametrize("kind", ["function", "method", "class"])
def test_functions_methods_and_classes_can_be_chosen(kind):
    g = build([("a.py", "Thing")], kinds={sid("a.py", "Thing"): kind})
    assert call_graph(g, sid("a.py", "Thing"))["subject"]["kind"] == kind


# ---- numbers the page shows ----------------------------------------------------------------------------------


def test_each_node_carries_its_own_proven_totals():
    res = call_graph(shop(), sid("shop.py", "checkout"))
    me, price = res["subject"], by_name(res)["price"]
    assert (me["callers_total"], me["callees_total"]) == (1, 2)
    assert (price["callers_total"], price["callees_total"]) == (1, 1)  # price is called by checkout and calls tax, which is not drawn at one level


def test_calls_written_and_calls_tied_are_the_sites_in_the_function_and_the_ones_tied_to_a_function_here():
    g = build(SHOP, [(sid("shop.py", "checkout"), sid("shop.py", "price"), "resolved", 3), (sid("shop.py", "checkout"), sid("shop.py", "tax"), "guess", 2)],
              sites={sid("shop.py", "checkout"): 9})
    assert call_graph(g, sid("shop.py", "checkout"))["calls"] == {"written": 9, "tied": 3}


def test_a_node_says_where_it_is():
    node = call_graph(shop(), sid("shop.py", "checkout"))["subject"]
    assert (node["file"], node["line"], node["lines"], node["kind"], node["test"]) == ("shop.py", 3, 10, "function", False)
    assert node["id"] == sid("shop.py", "checkout")


# ---- caps ----------------------------------------------------------------------------------------------------


def crowd(n):
    """n functions that call `hub`, the later ones more often (c00 once, c01 twice, ...), so the strongest are NOT the first by name."""
    funcs = [("hub.py", "hub"), *[("many.py", f"c{i:02d}") for i in range(n)]]
    calls = [(sid("many.py", f"c{i:02d}"), sid("hub.py", "hub"), "resolved", 1 + i) for i in range(n)]
    return build(funcs, calls)


def test_the_chosen_function_shows_at_most_ten_neighbours_a_side_the_strongest_first_and_says_how_many_were_cut():
    res = call_graph(crowd(14), sid("hub.py", "hub"))
    assert len(names(res, "caller")) == 10
    assert names(res, "caller") == [f"c{i:02d}" for i in range(4, 14)]  # c13 has the most call sites; the four weakest are cut
    assert res["left_out"]["over_limit"] == 4


def test_neighbours_of_equal_strength_are_cut_by_name_and_not_by_the_file_they_are_in():
    # twelve callers with one call site each; the file names run the other way from the function names
    funcs = [("hub.py", "hub")] + [(f"f{11 - i:02d}.py", f"n{i:02d}") for i in range(12)]
    calls = [(sid(f"f{11 - i:02d}.py", f"n{i:02d}"), sid("hub.py", "hub")) for i in range(12)]
    res = call_graph(build(funcs, calls), sid("hub.py", "hub"))
    assert names(res, "caller") == [f"n{i:02d}" for i in range(10)]


def test_the_nodes_come_out_by_column_then_name():
    g = build([*SHOP, ("jobs.py", "nightly"), ("jobs.py", "cron")],
              [*SHOP_CALLS, (sid("jobs.py", "nightly"), sid("web.py", "handle")), (sid("jobs.py", "cron"), sid("web.py", "handle"))])
    keys = [(n["column"], n["name"], n["id"]) for n in call_graph(g, sid("shop.py", "checkout"), depth=2)["nodes"]]
    assert keys == sorted(keys) and keys[0][0] == -2 and keys[-1][0] == 2


def test_two_functions_that_call_each_other_are_never_drawn_twice_two_steps_out():
    g = build([("a.py", "ping"), ("a.py", "pong")], [(sid("a.py", "ping"), sid("a.py", "pong")), (sid("a.py", "pong"), sid("a.py", "ping"))])
    res = call_graph(g, sid("a.py", "ping"), depth=2)
    assert [n["name"] for n in res["nodes"]].count("ping") == 1 and names(res) == ["ping", "pong"]
    assert by_name(res)["ping"]["role"] == "subject" and by_name(res)["ping"]["column"] == 0


def test_the_strongest_first_breaks_ties_by_name():
    g = build([("hub.py", "hub"), ("m.py", "b"), ("m.py", "a")], [(sid("m.py", "b"), sid("hub.py", "hub")), (sid("m.py", "a"), sid("hub.py", "hub"))])
    assert [n["name"] for n in call_graph(g, sid("hub.py", "hub"))["nodes"] if n["role"] == "caller"] == ["a", "b"]


def test_a_side_never_draws_more_than_the_side_cap_over_two_levels():
    funcs = [("hub.py", "hub")] + [("l1.py", f"m{i}") for i in range(10)] + [("l2.py", f"n{i}_{j}") for i in range(10) for j in range(5)]
    calls = [(sid("hub.py", "hub"), sid("l1.py", f"m{i}")) for i in range(10)] + [(sid("l1.py", f"m{i}"), sid("l2.py", f"n{i}_{j}")) for i in range(10) for j in range(5)]
    res = call_graph(build(funcs, calls), sid("hub.py", "hub"), depth=2)
    assert MAX_SIDE == 20  # the number the design and the page's notes speak of
    assert len(names(res, "callee")) == 20
    assert res["left_out"]["over_limit"] == 10 + 50 - 20


def test_a_neighbour_two_steps_away_shows_at_most_five_of_what_it_calls():
    funcs = [("hub.py", "hub"), ("l1.py", "mid")] + [("l2.py", f"leaf{i}") for i in range(9)]
    calls = [(sid("hub.py", "hub"), sid("l1.py", "mid"))] + [(sid("l1.py", "mid"), sid("l2.py", f"leaf{i}")) for i in range(9)]
    res = call_graph(build(funcs, calls), sid("hub.py", "hub"), depth=2)
    assert sum(1 for n in res["nodes"] if n["column"] == 2) == 5 and res["left_out"]["over_limit"] == 4


def test_a_neighbour_shown_by_another_path_is_not_counted_as_cut():
    g = build([("a.py", "hub"), ("a.py", "x"), ("a.py", "y")], [(sid("a.py", "hub"), sid("a.py", "x")), (sid("a.py", "hub"), sid("a.py", "y")), (sid("a.py", "x"), sid("a.py", "y"))])
    assert call_graph(g, sid("a.py", "hub"), depth=2)["left_out"]["over_limit"] == 0


# ---- the same answer every time ------------------------------------------------------------------------------


def test_the_answer_does_not_depend_on_the_order_the_graph_was_built_in():
    forward = shop()
    backward = build(list(reversed(SHOP)), list(reversed(SHOP_CALLS)))
    for depth in (1, 2):
        assert call_graph(forward, sid("shop.py", "checkout"), depth) == call_graph(backward, sid("shop.py", "checkout"), depth)


def test_no_path_of_a_folder_is_in_the_answer():
    g = build(SHOP, SHOP_CALLS)
    g.root = "C:/Users/someone/private/shop"
    assert "someone" not in repr(call_graph(g, sid("shop.py", "checkout")))


# ---- searching -----------------------------------------------------------------------------------------------


def test_the_search_ranks_an_exact_name_then_a_prefix_then_a_part_then_a_file():
    g = build([("x.py", "price"), ("x.py", "price_list"), ("x.py", "unit_price"), ("price_rules.py", "apply")])
    assert [m["name"] for m in search_functions(g, "price")["matches"]] == ["price", "price_list", "unit_price", "apply"]


def test_the_search_ignores_case_and_surrounding_spaces():
    assert [m["name"] for m in search_functions(shop(), "  CHECKOUT ")["matches"]] == ["checkout"]


def test_the_search_puts_code_before_tests_and_the_most_called_first():
    g = build([("t.py", "tax_test"), ("a.py", "tax_a"), ("a.py", "tax_b"), ("a.py", "caller")],
              [(sid("a.py", "caller"), sid("a.py", "tax_b")), (sid("a.py", "caller"), sid("t.py", "tax_test"))], tests=("t.py",))
    # all three start with the text; the test comes last although it has a caller, and of the other two the one with a caller comes first
    assert [m["name"] for m in search_functions(g, "tax")["matches"]] == ["tax_b", "tax_a", "tax_test"]


def test_a_module_is_not_found_but_a_class_is():
    g = build([("a.py", "<module>"), ("a.py", "Shop")], kinds={sid("a.py", "<module>"): "module", sid("a.py", "Shop"): "class"})
    assert [m["name"] for m in search_functions(g, "a.py")["matches"]] == ["Shop"]


def test_the_search_is_capped_and_says_how_many_matched():
    g = build([("a.py", f"f{i:03d}") for i in range(MAX_MATCHES + 7)])
    res = search_functions(g, "f")
    assert len(res["matches"]) == MAX_MATCHES and res["total"] == MAX_MATCHES + 7


def test_a_match_carries_what_helps_choose_it():
    g = build([*SHOP, ("a.lua", "run")], SHOP_CALLS, langs={"a.lua": "lua"})
    got = {m["name"]: m for m in search_functions(g, "checkout")["matches"] + search_functions(g, "run")["matches"]}
    assert got["checkout"] == {"id": sid("shop.py", "checkout"), "name": "checkout", "kind": "function", "file": "shop.py", "line": 3, "test": False,
                               "callers": 1, "callees": 2, "measured": True}
    assert got["run"]["measured"] is False


def test_a_blank_search_finds_nothing():
    assert search_functions(shop(), "   ") == {"matches": [], "total": 0}


def test_a_name_in_a_file_with_an_odd_path_is_found_by_the_name():
    g = build([("src/deep/er/file.py", "Klass.method")])
    assert [m["name"] for m in search_functions(g, "method")["matches"]] == ["Klass.method"]
