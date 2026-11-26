"use client";

import { useState } from "react";
import { MyModel } from "@/components/settings/MyModel";
import { MySpace } from "@/components/settings/MySpace";
import { SettingField } from "@/components/settings/SettingField";
import { Alert, Badge, Button, Card, ErrorBox, Loading, PageHeader } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import {
  buildChanges, changedNames, checkLine, groupItems, keyAdvice, missingKeys, problemFor, roleText, shownValue, statusLine, type Draft,
} from "@/lib/settings";
import type { ModelCheckReport, SettingGroup, SettingItem, SettingProblem, SettingsView } from "@/lib/types";
import { notifyStatusChanged, useAsync } from "@/lib/useAsync";

export default function SettingsPage() {
  const loaded = useAsync(api.settings, "settings");
  const [after, setAfter] = useState<SettingsView | null>(null); // the state the last save answered with
  const view = after ?? loaded.data;
  const [draft, setDraft] = useState<Draft>({}); // what was typed; a key is only ever here until it is saved
  const [removed, setRemoved] = useState<ReadonlySet<string>>(new Set());
  const [saving, setSaving] = useState(false);
  const [refused, setRefused] = useState<{ detail: string; problems: SettingProblem[] } | null>(null);
  const [saveError, setSaveError] = useState<Error | null>(null);
  const [justSaved, setJustSaved] = useState(false);
  const [checking, setChecking] = useState(false);
  const [report, setReport] = useState<ModelCheckReport | null>(null);
  const [checkError, setCheckError] = useState<Error | null>(null);

  if (loaded.error instanceof ApiError && loaded.error.status === 403) {
    // The hosted version: the server's own settings are not edited here (a save would be written on the server), but a signed-in person keeps a model and
    // key of their own, and the owner is told theirs is the server's own settings.
    return (
      <>
        <PageHeader title="Settings" subtitle="Choose the model you use and add its key. Your key is kept sealed on this server and used only for what you start." />
        <div className="space-y-6">
          <MyModel />
          <MySpace />
        </div>
      </>
    );
  }
  if (loaded.error && !view) {
    return (
      <>
        <PageHeader title="Settings" />
        <ErrorBox error={loaded.error} onRetry={loaded.reload} />
      </>
    );
  }
  if (!view) return <Loading what="the settings" />;

  const changed = changedNames(view.settings, draft, removed);
  const advice = keyAdvice(view.settings, draft, removed);
  const missing = missingKeys(view.settings, draft, removed);
  const status = statusLine(view.status);
  const problems = refused?.problems ?? [];

  function type(name: string, value: string) {
    setDraft((d) => ({ ...d, [name]: value }));
    setJustSaved(false);
  }

  function toggleRemove(name: string) {
    const removing = !removed.has(name);
    setRemoved((r) => {
      const next = new Set(r);
      if (removing) next.add(name);
      else next.delete(name);
      return next;
    });
    if (removing) setDraft(({ [name]: _typed, ...rest }) => rest); // what was typed for a key that is being removed is dropped, not saved
    setJustSaved(false);
  }

  function discard() {
    setDraft({});
    setRemoved(new Set());
    setRefused(null);
    setSaveError(null);
  }

  async function save() {
    if (!view) return;
    setSaving(true);
    setRefused(null);
    setSaveError(null);
    try {
      const result = await api.saveSettings(buildChanges(view.settings, draft, removed));
      if (result.ok) {
        setAfter(result.view);
        setDraft({}); // a key typed here is gone from the page the moment it is saved
        setRemoved(new Set());
        setReport(null); // an older test says nothing about the new setup
        setJustSaved(true);
        notifyStatusChanged();
      } else {
        setRefused({ detail: result.detail, problems: result.problems });
      }
    } catch (err) {
      setSaveError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setSaving(false);
    }
  }

  async function check() {
    setChecking(true);
    setCheckError(null);
    try {
      setReport(await api.checkModels());
    } catch (err) {
      setCheckError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setChecking(false);
    }
  }

  const renderGroup = (g: SettingGroup) => {
    const items = groupItems(view.settings, g.key);
    if (items.length === 0) return null;
    return (
      <Card key={g.key} className="p-5">
        <h2 className="text-lg font-semibold">{g.label}</h2>
        <p className="mt-0.5 max-w-prose text-sm text-muted">{g.help}</p>
        {g.key === "model" && advice && <p className="mt-2 text-sm text-warn">{advice}</p>}
        {g.key === "keys" && missing.length > 0 && (
          <p className="mt-2 text-sm text-warn">
            {missing.length === 1 ? "A backup model or a kind of work uses" : "Backup models or kinds of work use"} {missing.join(", ")}, but there is no key for {missing.length === 1 ? "it" : "them"} yet. Add {missing.length === 1 ? "it" : "them"} below, or every model call will fail.
          </p>
        )}
        <div className="mt-4 space-y-4">
          {items.map((item: SettingItem) => (
            <SettingField
              key={item.name}
              item={item}
              value={shownValue(item, draft)}
              onChange={(v) => type(item.name, v)}
              problem={problemFor(problems, item.name)}
              removing={removed.has(item.name)}
              onToggleRemove={() => toggleRemove(item.name)}
            />
          ))}
        </div>
      </Card>
    );
  };

  const basic = view.groups.filter((g) => !g.advanced);
  const advanced = view.groups.filter((g) => g.advanced);

  return (
    <>
      <PageHeader
        title="Settings"
        subtitle={`Choose the model SkillForge uses and add its key. Settings are saved in the ${view.file} file on this computer${view.file_exists ? "" : " (it is made the first time you save)"}. A key is never shown again, and is sent only to its own provider.`}
      />
      <div className="space-y-6">
        <Card className="p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold">The model in use</h2>
              <p className={`mt-0.5 text-sm ${status.tone === "ok" ? "" : "text-warn"}`}>{status.text}</p>
            </div>
            <Button busy={checking} disabled={changed.length > 0 || !view.status.configured} onClick={() => void check()}>
              Test my models
            </Button>
          </div>
          <p className="mt-2 text-xs text-muted">
            The test sends one tiny question to each model, so it uses a little of your quota. It tests what is saved
            {changed.length > 0 ? ": save your changes first." : "."}
          </p>
          {checkError && (
            <div className="mt-3">
              <ErrorBox error={checkError} />
            </div>
          )}
          {report && (
            <ul className="mt-3 divide-y divide-border rounded-lg border border-border" aria-label="Test results">
              {report.checks.length === 0 && <li className="px-3 py-2 text-sm text-muted">{report.detail || "No model is set up."}</li>}
              {report.checks.map((c) => {
                const line = checkLine(c);
                return (
                  <li key={`${c.provider}/${c.model}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm">
                    <span className="font-mono">
                      {c.provider} / {c.model}
                    </span>
                    <Badge tone={line.tone}>{line.tone === "ok" ? "Works" : "Failed"}</Badge>
                    <span className={line.tone === "ok" ? "text-muted" : "text-bad"}>{line.text}</span>
                    <span className="text-xs text-muted">{roleText(c.roles)}</span>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>

        {view.file_exists && !view.file_readable && (
          <Alert tone="warn" title={`The ${view.file} file cannot be read as text`}>
            <p>Nothing in it is being used. Save it as UTF-8 (a character such as an accented letter in a comment, saved in another encoding, is the usual cause), then reload this page.</p>
          </Alert>
        )}
        {justSaved && (view.status.configured ? (
          <Alert tone="ok" title="Saved. It is used from now on, with no restart." />
        ) : (
          <Alert tone="warn" title="Saved, but no model is usable yet">
            <p>{view.status.detail || status.text}</p>
          </Alert>
        ))}
        {refused && (
          <Alert tone="bad" title="Nothing was saved">
            <p>{refused.detail}</p>
          </Alert>
        )}
        {saveError && <ErrorBox error={saveError} />}

        {basic.map(renderGroup)}
        {advanced.length > 0 && (
          <details className="rounded-xl border border-border bg-surface">
            <summary className="cursor-pointer px-5 py-3 font-semibold">More options</summary>
            <div className="space-y-6 p-5 pt-2">{advanced.map(renderGroup)}</div>
          </details>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <Button variant="primary" busy={saving} disabled={changed.length === 0} onClick={() => void save()}>
            Save changes
          </Button>
          <Button variant="ghost" disabled={changed.length === 0 || saving} onClick={discard}>
            Discard changes
          </Button>
          <span className="text-sm text-muted">{changed.length === 0 ? "Nothing changed." : `${changed.length} ${changed.length === 1 ? "setting" : "settings"} will be saved.`}</span>
        </div>
      </div>
    </>
  );
}
