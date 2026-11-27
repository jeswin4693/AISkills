import { describe, expect, it } from "vitest";
import { callNotes, edgeSentences, layoutCalls, matchLine, nodeCounts, nodeSubtitle, searchNote, shortName, summarySentence } from "./callgraph";
import type { CallEdge, CallGraph, CallNode, FunctionMatch, FunctionSearch } from "./types";

const node = (name: string, column: number, over: Partial<CallNode> = {}): CallNode => ({
  id: `f.py::${name}`, name, kind: "function", file: "f.py", line: 3, lines: 10, test: false,
  role: column === 0 ? "subject" : column < 0 ? "caller" : "callee", column, callers_total: 0, tests_total: 0, callees_total: 0, ...over,
});

const edge = (from: string, to: string, count = 1): CallEdge => ({ from: `f.py::${from}`, to: `f.py::${to}`, count });

/** checkout, called by handle, calling price and audit. */
const graph = (over: Partial<CallGraph> = {}): CallGraph => {
  const nodes = [node("handle", -1), node("checkout", 0, { callers_total: 1, callees_total: 2 }), node("audit", 1), node("price", 1)];
  return {
    name: "shop", focus: null, subject: nodes[1], nodes, edges: [edge("handle", "checkout"), edge("checkout", "audit"), edge("checkout", "price", 3)],
    depth: 1, measured: true, language: "python", level: "full", calls: { written: 8, tied: 4 }, left_out: { guess: 0, from_tests: 0, over_limit: 0 }, ...over,
  };
};

const numbers = (d: string): number[] => (d.match(/-?\d+(?:\.\d+)?/g) ?? []).map(Number);
const overlap = (a: { x: number; y: number; w: number; h: number }, b: { x: number; y: number; w: number; h: number }) =>
  a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

describe("layoutCalls", () => {
  it("puts what calls the function on the left, the function in the middle and what it calls on the right", () => {
    const l = layoutCalls(graph());
    const at = (name: string) => l.boxes.find((b) => b.id === `f.py::${name}`)!;
    expect(at("handle").x).toBeLessThan(at("checkout").x);
    expect(at("checkout").x).toBeLessThan(at("price").x);
    expect(at("audit").x).toBe(at("price").x);
  });

  it("centres a short column against the tallest one", () => {
    const l = layoutCalls(graph());
    const at = (name: string) => l.boxes.find((b) => b.id === `f.py::${name}`)!;
    const middle = (name: string) => at(name).y + at(name).h / 2;
    const callees = (at("audit").y + at("price").y + at("price").h) / 2; // the middle of the two stacked boxes
    expect(middle("handle")).toBeCloseTo(callees, 5);
    expect(middle("checkout")).toBeCloseTo(callees, 5);
  });

  it("gives every node one box, in the answer's order, and no box lies on another", () => {
    const g = graph();
    const l = layoutCalls(g);
    expect(l.boxes.map((b) => b.id)).toEqual(g.nodes.map((n) => n.id));
    for (let i = 0; i < l.boxes.length; i++) for (let j = i + 1; j < l.boxes.length; j++) expect(overlap(l.boxes[i], l.boxes[j])).toBe(false);
  });

  it("uses only the columns that hold something, so one step is three columns wide and not five", () => {
    const l = layoutCalls(graph());
    expect(new Set(l.boxes.map((b) => b.x)).size).toBe(3);
    const two = layoutCalls(graph({ nodes: [...graph().nodes, node("deep", 2), node("up", -2)] }));
    expect(new Set(two.boxes.map((b) => b.x)).size).toBe(5);
    expect(two.width).toBeGreaterThan(l.width);
  });

  it("makes the picture exactly as wide and as tall as its boxes plus an equal margin, with no room for columns that hold nothing", () => {
    const l = layoutCalls(graph());
    const left = Math.min(...l.boxes.map((b) => b.x));
    const top = Math.min(...l.boxes.map((b) => b.y));
    expect(l.width).toBe(Math.max(...l.boxes.map((b) => b.x + b.w)) + left);
    expect(l.height).toBe(Math.max(...l.boxes.map((b) => b.y + b.h)) + top);
    expect(left).toBeGreaterThan(0);
    expect(top).toBeGreaterThan(0);
  });

  it("draws every edge with a path of finite numbers and a thicker line for more call sites", () => {
    const l = layoutCalls(graph());
    expect(l.arrows).toHaveLength(3);
    for (const a of l.arrows) expect(numbers(a.d).every(Number.isFinite) && numbers(a.d).length === 8).toBe(true);
    const width = (to: string) => l.arrows.find((a) => a.to === `f.py::${to}`)!.width;
    expect(width("price")).toBeGreaterThan(width("audit"));
  });

  it("draws a call that goes against the left-to-right order dashed, and one inside a column not dashed", () => {
    const g = graph({ edges: [...graph().edges, edge("price", "handle"), edge("audit", "price")] });
    const l = layoutCalls(g);
    expect(l.arrows.find((a) => a.from === "f.py::price" && a.to === "f.py::handle")!.back).toBe(true);
    expect(l.arrows.find((a) => a.from === "f.py::audit" && a.to === "f.py::price")!.back).toBe(false);
    expect(l.arrows.find((a) => a.from === "f.py::handle")!.back).toBe(false);
  });

  it("leaves room for an arrow that bulges out of a column", () => {
    const plain = layoutCalls(graph());
    const bulge = layoutCalls(graph({ edges: [...graph().edges, edge("audit", "price")] }));
    expect(bulge.width).toBeGreaterThan(plain.width);
  });

  it("draws a lone function as one box with no arrows", () => {
    const only = node("lonely", 0);
    const l = layoutCalls(graph({ nodes: [only], subject: only, edges: [] }));
    expect(l.boxes).toHaveLength(1);
    expect(l.arrows).toEqual([]);
    expect(l.width).toBeGreaterThan(0);
    expect(l.height).toBeGreaterThan(0);
  });

  it("draws the same picture for the same answer", () => {
    expect(layoutCalls(graph())).toEqual(layoutCalls(graph()));
  });

  it("skips an edge whose end is not among the nodes instead of failing", () => {
    const l = layoutCalls(graph({ edges: [...graph().edges, edge("checkout", "ghost")] }));
    expect(l.arrows).toHaveLength(3);
  });
});

