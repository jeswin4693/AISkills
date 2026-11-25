"use client";

import { useMemo, useState } from "react";
import { bands, docsRead, dropSummary, firstPart, HOP_INFO, hopDetail, hopsUsed, partFacts, PART_STATUS, quoteNote, quoteSource, routeSteps, stepNumbers } from "@/lib/guide";
import type { Guide, GuidePart } from "@/lib/types";
import { Alert, Badge, Card } from "../ui";

const LABEL = "text-xs font-semibold uppercase tracking-wide text-muted";

function StepBadge({ n }: { n: number }) {
  return <span className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent text-xs font-semibold text-accent-fg">{n}</span>;
}

/**
 * How a project works, read from its README and docs. The layers say where things live, the numbered route says in what order an action travels through
 * them, and a click on a part opens what a new developer needs: what it does, where to start reading, and the sentence of the docs it came from.
 * A quote is checked by code (it is in the documents); the words around it are the model's own, and are labelled so.
 */
export function HowItWorks({ guide }: { guide: Guide }) {
  // The choice remembers which answer it was made on, so a new guide never opens on a part that is no longer there.
  const [pick, setPick] = useState<{ guide: Guide; journey: number; part: string | null } | null>(null);
  const mine = pick && pick.guide === guide ? pick : null;
  const journeyIndex = Math.min(mine?.journey ?? 0, Math.max(guide.journeys.length - 1, 0));
  const journey = guide.journeys[journeyIndex];
  const numbers = useMemo(() => stepNumbers(journey), [journey]);
  const steps = useMemo(() => routeSteps(guide, journey), [guide, journey]);
  const layers = useMemo(() => bands(guide), [guide]);
  const selected: GuidePart | undefined = guide.parts.find((p) => p.id === (mine?.part ?? firstPart(guide, journey)));
  const choose = (part: string) => setPick({ guide, journey: journeyIndex, part });
  const dropped = dropSummary(guide);

  const heading = (
    <p className="max-w-prose text-sm text-muted">
      Drawn for <strong className="text-text">{guide.name}</strong> from {docsRead(guide) || "the documents"}. Every quote below was found in them, word for word, by code. The words around a
      quote are the model&apos;s own.
    </p>
  );

  if (guide.status === "no_docs") {
    return (
      <Card className="p-5">
        {heading}
        <div className="mt-3">
          <Alert tone="info" title="There is no README or docs to read">
            {guide.notes[0]}
          </Alert>
        </div>
      </Card>
    );
  }
  if (guide.status === "thin") {
    return (
      <Card className="p-5">
        {heading}
        <div className="mt-3">
          <Alert tone="warn" title="Not enough could be checked, so nothing is drawn">
            <p>{guide.notes[0]}</p>
            {dropped.length > 0 && <p className="mt-1">Dropped because they could not be checked: {dropped.join("; ")}.</p>}
          </Alert>
        </div>
      </Card>
    );
  }

  return (
    <Card className="p-5">
      {heading}

      {guide.journeys.length > 0 && (
        <div role="group" aria-label="Actions" className="mt-4 flex flex-wrap gap-2">
          {guide.journeys.map((j, i) => (
            <button
              key={`${i}-${j.title}`}
              type="button"
              aria-pressed={i === journeyIndex}
              onClick={() => setPick({ guide, journey: i, part: null })}
              className={`rounded-full border px-3 py-1 text-sm ${i === journeyIndex ? "border-accent bg-accent font-semibold text-accent-fg" : "border-border bg-surface hover:border-accent"}`}
            >
              {j.title}
            </button>
          ))}
        </div>
      )}

      {steps.length > 0 && (
        <div className="mt-4">
          <h3 className={LABEL}>The route: {journey?.title}</h3>
          <ol className="mt-2">
            {steps.map(({ n, step, part, hopAfter }) => (
              <li key={n}>
                <div className="flex items-start gap-2">
                  <StepBadge n={n} />
                  <p className="min-w-0 text-sm">
                    <button type="button" onClick={() => part && choose(part.id)} disabled={!part} className="font-semibold underline-offset-2 hover:underline">
                      {part?.name ?? step.part}
                    </button>
                    <span className="text-muted"> &ndash; {step.does}</span>
                    {!step.quote.on_topic && (
                      <span className="ml-1.5 align-middle">
                        <Badge tone="warn" title={quoteNote(step.quote)}>
                          quote does not mention this part
                        </Badge>
                      </span>
                    )}
                  </p>
                </div>
                {hopAfter && (
                  <div className={`my-1 ml-2.5 border-l-2 py-1 pl-4 ${HOP_INFO[hopAfter.status].solid ? "border-ok" : "border-dashed border-muted"}`}>
                    <Badge tone={HOP_INFO[hopAfter.status].tone} title={HOP_INFO[hopAfter.status].why}>
                      {HOP_INFO[hopAfter.status].label}
                    </Badge>
                    {hopDetail(hopAfter) && <p className="mt-0.5 break-all text-xs text-muted">{hopDetail(hopAfter)}</p>}
                  </div>
                )}
              </li>
            ))}
          </ol>
          <ul className="mt-2 space-y-0.5 text-xs text-muted">
            {hopsUsed(journey).map((status) => (
              <li key={status}>
                <strong className="text-text">{HOP_INFO[status].label}:</strong> {HOP_INFO[status].why}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-5 space-y-2">
        {layers.map((band) => (
          <section key={band.id} aria-label={band.label} className="rounded-lg border border-dashed border-border bg-surface-2 p-2.5">
            <h3 className={`${LABEL} mb-2`}>{band.label}</h3>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {band.parts.map((p) => {
                const on = numbers.get(p.id);
                const status = PART_STATUS[p.status];
                return (
                  <button
                    key={p.id}
                    type="button"
                    aria-pressed={p.id === selected?.id}
                    onClick={() => choose(p.id)}
                    className={`rounded-lg border p-3 text-left ${p.id === selected?.id ? "border-accent bg-accent-soft" : "border-border bg-surface hover:border-accent"} ${journey && !on ? "opacity-60" : ""}`}
                  >
                    <span className="flex flex-wrap items-center gap-1.5">
                      {on?.map((n) => <StepBadge key={n} n={n} />)}
                      <span className="font-semibold">{p.name}</span>
                    </span>
                    <span className="mt-1 block text-xs text-muted">{p.summary}</span>
                    <span className="mt-2 flex flex-wrap items-center gap-1.5">
                      {p.status === "in_code" ? <span className="break-all font-mono text-xs text-muted">{p.folder}</span> : <Badge tone={status.tone}>{status.label}</Badge>}
                    </span>
                  </button>
                );
              })}
            </div>
          </section>
        ))}
      </div>

      {selected && (
        <section aria-label={`${selected.name} in detail`} className="mt-4 rounded-lg border-2 border-accent bg-surface p-4">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-base font-semibold">{selected.name}</h3>
            <Badge tone={selected.quote.on_topic ? "ok" : "warn"} title={quoteNote(selected.quote) || "Code looked this sentence up in the documents"}>
              Quote found: {quoteSource(selected.quote)}
            </Badge>
            <Badge tone={PART_STATUS[selected.status].tone}>{PART_STATUS[selected.status].label}</Badge>
            {partFacts(selected) && <Badge>{partFacts(selected)}</Badge>}
            {numbers.get(selected.id) && <Badge tone="info">{`Step ${numbers.get(selected.id)!.join(" and ")} of the route`}</Badge>}
          </div>
          <div className="mt-3 grid gap-4 text-sm md:grid-cols-3">
            <div className="space-y-3">
              <div>
                <h4 className={LABEL}>What it does</h4>
                <p>{selected.summary}</p>
              </div>
              <div>
                <h4 className={LABEL}>Goes in, comes out</h4>
                <p>
                  <span className="text-muted">In:</span> {selected.takes_in}
                </p>
                <p>
                  <span className="text-muted">Out:</span> {selected.gives_out}
                </p>
              </div>
            </div>
            <div>
              <h4 className={LABEL}>Read these first</h4>
              {selected.read_first.files.length === 0 && selected.read_first.functions.length === 0 ? (
                <p className="text-muted">There is nothing to read: the code has no folder for this part.</p>
              ) : (
                <ul className="space-y-1">
                  {selected.read_first.files.map((f) => (
                    <li key={f.path} className="break-all font-mono text-xs">
                      {f.path} <span className="text-muted">({f.lines} lines)</span>
                    </li>
                  ))}
                  {selected.read_first.functions.map((f) => (
                    <li key={`${f.file}:${f.line}:${f.name}`} className="break-all font-mono text-xs">
                      {f.name}() <span className="text-muted">{f.file}:{f.line}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="space-y-3">
              <div>
                <h4 className={LABEL}>Where the docs say so</h4>
                <blockquote className="border-l-2 border-accent pl-2 italic text-muted">{selected.quote.text}</blockquote>
                <p className="mt-0.5 text-xs text-muted">{quoteSource(selected.quote)}</p>
                {quoteNote(selected.quote) && <p className="mt-1 text-xs text-warn">{quoteNote(selected.quote)}</p>}
              </div>
              <div>
                <h4 className={LABEL}>
                  In plain words <Badge>model&apos;s words, not checked</Badge>
                </h4>
                <p>{selected.plain}</p>
              </div>
            </div>
          </div>
        </section>
      )}

      <div className="mt-4 space-y-1 text-xs text-muted">
        {dropped.length > 0 && <p>Dropped because they could not be checked: {dropped.join("; ")}.</p>}
        {guide.notes.map((n) => (
          <p key={n}>{n}</p>
        ))}
        <p>
          Model: {guide.provider}/{guide.model}. Nothing is saved: asking again asks the model again.
        </p>
      </div>
    </Card>
  );
}
