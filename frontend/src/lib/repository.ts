import type { EvidenceRef, Idea, IdeaCategory, RepoAnalysis, RunStatus, SuggestRunSummary, Verdict } from "./types";

type Tone = "info" | "ok" | "warn" | "bad" | "neutral";

// ---- the folder a person works on, remembered in this browser only ------------------------------------------

export const REPO_KEY = "skillforge.repository";

export interface RememberedRepo {
  path: string;
  focus: string;
}

type Store = Pick<Storage, "getItem" | "setItem">;

function browserStore(): Store | undefined {
  try {
    return typeof window === "undefined" ? undefined : window.localStorage;
  } catch {
    return undefined; // blocked storage: the page works, it just does not remember
  }
}

export function loadRemembered(store: Store | undefined = browserStore()): RememberedRepo {
  try {
    const raw = store?.getItem(REPO_KEY);
    const v = raw ? (JSON.parse(raw) as Partial<RememberedRepo>) : {};
    return { path: typeof v.path === "string" ? v.path : "", focus: typeof v.focus === "string" ? v.focus : "" };
  } catch {
    return { path: "", focus: "" };
  }
}

export function remember(value: RememberedRepo, store: Store | undefined = browserStore()): void {
  try {
    store?.setItem(REPO_KEY, JSON.stringify(value));
  } catch {
    /* nothing to do: the next visit starts empty */
  }
}

/** A network path (\\server\share, //server/share): opening it would reach out to another machine, so the server does not read it. */
export function isNetworkPath(path: string): boolean {
  const p = path.trim();
  return p.startsWith("\\\\") || p.startsWith("//");
}

/** The server needs a full path on this computer, such as C:\code\repo or /home/me/repo. A bare folder name is not one. */
export function looksAbsolute(path: string): boolean {
  const p = path.trim();
  return !isNetworkPath(p) && (/^[A-Za-z]:[\\/]/.test(p) || p.startsWith("/"));
}

/** What to tell the person about a folder path before anything is sent, or null when it looks usable. */
export function pathProblem(path: string): string | null {
  if (!path.trim()) return null;
  if (isNetworkPath(path)) return "Network paths are not read. Use a folder on this computer (map the share to a drive letter first).";
  return looksAbsolute(path) ? null : "Give the full path of the folder, such as C:\\code\\shop or /home/me/shop.";
}

// ---- what the graph says ------------------------------------------------------------------------------------

const LEVEL: Record<string, string> = {
  full: "calls and imports are resolved; the facts here are as deep as they get",
  standard: "calls and imports are resolved for most code",
  basic: "files are counted and symbols found, but calls are not resolved",
};

export function levelNote(level: string | undefined): string {
  return (level && LEVEL[level]) || "level not known";
}

export function languageRows(stats: RepoAnalysis["stats"]): { name: string; files: number; level: string; note: string }[] {
  return Object.entries(stats.languages)
    .map(([name, files]) => ({ name, files, level: stats.language_levels[name] ?? "basic", note: levelNote(stats.language_levels[name]) }))
    .sort((a, b) => b.files - a.files || a.name.localeCompare(b.name));
}

/** How much of the call graph is proven. Guesses are never counted as links, so the page says how many calls were left out. */
export function callSummary(stats: RepoAnalysis["stats"]): string {
  const c = stats.call_sites;
  const total = Object.values(c).reduce((a, b) => a + b, 0);
  if (total === 0) return "No calls were found.";
  const resolved = c.resolved ?? 0;
  return `${resolved} of ${total} calls are tied to the function they call (${Math.round((resolved / total) * 100)}%). The rest are outside the repository, ambiguous or only a name match, and are left out.`;
}

// ---- ideas ---------------------------------------------------------------------------------------------------

export const CATEGORY: Record<IdeaCategory, { label: string; tone: Tone; buildable: boolean }> = {
  skill: { label: "Skill idea", tone: "ok", buildable: true },
  automation: { label: "Automation idea", tone: "ok", buildable: true },
  refactor: { label: "Refactor", tone: "info", buildable: false },
  test: { label: "Tests", tone: "info", buildable: false },
  cleanup: { label: "Cleanup", tone: "neutral", buildable: false },
  risk: { label: "Risk", tone: "warn", buildable: false },
};

