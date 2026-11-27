"use client";

import { Alert, Badge, Button, Card } from "@/components/ui";
import { callText, controlSummary, findingsOf, observationBadge, outcomeInfo, progressText, severityTone, taskState, taskStateText } from "@/lib/scan";
import { staleNote } from "@/lib/testing";
import type { ScanRun, ScanTaskRun } from "@/lib/types";

/**
 * One task run: what was asked, how it ended, what was found, and every step the model took, as PLAIN TEXT. The model (and the skill it was given) wrote all of it, so none of it is
 * ever treated as markup: it goes into text nodes and `<pre>` blocks only.
 */
function TaskRow({ run, control }: { run: ScanTaskRun; control: string | null }) {
  const state = taskState(run);
  const badge = observationBadge(run);
  return (
    <li className="rounded-xl border border-border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <p className="min-w-0 break-words font-medium">{run.scenario.message}</p>
        <Badge>{run.scenario.source}</Badge>
        <Badge tone={state === "finished" ? "neutral" : "warn"}>{taskStateText(state)}</Badge>
        {badge && <Badge tone={badge.tone}>{badge.text}</Badge>}
      </div>
      {run.error && <p className="mt-1 text-sm text-warn">Stopped early: {run.error}</p>}
      {run.observations.length > 0 && (
        <ul className="mt-2 space-y-1 text-sm">
          {run.observations.map((o, i) => (
            <li key={i} className="flex flex-wrap items-baseline gap-2">
              <Badge tone={severityTone(o.severity)}>{o.severity}</Badge>
              <span>
                step {o.turn}: {o.detail}
              </span>
            </li>
          ))}
        </ul>
      )}
      {control && <p className="mt-2 text-sm text-muted">{control}</p>}
      <details className="mt-2 text-sm">
        <summary className="cursor-pointer text-muted">
          Show the steps ({run.turns.length} tool {run.turns.length === 1 ? "call" : "calls"}, {run.model_calls} model {run.model_calls === 1 ? "call" : "calls"})
        </summary>
        {run.turns.length === 0 ? (
          <p className="mt-2 text-muted">The model made no tool calls.</p>
        ) : (
          <ol className="mt-2 space-y-3">
            {run.turns.map((t, i) => (
              <li key={i}>
                <p className="text-xs font-medium text-muted">Step {t.step}</p>
                <pre className="whitespace-pre-wrap break-words rounded bg-surface-2 p-2">{callText(t.call)}</pre>
                <p className="mt-1 text-xs text-muted">What the fake tool answered</p>
                <pre className="whitespace-pre-wrap break-words rounded bg-surface-2 p-2">{t.result}</pre>
              </li>
            ))}
          </ol>
        )}
        {run.reply.trim() && (
          <>
            <p className="mt-3 text-xs font-medium text-muted">What the model finally said</p>
            <pre className="whitespace-pre-wrap break-words rounded bg-surface-2 p-2">{run.reply}</pre>
          </>
        )}
      </details>
    </li>
  );
}

/** A scan: still working (with progress), failed (with the reason and a retry), or finished (the headline, the verdict, what did not run, the findings, every task, the limits). */
export function ScanResultView({
  run, latestVersion, onRetry, retrying,
}: {
  run: ScanRun;
  latestVersion: number | undefined;
  onRetry: () => void;
  retrying: boolean;
}) {
  if (run.status === "working") {
    const { done, total } = run.progress;
    const pct = total > 0 ? Math.round((done / total) * 100) : 0;
    return (
      <Card className="p-4">
        <div role="status" aria-live="polite">
          <p className="font-medium">{progressText(run.progress)}</p>
          <p className="mt-1 text-sm text-muted">
            The model is being asked ({run.name} {run.tag}). You can leave this page: the scan goes on and is kept.
          </p>
        </div>
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-surface-2" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={done} aria-label="Task runs done">
          <div className="h-full bg-accent transition-all" style={{ width: `${pct}%` }} />
        </div>
      </Card>
    );
  }
  if (run.status === "failed" || !run.result) {
    return (
      <Alert tone="bad" title="The scan did not finish">
        <p>{run.error || "No result was kept."}</p>
        {run.retryable && (
          <div className="mt-2">
            <Button className="min-h-11" busy={retrying} onClick={onRetry}>
              Run it again
            </Button>
          </div>
        )}
      </Alert>
    );
  }
  const r = run.result;
  const info = outcomeInfo(r.outcome, r.controlled);
  const stale = staleNote(run.version, latestVersion);
  const findings = findingsOf(r);
  return (
    <div className="space-y-4">
      <Alert tone={info.tone} title={info.title}>
        <p>{info.summary}</p>
        <p className="mt-2 text-sm">{r.verdict}</p>
        <p className="mt-2 text-xs">
          {r.calls} model calls, {r.runs.length} task {r.runs.length === 1 ? "run" : "runs"}
          {r.controlled ? ", with a control run of the same task without the skill when something was found" : ", without a control run"}.
        </p>
      </Alert>
      {stale && (
        <Alert tone="info" title="A newer version exists">
          {stale}
        </Alert>
      )}
      {r.not_run.length > 0 && (
        <section>
          <h3 className="mb-1 font-semibold">What did not run</h3>
          <ul className="list-disc pl-5 text-sm">
            {r.not_run.map((line, i) => (
              <li key={i} className="break-words">
                {line}
              </li>
            ))}
          </ul>
        </section>
      )}
      <section>
        <h3 className="mb-2 font-semibold">Findings</h3>
        {findings.length === 0 ? (
          <p className="text-sm text-muted">The code that judges every call found nothing in the task runs below.</p>
        ) : (
          <ul className="space-y-2">
            {findings.map((f, i) => (
              <li key={i} className="rounded-lg border border-border p-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={severityTone(f.severity)}>{f.severity}</Badge>
                  <span className="font-medium">{f.detail}</span>
                </div>
                <p className="mt-1 break-words text-muted">
                  Task: {f.task} (step {f.step})
                </p>
                {f.evidence && <pre className="mt-1 whitespace-pre-wrap break-words rounded bg-surface-2 p-2 text-xs">{f.evidence}</pre>}
              </li>
            ))}
          </ul>
        )}
      </section>
      <section>
        <h3 className="mb-2 font-semibold">Task by task</h3>
        <ol className="space-y-3">
          {r.runs.map((t, i) => (
            <TaskRow key={i} run={t} control={controlSummary(r, t.scenario.id)} />
          ))}
        </ol>
      </section>
      <p className="text-xs text-muted">{r.limits}</p>
    </div>
  );
}
