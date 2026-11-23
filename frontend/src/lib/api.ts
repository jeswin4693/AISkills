import type {
  AuthStatus, BuildSession, BuildSummary, DiffResult, EvidenceDoc, FileText, Health, HookInfo, ImportResult, InstallRequest, InstallResult, KindInfo, PluginPreview, PluginRequest, PluginSaveResult, ProviderStatus,
  RecheckReport, RepoAnalysis, RescanResult, SandboxStatus, SaveResult, SkillSummary, SuggestRun, SuggestRunSummary, VersionInfo,
} from "./types";

import { SIGNED_OUT_EVENT } from "./auth";

// "same-origin" (set when the hosted version is built) means the page and the API share one address, so calls are relative.
const configured = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
export const API_URL = configured === "same-origin" ? "" : configured.replace(/\/+$/, "");

/** Something the person can act on. status 0 means the API could not be reached at all. */
export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

/** FastAPI sends `detail` as a string, or as a list of problems for a malformed request. */
export function detailOf(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail.map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : "")).filter(Boolean);
    if (parts.length) return parts.join("; ");
  }
  return fallback;
}

/**
 * Each path segment is encoded. A `.` or `..` segment is refused outright: a URL parser collapses those, even when
 * written as %2e, so they could change which endpoint is called. Skill file paths never contain them (the validator
 * fails them), and the UI only asks for paths the API itself listed.
 */
export function encodePath(path: string): string {
  const parts = path.split("/");
  if (parts.some((p) => p === "" || p === "." || p === "..")) throw new ApiError(400, `'${path}' is not a plain file path.`);
  return parts.map(encodeURIComponent).join("/");
}

async function send(path: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(API_URL + path, init);
  } catch {
    throw new ApiError(0, `Cannot reach the SkillForge API at ${API_URL || "this site"}. Start it with: python -m skillforge serve`);
  }
}

async function json<T>(res: Response, accept: number[] = []): Promise<T> {
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    /* not JSON: the fallback message below is used */
  }
  if (res.status === 401 && typeof window !== "undefined") window.dispatchEvent(new Event(SIGNED_OUT_EVENT)); // the sign-in ended: ask again
  if (!res.ok && !accept.includes(res.status)) throw new ApiError(res.status, detailOf(body, `The API answered ${res.status}.`));
  return body as T;
}

const get = async <T,>(path: string): Promise<T> => json<T>(await send(path));
const post = async <T,>(path: string, body: unknown): Promise<T> =>
  json<T>(await send(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }));

/** `?kind=` is added only for a kind other than skill, so every skill URL is exactly what it always was. */
const withKind = (path: string, kind?: string): string =>
  kind && kind !== "skill" ? `${path}${path.includes("?") ? "&" : "?"}kind=${encodeURIComponent(kind)}` : path;

