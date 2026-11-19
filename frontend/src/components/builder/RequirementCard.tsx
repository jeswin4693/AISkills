"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { specRows } from "@/lib/builder";
import type { BuildSession } from "@/lib/types";
import { Alert, Button, ButtonLink, Card } from "../ui";

/**
 * The requirement, each item next to the words of the person that back it. Approving it is the only thing that starts
 * a build: until then nothing has been written.
 */
export function RequirementCard({ session, onSession }: { session: BuildSession; onSession: (s: BuildSession) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const rows = session.spec ? specRows(session.spec) : [];

  async function approve() {
    setBusy(true);
    setError(null);
    try {
      onSession(await api.approve(session.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <Card className="p-5">
      <h2 className="font-semibold">Check the requirement</h2>
      <p className="mt-1 text-sm text-muted">
        This is how I read your words. Each line is backed by a quote that was <strong>checked against what you typed</strong>: a line without your words behind
        it would not be here. If something is wrong, start over with a clearer description. Nothing has been built yet.
      </p>
      <dl className="mt-4 space-y-4">
        {rows.map((r) => (
          <div key={r.slot} className="grid gap-1 border-t border-border pt-3 md:grid-cols-[12rem_1fr]">
            <dt className="text-sm font-semibold">{r.label}</dt>
            <dd className="min-w-0 text-sm">
              {r.values.length === 0 ? (
                <span className="text-muted">Nothing recorded</span>
              ) : (
                <ul className="list-disc space-y-0.5 pl-5">
                  {r.values.map((v, i) => (
                    <li key={i}>{v}</li>
                  ))}
                </ul>
              )}
              {r.quote && (
                <blockquote className="mt-1.5 border-l-2 border-accent pl-3 text-muted">
                  <span className="text-xs font-medium tracking-wide uppercase">Your words</span>
                  <br />
                  &ldquo;{r.quote}&rdquo;
                </blockquote>
              )}
            </dd>
          </div>
        ))}
      </dl>
      {error && (
        <div className="mt-4">
          <Alert tone="bad" title="It could not be approved">
            {error}
          </Alert>
        </div>
      )}
      <div className="mt-5 flex flex-wrap items-center gap-2">
        <Button variant="primary" busy={busy} onClick={() => void approve()}>
          Approve and build
        </Button>
        <ButtonLink href="/builder">Start over</ButtonLink>
        <span className="text-sm text-muted">
          {session.with_scripts ? "Helper scripts will be written and tested in the sandbox." : "Instructions only: no scripts."}
        </span>
      </div>
    </Card>
  );
}
