import { plural } from "./format";
import { withKindParam } from "./kind";
import type { BuildSummary, ProviderStatus, RescanResult, SandboxStatus, ScanFinding, SkillSummary, VersionScan } from "./types";

/**
 * What the Dashboard says, worked out by code from answers the API already gives (docs/dashboard.md). Nothing here asks a model or runs anything, and every
 * function is pure, so it is tested without a browser.
 */

export type AttentionTone = "bad" | "warn" | "info";

export interface AttentionItem {
  /** Unique across kinds, so two skills with the same name in different kinds stay apart. */
  key: string;
  tone: AttentionTone;
  title: string;
  detail: string;
  /** Where to go about it, or null when there is nowhere (the sandbox cannot be fixed from a page). */
  href: string | null;
}

export interface DashboardInput {
  /** Today's checks on every stored version, one answer per kind of thing. */
  scans: { kind: string; label: string; result: RescanResult }[];
  /** The builds, newest first as the API gives them. */
  builds: BuildSummary[];
  /** Absent while it is still being asked (or could not be): nothing is said about what is not known. */
  provider?: Pick<ProviderStatus, "configured" | "detail">;
  sandbox?: SandboxStatus;
}

export const MAX_ATTENTION = 10;
const LABEL_LENGTH = 60;
const DETAIL_LENGTH = 200;
const RANK: Record<AttentionTone, number> = { bad: 0, warn: 1, info: 2 };

/** One line to call a build by: the skill's name, or the first words of what the person asked for. */
export function buildLabel(b: Pick<BuildSummary, "skill" | "description">): string {
  if (b.skill) return b.skill;
  const words = b.description.split(/\s+/).filter(Boolean).join(" ");
  if (!words) return "(untitled)";
  return words.length <= LABEL_LENGTH ? words : `${words.slice(0, LABEL_LENGTH - 1)}…`;
}

/** "x", "x, y", or "x, y and 1 more": the checks by name, without a wall of text. */
function names(findings: ScanFinding[]): string {
  const all = findings.map((f) => f.name);
  return all.length <= 2 ? all.join(", ") : `${all.slice(0, 2).join(", ")} and ${all.length - 2} more`;
}

const cut = (text: string): string => (text.length <= DETAIL_LENGTH ? text : `${text.slice(0, DETAIL_LENGTH - 1)}…`);

function fromScan(kind: string, v: VersionScan): AttentionItem | null {
  const href = withKindParam(`/library/${encodeURIComponent(v.name)}`, kind);
  const key = `scan:${kind}:${v.name}:${v.tag}`;
  if (v.status === "damaged") return { key, tone: "bad", title: `${v.name} cannot be read`, detail: v.message || "Its files are damaged or missing.", href };
  if (v.status === "failing") {
    const failed = v.findings.filter((f) => f.status === "failed");
    const shown = failed.length > 0 ? failed : v.findings;
    return { key, tone: "bad", title: `${v.name} ${v.tag} fails ${plural(shown.length, "check")} today`, detail: names(shown), href };
  }
  if (v.status === "worse") {
    return { key, tone: "warn", title: `${v.name} ${v.tag}: ${plural(v.findings.length, "check")} got worse since it was imported`, detail: names(v.findings), href };
  }
  return null;
}

function fromBuild(b: BuildSummary): AttentionItem | null {
  const href = `/builder/${b.id}`;
  const key = `build:${b.id}`;
  const label = buildLabel(b);
  switch (b.status) {
    case "awaiting_answers":
      return { key, tone: "info", title: `Waiting for your answers: ${label}`, detail: "Open it to answer, and it carries on.", href };
    case "awaiting_approval":
      return { key, tone: "info", title: `Waiting for your approval: ${label}`, detail: "Open it to read the requirement and approve it.", href };
    case "failed":
      return { key, tone: "bad", title: `A build failed: ${label}`, detail: "Open it to see why, and to try again.", href };
    case "done":
      if (b.saved) return null;
      return b.draft
        ? { key, tone: "warn", title: `A draft was not saved: ${label}`, detail: "It did not pass every check. Open it to read why, or to discard it.", href }
        : { key, tone: "info", title: `Finished, not saved to the library: ${label}`, detail: "Open it to save it, or to discard it.", href };
    default:
      return null; // still working: that is progress, not something to do
  }
}

/** What needs the person, worst first (bad, then warning, then info; inside one tone, the order the data came in), at most `limit` of it and a count of the rest. */
export function attentionItems(input: DashboardInput, limit: number = MAX_ATTENTION): { items: AttentionItem[]; more: number } {
  const found: AttentionItem[] = [];
  for (const { kind, result } of input.scans) {
    for (const v of result.versions) {
      const item = fromScan(kind, v);
      if (item) found.push(item);
    }
  }
  for (const b of input.builds) {
    const item = fromBuild(b);
    if (item) found.push(item);
  }
  if (input.provider && !input.provider.configured) {
    found.push({ key: "provider", tone: "warn", title: "No AI model is set up", detail: cut(input.provider.detail), href: "/settings" });
  }
  if (input.sandbox && !input.sandbox.available) {
    found.push({ key: "sandbox", tone: "info", title: "The sandbox is not available", detail: cut(input.sandbox.reason), href: null });
  }
  const sorted = found.map((item, order) => ({ item, order })).sort((a, b) => RANK[a.item.tone] - RANK[b.item.tone] || a.order - b.order).map((x) => x.item);
  return { items: sorted.slice(0, limit), more: Math.max(0, sorted.length - limit) };
}

export interface LibraryRow {
  kind: string;
  label: string;
  skills: number;
  versions: number;
  /** Set when this kind's library could not be read: the page says so, and the counts above are not "zero", they are unknown. */
  error?: string;
}

export interface RecentVersion {
  kind: string;
  name: string;
  tag: string;
  created_at: string;
  href: string;
}

/** How much the library holds, per kind and in all, and the versions saved most recently (across kinds, newest first). */
export function libraryOverview(
  lists: { kind: string; label: string; skills?: SkillSummary[]; error?: string }[],
  recentLimit = 5,
): { rows: LibraryRow[]; recent: RecentVersion[]; total: { skills: number; versions: number } } {
  const rows: LibraryRow[] = lists.map((l) =>
    l.error !== undefined
      ? { kind: l.kind, label: l.label, skills: 0, versions: 0, error: l.error }
      : { kind: l.kind, label: l.label, skills: (l.skills ?? []).length, versions: (l.skills ?? []).reduce((sum, s) => sum + s.versions, 0) },
  );
  const recent: RecentVersion[] = lists
    .flatMap((l) =>
      (l.skills ?? []).flatMap((s) =>
        s.latest ? [{ kind: l.kind, name: s.name, tag: s.latest.tag, created_at: s.latest.created_at, href: withKindParam(`/library/${encodeURIComponent(s.name)}`, l.kind) }] : [],
      ),
    )
    .sort((a, b) => (a.created_at < b.created_at ? 1 : a.created_at > b.created_at ? -1 : a.name.localeCompare(b.name)))
    .slice(0, recentLimit);
  return { rows, recent, total: { skills: rows.reduce((s, r) => s + r.skills, 0), versions: rows.reduce((s, r) => s + r.versions, 0) } };
}
