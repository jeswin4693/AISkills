"use client";

import { countChecks, plural, sortChecks } from "@/lib/format";
import type { Check, CheckStatus } from "@/lib/types";
import { Badge } from "./ui";

const LABEL: Record<CheckStatus, { text: string; tone: "ok" | "warn" | "bad" | "neutral" }> = {
  failed: { text: "FAILED", tone: "bad" },
  warning: { text: "warning", tone: "warn" },
  "not run": { text: "not run", tone: "neutral" },
  passed: { text: "passed", tone: "ok" },
};

function Item({ check }: { check: Check }) {
  const label = LABEL[check.status];
  return (
    <li className="flex gap-2 py-1.5">
      <span className="w-16 shrink-0 pt-0.5">
        <Badge tone={label.tone}>{label.text}</Badge>
      </span>
      <span className="min-w-0 text-sm">
        <span className="font-medium">{check.name}</span>
        {check.detail && <span className="block break-words text-muted">{check.detail}</span>}
      </span>
    </li>
  );
}

/** Everything that needs a person's eye is listed; the checks that passed are folded away behind a count. */
export function CheckList({ checks }: { checks: Check[] }) {
  const sorted = sortChecks(checks);
  const attention = sorted.filter((c) => c.status !== "passed");
  const passed = sorted.filter((c) => c.status === "passed");
  const counts = countChecks(checks);
  return (
    <div>
      <p className="text-sm text-muted">
        {counts.passed} passed · {plural(counts.warning, "warning")} · {counts.failed} failed · {counts["not run"]} not run
      </p>
      {attention.length > 0 && (
        <ul className="mt-1 divide-y divide-border">
          {attention.map((c) => (
            <Item key={c.name} check={c} />
          ))}
        </ul>
      )}
      {passed.length > 0 && (
        <details className="mt-1 text-sm">
          <summary className="cursor-pointer py-1 text-muted hover:text-text">Show the {passed.length} checks that passed</summary>
          <ul className="divide-y divide-border">
            {passed.map((c) => (
              <Item key={c.name} check={c} />
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

export function CheckBadges({ checks }: { checks: Check[] }) {
  const c = countChecks(checks);
  return (
    <span className="flex flex-wrap gap-1">
      {c.failed > 0 && <Badge tone="bad">{c.failed} failed</Badge>}
      {c.warning > 0 && <Badge tone="warn">{plural(c.warning, "warning")}</Badge>}
      <Badge tone="ok">{c.passed} passed</Badge>
      {c["not run"] > 0 && <Badge>{c["not run"]} not run</Badge>}
    </span>
  );
}
