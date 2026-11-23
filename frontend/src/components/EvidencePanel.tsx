"use client";

import { useEffect, useId, useRef, useState } from "react";
import { api } from "@/lib/api";
import { plural } from "@/lib/format";
import { factSummary, loadRemembered, pathProblem, recordedWhen, remember, VERDICT_ORDER, verdictInfo } from "@/lib/repository";
import type { RecheckReport } from "@/lib/types";
import { useAsync } from "@/lib/useAsync";
import { useAuth } from "@/lib/useAuth";
import { Alert, Badge, Button, ErrorBox, Loading } from "./ui";

/**
 * The code a stored version cites, with the facts recorded for each place, and a recheck that says what changed in it since.
 * The recheck reads a folder on this computer and changes nothing. It checks that cited facts still hold, not that the skill's
 * advice is right: the report says so.
 */
export function EvidencePanel({ name, version, kind }: { name: string; version: number; kind: string }) {
  const { hosted } = useAuth();
  const doc = useAsync(() => api.evidence(name, version, kind), `evidence/${kind}/${name}/${version}`);
  const pathId = useId();
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<RecheckReport | null>(null);
  const latest = useRef(0); // which recheck may still show its answer: a slow one for another version is dropped

  useEffect(() => {
    latest.current += 1;
    setReport(null);
    setError(null);
    setBusy(false);
  }, [name, version]);
  useEffect(() => setPath(loadRemembered().path), []);

  if (doc.error) return <ErrorBox error={doc.error} onRetry={doc.reload} />;
  if (!doc.data) return <Loading what="the evidence" />;
  const ev = doc.data.evidence;
  if (!ev) return null;
  const problem = pathProblem(path);

  async function recheck() {
    const mine = ++latest.current;
    setBusy(true);
    setError(null);
    try {
      const r = await api.recheck(name, { repo: path.trim(), version, focus: ev?.focus ?? undefined }, kind);
      if (mine !== latest.current) return;
      remember({ path: path.trim(), focus: loadRemembered().focus }); // the Repository page's own focus is not overwritten
      setReport(r);
    } catch (e) {
      if (mine !== latest.current) return;
      setReport(null);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (mine === latest.current) setBusy(false);
    }
  }

  return (
    <section>
      <h3 className="mb-1 font-semibold">Code it cites</h3>
      <p className="text-sm text-muted">
        {plural(ev.refs.length, "place")} in <strong className="text-text">{ev.repo}</strong>
        {ev.focus ? ` (only ${ev.focus})` : ""}, with the facts the graph had when each was recorded. Recheck them whenever the code may have changed.
      </p>
      <ul className="mt-2 space-y-1.5 text-sm">
        {ev.refs.map((r) => (
          <li key={r.id} className="min-w-0">
            <span className="font-mono break-all">{r.id}</span>
            <span className="text-muted">
              {" "}
              · {factSummary(r)} · {recordedWhen(r, ev)}
            </span>
          </li>
        ))}
      </ul>

      {hosted ? (
        <p className="mt-3 text-sm text-muted">Rechecking reads a folder on this computer, so it is not available in the hosted version. Use the command line: library recheck.</p>
      ) : (
        <div className="mt-3 space-y-2">
          <label htmlFor={pathId} className="text-sm font-medium">
            Folder of the repository to recheck against
          </label>
          <div className="flex flex-wrap items-center gap-2">
            <input
              id={pathId}
              value={path}
              onChange={(e) => setPath(e.target.value)}
              placeholder="C:\code\shop-api"
              autoComplete="off"
              spellCheck={false}
              className="min-w-0 flex-1 rounded-md border border-border bg-bg px-3 py-1.5 font-mono text-sm"
            />
            <Button variant="primary" busy={busy} disabled={!path.trim() || !!problem} onClick={() => void recheck()}>
              Recheck
            </Button>
          </div>
          {problem && <p className="text-sm text-warn">{problem}</p>}
        </div>
      )}

      {error && (
        <div className="mt-3">
          <Alert tone="bad" title="It could not be rechecked">
            {error}
          </Alert>
        </div>
      )}
      {report && <RecheckResult report={report} />}
    </section>
  );
}

function RecheckResult({ report }: { report: RecheckReport }) {
  const ordered = VERDICT_ORDER.flatMap((v) => report.findings.filter((f) => f.status === v));
  return (
    <div className="mt-3 space-y-3" aria-live="polite">
      <Alert tone={report.ok ? "ok" : "warn"} title={report.ok ? "Nothing the skill cites is gone, moved or changed" : "Something the skill cites is gone, moved or changed"}>
        <p className="mb-1.5 text-xs">Version {report.version} compared with the folder as it is now.</p>
        <div className="flex flex-wrap gap-1.5">
          {VERDICT_ORDER.filter((v) => report.counts[v]).map((v) => (
            <Badge key={v} tone={verdictInfo(v).tone} title={verdictInfo(v).hint}>
              {verdictInfo(v).label} {report.counts[v]}
            </Badge>
          ))}
        </div>
      </Alert>
      <ul className="space-y-2">
        {ordered.map((f) => {
          const v = verdictInfo(f.status);
          return (
            <li key={f.ref} className="rounded-lg border border-border p-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={v.tone} title={v.hint}>
                  {v.label}
                </Badge>
                <span className="font-mono break-all">{f.ref}</span>
                {f.recorded && <span className="text-xs text-muted">recorded {f.recorded}</span>}
              </div>
              {f.details.length > 0 && (
                <ul className="mt-1.5 list-disc space-y-0.5 pl-5">
                  {f.details.map((d) => (
                    <li key={d}>{d}</li>
                  ))}
                </ul>
              )}
              {f.candidates.length > 1 && <p className="mt-1 text-muted">Places that look like it: {f.candidates.join(", ")}</p>}
              {f.not_measured.map((n) => (
                <p key={n} className="mt-1 text-xs text-muted">
                  Not compared: {n}
                </p>
              ))}
            </li>
          );
        })}
      </ul>
      {report.notes.map((n) => (
        <p key={n} className="text-xs text-muted">
          {n}
        </p>
      ))}
      <p className="text-xs text-muted">{report.limits}</p>
    </div>
  );
}
