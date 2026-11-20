import type { BuildResultInfo, BuildSession, BuildStatus, JobInfo, KindInfo, Question, RequirementSpec, SessionUsage, SlotInfo, TestCase } from "./types";

export const SLOT_ORDER = ["goal", "inputs", "outputs", "constraints", "acceptance_criteria", "failure_behavior"] as const;

export const SLOT_LABEL: Record<string, string> = {
  goal: "Goal",
  inputs: "What it receives",
  outputs: "What it produces",
  constraints: "Rules it must respect",
  acceptance_criteria: "How we will know it works",
  failure_behavior: "When something goes wrong",
};

export interface SpecRow {
  slot: string;
  label: string;
  values: string[];
  quote: string; // the person's own words behind it, checked by the server
}

/** The skill's checklist as built in: used until (or unless) the server lists a kind's own slots. */
export const DEFAULT_SLOTS: SlotInfo[] = SLOT_ORDER.map((key) => ({ key, label: SLOT_LABEL[key], question: "" }));

/** The slots of a kind as the server lists them, or the skill's own when it does not list that kind. */
export function slotsOf(kinds: KindInfo[] | undefined, kind: string): SlotInfo[] {
  return kinds?.find((k) => k.key === kind)?.slots ?? DEFAULT_SLOTS;
}

/** The kinds that are described in words in the Builder: a plugin is composed from the library instead. */
export function conversationalKinds(kinds: KindInfo[] | undefined): KindInfo[] {
  return (kinds ?? []).filter((k) => k.conversational);
}

/** The Builder's picker is shown only when there is something to choose between. */
export function showKindPicker(kinds: KindInfo[] | undefined): boolean {
  return conversationalKinds(kinds).length > 1;
}

/** A kind's name for a person, or its key when the server does not list it. */
export function kindLabel(kinds: KindInfo[] | undefined, key: string): string {
  return kinds?.find((k) => k.key === key)?.label ?? key;
}

/** A kind's name inside a sentence: "skill", "agent", "MCP server" (lower case, except an acronym that is already capitals). */
export function kindNoun(kinds: KindInfo[] | undefined, key: string): string {
  const label = kindLabel(kinds, key);
  return /^[A-Z]{2,}/.test(label) ? label : label.toLowerCase();
}

/** "a skill", "an agent": the noun with the right article. */
export function withArticle(noun: string): string {
  const vowelSound = /^[A-Z]{2,}/.test(noun) ? /^[AEFHILMNORSX]/.test(noun) : /^[aeiou]/i.test(noun); // "an MCP": an acronym is read letter by letter
  return `${vowelSound ? "an" : "a"} ${noun}`;
}

/** The requirement as rows, each next to the words of the person that support it. */
export function specRows(spec: RequirementSpec, slots: SlotInfo[] = DEFAULT_SLOTS): SpecRow[] {
  const fields = spec as unknown as Record<string, unknown>;
  return slots.map(({ key, label }) => {
    const raw = fields[key];
    const values = Array.isArray(raw) ? raw.map(String) : raw ? [String(raw)] : [];
    return { slot: key, label, values, quote: spec.quotes[key] ?? "" };
  });
}

type Tone = "info" | "ok" | "warn" | "bad" | "neutral";

export function statusInfo(status: BuildStatus): { label: string; tone: Tone } {
  switch (status) {
    case "working": return { label: "Working", tone: "info" };
    case "awaiting_answers": return { label: "Needs your answers", tone: "warn" };
    case "awaiting_approval": return { label: "Needs your approval", tone: "warn" };
    case "done": return { label: "Built", tone: "ok" };
    case "failed": return { label: "Failed", tone: "bad" };
  }
}

export function activityText(job: JobInfo | null): string {
  if (!job) return "Starting";
  return job.kind === "understand" ? "Reading your words and checking them against the checklist" : "Writing the skill and running every check";
}

export function canSendAnswers(questions: Question[], values: Record<string, string>): boolean {
  return questions.some((q) => (values[q.slot] ?? "").trim() !== "");
}

/** Only the questions that were answered, trimmed. The server needs at least one. */
export function answersToSend(questions: Question[], values: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const q of questions) {
    const v = (values[q.slot] ?? "").trim();
    if (v) out[q.slot] = v;
  }
  return out;
}

