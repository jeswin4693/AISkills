import { plural } from "./format";
import type { Architecture } from "./types";

// The picture is plain SVG laid out by this file: no library, no randomness, so the same answer always draws the same map.

const BOX_W = 168;
const COLUMN_GAP = 96; // room between columns for the arrows
const ROW_GAP = 18;
const PAD = 16;
const BOX_MIN_H = 64; // room for the name, the counts and, when it has one, a line saying "tests" or "imports not measured"
const BOX_EXTRA_H = 28; // a box with many files is taller, up to this much more
const FILES_FOR_FULL_HEIGHT = 40;
const ARC = 48; // how far an arrow between two boxes of one column bulges out to the right
export const MIN_ARROW_WIDTH = 1.5;
export const MAX_ARROW_WIDTH = 8;

export interface Placed {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface DrawnArrow {
  from: string;
  to: string;
  count: number;
  /** An SVG path: "M sx sy C c1x c1y, c2x c2y, ex ey". */
  d: string;
  width: number;
  /** Points back against the main direction: an import that closes a loop. Drawn dashed. */
  cycle: boolean;
  /** Where to write the count. */
  x: number;
  y: number;
}

export interface MapLayout {
  width: number;
  height: number;
  boxes: Placed[];
  arrows: DrawnArrow[];
}

const round = (n: number): number => Math.round(n * 10) / 10;

export function arrowWidth(count: number): number {
  return Math.min(MAX_ARROW_WIDTH, Math.max(MIN_ARROW_WIDTH, MIN_ARROW_WIDTH + 1.5 * Math.log2(count)));
}

/** One arrow as a curve. Between columns it runs from the source's right edge to the target's left edge. Inside one column it bulges out to
 * the right (further when it goes up, so an arrow and its opposite do not lie on top of each other). Backwards it runs between the facing edges. */
function curve(s: Placed, t: Placed): { d: string; x: number; y: number } {
  const sy = s.y + s.h / 2;
  const ty = t.y + t.h / 2;
  let sx: number;
  let tx: number;
  let c1: number;
  let c2: number;
  if (t.x === s.x) {
    const bulge = ty < sy ? ARC : ARC / 2;
    sx = s.x + s.w;
    tx = t.x + t.w;
    c1 = sx + bulge;
    c2 = tx + bulge;
  } else if (t.x > s.x) {
    sx = s.x + s.w;
    tx = t.x;
    c1 = sx + (tx - sx) / 2;
    c2 = tx - (tx - sx) / 2;
  } else {
    sx = s.x;
    tx = t.x + t.w;
    c1 = sx + (tx - sx) / 2;
    c2 = tx - (tx - sx) / 2;
  }
  return {
    d: `M ${round(sx)} ${round(sy)} C ${round(c1)} ${round(sy)}, ${round(c2)} ${round(ty)}, ${round(tx)} ${round(ty)}`,
    x: round((sx + 3 * c1 + 3 * c2 + tx) / 8), // the middle of the curve
    y: round((sy + 3 * sy + 3 * ty + ty) / 8),
  };
}

export function layoutMap(arch: Architecture): MapLayout {
  if (arch.modules.length === 0) return { width: 0, height: 0, boxes: [], arrows: [] };
  const columns = Math.max(arch.columns, ...arch.modules.map((m) => m.column + 1));
  const nextY = Array.from({ length: columns }, () => PAD);
  const boxes: Placed[] = arch.modules.map((m) => {
    const h = BOX_MIN_H + Math.round(BOX_EXTRA_H * Math.min(1, m.files / FILES_FOR_FULL_HEIGHT));
    const placed = { id: m.id, x: PAD + m.column * (BOX_W + COLUMN_GAP), y: nextY[m.column], w: BOX_W, h };
    nextY[m.column] += h + ROW_GAP;
    return placed;
  });
  const byId = new Map(boxes.map((b) => [b.id, b]));

  const arrows: DrawnArrow[] = [];
  let sideways = false;
  for (const a of arch.arrows) {
    const s = byId.get(a.from);
    const t = byId.get(a.to);
    if (!s || !t) continue;
    sideways = sideways || s.x === t.x;
    arrows.push({ from: a.from, to: a.to, count: a.count, ...curve(s, t), width: arrowWidth(a.count), cycle: a.back });
  }
  return {
    width: PAD * 2 + columns * BOX_W + (columns - 1) * COLUMN_GAP + (sideways ? ARC : 0),
    height: Math.max(...nextY) - ROW_GAP + PAD,
    boxes,
    arrows,
  };
}

/** A box's name as drawn: a long name is shortened (the full name stays in the box's tooltip and panel). A folder path loses its front, because the
 * last folder is the informative part. Whole characters, not code units. */
export function shortLabel(label: string, max = 18): string {
  const chars = Array.from(label);
  if (chars.length <= max) return label;
  const slash = label.lastIndexOf("/");
  if (slash > 0 && slash < label.length - 1) {
    const tail = Array.from(label.slice(slash + 1));
    return tail.length + 2 <= max ? `…/${tail.join("")}` : `…/${tail.slice(0, max - 3).join("")}…`;
  }
  return chars.slice(0, max - 1).join("") + "…";
}

export function boxSubtitle(m: Architecture["modules"][number]): string {
  const parts = [plural(m.files, "file"), `${m.lines.toLocaleString("en-US")} ${m.lines === 1 ? "line" : "lines"}`];
  if (m.tests_only) parts.push("tests");
  if (!m.measured) parts.push("imports not measured");
  return parts.join(" · ");
}

function labels(arch: Architecture): Map<string, string> {
  return new Map(arch.modules.map((m) => [m.id, m.label]));
}

export function arrowSentences(arch: Architecture): string[] {
  const name = labels(arch);
  return arch.arrows.map((a) => `${name.get(a.from) ?? a.from} imports ${name.get(a.to) ?? a.to} (${plural(a.count, "file pair")})`);
}

const NAMES_SHOWN = 6; // a loop through most of a repository would otherwise be a wall of names

function joinNames(names: string[]): string {
  if (names.length > NAMES_SHOWN) return `${names.slice(0, NAMES_SHOWN).join(", ")} and ${names.length - NAMES_SHOWN} more`;
  return names.length < 2 ? names.join("") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

export function cycleSentences(arch: Architecture): string[] {
  const name = labels(arch);
  return arch.cycles.map((group) => `${joinNames(group.map((id) => name.get(id) ?? id))} import each other (directly or through one another).`);
}

const LIMIT =
  "This is a picture of imports only: an arrow means files in one folder can use files in another, not what the program does when it runs. " +
  "A folder is a rough stand-in for a module.";

/** What to say under the picture: the answer's own notes first, then what was left out and not measured, and always what the picture cannot say. */
export function mapNotes(arch: Architecture): string[] {
  const notes = [...arch.notes];
  if (arch.base) notes.push(`Showing the folders inside ${arch.base}/.`);
  const { guess, from_tests: fromTests } = arch.left_out;
  if (guess > 0) notes.push(`${plural(guess, "guessed link")} (name matches only, not proven) ${guess === 1 ? "is" : "are"} not drawn.`);
  if (fromTests > 0) {
    notes.push(`${plural(fromTests, "import")} written by test files ${fromTests === 1 ? "is" : "are"} not drawn, so a tests folder does not point at every box.`);
  }
  const unread = Object.entries(arch.language_levels).filter(([, level]) => level === "basic").map(([lang]) => lang).sort();
  if (arch.measured && unread.length > 0) {
    notes.push(`Imports are not measured for ${unread.join(", ")} (read for definitions only), so a folder holding only those files shows no arrows.`);
  }
  if (arch.arrows.some((a) => a.back)) {
    notes.push("Dashed arrows point back against the main direction (right to left, or inside one column): they are the imports that close a loop.");
  }
  notes.push(LIMIT);
  return notes;
}
