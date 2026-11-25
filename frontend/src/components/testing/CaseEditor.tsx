"use client";

import { useEffect, useState } from "react";
import { Alert, Button, Card, ErrorBox, Loading } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import {
  blankCase, blankCheck, CASE_KINDS, CHECK_KINDS, caseProblems, fromServer, isNumericKind, sameCases, toBody, type DraftCase, type DraftCheck,
} from "@/lib/cases";
import type { ImportResult } from "@/lib/types";
import { useAsync } from "@/lib/useAsync";

const INPUT = "w-full rounded-md border border-border bg-surface px-3 py-1.5 text-sm";

function Labelled({ id, label, children }: { id: string; label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 text-sm">
      <label htmlFor={id} className="mb-1 block font-medium">
        {label}
      </label>
      {children}
    </div>
  );
}

function CheckRow({ id, check, onChange, onRemove, canRemove }: { id: string; check: DraftCheck; onChange: (c: DraftCheck) => void; onRemove: () => void; canRemove: boolean }) {
  const kind = CHECK_KINDS.find((k) => k.kind === check.kind);
  return (
    <li className="grid gap-2 sm:grid-cols-[19rem_1fr_1fr_auto] sm:items-end">
      <Labelled id={`${id}-kind`} label="The reply">
        <select id={`${id}-kind`} className={INPUT} value={check.kind} onChange={(e) => onChange({ ...check, kind: e.target.value })}>
          {CHECK_KINDS.map((k) => (
            <option key={k.kind} value={k.kind}>
              {k.label}
            </option>
          ))}
        </select>
      </Labelled>
      <Labelled id={`${id}-value`} label={kind?.numeric ? "Number" : "Text or pattern"}>
        <input
          id={`${id}-value`} className={INPUT} value={check.value} placeholder={kind?.hint} inputMode={isNumericKind(check.kind) ? "numeric" : undefined}
          onChange={(e) => onChange({ ...check, value: e.target.value })}
        />
      </Labelled>
      <Labelled id={`${id}-why`} label="Why (optional)">
        <input id={`${id}-why`} className={INPUT} value={check.why} placeholder="the rule it checks" onChange={(e) => onChange({ ...check, why: e.target.value })} />
      </Labelled>
      <Button variant="ghost" onClick={onRemove} disabled={!canRemove} aria-label="Remove this check">
        Remove
      </Button>
    </li>
  );
}

function CaseCard({
  c, index, maxChecks, maxName, maxMessage, onChange, onRemove,
}: {
  c: DraftCase; index: number; maxChecks: number; maxName: number; maxMessage: number; onChange: (c: DraftCase) => void; onRemove: () => void;
}) {
  return (
    <li className="rounded-xl border border-border p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h4 className="font-medium">Case {index + 1}</h4>
        <Button variant="ghost" onClick={onRemove} aria-label={`Remove case ${index + 1}`}>
          Remove case
        </Button>
      </div>
      <div className="mt-2 grid gap-3 sm:grid-cols-2">
        <Labelled id={`${c.key}-name`} label="Name">
          <input id={`${c.key}-name`} className={INPUT} value={c.name} maxLength={maxName} onChange={(e) => onChange({ ...c, name: e.target.value })} />
        </Labelled>
        <Labelled id={`${c.key}-kind`} label="Kind">
          <select id={`${c.key}-kind`} className={INPUT} value={c.kind} onChange={(e) => onChange({ ...c, kind: e.target.value })}>
            {CASE_KINDS.map((k) => (
              <option key={k.kind} value={k.kind}>
                {k.label}
              </option>
            ))}
          </select>
        </Labelled>
      </div>
      <div className="mt-3">
        <Labelled id={`${c.key}-message`} label="Message sent to the model (exactly what a person would type)">
          <textarea
            id={`${c.key}-message`} className={`${INPUT} font-mono`} rows={3} maxLength={maxMessage} value={c.message}
            onChange={(e) => onChange({ ...c, message: e.target.value })}
          />
        </Labelled>
      </div>
      <fieldset className="mt-3">
        <legend className="text-sm font-medium">The reply must pass (1 to {maxChecks} checks)</legend>
        {c.checks.length === 0 && <p className="mt-2 text-sm text-muted">No checks yet. A reply cannot be judged without at least one: add one below.</p>}
        <ul className="mt-2 space-y-3">
          {c.checks.map((k, i) => (
            <CheckRow
              key={i} id={`${c.key}-check${i}`} check={k} canRemove={c.checks.length > 1}
              onChange={(next) => onChange({ ...c, checks: c.checks.map((x, j) => (j === i ? next : x)) })}
              onRemove={() => onChange({ ...c, checks: c.checks.filter((_, j) => j !== i) })}
            />
          ))}
        </ul>
        <div className="mt-2">
          <Button onClick={() => onChange({ ...c, checks: [...c.checks, blankCheck()] })} disabled={c.checks.length >= maxChecks}>
            Add a check
          </Button>
        </div>
      </fieldset>
    </li>
  );
}

/**
 * The person's own test cases for one version of a skill: a message to send and the checks the reply must pass. Saving makes the NEXT version
 * through the library's checked import (older versions are kept), so the editor is only offered on the latest. It tells a person what would stop
 * a save before they press it, by the same rules the server applies; the server is still the judge.
 */
