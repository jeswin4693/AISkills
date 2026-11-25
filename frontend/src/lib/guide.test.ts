import { describe, expect, it } from "vitest";
import { bands, docsRead, dropSummary, firstPart, HOP_INFO, hopDetail, hopsUsed, PART_STATUS, partFacts, quoteNote, quoteSource, routeSteps, stepNumbers } from "./guide";
import type { Guide, GuideHop, GuideJourney, GuidePart } from "./types";

const quote = { text: "The API asks the pricing engine for a price.", source: "README.md", line: 4, on_topic: true };

const part = (id: string, layer: string, over: Partial<GuidePart> = {}): GuidePart => ({
  id, name: id.toUpperCase(), layer, summary: "It does a job.", takes_in: "a request", gives_out: "an answer", plain: "Like a desk.", folder: id,
  status: "in_code", files: 3, lines: 120, read_first: { files: [], functions: [] }, quote, ...over,
});

const journey = (parts: string[], statuses: GuideHop["status"][]): GuideJourney => ({
  title: "Place an order",
  steps: parts.map((p) => ({ part: p, does: `${p} acts`, quote })),
  hops: statuses.map((status, i) => ({ from: parts[i], to: parts[i + 1], status, forward: 0, reverse: 0, evidence: [] })),
});

const guide = (over: Partial<Guide> = {}): Guide => ({
  status: "ok", name: "shop", focus: null, source: { kind: "folder" }, provider: "mock", model: "m1", attempts: 1,
  docs: [{ path: "README.md", lines: 35, chars: 900, truncated: false }], docs_skipped: {},
  layers: [{ id: "use", label: "What people use" }, { id: "door", label: "The doors in" }, { id: "work", label: "The workers" }, { id: "shared", label: "Shared services" }, { id: "outside", label: "The outside world" }],
  parts: [part("web", "use"), part("api", "door"), part("pricing", "work"), part("db", "shared")], journeys: [journey(["web", "api", "pricing"], ["docs_only", "confirmed"])],
  dropped: [], notes: [], ...over,
});

describe("bands", () => {
  it("lists only the layers that have a part, in the guide's own order", () => {
    const g = guide({ parts: [part("db", "shared"), part("web", "use"), part("pg", "outside")] });
    expect(bands(g).map((b) => b.id)).toEqual(["use", "shared", "outside"]);
  });

  it("keeps the parts of a layer in the order the guide gave them", () => {
    const g = guide({ parts: [part("b", "work"), part("a", "work")] });
    expect(bands(g)[0].parts.map((p) => p.id)).toEqual(["b", "a"]);
  });

  it("is empty when there are no parts, and ignores a part in a layer the guide does not have", () => {
    expect(bands(guide({ parts: [] }))).toEqual([]);
    expect(bands(guide({ parts: [part("x", "nowhere")] }))).toEqual([]);
  });
});

describe("stepNumbers and routeSteps", () => {
  it("numbers the steps from 1 and lets a part come up twice", () => {
    const j = journey(["web", "api", "web", "pricing"], ["docs_only", "docs_only", "docs_only"]);
    expect([...stepNumbers(j).entries()]).toEqual([["web", [1, 3]], ["api", [2]], ["pricing", [4]]]);
  });

  it("is empty without a route", () => {
    expect(stepNumbers(undefined).size).toBe(0);
    expect(routeSteps(guide(), undefined)).toEqual([]);
  });

  it("gives every step its part and the hop that leads on from it, the last one none", () => {
    const g = guide();
    const steps = routeSteps(g, g.journeys[0]);
    expect(steps.map((s) => [s.n, s.part?.id, s.hopAfter?.status])).toEqual([[1, "web", "docs_only"], [2, "api", "confirmed"], [3, "pricing", undefined]]);
  });

  it("does not break on a step that names a part the answer lacks", () => {
    const g = guide({ journeys: [journey(["web", "ghost"], ["docs_only"])] });
    expect(routeSteps(g, g.journeys[0])[1].part).toBeUndefined();
  });
});

describe("hopsUsed", () => {
  it("lists each kind once, in the order they first appear", () => {
    expect(hopsUsed(journey(["a", "b", "c", "d", "e"], ["docs_only", "confirmed", "docs_only", "reversed"]))).toEqual(["docs_only", "confirmed", "reversed"]);
    expect(hopsUsed(undefined)).toEqual([]);
  });
});

