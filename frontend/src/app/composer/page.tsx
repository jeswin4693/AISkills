"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { CheckList } from "@/components/CheckList";
import { Alert, Badge, Button, Card, Empty, ErrorBox, Loading, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { plural } from "@/lib/format";
import { withKindParam } from "@/lib/kind";
import {
  canPreview, hookWhen, isPicked, keepRequest, nameHint, optionProblem, parseOptionText, partLabel, pluginRequest, serverPowers, setOption, togglePick,
  type ComponentPick, type PluginForm,
} from "@/lib/plugin";
import type { HookInfo, PluginPreview, PluginSaveResult, SkillSummary } from "@/lib/types";
import { useAsync, type AsyncState } from "@/lib/useAsync";

const READING = new Set(["Read", "Grep", "Glob"]);

function Parts({
  title, kind, list, picks, onToggle,
}: {
  title: string;
  kind: ComponentPick["kind"];
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
        <Empty title={`No ${title.toLowerCase()} kept yet`}>Build one in the Builder and save it, or import one in the Library.</Empty>
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

/** The catalogue of hooks. A hook is never typed: each one is a fixed script from SkillForge, and the only thing a person adds is an option. */
function HookParts({
  list, picks, texts, onToggle, onOption,
}: {
  list: AsyncState<HookInfo[]>;
  picks: ComponentPick[];
  texts: Record<string, string>;
  onToggle: (p: ComponentPick) => void;
  onOption: (pick: ComponentPick, key: string, text: string) => void;
}) {
  return (
    <Card className="p-4">
      <h2 className="font-semibold">Hooks</h2>
      <p className="mt-1 text-xs text-muted">
        A hook is a small program that runs on your machine, with your permissions, every time its event happens. These are the only ones offered: fixed scripts from SkillForge, none written by a model.
      </p>
      {list.error ? (
        <ErrorBox error={list.error} onRetry={list.reload} />
      ) : list.data === undefined ? (
        <Loading what="hooks" />
      ) : (
        <ul className="mt-2 space-y-3">
          {list.data.map((h) => {
            const pick: ComponentPick = { kind: "hook", name: h.id };
            const picked = isPicked(picks, pick);
            const powers = serverPowers(h.powers);
            const current = picks.find((p) => p.kind === "hook" && p.name === h.id);
            return (
              <li key={h.id}>
                <label className="flex items-start gap-2 text-sm">
                  <input type="checkbox" className="mt-1" checked={picked} onChange={() => onToggle(pick)} />
                  <span>
                    <span className="font-medium">{h.title}</span>{" "}
                    <Badge tone="warn">runs on your machine</Badge>{" "}
                    <Badge tone={h.effect === "blocks" ? "warn" : "neutral"}>{h.effect === "blocks" ? "can block" : "only looks"}</Badge>
                    <span className="block text-muted">{h.summary}</span>
                    <span className="block text-xs text-muted">
                      Runs {hookWhen(h)}. It is handed {h.sees}.{powers.length ? ` Its script can ${powers.join(", ")}.` : " Its script does not reach the network, start programs or write files."}
                    </span>
                  </span>
                </label>
                {picked &&
                  h.options.map((o) => {
                    const id = `hook-${h.id}-${o.key}`;
                    const values = current?.options?.[o.key] ?? [];
                    const problem = optionProblem(o, values);
                    return (
                      <div key={o.key} className="ml-6 mt-2">
                        <label htmlFor={id} className="text-sm font-medium">
                          {o.label} <span className="font-normal text-muted">(optional, separated by commas)</span>
                        </label>
                        <input
                          id={id} value={texts[id] ?? ""} onChange={(e) => onOption(pick, o.key, e.target.value)}
                          className="mt-1 block w-full rounded-md border border-border bg-bg px-3 py-1.5 font-mono text-sm"
                        />
                        <p className={`mt-1 text-xs ${problem ? "text-warn" : "text-muted"}`}>{problem || o.help}</p>
                      </div>
                    );
                  })}
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
  const servers = useAsync(() => api.listSkills("mcp"), "composer-servers");
  const hooks = useAsync(() => api.hooks(), "composer-hooks");
  const [texts, setTexts] = useState<Record<string, string>>({}); // what is typed in each option box, as typed (the list is parsed from it)
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
  const option = (p: ComponentPick, key: string, text: string) => {
    setTexts({ ...texts, [`hook-${p.name}-${key}`]: text });
    setPicks(setOption(picks, p, key, parseOptionText(text)));
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
  const ready = canPreview(form, picks, hooks.data ?? []);

  return (
    <>
      <PageHeader
        title="Compose a plugin"
        subtitle="Combine skills, agents and MCP servers you already have into one plugin for Claude Code. No AI model is used here: you pick the parts, and the app works out what the plugin can do on your machine before you keep it."
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
          <Parts title="MCP servers" kind="mcp" list={servers} picks={picks} onToggle={toggle} />
          <HookParts list={hooks} picks={picks} texts={texts} onToggle={toggle} onOption={option} />
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
          {!ready && <span className="text-sm text-muted">Give it a name, a description and at least one skill, agent, MCP server or hook (and fix any option marked above).</span>}
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
              <p className="mt-1 text-xs text-muted">Worked out by code from the files. Hooks come only from SkillForge&apos;s catalogue.</p>
            </section>
            {preview.capabilities.hook_entries.length > 0 && (
              <section>
                <h3 className="mb-1 font-semibold">Hooks this plugin runs</h3>
                <p className="mb-2 text-sm text-muted">
                  Each one is a fixed script from the catalogue, shipped unchanged. It runs on your machine, with your permissions and outside any sandbox, every time its event happens. A hook is a
                  policy aid, not a security boundary: it matches names and text. A hook that guards something fails closed: if it cannot read what Claude Code sends it, or python is not on your PATH,
                  it blocks the action it watches until that is fixed.
                </p>
                <ul className="space-y-3">
                  {preview.capabilities.hook_entries.map((h) => {
                    const powers = serverPowers(h.powers);
                    const chosen = Object.entries(h.options);
                    return (
                      <li key={h.id} className="rounded-md border border-border p-3 text-sm">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-medium">{h.title}</span>
                          <code className="text-xs text-muted">{h.id}</code>
                          <Badge tone={h.effect === "blocks" ? "warn" : "neutral"}>{h.effect === "blocks" ? "can block" : "only looks"}</Badge>
                        </div>
                        <p className="mt-1">
                          Runs {hookWhen(h)}. {h.summary}
                        </p>
                        <p className="mt-1 text-muted">
                          It is handed {h.sees}.{powers.length ? ` By reading its script it can ${powers.join(", ")}.` : " By reading its script it does not reach the network, start programs or write files."}
                        </p>
                        {chosen.map(([key, values]) => (
                          <p key={key} className="mt-1">
                            Your choice, {key}: <span className="font-mono">{values.join(", ")}</span>
                          </p>
                        ))}
                      </li>
                    );
                  })}
                </ul>
              </section>
            )}
            {preview.capabilities.servers.length > 0 && (
              <section>
                <h3 className="mb-1 font-semibold">Programs this plugin starts</h3>
                <p className="mb-2 text-sm text-muted">
                  Claude Code starts each {partLabel("mcp")} when the plugin is enabled, with your permissions and outside any sandbox. This is read from its code by syntax, not run, and is not proof.
                </p>
                <ul className="space-y-3">
                  {preview.capabilities.servers.map((s) => {
                    const powers = serverPowers(s.capabilities);
                    return (
                      <li key={s.name} className="rounded-md border border-border p-3 text-sm">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-medium">{s.name}</span>
                          <code className="text-xs text-muted">{s.command}</code>
                        </div>
                        <p className="mt-1">
                          Tools: {s.tools.length ? s.tools.join(", ") : "none found"}.{" "}
                          {powers.length ? `Its code can ${powers.join(", ")}.` : "Its code does not reach the network, start programs or write files."}
                        </p>
                        {s.dynamic.length > 0 && <p className="mt-1 text-warn">It uses {s.dynamic.join(", ")}, which the checks cannot follow.</p>}
                        {s.environment.length > 0 && (
                          <p className="mt-1">
                            Claude Code will ask you for <span className="font-mono">{s.environment.join(", ")}</span> when you enable the plugin, and stores it in its own credentials store (on Windows a file in your Claude folder, not a vault). No value is written in the plugin.
                          </p>
                        )}
                        {s.environment_dynamic && <p className="mt-1 text-warn">It also reads environment variables by a name that is not written in the code.</p>}
                      </li>
                    );
                  })}
                </ul>
              </section>
            )}
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
