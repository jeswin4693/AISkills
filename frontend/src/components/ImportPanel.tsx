"use client";

import Link from "next/link";
import { useId, useState } from "react";
import { api } from "@/lib/api";
import { plural } from "@/lib/format";
import type { ImportResult } from "@/lib/types";
import { CheckList } from "./CheckList";
import { RiskSummary } from "./RiskSummary";
import { Alert, Card } from "./ui";

function ImportResultView({ result, onDismiss }: { result: ImportResult; onDismiss: () => void }) {
  if (result.refused) {
    const failed = result.checks.filter((c) => c.status === "failed").length;
    return (
      <Alert tone="bad" title="Refused: nothing was added to the library" onDismiss={onDismiss}>
        <p className="mb-2">
          {failed > 0 ? `${plural(failed, "check")} failed.` : "The skill has no usable name."} Fix these and import again.
        </p>
        <CheckList checks={result.checks} />
      </Alert>
    );
  }
  const v = result.version!;
  if (!result.created) {
    return (
      <Alert tone="info" title={`Unchanged: '${result.name}' is identical to ${v.tag}`} onDismiss={onDismiss}>
        <p>No new version was made.</p>
        <p className="mt-1">
          <Link href={`/library/${result.name}`} className="font-medium text-accent underline">
            Open the skill
          </Link>
        </p>
      </Alert>
    );
  }
  return (
    <Alert tone="ok" title={`Imported '${result.name}' as ${v.tag}`} onDismiss={onDismiss}>
      <p>
        {result.previous ? `A new version after ${result.previous}; ${plural(result.changes.length, "file")} differ.` : "This is its first version."}{" "}
        <Link href={`/library/${result.name}`} className="font-medium text-accent underline">
          Open the skill
        </Link>
      </p>
      {result.changes.length > 0 && (
        <ul className="mt-2 font-mono text-xs">
          {result.changes.map((c) => (
            <li key={c.path}>
              {c.status.padEnd(8, " ").replace(/ /g, " ")}
              {c.path}
            </li>
          ))}
        </ul>
      )}
      <div className="mt-3">
        <CheckList checks={result.checks} />
      </div>
    </Alert>
  );
}

/** Choose or drop a .zip. The checks run on the server; this only shows what they found. */
export function ImportPanel({ onImported }: { onImported: () => void }) {
  const inputId = useId();
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [testScripts, setTestScripts] = useState(false);
  const [note, setNote] = useState("");
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function upload(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    setResult(null);
    setError(null);
    try {
      const r = await api.importZip(file, { note, testScripts });
      setResult(r);
      if (!r.refused) onImported();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="p-4">
      <h2 className="font-semibold">Import a skill</h2>
      <p className="mt-0.5 text-sm text-muted">
        A <code className="font-mono">.zip</code> of a skill folder (the one with <code className="font-mono">SKILL.md</code>). It is checked first and refused if
        a check fails. Nothing in it is run.
      </p>
      <label
        htmlFor={inputId}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          void upload(e.dataTransfer.files[0]);
        }}
        className={`mt-3 flex cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed px-4 py-6 text-center text-sm transition-colors focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-accent ${
          dragging ? "border-accent bg-accent-soft" : "border-border hover:bg-surface-2"
        } ${busy ? "pointer-events-none opacity-60" : ""}`}
      >
        <span className="font-medium">{busy ? "Checking…" : "Drop a .zip here, or click to choose one"}</span>
        <span className="text-muted">Up to 6 MB</span>
        <input
          id={inputId}
          type="file"
          accept=".zip,application/zip"
          className="sr-only"
          disabled={busy}
          onChange={(e) => {
            void upload(e.target.files?.[0]);
            e.target.value = ""; // so the same file can be chosen again
          }}
        />
      </label>
      <details className="mt-3 text-sm">
        <summary className="cursor-pointer text-muted hover:text-text">Options</summary>
        <div className="mt-2 grid gap-3 sm:grid-cols-2">
          <label className="block">
            <span className="text-muted">Note stored with the version (optional)</span>
            <input
              value={note}
              maxLength={200}
              onChange={(e) => setNote(e.target.value)}
              className="mt-1 block w-full rounded-md border border-border bg-bg px-2 py-1.5"
              placeholder="for example: added a failure step"
            />
          </label>
          <label className="flex items-start gap-2 self-end">
            <input type="checkbox" checked={testScripts} onChange={(e) => setTestScripts(e.target.checked)} className="mt-1" />
            <span>
              Also re-run the skill&apos;s own script tests in the Linux sandbox
              <span className="block text-muted">Only for skills built here. It can take a while.</span>
            </span>
          </label>
        </div>
      </details>
      <div aria-live="polite" className="mt-3 space-y-2">
        {error && <Alert tone="bad" title="The import could not be done" onDismiss={() => setError(null)}>{error}</Alert>}
        {result && <ImportResultView result={result} onDismiss={() => setResult(null)} />}
        {result?.risk && <RiskSummary risk={result.risk} />}
        {result && (
          <p className="text-xs text-muted">Static checks only: nothing was run unless a line says so, and passing is not proof that a skill is safe.</p>
        )}
      </div>
    </Card>
  );
}