export function CaseEditor({ name, version, onSaved }: { name: string; version: number; onSaved: (version: number) => void }) {
  const data = useAsync(() => api.skillCases(name, version), `cases/${name}/${version}`);
  const [cases, setCases] = useState<DraftCase[] | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ status: number; message: string } | null>(null);
  const [refused, setRefused] = useState<ImportResult | null>(null);
  const [unchanged, setUnchanged] = useState(false);

  useEffect(() => {
    if (data.data && cases === null) setCases(data.data.cases.length ? fromServer(data.data.cases) : [blankCase()]);
  }, [data.data, cases]);

  if (data.error) return <ErrorBox error={data.error} onRetry={data.reload} />;
  if (!data.data || cases === null) return <Loading what="the test cases" />;
  const view = data.data;
  if (!view.latest) {
    return <Alert tone="info" title="Open the latest version to change test cases">Saving test cases makes the next version, so it can only be done from the latest one.</Alert>;
  }

  const saved: DraftCase[] = view.cases.map((c) => ({ ...c, key: "" })); // compared by content only, so no key is needed
  const dirty = !sameCases(cases, saved);
  const problems = caseProblems(cases, view.limits);
  const edit = (next: DraftCase[]) => {
    setCases(next);
    setError(null);
    setRefused(null);
    setUnchanged(false);
  };

  async function save() {
    if (!cases) return;
    setBusy(true);
    setError(null);
    setRefused(null);
    setUnchanged(false);
    try {
      const r = await api.saveCases(name, toBody(version, cases, note));
      if (r.refused) setRefused(r);
      else if (!r.created) setUnchanged(true);
      else if (r.version) onSaved(r.version.version);
    } catch (e) {
      setError(e instanceof ApiError ? { status: e.status, message: e.message } : { status: 0, message: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="p-4">
      <h2 className="font-semibold">Your test cases</h2>
      <p className="mt-1 text-sm text-muted">
        Each case is a message sent to the model and the checks its reply must pass. Tests you write yourself are the strongest kind: the model that wrote a skill did not write them.
        Saving makes <strong>v{version + 1}</strong>; every older version is kept.
      </p>
      {view.unreadable > 0 && (
        <div className="mt-3">
          <Alert tone="warn" title={`${view.unreadable} ${view.unreadable === 1 ? "entry" : "entries"} could not be read`}>
            tests/cases.json holds {view.unreadable === 1 ? "an entry" : "entries"} that are not test cases the Lab can read. Saving leaves {view.unreadable === 1 ? "it" : "them"} out.
          </Alert>
        </div>
      )}
      {view.needs_tools && (
        <div className="mt-3">
          <Alert tone="info" title="The Lab cannot run these cases">
            This skill needs tools ({view.needs_tools}), which a model with no tools cannot stand in for. The cases are still kept with the skill as a record of what a correct run looks like.
          </Alert>
        </div>
      )}
      <ol className="mt-4 space-y-4">
        {cases.map((c, i) => (
          <CaseCard
            key={c.key} c={c} index={i} maxChecks={view.limits.max_checks} maxName={view.limits.max_name} maxMessage={view.limits.max_message}
            onChange={(next) => edit(cases.map((x) => (x.key === c.key ? next : x)))}
            onRemove={() => edit(cases.filter((x) => x.key !== c.key))}
          />
        ))}
      </ol>
      <div className="mt-3">
        <Button onClick={() => edit([...cases, blankCase()])} disabled={cases.length >= view.limits.max_cases}>
          Add a case
        </Button>
      </div>
      {dirty && problems.length > 0 && (
        <div className="mt-4" role="status" aria-live="polite">
          <p className="text-sm font-medium">Before this can be saved</p>
          <ul className="mt-1 list-disc pl-5 text-sm text-bad">
            {problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="mt-4 flex flex-wrap items-end gap-3">
        <div className="min-w-[14rem] flex-1 text-sm">
          <label htmlFor="case-note" className="mb-1 block font-medium">
            Note for the new version (optional)
          </label>
          <input id="case-note" className={INPUT} value={note} maxLength={200} placeholder="for example: added the cases from the review" onChange={(e) => setNote(e.target.value)} />
        </div>
        <Button variant="primary" busy={busy} disabled={!dirty || problems.length > 0} onClick={() => void save()}>
          Keep as a new version (v{version + 1})
        </Button>
      </div>
      {error && (
        <div className="mt-3">
          <Alert tone="bad" title={error.status === 409 ? "A newer version exists" : "It was not saved"}>
            <p className="whitespace-pre-line">{error.message}</p>
          </Alert>
        </div>
      )}
      {refused && (
        <div className="mt-3">
          <Alert tone="bad" title="A check refused the new version, so nothing was saved">
            <ul className="list-disc pl-5">
              {refused.checks.filter((c) => c.status === "failed").map((c) => (
                <li key={c.name}>
                  {c.name}: {c.detail}
                </li>
              ))}
            </ul>
          </Alert>
        </div>
      )}
      {unchanged && (
        <div className="mt-3">
          <Alert tone="info" title="Nothing changed">These are the same test cases the latest version already has, so no new version was made.</Alert>
        </div>
      )}
    </Card>
  );
}
