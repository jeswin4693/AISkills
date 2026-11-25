"use client";

import { Badge, Card } from "@/components/ui";
import { formatWhen, relativeTime } from "@/lib/format";
import { runLine } from "@/lib/testing";
import type { EvalRunSummary } from "@/lib/types";

/** Earlier runs of one version, newest first. A run is opened by clicking it; the one being shown is marked. */
export function RunHistory({ runs, openId, onOpen }: { runs: EvalRunSummary[]; openId: string | null; onOpen: (id: string) => void }) {
  if (runs.length === 0) return null;
  return (
    <section>
      <h3 className="mb-2 font-semibold">Earlier runs of this version</h3>
      <Card>
        <ul className="divide-y divide-border">
          {runs.map((r) => (
            <li key={r.id}>
              <button
                type="button"
                onClick={() => onOpen(r.id)}
                aria-current={r.id === openId ? "true" : undefined}
                className={`block w-full px-4 py-2.5 text-left text-sm ${r.id === openId ? "bg-accent-soft" : "hover:bg-surface-2"}`}
              >
                <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span className="font-medium">{r.tag}</span>
                  <span className="text-muted" title={formatWhen(r.created_at)}>
                    {relativeTime(r.created_at)}
                  </span>
                  <span>{runLine(r)}</span>
                  {r.runs > 1 && <Badge>{r.runs} repeats</Badge>}
                  {r.status === "failed" && <Badge tone="bad">failed</Badge>}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </Card>
    </section>
  );
}
