import { describe, expect, it } from "vitest";
import {
  blankCase, blankCheck, caseProblems, CASE_KINDS, CHECK_KINDS, fromServer, isNumericKind, sameCases, toBody, type DraftCase,
} from "./cases";
import type { CaseDoc, CasesView } from "./types";

const LIMITS: CasesView["limits"] = { max_cases: 30, max_checks: 3, max_name: 80, max_message: 4000, max_value: 500, max_why: 200, max_covers: 100, max_cover: 120 };

const good = (over: Partial<DraftCase> = {}): DraftCase => ({
  key: "k1", name: "short change", kind: "positive", message: "fixed the login button", covers: [],
  checks: [{ kind: "first_line_max_chars", value: "50", why: "short title" }], ...over,
});

const doc = (over: Partial<CaseDoc> = {}): CaseDoc => ({
  name: "short change", kind: "positive", message: "fixed the login button", covers: ["AC1"], runnable: true,
  checks: [{ kind: "first_line_max_chars", value: "50", why: "short title" }], ...over,
});

describe("caseProblems", () => {
  it("has nothing to say about a well-formed case", () => {
    expect(caseProblems([good()], LIMITS)).toEqual([]);
  });

  it("asks for at least one case", () => {
    expect(caseProblems([], LIMITS)).toEqual(["Add at least one case, or leave the skill as it is."]);
  });

  it("names the case and says what is missing: a name, a message, a check", () => {
    const [p] = caseProblems([good({ name: " ", message: "", checks: [] })], LIMITS);
    expect(p).toMatch(/^Case 1: /);
    expect(p).toContain("needs a name");
    expect(p).toContain("needs a message to send");
    expect(p).toContain("needs at least one check");
  });

  it("names the case by its own name when it has one", () => {
    expect(caseProblems([good({ name: "empty one", message: "" })], LIMITS)[0]).toMatch(/^Case 1 \('empty one'\): /);
  });

  it("lists a problem for each case that has one and none for the others", () => {
    const problems = caseProblems([good({ message: "" }), good({ key: "k2", name: "fine" }), good({ key: "k3", name: "bad", checks: [] })], LIMITS);
    expect(problems).toHaveLength(2);
    expect(problems[0]).toMatch(/^Case 1/);
    expect(problems[1]).toMatch(/^Case 3/);
  });

  it("refuses a name used twice, ignoring case and spaces, and says which case has it too", () => {
    const [p] = caseProblems([good({ name: "A" }), good({ key: "k2", name: " a " })], LIMITS);
    expect(p).toMatch(/^Case 2/);
    expect(p).toContain("used twice");
    expect(p).toContain("Case 1");
  });

  it.each([
    ["max_chars", "fifty"],
    ["max_lines", "0"],
    ["first_line_max_chars", "12.5"],
    ["max_chars", "1000001"],
    ["max_lines", "-3"],
  ])("wants a whole number from 1 for %s, not '%s'", (kind, value) => {
    expect(caseProblems([good({ checks: [{ kind, value, why: "" }] })], LIMITS)[0]).toContain("whole number");
  });

  it("accepts the edges of the allowed numbers", () => {
    for (const value of ["1", "1000000"]) expect(caseProblems([good({ checks: [{ kind: "max_chars", value, why: "" }] })], LIMITS)).toEqual([]);
  });

  it("wants a value for a text check, and a pattern no longer than 80 characters", () => {
    expect(caseProblems([good({ checks: [{ kind: "contains", value: "  ", why: "" }] })], LIMITS)[0]).toContain("has no value");
    expect(caseProblems([good({ checks: [{ kind: "regex", value: "a".repeat(81), why: "" }] })], LIMITS)[0]).toContain("80 characters");
    expect(caseProblems([good({ checks: [{ kind: "regex", value: "a".repeat(80), why: "" }] })], LIMITS)).toEqual([]);
  });

  it("allows exactly the largest sizes the server allows", () => {
    const three = Array.from({ length: 3 }, (_, i) => ({ kind: "contains", value: `v${i}`, why: "" }));
    expect(caseProblems([good({ name: "x".repeat(80), message: "m".repeat(4000), checks: three })], LIMITS)).toEqual([]);
    expect(caseProblems([good({ checks: [{ kind: "contains", value: "x".repeat(500), why: "" }] })], LIMITS)).toEqual([]);
    const thirty = Array.from({ length: 30 }, (_, i) => good({ key: `k${i}`, name: `case ${i}` }));
    expect(caseProblems(thirty, LIMITS)).toEqual([]);
  });

  it("says when a reason for a check is longer than the server keeps, instead of letting the save fail with no explanation", () => {
    expect(caseProblems([good({ checks: [{ kind: "contains", value: "x", why: "w".repeat(200) }] })], LIMITS)).toEqual([]);
    const [p] = caseProblems([good({ checks: [{ kind: "contains", value: "x", why: "w".repeat(201) }] })], LIMITS);
    expect(p).toContain("reason");
    expect(p).toContain("200 characters");
  });

  it("says when the criteria a case cites (which the editor cannot change) are more than the server keeps", () => {
    expect(caseProblems([good({ covers: Array.from({ length: 100 }, (_, i) => `AC${i}`) })], LIMITS)).toEqual([]);
    expect(caseProblems([good({ covers: Array.from({ length: 101 }, (_, i) => `AC${i}`) })], LIMITS)[0]).toContain("at most 100 criteria");
    expect(caseProblems([good({ covers: ["A".repeat(121)] })], LIMITS)[0]).toContain("120 characters");
  });

  it("keeps to the server's sizes", () => {
    expect(caseProblems([good({ name: "x".repeat(81) })], LIMITS)[0]).toContain("80 characters");
    expect(caseProblems([good({ message: "x".repeat(4001) })], LIMITS)[0]).toContain("4000 characters");
    expect(caseProblems([good({ checks: [{ kind: "contains", value: "x".repeat(501), why: "" }] })], LIMITS)[0]).toContain("500 characters");
    const four = Array.from({ length: 4 }, (_, i) => ({ kind: "contains", value: `v${i}`, why: "" }));
    expect(caseProblems([good({ checks: four })], LIMITS)[0]).toContain("at most 3 checks");
    const many = Array.from({ length: 31 }, (_, i) => good({ key: `k${i}`, name: `case ${i}` }));
    expect(caseProblems(many, LIMITS)[0]).toContain("at most 30 cases");
  });
});