export const api = {
  health: () => get<Health>("/api/health"),
  kinds: () => get<KindInfo[]>("/api/kinds"),

  // ---- plugins: composed from the library, no model ----
  /** The hooks a plugin may carry: the catalogue, and nothing else. */
  hooks: () => get<HookInfo[]>("/api/hooks"),
  previewPlugin: (req: PluginRequest) => post<PluginPreview>("/api/plugins/preview", req),
  /** 200 and 422 both carry a report (kept or unchanged, or refused with the checks that failed). */
  async savePlugin(req: PluginRequest): Promise<PluginSaveResult> {
    const res = await send("/api/plugins", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req) });
    return json<PluginSaveResult>(res, [422]);
  },

  sandbox: () => get<SandboxStatus>("/api/sandbox"),
  provider: () => get<ProviderStatus>("/api/provider"),

  // ---- the hosted version's sign-in (the local version never asks) ----
  authStatus: () => get<AuthStatus>("/api/auth/status"),
  login: (token: string) => post<{ authenticated: boolean }>("/api/auth/login", { token }),
  logout: () => post<{ authenticated: boolean }>("/api/auth/logout", {}),

  listSkills: (kind?: string) => get<SkillSummary[]>(withKind("/api/library", kind)),
  versions: (name: string, kind?: string) =>
    get<{ name: string; versions: VersionInfo[] }>(withKind(`/api/library/${encodeURIComponent(name)}`, kind)),
  diff: (name: string, from?: number, to?: number, kind?: string) => {
    const q = new URLSearchParams();
    if (from !== undefined) q.set("frm", String(from));
    if (to !== undefined) q.set("to", String(to));
    if (kind && kind !== "skill") q.set("kind", kind);
    const qs = q.toString();
    return get<DiffResult>(`/api/library/${encodeURIComponent(name)}/diff${qs ? `?${qs}` : ""}`);
  },
  file: (name: string, version: number, path: string, kind?: string) =>
    get<FileText>(withKind(`/api/library/${encodeURIComponent(name)}/versions/${version}/files/${encodePath(path)}`, kind)),

  /** Today's static checks on stored versions (every skill, or one). Reads only: nothing is changed or run. */
  rescan: (name?: string, kind?: string) => get<RescanResult>(withKind(`/api/rescan${name ? `?name=${encodeURIComponent(name)}` : ""}`, kind)),

  /** 200 and 422 both carry a report (kept, or refused with the checks that failed); anything else is an error. */
  async importZip(file: File, opts: { note?: string; testScripts?: boolean; kind?: string } = {}): Promise<ImportResult> {
    const q = new URLSearchParams({ filename: file.name });
    if (opts.note?.trim()) q.set("note", opts.note.trim());
    if (opts.testScripts) q.set("test_scripts", "true");
    if (opts.kind && opts.kind !== "skill") q.set("kind", opts.kind);
    const res = await send(`/api/library/import?${q}`, { method: "POST", headers: { "Content-Type": "application/zip" }, body: file });
    return json<ImportResult>(res, [422]);
  },

  rollback: (name: string, to: number, kind?: string) =>
    post<{ created: boolean; version: VersionInfo }>(withKind(`/api/library/${encodeURIComponent(name)}/rollback`, kind), { to }),

  install: (name: string, req: InstallRequest, kind?: string) =>
    post<InstallResult>(withKind(`/api/library/${encodeURIComponent(name)}/install`, kind), req),

  // ---- a repository: read on this computer (the hosted version refuses all of these) ----
  analyzeRepo: (path: string, focus?: string) => post<RepoAnalysis>("/api/repos/analyze", { path, focus: focus || null }),
  startSuggest: (path: string, focus: string | undefined, withIdeas: boolean) =>
    post<SuggestRun>("/api/suggestions", { path, focus: focus || null, with_ideas: withIdeas }),
  suggestRun: (id: string) => get<SuggestRun>(`/api/suggestions/${encodeURIComponent(id)}`),
  suggestRuns: () => get<SuggestRunSummary[]>("/api/suggestions"),
  retrySuggest: (id: string) => post<SuggestRun>(`/api/suggestions/${encodeURIComponent(id)}/retry`, {}),

  // ---- evidence: the code a stored skill cites, and what changed in it ----
  evidence: (name: string, version?: number, kind?: string) =>
    get<EvidenceDoc>(withKind(`/api/library/${encodeURIComponent(name)}/evidence${version === undefined ? "" : `?version=${version}`}`, kind)),
  recheck: (name: string, req: { repo: string; version?: number; focus?: string }, kind?: string) =>
    post<RecheckReport>(withKind(`/api/library/${encodeURIComponent(name)}/recheck`, kind), req),

  // ---- the builder: a session you poll; each action returns the session as it is right after the action ----
  builds: () => get<BuildSummary[]>("/api/builds"),
  build: (id: string) => get<BuildSession>(`/api/builds/${encodeURIComponent(id)}`),
  /**
   * `seed` starts the build from an idea about a repository, so the built skill carries evidence of the places the idea cited. Give the
   * run and the idea's position: the server then takes that run's own folder and the idea's own places, so a build cannot be about a
   * different repository than its idea was made for. (`repo` + `evidenceNodes` is for scripts that have no run.)
   */
  startBuild: (
    description: string, withScripts: boolean, kind = "skill",
    seed?: { run: string; idea: number } | { repo: string; focus?: string; evidenceNodes: string[] },
  ) =>
    post<BuildSession>("/api/builds", {
      description, with_scripts: withScripts, ...(kind === "skill" ? {} : { kind }),
      ...(!seed ? {} : "run" in seed ? { from_run: seed.run, idea: seed.idea } : { repo: seed.repo, focus: seed.focus || null, evidence_nodes: seed.evidenceNodes }),
    }),
  answer: (id: string, answers: Record<string, string>) => post<BuildSession>(`/api/builds/${encodeURIComponent(id)}/answers`, { answers }),
  approve: (id: string) => post<BuildSession>(`/api/builds/${encodeURIComponent(id)}/approve`, {}),
  retry: (id: string) => post<BuildSession>(`/api/builds/${encodeURIComponent(id)}/retry`, {}),
  buildFile: (id: string, path: string) => get<FileText>(`/api/builds/${encodeURIComponent(id)}/files/${encodePath(path)}`),

  /** 200 and 422 both carry a report (kept, or refused with the checks that failed). 409 (a draft not accepted) is an error. */
  async saveBuild(id: string, opts: { acceptDraft?: boolean; note?: string } = {}): Promise<SaveResult> {
    const res = await send(`/api/builds/${encodeURIComponent(id)}/save`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ accept_draft: opts.acceptDraft ?? false, note: opts.note ?? "" }),
    });
    return json<SaveResult>(res, [422]);
  },

  async discardBuild(id: string): Promise<void> {
    await json<unknown>(await send(`/api/builds/${encodeURIComponent(id)}`, { method: "DELETE" }));
  },

  /** The zip as a Blob, with the file name the API suggested. */
  async exportZip(name: string, version: number, withoutSpec: boolean, kind?: string, withoutEvidence = false): Promise<{ blob: Blob; filename: string }> {
    const q = new URLSearchParams({ version: String(version), without_spec: String(withoutSpec) });
    if (withoutEvidence) q.set("without_evidence", "true");
    if (kind && kind !== "skill") q.set("kind", kind);
    const res = await send(`/api/library/${encodeURIComponent(name)}/export?${q}`);
    if (!res.ok) {
      let body: unknown = null;
      try {
        body = await res.json();
      } catch {
        /* keep the fallback */
      }
      throw new ApiError(res.status, detailOf(body, `The API answered ${res.status}.`));
    }
    const m = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "");
    return { blob: await res.blob(), filename: m?.[1] ?? `${name}-v${version}.zip` };
  },
};
