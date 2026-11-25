import { plural } from "./format";
import type { Guide, GuideHop, GuideJourney, GuidePart, GuideQuote, GuideStep, HopStatus, PartStatus } from "./types";

type Tone = "ok" | "warn" | "info" | "neutral";

/**
 * What a step of a route can be, in the words the page uses. Only `confirmed` is proof from the code. Everything else is what the documents say, and
 * the page must not let a reader mistake one for the other, so each says why it is not proof.
 */
export const HOP_INFO: Record<HopStatus, { label: string; tone: Tone; solid: boolean; why: string }> = {
  confirmed: { label: "Confirmed by the code", tone: "ok", solid: true, why: "Files in the first part really import files in the second. The file pairs are shown, so you can judge whether they are the real link." },
  both_ways: { label: "Imports both ways", tone: "warn", solid: false, why: "The code imports from the first part into the second and from the second into the first. The numbers show which way is stronger." },
  step_dropped: { label: "A step between was dropped", tone: "warn", solid: false, why: "A step the model put between these two could not be checked against the documents, so the two are not shown as joined." },
  reversed: { label: "The code imports the other way", tone: "warn", solid: false, why: "The documents say this order, but the code imports from the second part into the first. A callback or an event can look like that." },
  same_folder: { label: "One folder", tone: "neutral", solid: false, why: "Both parts are in the same folder, so imports cannot tell them apart." },
  not_measured: { label: "Not measured", tone: "neutral", solid: false, why: "SkillForge does not read the imports of a language used here, so this cannot be checked." },
  docs_only: { label: "From the docs only", tone: "info", solid: false, why: "The documents say so. The code does not import it directly: a web request or a message is not an import." },
};

export const PART_STATUS: Record<PartStatus, { label: string; tone: Tone }> = {
  // "found" is all that was checked: the folder the model named exists, which does not prove that the part really lives there
  in_code: { label: "Folder found in the code", tone: "ok" },
  docs_only: { label: "In the docs, not found in the code", tone: "warn" },
  external: { label: "Outside this repository", tone: "neutral" },
};

const DROP_REASON: Record<string, string> = {
  quote_not_found: "Quote not in the documents",
  quote_too_short: "Quote too short to check",
  quote_too_long: "Quote too long",
  unknown_part: "Named a part that was not kept",
  duplicate_id: "Repeated another part's id",
  bad_id: "No usable name or id",
  over_limit: "Over a limit",
  too_few_steps: "Fewer than two steps could be checked",
};

/** The layers that have a part in them, in the guide's order. An empty layer is not drawn. */
export function bands(guide: Guide): { id: string; label: string; parts: GuidePart[] }[] {
  return guide.layers
    .map((layer) => ({ ...layer, parts: guide.parts.filter((p) => p.layer === layer.id) }))
    .filter((band) => band.parts.length > 0);
}

/** For each part on a route, the step numbers it appears at (counting from 1). A part may come up twice. Empty with no journey. */
export function stepNumbers(journey: GuideJourney | undefined): Map<string, number[]> {
  const out = new Map<string, number[]>();
  (journey?.steps ?? []).forEach((s, i) => out.set(s.part, [...(out.get(s.part) ?? []), i + 1]));
  return out;
}

/** The route as a list: each step with its part, and the hop that leads from it to the next one. */
export function routeSteps(guide: Guide, journey: GuideJourney | undefined): { n: number; step: GuideStep; part: GuidePart | undefined; hopAfter: GuideHop | undefined }[] {
  const byId = new Map(guide.parts.map((p) => [p.id, p]));
  return (journey?.steps ?? []).map((step, i) => ({ n: i + 1, step, part: byId.get(step.part), hopAfter: journey?.hops[i] }));
}

/** The kinds of hop a route uses, each once, in the order they first appear: the legend lists only what is on the page. */
export function hopsUsed(journey: GuideJourney | undefined): HopStatus[] {
  return [...new Set((journey?.hops ?? []).map((h) => h.status))];
}

/** "3 files · 120 lines", or "" for a part with no files in the code. */
export function partFacts(p: Pick<GuidePart, "files" | "lines">): string {
  return p.files > 0 ? `${plural(p.files, "file")} · ${plural(p.lines, "line")}` : "";
}

export function quoteSource(q: GuideQuote): string {
  return `${q.source}, line ${q.line}`;
}

/** What stands behind a hop, in words: how many file pairs, and one of them; "" when no import is behind it. */
export function hopDetail(h: Pick<GuideHop, "status" | "forward" | "reverse" | "evidence">): string {
  if (h.status === "both_ways") return `${plural(h.forward, "file pair")} one way, ${plural(h.reverse, "file pair")} the other`;
  if (h.status !== "confirmed" && h.status !== "reversed") return "";
  const n = h.status === "confirmed" ? h.forward : h.reverse;
  const e = h.evidence[0];
  return `${plural(n, "file pair")}${e ? `, for example ${e.importer} imports ${e.imported}` : ""}`;
}

/** The warning under a quote that does not even mention the part it is given for, or "" when it does. */
export function quoteNote(q: Pick<GuideQuote, "on_topic">): string {
  return q.on_topic ? "" : "This sentence is in the documents, but it does not mention this part.";
}

/** What was dropped and why, one line per reason, the most common first. Empty when nothing was dropped. */
export function dropSummary(guide: Guide): string[] {
  const counts = new Map<string, number>();
  for (const d of guide.dropped) counts.set(d.reason, (counts.get(d.reason) ?? 0) + 1);
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([reason, n]) => `${DROP_REASON[reason] ?? reason}: ${n}`);
}

/** The documents that were read, as one line: "README.md (35 lines), docs/a.md (12 lines, cut)". */
export function docsRead(guide: Guide): string {
  return guide.docs.map((d) => `${d.path} (${plural(d.lines, "line")}${d.truncated ? ", cut" : ""})`).join(", ");
}

/** The part a reader should see first: the first step of the route, or else the first part. */
export function firstPart(guide: Guide, journey: GuideJourney | undefined): string | null {
  return journey?.steps[0]?.part ?? guide.parts[0]?.id ?? null;
}
