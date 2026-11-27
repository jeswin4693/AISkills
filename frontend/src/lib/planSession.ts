import { formatWhen, plural, shortHash } from "./format";
import type { PlanAnswersRequest, PlanApproval, PlanDecision, PlanEvent, PlanSessionView, PlanSummary } from "./types";

// The page's own logic for answering and approving a kept plan (slice AN). The SERVER decides: what counts as an answer, what stops an approval, the fingerprint.
// This only mirrors those rules to spare a round trip and to say what is missing as the person types; the server checks everything again and its word is final.

export const MAX_ANSWER = 2000;
export const ANSWER = "Answer: ";
export const DECIDE = "Decide: ";

const n = (x: number): string => x.toLocaleString("en-US");

/** What is in the boxes now, by the position of the question or assumption in the plan's own lists. "" is "nothing yet". */
export interface Drafts {
  questions: Record<number, string>;
  assumptions: Record<number, PlanDecision | "">;
}

/** The boxes as the server holds them. */
export function draftsOf(view: PlanSessionView): Drafts {
  return {
    questions: Object.fromEntries(view.questions.map((q) => [q.index, q.answer ?? ""])),
    assumptions: Object.fromEntries(view.assumptions.map((a) => [a.index, a.decision ?? ""])),
  };
}

/** An answer as the server keeps it: line breaks plain, trimmed. */
const kept = (text: string): string => text.replace(/\r\n?/g, "\n").trim();

/** What is wrong with one answer, or null. A blank box is fine: it removes the answer. The server counts characters, not UTF-16 units, and so does this. */
export function answerProblem(text: string): string | null {
  const t = kept(text);
  if (!t) return null;
  const length = [...t].length;
  if (length > MAX_ANSWER) return `The answer is too long: ${n(MAX_ANSWER)} characters at most (it is ${n(length)}).`;
  if (!/[\p{L}\p{N}]/u.test(t)) return "Write the answer in words.";
  return null;
}

/** The first answer that cannot be kept, with its number, or null. */
export function draftProblem(view: PlanSessionView, drafts: Drafts): string | null {
  for (const q of view.questions) {
    const problem = answerProblem(drafts.questions[q.index] ?? "");
    if (problem) return `Question ${q.index + 1}: ${problem.charAt(0).toLowerCase()}${problem.slice(1)}`;
  }
  return null;
}

/** What would stop an approval with the boxes as they are, in the plan's order: a blocking question with nothing written, an assumption with no decision. */
export function stopsOf(view: PlanSessionView, drafts: Drafts): string[] {
  const questions = view.questions.filter((q) => q.blocking && !kept(drafts.questions[q.index] ?? "")).map((q) => `${ANSWER}${q.question}`);
  const assumptions = view.assumptions.filter((a) => !drafts.assumptions[a.index]).map((a) => `${DECIDE}${a.text}`);
  return [...questions, ...assumptions];
}

/** Why an approval is not ready, in the words the server uses when it refuses. */
export function blockedSentence(stops: string[]): string {
  const questions = stops.filter((s) => s.startsWith(ANSWER)).length;
  const assumptions = stops.filter((s) => s.startsWith(DECIDE)).length;
  const parts: string[] = [];
  if (questions) parts.push(`${questions} blocking ${questions === 1 ? "question has" : "questions have"} no answer`);
  if (assumptions) parts.push(`${assumptions} ${assumptions === 1 ? "assumption has" : "assumptions have"} no decision`);
  return `Not ready to approve: ${parts.join(", and ")}.`;
}

/** Whether the boxes differ from what the server holds (spaces around an answer and a Windows line break are not differences: the server does not keep them). */
export function isDirty(view: PlanSessionView, drafts: Drafts): boolean {
  const held = draftsOf(view);
  const same = <T extends string>(a: Record<number, T>, b: Record<number, T>, norm: (x: T) => string): boolean => {
    const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
    return [...keys].every((k) => norm(a[Number(k)] ?? ("" as T)) === norm(b[Number(k)] ?? ("" as T)));
  };
  return !same(held.questions, drafts.questions, kept) || !same(held.assumptions, drafts.assumptions, (x) => x);
}

/** What is sent to save: every answer and decision with its position, the state the person saw, and nothing for what is blank. */
export function answersRequest(view: PlanSessionView, drafts: Drafts): PlanAnswersRequest {
  const questions: Record<string, string> = {};
  for (const [k, v] of Object.entries(drafts.questions)) if (kept(v)) questions[k] = kept(v);
  const assumptions: Record<string, PlanDecision | null> = {};
  for (const [k, v] of Object.entries(drafts.assumptions)) if (v) assumptions[k] = v;
  return { rev: view.rev, questions, assumptions };
}

export function approvalSentence(a: PlanApproval): string {
  const base = `Approved on ${formatWhen(a.approved_at)}. Tier ${a.tier}. Fingerprint ${shortHash(a.fingerprint)}… (it names this record in this app: it is not a signature).`;
  return a.intact ? base : `${base} Warning: the kept record does not match this fingerprint, so the plan or its answers were changed after the approval.`;
}

/** Where the plan stands, from the boxes as they are now. */
export function statusSentence(view: PlanSessionView, drafts: Drafts): string {
  if (view.status === "approved" && view.approval) return approvalSentence(view.approval);
  const stops = stopsOf(view, drafts);
  if (stops.length) return blockedSentence(stops);
  const open = view.questions.filter((q) => !q.blocking && !kept(drafts.questions[q.index] ?? "")).length;
  const base = "Ready to approve. Nothing blocking is missing.";
  return open ? `${base} ${open} ${open === 1 ? "question that does not block is" : "questions that do not block are"} left unanswered.` : base;
}

export function eventLine(e: PlanEvent): string {
  const label = { made: "Plan made", "answers saved": "Answers saved", approved: "Approved", reopened: "Approval withdrawn (reopened)" }[e.what] ?? e.what;
  return `${formatWhen(e.at)} · ${label}`;
}

/** One line for the list of kept plans: the tier and how far the answers have got. */
export function summaryLine(s: PlanSummary): string {
  if (!s.readable || !s.questions || !s.assumptions || s.tier === undefined) return "Made by an older version: it cannot be shown. Delete it.";
  const q = s.questions;
  const a = s.assumptions;
  const questions = q.total
    ? `${q.answered} of ${plural(q.total, "question")} answered${q.blocking ? ` (${q.blocking_answered} of ${q.blocking} blocking)` : ""}`
    : "no questions";
  const assumptions = a.total ? `${a.decided} of ${plural(a.total, "assumption")} decided` : "no assumptions";
  return `Tier ${s.tier} · ${questions} · ${assumptions}`;
}
