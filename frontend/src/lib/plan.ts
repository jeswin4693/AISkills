import { plural } from "./format";
import { isLinkLike, pathProblem } from "./repository";
import type { PlanGap, PlanKind, PlanReadItem, PlanRequest, PlanTokens, TaskPlan } from "./types";

// The Task Plan page's own logic. The plan itself is made by the server (the same code the command line runs); this only checks the form before
// anything is sent, says what would be sent, and words what comes back in the order the command prints it.

export const MAX_TASK = 8000;
export const MAX_SENSITIVE = 10;
export const MAX_SENSITIVE_LENGTH = 200;
export const MAX_BUDGET = 10_000_000;

/** The form as the person fills it in: every field is text, because that is what a box holds. "" means "work it out" for the kind and the tier. */
export interface PlanForm {
  task: string;
  repo: string;
  noAi: boolean;
  kind: string;
  tier: string;
  budget: string;
  sensitive: string;
}

export const EMPTY_FORM: PlanForm = { task: "", repo: "", noAi: false, kind: "", tier: "", budget: "", sensitive: "" };

export const KINDS: { value: PlanKind; label: string }[] = [
  { value: "feature", label: "A new feature" },
  { value: "bugfix", label: "A bug fix" },
  { value: "refactor", label: "A refactor" },
  { value: "migration", label: "A migration" },
  { value: "docs", label: "Documentation" },
  { value: "investigation", label: "An investigation" },
  { value: "other", label: "Something else" },
];

const n = (x: number): string => x.toLocaleString("en-US");

// ---- the form ------------------------------------------------------------------------------------------------

/** What is wrong with the task, or null when it can be planned (or the box is empty: the button is simply off). The server's own rule: at least three
 * words and ten characters. */
export function taskProblem(task: string): string | null {
  const words = task.trim();
  if (!words) return null;
  if (words.length > MAX_TASK) return `The task is too long: ${n(MAX_TASK)} characters at most (it is ${n(words.length)}).`;
  if (words.split(/\s+/).length < 3 || words.length < 10) return "Describe the task in at least a sentence.";
  return null;
}

export function budgetProblem(text: string): string | null {
  const t = text.trim();
  if (!t) return null;
  const value = /^\d+$/.test(t) ? Number(t) : Number.NaN;
  return Number.isInteger(value) && value >= 1 && value <= MAX_BUDGET ? null : `Give the budget as a whole number of tokens between 1 and ${n(MAX_BUDGET)}, such as 50000.`;
}

/** The path patterns of the box: separated by commas or lines, trimmed, without empties or repeats, in the order written. */
export function sensitiveList(text: string): string[] {
  return [...new Set(text.split(/[,\n]/).map((s) => s.trim()).filter(Boolean))];
}

export function sensitiveProblem(text: string): string | null {
  const list = sensitiveList(text);
  if (list.length > MAX_SENSITIVE) return `Give at most ${MAX_SENSITIVE} path patterns (there are ${list.length}).`;
  if (list.some((s) => s.length > MAX_SENSITIVE_LENGTH)) return `A path pattern can be at most ${MAX_SENSITIVE_LENGTH} characters.`;
  return null;
}

/** The first thing wrong with the form, in the order it is read, or null. The server checks everything again; this spares a round trip. */
export function formProblem(form: PlanForm): string | null {
  return taskProblem(form.task) ?? pathProblem(form.repo) ?? budgetProblem(form.budget) ?? sensitiveProblem(form.sensitive);
}

/** What is sent: the task trimmed, and nothing (null) for what was left on automatic. A tier of 0 is a choice, not automatic. */
export function buildPlanRequest(form: PlanForm): PlanRequest {
  const repo = form.repo.trim();
  const budget = form.budget.trim();
  return {
    task: form.task.trim(),
    repo: repo || null,
    no_ai: form.noAi,
    kind: (form.kind || null) as PlanKind | null,
    tier: form.tier === "" ? null : Number(form.tier),
    budget: budget ? Number(budget) : null,
    sensitive: sensitiveList(form.sensitive),
  };
}

/** What would leave this computer if the person pressed the button, said before anything is sent (the command prints the same sentence). */
export function sentSummary(form: PlanForm): string {
  if (form.noAi) return "Nothing is sent to a model. Only what the code can measure is planned.";
  const repo = form.repo.trim();
  if (!repo) return "Sent to the model: your task text.";
  const seen = "Sent to the model: your task text, the names and places (not the contents) of the files and functions it mentions, file and language counts";
  return isLinkLike(repo) ? `${seen}. A GitHub copy has no CLAUDE.md or AGENTS.md, so no rule lines are sent.` : `${seen}, and the lines of the repository's CLAUDE.md / AGENTS.md.`;
}

// ---- the plan, in the order the command prints it ---------------------------------------------------------------

export function modelLine(plan: TaskPlan): string {
  const parts = [plan.mode === "model" ? `Read by ${plan.model}` : "No model was used (facts only)"];
  if (plan.mode === "model") parts.push(plural(plan.model_calls, "model call"));
  if (plan.repo) parts.push(`repository ${plan.repo}`);
  return parts.join(" · ");
}

/** The words for a plan made without a model: the request was not read, and that is said, never shown as an empty "nothing stated". */
export function notReadText(plan: TaskPlan): string {
  return `Not read. No model was used, so what the request asks for, the rules and limits in it, and what it leaves out were not worked out. Kind of task, as you gave it: ${plan.reading.task_type}.`;
}

/** The code the request names and the graph found, each with its place. A name that matched several places is not listed here: it is a question. */
export function namedCode(plan: TaskPlan): string[] {
  return plan.mentions.filter((m) => !m.ambiguous).map((m) => `${m.text} → ${m.file}${m.line ? `:${m.line}` : ""}`);
}

/** The questions that block the work first, each group in the order given. */
export function gapGroups(gaps: PlanGap[]): { blocking: PlanGap[]; other: PlanGap[] } {
  return { blocking: gaps.filter((g) => g.blocking), other: gaps.filter((g) => !g.blocking) };
}

export function gapSource(gap: PlanGap): string {
  return gap.source === "code" ? "found by the code graph" : "asked by the model";
}

export function tierSentence(plan: TaskPlan): string {
  return `Tier ${plan.tier.tier}: ${plan.tier_name} (starting point for this kind of task: ${plan.tier.baseline})`;
}

export function signalLine(s: { name: string; floor: number; evidence: string }): string {
  return `${s.name}: tier ${s.floor}+ — ${s.evidence}`;
}

export function readLine(item: PlanReadItem): string {
  return item.kind === "slice" ? `${item.path} · ${item.symbol} lines ${item.lines}` : `${item.path} (whole file)`;
}

/** The budget, what the plan reads, what the same files read whole would cost, and whether everything fitted. All of it is an estimate. */
export function budgetSentence(tp: PlanTokens): string {
  let s = `Budget to read: ${n(tp.budget)} tokens. Planned reading: ${n(tp.read_total)}`;
  if (tp.whole_files_total > tp.read_total) s += ` (the same files read whole would cost about ${n(tp.whole_files_total)})`;
  return s + (tp.fits_budget ? ". Everything planned fits the budget." : ". Not everything fits: some context is left out (see Not planned).");
}
