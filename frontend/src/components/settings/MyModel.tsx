"use client";

import { useId, useState } from "react";
import { Alert, Badge, Button, Card, ErrorBox, Loading } from "@/components/ui";
import { api } from "@/lib/api";
import { allowanceText, canSave, cleanKey, problemsWith } from "@/lib/myModel";
import { checkLine, problemFor, roleText } from "@/lib/settings";
import type { ModelCheckReport, MyModelView, SettingProblem } from "@/lib/types";
import { notifyStatusChanged, useAsync } from "@/lib/useAsync";

// 16 px text (iPhone does not zoom in on focus) and 44 px tall: a thumb can use it.
const INPUT = "mt-1 block min-h-11 w-full max-w-md rounded-md border border-border bg-bg px-3 py-2 text-base disabled:cursor-not-allowed disabled:opacity-60";
const BUTTON = "min-h-11";

function savedOn(iso: string): string {
  const when = new Date(iso);
  return Number.isNaN(when.getTime()) ? "" : when.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/**
 * The hosted version's Settings page for a signed-in person: their own model and key, kept sealed on the server. A key is typed here, sent once, cleared from
 * the page the moment it is saved, and never comes back. The owner is told that the server's own settings are used.
 */
export function MyModel() {
  const loaded = useAsync(api.myModel, "my-model");
  const [after, setAfter] = useState<MyModelView | null>(null); // what the last change answered with
  const view = after ?? loaded.data;
  const [provider, setProvider] = useState<string | null>(null); // null: untouched, so the saved (or the first) one shows
  const [model, setModel] = useState<string | null>(null);
  const [key, setKey] = useState(""); // a key is only ever here until it is saved
  const [busy, setBusy] = useState<"save" | "remove" | "test" | null>(null);
  const [refused, setRefused] = useState<{ detail: string; problems: SettingProblem[] } | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [justSaved, setJustSaved] = useState(false);
  const [report, setReport] = useState<ModelCheckReport | null>(null);
  const ids = { provider: useId(), model: useId(), key: useId() };

  if (loaded.error && !view) return <ErrorBox error={loaded.error} onRetry={loaded.reload} />;
  if (!view) return <Loading what="your model" />;

  if (view.mode === "owner") {
    return (
      <Alert tone="info" title="Your model is the server's own">
        <p>{view.message}</p>
      </Alert>
    );
  }

  const chosenProvider = provider ?? (view.provider || view.providers[0] || "");
  const chosenModel = model ?? view.model;
  const saved = view.key_saved ? { provider: view.provider, readable: view.key_readable } : null; // an empty key box keeps this one
  const problems = problemsWith(chosenProvider, chosenModel, key, view.providers, saved);
  const serverProblems = refused?.problems ?? [];
  const failed = (e: unknown) => setError(e instanceof Error ? e : new Error(String(e)));

  async function save() {
    setBusy("save");
    setRefused(null);
    setError(null);
    setJustSaved(false);
    try {
      const result = await api.saveMyModel({ provider: chosenProvider, model: chosenModel.trim(), key: cleanKey(key) });
      if (result.ok) {
        setAfter(result.view);
        setKey(""); // gone from the page the moment it is saved
        setProvider(null);
        setModel(null);
        setReport(null);
        setJustSaved(true);
        notifyStatusChanged(); // the banners and the sidebar look at the model again
      } else {
        setRefused({ detail: result.detail, problems: result.problems });
      }
    } catch (err) {
      failed(err);
    } finally {
      setBusy(null);
    }
  }

  async function remove() {
    setBusy("remove");
    setError(null);
    setJustSaved(false);
    try {
      setAfter(await api.removeMyModel());
      setKey("");
      setProvider(null);
      setModel(null);
      setReport(null);
      notifyStatusChanged();
    } catch (err) {
      failed(err);
    } finally {
      setBusy(null);
    }
  }

  async function test() {
    setBusy("test");
    setError(null);
    try {
      setReport(await api.testMyModel());
    } catch (err) {
      failed(err);
    } finally {
      setBusy(null);
    }
  }

  const allowance = allowanceText(view.allowance);
  const date = view.key_saved ? savedOn(view.key_saved_at) : "";
  const typed = chosenModel.trim().length > 0 || key.length > 0; // a refusal is shown once there is something to refuse

  return (
    <div className="space-y-6">
      <Card className="p-5">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold">The model you use</h2>
          {view.mode === "own" && <Badge tone="ok">Your own key</Badge>}
          {view.mode === "shared" && <Badge tone="info">This server&apos;s model</Badge>}
          {view.mode === "none" && <Badge tone="warn">Not set up</Badge>}
        </div>
        <p className="mt-1 text-sm">{view.message}</p>
        {view.mode === "own" && (
          <p className="mt-1 text-sm text-muted">
            {view.provider} / {view.model}. A key is saved{date ? ` (${date})` : ""} and is never shown again.
          </p>
        )}
        {allowance && <p className="mt-1 text-sm text-muted">{allowance}</p>}
        {!view.key_readable && (
          <div className="mt-3">
            <Alert tone="warn" title="Your saved key cannot be opened">
              <p>The server&apos;s access token changed after you saved it. Enter your key again below.</p>
            </Alert>
          </div>
        )}
      </Card>

      {justSaved && <Alert tone="ok" title="Saved. It is used for everything you start from now on, with no restart." />}
      {refused && (
        <Alert tone="bad" title="Nothing was saved">
          <p>{refused.detail}</p>
        </Alert>
      )}
      {error && <ErrorBox error={error} />}

      <Card className="p-5">
        <h2 className="text-lg font-semibold">{view.key_saved ? "Change your model or key" : "Use your own model"}</h2>
        <p className="mt-0.5 max-w-prose text-sm text-muted">
          Pick a provider, give the model name your key can use, and paste the key. It is sealed on this server and sent only to that provider; it is never shown again.
          Whoever runs this server could still read it, so use a key with its own spending limit.
        </p>
        <div className="mt-4 space-y-4">
          <div>
            <label htmlFor={ids.provider} className="font-medium">
              Provider
            </label>
            <select id={ids.provider} value={chosenProvider} onChange={(e) => setProvider(e.target.value)} aria-invalid={problems.provider ? true : undefined} className={INPUT}>
              {view.providers.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
            {(problemFor(serverProblems, "provider") ?? problems.provider) && (
              <p role="alert" className="mt-1 text-sm text-bad">
                {problemFor(serverProblems, "provider") ?? problems.provider}
              </p>
            )}
          </div>
          <div>
            <label htmlFor={ids.model} className="font-medium">
              Model
            </label>
            <input
              id={ids.model}
              value={chosenModel}
              onChange={(e) => setModel(e.target.value)}
              autoComplete="off"
              autoCapitalize="none"
              spellCheck={false}
              aria-invalid={problems.model && typed ? true : undefined}
              className={`${INPUT} font-mono`}
            />
            <p className="mt-1 max-w-md text-xs text-muted">
              Copy the exact name from your provider&apos;s model list. Some names contain a slash, for example <span className="font-mono">openai/gpt-oss-120b</span> on Groq.
            </p>
            {(problemFor(serverProblems, "model") ?? (chosenModel.length > 0 ? problems.model : undefined)) && (
              <p role="alert" className="mt-1 text-sm text-bad">
                {problemFor(serverProblems, "model") ?? problems.model}
              </p>
            )}
          </div>
          <div>
            <label htmlFor={ids.key} className="font-medium">
              Key
            </label>
            <input
              id={ids.key}
              type="password"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder={view.key_saved ? "Saved. Leave empty to keep it, or paste to replace." : "Paste the key"}
              autoComplete="off"
              autoCapitalize="none"
              spellCheck={false}
              aria-invalid={problems.key && key.length > 0 ? true : undefined}
              className={`${INPUT} font-mono`}
            />
            {(problemFor(serverProblems, "key") ?? (key.length > 0 ? problems.key : undefined)) && (
              <p role="alert" className="mt-1 text-sm text-bad">
                {problemFor(serverProblems, "key") ?? problems.key}
              </p>
            )}
          </div>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button variant="primary" className={BUTTON} busy={busy === "save"} disabled={busy !== null || !canSave(problems)} onClick={() => void save()}>
            Save my model
          </Button>
          {view.key_saved && (
            <>
              <Button className={BUTTON} busy={busy === "test"} disabled={busy !== null || !view.key_readable} onClick={() => void test()}>
                Test my key
              </Button>
              <Button variant="ghost" className={BUTTON} busy={busy === "remove"} disabled={busy !== null} onClick={() => void remove()}>
                Remove my key
              </Button>
            </>
          )}
        </div>
        {view.key_saved && <p className="mt-2 text-xs text-muted">The test sends one tiny question to your model, so it uses a little of your own quota.</p>}
        {report && (
          <ul className="mt-3 divide-y divide-border rounded-lg border border-border" aria-label="Test results">
            {report.checks.length === 0 && <li className="px-3 py-2 text-sm text-muted">{report.detail || "No model to test."}</li>}
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
    </div>
  );
}
