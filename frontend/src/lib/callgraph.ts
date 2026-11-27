import { arrowWidth, curve, shortLabel, type Placed } from "./architecture";
import { plural } from "./format";
import type { CallGraph, CallNode, FunctionMatch, FunctionSearch } from "./types";

// The call graph of one function is plain SVG laid out by this file: no library, no randomness, so the same answer always draws the same picture.
// Callers are on the left, the chosen function in the middle and what it calls on the right; only columns that hold something take room.

const BOX_W = 196;
const BOX_H = 52;
const COLUMN_GAP = 84; // room between columns for the arrows
const ROW_GAP = 14;
const PAD = 16;
const ARC = 48; // how far an arrow between two boxes of one column bulges out to the right (the same bulge the folder map draws)

export interface DrawnCall {
  from: string;
  to: string;
  count: number;
  /** An SVG path: "M sx sy C c1x c1y, c2x c2y, ex ey". */
  d: string;
  width: number;
  /** The call goes against the left-to-right order (a callee that calls one of the callers). Drawn dashed. */
  back: boolean;
  /** Where to write the count. */
  x: number;
  y: number;
}

export interface CallLayout {
  width: number;
  height: number;
  boxes: Placed[];
  arrows: DrawnCall[];
}

export function layoutCalls(g: CallGraph): CallLayout {
  if (g.nodes.length === 0) return { width: 0, height: 0, boxes: [], arrows: [] };
  const first = Math.min(...g.nodes.map((n) => n.column));
  const columns = Math.max(...g.nodes.map((n) => n.column)) - first + 1;
  const stacks: CallNode[][] = Array.from({ length: columns }, () => []);
  for (const n of g.nodes) stacks[n.column - first].push(n); // the answer's order is by name, so each column is too
  const heights = stacks.map((s) => s.length * BOX_H + Math.max(0, s.length - 1) * ROW_GAP);
  const tallest = Math.max(...heights);
  const placed = new Map<string, Placed>();
  stacks.forEach((stack, c) => {
    let y = PAD + (tallest - heights[c]) / 2; // a short column is centred against the tallest one
    for (const n of stack) {
      placed.set(n.id, { id: n.id, x: PAD + c * (BOX_W + COLUMN_GAP), y, w: BOX_W, h: BOX_H });
      y += BOX_H + ROW_GAP;
    }
  });

  const arrows: DrawnCall[] = [];
  let sideways = false;
  for (const e of g.edges) {
    const s = placed.get(e.from);
    const t = placed.get(e.to);
    if (!s || !t) continue;
    sideways = sideways || s.x === t.x;
    arrows.push({ from: e.from, to: e.to, count: e.count, ...curve(s, t), width: arrowWidth(e.count), back: t.x < s.x });
  }
  return {
    width: PAD * 2 + columns * BOX_W + (columns - 1) * COLUMN_GAP + (sideways ? ARC : 0),
    height: PAD * 2 + tallest,
    boxes: g.nodes.map((n) => placed.get(n.id)!),
    arrows,
  };
}

/** A function's name as drawn in its box: a long name is shortened (the full name is in the box's tooltip and in the list under the picture). */
export function shortName(name: string): string {
  return shortLabel(name, 26);
}

/** Where a function is, short enough for a box: the last folder and the file, then the line. */
export function nodeSubtitle(n: Pick<CallNode, "file" | "line">): string {
  return `${n.file.split("/").slice(-2).join("/")}:${n.line}`;
}

/** A function's own proven callers and callees, and the test functions that call it. */
export function nodeCounts(n: Pick<CallNode, "callers_total" | "callees_total" | "tests_total">): string {
  const parts = [plural(n.callers_total, "caller"), `calls ${n.callees_total}`];
  if (n.tests_total > 0) parts.push(plural(n.tests_total, "test"));
  return parts.join(" · ");
}

function drawnNeighbours(g: CallGraph): { callers: number; callees: number } {
  const id = g.subject.id;
  return {
    callers: new Set(g.edges.filter((e) => e.to === id && e.from !== id).map((e) => e.from)).size,
    callees: new Set(g.edges.filter((e) => e.from === id && e.to !== id).map((e) => e.to)).size,
  };
}

/** The headline: how many functions call the chosen one and how many it calls, and how many of those are not drawn. A language whose calls are
 * not read says so; it is never "called by 0". */
export function summarySentence(g: CallGraph): string {
  const name = g.subject.name;
  if (!g.measured) return `${name} is in ${g.language}. Who calls it and what it calls is not measured.`;
  const { callers, callees } = drawnNeighbours(g);
  const more = (total: number, drawn: number) => (total > drawn ? ` (${total - drawn} more not drawn)` : "");
  return `${name} is called by ${plural(callers, "function")}${more(g.subject.callers_total, callers)} and calls ${plural(callees, "function")}${more(g.subject.callees_total, callees)}.`;
}

/** What the picture leaves out and what it cannot know, in words. Only what applies is said. */
export function callNotes(g: CallGraph): string[] {
  if (!g.measured) {
    return [
      `The graph reads ${g.language} at the ${g.level} level: it finds the functions but not the calls between them, so an empty picture means nothing is known, not that nothing calls it.`,
    ];
  }
  const { guess, from_tests: tests, over_limit: over } = g.left_out;
  const notes = ["Only calls the graph proves are drawn: it ties each call to one function by scope and imports, and a call it cannot pin to one function is left out."];
  if (guess > 0) notes.push(`${plural(guess, "call")} matched by name only ${guess === 1 ? "was" : "were"} left out.`);
  if (tests > 0) {
    notes.push(`${plural(tests, "test function")} call${tests === 1 ? "s" : ""} these functions and ${tests === 1 ? "is" : "are"} not drawn: that shows they are tested, not how the program works.`);
  }
  if (over > 0) notes.push(`${plural(over, "more function")} ${over === 1 ? "is" : "are"} not drawn, to keep the picture readable. Click a function to see its own neighbours.`);
  if (g.calls.written > 0) {
    notes.push(
      `Of the ${plural(g.calls.written, "call")} written in ${g.subject.name}, ${g.calls.tied} ${g.calls.tied === 1 ? "is" : "are"} tied to a function in this repository; the rest reach code outside it, the function itself, or a name the graph cannot pin to one function.`,
    );
  }
  return notes;
}

/** Every drawn call as a sentence: the picture's text twin, for a screen reader and for a crowded picture. */
export function edgeSentences(g: CallGraph): string[] {
  const name = new Map(g.nodes.map((n) => [n.id, n.name]));
  return [...g.edges]
    .map((e) => ({ a: name.get(e.from) ?? e.from, b: name.get(e.to) ?? e.to, count: e.count }))
    .sort((x, y) => x.a.localeCompare(y.a) || x.b.localeCompare(y.b))
    .map((e) => `${e.a} calls ${e.b}${e.count > 1 ? ` (${e.count} call sites)` : ""}`);
}

/** One search result: where it is, and what it connects to (or that this language's calls are not measured: the numbers would be unknown, not zero). */
export function matchLine(m: FunctionMatch): string {
  const parts = [`${m.file}:${m.line}`, m.measured ? `${plural(m.callers, "caller")} · calls ${m.callees}` : "calls not measured in this language"];
  if (m.test) parts.push("test");
  return parts.join(" · ");
}

/** What to say under the search results, or null when the list is the whole answer. */
export function searchNote(s: FunctionSearch): string | null {
  if (s.total === 0) return `No function matches "${s.query}".`;
  if (s.total > s.matches.length) return `Showing the first ${s.matches.length} of ${s.total} matches. Type more of the name to narrow them.`;
  return null;
}
