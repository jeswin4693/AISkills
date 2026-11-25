import { describe, expect, it } from "vitest";
import { arrowSentences, boxSubtitle, cycleSentences, drawnArrows, layoutMap, loopMarks, mapNotes, MAX_DRAWN_ARROWS, shortLabel } from "./architecture";
import type { Architecture, ArchModule } from "./types";

const box = (id: string, label: string, column: number, over: Partial<ArchModule> = {}): ArchModule => ({
  id, label, kind: "folder", files: 5, lines: 120, test_files: 0, tests_only: false, symbols: 9, languages: { python: 5 }, measured: true, column,
  top_functions: [], file_list: [], members: [], ...over,
});

const arch = (over: Partial<Architecture> = {}): Architecture => ({
  base: "", modules: [box("m0", "api", 1), box("m1", "pricing", 2), box("m2", "web", 0)],
  arrows: [{ from: "m2", to: "m0", count: 3, back: false }, { from: "m0", to: "m1", count: 1, back: false }],
  cycles: [], columns: 3, measured: true, language_levels: { python: "full" }, imports_not_read: [], left_out: { guess: 0, from_tests: 0 }, notes: [], ...over,
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
      { from: "m0", to: "m1", count: 9, back: false }, { from: "m1", to: "m2", count: 1, back: false },
      { from: "m6", to: "m12", count: 40, back: false }, // same column: arcs on the right
      { from: "m5", to: "m0", count: 2, back: true }, // backwards
      { from: "m5", to: "m11", count: 3, back: false }, { from: "m11", to: "m5", count: 1, back: true }, // the last column: its arcs need room on the right
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

  it("still draws an arrow that goes sideways or backwards, and marks as a cycle arrow exactly the ones the answer says point back", () => {
    const modules = [box("m0", "a", 0), box("m1", "b", 0), box("m2", "c", 1)];
    const arrows = [
      { from: "m0", to: "m1", count: 1, back: false }, { from: "m1", to: "m0", count: 1, back: true },
      { from: "m2", to: "m0", count: 1, back: true }, { from: "m0", to: "m2", count: 1, back: false },
    ];
    const l = layoutMap(arch({ modules, arrows, cycles: [["m0", "m1", "m2"]], columns: 2 }));
    const arrow = (from: string, to: string) => l.arrows.find((a) => a.from === from && a.to === to)!;
    expect(l.arrows).toHaveLength(4);
    for (const a of l.arrows) expect(a.d.startsWith("M")).toBe(true);
    expect(arrow("m0", "m1").cycle).toBe(false); // inside the cycle group, but it follows the main direction
    expect(arrow("m1", "m0").cycle).toBe(true);
    expect(arrow("m2", "m0").cycle).toBe(true);
    expect(arrow("m0", "m2").cycle).toBe(false);
  });

  it("orders the boxes inside a column so arrows cross less: a box sits near the boxes it is connected to", () => {
    const modules = [box("m0", "a", 0), box("m1", "b", 0), box("m2", "x", 1), box("m3", "y", 1)]; // by name x comes before y
    const arrows = [{ from: "m0", to: "m3", count: 1, back: false }, { from: "m1", to: "m2", count: 1, back: false }]; // a -> y and b -> x would cross
    const l = layoutMap(arch({ modules, arrows, columns: 2 }));
    const at = (id: string) => l.boxes.find((b) => b.id === id)!;
    expect(at("m3").y).toBeLessThan(at("m2").y); // y, which a points at, is above x, which b points at
    expect(at("m0").y).toBeLessThan(at("m1").y); // the column that was already in order is left alone
  });

  it("keeps the answer's order for boxes that are not connected to anything", () => {
    const modules = [box("m0", "a", 0), box("m1", "b", 0), box("m2", "c", 0)];
    const l = layoutMap(arch({ modules, arrows: [], columns: 1 }));
    const ys = ["m0", "m1", "m2"].map((id) => l.boxes.find((b) => b.id === id)!.y);
    expect(ys).toEqual([...ys].sort((p, q) => p - q));
  });

  it("draws at most 36 arrows, the strongest, and keeps the rest for the list", () => {
    const modules = Array.from({ length: 12 }, (_, i) => box(`m${i}`, `f${i}`, i % 4));
    const arrows = Array.from({ length: 50 }, (_, i) => ({ from: `m${i % 12}`, to: `m${(i * 5 + 3) % 12}`, count: 50 - i, back: false })).filter((a) => a.from !== a.to);
    const drawnCounts = layoutMap(arch({ modules, arrows, columns: 4 })).arrows.map((a) => a.count);
    expect(MAX_DRAWN_ARROWS).toBe(36);
    expect(drawnCounts).toHaveLength(Math.min(36, arrows.length));
    expect(drawnArrows(arch({ modules, arrows, columns: 4 })).length).toBe(drawnCounts.length);
    const left = arrows.map((a) => a.count).filter((c) => !drawnCounts.includes(c));
    expect(Math.min(...drawnCounts)).toBeGreaterThan(Math.max(...left));
  });

  it("keeps an arrow and the one going the other way between the same two boxes apart, so both can be seen", () => {
    const pair = (columns: [number, number]) =>
      layoutMap(arch({
        modules: [box("m0", "a", columns[0]), box("m1", "b", columns[1])],
        arrows: [{ from: "m0", to: "m1", count: 1, back: false }, { from: "m1", to: "m0", count: 1, back: true }],
        columns: 2,
      }));
    for (const l of [pair([0, 1]), pair([0, 0])]) {
      const [there, back] = l.arrows;
      expect(Math.hypot(there.x - back.x, there.y - back.y)).toBeGreaterThanOrEqual(8); // their middles are not in the same place
    }
  });

  it("makes an arrow thicker as its count grows, but never thinner than 1.5 or thicker than 8", () => {
    const widthOf = (count: number) => layoutMap(arch({ arrows: [{ from: "m2", to: "m0", count, back: false }] })).arrows[0].width;
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

  it("shortens a long folder path from the front, because the last folder is the informative part", () => {
    expect(shortLabel("skillforge/validate")).toBe("…/validate");
    expect(shortLabel("skillforge/graph")).toBe("skillforge/graph"); // fits: kept whole
    expect(shortLabel("a/" + "x".repeat(60))).toBe("…/" + "x".repeat(15) + "…");
    expect(Array.from(shortLabel("a/b/" + "y".repeat(40))).length).toBeLessThanOrEqual(18);
  });

  it("leaves markup-like text as plain text (the page escapes it, this does not rewrite it)", () => {
    expect(shortLabel("<b>x</b>")).toBe("<b>x</b>");
    expect(Array.from(shortLabel("<script>alert(1)</script>")).length).toBeLessThanOrEqual(18);
  });
});

describe("loopMarks", () => {
  it("marks every folder of a loop, and separately the ones at the ends of an arrow that closes it", () => {
    // a loop m0 -> m1 -> m2 -> m0: only m2 -> m0 points back, so the folder in the middle is in the loop but at the end of no back arrow
    const modules = [box("m0", "a", 0), box("m1", "b", 1), box("m2", "c", 2), box("m3", "d", 3)];
    const arrows = [
      { from: "m0", to: "m1", count: 1, back: false }, { from: "m1", to: "m2", count: 1, back: false }, { from: "m2", to: "m0", count: 1, back: true },
      { from: "m2", to: "m3", count: 1, back: false },
    ];
    const marks = loopMarks(arch({ modules, arrows, cycles: [["m0", "m1", "m2"]], columns: 4 }));
    expect([...marks.inLoop].sort()).toEqual(["m0", "m1", "m2"]);
    expect([...marks.closes].sort()).toEqual(["m0", "m2"]);
  });

  it("marks nothing when nothing loops", () => {
    const marks = loopMarks(arch());
    expect(marks.inLoop.size).toBe(0);
    expect(marks.closes.size).toBe(0);
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

  it("does not list a long cycle group in full: the first six names, then how many more", () => {
    const modules = Array.from({ length: 9 }, (_, i) => box(`m${i}`, `folder${i}`, 0));
    const [line] = cycleSentences(arch({ modules, arrows: [], cycles: [modules.map((m) => m.id)] }));
    expect(line).toBe("folder0, folder1, folder2, folder3, folder4, folder5 and 3 more import each other (directly or through one another).");
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
    expect(notes).toContain("1 import written by tests or test scaffolding (an e2e suite, fixtures, mocks) is not drawn");
    expect(mapNotes(arch()).join("\n")).not.toContain("guessed");
  });

  it("uses the plural for several test imports and says nothing when there are none", () => {
    expect(mapNotes(arch({ left_out: { guess: 0, from_tests: 12 } })).join("\n")).toContain("12 imports written by tests or test scaffolding (an e2e suite, fixtures, mocks) are not drawn");
    expect(mapNotes(arch()).join("\n")).not.toContain("scaffolding");
  });

  it("names the languages whose imports are not measured, once, and the base folder", () => {
    // csharp is a "standard" level language, but its imports are not turned into links between files: the answer says so, the level alone does not
    const mixed = mapNotes(arch({ base: "src", language_levels: { python: "full", csharp: "standard" }, imports_not_read: ["csharp"] }));
    expect(mixed.join("\n")).toContain("Imports are not measured for csharp");
    expect(mixed.join("\n")).toContain("folders inside src/");
    expect(mapNotes(arch({ language_levels: { python: "full", java: "standard" } })).join("\n")).not.toContain("not measured");
    const none = mapNotes(arch({
      measured: false, language_levels: { swift: "basic" }, imports_not_read: ["swift"],
      notes: ["Imports are not measured for any language here (swift), so no arrows are drawn."],
    }));
    expect(none.filter((n) => n.includes("not measured"))).toHaveLength(1);
  });

  it("points at a folder that holds most of the code, with the exact text to type to zoom in", () => {
    const big = arch({ base: "src", modules: [box("m0", "api", 0, { files: 60 }), box("m1", "db", 0, { files: 10 })], arrows: [] });
    expect(mapNotes(big).join("\n")).toContain('api holds 86% of the files. To see how it is laid out, type src/api in "Only this folder inside it"');
    const flat = arch({ modules: [box("m0", "api", 0, { files: 60 }), box("m1", "db", 0, { files: 10 })], arrows: [] });
    expect(mapNotes(flat).join("\n")).toContain("type api in");
  });

  it("gives no zoom-in hint when no folder dominates, the repository is small, or the big box is not one folder", () => {
    expect(mapNotes(arch()).join("\n")).not.toContain("holds");
    expect(mapNotes(arch({ modules: [box("m0", "a", 0, { files: 10 }), box("m1", "b", 0, { files: 1 })], arrows: [] })).join("\n")).not.toContain("holds");
    const folded = arch({ modules: [box("m0", "(other: 9 more)", 0, { files: 60, kind: "other" }), box("m1", "db", 0, { files: 10 })], arrows: [] });
    expect(mapNotes(folded).join("\n")).not.toContain("holds");
    const top = arch({ modules: [box("m0", "(root)", 0, { files: 60, kind: "root" }), box("m1", "db", 0, { files: 10 })], arrows: [] });
    expect(mapNotes(top).join("\n")).not.toContain("holds");
  });

  it("says how many weaker arrows are not drawn, only when some are left out", () => {
    expect(mapNotes(arch()).join("\n")).not.toContain("weaker");
    const modules = Array.from({ length: 12 }, (_, i) => box(`m${i}`, `f${i}`, i % 4));
    const arrows = Array.from({ length: 50 }, (_, i) => ({ from: `m${i % 12}`, to: `m${(i * 5 + 3) % 12}`, count: 50 - i, back: false })).filter((a) => a.from !== a.to);
    const notes = mapNotes(arch({ modules, arrows, columns: 4 })).join("\n");
    expect(notes).toContain(`${arrows.length - 36} weaker arrows are not drawn`);
    expect(notes).toContain("The arrows as a list");
  });

  it("explains dashed arrows only when there are some", () => {
    expect(mapNotes(arch()).join("\n")).not.toContain("Dashed");
    const back = arch({ arrows: [{ from: "m0", to: "m2", count: 1, back: true }] });
    expect(mapNotes(back).join("\n")).toContain("Dashed arrows point back against the main direction");
  });

  it("always ends with what the picture cannot say", () => {
    const notes = mapNotes(arch());
    expect(notes[notes.length - 1]).toContain("imports only");
  });
});
