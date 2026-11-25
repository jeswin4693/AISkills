import type { EvalAttempt, EvalBlocker, EvalCheckSpec, EvalOutcome, EvalRunSummary } from "./types";

/**
 * The Testing Lab's decisions, kept out of the components so they can be tested without a browser: how an outcome is worded and toned, what a run
 * costs, what to tell a person whose skill cannot be run, and how a check reads in words. The server decides the outcome as a code; nothing here
 * parses its sentence.
 */

export type Tone = "ok" | "warn" | "bad" | "info";

export interface OutcomeInfo {
  tone: Tone;
  title: string;
  text: string;
}

/** The headline of a finished run. "Nothing was run" and "too few" are never worded as a pass. */
export function outcomeInfo(outcome: EvalOutcome, o: { skillTokens: number; cases: number; minCases: number }): OutcomeInfo {
  switch (outcome) {
    case "helped":
      return { tone: "ok", title: "The skill helped", text: "The model passed more tests with the skill than it did without it. The tests it fixed are where the skill earns its tokens." };
    case "adds_nothing":
      return {
        tone: "warn",
        title: "The skill adds nothing on these tests",
        text: `The model passed every test without it too, so the skill's ${o.skillTokens} tokens are paid each time it is used for nothing these tests can see.`,
      };
    case "no_difference":
      return { tone: "info", title: "No difference on these tests", text: "The model did equally well with the skill and without it." };
    case "worse":
      return {
        tone: "bad",
        title: "The skill made it worse",
        text: "The model passed fewer tests with the skill than without it. Read the failed checks below: it may be a weak test or a weak skill.",
      };
    case "too_few":
      return {
        tone: "info",
        title: "Too few test cases to say",
        text: `Only ${o.cases} test case${o.cases === 1 ? "" : "s"} could be run. At least ${o.minCases} are needed before this says whether the skill helps.`,
      };
    case "with_only":
      return {
        tone: "info",
        title: "Run without the comparison",
        text: "This shows how the skill did, not whether it helped. Run it again with the comparison ticked to see what the model does without the skill.",
      };
    case "not_run":
      return { tone: "warn", title: "Nothing was run", text: "No test case could be run, so there is no result." };
  }
}

/** A few words for a list of earlier runs. */
export function outcomeLabel(outcome: EvalOutcome): string {
  return {
    helped: "the skill helped",
    adds_nothing: "the skill adds nothing",
    no_difference: "no difference",
    worse: "the skill made it worse",
    too_few: "too few cases to say",
    with_only: "no comparison",
    not_run: "nothing ran",
  }[outcome];
}

/** One model call per case, per repeat, per condition (with the skill, and without it when the comparison is asked for). */
export const callsFor = (cases: number, runs: number, baseline: boolean): number => cases * runs * (baseline ? 2 : 1);

export const costText = (calls: number): string => `${calls} model ${calls === 1 ? "call" : "calls"}`;

/** The repeat counts offered: only those the server allows. */
export function runChoices(maxRuns: number): number[] {
  const choices = [1, 3, 5].filter((n) => n <= maxRuns);
  return choices.length ? choices : [1];
}

/** Models vary from run to run, so a single repeat of each test can mislead. */
export function repeatNote(runs: number): string | null {
  return runs < 3 ? "Models vary from run to run, so one repeat of each test can mislead. Repeat 3 times before trusting a small difference." : null;
}

/** What a person can do when a skill cannot be run. Only what exists today: the advice never points at a button that is not there. */
export function blockerAdvice(blocker: EvalBlocker): string {
  switch (blocker) {
    case "needs_tools":
      return "Install it and use it for real: that is the test that matters for a skill like this.";
    case "no_cases":
      return "It has no test cases yet. Build it again in the Builder (a built skill comes with test cases), or add a tests/cases.json to it and import it as a new version.";
    case "nothing_runnable":
      return "Its test cases have no message to send or no check to run (they were saved before test cases could be run). Build it again in the Builder, or add messages and checks and import it as a new version.";
    default:
      return "";
  }
}

/** A check as a person would say it. An unknown kind is shown as it is, never hidden. */
export function checkWords(c: EvalCheckSpec): string {
  switch (c.kind) {
    case "contains":
      return `contains "${c.value}"`;
    case "not_contains":
      return `does not contain "${c.value}"`;
    case "starts_with":
      return `starts with "${c.value}"`;
    case "regex":
      return `matches the pattern ${c.value}`;
    case "max_chars":
      return `is at most ${c.value} characters`;
    case "max_lines":
      return `is at most ${c.value} lines`;
    case "first_line_max_chars":
      return `has a first line of at most ${c.value} characters`;
    default:
      return `${c.kind} ${c.value}`;
  }
}

export interface Side {
  text: string;
  tone: "ok" | "warn" | "bad" | "none";
}

/** How one side of a case (with the skill, or without it) went. */
export function sideSummary(a: EvalAttempt | null): Side {
  if (!a || a.runs === 0) return { text: "not run", tone: "none" };
  const tone = a.passed === a.runs ? "ok" : a.passed === 0 ? "bad" : "warn";
  return { text: `passed ${a.passed} of ${a.runs}`, tone };
}

/** Each failed check once, as the server worded it, in the order they were found. */
export function failureLines(a: EvalAttempt | null): string[] {
  const out: string[] = [];
  for (const t of a?.tries ?? []) {
    for (const c of t.checks) if (!c.passed && c.detail && !out.includes(c.detail)) out.push(c.detail);
  }
  return out;
}

export function progressText(p: { done: number; total: number }): string {
  return p.total > 0 ? `Running test ${Math.min(p.done + 1, p.total)} of ${p.total}` : "Starting";
}

/** A run is about the version it tested. When a newer one exists, the page says the run does not speak for it. */
export function staleNote(runVersion: number, latest: number | undefined): string | null {
  if (latest === undefined || latest <= runVersion) return null;
  return `This run tested v${runVersion}. The latest version is v${latest}, and this run says nothing about it.`;
}

/** The version to show: the one asked for when it exists, otherwise the latest (undefined when there are none). */
export function pickVersion(versions: { version: number }[], wanted: number | undefined): number | undefined {
  if (wanted !== undefined && versions.some((v) => v.version === wanted)) return wanted;
  return versions.length ? Math.max(...versions.map((v) => v.version)) : undefined;
}

/** A version from the address: a whole number above zero, or nothing. */
export function parseVersion(text: string | null): number | undefined {
  return text !== null && /^[1-9]\d{0,6}$/.test(text) ? Number(text) : undefined;
}

/** One line for the list of earlier runs. */
export function runLine(r: EvalRunSummary): string {
  if (r.status === "working") return "still running";
  if (r.status === "failed") return "failed";
  if (!r.summary) return "no result";
  const s = r.summary;
  const base = s.baseline ? ` · without it ${s.baseline.passed}/${s.baseline.total}` : "";
  return `${outcomeLabel(s.outcome)} · with the skill ${s.with_skill.passed}/${s.with_skill.total}${base}`;
}
