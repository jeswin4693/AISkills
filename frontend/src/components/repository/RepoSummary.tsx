"use client";

import { plural } from "@/lib/format";
import { callSummary, languageRows, sourceNote } from "@/lib/repository";
import type { RepoAnalysis } from "@/lib/types";
import { Badge, Card } from "../ui";

const LEVEL_TONE: Record<string, "ok" | "info" | "warn"> = { full: "ok", standard: "info", basic: "warn" };

/** What the graph says about a repository. Every number is computed from parsed code; no model took part. */
export function RepoSummary({ analysis: a }: { analysis: RepoAnalysis }) {
  const rows = languageRows(a.stats);
  const functions = (a.stats.symbols.function ?? 0) + (a.stats.symbols.method ?? 0);
  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold break-all">{a.name}</h2>
        <div className="flex flex-wrap items-center gap-1.5">
          {a.source.kind === "github" && <Badge tone="info" title="Downloaded from a public GitHub repository">from GitHub</Badge>}
          {a.focus && <Badge tone="info" title="Only this folder of the repository was read">focus: {a.focus}</Badge>}
        </div>
      </div>
      {sourceNote(a.source).map((line) => (
        <p key={line} className="mt-1 text-xs text-muted">
          {line}
        </p>
      ))}
      <p className="mt-1 text-sm text-muted">
        {plural(a.stats.files, "file")} ({a.stats.test_files} of them tests), {a.stats.lines.toLocaleString()} lines, {plural(functions, "function")} and methods,{" "}
        {a.stats.commits_read === null ? "no git history" : plural(a.stats.commits_read, "commit") + " read"}.
      </p>

      <div className="mt-4 grid gap-5 md:grid-cols-2">
        <section>
          <h3 className="font-semibold">Languages, and how deeply each is read</h3>
          <ul className="mt-2 space-y-1.5 text-sm">
            {rows.map((r) => (
              <li key={r.name} className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                <span className="font-medium">{r.name}</span>
                <span className="text-muted">{plural(r.files, "file")}</span>
                <Badge tone={LEVEL_TONE[r.level] ?? "neutral"} title={r.note}>{r.level}</Badge>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-muted">{callSummary(a.stats)}</p>
        </section>

        <section>
          <h3 className="font-semibold">Most depended on</h3>
          {a.hotspots.core_symbols.length === 0 ? (
            <p className="mt-2 text-sm text-muted">No function in this repository is called from other non-test code that the graph could prove.</p>
          ) : (
            <ol className="mt-2 space-y-1 text-sm">
              {a.hotspots.core_symbols.slice(0, 6).map((s) => (
                <li key={s.id} className="min-w-0">
                  <span className="font-mono break-all">{s.name}</span>{" "}
                  <span className="text-muted">
                    {s.file}:{s.line} · {plural(s.fan_in, "caller")}
                  </span>
                </li>
              ))}
            </ol>
          )}
          {a.hotspots.risky_files.length > 0 ? (
            <>
              <h3 className="mt-3 font-semibold">Busy and imported by many</h3>
              <ul className="mt-1 space-y-1 text-sm">
                {a.hotspots.risky_files.slice(0, 4).map((f) => (
                  <li key={f.path} className="break-all">
                    <span className="font-mono">{f.path}</span> <span className="text-muted">· {plural(f.importers, "importer")}, {plural(f.commits, "commit")}</span>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="mt-2 text-xs text-muted">{a.hotspots.note}</p>
          )}
        </section>
      </div>

      <p className="mt-4 text-sm text-muted">
        <strong className="text-text">{plural(a.dead_code.internal, "internal function")}</strong> and {plural(a.dead_code.exported, "exported function")} look unused. These are
        candidates only: a call the graph cannot see (a name built at run time, a call from outside) would make one look unused.
      </p>
      {a.notes.length > 0 && (
        <ul className="mt-2 list-disc space-y-0.5 pl-5 text-xs text-muted">
          {a.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
    </Card>
  );
}
