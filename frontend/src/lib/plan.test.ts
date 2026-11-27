import { describe, expect, it } from "vitest";
import {
  budgetProblem, budgetSentence, buildPlanRequest, EMPTY_FORM, formProblem, gapGroups, gapSource, modelLine, namedCode, notReadText, readLine, sensitiveList,
  sensitiveProblem, sentSummary, signalLine, taskProblem, tierSentence, type PlanForm,
} from "./plan";
import type { PlanGap, PlanReadItem, PlanTokens, TaskPlan } from "./types";

const form = (over: Partial<PlanForm> = {}): PlanForm => ({ ...EMPTY_FORM, task: "Add a --json option to the library list command.", ...over });

const tokens = (over: Partial<PlanTokens> = {}): PlanTokens => ({
  budget: 100000, reads: [], dropped: [], read_total: 30665, whole_files_total: 30665, create: [], create_total: 0, fits_budget: true, method: "graph slices", ...over,
});

const plan = (over: Partial<TaskPlan> = {}): TaskPlan => ({
  created_at: "2026-11-27T10:00:00+00:00", prompt: "x", mode: "model", model: "gemini/some-model", repo: "shop", model_calls: 2, markdown: "# Task plan", source: { kind: "folder" },
  reading: { task_type: "feature", summary: "s", stated: [], constraints: [], out_of_scope: [], declared_risks: [], gaps: [], assumptions: [] },
  mentions: [], tier: { tier: 2, baseline: 2, signals: [], measured: true, note: "" }, tier_name: "Feature or refactor", phases: [], stop_triggers: [], rules: [], rules_found: 0,
  token_plan: tokens(), notes: [], not_checked: [], ...over,
});

describe("taskProblem", () => {
  it("says nothing about an empty box (the button is simply off) and nothing about a task that can be planned", () => {
    expect(taskProblem("")).toBeNull();
    expect(taskProblem("   ")).toBeNull();
    expect(taskProblem("Fix the login bug today")).toBeNull();
  });

  it("asks for at least a sentence when there are fewer than three words or ten characters, as the server does", () => {
    expect(taskProblem("fix it")).toBe("Describe the task in at least a sentence.");
    expect(taskProblem("a b c")).toBe("Describe the task in at least a sentence."); // three words, but under ten characters
    expect(taskProblem("Refactoring")).toBe("Describe the task in at least a sentence.");
    expect(taskProblem("abcd efgh ij")).toBeNull();
  });

  it("draws the line at three words and ten characters exactly", () => {
    expect(taskProblem("ab cd efg")).not.toBeNull(); // three words, nine characters
    expect(taskProblem("ab cd efgh")).toBeNull(); // three words, ten characters
    expect(taskProblem("abcdefghij kl")).not.toBeNull(); // many characters, two words
  });

  it("refuses a task over 8,000 characters and says how long it may be", () => {
    expect(taskProblem(`${"a".repeat(7997)} b c`)).not.toBeNull(); // 8,001 characters: one too many
    expect(taskProblem(`${"a".repeat(7996)} b c`)).toBeNull(); // exactly 8,000
    expect(taskProblem("word ".repeat(1600))).toBeNull(); // exactly 8,000
    expect(taskProblem("word ".repeat(1601))).toContain("8,000");
  });
});

describe("budgetProblem", () => {
  it("accepts a blank box and a whole number of tokens", () => {
    expect(budgetProblem("")).toBeNull();
    expect(budgetProblem(" 50000 ")).toBeNull();
    expect(budgetProblem("10000000")).toBeNull();
  });

  it("refuses anything else in plain words", () => {
    for (const bad of ["0", "-5", "1.5", "1.", "1e3", "0x10", "lots", "10000001", "5k"]) expect(budgetProblem(bad), bad).toContain("whole number");
  });
});

