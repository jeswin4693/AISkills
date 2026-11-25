import { describe, expect, it } from "vitest";
import { arrowSentences, boxSubtitle, cycleSentences, layoutMap, mapNotes, shortLabel } from "./architecture";
import type { Architecture, ArchModule } from "./types";

const box = (id: string, label: string, column: number, over: Partial<ArchModule> = {}): ArchModule => ({
  id, label, kind: "folder", files: 5, lines: 120, test_files: 0, tests_only: false, symbols: 9, languages: { python: 5 }, measured: true, column,
  top_functions: [], file_list: [], members: [], ...over,
});

const arch = (over: Partial<Architecture> = {}): Architecture => ({
  base: "", modules: [box("m0", "api", 1), box("m1", "pricing", 2), box("m2", "web", 0)],
  arrows: [{ from: "m2", to: "m0", count: 3 }, { from: "m0", to: "m1", count: 1 }],
  cycles: [], columns: 3, measured: true, language_levels: { python: "full" }, left_out: { guess: 0, from_tests: 0 }, notes: [], ...over,
});

/** The eight numbers of an arrow's path "M sx sy C c1x c1y, c2x c2y, ex ey". */
const numbers = (d: string): number[] => (d.match(/-?\d+(?:\.\d+)?/g) ?? []).map(Number);

const overlap = (a: { x: number; y: number; w: number; h: number }, b: { x: number; y: number; w: number; h: number }) =>
  a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

describe("layoutMap", () => {
  it("puts each module in its column, left to right, with no box on top of another", () => {
    const stacked = arch({ modules: [box("m0", "api", 0), box("m1", "db", 0), box("m2", "web", 1), box("m3", "x", 2)], arrows: [], columns: 3 });
    const l = layoutMap(stacked);
    const at = (id: string) => l.boxes.find((b) => b.id === id)!;
    expect(at("m0").x).toBe(at("m1").x);
    expect(at("m0").x).toBeLessThan(at("m2").x);
    expect(at("m2").x).toBeLessThan(at("m3").x);
    for (const a of l.boxes) for (const b of l.boxes) if (a !== b) expect(overlap(a, b)).toBe(false);
  });

  it("stays inside its frame, even with 14 boxes over 6 columns and arrows that go sideways", () => {
    const modules = Array.from({ length: 14 }, (_, i) => box(`m${i}`, `folder${i}`, i % 6, { files: 1 + i * 7 }));
    const arrows = [
      { from: "m0", to: "m1", count: 9 }, { from: "m1", to: "m2", count: 1 }, { from: "m6", to: "m12", count: 40 }, // same column: arcs on the right
      { from: "m5", to: "m0", count: 2 }, // backwards
    ];
    const l = layoutMap(arch({ modules, arrows, columns: 6 }));
    for (const b of l.boxes) {
      expect(b.x).toBeGreaterThanOrEqual(0);
      expect(b.y).toBeGreaterThanOrEqual(0);
      expect(b.x + b.w).toBeLessThanOrEqual(l.width);
      expect(b.y + b.h).toBeLessThanOrEqual(l.height);
    }
    for (const a of l.arrows) {
      numbers(a.d).forEach((n, i) => {
        expect(n).toBeGreaterThanOrEqual(0);
        expect(n).toBeLessThanOrEqual(i % 2 === 0 ? l.width : l.height);
      });
      expect(a.x).toBeGreaterThanOrEqual(0);
      expect(a.x).toBeLessThanOrEqual(l.width);
      expect(a.y).toBeGreaterThanOrEqual(0);
      expect(a.y).toBeLessThanOrEqual(l.height);
    }
  });

  it("starts a forward arrow at the source's right edge and ends it at the target's left edge", () => {
    const l = layoutMap(arch());
    const at = (id: string) => l.boxes.find((b) => b.id === id)!;
    const n = numbers(l.arrows.find((a) => a.from === "m2" && a.to === "m0")!.d);
    expect(n).toHaveLength(8);
    expect(n[0]).toBeCloseTo(at("m2").x + at("m2").w, 1);
    expect(n[1]).toBeCloseTo(at("m2").y + at("m2").h / 2, 1);
    expect(n[6]).toBeCloseTo(at("m0").x, 1);
    expect(n[7]).toBeCloseTo(at("m0").y + at("m0").h / 2, 1);
  });

  it("still draws an arrow that goes sideways or backwards, and flags it as a cycle only when both ends are in one cycle group", () => {
    const modules = [box("m0", "a", 0), box("m1", "b", 0), box("m2", "c", 1)];
    const arrows = [{ from: "m0", to: "m1", count: 1 }, { from: "m1", to: "m0", count: 1 }, { from: "m2", to: "m0", count: 1 }, { from: "m0", to: "m2", count: 1 }];
    const l = layoutMap(arch({ modules, arrows, cycles: [["m0", "m1"]], columns: 2 }));
    const arrow = (from: string, to: string) => l.arrows.find((a) => a.from === from && a.to === to)!;
    expect(l.arrows).toHaveLength(4);
    for (const a of l.arrows) expect(a.d.startsWith("M")).toBe(true);
    expect(arrow("m0", "m1").cycle).toBe(true);
    expect(arrow("m1", "m0").cycle).toBe(true);
    expect(arrow("m2", "m0").cycle).toBe(false);
    expect(arrow("m0", "m2").cycle).toBe(false);
  });

  it("makes an arrow thicker as its count grows, but never thinner than 1.5 or thicker than 8", () => {
    const widthOf = (count: number) => layoutMap(arch({ arrows: [{ from: "m2", to: "m0", count }] })).arrows[0].width;
    expect(widthOf(1)).toBe(1.5);
    expect(widthOf(2)).toBeGreaterThan(widthOf(1));
    expect(widthOf(16)).toBeGreaterThan(widthOf(4));
    expect(widthOf(100000)).toBe(8);
  });

  it("gives the same layout for the same input", () => {
    expect(layoutMap(arch())).toEqual(layoutMap(structuredClone(arch())));
  });

  it("draws nothing for an empty map", () => {
    expect(layoutMap(arch({ modules: [], arrows: [], columns: 0 }))).toEqual({ width: 0, height: 0, boxes: [], arrows: [] });
  });
});

