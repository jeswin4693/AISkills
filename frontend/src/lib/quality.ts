import { plural } from "./format";
import { outcomeLabel } from "./testing";
import type { CheckStatus, QualityChange, QualityLab, QualityLink, QualityReport, QualitySuggestion } from "./types";

/**
 * The Quality Report page's decisions, kept out of the components so they can be tested without a browser: tones, wording, and links. The server
 * decides every fact (what failed, what was covered, what did not run); nothing here works anything out, and nothing here ever says "safe".
 */

export type Tone = "ok" | "warn" | "bad" | "info" | "neutral";

/** A check that did not run is neutral: it is never shown in the colour of a pass. */
export const statusTone = (status: CheckStatus): Tone => ({ failed: "bad", warning: "warn", "not run": "neutral", passed: "ok" } as const)[status];

/** What a library check did since the skill was imported. Nothing is said for a check that did not change, or for one that was never kept at import. */
export function changeLabel(change: QualityChange): { text: string; tone: Tone } | null {
  switch (change) {
    case "worse":
      return { text: "worse than at import", tone: "bad" };
    case "better":
      return { text: "better than at import", tone: "ok" };
    case "new":
      return { text: "did not exist at import", tone: "info" };
    default:
      return null;
  }
}

export function headlineParts(h: QualityReport["headline"]): { key: string; text: string; tone: Tone }[] {
  return [
    { key: "failed", text: `${h.failed} failed`, tone: h.failed > 0 ? "bad" : "neutral" },
    { key: "warnings", text: plural(h.warnings, "warning"), tone: h.warnings > 0 ? "warn" : "neutral" },
    { key: "not_run", text: `${h.not_run} not run`, tone: "neutral" },
    { key: "passed", text: `${h.passed} passed`, tone: "ok" },
  ];
}

/** The requirement against its tests, in one line. A skill that records no requirement is said to, and no zero is shown as if all were covered. */
export function coverageLine(req: QualityReport["requirements"]): string {
  if (req.source === "none") return "No requirement is recorded for this skill, so there is nothing to compare its tests with.";
  if (req.criteria.length === 0) return "The requirement lists no acceptance criteria.";
  const without = req.criteria.filter((c) => c.tests.length === 0).length;
  const n = req.criteria.length;
  return `${n} acceptance ${n === 1 ? "criterion" : "criteria"}: ${n - without} with a test, ${without} without.`;
}

/** The Testing Lab's result for THIS version. A run of another version is never worded as this version's. */
export function labLine(lab: QualityLab): string {
  switch (lab.state) {
    case "this_version": {
      const r = lab.run!;
      const base = r.baseline ? ` · without it ${r.baseline.passed}/${r.baseline.total}` : "";
      return `The Testing Lab ran ${r.tag}: ${outcomeLabel(r.outcome)} (with the skill ${r.with_skill.passed}/${r.with_skill.total}${base}).`;
    }
    case "older_version":
      return `Only ${lab.other!.tag} was run in the Testing Lab (${outcomeLabel(lab.other!.outcome)}). This version has not been.`;
    case "running":
      return "A Testing Lab run of this version is going.";
    case "failed":
      return "The last Testing Lab run of this version did not finish.";
    default:
      return "The Testing Lab has not been run on this version.";
  }
}

/** The risk diff's level in words. Never "safe": a missing finding is not a finding of safety. */
export const riskWords = (level: NonNullable<QualityReport["changes"]>["level"]): string =>
  ({ more_risk: "Got riskier", look: "Worth a look", less_risk: "Got less risky", no_new_risk: "No new risk found" })[level];

/** Where a suggestion leads, or null when it leads nowhere. */
export function suggestionHref(link: QualityLink, name: string): string | null {
  if (!link) return null;
  const n = encodeURIComponent(name);
  switch (link.page) {
    case "lab":
      return `/testing?name=${n}&version=${link.version}`;
    case "skill":
      return `/library/${n}`;
    case "compare":
      return `/library/${n}/diff?from=${link.from}&to=${link.to}`;
  }
}

export const kindWord = (kind: QualitySuggestion["kind"]): string => ({ fix: "Fix", write: "Write", run: "Run", read: "Read", shorten: "Shorten" })[kind];

export function groupCaption(key: "library" | "design" | "written"): string {
  if (key === "library") return "The same checks as an import, run again today. Each says what it was when the skill was imported.";
  if (key === "design") return "The builder's own design checks, run again today from the skill's saved definition. They were not kept with the version at import.";
  return "The skill's written files held to the requirement it was built from, run again today. They were not kept with the version at import.";
}

export function tokenLine(t: QualityReport["tokens"]): string {
  return `About ${t.always} tokens always loaded (name and description), ${t.when_used} when the skill is used (SKILL.md), and ${t.on_demand} more in other files that the agent opens only if it needs them. These are estimates.`;
}
