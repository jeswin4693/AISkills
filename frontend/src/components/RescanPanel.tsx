"use client";

import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { findingText, rescanHeadline, SCAN_LABEL, SCAN_TONE } from "@/lib/risk";
import type { RescanResult } from "@/lib/types";
import { Alert, Badge, Button, Card } from "./ui";

/**
 * Run today's static checks on skills already in the library. A skill is checked once when it comes in, and checks
 * improve: this says which stored versions would not pass today. It changes nothing and runs nothing.
 */
export function RescanPanel({ name }: { name?: string }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<RescanResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      setResult(await api.rescan(name));
    } catch (e) {
      setResult(null);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const head = result ? rescanHeadline(result) : null;
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="font-semibold">{name ? "Re-check this skill" : "Re-check everything"}</h2>
          <p className="mt-0.5 max-w-prose text-sm text-muted">
            Skills are checked once, when they come in, and the checks get better over time. This runs today&apos;s checks on {name ? "every version of this skill" : "every stored version"} and
            says which ones are now worse. Nothing is changed and nothing is run.
          </p>
        </div>
        <Button busy={busy} onClick={() => void run()}>
          {result ? "Re-check again" : "Re-check now"}
        </Button>
      </div>
      <div aria-live="polite" className="mt-3 space-y-2">
        {error && (
          <Alert tone="bad" title="The re-check could not be done" onDismiss={() => setError(null)}>
            {error}
          </Alert>
        )}
        {result && head && (
          <Alert tone={head.tone} title={head.title}>
            {result.versions.length > 0 && (
              <ul className="mt-1 divide-y divide-border/60">
                {result.versions.map((s) => (
                  <li key={`${s.name}/${s.tag}`} className="py-2 first:pt-0 last:pb-0">
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      {name ? (
                        <span className="font-medium">{s.tag || s.name}</span>
                      ) : (
                        <Link href={`/library/${s.name}`} className="font-medium text-accent underline">
                          {s.name} {s.tag}
                        </Link>
                      )}
                      <Badge tone={SCAN_TONE[s.status]}>{SCAN_LABEL[s.status]}</Badge>
                    </div>
                    {s.status === "damaged" && <p className="mt-1 text-sm">{s.message}</p>}
                    {s.findings.length > 0 && (
                      <ul className="mt-1 space-y-1 text-sm">
                        {s.findings.map((f) => (
                          <li key={f.name}>
                            <span className="font-medium">{findingText(f)}</span>
                            {f.detail && <span className="block break-words text-muted">{f.detail}</span>}
                          </li>
                        ))}
                      </ul>
                    )}
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-2 text-xs text-muted">Static checks only: passing is not proof that a skill is safe.</p>
          </Alert>
        )}
      </div>
    </Card>
  );
}