describe("summarySentence", () => {
  it("says how many functions call it and how many it calls", () => {
    expect(summarySentence(graph())).toBe("checkout is called by 1 function and calls 2 functions.");
  });

  it("says how many neighbours are not drawn", () => {
    const g = graph();
    const subject = { ...g.subject, callers_total: 4, callees_total: 9 };
    expect(summarySentence({ ...g, subject, nodes: g.nodes.map((n) => (n.id === subject.id ? subject : n)) })).toBe(
      "checkout is called by 1 function (3 more not drawn) and calls 2 functions (7 more not drawn).",
    );
  });

  it("says a function nothing calls and that calls nothing is alone", () => {
    const only = node("lonely", 0);
    expect(summarySentence(graph({ nodes: [only], subject: only, edges: [] }))).toBe("lonely is called by 0 functions and calls 0 functions.");
  });

  it("says plainly that calls are not measured, never that nothing calls it", () => {
    const only = node("run", 0, { file: "a.lua" });
    const s = summarySentence(graph({ nodes: [only], subject: only, edges: [], measured: false, language: "lua", level: "basic" }));
    expect(s).toContain("lua");
    expect(s).toContain("not measured");
    expect(s).not.toContain("called by 0");
  });
});

describe("callNotes", () => {
  it("always says that only proven calls are drawn", () => {
    expect(callNotes(graph()).join(" ")).toContain("proves");
  });

  it("says nothing about what was left out when nothing was", () => {
    const notes = callNotes(graph()).join(" ");
    expect(notes).not.toContain("name only");
    expect(notes).not.toContain("test function");
    expect(notes).not.toContain("not drawn");
  });

  it("counts the calls matched by name only that were left out", () => {
    expect(callNotes(graph({ left_out: { guess: 1, from_tests: 0, over_limit: 0 } })).join(" ")).toContain("1 call matched by name only was left out");
    expect(callNotes(graph({ left_out: { guess: 3, from_tests: 0, over_limit: 0 } })).join(" ")).toContain("3 calls matched by name only were left out");
  });

  it("counts the test functions that were not drawn", () => {
    expect(callNotes(graph({ left_out: { guess: 0, from_tests: 2, over_limit: 0 } })).join(" ")).toContain("2 test functions");
  });

  it("says how many more could be drawn and how to see them", () => {
    const notes = callNotes(graph({ left_out: { guess: 0, from_tests: 0, over_limit: 5 } })).join(" ");
    expect(notes).toContain("5 more functions are not drawn");
    expect(notes).toContain("Click");
  });

  it("says how many of the calls written in the function are tied to a function of the repository", () => {
    expect(callNotes(graph()).join(" ")).toContain("Of the 8 calls written in checkout, 4 are tied");
    expect(callNotes(graph({ calls: { written: 0, tied: 0 } })).join(" ")).not.toContain("Of the");
  });

  it("explains a language whose calls are not measured and gives no other note", () => {
    const only = node("run", 0);
    const notes = callNotes(graph({ nodes: [only], subject: only, edges: [], measured: false, language: "lua", level: "basic" }));
    expect(notes).toHaveLength(1);
    expect(notes[0]).toContain("lua");
    expect(notes[0]).toContain("basic");
  });
});