describe("shortLabel", () => {
  it("keeps a short name as it is", () => {
    expect(shortLabel("api")).toBe("api");
  });

  it("shortens a long name to the limit with an ellipsis, counting whole characters", () => {
    expect(shortLabel("x".repeat(90))).toBe("x".repeat(17) + "…");
    const wide = String.fromCodePoint(0x1f600);
    expect(shortLabel(wide.repeat(30))).toBe(wide.repeat(17) + "…");
    expect(shortLabel("abcdefgh", 5)).toBe("abcd…");
  });

  it("leaves markup-like text as plain text (the page escapes it, this does not rewrite it)", () => {
    expect(shortLabel("<b>x</b>")).toBe("<b>x</b>");
    expect(shortLabel("<script>alert(1)</script>").startsWith("<script>alert")).toBe(true);
  });
});

describe("the words under the picture", () => {
  it("reads each arrow as a sentence, in the singular for one file pair", () => {
    expect(arrowSentences(arch())).toEqual(["web imports api (3 file pairs)", "api imports pricing (1 file pair)"]);
  });

  it("names every member of a cycle", () => {
    const [line] = cycleSentences(arch({ cycles: [["m0", "m1"]] }));
    expect(line).toContain("api");
    expect(line).toContain("pricing");
    expect(line).toContain("each other");
    expect(cycleSentences(arch())).toEqual([]);
  });

  it("describes a box in numbers, and says when it is only tests or its imports are not measured", () => {
    expect(boxSubtitle(box("m0", "api", 0, { files: 12, lines: 3400 }))).toBe("12 files · 3,400 lines");
    expect(boxSubtitle(box("m0", "t", 0, { files: 1, lines: 10, tests_only: true }))).toBe("1 file · 10 lines · tests");
    expect(boxSubtitle(box("m0", "s", 0, { measured: false }))).toBe("5 files · 120 lines · imports not measured");
  });

  it("starts with the answer's own notes", () => {
    const one = "Everything sits in one place, so the map is a single box.";
    expect(mapNotes(arch({ notes: [one] }))[0]).toBe(one);
  });

  it("says how many guessed links and test imports were left out", () => {
    const notes = mapNotes(arch({ left_out: { guess: 2, from_tests: 1 } })).join("\n");
    expect(notes).toContain("2 guessed links (name matches only, not proven) are not drawn.");
    expect(notes).toContain("1 import written by test files is not drawn");
    expect(mapNotes(arch()).join("\n")).not.toContain("guessed");
  });

  it("names the languages whose imports are not measured, once, and the base folder", () => {
    const mixed = mapNotes(arch({ base: "src", language_levels: { python: "full", swift: "basic" } }));
    expect(mixed.join("\n")).toContain("Imports are not measured for swift");
    expect(mixed.join("\n")).toContain("folders inside src/");
    const none = mapNotes(arch({ measured: false, language_levels: { swift: "basic" }, notes: ["Imports are not measured for any language here (swift), so no arrows are drawn."] }));
    expect(none.filter((n) => n.includes("not measured"))).toHaveLength(1);
  });

  it("always ends with what the picture cannot say", () => {
    const notes = mapNotes(arch());
    expect(notes[notes.length - 1]).toContain("imports only");
  });
});
