"use client";

import { Alert, Card, ErrorBox, Loading } from "@/components/ui";
import { api } from "@/lib/api";
import { adviceFor, spaceRows, type SpaceTone } from "@/lib/space";
import { useAsync } from "@/lib/useAsync";

const BAR: Record<SpaceTone, string> = { ok: "bg-ok", warn: "bg-warn", bad: "bg-bad" };

/**
 * What a signed-in person uses of this server and may use: disk, builds kept, runs working at once (docs/person-limits.md). Only their own numbers.
 * The owner has no limits and sees nothing here (the model section already says the owner's settings are the server's own).
 */
export function MySpace() {
  const loaded = useAsync(api.mySpace, "my-space");
  if (loaded.error && !loaded.data) return <ErrorBox error={loaded.error} onRetry={loaded.reload} />;
  if (!loaded.data) return <Loading what="your space" />;
  const space = loaded.data;
  if (space.mode !== "person") return null;
  const rows = spaceRows(space);
  const advice = adviceFor(rows);

  return (
    <Card className="p-5">
      <h2 className="text-lg font-semibold">Your space on this server</h2>
      <p className="mt-0.5 max-w-prose text-sm text-muted">What you use, and the most this server gives each person. Only you see these numbers.</p>
      <ul className="mt-4 space-y-4">
        {rows.map((row) => (
          <li key={row.key}>
            <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
              <span className="font-medium">{row.label}</span>
              <span className={`text-sm ${row.tone === "bad" ? "text-bad" : "text-muted"}`}>{row.text}</span>
            </div>
            {row.percent !== null && (
              <div
                role="progressbar"
                aria-label={row.label}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={row.percent}
                aria-valuetext={row.text}
                className="mt-1 h-2 overflow-hidden rounded-full bg-surface-2"
              >
                <div className={`h-full rounded-full ${BAR[row.tone]}`} style={{ width: `${row.percent}%` }} />
              </div>
            )}
          </li>
        ))}
      </ul>
      {advice && (
        <div className="mt-4">
          <Alert tone="warn" title="A limit is reached">
            <p>{advice}</p>
          </Alert>
        </div>
      )}
    </Card>
  );
}
