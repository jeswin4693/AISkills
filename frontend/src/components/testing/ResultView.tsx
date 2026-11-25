"use client";

import { Alert, Badge, Button, Card } from "@/components/ui";
import { checkWords, failureLines, outcomeInfo, progressText, repeatNote, sideSummary, staleNote } from "@/lib/testing";
import type { EvalAttempt, EvalCase, EvalRun } from "@/lib/types";

const SIDE_TONE = { ok: "ok", warn: "warn", bad: "bad", none: "neutral" } as const;

/** One side of a case: how it went, each failed check in words, and the replies themselves (as plain text) behind a disclosure. */
function Side({ title, attempt }: { title: string; attempt: EvalAttempt | null }) {
  const side = sideSummary(attempt);
  const lines = failureLines(attempt);
  return (
    <div className="min-w-0 rounded-lg border border-border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">{title}</span>
        <Badge tone={SIDE_TONE[side.tone]}>{side.text}</Badge>
      </div>
      {lines.length > 0 && (
        <ul className="mt-2 list-disc pl-5 text-sm text-bad">
          {lines.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      )}
      {attempt && attempt.tries.length > 0 && (
        <details className="mt-2 text-sm">
          <summary className="cursor-pointer text-muted">Show the {attempt.tries.length === 1 ? "reply" : "replies"}</summary>
          <ol className="mt-2 space-y-3">
            {attempt.tries.map((t, i) => (
              <li key={i}>
                <p className="text-xs font-medium text-muted">
                  {attempt.tries.length > 1 ? `Try ${i + 1}: ` : ""}
                  {t.passed ? "passed every check" : "failed a check"}
                </p>
                <pre className="whitespace-pre-wrap break-words rounded bg-surface-2 p-2">
                  {t.reply}
                  {t.cut ? "\n… (cut: the reply was longer than is kept)" : ""}
                </pre>
                <ul className="mt-1 space-y-0.5 text-xs">
                  {t.checks.map((c, j) => (
                    <li key={j} className={c.passed ? "text-muted" : "text-bad"}>
                      {c.passed ? "passed" : "failed"}: the reply {checkWords(c)}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ol>
        </details>
      )}
    </div>
  );
}

function CaseRow({ c }: { c: EvalCase }) {
  return (
    <li className="rounded-xl border border-border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="font-medium">{c.name}</h4>
        <Badge>{c.kind}</Badge>
      </div>
      <details className="mt-1 text-sm">
        <summary className="cursor-pointer text-muted">Message sent</summary>
        <pre className="mt-1 whitespace-pre-wrap break-words rounded bg-surface-2 p-2">
          {c.message}
          {c.message_cut ? " …" : ""}
        </pre>
      </details>
      <div className={`mt-2 grid gap-3 ${c.baseline ? "sm:grid-cols-2" : ""}`}>
        <Side title="With the skill" attempt={c.with_skill} />
        {c.baseline && <Side title="Without it" attempt={c.baseline} />}
      </div>
    </li>
  );
}

/** A run: still working (with progress), failed (with the reason and a retry), or finished (the headline, the two counts, every case, the limits). */
export function ResultView({
  run, latestVersion, onRetry, retrying,
}: {
  run: EvalRun;
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
            The model is being asked ({run.name} {run.tag}). You can leave this page: the run goes on and is kept.
          </p>
        </div>
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-surface-2" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={done} aria-label="Tests done">
          <div className="h-full bg-accent transition-all" style={{ width: `${pct}%` }} />
        </div>
      </Card>
    );
  }
  if (run.status === "failed" || !run.result) {
    return (
      <Alert tone="bad" title="The run did not finish">
        <p>{run.error || "No result was kept."}</p>
        {run.retryable && (
          <div className="mt-2">
            <Button busy={retrying} onClick={onRetry}>
              Run it again
            </Button>
          </div>
        )}
      </Alert>
    );
  }
  const r = run.result;
  const info = outcomeInfo(r.outcome, { skillTokens: r.skill_tokens, cases: r.cases.length, minCases: r.min_cases });
  const stale = staleNote(run.version, latestVersion);
  const note = repeatNote(r.runs);
  return (
    <div className="space-y-4">
      <Alert tone={info.tone} title={info.title}>
        <p>{info.text}</p>
        <p className="mt-2 text-sm">
          <strong>With the skill:</strong> {r.with_skill.passed} of {r.with_skill.total} runs passed every check.{" "}
          {r.baseline && (
            <>
              <strong>Without it:</strong> {r.baseline.passed} of {r.baseline.total}.{" "}
            </>
          )}
          <span className="text-muted">
            ({r.calls} model calls, {r.runs === 1 ? "each test once" : `each test ${r.runs} times`}, about {r.skill_tokens} tokens for the skill)
          </span>
        </p>
      </Alert>
      {stale && <Alert tone="info" title="A newer version exists">{stale}</Alert>}
      {note && r.runs < 3 && r.outcome !== "not_run" && <p className="text-sm text-muted">{note}</p>}
      <section>
        <h3 className="mb-2 font-semibold">Case by case</h3>
        <ol className="space-y-3">
          {r.cases.map((c) => (
            <CaseRow key={c.name} c={c} />
          ))}
        </ol>
        {r.skipped.length > 0 && (
          <div className="mt-3 text-sm text-muted">
            <p className="font-medium">Not run</p>
            <ul className="list-disc pl-5">
              {r.skipped.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
          </div>
        )}
      </section>
      <p className="text-xs text-muted">{r.limits}</p>
    </div>
  );
}
