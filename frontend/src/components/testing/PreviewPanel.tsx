"use client";

import { Alert, Badge, Card } from "@/components/ui";
import { blockerAdvice, checkWords } from "@/lib/testing";
import type { EvalPreview } from "@/lib/types";

/** What a run would do: the test cases and their checks. Or, for a skill that cannot be run, why not and what a person can do. */
export function PreviewPanel({ preview }: { preview: EvalPreview }) {
  if (!preview.runnable) {
    return (
      <Alert tone="warn" title={`${preview.name} ${preview.tag} cannot be run here`}>
        <p>
          <strong>Why:</strong> {preview.reason}.
        </p>
        <p className="mt-1">{blockerAdvice(preview.blocker)}</p>
        {preview.skipped.length > 0 && (
          <ul className="mt-2 list-disc pl-5 text-muted">
            {preview.skipped.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        )}
      </Alert>
    );
  }
  return (
    <Card className="p-4">
      <h2 className="font-semibold">What would run</h2>
      <p className="mt-1 text-sm text-muted">
        Each test is a message sent to a model that has the skill, and again to one that does not. Code (not a model) then checks every reply.
      </p>
      <ol className="mt-3 space-y-3">
        {preview.cases.map((c) => (
          <li key={c.name} className="rounded-lg border border-border p-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{c.name}</span>
              <Badge>{c.kind}</Badge>
            </div>
            <p className="mt-1 text-xs font-medium text-muted">Message sent</p>
            <pre className="whitespace-pre-wrap break-words rounded bg-surface-2 p-2 text-sm">
              {c.message}
              {c.message_cut ? " …" : ""}
            </pre>
            <p className="mt-2 text-xs font-medium text-muted">The reply must pass</p>
            <ul className="list-disc pl-5 text-sm">
              {c.checks.map((k, i) => (
                <li key={i}>
                  {checkWords(k)}
                  {k.why && <span className="text-muted"> ({k.why})</span>}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ol>
      {preview.skipped.length > 0 && (
        <div className="mt-3 text-sm text-muted">
          <p className="font-medium">Not run</p>
          <ul className="list-disc pl-5">
            {preview.skipped.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}
