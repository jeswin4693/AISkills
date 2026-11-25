"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Field, NoSkillsHere, SELECT, SkillVersionPicker, useSkillTarget } from "@/components/SkillVersionPicker";
import { Alert, Button, Card, ErrorBox, Loading, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { callsFor, costText, repeatNote, runChoices } from "@/lib/testing";
import { useAsync } from "@/lib/useAsync";
import { useEvalRun } from "@/lib/useEvalRun";
import { CaseEditor } from "./CaseEditor";
import { PreviewPanel } from "./PreviewPanel";
import { ResultView } from "./ResultView";
import { RunHistory } from "./RunHistory";

/** Everything about one version of one skill. Keyed by the pair, so choosing another starts a clean page: no result or choice carries over. */
function LabFor({ name, version, latest, onSaved }: { name: string; version: number; latest: number; onSaved: (version: number) => void }) {
  const preview = useAsync(() => api.evalPreview(name, version), `testing-preview/${name}/${version}`);
  const history = useAsync(() => api.evalRuns(name, version), `testing-history/${name}/${version}`);
  const provider = useAsync(api.provider, "testing-provider");
  const [runId, setRunId] = useState<string | null>(null);
  const { run, error: runError, adopt, stalled, check } = useEvalRun(runId);
  const [repeats, setRepeats] = useState(1);
  const [baseline, setBaseline] = useState(true);
  const [busy, setBusy] = useState<"start" | "retry" | null>(null);
  const [problem, setProblem] = useState<Error | null>(null);
  const [editing, setEditing] = useState(false);

  // A page that is opened (or reloaded) shows the run that is still going, else the latest one, so a result is never lost by leaving the page.
  const rows = history.data;
  useEffect(() => {
    if (runId !== null || !rows || rows.length === 0) return;
    setRunId((rows.find((r) => r.status === "working") ?? rows[0]).id);
  }, [rows, runId]);

  // When a run ends, the list of earlier runs learns of it.
  const status = run?.status;
  const reload = history.reload;
  useEffect(() => {
    if (status === "done" || status === "failed") reload();
  }, [status, reload]);

  const noModel = provider.data !== undefined && !provider.data.configured;
  const working = run?.status === "working";

  async function start() {
    setBusy("start");
    setProblem(null);
    try {
      const r = await api.startEval({ name, version, runs: repeats, baseline });
      setRunId(r.id);
      adopt(r);
      history.reload();
    } catch (e) {
      setProblem(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setBusy(null);
    }
  }

  async function retry() {
    if (!run) return;
    setBusy("retry");
    setProblem(null);
    try {
      adopt(await api.retryEval(run.id));
    } catch (e) {
      setProblem(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setBusy(null);
    }
  }

  if (preview.error) return <ErrorBox error={preview.error} onRetry={preview.reload} />;
  if (!preview.data) return <Loading what={`the test cases of ${name}`} />;
  const p = preview.data;
  const calls = callsFor(p.cases.length, repeats, baseline);
  const note = repeatNote(repeats);
  // Saving test cases makes the next version, so they can only be written on the latest. A skill that needs tools gets no editor: more cases would not make it runnable.
  const canEdit = version === latest;
  const needsCases = !p.runnable && (p.blocker === "no_cases" || p.blocker === "nothing_runnable");

  return (
    <div className="space-y-6">
      {noModel && (
        <Alert tone="warn" title="No AI model is set up">
          A run asks a model, so it cannot start yet. <Link href="/settings" className="underline">Set one up in Settings</Link>.
        </Alert>
      )}
      <PreviewPanel preview={p} canEdit={canEdit} />
      {needsCases && canEdit && <CaseEditor name={name} version={version} onSaved={onSaved} />}
      {p.runnable && canEdit && (editing ? (
        <CaseEditor name={name} version={version} onSaved={onSaved} />
      ) : (
        <div>
          <Button onClick={() => setEditing(true)}>Edit the test cases…</Button>
        </div>
      ))}
      {p.runnable && (
        <Card className="p-4">
          <h2 className="font-semibold">Run it</h2>
          <div className="mt-3 flex flex-wrap items-end gap-x-6 gap-y-3">
            <Field label="Repeat each test">
              {(id) => (
                <select id={id} className={SELECT} value={repeats} onChange={(e) => setRepeats(Number(e.target.value))}>
                  {runChoices(p.limits.max_runs).map((n) => (
                    <option key={n} value={n}>
                      {n === 1 ? "once" : `${n} times`}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={baseline} onChange={(e) => setBaseline(e.target.checked)} />
              <span>
                Also run without the skill <span className="text-muted">(this is what shows whether the skill adds anything)</span>
              </span>
            </label>
          </div>
          <p className="mt-3 text-sm">
            This will make <strong>{costText(calls)}</strong> to your model ({p.cases.length} {p.cases.length === 1 ? "test" : "tests"} × {repeats} {repeats === 1 ? "repeat" : "repeats"}
            {baseline ? " × with and without the skill" : ""}), about {p.skill_tokens} tokens of skill each time. A call that has to be tried again is counted too, so the result may show a few more.
          </p>
          {note && <p className="mt-1 text-sm text-muted">{note}</p>}
          <div className="mt-3">
            <Button variant="primary" busy={busy === "start"} disabled={noModel || working} onClick={() => void start()}>
              {working ? "A run is going…" : "Run the tests"}
            </Button>
          </div>
          {problem && (
            <div className="mt-3">
              <ErrorBox error={problem} />
            </div>
          )}
        </Card>
      )}
      {runId && runError && !run && <ErrorBox error={runError} />}
      {stalled && run?.status === "working" && (
        <Alert tone="warn" title="This page lost touch with the server">
          <p>The run may well still be going: it is kept on the server. {runError?.message}</p>
          <div className="mt-2">
            <Button onClick={check}>Check again</Button>
          </div>
        </Alert>
      )}
      {run && <ResultView run={run} latestVersion={latest} onRetry={() => void retry()} retrying={busy === "retry"} />}
      {history.error ? <ErrorBox error={history.error} onRetry={history.reload} /> : <RunHistory runs={history.data ?? []} openId={runId} onOpen={setRunId} />}
    </div>
  );
}

/** The Testing Lab: a skill's own test cases, run against a model with the skill and without it, graded by code. */
export function TestingLab() {
  const target = useSkillTarget("/testing");
  const { name, version, latest } = target;
  const [saved, setSaved] = useState<string | null>(null);

  const choose = (n: string, v?: number) => {
    setSaved(null);
    target.go(n, v);
  };
  // The page moves to the new version. The notice lives here, not in the editor, because the editor is replaced when the version changes.
  const onSaved = (v: number) => {
    setSaved(`Saved as v${v}. Your test cases are now the latest version, and every older version is kept.`);
    target.reloadVersions();
    target.go(name, v);
  };

  return (
    <>
      <PageHeader
        title="Testing Lab"
        subtitle="Does a skill really help? Its own test cases are sent to a model that has the skill and to one that does not, and code (never a model) checks every reply."
      />
      <div className="space-y-6">
        <SkillVersionPicker target={target} onChoose={choose} emptyTitle="No skills to test yet" emptyText={NoSkillsHere} />
        {saved && (
          <Alert tone="ok" title="Your test cases were saved" onDismiss={() => setSaved(null)}>
            {saved}
          </Alert>
        )}
        {name && version !== undefined && latest !== undefined && <LabFor key={`${name}/${version}`} name={name} version={version} latest={latest} onSaved={onSaved} />}
      </div>
    </>
  );
}