describe("sensitiveList and sensitiveProblem", () => {
  it("splits on commas and lines, trims, drops empties and repeats, and keeps the order", () => {
    expect(sensitiveList(" src/auth/** , migrations/*\n\n src/auth/** ,billing/*,, ")).toEqual(["src/auth/**", "migrations/*", "billing/*"]);
    expect(sensitiveList("")).toEqual([]);
  });

  it("allows ten patterns of 200 characters and no more", () => {
    expect(sensitiveProblem(Array.from({ length: 10 }, (_, i) => `p${i}`).join(","))).toBeNull();
    expect(sensitiveProblem(Array.from({ length: 11 }, (_, i) => `p${i}`).join(","))).toContain("10");
    expect(sensitiveProblem("x".repeat(200))).toBeNull();
    expect(sensitiveProblem("x".repeat(201))).toContain("200");
  });
});

describe("formProblem", () => {
  it("is the first thing wrong with the form, in the order the form is read, and null when nothing is", () => {
    expect(formProblem(form())).toBeNull();
    expect(formProblem(form({ task: "fix it", budget: "lots" }))).toBe("Describe the task in at least a sentence.");
    expect(formProblem(form({ repo: "relative/folder" }))).toContain("full path");
    expect(formProblem(form({ repo: "https://example.com/x" }))).toContain("GitHub");
    expect(formProblem(form({ budget: "lots" }))).toContain("whole number");
    expect(formProblem(form({ sensitive: "x".repeat(201) }))).toContain("200");
  });

  it("reads the boxes top to bottom: the folder before the budget before the patterns", () => {
    expect(formProblem(form({ repo: "relative/folder", budget: "lots", sensitive: "x".repeat(201) }))).toContain("full path");
    expect(formProblem(form({ budget: "lots", sensitive: "x".repeat(201) }))).toContain("whole number");
  });

  it("accepts a folder path, a GitHub link and an empty repository box", () => {
    expect(formProblem(form({ repo: "" }))).toBeNull();
    expect(formProblem(form({ repo: "C:\\code\\shop" }))).toBeNull();
    expect(formProblem(form({ repo: "https://github.com/owner/repo" }))).toBeNull();
  });
});

describe("buildPlanRequest", () => {
  it("sends the task trimmed and nothing for what was left on automatic", () => {
    expect(buildPlanRequest(form({ task: "  Add a --json option to the list command.  " }))).toEqual({
      task: "Add a --json option to the list command.", repo: null, no_ai: false, kind: null, tier: null, budget: null, sensitive: [],
    });
  });

  it("sends what was chosen: the repository trimmed, the kind, a raised tier, a budget and the patterns", () => {
    expect(buildPlanRequest(form({ repo: " C:\\code\\shop ", noAi: true, kind: "bugfix", tier: "3", budget: " 8000 ", sensitive: "a/*, b/*" }))).toEqual({
      task: "Add a --json option to the library list command.", repo: "C:\\code\\shop", no_ai: true, kind: "bugfix", tier: 3, budget: 8000, sensitive: ["a/*", "b/*"],
    });
  });

  it("treats tier 0 as a choice and not as automatic", () => {
    expect(buildPlanRequest(form({ tier: "0" })).tier).toBe(0);
  });
});

describe("sentSummary", () => {
  it("says nothing is sent when no model is used", () => {
    expect(sentSummary(form({ noAi: true, repo: "C:\\code\\shop" }))).toBe("Nothing is sent to a model. Only what the code can measure is planned.");
  });

  it("says what a model sees without a repository: the task text and nothing else", () => {
    expect(sentSummary(form())).toBe("Sent to the model: your task text.");
  });

  it("says what a model sees with a folder: names and places, never contents", () => {
    expect(sentSummary(form({ repo: "C:\\code\\shop" }))).toBe(
      "Sent to the model: your task text, the names and places (not the contents) of the files and functions it mentions, file and language counts, and the lines of the repository's CLAUDE.md / AGENTS.md.",
    );
  });

  it("says a GitHub copy has no rule files to send", () => {
    const s = sentSummary(form({ repo: "https://github.com/owner/repo" }));
    expect(s).toContain("names and places (not the contents)");
    expect(s).toContain("A GitHub copy has no CLAUDE.md or AGENTS.md");
    expect(s).not.toContain("the lines of the repository's");
  });
});