export function categoryInfo(category: string): { label: string; tone: Tone; buildable: boolean } {
  return CATEGORY[category as IdeaCategory] ?? { label: category, tone: "neutral", buildable: false };
}

/** An idea can start a build when it is a skill or automation idea that carries a requirement and cites places that exist. */
export function canBuild(idea: Idea): boolean {
  return categoryInfo(idea.category).buildable && idea.skill_requirement.trim().length >= 20 && idea.evidence_nodes.length > 0;
}

/**
 * What starting a build from an idea sends: the requirement text (the model's wording, or the person's edit of it) and which idea of
 * which run. The server takes the folder and the cited places from the run itself.
 */
export function buildRequest(text: string, runId: string, index: number): { description: string; seed: { run: string; idea: number } } {
  return { description: text.trim(), seed: { run: runId, idea: index } };
}

/** The key of one idea's edited wording: a run and a position, so a later run with a same-titled idea never inherits an edit. */
export function ideaKey(runId: string, index: number): string {
  return `${runId}:${index}`;
}

/** A run that is still asking the model (the page picks it up again after a reload, so a second click does not start another). */
export function workingRun(runs: SuggestRunSummary[] | undefined): SuggestRunSummary | undefined {
  return runs?.find((r) => r.status === "working");
}

/** Buildable ideas first (they are what this app makes), then the rest, each group keeping the order the model gave. */
export function ideaGroups(ideas: Idea[]): { buildable: Idea[]; other: Idea[] } {
  return { buildable: ideas.filter((i) => categoryInfo(i.category).buildable), other: ideas.filter((i) => !categoryInfo(i.category).buildable) };
}

export function runInfo(status: RunStatus): { label: string; tone: Tone } {
  switch (status) {
    case "working": return { label: "Asking the model", tone: "info" };
    case "done": return { label: "Done", tone: "ok" };
    case "failed": return { label: "Failed", tone: "bad" };
  }
}

// ---- evidence ------------------------------------------------------------------------------------------------

const VERDICT: Record<Verdict, { label: string; tone: Tone; hint: string }> = {
  missing: { label: "Missing", tone: "bad", hint: "the cited place is gone" },
  moved: { label: "Moved?", tone: "warn", hint: "gone, and exactly one place looks like it: a candidate, never applied for you" },
  changed: { label: "Changed", tone: "warn", hint: "it is there and a recorded fact differs" },
  edited: { label: "Edited", tone: "info", hint: "the facts are the same but the text differs" },
  holds: { label: "Holds", tone: "ok", hint: "every recorded fact is the same, and so is the text" },
};

/** Worst first, the order a recheck report lists them in. */
export const VERDICT_ORDER: Verdict[] = ["missing", "moved", "changed", "edited", "holds"];

export function verdictInfo(status: Verdict): { label: string; tone: Tone; hint: string } {
  return VERDICT[status] ?? { label: status, tone: "neutral", hint: "" };
}

/** "2026-11-23, commit 023faa8e (with uncommitted changes)" for one cited place. */
export function recordedWhen(ref: Pick<EvidenceRef, "taken_at" | "commit" | "dirty">, fallback?: { taken_at: string; commit: string | null }): string {
  const when = (ref.taken_at ?? fallback?.taken_at ?? "").slice(0, 10);
  const commit = ref.commit ?? fallback?.commit ?? null;
  return [when, commit ? `commit ${commit}${ref.dirty ? " (with uncommitted changes)" : ""}` : ""].filter(Boolean).join(", ");
}

/** What was recorded about a place, in a few words a person can read. */
export function factSummary(ref: EvidenceRef): string {
  if (ref.kind === "file") {
    const parts = [`${ref.symbols_total} symbol${ref.symbols_total === 1 ? "" : "s"}`];
    if (ref.measured) parts.push(`imported by ${ref.importers_total}`);
    return parts.join(", ");
  }
  const parts = [ref.symbol_kind || "symbol"];
  if (ref.measured) parts.push(`${ref.callers_total} caller${ref.callers_total === 1 ? "" : "s"}`, `calls ${ref.callees_total}`);
  else parts.push("callers not measured in this language");
  if (ref.symbol_kind === "class") parts.push(`${ref.members_total} method${ref.members_total === 1 ? "" : "s"}`);
  return parts.join(", ");
}
