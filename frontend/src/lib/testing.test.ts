import { describe, expect, it } from "vitest";
import {
  blockerAdvice, callsFor, checkWords, costText, failureLines, outcomeInfo, outcomeLabel, parseVersion, pickVersion, progressText, repeatNote,
  runChoices, runLine, sideSummary, staleNote,
} from "./testing";
import type { EvalAttempt, EvalCheckResult, EvalRunSummary, EvalTry } from "./types";

const check = (passed: boolean, detail = "", kind = "regex"): EvalCheckResult => ({ kind, value: "x", why: "rule", passed, detail });
const attempt = (passes: boolean[], details: string[][] = []): EvalAttempt => {
  const tries: EvalTry[] = passes.map((p, i) => ({ reply: "r", cut: false, passed: p, checks: p ? [check(true)] : (details[i] ?? ["it failed"]).map((d) => check(false, d)) }));
  return { passed: passes.filter(Boolean).length, runs: passes.length, tries };
};

describe("outcomeInfo", () => {
  const o = { skillTokens: 392, cases: 3, minCases: 3 };

  it("says the skill helped, in a good tone", () => {
    expect(outcomeInfo("helped", o)).toMatchObject({ tone: "ok", title: "The skill helped" });
  });

  it("warns, with the token cost, when the model does as well without the skill", () => {
    const r = outcomeInfo("adds_nothing", o);
    expect(r.tone).toBe("warn");
    expect(r.title).toBe("The skill adds nothing on these tests");
    expect(r.text).toContain("392 tokens");
  });

  it("says plainly that the skill made it worse, and that a weak test is possible too", () => {
    const r = outcomeInfo("worse", o);
    expect(r.tone).toBe("bad");
    expect(r.text).toMatch(/weak test or a weak skill/);
  });

  it("is neutral when there was no difference", () => {
    expect(outcomeInfo("no_difference", o)).toMatchObject({ tone: "info", title: "No difference on these tests" });
  });

  it("says how many cases ran and how many are needed when there were too few", () => {
    const r = outcomeInfo("too_few", { ...o, cases: 2 });
    expect(r.tone).toBe("info");
    expect(r.text).toContain("Only 2");
    expect(r.text).toContain("3");
  });

  it("never claims a result when the comparison was not run", () => {
    const r = outcomeInfo("with_only", o);
    expect(r.tone).toBe("info");
    expect(r.text).toMatch(/not whether it helped/);
  });

  it("is a warning, not a pass, when nothing ran", () => {
    expect(outcomeInfo("not_run", o)).toMatchObject({ tone: "warn", title: "Nothing was run" });
  });
});

describe("cost", () => {
  it("counts one call per case, repeat and condition", () => {
    expect(callsFor(3, 1, true)).toBe(6);
    expect(callsFor(3, 3, true)).toBe(18);
    expect(callsFor(3, 3, false)).toBe(9);
    expect(callsFor(0, 3, true)).toBe(0);
  });

  it("writes the number in words, singular included", () => {
    expect(costText(6)).toBe("6 model calls");
    expect(costText(1)).toBe("1 model call");
  });

  it("offers only the repeat counts the server allows", () => {
    expect(runChoices(5)).toEqual([1, 3, 5]);
    expect(runChoices(3)).toEqual([1, 3]);
    expect(runChoices(1)).toEqual([1]);
  });

  it("reminds that one repeat can mislead, but not after three", () => {
    expect(repeatNote(1)).toMatch(/Repeat 3 times/);
    expect(repeatNote(3)).toBeNull();
    expect(repeatNote(5)).toBeNull();
  });
});

describe("blockerAdvice", () => {
  it("gives a different next step for each reason a skill cannot be run, and none when it can", () => {
    const texts = (["no_cases", "needs_tools", "nothing_runnable"] as const).map(blockerAdvice);
    expect(new Set(texts).size).toBe(3);
    expect(texts.every((t) => t.length > 20)).toBe(true);
    expect(blockerAdvice("")).toBe("");
  });

  it("tells a person with a tool-using skill that the Lab cannot help it, instead of offering a fix that does not exist", () => {
    expect(blockerAdvice("needs_tools")).toMatch(/use it for real/i);
    expect(blockerAdvice("needs_tools")).not.toMatch(/add .*test cases|build it again|import it as a new version/i); // more test cases would not make it runnable
    expect(blockerAdvice("no_cases")).toMatch(/build it again/i); // and for a skill that can be helped, the way is named
  });
});

