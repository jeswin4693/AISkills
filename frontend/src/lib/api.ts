import type {
  AdminPeople, AuthStatus, BuildSession, BuildSummary, CallGraph, CasesView, FunctionSearch, DeleteReport, EraseReport, ScanPreview, ScanRun, ScanRunSummary, ScanStart, QualityReport, DiffResult, EvalPreview, EvalRun, EvalRunSummary, EvidenceDoc, FileText, Guide, Health, HookInfo, ImportResult, InstallRequest, InstallResult, KindInfo, PluginPreview, PluginRequest, PluginSaveResult, ProviderStatus,
  ModelCheckReport, MyModelView, MySpace, Person, PlanAnswersRequest, PlanApproveResult, PlanRequest, PlanSessionView, PlanSummary, RecheckReport, RepoAnalysis, RescanResult, SandboxStatus, SaveMyModelResult, SaveResult, SaveSettingsResult, SettingsView,
  SkillSummary, SuggestRun, SuggestRunSummary, TaskPlan, VersionInfo,
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

  // ---- settings: what is set (never a key) and a save into the .env file; the hosted version refuses both ----
  settings: () => get<SettingsView>("/api/settings"),
  /** 200 is the new state; 400 says which settings were refused and why (never repeating a value). Anything else is an error. */
  async saveSettings(changes: Record<string, string | null>): Promise<SaveSettingsResult> {
    const res = await send("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ changes }) });
    const body = await json<SettingsView & { detail?: string; problems?: { name: string; message: string }[] }>(res, [400]);
    if (res.status === 400) return { ok: false, detail: detailOf(body, "Some settings were refused."), problems: body.problems ?? [] };
    return { ok: true, view: body };
  },
  /** One tiny call to each model that is set up: it uses a little quota, so only when asked. */
  checkModels: () => post<ModelCheckReport>("/api/provider/check", {}),

  // ---- a person's own model in the hosted version: a key goes in once and never comes back ----
  myModel: () => get<MyModelView>("/api/me/model"),
  mySpace: () => get<MySpace>("/api/me/space"),
  adminPeople: () => get<AdminPeople>("/api/admin/people"),
  blockPerson: (id: string) => post<{ blocked: boolean }>(`/api/admin/people/${encodeURIComponent(id)}/block`, {}),
  unblockPerson: (id: string) => post<{ blocked: boolean }>(`/api/admin/people/${encodeURIComponent(id)}/unblock`, {}),
  /** Erase a turned-off person's data. `confirm` is the address the owner typed: the server checks it too. Cannot be undone. */
  erasePerson: (id: string, confirm: string) => post<EraseReport>(`/api/admin/people/${encodeURIComponent(id)}/erase`, { confirm }),
  /** 200 is the new state; 400 says which fields were refused and why (never repeating the key). */
  async saveMyModel(choice: { provider: string; model: string; key: string }): Promise<SaveMyModelResult> {
    const res = await send("/api/me/model", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(choice) });
    const body = await json<MyModelView & { detail?: string; problems?: { name: string; message: string }[] }>(res, [400]);
    if (res.status === 400) return { ok: false, detail: detailOf(body, "That was refused."), problems: body.problems ?? [] };
    return { ok: true, view: body };
  },
  removeMyModel: async () => json<MyModelView>(await send("/api/me/model", { method: "DELETE" })),
  /** One tiny call to the person's OWN model. */
  testMyModel: () => post<ModelCheckReport>("/api/me/model/test", {}),

  // ---- the hosted version's sign-in (the local version never asks) ----
  authStatus: () => get<AuthStatus>("/api/auth/status"),
  login: (token: string) => post<{ authenticated: boolean }>("/api/auth/login", { token }),
  logout: () => post<{ authenticated: boolean }>("/api/auth/logout", {}),
  /** A fresh nonce for one Google sign-in attempt (the server also remembers it in a cookie the page cannot read). */
  authNonce: () => get<{ nonce: string }>("/api/auth/nonce"),
  /** The signed ticket Google's button returned. The server checks it; the answer is who signed in, or the server's own words for why not. */
  googleLogin: (credential: string) => post<{ authenticated: boolean; user: Person }>("/api/auth/google", { credential }),

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
  /** How the project works, from its README and docs. One model call: this waits for it (up to a minute or so) and nothing is saved. */
  guideRepo: (path: string, focus?: string) => post<Guide>("/api/repos/guide", { path, focus: focus || null }),
  /** Functions of a repository whose name contains the text. No model. */
  searchFunctions: (path: string, focus: string | undefined, query: string) =>
    post<FunctionSearch>("/api/repos/functions", { path, focus: focus || null, query }),
  /** One function with who calls it and what it calls (proven calls only), one step or two. No model. */
  callGraph: (path: string, focus: string | undefined, symbol: string, depth: 1 | 2) =>
    post<CallGraph>("/api/repos/calls", { path, focus: focus || null, symbol, depth }),
  /** A request planned before any work. One or two model calls unless `no_ai`; nothing is saved and nothing in the repository is changed or run. */
  planTask: (body: PlanRequest) => post<TaskPlan>("/api/plan", body),
  /** Make a plan and keep it, so its questions can be answered and it can be approved. Same body as `planTask`. */
  keepPlan: (body: PlanRequest) => post<PlanSessionView>("/api/plans", body),
  keptPlans: () => get<PlanSummary[]>("/api/plans"),
  keptPlan: (id: string) => get<PlanSessionView>(`/api/plans/${encodeURIComponent(id)}`),
  /** Replace the answers and decisions. 409 means the plan changed in another window (or is approved): the message says so. */
  savePlanAnswers: (id: string, body: PlanAnswersRequest) => post<PlanSessionView>(`/api/plans/${encodeURIComponent(id)}/answers`, body),
  /** 200 is the approved plan; 409 is a refusal, with what is missing when something is. Anything else is an error. */
  async approvePlan(id: string, rev: number): Promise<PlanApproveResult> {
    const res = await send(`/api/plans/${encodeURIComponent(id)}/approve`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ rev }) });
    const body = await json<PlanSessionView & { detail?: unknown; missing?: unknown }>(res, [409]);
    if (res.status === 409) return { ok: false, detail: detailOf(body, "This plan could not be approved."), missing: Array.isArray(body.missing) ? body.missing.map(String) : [] };
    return { ok: true, view: body };
  },
  reopenPlan: (id: string) => post<PlanSessionView>(`/api/plans/${encodeURIComponent(id)}/reopen`, {}),
  deletePlan: async (id: string) => json<{ deleted: boolean }>(await send(`/api/plans/${encodeURIComponent(id)}`, { method: "DELETE" })),
  startSuggest: (path: string, focus: string | undefined, withIdeas: boolean) =>
    post<SuggestRun>("/api/suggestions", { path, focus: focus || null, with_ideas: withIdeas }),
  suggestRun: (id: string) => get<SuggestRun>(`/api/suggestions/${encodeURIComponent(id)}`),
  suggestRuns: () => get<SuggestRunSummary[]>("/api/suggestions"),
  retrySuggest: (id: string) => post<SuggestRun>(`/api/suggestions/${encodeURIComponent(id)}/retry`, {}),

  // ---- the Testing Lab: a skill's own test cases, run against a model with the skill and without it ----
  /** What a run would do (the cases, the checks, the calls) or why it cannot be run. No model is asked. */
  evalPreview: (name: string, version?: number) =>
    get<EvalPreview>(`/api/evals/preview?name=${encodeURIComponent(name)}${version ? `&version=${version}` : ""}`),
  startEval: (body: { name: string; version?: number; runs: number; baseline: boolean }) => post<EvalRun>("/api/evals", body),
  evalRun: (id: string) => get<EvalRun>(`/api/evals/${encodeURIComponent(id)}`),
  evalRuns: (name?: string, version?: number) => {
    const q = new URLSearchParams();
    if (name) q.set("name", name);
    if (version) q.set("version", String(version));
    return get<EvalRunSummary[]>(`/api/evals${q.size ? `?${q}` : ""}`);
  },
  retryEval: (id: string) => post<EvalRun>(`/api/evals/${encodeURIComponent(id)}/retry`, {}),

  // ---- the behaviour scan: a skill's or agent's instructions run on fake tools with planted fake secrets; code judges ----
  /** The tasks a scan would run and the most model calls, before any model is asked. */
  scanPreview: (o: { name: string; version?: number; kind?: string; runs?: number; scenarios?: number; control?: boolean; draft?: boolean }) => {
    const q = new URLSearchParams({ name: o.name });
    if (o.version) q.set("version", String(o.version));
    if (o.kind && o.kind !== "skill") q.set("kind", o.kind);
    if (o.runs !== undefined) q.set("runs", String(o.runs));
    if (o.scenarios !== undefined) q.set("scenarios", String(o.scenarios));
    if (o.control !== undefined) q.set("control", String(o.control));
    if (o.draft !== undefined) q.set("draft", String(o.draft));
    return get<ScanPreview>(`/api/scans/preview?${q}`);
  },
  startScan: (body: ScanStart) => post<ScanRun>("/api/scans", body),
  scanRun: (id: string) => get<ScanRun>(`/api/scans/${encodeURIComponent(id)}`),
  scanRuns: (o: { name?: string; version?: number; kind?: string } = {}) => {
    const q = new URLSearchParams();
    if (o.name) q.set("name", o.name);
    if (o.version) q.set("version", String(o.version));
    if (o.kind) q.set("kind", o.kind); // always when known: a skill's page must never get an agent's scans of the same name
    return get<ScanRunSummary[]>(`/api/scans${q.size ? `?${q}` : ""}`);
  },
  retryScan: (id: string) => post<ScanRun>(`/api/scans/${encodeURIComponent(id)}/retry`, {}),
  /** Today's checks on one version, the requirement against its tests, the cost, the Lab's result, what did not run, and what to do next. A GET: no model, nothing run. */
  qualityReport: (name: string, version?: number) =>
    get<QualityReport>(`/api/library/${encodeURIComponent(name)}/quality${version ? `?version=${version}` : ""}`),
  /** Every test case of a skill version, the ones that cannot be run too (so they can be fixed). */
  skillCases: (name: string, version?: number) =>
    get<CasesView>(`/api/library/${encodeURIComponent(name)}/tests${version ? `?version=${version}` : ""}`),
  /** Keep cases as a NEW version of the skill (the latest only). 200 and 422 both carry a report (kept, or refused by a check); a case that could
   *  not be run is a 400 that names it, and an edit of a version that is no longer the latest is a 409. */
  async saveCases(name: string, body: { base_version: number; note: string; cases: unknown[] }): Promise<ImportResult> {
    const res = await send(`/api/library/${encodeURIComponent(name)}/tests`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    // FastAPI also answers 422 for a request it could not read ({detail: [...]}): that is not an import report, and treated as one it would be shown as
    // "Nothing changed". Only a body that is a report (it has `refused`) is returned as one.
    const result = await json<ImportResult | { detail: unknown }>(res, [422]);
    if (!("refused" in result)) throw new ApiError(res.status, detailOf(result, "The request could not be read."));
    return result;
  },

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

  /** Delete a library entry of any kind with every version and its backups. `confirm` is the name the person typed (the server checks it too). Cannot be undone. */
  async deleteEntry(name: string, confirm: string, kind?: string): Promise<DeleteReport> {
    return json<DeleteReport>(await send(withKind(`/api/library/${encodeURIComponent(name)}?confirm=${encodeURIComponent(confirm)}`, kind), { method: "DELETE" }));
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
