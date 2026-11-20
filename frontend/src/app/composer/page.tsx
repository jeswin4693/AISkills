"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { CheckList } from "@/components/CheckList";
import { Alert, Badge, Button, Card, Empty, ErrorBox, Loading, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { plural } from "@/lib/format";
import { withKindParam } from "@/lib/kind";
import { canPreview, isPicked, keepRequest, nameHint, pluginRequest, togglePick, type ComponentPick, type PluginForm } from "@/lib/plugin";
import type { PluginPreview, PluginSaveResult, SkillSummary } from "@/lib/types";
import { useAsync, type AsyncState } from "@/lib/useAsync";

const READING = new Set(["Read", "Grep", "Glob"]);

function Parts({
  title, kind, list, picks, onToggle,
}: {
  title: string;
  kind: "skill" | "agent";
  list: AsyncState<SkillSummary[]>;
  picks: ComponentPick[];
  onToggle: (p: ComponentPick) => void;
}) {
  return (
    <Card className="p-4">
      <h2 className="font-semibold">{title}</h2>
      {list.error ? (
        <ErrorBox error={list.error} onRetry={list.reload} />
      ) : list.data === undefined ? (
        <Loading what={title.toLowerCase()} />
      ) : list.data.length === 0 ? (
        <Empty title={`No ${kind}s kept yet`}>Build one in the Builder and save it, or import one in the Library.</Empty>
      ) : (
        <ul className="mt-2 space-y-1">
          {list.data.filter((s) => s.latest).map((s) => {
            const pick: ComponentPick = { kind, name: s.name };
            return (
              <li key={s.name}>
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={isPicked(picks, pick)} onChange={() => onToggle(pick)} />
                  <span className="font-medium">{s.name}</span>
                  <span className="text-muted">{s.latest?.tag} · the latest version is used</span>
                </label>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

export default function ComposerPage() {
  const skills = useAsync(() => api.listSkills("skill"), "composer-skills");
  const agents = useAsync(() => api.listSkills("agent"), "composer-agents");
  const [form, setForm] = useState<PluginForm>({ name: "", description: "", author: "" });
  const [picks, setPicks] = useState<ComponentPick[]>([]);
  const [preview, setPreview] = useState<PluginPreview | null>(null);
  const [saved, setSaved] = useState<PluginSaveResult | null>(null);
  const [busy, setBusy] = useState<"preview" | "keep" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const latest = useRef(0); // each request gets a number; an answer to an older one is ignored
  const stale = () => {
    latest.current += 1; // an answer still on its way was asked about a form that has changed
    setBusy(null);
    setPreview(null); // what was shown no longer matches the form
    setSaved(null);
  };
  const edit = (patch: Partial<PluginForm>) => {
    setForm({ ...form, ...patch });
    stale();
  };
  const toggle = (p: ComponentPick) => {
    setPicks(togglePick(picks, p));
    stale();
  };

  async function run<T>(what: "preview" | "keep", call: () => Promise<T>, done: (r: T) => void) {
    const mine = ++latest.current;
    setBusy(what);
    setError(null);
    try {
      const result = await call();
      if (mine === latest.current) done(result);
    } catch (e) {
      if (mine === latest.current) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (mine === latest.current) setBusy(null);
    }
  }

  const request = pluginRequest(form, picks);
  const hint = nameHint(form.name.trim());
  const ready = canPreview(form, picks);

  return (
    <>
      <PageHeader
        title="Compose a plugin"
        subtitle="Combine skills and agents you already have into one plugin for Claude Code. No AI model is used here: you pick the parts, and the app works out what the plugin can do on your machine before you keep it."
      />
      <div className="space-y-6">
        <Card className="space-y-4 p-5">
          <div>
            <label htmlFor="plugin-name" className="font-semibold">
              Name
            </label>
            <input
              id="plugin-name" value={form.name} maxLength={64} onChange={(e) => edit({ name: e.target.value })} placeholder="my-helpers"
              className="mt-1.5 block w-full rounded-md border border-border bg-bg px-3 py-2 font-mono"
            />
            {hint && <p className="mt-1 text-sm text-warn">{hint}</p>}
          </div>
          <div>
            <label htmlFor="plugin-description" className="font-semibold">
              What is it for?
            </label>
            <input
              id="plugin-description" value={form.description} maxLength={1000} onChange={(e) => edit({ description: e.target.value })}
              placeholder="Review helpers for pull requests" className="mt-1.5 block w-full rounded-md border border-border bg-bg px-3 py-2"
            />
          </div>
          <div>
            <label htmlFor="plugin-author" className="font-semibold">
              Your name <span className="font-normal text-muted">(optional, shown as the author)</span>
            </label>
            <input
              id="plugin-author" value={form.author} maxLength={100} onChange={(e) => edit({ author: e.target.value })}
              className="mt-1.5 block w-full rounded-md border border-border bg-bg px-3 py-2"
            />
          </div>
        </Card>

        <div className="grid gap-4 md:grid-cols-2">
          <Parts title="Skills" kind="skill" list={skills} picks={picks} onToggle={toggle} />
          <Parts title="Agents" kind="agent" list={agents} picks={picks} onToggle={toggle} />
        </div>

        {error && (
          <Alert tone="bad" title="It could not be done">
            {error}
          </Alert>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <Button
            variant="primary" busy={busy === "preview"} disabled={!ready}
            onClick={() => void run("preview", () => api.previewPlugin(request), setPreview)}
          >
            Preview the plugin
          </Button>
          {!ready && <span className="text-sm text-muted">Give it a name, a description and at least one skill or agent.</span>}
        </div>

        {preview && (
          <Card className="space-y-5 p-5">
            <div>
              <h2 className="font-semibold">
                {preview.name} <span className="font-normal text-muted">version {preview.version}</span>
              </h2>
              <p className="text-sm text-muted">Nothing has been kept yet. This is what would be kept.</p>
            </div>
            <section>
              <h3 className="mb-1 font-semibold">What it can do on your machine</h3>
              <ul className="list-disc space-y-1 pl-5 text-sm">
                {preview.capabilities.notes.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {preview.capabilities.tools.map((t) => (
                  <Badge key={t} tone={READING.has(t) ? "neutral" : "warn"}>
                    {t}
                  </Badge>
                ))}
              </div>
              <p className="mt-1 text-xs text-muted">Worked out by code from the files. Hooks and MCP servers are not part of this kind of plugin yet.</p>
            </section>
            <section>
              <h3 className="mb-1 font-semibold">What is inside ({plural(preview.files.length, "file")})</h3>
              <ul className="font-mono text-xs">
                {preview.files.map((f) => (
                  <li key={f.path}>
                    {f.path} <span className="text-muted">{f.bytes} bytes</span>
                  </li>
                ))}
              </ul>
            </section>
            <section>
              <h3 className="mb-1 font-semibold">Checks</h3>
              <CheckList checks={preview.checks} />
            </section>
            <div className="flex flex-wrap items-center gap-3">
              <Button
                variant="primary" busy={busy === "keep"} disabled={preview.failed}
                onClick={() => void run("keep", () => api.savePlugin(keepRequest(request, preview.components)), setSaved)}
              >
                Keep this plugin
              </Button>
              {preview.failed && <span className="text-sm text-muted">A check failed, so it cannot be kept.</span>}
            </div>
          </Card>
        )}

        {saved &&
          (saved.refused ? (
            <Alert tone="bad" title="Refused: nothing was kept">
              <CheckList checks={saved.checks} />
            </Alert>
          ) : (
            <Alert tone="ok" title={saved.created ? `Kept '${saved.name}' as ${saved.version?.tag}` : `Unchanged: '${saved.name}' is identical to ${saved.version?.tag}`}>
              <Link href={withKindParam(`/library/${saved.name}`, "plugin")} className="font-medium text-accent underline">
                Open it in the library
              </Link>{" "}
              to export it or install it from a folder. Its README has the two commands that add it to Claude Code.
            </Alert>
          ))}
      </div>
    </>
  );
}
