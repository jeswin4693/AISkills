import { plural } from "./format";
import type { RescanResult, RiskDirection, RiskInfo, RiskLevel, ScanFinding, ScanStatus } from "./types";

type Tone = "ok" | "warn" | "bad" | "info";

/**
 * The headline for a risk diff. Two rules: it never says "safe" (code reads patterns, not meaning), and the words
 * match the colour, because colour must never be the only signal.
 */
export function riskHeadline(level: RiskLevel): { tone: Tone; title: string } {
  switch (level) {
    case "more_risk":
      return { tone: "bad", title: "More risk than the version before" };
    case "look":
      return { tone: "warn", title: "Worth a look" };
    case "less_risk":
      return { tone: "ok", title: "Less risk than the version before" };
    default:
      return { tone: "info", title: "No new risk found by these checks" };
  }
}

export const DIRECTION_LABEL: Record<RiskDirection, string> = {
  riskier: "More risk",
  look: "Worth a look",
  safer: "Less risk",
};

export const DIRECTION_TONE: Record<RiskDirection, "bad" | "warn" | "ok"> = { riskier: "bad", look: "warn", safer: "ok" };

/** "2 more risk, 1 to look at, 0 less risk" without the zeros. */
export function riskCounts(risk: RiskInfo): string {
  const parts: string[] = [];
  if (risk.counts.riskier) parts.push(`${risk.counts.riskier} more risk`);
  if (risk.counts.look) parts.push(`${risk.counts.look} to look at`);
  if (risk.counts.safer) parts.push(`${risk.counts.safer} less risk`);
  return parts.join(", ");
}

export const SCAN_LABEL: Record<ScanStatus, string> = {
  same: "same as at import",
  worse: "worse than at import",
  failing: "fails today",
  damaged: "damaged",
};

export const SCAN_TONE: Record<ScanStatus, "ok" | "warn" | "bad"> = { same: "ok", worse: "warn", failing: "bad", damaged: "bad" };

/** The one sentence on top of a rescan. */
export function rescanHeadline(r: RescanResult): { tone: Tone; title: string } {
  const total = r.versions.length;
  if (total === 0) return { tone: "info", title: "There is nothing to re-check yet" };
  const { same, worse, failing, damaged } = r.counts;
  if (same === total) return { tone: "ok", title: `Nothing got worse: ${plural(total, "version")} checked` };
  const bad = [
    failing && `${plural(failing, "version")} fail${failing === 1 ? "s" : ""} today`,
    damaged && `${plural(damaged, "version")} damaged`,
    worse && `${plural(worse, "version")} worse than at import`,
  ].filter(Boolean);
  return { tone: failing || damaged ? "bad" : "warn", title: `${bad.join(", ")} (of ${total})` };
}

/** What one finding says, in a sentence. */
export function findingText(f: ScanFinding): string {
  const was = f.was === "found now" ? "this check did not exist at import" : `it was ${f.was} at import`;
  return `${f.status === "failed" ? "Fails" : "Warns"}: ${f.name} (${was})`;
}
