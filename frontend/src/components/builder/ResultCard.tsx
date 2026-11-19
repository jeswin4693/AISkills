"use client";

import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { parseTests, traceability } from "@/lib/builder";
import type { BuildSession, ImportResult } from "@/lib/types";
import { useAsync } from "@/lib/useAsync";
import { CheckBadges, CheckList } from "../CheckList";
import { FileViewer } from "../FileViewer";
import { Alert, Badge, Button, Card } from "../ui";

function Traceability({ session }: { session: BuildSession }) {
  const tests = useAsync(async () => parseTests((await api.buildFile(session.id, "tests/cases.json")).text), `tests/${session.id}`);
  const trace = session.spec ? traceability(session.spec.acceptance_criteria, tests.data ?? []) : [];
  return (
    <section>
      <h3 className="font-semibold">What you asked for, and what covers it</h3>
      <p className="mt-0.5 text-sm text-muted">
        Each way you said you would know it works, next to the test cases written for it. These test cases are <strong>data</strong>: nothing has run them against a
        real agent yet, so they describe what to check, not proof that it passes.
      </p>
      {tests.error ? (
        <p className="mt-2 text-sm text-muted">The test cases could not be read: {tests.error.message}</p>
      ) : trace.length === 0 ? (
        <p className="mt-2 text-sm text-muted">{tests.loading ? "Reading the test cases…" : "No acceptance criteria were recorded."}</p>
      ) : (
        <ul className="mt-2 space-y-3">
          {trace.map((t) => (
            <li key={t.id} className="rounded-lg border border-border p-3 text-sm">
              <p>
                <Badge>{t.id}</Badge> {t.text}
              </p>
              {t.tests.length === 0 ? (
                <p className="mt-1.5 font-medium text-warn">No test case covers this.</p>
              ) : (
                <ul className="mt-1.5 flex flex-wrap gap-1.5">
                  {t.tests.map((x) => (
                    <li key={x.name}>
                      <Badge tone={x.kind === "negative" ? "warn" : x.kind === "edge" ? "info" : "ok"} title={`${x.kind} test`}>
                        {x.kind}: {x.name}
                      </Badge>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function SavePanel({ session, onSession }: { session: BuildSession; onSession: (s: BuildSession) => void }) {
  const r = session.result!;
  const draft = r.status === "draft";
  const [note, setNote] = useState("");
  const [acceptDraft, setAcceptDraft] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refused, setRefused] = useState<ImportResult | null>(null);

  if (session.saved) {
    return (
      <Alert tone="ok" title={`Saved to the library as '${session.saved.name}' ${session.saved.version}`}>
        <Link href={`/library/${session.saved.name}`} className="font-medium text-accent underline">
          Open it in the library
        </Link>{" "}
        to read its versions, export it or install it.
      </Alert>
    );
  }

  async function save() {
    setBusy(true);
    setError(null);
    setRefused(null);
    try {
      const out = await api.saveBuild(session.id, { acceptDraft, note });
      if (out.refused) setRefused(out);
      else onSession(out.session);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="p-4">
      <h3 className="font-semibold">Keep it</h3>
      <p className="mt-0.5 text-sm text-muted">
        Saving puts it in your library through the same checked import as any other skill: if a check fails it is refused. Until you save, it exists only here.
      </p>
      {draft && (
        <div className="mt-3">
          <Alert tone="warn" title="This skill is a DRAFT">
            <p>{r.draft_reason || `${r.counts.failed} check(s) failed.`} Do not rely on it before you have read the checks and the report.</p>
            <label className="mt-2 flex items-start gap-2">
              <input type="checkbox" checked={acceptDraft} onChange={(e) => setAcceptDraft(e.target.checked)} className="mt-1" />
              <span>I understand it is a draft, and I want to keep it anyway.</span>
            </label>
          </Alert>
        </div>
      )}
      <label className="mt-3 block text-sm">
        <span className="text-muted">Note stored with the version (optional)</span>
        <input value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} className="mt-1 block w-full max-w-md rounded-md border border-border bg-bg px-2 py-1.5" />
      </label>
      <div className="mt-3">
        <Button variant="primary" busy={busy} disabled={draft && !acceptDraft} onClick={() => void save()}>
          Save to the library
        </Button>
      </div>
      <div aria-live="polite" className="mt-3 space-y-2">
        {error && (
          <Alert tone="bad" title="It was not saved">
            {error}
          </Alert>
        )}
        {refused && (
          <Alert tone="bad" title="Refused: the library's checks failed, so nothing was added">
            <CheckList checks={refused.checks} />
          </Alert>
        )}
      </div>
    </Card>
  );
}

/** The built skill: what was asked and what covers it, the files, the checks, the report, and the choice to keep it. */
export function ResultCard({ session, onSession }: { session: BuildSession; onSession: (s: BuildSession) => void }) {
  const r = session.result!;
  const draft = r.status === "draft";
  return (
    <div className="space-y-5">
      <Card className="p-5">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold break-all">{r.name}</h2>
          {draft ? <Badge tone="warn">DRAFT</Badge> : <Badge tone="ok">every check that ran passed</Badge>}
          {r.scripts > 0 && <Badge tone="info">{r.scripts} script{r.scripts === 1 ? "" : "s"}</Badge>}
        </div>
        <p className="mt-1 text-sm">{r.description}</p>
        <div className="mt-2">
          <CheckBadges checks={r.checks} />
        </div>
        <p className="mt-2 text-xs text-muted">
          Made with {session.model_calls} model call{session.model_calls === 1 ? "" : "s"}. The checks are structural: they show the skill is consistent, not that
          its instructions are good. Read it before you rely on it.
        </p>
      </Card>

      <SavePanel session={session} onSession={onSession} />

      <Card className="space-y-6 p-5">
        <Traceability session={session} />
        <section>
          <h3 className="mb-2 font-semibold">Files</h3>
          <FileViewer id={`build/${session.id}`} paths={r.files} load={(p) => api.buildFile(session.id, p)} />
        </section>
        <section>
          <h3 className="mb-2 font-semibold">Checks</h3>
          <CheckList checks={r.checks} />
        </section>
        <section>
          <details>
            <summary className="cursor-pointer font-semibold">The build report</summary>
            <pre tabIndex={0} aria-label="Build report" className="mt-2 max-h-96 overflow-auto rounded-lg border border-border bg-bg p-3 font-mono text-xs leading-5 whitespace-pre-wrap break-words">
              {r.report_md}
            </pre>
          </details>
        </section>
      </Card>
    </div>
  );
}
