"use client";

import { useEffect, useId, useState } from "react";
import { api } from "@/lib/api";
import { answerProblem, answersRequest, draftProblem, draftsOf, eventLine, isDirty, statusSentence, stopsOf, type Drafts } from "@/lib/planSession";
import type { PlanDecision, PlanSessionView } from "@/lib/types";
import { Alert, Badge, Button } from "../ui";

const INPUT = "block w-full rounded-md border border-border bg-bg px-3 py-2 text-sm disabled:opacity-70";

type Busy = "save" | "approve" | "reopen" | null;

/**
 * The person's side of a kept plan: an answer to each question in their own words, a decision on each assumption, and the approval. The SERVER decides whether
 * the plan can be approved (every blocking question answered, every assumption decided); this shows what is missing as the person types, and every request names
 * the state of the plan the person was looking at, so an approval is always of what was on the screen.
 */
export function PlanAnswers({ view, onView, onDirty }: { view: PlanSessionView; onView: (v: PlanSessionView) => void; onDirty: (dirty: boolean) => void }) {
  const base = useId();
  const [drafts, setDrafts] = useState<Drafts>(() => draftsOf(view));
  const [busy, setBusy] = useState<Busy>(null);
  const [error, setError] = useState<string | null>(null);
  const [missing, setMissing] = useState<string[]>([]);
  const locked = view.status === "approved";

  // The boxes start again from the server's state whenever it moves: after a save, an approval or a reopen, or when another plan is opened.
  useEffect(() => {
    setDrafts(draftsOf(view));
    setError(null);
    setMissing([]);
  }, [view.id, view.rev, view.status]); // eslint-disable-line react-hooks/exhaustive-deps -- `view` as a whole changes on every poll; these three are what mark a new state

  const dirty = isDirty(view, drafts);
  useEffect(() => onDirty(dirty), [dirty, onDirty]);
  useEffect(() => () => onDirty(false), [onDirty]);

  const problem = draftProblem(view, drafts);
  const stops = stopsOf(view, drafts);
  const working = busy !== null;

  const setAnswer = (index: number, text: string) => setDrafts((d) => ({ ...d, questions: { ...d.questions, [index]: text } }));
  const setDecision = (index: number, decision: PlanDecision) => setDrafts((d) => ({ ...d, assumptions: { ...d.assumptions, [index]: decision } }));

  async function run(kind: Exclude<Busy, null>, work: () => Promise<void>) {
    setBusy(kind);
    setError(null);
    setMissing([]);
    try {
      await work();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  const save = () => run("save", async () => onView(await api.savePlanAnswers(view.id, answersRequest(view, drafts))));

  const approve = () =>
    run("approve", async () => {
      let current = view;
      if (dirty) {
        current = await api.savePlanAnswers(view.id, answersRequest(view, drafts)); // what is approved is what is saved, never what is only on the screen
        onView(current);
      }
      const result = await api.approvePlan(current.id, current.rev);
      if (result.ok) onView(result.view);
      else {
        setError(result.detail);
        setMissing(result.missing);
      }
    });

  const reopen = () => run("reopen", async () => onView(await api.reopenPlan(view.id)));

  const nothingToAnswer = view.questions.length === 0 && view.assumptions.length === 0;

  return (
    <section id="answers" aria-label="Your answers and approval" className="space-y-4 border-t border-border pt-5">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-base font-semibold">6. Your answers and approval</h3>
        <Badge tone={locked ? "ok" : "warn"}>{locked ? "Approved" : "Not approved yet"}</Badge>
      </div>
      <p className="text-sm" role="status" aria-live="polite">
        {statusSentence(view, drafts)}
      </p>
      <p className="text-sm text-muted">
        Answer in your own words. The code checks that an answer exists, not that it is right. Assumptions are not facts: none is used until you approve it. The size of the
        change, the tier and the token plan above were measured before your answers and are not measured again.
      </p>

      {nothingToAnswer && <p className="text-sm text-muted">This plan has no questions and no assumptions, so there is nothing to answer. You can approve it as it is.</p>}

      {view.questions.length > 0 && (
        <div className="space-y-4">
          <h4 className="text-sm font-medium">Questions</h4>
          <ol className="space-y-4">
            {view.questions.map((q) => {
              const id = `${base}-q${q.index}`;
              const text = drafts.questions[q.index] ?? "";
              const bad = answerProblem(text);
              return (
                <li key={q.index} className="space-y-1.5 text-sm">
                  <label htmlFor={id} className="block">
                    {q.blocking && <Badge tone="bad">Blocking</Badge>} <span className="font-medium">{q.question}</span>
                  </label>
                  <p className="text-muted">{q.why}</p>
                  <textarea
                    id={id}
                    value={text}
                    onChange={(e) => setAnswer(q.index, e.target.value)}
                    readOnly={locked}
                    rows={2}
                    aria-invalid={bad ? true : undefined}
                    aria-describedby={bad ? `${id}-problem` : undefined}
                    placeholder={q.blocking ? "Required before you can approve" : "Optional"}
                    className={`${INPUT} resize-y`}
                  />
                  {bad && (
                    <p id={`${id}-problem`} className="text-warn">
                      {bad}
                    </p>
                  )}
                </li>
              );
            })}
          </ol>
        </div>
      )}

      {view.assumptions.length > 0 && (
        <div className="space-y-4">
          <h4 className="text-sm font-medium">Assumptions</h4>
          <ul className="space-y-4">
            {view.assumptions.map((a) => {
              const choice = drafts.assumptions[a.index] ?? "";
              const name = `${base}-a${a.index}`;
              return (
                <li key={a.index} className="text-sm">
                  <fieldset disabled={locked} className="space-y-1.5">
                    <legend className="font-medium">{a.text}</legend>
                    <p className="text-muted">{a.why}</p>
                    <div className="flex flex-wrap gap-x-5 gap-y-1">
                      <label className="inline-flex items-center gap-2">
                        <input type="radio" name={name} checked={choice === "approve"} onChange={() => setDecision(a.index, "approve")} />
                        <span>Approve (the work may rely on it)</span>
                      </label>
                      <label className="inline-flex items-center gap-2">
                        <input type="radio" name={name} checked={choice === "reject"} onChange={() => setDecision(a.index, "reject")} />
                        <span>Do not approve (the work must ask instead)</span>
                      </label>
                    </div>
                  </fieldset>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {problem && <p className="text-sm text-warn">{problem}</p>}
      {error && (
        <Alert tone={missing.length ? "warn" : "bad"} title={missing.length ? "Not ready to approve" : "That did not work"}>
          <p>{error}</p>
          {missing.length > 0 && (
            <ul className="mt-1 list-disc space-y-0.5 pl-5">
              {missing.map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
          )}
        </Alert>
      )}

      <div className="flex flex-wrap items-center gap-3">
        {locked ? (
          <Button onClick={() => void reopen()} busy={busy === "reopen"} disabled={working}>
            Reopen to change
          </Button>
        ) : (
          <>
            <Button onClick={() => void save()} busy={busy === "save"} disabled={!dirty || !!problem || working}>
              Save answers
            </Button>
            <Button variant="primary" onClick={() => void approve()} busy={busy === "approve"} disabled={stops.length > 0 || !!problem || working}>
              Approve this plan
            </Button>
          </>
        )}
        {!locked && dirty && <span className="text-sm text-muted">You have changes that are not saved. Approving saves them first.</span>}
      </div>

      {view.events.length > 0 && (
        <details className="text-sm">
          <summary className="cursor-pointer font-medium">History of this plan</summary>
          <ul className="mt-2 list-disc space-y-0.5 pl-5">
            {view.events.map((e, i) => (
              <li key={`${e.at}|${e.what}|${i}`}>{eventLine(e)}</li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
