"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Field, SELECT } from "@/components/SkillVersionPicker";
import { Alert, Badge, Button, Card, Empty, ErrorBox, Loading, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { formatWhen, relativeTime } from "@/lib/format";
import { costNote, draftNote, matchesPage, maxCallsText, runChoices, scanLine, taskChoices } from "@/lib/scan";
import { parseVersion, pickVersion } from "@/lib/testing";
import { useAsync } from "@/lib/useAsync";
import { useScanRun } from "@/lib/useScanRun";
import { ScanResultView } from "./ScanResult";

const KINDS = [
  { key: "skill", label: "Skill" },
  { key: "agent", label: "Agent" },
];

/** Which skill or agent and which version the page is about, kept in the address (`?kind=&name=&version=`) so a link can point straight at one. */
function useScanTarget() {
  const router = useRouter();
  const params = useSearchParams();
  const kind = params.get("kind") === "agent" ? "agent" : "skill";
  const name = params.get("name") ?? "";
  const wanted = parseVersion(params.get("version"));
  const entries = useAsync(() => api.listSkills(kind), `scan-entries/${kind}`);
  const versions = useAsync(() => (name ? api.versions(name, kind) : Promise.resolve(null)), `scan-versions/${kind}/${name}`);
  const list = versions.data?.versions ?? [];
  const version = pickVersion(list, wanted);
  const latest = list.length ? Math.max(...list.map((v) => v.version)) : undefined;
  const go = (k: string, n: string, v?: number) =>
    router.replace(`/scan?kind=${k}${n ? `&name=${encodeURIComponent(n)}${v ? `&version=${v}` : ""}` : ""}`, { scroll: false });
  return { kind, name, version, latest, list, entries, versions, go };
}

/** Everything about one version of one entry. Keyed by the three, so choosing another starts a clean page: no result or choice carries over. */
function ScanFor({ kind, name, version, latest }: { kind: string; name: string; version: number; latest: number }) {
  const [repeats, setRepeats] = useState(1);
  const [tasks, setTasks] = useState(5);
  const [control, setControl] = useState(true);
  const [draft, setDraft] = useState(true);
  const preview = useAsync(
    () => api.scanPreview({ name, version, kind, runs: repeats, scenarios: tasks, control, draft }),
    `scan-preview/${kind}/${name}/${version}/${repeats}/${tasks}/${control}/${draft}`,
  );
  const history = useAsync(() => api.scanRuns({ name, version, kind }), `scan-history/${kind}/${name}/${version}`);
  const provider = useAsync(api.provider, "scan-provider");
  const [runId, setRunId] = useState<string | null>(null);
  const { run: opened, error: runError, adopt, stalled, check } = useScanRun(runId);
  // A page shows only a scan that is about its own kind, entry and version (a skill and an agent can share a name and a version number).
  const run = opened && matchesPage(opened, { kind, name, version }) ? opened : undefined;
  const [busy, setBusy] = useState<"start" | "retry" | null>(null);
  const [problem, setProblem] = useState<Error | null>(null);

  // A page that is opened (or reloaded) shows the scan that is still going, else the latest one, so a result is never lost by leaving the page.
  const rows = history.data;
  useEffect(() => {
    if (runId !== null || !rows || rows.length === 0) return;
    setRunId((rows.find((r) => r.status === "working") ?? rows[0]).id);
  }, [rows, runId]);

  // When a scan ends, the list of earlier scans learns of it.
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
      const r = await api.startScan({ name, version, kind, runs: repeats, scenarios: tasks, control, draft });
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
      adopt(await api.retryScan(run.id));
    } catch (e) {
      setProblem(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setBusy(null);
    }
  }

  if (preview.error && !preview.data) return <ErrorBox error={preview.error} onRetry={preview.reload} />;
  if (!preview.data) return <Loading what={`the tasks for ${name}`} />;
  const p = preview.data;

  return (
    <div className="space-y-6">
      {noModel && (
        <Alert tone="warn" title="No AI model is set up">
          A scan asks a model, so it cannot start yet. <Link href="/settings" className="underline">Set one up in Settings</Link>.
        </Alert>
      )}
      <Card className="p-4">
        <h2 className="font-semibold">What would run</h2>
        <p className="mt-1 text-sm text-muted">
          The model is given the {kind}&apos;s instructions and each of these ordinary tasks in turn, and works on a fake machine with fake tools and planted fake secrets. Code, never a
          model, judges everything it does. {p.limits_text}
        </p>
        <ol className="mt-3 space-y-2">
          {p.tasks.map((t) => (
            <li key={t.id} className="flex flex-wrap items-baseline gap-2 text-sm">
              <Badge>{t.source}</Badge>
              <span className="min-w-0 break-words">{t.message}</span>
            </li>
          ))}
        </ol>
        {p.draft && <p className="mt-2 text-sm text-muted">{draftNote(kind, p.max_tasks)}</p>}
        <p className="mt-2 text-sm">
          {p.declared ? <>It declares these kinds of tool: {p.declared.join(", ")}. </> : <>It declares no kinds of tool the scan can compare with. </>}
          {p.scripts.length > 0 && <>It ships scripts ({p.scripts.join(", ")}): they are listed, never run. </>}
        </p>
      </Card>
      <Card className="p-4">
        <h2 className="font-semibold">Run it</h2>
        <div className="mt-3 flex flex-wrap items-end gap-x-6 gap-y-3">
          <Field label="Repeat each task">
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
          <Field label="Tasks to run">
            {(id) => (
              <select id={id} className={SELECT} value={tasks} onChange={(e) => setTasks(Number(e.target.value))}>
                {taskChoices(p.limits.max_scenarios).map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            )}
          </Field>
        </div>
        <div className="mt-3 space-y-1.5">
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={control} onChange={(e) => setControl(e.target.checked)} />
            <span>
              Also run a task that produced something without the {kind} <span className="text-muted">(this is what shows whether the {kind} or the model did it)</span>
            </span>
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={draft} onChange={(e) => setDraft(e.target.checked)} />
            <span>
              Let a model draft one more task from the description <span className="text-muted">(one more model call)</span>
            </span>
          </label>
        </div>
        <p className="mt-3 text-sm">
          This will make <strong>{maxCallsText(p.max_calls, p.draft)}</strong> to your model. {costNote()}
        </p>
        <div className="mt-3">
          <Button variant="primary" className="min-h-11" busy={busy === "start"} disabled={noModel || working} onClick={() => void start()}>
            {working ? "A scan is going…" : "Run the scan"}
          </Button>
        </div>
        {problem && (
          <div className="mt-3">
            <ErrorBox error={problem} />
          </div>
        )}
      </Card>
      {runId && runError && !run && <ErrorBox error={runError} />}
      {stalled && run?.status === "working" && (
        <Alert tone="warn" title="This page lost touch with the server">
          <p>The scan may well still be going: it is kept on the server. {runError?.message}</p>
          <div className="mt-2">
            <Button className="min-h-11" onClick={check}>
              Check again
            </Button>
          </div>
        </Alert>
      )}
      {run && <ScanResultView run={run} latestVersion={latest} onRetry={() => void retry()} retrying={busy === "retry"} />}
      {history.error ? (
        <ErrorBox error={history.error} onRetry={history.reload} />
      ) : (
        (history.data ?? []).length > 0 && (
          <section>
            <h3 className="mb-2 font-semibold">Earlier scans of this version</h3>
            <Card>
              <ul className="divide-y divide-border">
                {(history.data ?? []).map((r) => (
                  <li key={r.id}>
                    <button
                      type="button"
                      onClick={() => setRunId(r.id)}
                      aria-current={r.id === runId ? "true" : undefined}
                      className={`block min-h-11 w-full px-4 py-2.5 text-left text-sm ${r.id === runId ? "bg-accent-soft" : "hover:bg-surface-2"}`}
                    >
                      <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
                        <span className="font-medium">{r.tag}</span>
                        <span className="text-muted" title={formatWhen(r.created_at)}>
                          {relativeTime(r.created_at)}
                        </span>
                        <span>{scanLine(r)}</span>
                        {r.runs > 1 && <Badge>{r.runs} repeats</Badge>}
                        {r.status === "failed" && <Badge tone="bad">failed</Badge>}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </Card>
          </section>
        )
      )}
    </div>
  );
}

/** The Behaviour Scan: a skill's or agent's instructions are run by a model on fake tools with planted fake secrets, and code (never a model) says what it did. Never "safe". */
export function ScanPage() {
  const target = useScanTarget();
  const { kind, name, version, latest, list, entries, versions } = target;
  return (
    <>
      <PageHeader
        title="Behaviour Scan"
        subtitle="What does a model do when it follows a skill or an agent? Its instructions are run on fake tools with planted fake secrets, and code (never a model) judges every step. A clean scan is evidence, not proof."
      />
      <div className="space-y-6">
        {entries.error ? (
          <ErrorBox error={entries.error} onRetry={entries.reload} />
        ) : entries.data === undefined ? (
          <Loading what={kind === "agent" ? "your agents" : "your skills"} />
        ) : (
          <Card className="p-4">
            <div className="flex flex-wrap items-end gap-4">
              <Field label="What to scan">
                {(id) => (
                  <select id={id} className={SELECT} value={kind} onChange={(e) => target.go(e.target.value, "")}>
                    {KINDS.map((k) => (
                      <option key={k.key} value={k.key}>
                        {k.label}
                      </option>
                    ))}
                  </select>
                )}
              </Field>
              {entries.data.length > 0 && (
                <Field label={kind === "agent" ? "Agent" : "Skill"}>
                  {(id) => (
                    <select id={id} className={SELECT} value={name} onChange={(e) => target.go(kind, e.target.value)}>
                      <option value="">Choose one…</option>
                      {entries.data?.map((s) => (
                        <option key={s.name} value={s.name}>
                          {s.name}
                        </option>
                      ))}
                    </select>
                  )}
                </Field>
              )}
              {name && list.length > 0 && version !== undefined && (
                <Field label="Version">
                  {(id) => (
                    <select id={id} className={SELECT} value={version} onChange={(e) => target.go(kind, name, Number(e.target.value))}>
                      {list.map((v) => (
                        <option key={v.version} value={v.version}>
                          {v.tag}
                          {v.version === latest ? " (latest)" : ""}
                        </option>
                      ))}
                    </select>
                  )}
                </Field>
              )}
            </div>
            {entries.data.length === 0 && (
              <div className="mt-3">
                <Empty title={kind === "agent" ? "No agents to scan yet" : "No skills to scan yet"}>
                  Build one in the Builder or import one into the{" "}
                  <Link href="/library" className="underline">
                    Library
                  </Link>
                  , then come back. A plugin or an MCP server is checked through the skills and agents it holds.
                </Empty>
              </div>
            )}
          </Card>
        )}
        {name && versions.error && <ErrorBox error={versions.error} onRetry={versions.reload} />}
        {name && !versions.error && versions.data === undefined && <Loading what={name} />}
        {name && version !== undefined && latest !== undefined && <ScanFor key={`${kind}/${name}/${version}`} kind={kind} name={name} version={version} latest={latest} />}
      </div>
    </>
  );
}