describe("the request", () => {
  it("sends only what the server reads, with every text trimmed", () => {
    const body = toBody(3, [good({ name: "  short change ", message: "  hi  ", checks: [{ kind: "contains", value: " x ", why: " why " }] })], " my note ");
    expect(body).toEqual({
      base_version: 3, note: "my note",
      cases: [{ name: "short change", kind: "positive", message: "hi", covers: [], checks: [{ kind: "contains", value: "x", why: "why" }] }],
    });
  });

  it("keeps the criteria a case covers, as they were", () => {
    expect(toBody(1, [good({ covers: ["AC1", "AC2"] })], "").cases[0].covers).toEqual(["AC1", "AC2"]);
  });
});

describe("reading what the server has", () => {
  it("makes a draft of each case with its own key, keeping every field", () => {
    const drafts = fromServer([doc(), doc({ name: "second", covers: [] })]);
    expect(drafts.map((d) => d.name)).toEqual(["short change", "second"]);
    expect(new Set(drafts.map((d) => d.key)).size).toBe(2);
    expect(drafts[0]).toMatchObject({ kind: "positive", message: "fixed the login button", covers: ["AC1"], checks: [{ kind: "first_line_max_chars", value: "50", why: "short title" }] });
  });

  it("does not share the server's objects, so editing a draft never changes what was loaded", () => {
    const original = doc();
    const [draft] = fromServer([original]);
    draft.checks[0].value = "99";
    draft.covers.push("AC9");
    expect(original.checks[0].value).toBe("50");
    expect(original.covers).toEqual(["AC1"]);
  });

  it("keeps a case that could not be run as it is, empty, so it can be fixed", () => {
    const [draft] = fromServer([doc({ message: "", checks: [], runnable: false })]);
    expect(draft.message).toBe("");
    expect(draft.checks).toEqual([]);
    expect(caseProblems([draft], LIMITS)[0]).toContain("needs a message to send");
  });
});

describe("sameCases", () => {
  it("is true for the same cases, whatever their keys", () => {
    expect(sameCases([good({ key: "a" })], [good({ key: "b" })])).toBe(true);
  });

  it("notices a changed message, name, kind, check, criterion, a removed case and a reordering", () => {
    const base = [good({ key: "a" }), good({ key: "b", name: "second" })];
    expect(sameCases(base, [base[0], { ...base[1], message: "other" }])).toBe(false);
    expect(sameCases(base, [{ ...base[0], name: "renamed" }, base[1]])).toBe(false);
    expect(sameCases(base, [{ ...base[0], kind: "edge" }, base[1]])).toBe(false);
    expect(sameCases(base, [{ ...base[0], checks: [{ kind: "contains", value: "x", why: "" }] }, base[1]])).toBe(false);
    expect(sameCases(base, [{ ...base[0], covers: ["AC1"] }, base[1]])).toBe(false);
    expect(sameCases(base, [base[0]])).toBe(false);
    expect(sameCases(base, [base[1], base[0]])).toBe(false);
  });

  it("ignores spaces around texts, which the server trims too", () => {
    expect(sameCases([good()], [good({ name: " short change ", message: " fixed the login button " })])).toBe(true);
  });
});

describe("the choices a person is offered", () => {
  it("offers the seven checks the harness can run, and says which take a number", () => {
    expect(CHECK_KINDS.map((k) => k.kind)).toEqual(["contains", "not_contains", "starts_with", "regex", "max_chars", "max_lines", "first_line_max_chars"]);
    expect(CHECK_KINDS.filter((k) => k.numeric).map((k) => k.kind)).toEqual(["max_chars", "max_lines", "first_line_max_chars"]);
    expect(isNumericKind("max_lines")).toBe(true);
    expect(isNumericKind("contains")).toBe(false);
    expect(isNumericKind("mystery")).toBe(false);
  });

  it("offers the three kinds of case", () => {
    expect(CASE_KINDS.map((k) => k.kind)).toEqual(["positive", "negative", "edge"]);
  });

  it("starts a new case with one empty check, and every new case has a key of its own", () => {
    const first = blankCase();
    expect(first).toMatchObject({ name: "", kind: "positive", message: "", covers: [] });
    expect(first.checks).toEqual([blankCheck()]);
    expect(blankCase().key).not.toBe(first.key);
  });
});