describe("edgeSentences", () => {
  it("says each call in words with the number of places it is called from", () => {
    expect(edgeSentences(graph())).toEqual(["checkout calls audit", "checkout calls price (3 call sites)", "handle calls checkout"]);
  });
});

describe("shortName", () => {
  it("leaves a short name alone and shortens a long one to fit its box, with a mark that it was cut", () => {
    expect(shortName("checkout")).toBe("checkout");
    const long = shortName("a_function_with_a_name_that_is_far_too_long_for_a_box");
    expect(Array.from(long)).toHaveLength(26);
    expect(long.endsWith("…")).toBe(true);
  });
});

describe("nodeSubtitle and nodeCounts", () => {
  it("shows the last two folders of a file and its line", () => {
    expect(nodeSubtitle(node("x", 0, { file: "backend/skillforge/graph/query.py", line: 42 }))).toBe("graph/query.py:42");
    expect(nodeSubtitle(node("x", 0, { file: "q.py", line: 7 }))).toBe("q.py:7");
  });

  it("says its own callers and calls, and the tests that call it", () => {
    expect(nodeCounts(node("x", 0, { callers_total: 2, callees_total: 1 }))).toBe("2 callers · calls 1");
    expect(nodeCounts(node("x", 0, { callers_total: 1, callees_total: 0, tests_total: 3 }))).toBe("1 caller · calls 0 · 3 tests");
  });
});

describe("search results", () => {
  const match = (over: Partial<FunctionMatch> = {}): FunctionMatch => ({ id: "f.py::x", name: "x", kind: "function", file: "pkg/f.py", line: 9, test: false, callers: 2, callees: 1, measured: true, ...over });
  const found = (over: Partial<FunctionSearch> = {}): FunctionSearch => ({ name: "shop", focus: null, query: "x", matches: [match()], total: 1, ...over });

  it("describes a match with where it is and what it connects to", () => {
    expect(matchLine(match())).toBe("pkg/f.py:9 · 2 callers · calls 1");
    expect(matchLine(match({ callers: 1 }))).toBe("pkg/f.py:9 · 1 caller · calls 1");
    expect(matchLine(match({ test: true }))).toBe("pkg/f.py:9 · 2 callers · calls 1 · test");
  });

  it("says calls are not measured instead of showing zeros for a language that is not read", () => {
    const line = matchLine(match({ measured: false, callers: 0, callees: 0 }));
    expect(line).toContain("not measured");
    expect(line).not.toContain("0 callers");
  });

  it("says when there are more matches than are shown, and when there are none", () => {
    expect(searchNote(found())).toBeNull();
    expect(searchNote(found({ total: 61, matches: Array.from({ length: 25 }, () => match()) }))).toBe("Showing the first 25 of 61 matches. Type more of the name to narrow them.");
    expect(searchNote(found({ total: 0, matches: [], query: "zzz" }))).toBe('No function matches "zzz".');
  });
});
