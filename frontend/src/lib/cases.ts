import type { CaseDoc, CasesView } from "./types";

/**
 * The test-case editor's rules, kept out of the components so they can be tested without a browser: what a person can choose, what makes a draft
 * unsaveable (the same rules the server applies, so a person is told before the save, never only after), and how a draft becomes the request.
 * The server is still the judge: it checks every rule again, and also the ones that need Python (a pattern that could hang the checker).
 */

export interface DraftCheck {
  kind: string;
  value: string;
  why: string;
}

export interface DraftCase {
  key: string; // identifies the card while it is being edited; never sent
  name: string;
  kind: string;
  message: string;
  checks: DraftCheck[];
  covers: string[]; // the acceptance criteria it checks, kept exactly as they were: the editor does not change them
}

export type Limits = CasesView["limits"];

/** The seven checks code can run on a reply, as the person is asked. `numeric` ones take a whole number. */
export const CHECK_KINDS: { kind: string; label: string; hint: string; numeric: boolean }[] = [
  { kind: "contains", label: "contains the text", hint: "text that must appear (capital letters do not matter)", numeric: false },
  { kind: "not_contains", label: "does not contain the text", hint: "text that must not appear", numeric: false },
  { kind: "starts_with", label: "starts with the text", hint: "what the reply must begin with", numeric: false },
  { kind: "regex", label: "matches a pattern", hint: "a short regular expression, at most 80 characters", numeric: false },
  { kind: "max_chars", label: "is at most … characters", hint: "a whole number", numeric: true },
  { kind: "max_lines", label: "is at most … lines", hint: "a whole number (blank lines are not counted)", numeric: true },
  { kind: "first_line_max_chars", label: "has a first line of at most … characters", hint: "a whole number: for a title", numeric: true },
];

export const CASE_KINDS: { kind: string; label: string }[] = [
  { kind: "positive", label: "positive: the usual case, it should work" },
  { kind: "negative", label: "negative: it should refuse, or ask" },
  { kind: "edge", label: "edge: an unusual input" },
];

export const isNumericKind = (kind: string): boolean => CHECK_KINDS.some((k) => k.kind === kind && k.numeric);

const MAX_NUMBER = 1_000_000;
const MAX_PATTERN = 80;
let counter = 0;
const newKey = (): string => `c${++counter}`;

export const blankCheck = (): DraftCheck => ({ kind: "contains", value: "", why: "" });
export const blankCase = (): DraftCase => ({ key: newKey(), name: "", kind: "positive", message: "", checks: [blankCheck()], covers: [] });

/** Drafts made from what the server holds. Nothing is shared with the server's objects, so editing a draft never changes what was loaded. */
export function fromServer(cases: CaseDoc[]): DraftCase[] {
  return cases.map((c) => ({
    key: newKey(), name: c.name, kind: c.kind, message: c.message, covers: [...c.covers], checks: c.checks.map((k) => ({ ...k })),
  }));
}

const clean = (c: DraftCase) => ({
  name: c.name.trim(), kind: c.kind, message: c.message.trim(), covers: c.covers,
  checks: c.checks.map((k) => ({ kind: k.kind, value: k.value.trim(), why: k.why.trim() })),
});

/** Whether two lists are the same cases in the same order (keys and spaces around texts do not count). */
export const sameCases = (a: DraftCase[], b: DraftCase[]): boolean => JSON.stringify(a.map(clean)) === JSON.stringify(b.map(clean));

/** What stops these cases from being saved, one line for each case that has a problem. The same rules the server applies. */
export function caseProblems(cases: DraftCase[], limits: Limits): string[] {
  if (cases.length === 0) return ["Add at least one case, or leave the skill as it is."];
  const out: string[] = [];
  if (cases.length > limits.max_cases) out.push(`A skill can hold at most ${limits.max_cases} cases.`);
  const seen = new Map<string, number>();
  cases.forEach((c, i) => {
    const name = c.name.trim();
    const issues: string[] = [];
    if (!name) issues.push("it needs a name");
    else if (name.length > limits.max_name) issues.push(`its name is longer than ${limits.max_name} characters`);
    else if (seen.has(name.toLowerCase())) issues.push(`its name is used twice (Case ${seen.get(name.toLowerCase())} has it too)`);
    else seen.set(name.toLowerCase(), i + 1);
    const message = c.message.trim();
    if (!message) issues.push("it needs a message to send");
    else if (message.length > limits.max_message) issues.push(`its message is longer than ${limits.max_message} characters`);
    if (c.checks.length === 0) issues.push("it needs at least one check the reply must pass");
    else if (c.checks.length > limits.max_checks) issues.push(`it can have at most ${limits.max_checks} checks`);
    for (const k of c.checks) {
      const value = k.value.trim();
      if (!value) issues.push(`${k.kind} has no value`);
      else if (value.length > limits.max_value) issues.push(`a check's value is longer than ${limits.max_value} characters`);
      else if (isNumericKind(k.kind) && !(/^[0-9]+$/.test(value) && Number(value) >= 1 && Number(value) <= MAX_NUMBER)) {
        issues.push(`${k.kind} needs a whole number from 1 to ${MAX_NUMBER}, not '${value}'`);
      } else if (k.kind === "regex" && value.length > MAX_PATTERN) issues.push(`a pattern can be at most ${MAX_PATTERN} characters`);
    }
    if (issues.length) out.push(`Case ${i + 1}${name ? ` ('${name.slice(0, 40)}')` : ""}: ${issues.join("; ")}.`);
  });
  return out;
}

/** The request the server reads. Every text is trimmed, as the server trims it. */
export function toBody(baseVersion: number, cases: DraftCase[], note: string) {
  return { base_version: baseVersion, note: note.trim(), cases: cases.map(clean) };
}
