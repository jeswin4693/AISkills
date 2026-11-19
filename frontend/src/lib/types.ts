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

// ---- the builder (docs/api.md, "The skill builder") ----------------------------------------------------

export type BuildStatus = "working" | "awaiting_answers" | "awaiting_approval" | "done" | "failed";

export interface Question {
  slot: string;
  text: string;
}

/** What the person asked for, as the checklist read it. `quotes` holds the person's own words behind each item. */
export interface RequirementSpec {
  kind: string;
  goal: string;
  inputs: string[];
  outputs: string[];
  constraints: string[];
  acceptance_criteria: string[];
  failure_behavior: string;
  quotes: Record<string, string>;
  user_words: string;
  rounds: number;
}

export interface JobInfo {
  kind: "understand" | "build";
  status: "queued" | "running" | "succeeded" | "failed";
  started_at: string | null;
  finished_at: string | null;
  events: { at: string; message: string }[];
}

export interface BuildResultInfo {
  status: "ok" | "draft";
  draft_reason: string;
  name: string;
  description: string;
  folder: string;
  files: string[];
  scripts: number;
  report_md: string;
  counts: { passed: number; warning: number; failed: number; not_run: number };
  checks: Check[];
}

export interface BuildSession {
  id: string;
  status: BuildStatus;
  description: string;
  round: number;
  max_rounds: number;
  with_scripts: boolean;
  questions: Question[];
  spec: RequirementSpec | null;
  result: BuildResultInfo | null;
  error: string;
  retryable: boolean;
  model_calls: number;
  notes: string[];
  saved: { name: string; version: string } | null;
  created_at: string;
  updated_at: string;
  job: JobInfo | null;
}

export interface BuildSummary {
  id: string;
  status: BuildStatus;
  description: string;
  created_at: string;
  updated_at: string;
  skill: string;
  draft: boolean;
  saved: { name: string; version: string } | null;
}

export interface SaveResult extends ImportResult {
  session: BuildSession;
}

/** One entry of tests/cases.json in a built skill. Cases are data: nothing has run them against an agent. */
export interface TestCase {
  name: string;
  kind: string;
  input_description: string;
  expected_result: string;
  covers: string[];
}
