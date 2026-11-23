"use client";

import { useId } from "react";
import { categoryInfo } from "@/lib/repository";
import type { Idea } from "@/lib/types";
import { Badge, Button, Card } from "../ui";

const CONFIDENCE = { high: "ok", medium: "info", low: "warn" } as const;

/**
 * One idea. It was kept because everything it cites exists in the graph; whether its reasoning is right is for the person to judge,
 * and the card says so. A skill or automation idea can start a build, which then records the cited places as evidence.
 */
export function IdeaCard({
  idea, requirement, onRequirement, canStart, why, busy, onBuild,
}: {
  idea: Idea;
  /** What the skill will be asked to do: the model's wording to start with, and whatever the person changed it to. */
  requirement?: string;
  onRequirement?: (text: string) => void;
  canStart: boolean;
  why?: string;
  busy: boolean;
  onBuild: () => void;
}) {
  const cat = categoryInfo(idea.category);
  const textId = useId();
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="min-w-0 flex-1 font-semibold">{idea.title}</h3>
        <Badge tone={cat.tone}>{cat.label}</Badge>
        <Badge tone={CONFIDENCE[idea.confidence]} title="How sure the model says it is. This is its own statement: nothing checks it.">
          {idea.confidence} confidence
        </Badge>
      </div>
      <p className="mt-1.5 text-sm">{idea.rationale}</p>

      <div className="mt-3">
        <p className="text-xs font-medium tracking-wide text-muted uppercase">Cites (these exist in the graph)</p>
        <ul className="mt-1 flex flex-wrap gap-1.5">
          {idea.evidence_nodes.map((n) => (
            <li key={n} className="rounded border border-border bg-surface-2 px-1.5 py-0.5 font-mono text-xs break-all">
              {n}
            </li>
          ))}
        </ul>
        <p className="mt-1.5 text-xs text-muted">That the places exist is checked by code. Whether the reasoning above is right is not: read it against that code.</p>
      </div>

      {idea.unverified_numbers.length > 0 && (
        <p className="mt-2 text-xs text-warn">
          It mentions {idea.unverified_numbers.join(", ")}, which appear nowhere in the facts the model was given. Do not rely on {idea.unverified_numbers.length === 1 ? "that number" : "those numbers"}.
        </p>
      )}
      <p className="mt-2 text-sm text-muted">
        <span className="font-medium text-text">First step:</span> {idea.next_step}
      </p>

      {cat.buildable && onRequirement && (
        <details className="mt-3 rounded-lg border border-border p-3">
          <summary className="cursor-pointer text-sm font-medium">What the skill will be asked to do (you can change it)</summary>
          <label htmlFor={textId} className="mt-2 block text-xs text-muted">
            This is the model&apos;s wording. A skill is reusable instructions an agent follows, with something it receives and something it produces. If the wording reads like an
            action to carry out (&ldquo;Refactor these functions&rdquo;), the builder may refuse it as an agent: say here what the skill itself should do.
          </label>
          <textarea
            id={textId}
            rows={5}
            maxLength={10000}
            value={requirement ?? idea.skill_requirement}
            onChange={(e) => onRequirement(e.target.value)}
            className="mt-1.5 block w-full rounded-md border border-border bg-bg px-3 py-2 text-sm"
          />
        </details>
      )}

      {cat.buildable && (
        <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-border pt-3">
          <Button variant="primary" busy={busy} disabled={!canStart} onClick={onBuild}>
            Build this as a skill
          </Button>
          <span className="max-w-prose text-xs text-muted">
            {canStart
              ? "You will be asked only what is missing, and approve the requirement before anything is built. The result records the places above as evidence, so you can recheck it when the code changes."
              : why}
          </span>
        </div>
      )}
    </Card>
  );
}
