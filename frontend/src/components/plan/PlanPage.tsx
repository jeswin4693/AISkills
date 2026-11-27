"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { Field, SELECT } from "@/components/SkillVersionPicker";
import { Alert, Button, Card, PageHeader, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { buildPlanRequest, EMPTY_FORM, formProblem, KINDS, MAX_BUDGET, sentSummary, taskProblem, type PlanForm } from "@/lib/plan";
import { loadRemembered } from "@/lib/repository";
import type { TaskPlan } from "@/lib/types";
import { useAsync } from "@/lib/useAsync";
import { PlanView } from "./PlanView";

const INPUT = "block w-full rounded-md border border-border bg-bg px-3 py-2 text-sm";

/**
 * A request planned before any work: what it contains and does not say, its size from the code graph, the process, the rules and a token plan. It is the
 * command line's `plan`, unchanged, behind one request. Nothing is saved and nothing in the repository is changed or run.
 */
export function PlanPage() {
  const provider = useAsync(api.provider, "provider-plan");
  const [form, setForm] = useState<PlanForm>(EMPTY_FORM);
  const [plan, setPlan] = useState<TaskPlan | null>(null);
  const [planning, setPlanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const seq = useRef(0); // an answer that comes back after a newer request was made is ignored

  useEffect(() => {
    // after mount, so the first render matches the server's: the folder the Repository page last read is offered, and can be changed
    setForm((f) => ({ ...f, repo: loadRemembered().path }));
  }, []);

  const set = <K extends keyof PlanForm>(key: K, value: PlanForm[K]) => setForm((f) => ({ ...f, [key]: value }));
  const taskText = taskProblem(form.task); // shown under the task box
  const otherText = formProblem({ ...form, task: "" }); // the first problem of the other boxes (folder, budget, patterns), shown above the button
  const problem = taskText ?? otherText;
  const modelReady = provider.data?.configured === true;
  const blockedByModel = !form.noAi && !modelReady; // a plan that asks a model needs one; "facts only" never does

  async function run(e: FormEvent) {
    e.preventDefault();
    const mine = ++seq.current;
    setPlanning(true);
    setError(null);
    try {
      const answer = await api.planTask(buildPlanRequest(form));
      if (mine === seq.current) setPlan(answer);
    } catch (err) {
      if (mine === seq.current) setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (mine === seq.current) setPlanning(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Task Plan"
        subtitle="Plan a task before doing it. It says what your request contains (with your own words as proof) and what it leaves out, how big the task is from the code graph, which phases it needs and when it stops to ask, which rules apply, and what reading it would cost. Nothing is run, and nothing in the repository is changed."
      />
      <div className="space-y-6">
        <Card className="p-5">
          <form onSubmit={(e) => void run(e)} className="space-y-4">
            <Field label="What should be done?">
              {(id) => (
                <textarea
                  id={id}
                  value={form.task}
                  onChange={(e) => set("task", e.target.value)}
                  rows={5}
                  placeholder={"Add a --json option to the `library list` command in `cli.py`. Do not change any other command."}
                  className={`${INPUT} resize-y`}
                />
              )}
            </Field>
            <p className="-mt-2 text-xs text-muted">Write code names in backticks, such as `parse_config` or `src/util.py`: only a name written that way is looked up as code.</p>
            {taskText && <p className="-mt-2 text-sm text-warn">{taskText}</p>}

            <Field label="Folder or GitHub link (optional)">
              {(id) => (
                <input
                  id={id}
                  value={form.repo}
                  onChange={(e) => set("repo", e.target.value)}
                  placeholder="C:\code\shop-api   or   https://github.com/owner/repo"
                  autoComplete="off"
                  spellCheck={false}
                  className={`${INPUT} font-mono`}
                />
              )}
            </Field>
            <p className="-mt-2 text-xs text-muted">
              Without a repository the size of the change, the rules and the reading plan cannot be measured. The path stays on this computer and is never shown back.
            </p>

            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" checked={form.noAi} onChange={(e) => set("noAi", e.target.checked)} className="mt-1" />
              <span>
                <span className="font-medium">Don&apos;t use a model (plan from facts only)</span>
                <span className="block text-muted">Only what the code can measure is planned; the request itself is not read.</span>
              </span>
            </label>

            <details className="text-sm">
              <summary className="cursor-pointer font-medium">Options</summary>
              <div className="mt-3 grid gap-4 sm:grid-cols-2">
                <Field label="Kind of task">
                  {(id) => (
                    <select id={id} value={form.kind} onChange={(e) => set("kind", e.target.value)} className={`${SELECT} w-full`}>
                      <option value="">Work it out from the request</option>
                      {KINDS.map((k) => (
                        <option key={k.value} value={k.value}>
                          {k.label}
                        </option>
                      ))}
                    </select>
                  )}
                </Field>
                <Field label="Raise the tier to">
                  {(id) => (
                    <select id={id} value={form.tier} onChange={(e) => set("tier", e.target.value)} className={`${SELECT} w-full`}>
                      <option value="">Work it out from the code</option>
                      {[0, 1, 2, 3].map((t) => (
                        <option key={t} value={String(t)}>
                          Tier {t}
                        </option>
                      ))}
                    </select>
                  )}
                </Field>
                <Field label="Reading budget (tokens)">
                  {(id) => <input id={id} value={form.budget} onChange={(e) => set("budget", e.target.value)} inputMode="numeric" placeholder={`up to ${MAX_BUDGET.toLocaleString("en-US")}`} className={INPUT} />}
                </Field>
                <Field label="Sensitive paths">
                  {(id) => (
                    <textarea
                      id={id}
                      value={form.sensitive}
                      onChange={(e) => set("sensitive", e.target.value)}
                      rows={2}
                      placeholder="src/auth/**, migrations/*"
                      className={`${INPUT} font-mono`}
                    />
                  )}
                </Field>
              </div>
              <p className="mt-2 text-xs text-muted">
                Tiers run from 0 (a typo) to 3 (complex or risky). Here a tier can only be raised. A task that touches a sensitive path is always tier 3.
              </p>
            </details>

            {blockedByModel && provider.data && (
              <Alert tone="warn" title="No AI model is set up yet">
                <p>{provider.data.detail}</p>
                <p className="mt-1">Set one up in Settings, or tick &ldquo;Don&apos;t use a model&rdquo; to plan from facts only.</p>
              </Alert>
            )}
            {otherText && <p className="text-sm text-warn">{otherText}</p>}

            <div className="flex flex-wrap items-center gap-3">
              <Button type="submit" variant="primary" busy={planning} disabled={!form.task.trim() || !!problem || blockedByModel}>
                Plan it
              </Button>
              <p className="text-sm text-muted" aria-live="polite">
                {sentSummary(form)}
              </p>
            </div>
          </form>
        </Card>

        {planning && (
          <p role="status" className="flex items-center gap-2 text-sm text-muted">
            <Spinner /> {form.noAi ? "Reading the code…" : "Reading the request and the code. This takes a few seconds."}
          </p>
        )}
        {error && (
          <Alert tone="bad" title="The plan could not be made">
            {error}
          </Alert>
        )}
        {plan && <PlanView plan={plan} />}
      </div>
    </>
  );
}
