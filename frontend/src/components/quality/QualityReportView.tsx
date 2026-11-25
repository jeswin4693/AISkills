"use client";

import Link from "next/link";
import { Alert, Badge, Card } from "@/components/ui";
import { formatWhen, plural, relativeTime, sourceText } from "@/lib/format";
import {
  changeLabel, coverageLine, groupCaption, headlineParts, kindWord, labLine, riskWords, statusTone, suggestionHref, tokenLine, type Tone,
} from "@/lib/quality";
import type { CheckStatus, QualityGroup, QualityReport } from "@/lib/types";

const ORDER: CheckStatus[] = ["failed", "warning", "not run", "passed"];
const BADGE: Record<Tone, "ok" | "warn" | "bad" | "info" | "neutral"> = { ok: "ok", warn: "warn", bad: "bad", info: "info", neutral: "neutral" };
const STATUS_TEXT = { failed: "FAILED", warning: "warning", "not run": "not run", passed: "passed" } as const;

/** A check with its status, what changed since import (library checks only) and its detail. */
function Row({ row }: { row: QualityGroup["rows"][number] }) {
  const change = changeLabel(row.change);
  return (
    <li className="flex gap-2 py-1.5">
      <span className="w-16 shrink-0 pt-0.5">
        <Badge tone={BADGE[statusTone(row.status)]}>{STATUS_TEXT[row.status]}</Badge>
      </span>
      <span className="min-w-0 text-sm">
        <span className="font-medium">{row.name}</span>{" "}
        {change && <Badge tone={BADGE[change.tone]}>{change.text}</Badge>}
        {row.detail && <span className="block break-words text-muted">{row.detail}</span>}
      </span>
    </li>
  );
}

