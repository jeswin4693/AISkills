import { diffStats, parseDiff, type DiffLineKind } from "@/lib/diff";
import type { FileChange } from "@/lib/types";
import { Badge } from "./ui";

const LINE: Record<DiffLineKind, string> = {
  add: "bg-add-bg",
  del: "bg-del-bg",
  hunk: "bg-surface-2 text-muted",
  meta: "text-muted italic",
  ctx: "",
};

const SIGN: Record<DiffLineKind, string> = { add: "added line", del: "removed line", hunk: "", meta: "", ctx: "" };

/** One file's changes. Text is rendered as text, never as markup, and the sign of each line is also readable aloud. */
export function DiffView({ change }: { change: FileChange }) {
  const lines = parseDiff(change.text);
  const { added, removed } = diffStats(change.text);
  const tone = change.status === "added" ? "ok" : change.status === "removed" ? "bad" : "info";
  return (
    <details open className="rounded-lg border border-border bg-surface">
      <summary className="flex cursor-pointer flex-wrap items-center gap-2 px-3 py-2">
        <Badge tone={tone}>{change.status}</Badge>
        <span className="font-mono text-sm break-all">{change.path}</span>
        {!change.binary && (added > 0 || removed > 0) && (
          <span className="ml-auto text-xs text-muted">
            <span className="text-ok">+{added}</span> <span className="text-bad">−{removed}</span>
          </span>
        )}
      </summary>
      {change.binary ? (
        <p className="border-t border-border px-3 py-2 text-sm text-muted">A binary file: its content changed, and a text comparison is not shown.</p>
      ) : (
        <div className="overflow-x-auto border-t border-border font-mono text-xs leading-5" role="group" aria-label={`Changes in ${change.path}`}>
          {lines.map((l, i) => (
            <div key={i} className={`px-3 whitespace-pre ${LINE[l.kind]}`}>
              {SIGN[l.kind] && <span className="sr-only">{SIGN[l.kind]}: </span>}
              {l.text || " "}
            </div>
          ))}
        </div>
      )}
    </details>
  );
}
