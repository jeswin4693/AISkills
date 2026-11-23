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

// ---- settings (docs/settings.md) -----------------------------------------------------------------------

export interface SettingItem {
  name: string;
  group: string;
  label: string;
  help: string;
  kind: "secret" | "choice" | "text" | "url" | "number" | "flag";
  /** For a key (and the custom address): the provider it belongs to. */
  provider: string;
  choices: string[];
  set: boolean;
  /** Where the value comes from. "environment" cannot be changed here: a real environment variable wins over .env. */
  source: "file" | "environment" | "unset";
  editable: boolean;
  /** Absent for a key: the server never sends one, not even its end or its length. */
  value?: string;
}

export interface SettingGroup {
  key: string;
  label: string;
  help: string;
  advanced: boolean;
}

export interface SettingsView {
  file: string;
  file_exists: boolean;
  /** False when the file exists but cannot be read as text (for example it is not UTF-8): nothing in it is being used. */
  file_readable: boolean;
  groups: SettingGroup[];
  settings: SettingItem[];
  status: ProviderStatus;
}

export interface SettingProblem {
  /** Empty when the problem is about the request as a whole. Never holds the value that was refused. */
  name: string;
  message: string;
}

export type SaveSettingsResult = { ok: true; view: SettingsView } | { ok: false; detail: string; problems: SettingProblem[] };

export interface ModelCheck {
  provider: string;
  model: string;
  roles: string[];
  ok: boolean;
  kind: string;
  detail: string;
  latency_ms: number;
  input_tokens: number | null;
  output_tokens: number | null;
}

export interface ModelCheckReport {
  configured: boolean;
  detail: string;
  checks: ModelCheck[];
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
  /** The places of a repository this build cites, recorded in evidence.json. Absent when the build did not start from a repository. */
  evidence?: { repo: string; places: number; skipped: string[] };
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
  /** Set when the build started from a repository (the Repository page). Absent from older servers. */
  seed?: BuildSeed | null;
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

// ---- a repository, ideas for it, and evidence (docs/evidence.md) ---------------------------------------------

export interface CoreSymbol {
  id: string;
  kind: string;
  name: string;
  file: string;
  line: number;
  fan_in: number;
  fan_out: number;
  size: number;
}

export interface RiskyFile {
  path: string;
  importers: number;
  commits: number;
  score: number;
}

/** What the graph says about a folder. Computed from parsed code; no model took part. */
/** Where a repository was read from. A GitHub link is downloaded (public repositories only, source files only, nothing run) into a copy on this computer. */
export type RepoSource =
  | { kind: "folder" }
  | {
      kind: "github";
      owner: string;
      repo: string;
      ref: string | null;
      url: string;
      fetched_at: string;
      files: number;
      bytes: number;
      /** Why files were left out, by reason and count. */
      skipped: Record<string, number>;
      /** True when a copy downloaded a little earlier was used instead of downloading again. */
      reused: boolean;
    };

export interface RepoAnalysis {
  name: string;
  source: RepoSource;
  focus: string | null;
  stats: {
    files: number;
    test_files: number;
    lines: number;
    languages: Record<string, number>;
    language_levels: Record<string, string>;
    symbols: Record<string, number>;
    edges: Record<string, number>;
    call_sites: Record<string, number>;
    unresolved_imports: number;
    parse_problems: number;
    commits_read: number | null;
    co_change_pairs: number;
  };
  notes: string[];
  hotspots: { core_symbols: CoreSymbol[]; risky_files: RiskyFile[]; note: string };
  dead_code: { internal: number; exported: number; note: string };
}

export type IdeaCategory = "refactor" | "test" | "cleanup" | "risk" | "skill" | "automation";

/** One suggestion that survived grounding: everything it cites exists in the graph. */
export interface Idea {
  title: string;
  category: IdeaCategory;
  rationale: string;
  evidence: string[];
  next_step: string;
  confidence: "high" | "medium" | "low";
  skill_requirement: string;
  evidence_nodes: string[];
  ignored_evidence: string[];
  unverified_numbers: string[];
}

export interface SuggestResult {
  repo: string;
  provider: string;
  model: string;
  attempts: number;
  facts: { id: string; kind: string; summary: string; nodes: string[] }[];
  suggestions: Idea[];
  dropped: { title: string; reason: string }[];
  notes: string[];
}

export type RunStatus = "working" | "done" | "failed";

export interface SuggestRun {
  id: string;
  status: RunStatus;
  repo: string;
  focus: string | null;
  with_ideas: boolean;
  result: SuggestResult | null;
  error: string;
  retryable: boolean;
  created_at: string;
  updated_at: string;
}

export interface SuggestRunSummary extends Omit<SuggestRun, "result"> {
  ideas: number;
}

/** The repository a build started from. The folder's name only: the path stays on the server. */
export interface BuildSeed {
  repo: string;
  focus: string | null;
  places: number;
}

export interface EvidenceRef {
  id: string;
  kind: "file" | "symbol";
  file: string;
  lang: string;
  taken_at: string | null;
  commit: string | null;
  dirty: boolean;
  symbol_kind: string;
  callers_total: number;
  callees_total: number;
  members_total: number;
  symbols_total: number;
  importers_total: number;
  measured: boolean;
}

/** The code a stored version cites, with the facts recorded for each place. `evidence` is null for a version that cites none. */
export interface EvidenceDoc {
  name: string;
  version: string;
  evidence: { repo: string; commit: string | null; dirty: boolean; focus: string | null; taken_at: string; refs: EvidenceRef[] } | null;
}

export type Verdict = "missing" | "moved" | "changed" | "edited" | "holds";

export interface RecheckFinding {
  ref: string;
  kind: "file" | "symbol";
  status: Verdict;
  details: string[];
  candidates: string[];
  not_measured: string[];
  recorded: string;
}

export interface RecheckReport {
  skill: string;
  version: string;
  repo: string;
  taken_at: string;
  recorded_commit: string | null;
  current_commit: string | null;
  recorded_dirty: boolean;
  current_dirty: boolean;
  ok: boolean;
  counts: Partial<Record<Verdict, number>>;
  findings: RecheckFinding[];
  notes: string[];
  limits: string;
}
