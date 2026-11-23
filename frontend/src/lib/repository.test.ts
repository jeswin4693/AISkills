import { describe, expect, it } from "vitest";
import {
  buildRequest, callSummary, canBuild, categoryInfo, factSummary, ideaGroups, ideaKey, isNetworkPath, languageRows, levelNote, loadRemembered, looksAbsolute,
  pathProblem, recordedWhen, remember, REPO_KEY, runInfo, verdictInfo, VERDICT_ORDER, workingRun,
} from "./repository";
import type { EvidenceRef, Idea, RepoAnalysis, SuggestRunSummary } from "./types";

const idea = (over: Partial<Idea> = {}): Idea => ({
  title: "A skill", category: "skill", rationale: "why", evidence: ["F1"], next_step: "go", confidence: "high",
  skill_requirement: "A skill that lists what a change to a function touches.", evidence_nodes: ["pricing.py::calculate_tax", "pricing.py"],
  ignored_evidence: [], unverified_numbers: [], ...over,
});

function memory(initial: Record<string, string> = {}) {
  const data = { ...initial };
  return { getItem: (k: string) => data[k] ?? null, setItem: (k: string, v: string) => void (data[k] = v), data };
}

describe("the remembered folder", () => {
  it("is empty the first time and remembers what was typed", () => {
    const store = memory();
    expect(loadRemembered(store)).toEqual({ path: "", focus: "" });
    remember({ path: "C:\\code\\shop", focus: "src" }, store);
    expect(JSON.parse(store.data[REPO_KEY])).toEqual({ path: "C:\\code\\shop", focus: "src" });
    expect(loadRemembered(store)).toEqual({ path: "C:\\code\\shop", focus: "src" });
  });

  it("ignores a damaged or odd value instead of breaking the page", () => {
    expect(loadRemembered(memory({ [REPO_KEY]: "{not json" }))).toEqual({ path: "", focus: "" });
    expect(loadRemembered(memory({ [REPO_KEY]: JSON.stringify({ path: 5, focus: null }) }))).toEqual({ path: "", focus: "" });
  });

  it("works without any storage (a blocked browser)", () => {
    expect(loadRemembered(undefined)).toEqual({ path: "", focus: "" });
    expect(() => remember({ path: "/x", focus: "" }, undefined)).not.toThrow();
    const failing = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
    expect(loadRemembered(failing)).toEqual({ path: "", focus: "" });
    expect(() => remember({ path: "/x", focus: "" }, failing)).not.toThrow();
  });
});

describe("what counts as a full path", () => {
  it.each(["C:\\code\\shop", "c:/code/shop", "/home/me/repo", "  /home/me/repo  "])("accepts %s", (p) => expect(looksAbsolute(p)).toBe(true));
  it.each(["", "shop-api", ".." + "\\shop", "./shop", "code\\shop", "C:shop"])("refuses %j", (p) => expect(looksAbsolute(p)).toBe(false));

  it("never takes a network path: opening one would reach out to another machine", () => {
    for (const p of ["\\\\server\\share\\repo", "//server/share/repo", "\\\\?\\C:\\x"]) {
      expect(isNetworkPath(p)).toBe(true);
      expect(looksAbsolute(p)).toBe(false);
      expect(pathProblem(p)).toContain("Network paths are not read");
    }
  });

  it("says what is wrong with a path, and nothing about an empty box or a good path", () => {
    expect(pathProblem("")).toBeNull();
    expect(pathProblem("/home/me/shop")).toBeNull();
    expect(pathProblem("shop-api")).toContain("full path");
  });
});

const stats: RepoAnalysis["stats"] = {
  files: 120, test_files: 20, lines: 9000, languages: { typescript: 30, python: 80, lua: 10 },
  language_levels: { typescript: "full", python: "full", lua: "basic" }, symbols: {}, edges: {},
  call_sites: { resolved: 60, guess: 10, ambiguous: 10, external: 15, unresolved: 5 }, unresolved_imports: 0, parse_problems: 0, commits_read: null, co_change_pairs: 0,
};

describe("the graph's facts in words", () => {
  it("lists languages by size and says what each level means", () => {
    const rows = languageRows(stats);
    expect(rows.map((r) => r.name)).toEqual(["python", "typescript", "lua"]);
    expect(rows[2].note).toContain("calls are not resolved");
    expect(levelNote("zzz")).toBe("level not known");
    expect(levelNote(undefined)).toBe("level not known");
  });

  it("says how much of the call graph is proven, and that the rest is left out", () => {
    expect(callSummary(stats)).toContain("60 of 100 calls");
    expect(callSummary(stats)).toContain("left out");
    expect(callSummary({ ...stats, call_sites: {} })).toBe("No calls were found.");
  });
});

