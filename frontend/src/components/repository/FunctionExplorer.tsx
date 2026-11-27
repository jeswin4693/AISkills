"use client";

import { useId, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { api } from "@/lib/api";
import { callNotes, edgeSentences, layoutCalls, matchLine, nodeCounts, nodeSubtitle, searchNote, shortName, summarySentence } from "@/lib/callgraph";
import { plural } from "@/lib/format";
import type { CallGraph, CoreSymbol, FunctionSearch } from "@/lib/types";
import { Alert, Badge, Button, Card, Spinner } from "../ui";

const MAX_STARTERS = 6;

/**
 * One function and the functions around it: who calls it on the left, what it calls on the right, one step or two. Computed by code from the graph
 * (no model, nothing is run) and drawn as plain SVG. A call is drawn only when the graph proves it; the notes under the picture say what was left out.
 * `path` and `focus` are what was last read, not what the boxes above say now.
 */
export function FunctionExplorer({ path, focus, starters }: { path: string; focus: string; starters: CoreSymbol[] }) {
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<FunctionSearch | null>(null);
  const [searching, setSearching] = useState(false);
  const [graph, setGraph] = useState<CallGraph | null>(null);
  const [depth, setDepth] = useState<1 | 2>(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trail, setTrail] = useState<string[]>([]); // the functions looked at, the last one being the one on show: Back goes one step along it
  const seq = useRef(0); // an answer that comes back after a newer request was made is ignored
  const searchSeq = useRef(0);
  const queryId = useId();
  const marker = useId().replace(/[^a-zA-Z0-9]/g, "");
  const layout = useMemo(() => (graph ? layoutCalls(graph) : null), [graph]);

  async function show(id: string, steps: 1 | 2, how: "push" | "stay" | "pop") {
    const mine = ++seq.current;
    setLoading(true);
    setError(null);
    try {
      const g = await api.callGraph(path, focus, id, steps);
      if (mine !== seq.current) return;
      setGraph(g);
      setTrail((t) => (how === "push" ? (t[t.length - 1] === id ? t : [...t, id]) : how === "pop" ? t.slice(0, -1) : t));
    } catch (err) {
      if (mine === seq.current) setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (mine === seq.current) setLoading(false);
    }
  }

  async function search(e: FormEvent) {
    e.preventDefault();
    const mine = ++searchSeq.current;
    setSearching(true);
    setError(null);
    try {
      const r = await api.searchFunctions(path, focus, query.trim());
      if (mine === searchSeq.current) setFound(r);
    } catch (err) {
      if (mine === searchSeq.current) setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (mine === searchSeq.current) setSearching(false);
    }
  }

  function changeDepth(steps: 1 | 2) {
    setDepth(steps);
    if (graph) void show(graph.subject.id, steps, "stay");
  }

  function back() {
    const previous = trail[trail.length - 2];
    if (previous) void show(previous, depth, "pop");
  }

  const subjectId = graph?.subject.id;
  const pick = (id: string) => void show(id, depth, "push");
  const onKey = (id: string) => (e: KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      pick(id);
    }
  };
  const note = found ? searchNote(found) : null;
  const callers = graph?.nodes.filter((n) => n.role === "caller") ?? [];
  const callees = graph?.nodes.filter((n) => n.role === "callee" || n.role === "both") ?? [];

  return (
    <Card className="p-5">
      <h2 className="text-lg font-semibold">Who calls what</h2>
      <p className="mt-1 max-w-prose text-sm text-muted">
        Pick a function to see which functions call it and which it calls. Only calls the graph proves are drawn. Click a function in the picture to look at it next.
      </p>

      <form onSubmit={(e) => void search(e)} className="mt-3 flex flex-wrap items-end gap-2">
        <div>
          <label htmlFor={queryId} className="text-sm font-medium">
            Find a function
          </label>
          <input
            id={queryId}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="part of a name, such as checkout"
            autoComplete="off"
            spellCheck={false}
            maxLength={200}
            className="mt-1 block w-72 max-w-full rounded-md border border-border bg-bg px-3 py-1.5 font-mono text-sm"
          />
        </div>
        <Button type="submit" variant="primary" busy={searching} disabled={!query.trim()}>
          Search
        </Button>
      </form>

      {starters.length > 0 && (
        <div className="mt-3">
          <p className="text-xs text-muted">Or start from a function many others depend on:</p>
          <ul className="mt-1 flex flex-wrap gap-2">
            {starters.slice(0, MAX_STARTERS).map((s) => (
              <li key={s.id}>
                <button
                  type="button"
                  onClick={() => pick(s.id)}
                  aria-pressed={s.id === subjectId}
                  className="rounded-md border border-border px-2 py-1 text-left text-xs hover:bg-surface-2 aria-pressed:border-accent"
                >
                  <span className="font-mono">{shortName(s.name)}</span> <span className="text-muted">· {plural(s.fan_in, "caller")}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {error && (
        <div className="mt-3">
          <Alert tone="bad" title="That could not be shown">
            {error}
          </Alert>
        </div>
      )}

      {found && (
        <div className="mt-3" aria-live="polite">
          {found.matches.length > 0 && (
            <ul className="max-h-64 divide-y divide-border overflow-y-auto rounded-md border border-border">
              {found.matches.map((m) => (
                <li key={m.id}>
                  <button type="button" onClick={() => pick(m.id)} className="flex w-full flex-wrap items-center gap-x-3 gap-y-0.5 px-3 py-2 text-left text-sm hover:bg-surface-2">
                    <span className="font-mono font-medium break-all">{m.name}</span>
                    <Badge tone={m.kind === "class" ? "info" : "neutral"}>{m.kind}</Badge>
                    <span className="text-xs text-muted break-all">{matchLine(m)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {note && <p className="mt-1 text-sm text-muted">{note}</p>}
        </div>
      )}

      {!graph && !loading && <p className="mt-4 text-sm text-muted">No function is shown yet.</p>}
      {loading && (
        <p role="status" className="mt-4 flex items-center gap-2 text-sm text-muted">
          <Spinner /> Reading the calls…
        </p>
      )}

      {graph && layout && (
        <div className="mt-4 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={back} disabled={trail.length < 2 || loading}>
              ← Back
            </Button>
            <div role="group" aria-label="How many steps to follow" className="flex gap-1">
              <Button variant={depth === 1 ? "primary" : "secondary"} aria-pressed={depth === 1} onClick={() => changeDepth(1)} disabled={loading}>
                One step
              </Button>
              <Button variant={depth === 2 ? "primary" : "secondary"} aria-pressed={depth === 2} onClick={() => changeDepth(2)} disabled={loading}>
                Two steps
              </Button>
            </div>
          </div>

          <p className="text-sm" aria-live="polite">
            {summarySentence(graph)}
          </p>

          <div className="overflow-x-auto rounded-md border border-border bg-bg">
            <svg
              role="group"
              aria-label={`Calls around ${graph.subject.name}: ${plural(graph.nodes.length, "function")} and ${plural(graph.edges.length, "call")}`}
              width={layout.width}
              height={layout.height}
              viewBox={`0 0 ${layout.width} ${layout.height}`}
              className="block max-w-none"
            >
              <title>{`Calls around ${graph.subject.name}`}</title>
              <defs>
                {(["head", "active", "back"] as const).map((kind) => (
                  <marker key={kind} id={`${marker}-${kind}`} viewBox="0 0 10 10" refX="10" refY="5" markerWidth="9" markerHeight="9" markerUnits="userSpaceOnUse" orient="auto">
                    <path d="M0 0 L10 5 L0 10 z" className={kind === "active" ? "fill-accent" : kind === "back" ? "fill-warn" : "fill-muted"} />
                  </marker>
                ))}
              </defs>

              {layout.arrows.map((a) => {
                const touchesSubject = a.from === graph.subject.id || a.to === graph.subject.id;
                const kind = a.back ? "back" : touchesSubject ? "active" : "head";
                return (
                  <g key={`${a.from}>${a.to}`}>
                    <path
                      d={a.d}
                      fill="none"
                      strokeWidth={a.width}
                      strokeDasharray={a.back ? "6 4" : undefined}
                      markerEnd={`url(#${marker}-${kind})`}
                      className={a.back ? "stroke-warn" : touchesSubject ? "stroke-accent" : "stroke-muted"}
                      opacity={touchesSubject || a.back ? 0.9 : 0.55}
                    />
                    {a.count > 1 && (
                      <text x={a.x} y={a.y} textAnchor="middle" dominantBaseline="central" paintOrder="stroke" strokeWidth={4} className="fill-text stroke-bg text-[10px]">
                        {a.count}
                      </text>
                    )}
                  </g>
                );
              })}

              {graph.nodes.map((n, i) => {
                const b = layout.boxes[i];
                const isSubject = n.id === graph.subject.id;
                return (
                  <g
                    key={n.id}
                    role="button"
                    tabIndex={0}
                    aria-label={`${n.name}, ${nodeSubtitle(n)}, ${nodeCounts(n)}${isSubject ? ". This is the function shown." : ". Press Enter to look at this function next."}`}
                    aria-current={isSubject || undefined}
                    onClick={() => !isSubject && pick(n.id)}
                    onKeyDown={isSubject ? undefined : onKey(n.id)}
                    className={`group outline-none ${isSubject ? "cursor-default" : "cursor-pointer"}`}
                  >
                    <title>{`${n.name} (${n.kind}) ${n.file}:${n.line}`}</title>
                    <rect
                      x={b.x}
                      y={b.y}
                      width={b.w}
                      height={b.h}
                      rx={8}
                      strokeWidth={isSubject ? 3 : 1.5}
                      strokeDasharray={n.test ? "4 3" : undefined}
                      className={`fill-surface group-focus-visible:stroke-accent ${isSubject ? "stroke-accent" : "stroke-border"}`}
                    />
                    <text x={b.x + 10} y={b.y + 19} className="fill-text text-[13px] font-semibold">
                      {shortName(n.name)}
                      {n.role === "both" ? " ⇄" : ""}
                    </text>
                    <text x={b.x + 10} y={b.y + 34} className="fill-muted text-[11px]">
                      {nodeSubtitle(n)}
                      {n.test ? " · test" : ""}
                    </text>
                    <text x={b.x + 10} y={b.y + 47} className="fill-muted text-[11px]">
                      {nodeCounts(n)}
                    </text>
                  </g>
                );
              })}
            </svg>
          </div>

          <details className="text-sm">
            <summary className="cursor-pointer font-medium">The calls as a list</summary>
            <div className="mt-2 space-y-2">
              <p>
                <span className="font-medium">Called by:</span> {callers.length > 0 ? callers.map((n) => n.name).join(", ") : "nothing drawn"}
              </p>
              <p>
                <span className="font-medium">Calls:</span> {callees.length > 0 ? callees.map((n) => n.name).join(", ") : "nothing drawn"}
              </p>
              {graph.edges.length > 0 && (
                <ul className="list-disc space-y-0.5 pl-5">
                  {edgeSentences(graph).map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              )}
            </div>
          </details>

          {callNotes(graph).map((n) => (
            <p key={n} className="text-xs text-muted">
              {n}
            </p>
          ))}
        </div>
      )}
    </Card>
  );
}