export function elapsedSeconds(startIso: string | null | undefined, now: number): number {
  if (!startIso) return 0;
  const start = new Date(startIso).getTime();
  return Number.isNaN(start) ? 0 : Math.max(0, Math.round((now - start) / 1000));
}

export interface Trace {
  id: string;
  text: string;
  tests: { name: string; kind: string }[];
}

/**
 * Each acceptance criterion next to the tests that cover it. Ids are numbered the way the builder numbers them: from AC1,
 * skipping empty items and "none".
 */
export function traceability(criteria: string[], tests: TestCase[]): Trace[] {
  const items = criteria.map((c) => c.trim()).filter((c) => c && c.toLowerCase() !== "none");
  return items.map((text, i) => {
    const id = `AC${i + 1}`;
    return { id, text, tests: tests.filter((t) => t.covers.includes(id)).map(({ name, kind }) => ({ name, kind })) };
  });
}

/** tests/cases.json is written by the builder, but it is still read defensively: anything odd gives an empty list. */
export function parseTests(json: string): TestCase[] {
  try {
    const data: unknown = JSON.parse(json);
    if (!Array.isArray(data)) return [];
    return data.flatMap((d): TestCase[] => {
      if (!d || typeof d !== "object") return [];
      const t = d as Record<string, unknown>;
      if (typeof t.name !== "string" || typeof t.kind !== "string") return [];
      return [{
        name: t.name, kind: t.kind,
        input_description: typeof t.input_description === "string" ? t.input_description : "",
        expected_result: typeof t.expected_result === "string" ? t.expected_result : "",
        covers: Array.isArray(t.covers) ? t.covers.filter((c): c is string => typeof c === "string") : [],
      }];
    });
  } catch {
    return [];
  }
}

export const STEPS = ["Describe", "Answer", "Approve", "Build", "Save"] as const;
export type StepState = "done" | "current" | "todo" | "failed";

/** Where the person is in the conversation, for the strip at the top of the page. */
export function progressSteps(s: Pick<BuildSession, "status" | "round" | "job" | "saved">): { label: string; state: StepState }[] {
  const building = s.job?.kind === "build";
  let current: number;
  if (s.status === "awaiting_answers") current = 1;
  else if (s.status === "awaiting_approval") current = 2;
  else if (s.status === "done") current = s.saved ? STEPS.length : 4;
  else if (building) current = 3;
  else current = s.round > 1 ? 1 : 0; // reading the words, before or after a round of answers
  return STEPS.map((label, i) => ({
    label,
    state: i < current ? "done" : i === current ? (s.status === "failed" ? "failed" : "current") : "todo",
  }));
}

export const EXAMPLES = [
  "A skill that counts TODO and FIXME comments in a folder and reports them for each file.",
  "A skill that turns pasted meeting notes into a short summary, the decisions made, and action items with owners.",
  "A skill that reads a pull request description and lists what is missing from it.",
];

/**
 * What using the skill costs, in words. These are estimates (about 4 characters per token), and the line says so:
 * the name and description are in the agent's context on every task; SKILL.md only when the skill is picked.
 */
export function tokenLine(tokens: BuildResultInfo["tokens"]): string | null {
  if (!tokens) return null;
  const n = (v: number) => v.toLocaleString("en-US");
  return `Costs about ${n(tokens.always)} tokens on every task (its name and description) and ${n(tokens.when_used)} more when the agent uses it. Estimates.`;
}

/**
 * What the model was asked while building, in words: every attempt (a failed one counts), the tokens the provider reported
 * (never an estimate), and the models used. Empty when there is nothing to say.
 */
export function usageText(usage: SessionUsage | undefined): string {
  if (!usage || usage.calls === 0) return "";
  const n = (v: number) => v.toLocaleString("en-US");
  const parts = [`${n(usage.calls)} attempt${usage.calls === 1 ? "" : "s"} at the model${usage.errors > 0 ? ` (${n(usage.errors)} failed)` : ""}`];
  parts.push(
    usage.input_tokens === null && usage.output_tokens === null
      ? "no token counts reported"
      : `${n(usage.input_tokens ?? 0)} tokens in and ${n(usage.output_tokens ?? 0)} out`,
  );
  if (usage.models.length > 0) parts.push(usage.models.join(", "));
  return parts.join(" · ") + ".";
}
