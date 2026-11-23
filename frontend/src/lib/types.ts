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

/** What got riskier between two versions (docs/library.md, "Risk diff"). Worked out by code; no model reads the skill. */
export type RiskDirection = "riskier" | "look" | "safer";
export type RiskLevel = "more_risk" | "look" | "less_risk" | "no_new_risk";

export interface RiskChange {
  direction: RiskDirection;
  kind: string;
  detail: string; // a plain sentence
  path: string;
}

export interface RiskInfo {
  older: string;
  newer: string;
  level: RiskLevel;
  counts: Record<RiskDirection, number>;
  changes: RiskChange[]; // riskiest first
  note: string; // what this can and cannot see
}

export interface ImportResult {
  refused: boolean;
  created: boolean;
  name: string | null;
  version: VersionInfo | null;
  previous: string | null;
  checks: Check[];
  changes: FileChange[];
  risk: RiskInfo | null; // null for a first version, a refused skill, or content that is already stored
}

export interface DiffResult {
  name: string;
  from: string;
  to: string;
  changes: FileChange[];
  risk: RiskInfo;
}

/** Today's checks on a stored version (docs/library.md, "Rescan"). */
export type ScanStatus = "same" | "worse" | "failing" | "damaged";

export interface ScanFinding {
  status: "warning" | "failed";
  name: string;
  detail: string;
  was: string; // passed, warning, failed, or "found now" for a check that did not exist at import
}

export interface VersionScan {
  name: string;
  tag: string; // "" when the skill's manifests could not be read at all
  status: ScanStatus;
  findings: ScanFinding[];
  message: string; // why, for damaged
}

export interface RescanResult {
  ok: boolean;
  counts: Record<ScanStatus, number>;
  versions: VersionScan[]; // newest version of each skill first
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
  /** "hosted" for the deployed version, which asks for a sign-in. Absent from older servers. */
  mode?: "local" | "hosted";
}

/** Whether this server asks for a sign-in, and whether this browser is signed in. The local version never asks. */
export interface AuthStatus {
  required: boolean;
  authenticated: boolean;
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
  /** The model behind each kind of work, and the other models asked when the first cannot answer. Absent from older servers. */
  tiers?: { tier: string; provider: string; model: string }[];
  fallbacks?: { provider: string; model: string }[];
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
  /** An estimate (about 4 characters per token). Absent on sessions saved before it existed. */
  tokens?: { always: number; when_used: number; on_demand: number } | null;
}

/** What the model was asked for a session (docs/ai-engine.md). Counts and timings only; tokens are null when the provider gave none. */
export interface SessionUsage {
  calls: number; // attempts at the model, failed ones included
  errors: number;
  input_tokens: number | null;
  output_tokens: number | null;
  models: string[];
}

/** One answer a kind's requirement must have, as the server lists it. */
export interface SlotInfo {
  key: string;
  label: string;
  question: string;
}

/** A kind of thing the app builds (today a skill), as GET /api/kinds lists it. */
export interface KindInfo {
  key: string;
  label: string;
  /** The file that defines the thing: SKILL.md for a skill, AGENT.md for an agent. */
  definition_file: string;
  /** How the personal install folder is shown, such as ~/.claude/agents. */
  personal_label: string;
  /** True when installing writes one file (an agent), not a folder. */
  installs_as_file: boolean;
  /** False for a kind that is composed from the library (a plugin), not described in the Builder. */
  conversational: boolean;
  install_targets: string[];
  slots: SlotInfo[];
}

/** One skill, agent, MCP server or hook in a plugin. A hook is named by its id in the catalogue and has no version. */
export interface PluginComponentRef {
  kind: "skill" | "agent" | "mcp" | "hook";
  name: string;
  version?: number;
  /** A hook's typed options (only a hook has any). */
  options?: Record<string, string[]>;
}

/** One thing a person may choose for a catalogue hook. */
export interface HookOption {
  key: string;
  label: string;
  help: string;
  max_items: number;
  max_length: number;
  /** A regular expression every value must match completely. The server decides; the page only hints early. */
  pattern: string;
}

/** A hook of the catalogue: the only hooks a plugin may carry. */
export interface HookInfo {
  id: string;
  title: string;
  summary: string;
  event: string;
  matcher: string;
  /** "blocks": it can stop what Claude is about to do; "observes": it only looks. */
  effect: string;
  sees: string;
  timeout: number;
  powers: string[];
  revision: number;
  options: HookOption[];
}

/** A catalogue hook a plugin carries, with the options chosen. */
export interface PluginHook {
  id: string;
  title: string;
  summary: string;
  event: string;
  matcher: string;
  effect: string;
  sees: string;
  options: Record<string, string[]>;
  powers: string[];
  command: string;
  revision: number;
}

export interface PluginRequest {
  name: string;
  description: string;
  author: string;
  components: PluginComponentRef[];
}

/** An MCP server a plugin starts, read from its code by syntax (never run). */
export interface PluginServer {
  name: string;
  tools: string[];
  /** network, write_files, read_files, run_commands */
  capabilities: string[];
  /** The environment variables it reads by a name written in the code: each becomes an option Claude Code asks for. */
  environment: string[];
  environment_dynamic: boolean;
  dynamic: string[];
  command: string;
  /** Whether the server ships a requirements.txt (the page only says "pip install -r" for one that does). */
  requirements: boolean;
}

/** What a plugin can do on the machine, worked out by code from its files. */
export interface PluginCapabilities {
  tools: string[];
  by_component: { kind: string; name: string; tools: string[]; scripts: string[]; script_capabilities: string[] }[];
  scripts: string[];
  script_capabilities: string[];
  hooks: string[];
  mcp_servers: string[];
  notes: string[];
  servers: PluginServer[];
  hook_entries: PluginHook[];
}

export interface PluginPreview {
  name: string;
  version: string;
  components: { kind: string; name: string; version: string }[];
  manifest: string;
  files: { path: string; bytes: number }[];
  capabilities: PluginCapabilities;
  checks: Check[];
  failed: boolean;
}

export interface PluginSaveResult extends ImportResult {
  capabilities?: PluginCapabilities;
  components?: { kind: string; name: string; version: string }[];
}

export interface BuildSession {
  id: string;
  kind: string;
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
  /** Absent from servers that do not record it. */
  usage?: SessionUsage;
  notes: string[];
  saved: { name: string; version: string } | null;
  created_at: string;
  updated_at: string;
  job: JobInfo | null;
}

export interface BuildSummary {
  id: string;
  kind: string;
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