/** One group of checks. What needs an eye is listed first; the passed ones are folded behind a count, as on the skill's own page. */
function Group({ group }: { group: QualityGroup }) {
  const ordered = [...group.rows].sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status)); // what failed first, then what to read, then what did not run
  const attention = ordered.filter((r) => r.status !== "passed");
  const passed = ordered.filter((r) => r.status === "passed");
  return (
    <section aria-labelledby={`g-${group.key}`}>
      <h3 id={`g-${group.key}`} className="font-semibold">
        {group.title}
      </h3>
      <p className="text-sm text-muted">{groupCaption(group.key)}</p>
      {attention.length > 0 && (
        <ul className="mt-1 divide-y divide-border">
          {attention.map((r) => (
            <Row key={r.name} row={r} />
          ))}
        </ul>
      )}
      {passed.length > 0 && (
        <details className="mt-1 text-sm">
          <summary className="cursor-pointer py-1 text-muted hover:text-text">Show the {passed.length} checks that passed</summary>
          <ul className="divide-y divide-border">
            {passed.map((r) => (
              <Row key={r.name} row={r} />
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

/** The report for one version. Every fact on it comes from the response: the page works nothing out. */
export function QualityReportView({ report }: { report: QualityReport }) {
  const { name } = report;
  return (
    <div className="space-y-6">
      <Card className="p-4">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold">
            {name} {report.tag}
          </h2>
          {report.latest ? <Badge tone="info">latest</Badge> : <Badge>not the latest</Badge>}
          <span className="text-sm text-muted" title={formatWhen(report.created_at)}>
            {relativeTime(report.created_at)} · {sourceText(report.source_kind, report.source_label)} · {plural(report.versions, "version")} in all
          </span>
        </div>
        <div className="mt-3 flex flex-wrap gap-2" aria-label="What the checks found">
          {headlineParts(report.headline).map((p) => (
            <Badge key={p.key} tone={BADGE[p.tone]}>
              {p.text}
            </Badge>
          ))}
        </div>
        <div className="mt-3">
          <Alert tone={report.attention.tone} title={report.attention.tone === "bad" ? "A problem" : report.attention.tone === "warn" ? "Worth a look" : "Nothing found by what ran"}>
            {report.attention.text}
          </Alert>
        </div>
      </Card>

      <section aria-labelledby="next-heading">
        <h2 id="next-heading" className="mb-2 font-semibold">
          What to do next
        </h2>
        {report.suggestions.length === 0 ? (
          <p className="text-sm text-muted">Nothing to suggest from what ran.</p>
        ) : (
          <Card>
            <ol className="divide-y divide-border">
              {report.suggestions.map((s, i) => {
                const href = suggestionHref(s.link, name);
                return (
                  <li key={i} className="flex gap-3 px-4 py-2.5 text-sm">
                    <span className="w-16 shrink-0 pt-0.5">
                      <Badge tone={s.kind === "fix" ? "bad" : "info"}>{kindWord(s.kind)}</Badge>
                    </span>
                    <span className="min-w-0 break-words">
                      {s.text}
                      {href && (
                        <>
                          {" "}
                          <Link href={href} className="whitespace-nowrap text-accent underline">
                            Open
                          </Link>
                        </>
                      )}
                    </span>
                  </li>
                );
              })}
            </ol>
          </Card>
        )}
        {report.suggestions_more > 0 && <p className="mt-1 text-sm text-muted">{plural(report.suggestions_more, "more suggestion")} not shown.</p>}
      </section>

      <section aria-labelledby="checks-heading" className="space-y-5">
        <h2 id="checks-heading" className="font-semibold">
          The checks, run again today
        </h2>
        {report.groups.map((g) => (
          <Group key={g.key} group={g} />
        ))}
      </section>

      <section aria-labelledby="req-heading">
        <h2 id="req-heading" className="mb-1 font-semibold">
          The requirement and its tests
        </h2>
        <p className="text-sm">{coverageLine(report.requirements)}</p>
        {report.requirements.criteria.length > 0 && (
          <ul className="mt-2 space-y-2">
            {report.requirements.criteria.map((c) => (
              <li key={c.id} className="rounded-lg border border-border p-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{c.id}</span>
                  <Badge tone={c.tests.length ? "ok" : "warn"}>{c.tests.length ? plural(c.tests.length, "test") : "no test"}</Badge>
                </div>
                <p className="mt-1 break-words">{c.text}</p>
                {c.tests.length > 0 && <p className="mt-1 text-muted">Tests: {c.tests.join(", ")}</p>}
              </li>
            ))}
          </ul>
        )}
        {report.requirements.unknown_cites.map((u) => (
          <p key={u.test} className="mt-2 text-sm text-warn">
            The test &ldquo;{u.test}&rdquo; cites {u.ids.join(", ")}, which {u.ids.length === 1 ? "is not a criterion" : "are not criteria"} of this skill.
          </p>
        ))}
        <p className="mt-3 text-sm">
          {report.tests.total === 0
            ? "It has no test cases."
            : `${plural(report.tests.total, "test case")}, ${report.tests.runnable} that the Testing Lab can run.`}{" "}
          {report.tests.reason && <span className="text-muted">Why not all: {report.tests.reason}.</span>}
        </p>
        {report.tests.skipped.length > 0 && (
          <ul className="mt-1 list-disc pl-5 text-sm text-muted">
            {report.tests.skipped.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="cost-heading">
        <h2 id="cost-heading" className="mb-1 font-semibold">
          What it costs to use
        </h2>
        <p className="text-sm">{tokenLine(report.tokens)}</p>
        {report.tokens.heavy.length > 0 && (
          <ul className="mt-1 list-disc pl-5 text-sm text-warn">
            {report.tokens.heavy.map((h) => (
              <li key={h}>{h}</li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="lab-heading">
        <h2 id="lab-heading" className="mb-1 font-semibold">
          The Testing Lab
        </h2>
        <p className="text-sm">{labLine(report.lab)}</p>
        <p className="mt-1 text-sm">
          <Link href={`/testing?name=${encodeURIComponent(name)}&version=${report.version}`} className="text-accent underline">
            Open the Testing Lab on {report.tag}
          </Link>
        </p>
      </section>

      {report.changes && (
        <section aria-labelledby="changes-heading">
          <h2 id="changes-heading" className="mb-1 font-semibold">
            Changes since {report.changes.from}
          </h2>
          <p className="text-sm">
            <strong>{riskWords(report.changes.level)}.</strong> {report.changes.counts.riskier} riskier, {report.changes.counts.look} worth a look, {report.changes.counts.safer} less risky.{" "}
            <span className="text-muted">{report.changes.note}</span>
          </p>
          {report.changes.items.length > 0 && (
            <ul className="mt-1 list-disc pl-5 text-sm">
              {report.changes.items.map((c, i) => (
                <li key={i} className="break-words">
                  <span className="text-muted">{c.direction}:</span> {c.detail}
                </li>
              ))}
            </ul>
          )}
          {report.changes.more > 0 && <p className="mt-1 text-sm text-muted">{plural(report.changes.more, "more change")} not shown.</p>}
          <p className="mt-1 text-sm">
            <Link href={`/library/${encodeURIComponent(name)}/diff?from=${report.changes.from_version}&to=${report.changes.to_version}`} className="text-accent underline">
              Compare {report.changes.from} and {report.changes.to}
            </Link>
          </p>
        </section>
      )}

      {report.evidence && (
        <section aria-labelledby="evidence-heading">
          <h2 id="evidence-heading" className="mb-1 font-semibold">
            Code it cites
          </h2>
          <p className="text-sm">
            {plural(report.evidence.places, "place")} in <span className="font-mono">{report.evidence.repo}</span>, recorded {relativeTime(report.evidence.taken_at)}
            {report.evidence.dirty ? " (the tree had uncommitted changes)" : ""}. Whether it still holds needs the repository:{" "}
            <Link href={`/library/${encodeURIComponent(name)}`} className="text-accent underline">
              recheck it on the skill&apos;s page
            </Link>
            .
          </p>
        </section>
      )}

      <section aria-labelledby="notrun-heading">
        <h2 id="notrun-heading" className="mb-1 font-semibold">
          What did not run
        </h2>
        <ul className="space-y-1 text-sm">
          {report.not_run.map((n) => (
            <li key={n.what}>
              <span className="font-medium">{n.what}.</span> <span className="text-muted">{n.why.charAt(0).toUpperCase() + n.why.slice(1)}.</span>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="limits-heading" className="text-sm text-muted">
        <h2 id="limits-heading" className="mb-1 font-semibold text-text">
          What this report cannot tell you
        </h2>
        <ul className="list-disc space-y-1 pl-5">
          {report.limits.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      </section>
    </div>
  );
}
