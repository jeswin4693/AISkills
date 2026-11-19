import { progressSteps } from "@/lib/builder";
import type { BuildSession } from "@/lib/types";

const STYLE = {
  done: "bg-ok-bg text-ok",
  current: "bg-accent text-accent-fg",
  failed: "bg-bad-bg text-bad",
  todo: "bg-surface-2 text-muted",
} as const;

const WORD = { done: "done", current: "now", failed: "failed", todo: "not yet" } as const;

/** Where the person is: Describe, Answer, Approve, Build, Save. Each step has a word for its state, not just a colour. */
export function ProgressStrip({ session }: { session: BuildSession }) {
  const steps = progressSteps(session);
  return (
    <ol aria-label="Progress" className="mb-5 flex flex-wrap gap-x-1 gap-y-2 text-sm">
      {steps.map((s, i) => (
        <li key={s.label} aria-current={s.state === "current" || s.state === "failed" ? "step" : undefined} className="flex items-center gap-1">
          <span className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 font-medium ${STYLE[s.state]}`}>
            <span aria-hidden>{s.state === "done" ? "✓" : s.state === "failed" ? "!" : i + 1}</span>
            {s.label}
            <span className="sr-only"> ({WORD[s.state]})</span>
          </span>
          {i < steps.length - 1 && <span aria-hidden className="text-muted">›</span>}
        </li>
      ))}
    </ol>
  );
}
