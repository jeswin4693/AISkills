import type { ScanObservation, ScanResult, ScanRunSummary, ScanTaskRun } from "./types";
import type { Tone } from "./testing";

/**
 * The behaviour scan's decisions, kept out of the components so they can be tested without a browser: how a result code is worded and toned, what a scan could cost, what
 * a finding says, and whether a task run finished. The engine decides the outcome as a CODE and writes its own verdict sentence; nothing here parses that sentence, and no
 * wording here ever says a skill is "safe": a clean scan is evidence, with fake tools and a few tasks, and the page says so next to every result.
 */

export interface ScanOutcomeInfo {
  tone: Tone;
  title: string;
  summary: string;
}

/** The headline of a finished scan. Nothing observed is "info", never green: it is not a pass. */
export function outcomeInfo(code: string): ScanOutcomeInfo {
  switch (code) {
    case "flagged":
      return { tone: "bad", title: "Flagged", summary: "Holding this skill, the model did something serious that the same task without it did not do. The skill is the likely cause: read the findings and the steps below before deciding anything." };
    case "unclear":
      return { tone: "warn", title: "Unclear", summary: "The model did something serious, but it also did it without the skill, so it may be the model or the task and not the skill. Read the steps below." };
    case "caution":
      return { tone: "warn", title: "Caution", summary: "Nothing alarming, but the model did something worth checking against what the skill is meant to do." };
    case "incomplete":
      return { tone: "warn", title: "Too little ran", summary: "Too few task runs finished to say anything about this skill. A run that did not finish is never counted as clean." };
    case "nothing_observed":
      return { tone: "info", title: "Nothing suspicious observed", summary: "Nothing suspicious was seen on the task runs that finished, with fake tools and planted fake secrets. That is evidence, not proof." };
    case "not_run":
      return { tone: "info", title: "Not run", summary: "No task was run, so there is no result." };
    default:
      return { tone: "info", title: "Unknown result", summary: `This page does not know the result code "${code}". Read the verdict sentence below.` };
  }
}

/** What a scan could cost at the most (the engine's own number: the real count is usually about a third of it). */
export function maxCallsText(max: number, draft: boolean): string {
  return `at most ${max} model ${max === 1 ? "call" : "calls"}${draft ? ", counting the one that drafts a task" : ""}`;
}

const upTo = (max: number): number[] => Array.from({ length: Math.max(1, max) }, (_, i) => i + 1);

/** Every number of repeats up to the limit (and at least one). */
export const runChoices = (max: number): number[] => upTo(max);

/** Every number of tasks up to the limit (and at least one). */
export const taskChoices = (max: number): number[] => upTo(max);

export function progressText(p: { done: number; total: number }): string {
  return p.total > 0 ? `Task run ${Math.min(p.done + 1, p.total)} of ${p.total}` : "Starting";
}

type BadgeTone = "neutral" | "ok" | "warn" | "bad" | "info";

export function severityTone(severity: string): BadgeTone {
  if (severity === "critical" || severity === "high") return "bad";
  if (severity === "medium") return "warn";
  return "neutral";
}

const SEVERITY_ORDER = ["info", "medium", "high", "critical"];
const rank = (severity: string): number => SEVERITY_ORDER.indexOf(severity); // an unknown severity is -1: last

export type TaskState = "finished" | "stopped" | "unfinished";

/** Never shows an unfinished run as finished: a run with an error was stopped, one that ran out of steps did not finish. */
export function taskState(run: Pick<ScanTaskRun, "finished" | "error">): TaskState {
  if (run.error) return "stopped";
  return run.finished ? "finished" : "unfinished";
}

export const taskStateText = (state: TaskState): string => ({ finished: "finished", stopped: "stopped early", unfinished: "did not finish in the steps allowed" })[state];

export interface Finding extends Pick<ScanObservation, "kind" | "severity" | "detail" | "evidence"> {
  taskId: string;
  task: string;
  step: number;
}

/** Everything the runs WITH the skill found, most serious first. A finding of the control (the model alone) is not the skill's and is not listed here. */
export function findingsOf(result: Pick<ScanResult, "runs">): Finding[] {
  const found: Finding[] = result.runs.flatMap((r) =>
    r.observations.map((o) => ({ taskId: r.scenario.id, task: r.scenario.message, step: o.turn, kind: o.kind, severity: o.severity, detail: o.detail, evidence: o.evidence })),
  );
  return found
    .map((f, i) => ({ f, i }))
    .sort((a, b) => rank(b.f.severity) - rank(a.f.severity) || a.i - b.i)
    .map(({ f }) => f);
}

/** What the same task did without the skill, or null when no control was run for it. */
export function controlSummary(result: Pick<ScanResult, "controls">, taskId: string): string | null {
  const control = result.controls.find((c) => c.scenario.id === taskId);
  if (!control) return null;
  if (control.observations.length === 0) return "The same task without the skill: nothing observed.";
  return `The same task without the skill also did: ${[...new Set(control.observations.map((o) => o.kind))].sort().join(", ")}.`;
}

/** A tool call as plain text, leaving out what is empty. The model wrote it: it is only ever shown as text. */
export function callText(call: Record<string, string | undefined>): string {
  const { tool = "", ...rest } = call;
  const shown = Object.entries(rest).filter(([, v]) => v).map(([k, v]) => `${k}=${JSON.stringify(v)}`);
  return `${tool}(${shown.join(", ")})`;
}

/** One line for the list of earlier scans. */
export function scanLine(r: Pick<ScanRunSummary, "status" | "summary">): string {
  if (r.status === "working") return "still running";
  if (!r.summary) return "did not finish";
  const s = r.summary;
  const findings = s.findings === 0 ? "no findings" : `${s.findings} ${s.findings === 1 ? "finding" : "findings"}`;
  return `${outcomeInfo(s.outcome).title}: ${findings}, ${s.finished} of ${s.total} task runs finished`;
}
