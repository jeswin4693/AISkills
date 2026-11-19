// The shapes the local API returns (docs/api.md). Kept by hand next to the Python code that produces them.

export type CheckStatus = "passed" | "warning" | "failed" | "not run";

export interface Check {
  name: string;
  status: CheckStatus;
  detail: string;
}

export interface VersionInfo {
  name: string;
  version: number;
  tag: string; // "v3"
  created_at: string; // ISO 8601, UTC
  content_hash: string;
  files: Record<string, string>; // path -> sha256
  source_kind: string; // folder | zip | rollback
  source_label: string;
  note: string;
  skill_version: string;
  checks: Check[];
}

export interface SkillSummary {
  name: string;
  versions: number;
  latest: VersionInfo | null;
  error?: string;
}

export interface FileChange {
  path: string;
  status: "added" | "removed" | "changed";
  text: string; // a unified diff, possibly cut
  binary: boolean;
}

export interface ImportResult {
  refused: boolean;
  created: boolean;
  name: string | null;
  version: VersionInfo | null;
  previous: string | null;
  checks: Check[];
  changes: FileChange[];
}

export interface DiffResult {
  name: string;
  from: string;
  to: string;
  changes: FileChange[];
}

export interface FileText {
  path: string;
  binary: boolean;
  text: string;
}

export interface InstallResult {
  path: string;
  version: VersionInfo;
  backup: string | null;
  has_scripts: boolean;
}

export interface InstallRequest {
  version?: number;
  target: "personal" | "folder";
  folder?: string;
  force?: boolean;
}

export interface Health {
  status: string;
  version: string;
}

export interface SandboxStatus {
  available: boolean;
  reason: string;
}

export interface ProviderStatus {
  configured: boolean;
  provider: string;
  model: string;
  detail: string;
}
