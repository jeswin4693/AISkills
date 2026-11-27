"use client";

import { useState } from "react";
import { formatWhen } from "@/lib/format";
import { summaryLine } from "@/lib/planSession";
import type { PlanSummary } from "@/lib/types";
import { Badge, Button, Card } from "../ui";

/** The plans that are kept on this computer: open one to carry on answering it, or delete it. Deleting asks once more, on the row. */
export function KeptPlans({
  plans, openId, busyId, onOpen, onDelete,
}: {
  plans: PlanSummary[];
  openId: string | null;
  busyId: string | null;
  onOpen: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  const [asking, setAsking] = useState<string | null>(null);
  return (
    <Card className="space-y-3 p-5">
      <h2 className="text-base font-semibold">Kept plans</h2>
      <p className="text-sm text-muted">Every plan you make is kept on this computer, with your answers, so you can come back to it. A kept plan holds your request and the plan, never your code.</p>
      {plans.length === 0 ? (
        <p className="text-sm text-muted">None yet. The plan you make below will appear here.</p>
      ) : (
        <ul aria-label="Kept plans" className="divide-y divide-border">
          {plans.map((p) => (
            <li key={p.id} className="space-y-1 py-3 text-sm first:pt-0 last:pb-0">
              <p className="flex flex-wrap items-center gap-2">
                <Badge tone={p.status === "approved" ? "ok" : "warn"}>{p.status === "approved" ? "Approved" : "Not approved"}</Badge>
                <span className="font-medium break-words">{p.task}</span>
              </p>
              <p className="text-xs text-muted">
                {p.repo ? `${p.repo} · ` : ""}
                {formatWhen(p.created_at)} · {summaryLine(p)}
              </p>
              <div className="flex flex-wrap items-center gap-2 pt-1">
                {p.id === openId ? (
                  <span className="text-xs text-muted">Open below</span>
                ) : (
                  <Button onClick={() => onOpen(p.id)} disabled={!p.readable || busyId !== null} busy={busyId === p.id}>
                    Open
                  </Button>
                )}
                {asking === p.id ? (
                  <>
                    <span className="text-xs">Delete this plan and its answers?</span>
                    <Button
                      variant="danger"
                      onClick={() => {
                        setAsking(null);
                        onDelete(p.id);
                      }}
                      disabled={busyId !== null}
                    >
                      Yes, delete it
                    </Button>
                    <Button variant="ghost" onClick={() => setAsking(null)}>
                      Keep it
                    </Button>
                  </>
                ) : (
                  <Button variant="ghost" onClick={() => setAsking(p.id)} disabled={busyId !== null}>
                    Delete
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
