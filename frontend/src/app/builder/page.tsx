"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useId, useState, type FormEvent } from "react";
import { Alert, Badge, Button, Card, Empty, ErrorBox, Loading, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { EXAMPLES, conversationalKinds, kindLabel, kindNoun, showKindPicker, statusInfo, withArticle } from "@/lib/builder";
import { relativeTime } from "@/lib/format";
import { useAuth } from "@/lib/useAuth";
import { notifyStatusChanged, useAsync } from "@/lib/useAsync";
import { useKinds } from "@/lib/useKinds";

function ModelBanner({ onCheck }: { onCheck: () => void }) {
  const provider = useAsync(api.provider, "provider-banner");
  const { hosted, user } = useAuth();
  if (!provider.data || provider.data.configured) return null;
  return (
    <Alert tone="warn" title="No AI model is set up yet">
      <p>{provider.data.detail}</p>
      {hosted ? (
        user ? (
          <p className="mt-2">
            The builder needs a model. Add your own model key in <Link href="/settings" className="underline">Settings</Link>: it is kept sealed on this server and used
            only for what you start.
          </p>
        ) : (
          <p className="mt-2">The builder needs a model. On a hosted server the owner sets it in the server&apos;s own environment (see docs/hosting.md), not on this page.</p>
        )
      ) : (
        <p className="mt-2">
          The builder needs a model. Put the settings in the <code className="font-mono">.env</code> file in the repository&apos;s root folder (the file{" "}
          <code className="font-mono">.env.example</code> shows which): <code className="font-mono">LLM_PROVIDER</code>, <code className="font-mono">LLM_MODEL</code> and the
          key for that provider. Keys are only ever read from that file or from the environment; this page never asks for one.
        </p>
      )}
      <div className="mt-2">
        <Button
          onClick={() => {
            provider.reload();
            onCheck();
            notifyStatusChanged(); // the sidebar's Model row looks again too
          }}
        >
          Check again
        </Button>
      </div>
    </Alert>
  );
}

export default function BuilderPage() {
  const router = useRouter();
  const textId = useId();
  const kindGroup = useId();
  const provider = useAsync(api.provider, "provider-form");
  const sandbox = useAsync(api.sandbox, "sandbox-form");
  const recent = useAsync(api.builds, "builds");
  const kinds = useKinds();
  const [kind, setKind] = useState("skill");
  const picker = showKindPicker(kinds.data); // with one kind there is nothing to choose, and the page is as it always was
  const noun = kindNoun(kinds.data, kind);
  const isSkill = kind === "skill";
  const [description, setDescription] = useState("");
  const [withScripts, setWithScripts] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ready = provider.data?.configured === true;
  const tooShort = description.trim().length < 10;

  async function start(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const s = await api.startBuild(description, isSkill && withScripts, kind);
      router.push(`/builder/${s.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title={`Build ${withArticle(noun)}`}
        subtitle={`Say in your own words what the ${noun} should do. I will ask only about what is missing, show you the requirement to approve, and only then build it.`}
      />
      <div className="space-y-6">
        <ModelBanner onCheck={provider.reload} />
        <Card className="p-5">
          <form onSubmit={start} className="space-y-4">
            {picker && (
              <fieldset>
                <legend className="font-semibold">What do you want to build?</legend>
                <div className="mt-1.5 flex flex-wrap gap-2">
                  {conversationalKinds(kinds.data).map((k) => (
                    <label key={k.key} className="flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-sm">
                      <input type="radio" name={kindGroup} value={k.key} checked={kind === k.key} onChange={() => setKind(k.key)} />
                      {k.label}
                    </label>
                  ))}
                </div>
              </fieldset>
            )}
            <div>
              <label htmlFor={textId} className="font-semibold">
                What should the {noun} do?
              </label>
              <textarea
                id={textId}
                rows={4}
                maxLength={10000}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder={
                  isSkill
                    ? "For example: A skill that counts TODO and FIXME comments in a folder and reports them for each file."
                    : `Describe, in your own words, what the ${noun} should do.`
                }
                className="mt-1.5 block w-full rounded-md border border-border bg-bg px-3 py-2"
              />
              {isSkill && (
                <div className="mt-2 flex flex-wrap items-center gap-1.5 text-sm">
                  <span className="text-muted">Try:</span>
                  {EXAMPLES.map((ex) => (
                    <button
                      key={ex}
                      type="button"
                      onClick={() => setDescription(ex)}
                      className="rounded-full border border-border px-2.5 py-0.5 text-left text-xs hover:bg-surface-2"
                      title={ex}
                    >
                      {ex.length > 52 ? ex.slice(0, 50) + "…" : ex}
                    </button>
                  ))}
                </div>
              )}
            </div>
            {isSkill && (
            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" checked={withScripts} onChange={(e) => setWithScripts(e.target.checked)} className="mt-1" />
              <span>
                Also write helper scripts and test them in the sandbox
                <span className="block text-muted">
                  {sandbox.data && !sandbox.data.available
                    ? "There is no Linux sandbox on this machine, so the scripts could not be tested and the skill would be marked DRAFT."
                    : "Every script case runs in a locked container with no network. It takes longer."}
                </span>
              </span>
            </label>
            )}
            {error && (
              <Alert tone="bad" title="It could not be started">
                {error}
              </Alert>
            )}
            <div className="flex flex-wrap items-center gap-3">
              <Button type="submit" variant="primary" busy={busy} disabled={!ready || tooShort}>
                Start
              </Button>
              {!ready && provider.data && <span className="text-sm text-muted">Set up a model first.</span>}
              {ready && tooShort && description.length > 0 && <span className="text-sm text-muted">Describe it in at least a sentence.</span>}
              {ready && provider.data && <span className="text-sm text-muted">Model: {provider.data.model}</span>}
            </div>
          </form>
        </Card>

        <section>
          <h2 className="mb-2 font-semibold">Your builds</h2>
          {recent.error ? (
            <ErrorBox error={recent.error} onRetry={recent.reload} />
          ) : recent.data === undefined ? (
            <Loading what="your builds" />
          ) : recent.data.length === 0 ? (
            <Empty title="Nothing built yet">Your conversations with the builder will be listed here, so you can come back to one.</Empty>
          ) : (
            <Card>
              <ul className="divide-y divide-border">
                {recent.data.map((b) => {
                  const s = statusInfo(b.status);
                  return (
                    <li key={b.id}>
                      <Link href={`/builder/${b.id}`} className="block px-4 py-3 hover:bg-surface-2 focus-visible:bg-surface-2">
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                          <span className="min-w-0 flex-1 truncate font-medium">{b.skill || b.description}</span>
                          {picker && <Badge tone="neutral">{kindLabel(kinds.data, b.kind)}</Badge>}
                          <Badge tone={s.tone}>{s.label}</Badge>
                          {b.draft && <Badge tone="warn">DRAFT</Badge>}
                          {b.saved && <Badge tone="ok">saved {b.saved.version}</Badge>}
                          <span className="text-sm text-muted">{relativeTime(b.updated_at)}</span>
                        </div>
                        {b.skill && <p className="mt-0.5 truncate text-sm text-muted">{b.description}</p>}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </Card>
          )}
        </section>
      </div>
    </>
  );
}
