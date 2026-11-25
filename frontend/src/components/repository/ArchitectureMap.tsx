"use client";

import { useId, useMemo, useState, type KeyboardEvent } from "react";
import { arrowSentences, boxSubtitle, cycleSentences, layoutMap, loopMarks, mapNotes, shortLabel } from "@/lib/architecture";
import { plural } from "@/lib/format";
import type { Architecture } from "@/lib/types";
import { Alert, Badge, Card } from "../ui";

const LEVEL_TONE: Record<string, "ok" | "info" | "warn"> = { full: "ok", standard: "info", basic: "warn" };

/**
 * How a repository is laid out: its top-level folders as boxes and the proven imports between them as arrows. Everything is computed by code from
 * the graph (no model), and drawn here as plain SVG. A guess is never drawn, and the notes under the picture say what was left out.
 */
export function ArchitectureMap({ architecture: arch }: { architecture: Architecture | undefined }) {
  // The selection remembers which answer it was made on, so reading another repository never shows a stale box.
  const [sel, setSel] = useState<{ arch: Architecture; id: string } | null>(null);
  const layout = useMemo(() => (arch ? layoutMap(arch) : null), [arch]);
  const marker = useId().replace(/[^a-zA-Z0-9]/g, "");
  if (!arch || !layout || arch.modules.length === 0) return null;

  const selected = sel && sel.arch === arch ? arch.modules.find((m) => m.id === sel.id) : undefined;
  const marks = loopMarks(arch); // ⇄ for every folder in a loop; the warning outline only where an import that closes a loop starts or ends
  const boxAt = new Map(layout.boxes.map((b) => [b.id, b]));
  const cycles = cycleSentences(arch);
  const pick = (id: string) => setSel({ arch, id });
  const onKey = (id: string) => (e: KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      pick(id);
    }
  };

  return (
    <Card className="p-5">
      <h2 className="text-lg font-semibold">How the code is laid out</h2>
      <p className="mt-1 text-sm text-muted">Folders as boxes; an arrow means files in one folder import files in the other (proven links only).</p>

      {cycles.length > 0 && (
        <div className="mt-3">
          <Alert tone="warn" title="Folders that import each other">
            <ul className="list-disc space-y-0.5 pl-5">
              {cycles.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </Alert>
        </div>
      )}

      <div className="mt-3 overflow-x-auto rounded-md border border-border bg-bg">
        <svg
          role="group"
          aria-label={`Map of ${plural(arch.modules.length, "folder")} and ${plural(arch.arrows.length, "arrow")}`}
          width={layout.width}
          height={layout.height}
          viewBox={`0 0 ${layout.width} ${layout.height}`}
          className="block max-w-none"
        >
          <title>{`Map of ${plural(arch.modules.length, "folder")} and ${plural(arch.arrows.length, "arrow")}`}</title>
          <defs>
            <marker id={`${marker}-head`} viewBox="0 0 10 10" refX="10" refY="5" markerWidth="9" markerHeight="9" markerUnits="userSpaceOnUse" orient="auto">
              <path d="M0 0 L10 5 L0 10 z" className="fill-muted" />
            </marker>
            <marker id={`${marker}-cycle`} viewBox="0 0 10 10" refX="10" refY="5" markerWidth="9" markerHeight="9" markerUnits="userSpaceOnUse" orient="auto">
              <path d="M0 0 L10 5 L0 10 z" className="fill-warn" />
            </marker>
            <marker id={`${marker}-active`} viewBox="0 0 10 10" refX="10" refY="5" markerWidth="9" markerHeight="9" markerUnits="userSpaceOnUse" orient="auto">
              <path d="M0 0 L10 5 L0 10 z" className="fill-accent" />
            </marker>
          </defs>

          {layout.arrows.map((a) => {
            // With a box selected, its arrows stand out and every other arrow fades: a dense map can be read one box at a time.
            const related = !selected || a.from === selected.id || a.to === selected.id;
            const active = !!selected && related && !a.cycle;
            return (
              <g key={`${a.from}>${a.to}`}>
                <path
                  d={a.d}
                  fill="none"
                  strokeWidth={a.width}
                  strokeDasharray={a.cycle ? "6 4" : undefined}
                  markerEnd={`url(#${marker}-${a.cycle ? "cycle" : active ? "active" : "head"})`}
                  className={a.cycle ? "stroke-warn" : active ? "stroke-accent" : "stroke-muted"}
                  opacity={related ? 0.85 : 0.1}
                  data-faded={!related}
                />
                {a.count > 1 && related && (
                  <text x={a.x} y={a.y} textAnchor="middle" dominantBaseline="central" paintOrder="stroke" strokeWidth={4} className="fill-text stroke-bg text-[10px]">
                    {a.count}
                  </text>
                )}
              </g>
            );
          })}

          {arch.modules.map((m) => {
            const b = boxAt.get(m.id);
            if (!b) return null;
            const [files, lines, ...tags] = boxSubtitle(m).split(" · ");
            const isSelected = selected?.id === m.id;
            return (
              <g
                key={m.id}
                role="button"
                tabIndex={0}
                aria-label={`${m.label}: ${boxSubtitle(m)}`}
                aria-pressed={isSelected}
                onClick={() => pick(m.id)}
                onKeyDown={onKey(m.id)}
                className="group cursor-pointer outline-none"
              >
                <title>{`${m.label} (${boxSubtitle(m)})`}</title>
                <rect
                  x={b.x}
                  y={b.y}
                  width={b.w}
                  height={b.h}
                  rx={8}
                  strokeWidth={isSelected ? 3 : 1.5}
                  className={`fill-surface group-focus-visible:stroke-accent ${isSelected ? "stroke-accent" : marks.closes.has(m.id) ? "stroke-warn" : "stroke-border"}`}
                />
                <text x={b.x + 12} y={b.y + 22} className="fill-text text-[13px] font-semibold">
                  {shortLabel(m.label)}
                  {marks.inLoop.has(m.id) ? " ⇄" : ""}
                </text>
                <text x={b.x + 12} y={b.y + 40} className="fill-muted text-[11px]">
                  {files} · {lines}
                </text>
                {tags.length > 0 && (
                  <text x={b.x + 12} y={b.y + 55} className="fill-muted text-[11px] italic">
                    {tags.join(" · ")}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      </div>

      <details className="mt-3 text-sm">
        <summary className="cursor-pointer font-medium">The arrows as a list</summary>
        {arch.arrows.length === 0 ? (
          <p className="mt-1 text-muted">No imports between folders were found.</p>
        ) : (
          <ul className="mt-1 list-disc space-y-0.5 pl-5">
            {arrowSentences(arch).map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        )}
      </details>

      <div className="mt-4 rounded-md border border-border p-4" aria-live="polite">
        {!selected ? (
          <p className="text-sm text-muted">Select a box to see what is inside it.</p>
        ) : (
          <div className="space-y-3 text-sm">
            <div>
              <h3 className="font-semibold break-all">Inside {selected.label}</h3>
              <p className="text-muted">{boxSubtitle(selected)}</p>
            </div>
            <ul className="flex flex-wrap items-center gap-x-3 gap-y-1">
              {Object.entries(selected.languages).map(([lang, count]) => (
                <li key={lang} className="flex items-center gap-1.5">
                  <span className="font-medium">{lang}</span>
                  <span className="text-muted">{plural(count, "file")}</span>
                  <Badge tone={LEVEL_TONE[arch.language_levels[lang]] ?? "neutral"}>{arch.language_levels[lang] ?? "unknown"}</Badge>
                  {arch.imports_not_read.includes(lang) && <span className="text-xs text-warn">imports not read</span>}
                </li>
              ))}
            </ul>
            {selected.members.length > 0 && (
              <p>
                <span className="font-medium">Folders folded into this box:</span> <span className="font-mono break-all">{selected.members.join(", ")}</span>
              </p>
            )}
            {selected.file_list.length > 0 && (
              <div>
                <h4 className="font-medium">Biggest files</h4>
                <ul className="mt-1 space-y-0.5">
                  {selected.file_list.map((f) => (
                    <li key={f.path} className="break-all">
                      <span className="font-mono">{f.path}</span> <span className="text-muted">· {plural(f.lines, "line")}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {selected.top_functions.length > 0 && (
              <div>
                <h4 className="font-medium">Biggest functions</h4>
                <ul className="mt-1 space-y-0.5">
                  {selected.top_functions.map((f) => (
                    <li key={`${f.file}:${f.line}:${f.name}`} className="break-all">
                      <span className="font-mono">{f.name}</span> <span className="text-muted">· {f.file}:{f.line}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>

      {mapNotes(arch).map((note) => (
        <p key={note} className="mt-2 text-xs text-muted">
          {note}
        </p>
      ))}
    </Card>
  );
}
