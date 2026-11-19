"use client";

import { useState } from "react";
import { shortHash } from "@/lib/format";
import type { FileText } from "@/lib/types";
import { useAsync } from "@/lib/useAsync";
import { ErrorBox, Loading } from "./ui";

/**
 * A list of files and the text of the one you pick. Used for a stored version and for a build that is not saved yet:
 * `load` says how to fetch one file, `id` says which collection of files this is (it keys the cache of what was loaded).
 */
export function FileViewer({
  id, paths: given, hashes, load,
}: {
  id: string;
  paths: string[];
  hashes?: Record<string, string>;
  load: (path: string) => Promise<FileText>;
}) {
  const paths = [...given].sort((a, b) => (a === "SKILL.md" ? -1 : b === "SKILL.md" ? 1 : a.localeCompare(b)));
  const [picked, setPicked] = useState<string | null>(null);
  const path = picked && paths.includes(picked) ? picked : (paths[0] ?? null);
  const file = useAsync(() => (path ? load(path) : Promise.resolve(undefined)), `${id}/${path}`);

  if (paths.length === 0) return <p className="text-sm text-muted">There are no files.</p>;
  return (
    <div className="grid gap-3 md:grid-cols-[14rem_1fr]">
      <ul aria-label="Files" className="max-h-96 space-y-0.5 overflow-y-auto text-sm md:max-h-[28rem]">
        {paths.map((p) => (
          <li key={p}>
            <button
              type="button"
              onClick={() => setPicked(p)}
              aria-current={p === path ? "true" : undefined}
              title={hashes?.[p] ? `sha256 ${shortHash(hashes[p])}…` : undefined}
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
