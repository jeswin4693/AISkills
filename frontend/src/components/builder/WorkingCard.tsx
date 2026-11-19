"use client";

import { activityText, elapsedSeconds } from "@/lib/builder";
import type { BuildSession } from "@/lib/types";
import { useNow } from "@/lib/useBuildSession";
import { Card, Spinner } from "../ui";

function clock(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toTimeString().slice(0, 8);
}

/** A background job is running. The page polls once a second, so this stays current without being refreshed. */
export function WorkingCard({ session }: { session: BuildSession }) {
  const now = useNow(true);
  const job = session.job;
  const seconds = elapsedSeconds(job?.started_at ?? session.updated_at, now);
  const events = job?.events ?? [];
  return (
    <Card className="p-5">
      <div role="status" aria-live="polite">
        <h2 className="flex items-center gap-2 font-semibold">
          <Spinner /> {activityText(job)}…
        </h2>
        <p className="mt-1 text-sm text-muted">
          Working for {seconds} s. A few seconds is normal; it can take a minute or more when scripts are tested. You can leave this page and come back: it keeps going.
        </p>
      </div>
      {events.length > 0 && (
        <ol aria-label="Progress messages" className="mt-3 space-y-1 border-l-2 border-border pl-3 text-sm">
          {events.map((e, i) => (
            <li key={`${e.at}-${i}`} className={i === events.length - 1 ? "font-medium" : "text-muted"}>
              <span className="mr-2 font-mono text-xs text-muted">{clock(e.at)}</span>
              {e.message}
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}
