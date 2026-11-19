"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { BuildSession } from "@/lib/types";
import { Alert, Button, ButtonLink } from "../ui";

/** A step stopped. If a second try can help (a missing key, an unreachable model) it can be retried; otherwise start over. */
export function FailedCard({ session, onSession }: { session: BuildSession; onSession: (s: BuildSession) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function retry() {
    setBusy(true);
    setError(null);
    try {
      onSession(await api.retry(session.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      <Alert tone="bad" title="It stopped">
        <p className="break-words">{session.error || "The step failed for a reason that was not recorded."}</p>
        {session.retryable ? (
          <p className="mt-2 text-muted">
            A second try can help here. If this is about the model or a key, fix the settings in the <code className="font-mono">.env</code> file in the repository&apos;s
            root folder first, then try again.
          </p>
        ) : (
          <p className="mt-2 text-muted">Trying again would give the same result, so start over with a changed description.</p>
        )}
      </Alert>
      {error && (
        <Alert tone="bad" title="It could not be retried">
          {error}
        </Alert>
      )}
      <div className="flex flex-wrap gap-2">
        {session.retryable && (
          <Button variant="primary" busy={busy} onClick={() => void retry()}>
            Try again
          </Button>
        )}
        <ButtonLink href="/builder">Start over</ButtonLink>
      </div>
    </div>
  );
}
