import { plural, relativeTime } from "./format";
import type { EvidenceRef, Idea, IdeaCategory, RepoAnalysis, RepoSource, RunStatus, SuggestRunSummary, Verdict } from "./types";

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

// ---- a GitHub link instead of a folder ----------------------------------------------------------------------
// The server is the authority (builder/github.py); this only spares a round trip for the mistakes people actually make.

const OWNER = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$/;
const NAME = /^[A-Za-z0-9._-]{1,100}$/;
const LINK_START = /^[A-Za-z][A-Za-z0-9+.-]*:\/\//;
const GITHUB_HELP =
  "Give the link of a public GitHub repository, such as https://github.com/owner/repo (or https://github.com/owner/repo/tree/branch). Other sites and other kinds of link are not read.";
const FOCUS_HELP =
  "To read one folder of the repository, use the 'Only this folder inside it' box and give the repository's own link. A branch name with a slash cannot be given in a link.";

/** Whether the box holds something meant as a link (so a problem is about links) and not a folder path. */
export function isLinkLike(text: string): boolean {
  const t = text.trim();
  return LINK_START.test(t) || /^(www\.)?github\.com(\/|$)/i.test(t);
}

export interface GithubRef {
  owner: string;
  repo: string;
  ref: string | null;
}

type Parsed = { ref: GithubRef } | { problem: string };

function parseGithub(text: string): Parsed {
  const raw = text.trim();
  const candidate = LINK_START.test(raw) ? raw : `https://${raw}`;
  if ([...candidate].some((c) => c.charCodeAt(0) <= 32 || c.charCodeAt(0) === 127)) return { problem: GITHUB_HELP };
  let url: URL;
  try {
    url = new URL(candidate);
  } catch {
    return { problem: GITHUB_HELP };
  }
  const host = url.host.toLowerCase();
  if (url.protocol === "http:" && (host === "github.com" || host === "www.github.com")) return { problem: "Use an https:// link." };
  if (url.protocol !== "https:" || (host !== "github.com" && host !== "www.github.com") || url.username || url.password) return { problem: GITHUB_HELP };
  if (url.pathname.includes("%")) return { problem: GITHUB_HELP };
  const segments = url.pathname.split("/").slice(1);
  if (segments.length && segments[segments.length - 1] === "") segments.pop();
  if (segments.length < 2 || segments.some((s) => s === "")) return { problem: GITHUB_HELP };
  const owner = segments[0];
  let repo = segments[1];
  if (repo.endsWith(".git") && repo.length > 4) repo = repo.slice(0, -4);
  let ref: string | null = null;
  if (segments.length > 2) {
    if (segments[2] !== "tree") return { problem: GITHUB_HELP };
    if (segments.length > 4) return { problem: FOCUS_HELP };
    if (segments.length !== 4) return { problem: GITHUB_HELP };
    ref = segments[3];
  }
  const dots = (s: string) => /^\.+$/.test(s);
  if (!OWNER.test(owner) || !NAME.test(repo) || dots(repo) || (ref !== null && (!NAME.test(ref) || dots(ref)))) return { problem: GITHUB_HELP };
  return { ref: { owner, repo, ref } };
}

/** The repository a GitHub link names, or null when the text is not a plain public repository link. */
export function githubRef(text: string): GithubRef | null {
  const r = parseGithub(text);
  return "ref" in r ? r.ref : null;
}

/** What is wrong with a link, in words, or null when it is usable (or the box is empty). */
export function githubProblem(text: string): string | null {
  if (!text.trim()) return null;
  const r = parseGithub(text);
  return "problem" in r ? r.problem : null;
}

/** `owner/repo` for a GitHub link, the way the page names it, and an empty text for anything else. */
export function repoLabel(text: string): string {
  const r = githubRef(text);
  return r ? `${r.owner}/${r.repo}` : "";
}

const SKIP_TEXT: [string, (n: number) => string][] = [
  ["not_source", (n) => `${plural(n, "other file")} (docs, images, data) not read`],
  ["ignored_dir", (n) => `${plural(n, "file")} in folders such as node_modules left out`],
  ["too_large", (n) => `${plural(n, "file")} over 1 MB left out`],
  ["link", (n) => `${plural(n, "symbolic link")} left out`],
  ["unsafe_name", (n) => `${plural(n, "file")} with an unsafe name left out`],
  ["duplicate", (n) => `${plural(n, "file")} whose name differs only in case left out`],
  ["limit", (n) => `${plural(n, "file")} left out because of the size limits`],
  ["path_too_long", (n) => `${plural(n, "file")} whose path is too long for this disk left out`],
  ["unwritable", (n) => `${plural(n, "file")} that could not be written left out`],
  ["unreadable", (n) => `${plural(n, "file")} that could not be read left out`],
];

/** What was left out of a download, one phrase for each reason that applies, in a fixed order. A reason this page does not know is not shown. */
export function skippedSummary(skipped: Record<string, number>): string[] {
  return SKIP_TEXT.filter(([key]) => (skipped[key] ?? 0) > 0).map(([key, say]) => say(skipped[key]));
}

function size(bytes: number): string {
  return bytes < 1_000_000 ? `${Math.max(1, Math.round(bytes / 1000))} KB` : `${(bytes / 1_000_000).toFixed(1)} MB`;
}

/** Where a repository came from, in lines for the summary: nothing for a folder; for a download, what was kept, that nothing was run, what was
 * left out and what a download cannot know. */
export function sourceNote(source: RepoSource, now: number = Date.now()): string[] {
  if (source.kind !== "github") return [];
  const which = source.ref ? `branch or tag ${source.ref}` : "default branch";
  const when = relativeTime(source.fetched_at, now);
  const lines = [
    `From GitHub (${which}), ${source.reused ? "a copy downloaded" : "downloaded"} ${when}: ${plural(source.files, "source file")} kept (${size(source.bytes)}). Nothing was run.`,
  ];
  const left = skippedSummary(source.skipped);
  if (left.length > 0) lines.push(`Left out: ${left.join("; ")}.`);
  lines.push("Git history is not downloaded, so facts that come from it (how often a file changes) are missing.");
  return lines;
}

/** What to tell the person about the box (a folder path or a GitHub link) before anything is sent, or null when it looks usable. */
export function pathProblem(path: string): string | null {
  if (!path.trim()) return null;
  if (isLinkLike(path)) return githubProblem(path);
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
