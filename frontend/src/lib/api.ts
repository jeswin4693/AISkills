import type {
  BuildSession, BuildSummary, DiffResult, FileText, Health, ImportResult, InstallRequest, InstallResult, ProviderStatus,
  RescanResult, SandboxStatus, SaveResult, SkillSummary, VersionInfo,
} from "./types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");

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
    throw new ApiError(0, `Cannot reach the SkillForge API at ${API_URL}. Start it with: python -m skillforge serve`);
  }
}

async function json<T>(res: Response, accept: number[] = []): Promise<T> {
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    /* not JSON: the fallback message below is used */
  }
  if (!res.ok && !accept.includes(res.status)) throw new ApiError(res.status, detailOf(body, `The API answered ${res.status}.`));
  return body as T;
}

const get = async <T,>(path: string): Promise<T> => json<T>(await send(path));
const post = async <T,>(path: string, body: unknown): Promise<T> =>
  json<T>(await send(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }));

export const api = {
  health: () => get<Health>("/api/health"),
  sandbox: () => get<SandboxStatus>("/api/sandbox"),
  provider: () => get<ProviderStatus>("/api/provider"),

  listSkills: () => get<SkillSummary[]>("/api/library"),
  versions: (name: string) => get<{ name: string; versions: VersionInfo[] }>(`/api/library/${encodeURIComponent(name)}`),
  diff: (name: string, from?: number, to?: number) => {
    const q = new URLSearchParams();
    if (from !== undefined) q.set("frm", String(from));
    if (to !== undefined) q.set("to", String(to));
    const qs = q.toString();
    return get<DiffResult>(`/api/library/${encodeURIComponent(name)}/diff${qs ? `?${qs}` : ""}`);
  },
  file: (name: string, version: number, path: string) =>
    get<FileText>(`/api/library/${encodeURIComponent(name)}/versions/${version}/files/${encodePath(path)}`),

  /** Today's static checks on stored versions (every skill, or one). Reads only: nothing is changed or run. */
  rescan: (name?: string) => get<RescanResult>(`/api/rescan${name ? `?name=${encodeURIComponent(name)}` : ""}`),

  /** 200 and 422 both carry a report (kept, or refused with the checks that failed); anything else is an error. */
  async importZip(file: File, opts: { note?: string; testScripts?: boolean } = {}): Promise<ImportResult> {
    const q = new URLSearchParams({ filename: file.name });
    if (opts.note?.trim()) q.set("note", opts.note.trim());
    if (opts.testScripts) q.set("test_scripts", "true");
    const res = await send(`/api/library/import?${q}`, { method: "POST", headers: { "Content-Type": "application/zip" }, body: file });
    return json<ImportResult>(res, [422]);
  },

  rollback: (name: string, to: number) =>
    post<{ created: boolean; version: VersionInfo }>(`/api/library/${encodeURIComponent(name)}/rollback`, { to }),

  install: (name: string, req: InstallRequest) => post<InstallResult>(`/api/library/${encodeURIComponent(name)}/install`, req),

  // ---- the builder: a session you poll; each action returns the session as it is right after the action ----
  builds: () => get<BuildSummary[]>("/api/builds"),
  build: (id: string) => get<BuildSession>(`/api/builds/${encodeURIComponent(id)}`),
  startBuild: (description: string, withScripts: boolean) => post<BuildSession>("/api/builds", { description, with_scripts: withScripts }),
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
  async exportZip(name: string, version: number, withoutSpec: boolean): Promise<{ blob: Blob; filename: string }> {
    const q = new URLSearchParams({ version: String(version), without_spec: String(withoutSpec) });
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
