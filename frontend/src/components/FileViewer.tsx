"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { shortHash } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";
import { ErrorBox, Loading } from "./ui";

/** The files of one version, and the text of the one you pick. The API checks the whole version against its hashes first. */
export function FileViewer({ name, version, files }: { name: string; version: number; files: Record<string, string> }) {
  const paths = Object.keys(files).sort((a, b) => (a === "SKILL.md" ? -1 : b === "SKILL.md" ? 1 : a.localeCompare(b)));
  const [picked, setPicked] = useState<string | null>(null);
  const path = picked && paths.includes(picked) ? picked : (paths[0] ?? null);
  const file = useAsync(() => (path ? api.file(name, version, path) : Promise.resolve(undefined)), `${name}/${version}/${path}`);

  if (paths.length === 0) return <p className="text-sm text-muted">This version has no files.</p>;
  return (
    <div className="grid gap-3 md:grid-cols-[14rem_1fr]">
      <ul aria-label="Files" className="max-h-96 space-y-0.5 overflow-y-auto text-sm md:max-h-[28rem]">
        {paths.map((p) => (
          <li key={p}>
            <button
              type="button"
              onClick={() => setPicked(p)}
              aria-current={p === path ? "true" : undefined}
              title={`sha256 ${shortHash(files[p])}…`}
              className={`block w-full rounded px-2 py-1 text-left font-mono text-xs break-all ${p === path ? "bg-accent-soft text-accent" : "hover:bg-surface-2"}`}
            >
              {p}
            </button>
          </li>
        ))}
      </ul>
      <div className="min-w-0">
        {file.error ? (
          <ErrorBox error={file.error} onRetry={file.reload} />
        ) : file.loading && !file.data ? (
          <Loading what={path ?? "file"} />
        ) : file.data?.binary ? (
          <p className="rounded-lg border border-border bg-surface-2 p-3 text-sm text-muted">A binary file: its text is not shown.</p>
        ) : (
          <pre
            tabIndex={0}
            aria-label={path ? `Text of ${path}` : "File text"}
            className="max-h-96 overflow-auto rounded-lg border border-border bg-bg p-3 font-mono text-xs leading-5 whitespace-pre-wrap break-words md:max-h-[28rem]"
          >
            {file.data?.text || "(empty file)"}
          </pre>
        )}
      </div>
    </div>
  );
}