describe("the plan's own wording", () => {
  it("names the tier, its name and where it started", () => {
    expect(tierSentence(plan())).toBe("Tier 2: Feature or refactor (starting point for this kind of task: 2)");
    expect(tierSentence(plan({ tier: { tier: 3, baseline: 1, signals: [], measured: true, note: "" }, tier_name: "Complex or risky" }))).toBe("Tier 3: Complex or risky (starting point for this kind of task: 1)");
  });

  it("writes a signal as its name, the lowest tier it allows and its evidence", () => {
    expect(signalLine({ name: "sensitive code", floor: 3, evidence: "src/auth.py matches a sensitive path" })).toBe("sensitive code: tier 3+ — src/auth.py matches a sensitive path");
  });

  it("writes a slice with its lines and a file as a whole file", () => {
    const item = (over: Partial<PlanReadItem>): PlanReadItem => ({ kind: "slice", path: "cli.py", symbol: "_run_library", lines: "890-940", tokens: 890, whole_file_tokens: 9000, why: "named", priority: 1, ...over });
    expect(readLine(item({}))).toBe("cli.py · _run_library lines 890-940");
    expect(readLine(item({ kind: "file", symbol: "", lines: "" }))).toBe("cli.py (whole file)");
  });

  it("says the budget, the planned reading, what whole files would cost, and whether everything fitted", () => {
    expect(budgetSentence(tokens())).toBe("Budget to read: 100,000 tokens. Planned reading: 30,665. Everything planned fits the budget.");
    expect(budgetSentence(tokens({ whole_files_total: 60000 }))).toContain("(the same files read whole would cost about 60,000)");
    expect(budgetSentence(tokens({ fits_budget: false }))).toContain("Not everything fits");
  });

  it("puts the questions that block first and keeps the order inside each group", () => {
    const gap = (question: string, blocking: boolean): PlanGap => ({ question, why: "w", blocking, source: "model" });
    const groups = gapGroups([gap("a", false), gap("b", true), gap("c", false), gap("d", true)]);
    expect(groups.blocking.map((g) => g.question)).toEqual(["b", "d"]);
    expect(groups.other.map((g) => g.question)).toEqual(["a", "c"]);
  });

  it("says who found a question", () => {
    expect(gapSource({ question: "q", why: "w", blocking: true, source: "code" })).toBe("found by the code graph");
    expect(gapSource({ question: "q", why: "w", blocking: true, source: "model" })).toBe("asked by the model");
  });

  it("lists the code the request names with its place, and leaves out a name that matched several places", () => {
    const m = (text: string, over = {}) => ({ kind: "symbol" as const, text, target: `f.py::${text}`, file: "f.py", line: 4, candidates: 1, ambiguous: false, source: "prompt" as const, options: [], ...over });
    expect(namedCode(plan({ mentions: [m("parse_config"), m("main", { line: null }), m("build", { ambiguous: true, candidates: 3 })] }))).toEqual(["parse_config → f.py:4", "main → f.py"]);
  });

  it("says when a model read the request and how many calls it took, and when none did", () => {
    expect(modelLine(plan())).toBe("Read by gemini/some-model · 2 model calls · repository shop");
    expect(modelLine(plan({ model_calls: 1, repo: "" }))).toBe("Read by gemini/some-model · 1 model call");
    expect(modelLine(plan({ mode: "facts only", model: "", model_calls: 0 }))).toBe("No model was used (facts only) · repository shop");
  });

  it("says plainly that a plan made without a model did not read the request", () => {
    const text = notReadText(plan({ mode: "facts only" }));
    expect(text).toContain("Not read.");
    expect(text).toContain("No model was used");
    expect(text).toContain("feature");
  });
});
