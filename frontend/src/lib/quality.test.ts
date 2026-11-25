import { describe, expect, it } from "vitest";
import { changeLabel, coverageLine, groupCaption, headlineParts, kindWord, labLine, riskWords, statusTone, suggestionHref, tokenLine } from "./quality";
import type { QualityLab, QualityReport, QualityRun } from "./types";

const run = (over: Partial<QualityRun> = {}): QualityRun => ({
  id: "a".repeat(32), tag: "v2", outcome: "helped", with_skill: { passed: 3, total: 3 }, baseline: { passed: 1, total: 3 }, calls: 6, runs: 1, created_at: "t", ...over,
});
const lab = (over: Partial<QualityLab>): QualityLab => ({ state: "never_run", run: null, other: null, ...over });

describe("statusTone", () => {
  it("maps each check status to a tone, and a check that did not run is neutral, never good", () => {
    expect(statusTone("failed")).toBe("bad");
    expect(statusTone("warning")).toBe("warn");
    expect(statusTone("not run")).toBe("neutral");
    expect(statusTone("passed")).toBe("ok");
  });
});

describe("changeLabel", () => {
  it("says what a library check did since import, in words, and says nothing when it did not change", () => {
    expect(changeLabel("worse")).toEqual({ text: "worse than at import", tone: "bad" });
    expect(changeLabel("better")).toEqual({ text: "better than at import", tone: "ok" });
    expect(changeLabel("new")).toEqual({ text: "did not exist at import", tone: "info" });
    expect(changeLabel("same")).toBeNull();
  });

  it("says nothing for a check run now that was never kept with the version, because the group's caption says it once", () => {
    expect(changeLabel("run_now")).toBeNull();
  });
});

describe("headlineParts", () => {
  it("lists failed, warnings, not run and passed, and only a failure or a warning gets a loud tone", () => {
    expect(headlineParts({ failed: 1, warnings: 2, not_run: 2, passed: 27 })).toEqual([
      { key: "failed", text: "1 failed", tone: "bad" },
      { key: "warnings", text: "2 warnings", tone: "warn" },
      { key: "not_run", text: "2 not run", tone: "neutral" },
      { key: "passed", text: "27 passed", tone: "ok" },
    ]);
  });

  it("is quiet about what is zero and says 1 warning in the singular", () => {
    const parts = headlineParts({ failed: 0, warnings: 1, not_run: 0, passed: 12 });
    expect(parts.map((p) => p.text)).toEqual(["0 failed", "1 warning", "0 not run", "12 passed"]);
    expect(parts[0].tone).toBe("neutral");
    expect(parts[2].tone).toBe("neutral");
  });
});

describe("coverageLine", () => {
  const base: QualityReport["requirements"] = { source: "definition", criteria: [], uncovered: [], unknown_cites: [] };

  it("says plainly when no requirement is recorded, instead of showing zero criteria as if all were covered", () => {
    expect(coverageLine({ ...base, source: "none" })).toMatch(/No requirement is recorded/);
  });

  it("says when the requirement lists no criteria", () => {
    expect(coverageLine(base)).toMatch(/lists no acceptance criteria/);
  });

  it("counts the criteria with and without a test", () => {
    const criteria = [{ id: "AC1", text: "a", tests: ["t"], runnable: 1 }, { id: "AC2", text: "b", tests: [], runnable: 0 }];
    expect(coverageLine({ ...base, criteria, uncovered: ["AC2"] })).toBe("2 acceptance criteria: 1 with a test, 1 without.");
    expect(coverageLine({ ...base, criteria: [criteria[0]] })).toBe("1 acceptance criterion: 1 with a test, 0 without.");
  });
});

describe("labLine", () => {
  it("reports the run of this version with both counts", () => {
    expect(labLine(lab({ state: "this_version", run: run() }))).toBe("The Testing Lab ran v2: the skill helped (with the skill 3/3 · without it 1/3).");
  });

  it("leaves out the comparison when there was none", () => {
    expect(labLine(lab({ state: "this_version", run: run({ baseline: null, outcome: "with_only" }) }))).toBe("The Testing Lab ran v2: no comparison (with the skill 3/3).");
  });

  it("never presents a run of another version as this version's", () => {
    const line = labLine(lab({ state: "older_version", other: run({ tag: "v1" }) }));
    expect(line).toContain("Only v1 was run");
    expect(line).toContain("This version has not been");
  });

  it("says never run, going, and did not finish", () => {
    expect(labLine(lab({ state: "never_run" }))).toBe("The Testing Lab has not been run on this version.");
    expect(labLine(lab({ state: "running" }))).toMatch(/is going/);
    expect(labLine(lab({ state: "failed" }))).toMatch(/did not finish/);
  });
});

describe("riskWords", () => {
  it("never says safe", () => {
    for (const level of ["more_risk", "look", "less_risk", "no_new_risk"] as const) expect(riskWords(level).toLowerCase()).not.toMatch(/\bsafe\b/);
    expect(riskWords("more_risk")).toBe("Got riskier");
    expect(riskWords("no_new_risk")).toBe("No new risk found");
  });
});

describe("suggestionHref", () => {
  it("links to the Lab on the version, the skill's page, and the comparison, with the name encoded", () => {
    expect(suggestionHref({ page: "lab", version: 2 }, "a b")).toBe("/testing?name=a%20b&version=2");
    expect(suggestionHref({ page: "skill" }, "a b")).toBe("/library/a%20b");
    expect(suggestionHref({ page: "compare", from: 1, to: 2 }, "s")).toBe("/library/s/diff?from=1&to=2");
  });

  it("has no link when the server gave none", () => {
    expect(suggestionHref(null, "s")).toBeNull();
  });
});

describe("kindWord", () => {
  it("names what to do in one word", () => {
    expect(["fix", "write", "run", "read", "shorten"].map((k) => kindWord(k as never))).toEqual(["Fix", "Write", "Run", "Read", "Shorten"]);
  });
});

describe("groupCaption", () => {
  it("says for the library group that its checks are the import's, run again; and for the others that they were run now and not kept", () => {
    expect(groupCaption("library")).toMatch(/same checks as an import/);
    expect(groupCaption("design")).toMatch(/not kept with the version/);
    expect(groupCaption("written")).toMatch(/not kept with the version/);
  });
});

describe("tokenLine", () => {
  it("says what is loaded always, when used, and on demand, and that they are estimates", () => {
    const line = tokenLine({ always: 43, when_used: 536, on_demand: 2151, heavy: [] });
    expect(line).toContain("43 tokens always loaded");
    expect(line).toContain("536 when the skill is used");
    expect(line).toContain("2151 more");
    expect(line).toContain("estimates");
  });
});