describe("what the page says", () => {
  it("only a confirmed hop is solid, and every other one says why it is not proof", () => {
    expect(Object.entries(HOP_INFO).filter(([, v]) => v.solid).map(([k]) => k)).toEqual(["confirmed"]);
    for (const info of Object.values(HOP_INFO)) {
      expect(info.label.length).toBeGreaterThan(3);
      expect(info.why.length).toBeGreaterThan(20);
    }
  });

  it("names every kind of hop the server can send, so none shows as an empty label", () => {
    expect(Object.keys(HOP_INFO).sort()).toEqual(["both_ways", "confirmed", "docs_only", "not_measured", "reversed", "same_folder", "step_dropped"]);
  });

  it("names every status a part can have, and says only what was checked about a folder", () => {
    expect(Object.keys(PART_STATUS).sort()).toEqual(["docs_only", "external", "in_code"]);
    expect(PART_STATUS.docs_only.label).toContain("not found in the code");
    expect(PART_STATUS.in_code.label).toBe("Folder found in the code"); // not "the part is in the code": the folder was named by a model and only looked up
  });

  it("writes a part's size, and nothing for a part with no files", () => {
    expect(partFacts({ files: 3, lines: 120 })).toBe("3 files · 120 lines");
    expect(partFacts({ files: 1, lines: 1 })).toBe("1 file · 1 line");
    expect(partFacts({ files: 0, lines: 0 })).toBe("");
  });

  it("says where a quote was found", () => {
    expect(quoteSource(quote)).toBe("README.md, line 4");
  });

  it("says nothing about a quote that mentions its part, and warns about one that does not", () => {
    expect(quoteNote({ on_topic: true })).toBe("");
    expect(quoteNote({ on_topic: false })).toContain("does not mention this part");
  });

  it("says how many file pairs are behind a confirmed or reversed hop, and shows one of them", () => {
    const evidence = [{ importer: "web/app.py", imported: "api/routes.py" }];
    expect(hopDetail({ status: "confirmed", forward: 1, reverse: 0, evidence })).toBe("1 file pair, for example web/app.py imports api/routes.py");
    expect(hopDetail({ status: "confirmed", forward: 15, reverse: 0, evidence })).toBe("15 file pairs, for example web/app.py imports api/routes.py");
    expect(hopDetail({ status: "reversed", forward: 0, reverse: 13, evidence })).toBe("13 file pairs, for example web/app.py imports api/routes.py");
  });

  it("gives both numbers for imports both ways, so a reader can see which way is stronger", () => {
    expect(hopDetail({ status: "both_ways", forward: 1, reverse: 6, evidence: [] })).toBe("1 file pair one way, 6 file pairs the other");
  });

  it("has nothing to add for a hop with no import behind it, and does not break with no evidence", () => {
    for (const status of ["docs_only", "same_folder", "not_measured", "step_dropped"] as const) expect(hopDetail({ status, forward: 0, reverse: 0, evidence: [] })).toBe("");
    expect(hopDetail({ status: "confirmed", forward: 2, reverse: 0, evidence: [] })).toBe("2 file pairs");
  });

  it("lists the documents that were read and says which were cut", () => {
    const g = guide({ docs: [{ path: "README.md", lines: 35, chars: 900, truncated: false }, { path: "docs/a.md", lines: 1, chars: 10, truncated: true }] });
    expect(docsRead(g)).toBe("README.md (35 lines), docs/a.md (1 line, cut)");
  });

  it("opens on the route's first part, or the first part when there is no route", () => {
    const g = guide();
    expect(firstPart(g, g.journeys[0])).toBe("web");
    expect(firstPart(g, undefined)).toBe("web");
    expect(firstPart(guide({ parts: [] }), undefined)).toBeNull();
  });
});

describe("dropSummary", () => {
  it("is empty when nothing was dropped", () => {
    expect(dropSummary(guide())).toEqual([]);
  });

  it("counts each reason, the most common first (a tie by the reason's own name), and shows a reason it does not know as it is", () => {
    const dropped = [
      { what: "part", name: "A", reason: "quote_not_found" }, { what: "step", name: "B", reason: "unknown_part" }, { what: "step", name: "C", reason: "quote_not_found" },
      { what: "part", name: "D", reason: "something_new" },
    ];
    expect(dropSummary(guide({ dropped }))).toEqual(["Quote not in the documents: 2", "something_new: 1", "Named a part that was not kept: 1"]);
  });
});