describe("checkWords", () => {
  it.each([
    [{ kind: "contains", value: "Fix" }, 'contains "Fix"'],
    [{ kind: "not_contains", value: "TODO" }, 'does not contain "TODO"'],
    [{ kind: "starts_with", value: "Add" }, 'starts with "Add"'],
    [{ kind: "regex", value: "^[A-Z]" }, "matches the pattern ^[A-Z]"],
    [{ kind: "max_chars", value: "280" }, "is at most 280 characters"],
    [{ kind: "max_lines", value: "6" }, "is at most 6 lines"],
    [{ kind: "first_line_max_chars", value: "50" }, "has a first line of at most 50 characters"],
  ])("says %j in words", (spec, words) => {
    expect(checkWords({ ...spec, why: "" })).toBe(words);
  });

  it("does not hide a kind it does not know", () => {
    expect(checkWords({ kind: "mystery", value: "7", why: "" })).toBe("mystery 7");
  });
});

describe("sideSummary", () => {
  it("is 'not run' and neutral when there is no comparison", () => {
    expect(sideSummary(null)).toEqual({ text: "not run", tone: "none" });
  });

  it("is good when every try passed, bad when none did, and a warning in between", () => {
    expect(sideSummary(attempt([true, true]))).toEqual({ text: "passed 2 of 2", tone: "ok" });
    expect(sideSummary(attempt([false, false]))).toEqual({ text: "passed 0 of 2", tone: "bad" });
    expect(sideSummary(attempt([true, false, true]))).toEqual({ text: "passed 2 of 3", tone: "warn" });
  });
});

describe("failureLines", () => {
  it("lists each failed check once, in the order they were found", () => {
    const a = attempt([false, false, true], [["the first line is 54 characters, the limit is 50"], ["the first line is 54 characters, the limit is 50", "the reply does not match the pattern x"]]);
    expect(failureLines(a)).toEqual(["the first line is 54 characters, the limit is 50", "the reply does not match the pattern x"]);
  });

  it("is empty when everything passed or there is no attempt", () => {
    expect(failureLines(attempt([true, true]))).toEqual([]);
    expect(failureLines(null)).toEqual([]);
  });
});

describe("progressText", () => {
  it("counts the test being run, never beyond the last", () => {
    expect(progressText({ done: 0, total: 3 })).toBe("Running test 1 of 3");
    expect(progressText({ done: 2, total: 3 })).toBe("Running test 3 of 3");
    expect(progressText({ done: 3, total: 3 })).toBe("Running test 3 of 3");
  });

  it("says it is starting when the number of tests is not known yet", () => {
    expect(progressText({ done: 0, total: 0 })).toBe("Starting");
  });
});

describe("a result against the latest version", () => {
  it("says nothing when the run tested the latest version, or the latest is not known", () => {
    expect(staleNote(2, 2)).toBeNull();
    expect(staleNote(2, undefined)).toBeNull();
  });

  it("says which version was tested and which is the latest when they differ", () => {
    const note = staleNote(1, 3);
    expect(note).toContain("v1");
    expect(note).toContain("v3");
  });
});

describe("versions in the address", () => {
  const versions = [{ version: 3 }, { version: 2 }, { version: 1 }];

  it("takes the version asked for when it exists, and the latest otherwise", () => {
    expect(pickVersion(versions, 2)).toBe(2);
    expect(pickVersion(versions, 9)).toBe(3);
    expect(pickVersion(versions, undefined)).toBe(3);
    expect(pickVersion([], 2)).toBeUndefined();
  });

  it("reads a version from text only when it is a whole number above zero", () => {
    expect(parseVersion("2")).toBe(2);
    expect(parseVersion("0")).toBeUndefined();
    expect(parseVersion("-1")).toBeUndefined();
    expect(parseVersion("2.5")).toBeUndefined();
    expect(parseVersion("two")).toBeUndefined();
    expect(parseVersion(null)).toBeUndefined();
  });
});

describe("the history line", () => {
  const run = (summary: EvalRunSummary["summary"]): EvalRunSummary => ({
    id: "a".repeat(32), status: "done", kind: "skill", name: "s", version: 2, tag: "v2", content_hash: "h", runs: 1, baseline: true,
    progress: { done: 3, total: 3 }, error: "", retryable: false, created_at: "t", updated_at: "t", summary,
  });

  it("gives the outcome and both counts", () => {
    expect(runLine(run({ outcome: "helped", with_skill: { passed: 3, total: 3 }, baseline: { passed: 1, total: 3 }, calls: 6 }))).toBe(
      "the skill helped · with the skill 3/3 · without it 1/3",
    );
  });

  it("leaves out the comparison when there was none", () => {
    expect(runLine(run({ outcome: "with_only", with_skill: { passed: 2, total: 3 }, baseline: null, calls: 3 }))).toBe("no comparison · with the skill 2/3");
  });

  it("says what a run that did not finish is", () => {
    expect(runLine({ ...run(null), status: "working" })).toBe("still running");
    expect(runLine({ ...run(null), status: "failed" })).toBe("failed");
  });

  it("has a label for every outcome", () => {
    for (const o of ["helped", "adds_nothing", "no_difference", "worse", "too_few", "with_only", "not_run"] as const) expect(outcomeLabel(o).length).toBeGreaterThan(3);
  });
});
