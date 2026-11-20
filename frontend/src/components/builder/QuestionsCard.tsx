"use client";

import { useId, useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import { answersToSend, canSendAnswers, slotsOf } from "@/lib/builder";
import type { BuildSession } from "@/lib/types";
import { useKinds } from "@/lib/useKinds";
import { Alert, Button, Card } from "../ui";

/** Only what the person's words did not cover is asked. The server decides that with a checklist, not the model. */
export function QuestionsCard({ session, onSession }: { session: BuildSession; onSession: (s: BuildSession) => void }) {
  const base = useId();
  const slots = slotsOf(useKinds().data, session.kind);
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function send(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onSession(await api.answer(session.id, answersToSend(session.questions, values)));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  return (
    <Card className="p-5">
      <form onSubmit={send} className="space-y-4">
        <div>
          <h2 className="font-semibold">A few details are missing</h2>
          <p className="mt-1 text-sm text-muted">
            Round {session.round} of {session.max_rounds}. I only ask about what your words did not cover, and nothing is built until you approve a requirement.
            Answer as many as you can; any you skip are asked again.
          </p>
        </div>
        {session.questions.map((q) => {
          const id = `${base}-${q.slot}`;
          return (
            <div key={q.slot}>
              <label htmlFor={id} className="block">
                <span className="font-medium">{slots.find((s) => s.key === q.slot)?.label ?? q.slot}</span>
                <span className="block text-sm text-muted">{q.text}</span>
              </label>
              <textarea
                id={id}
                rows={2}
                maxLength={5000}
                value={values[q.slot] ?? ""}
                onChange={(e) => setValues({ ...values, [q.slot]: e.target.value })}
                className="mt-1.5 block w-full rounded-md border border-border bg-bg px-3 py-2 text-sm"
              />
            </div>
          );
        })}
        {session.notes.length > 0 && (
          <details className="text-sm">
            <summary className="cursor-pointer text-muted hover:text-text">Why am I being asked?</summary>
            <ul className="mt-1 list-disc space-y-1 pl-5 text-muted">
              {session.notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          </details>
        )}
        {error && (
          <Alert tone="bad" title="Your answers could not be sent">
            {error}
          </Alert>
        )}
        <Button type="submit" variant="primary" busy={busy} disabled={!canSendAnswers(session.questions, values)}>
          Send answers
        </Button>
      </form>
    </Card>
  );
}