describe("ideas", () => {
  it("only skill and automation ideas that carry a requirement and cite real places can start a build", () => {
    expect(canBuild(idea())).toBe(true);
    expect(canBuild(idea({ category: "automation" }))).toBe(true);
    expect(canBuild(idea({ category: "refactor" }))).toBe(false);
    expect(canBuild(idea({ skill_requirement: "too short" }))).toBe(false);
    expect(canBuild(idea({ evidence_nodes: [] }))).toBe(false);
  });

  it("starts the build with the wording the person settled on, and says which idea of which run", () => {
    expect(buildRequest("  A skill that does a thing for people.  ", "r1", 2)).toEqual({ description: "A skill that does a thing for people.", seed: { run: "r1", idea: 2 } });
  });

  it("keys an edit by run and position, so a later run with a same-titled idea never inherits it", () => {
    expect(ideaKey("run-a", 1)).not.toBe(ideaKey("run-b", 1));
    expect(ideaKey("run-a", 1)).not.toBe(ideaKey("run-a", 2));
    expect(ideaKey("run-a", 1)).toBe(ideaKey("run-a", 1));
  });

  it("picks up a run that is still asking the model, and only that", () => {
    const run = (id: string, status: SuggestRunSummary["status"]): SuggestRunSummary => ({ id, status, repo: "r", focus: null, with_ideas: true, error: "", retryable: false, created_at: "", updated_at: "", ideas: 0 });
    expect(workingRun(undefined)).toBeUndefined();
    expect(workingRun([run("a", "done"), run("b", "failed")])).toBeUndefined();
    expect(workingRun([run("a", "done"), run("b", "working"), run("c", "working")])?.id).toBe("b");
  });

  it("puts what this app can build first and keeps the model's order inside each group", () => {
    const a = idea({ title: "a", category: "risk" }), b = idea({ title: "b" }), c = idea({ title: "c", category: "test" }), d = idea({ title: "d", category: "automation" });
    const g = ideaGroups([a, b, c, d]);
    expect(g.buildable.map((i) => i.title)).toEqual(["b", "d"]);
    expect(g.other.map((i) => i.title)).toEqual(["a", "c"]);
  });

  it("names a category it does not know instead of hiding it", () => {
    expect(categoryInfo("skill").label).toBe("Skill idea");
    expect(categoryInfo("mystery")).toEqual({ label: "mystery", tone: "neutral", buildable: false });
  });

  it("describes each state of a run", () => {
    expect(runInfo("working").label).toBe("Asking the model");
    expect(runInfo("failed").tone).toBe("bad");
    expect(runInfo("done").tone).toBe("ok");
  });
});

describe("evidence", () => {
  it("orders verdicts worst first and explains each", () => {
    expect(VERDICT_ORDER).toEqual(["missing", "moved", "changed", "edited", "holds"]);
    for (const v of VERDICT_ORDER) expect(verdictInfo(v).hint.length).toBeGreaterThan(10);
    expect(verdictInfo("moved").hint).toContain("never applied for you");
  });

  it("says when a place was recorded, and whether the tree had uncommitted changes then", () => {
    expect(recordedWhen({ taken_at: "2026-11-23T09:00:00+00:00", commit: "023faa8", dirty: true })).toBe("2026-11-23, commit 023faa8 (with uncommitted changes)");
    expect(recordedWhen({ taken_at: null, commit: null, dirty: false }, { taken_at: "2026-11-20T01:00:00+00:00", commit: "abc" })).toBe("2026-11-20, commit abc");
    expect(recordedWhen({ taken_at: "2026-11-23T09:00:00+00:00", commit: null, dirty: false })).toBe("2026-11-23");
  });

  const ref = (over: Partial<EvidenceRef>): EvidenceRef => ({
    id: "a.py::f", kind: "symbol", file: "a.py", lang: "python", taken_at: null, commit: null, dirty: false, symbol_kind: "function",
    callers_total: 4, callees_total: 1, members_total: 0, symbols_total: 0, importers_total: 0, measured: true, ...over,
  });

  it("summarises what was recorded, and never says 'no callers' where calls were not measured", () => {
    expect(factSummary(ref({}))).toBe("function, 4 callers, calls 1");
    expect(factSummary(ref({ callers_total: 1 }))).toContain("1 caller,");
    expect(factSummary(ref({ measured: false }))).toBe("function, callers not measured in this language");
    expect(factSummary(ref({ symbol_kind: "class", members_total: 3 }))).toContain("3 methods");
    expect(factSummary(ref({ kind: "file", symbols_total: 2, importers_total: 5 }))).toBe("2 symbols, imported by 5");
    expect(factSummary(ref({ kind: "file", symbols_total: 1, measured: false }))).toBe("1 symbol");
  });
});
