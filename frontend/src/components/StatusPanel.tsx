"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";
import { API_URL, api } from "@/lib/api";
import { STATUS_EVENT, useAsync, type AsyncState } from "@/lib/useAsync";
import { Spinner } from "./ui";

function Row({ label, state, ok, bad, hint }: { label: string; state: AsyncState<unknown>; ok: string | null; bad: string; hint?: string }) {
  let body: React.ReactNode;
  if (state.loading && state.data === undefined) {
    body = (
      <span className="flex items-center gap-1.5 text-muted">
        <Spinner /> checking…
      </span>
    );
  } else if (state.error) {
    body = <span className="text-bad">not reachable</span>;
  } else if (ok !== null) {
    body = (
      <span className="flex items-center gap-1.5">
        <span aria-hidden className="size-2 rounded-full bg-ok" /> {ok}
      </span>
    );
  } else {
    body = (
      <span className="flex items-center gap-1.5 text-warn">
        <span aria-hidden className="size-2 rounded-full bg-warn" /> {bad}
      </span>
    );
  }
  return (
    <div className="flex items-baseline justify-between gap-3" title={hint}>
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 truncate text-right">{body}</dd>
    </div>
  );
}

/**
 * What the local server can do right now. Each row loads on its own: the sandbox check takes a moment, so it is only
 * repeated on "Refresh". The API and model rows are cheap: they look again on every page change, and at once when
 * a page says the setup changed.
 */
export function StatusPanel() {
  const path = usePathname();
  const health = useAsync(api.health, `health:${path}`);
  const sandbox = useAsync(api.sandbox, "sandbox");
  const provider = useAsync(api.provider, `provider:${path}`);
  const reload = () => {
    health.reload();
    sandbox.reload();
    provider.reload();
  };
  const { reload: reloadHealth } = health;
  const { reload: reloadProvider } = provider;
  useEffect(() => {
    const again = () => {
      reloadHealth();
      reloadProvider();
    };
    window.addEventListener(STATUS_EVENT, again);
    return () => window.removeEventListener(STATUS_EVENT, again);
  }, [reloadHealth, reloadProvider]);
  return (
    <section aria-label="Status" className="rounded-lg border border-border bg-surface p-3 text-xs">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="font-semibold">Status</h2>
        <button type="button" onClick={reload} className="rounded px-1.5 py-0.5 text-muted hover:bg-surface-2">
          Refresh
        </button>
      </div>
      <dl className="space-y-1.5">
        <Row label="API" state={health} ok={health.data ? `online · v${health.data.version}` : null} bad="" hint={API_URL} />
        <Row
          label="Sandbox"
          state={sandbox}
          ok={sandbox.data?.available ? "Linux, ready" : null}
          bad="none: scripts will not run"
          hint={sandbox.data?.reason}
        />
        <Row
          label="Model"
          state={provider}
          ok={provider.data?.configured ? provider.data.model : null}
          bad="not set up"
          hint={provider.data?.detail || (provider.data ? `${provider.data.provider}` : undefined)}
        />
      </dl>
      {health.error && (
        <p className="mt-2 text-muted">
          Start the API: <code className="font-mono">python -m skillforge serve</code>
        </p>
      )}
    </section>
  );
}
