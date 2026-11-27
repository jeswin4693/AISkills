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

/** Someone who signed in with Google: what the server knows about them (never anything secret). */
export interface Person {
  email: string;
  name: string;
  picture: string;
}

/** Whether this server asks for a sign-in, and whether this browser is signed in. The local version never asks. */
export interface AuthStatus {
  required: boolean;
  authenticated: boolean;
  /** The PUBLIC Google client id when this server offers "Sign in with Google"; "" or absent when it does not (and from older servers). */
  google_client_id?: string;
  /** Who is signed in, when it is a person who used Google. Null for the owner (the access token) and for nobody. */
  user?: Person | null;
  /** True when the access token can still sign the owner in (always on a hosted server). */
  owner_login?: boolean;
  /** True when this person's account has been turned off by the owner: they are not signed in, and are told why. Absent otherwise. */
  blocked?: boolean;
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
  /** Whose model it is, in the hosted version: the person's own, the server's (shared), or none for them. Absent from older servers and for the owner's local use. */
  source?: "own" | "server" | "none";
  /** The daily allowance on the server's shared model, when the host shares it with people who have no key of their own. */
  allowance?: Allowance | null;
}

/** Model calls a person may make a day on the server's shared model, and how many they have made today (UTC). */
export interface Allowance {
  limit: number;
  used: number;
}

/** What applies to one person about models (GET /api/me/model). Never a key, not even its end. */
export interface MyModelView {
  /** "owner": the server's own settings are used. "own": their saved key. "shared": the server's model, with an allowance. "none": nothing yet. */
  mode: "owner" | "own" | "shared" | "none";
  provider: string;
  model: string;
  key_saved: boolean;
  /** When the key was saved (ISO text), or "". */
  key_saved_at: string;
  /** False when a saved key can no longer be opened (the server's access token changed): the person enters it again. */
  key_readable: boolean;
  allowance: Allowance | null;
  /** The providers a person may choose from (never "custom"). */
  providers: string[];
  message: string;
}

/** What one person uses and may use (GET /api/me/space). A limit of 0 means none. */
export interface PersonSpace {
  mode: "person";
  disk: { used: number; limit: number };
  builds: { kept: number; limit: number };
  active: { now: number; limit: number };
}
export interface OwnerSpace {
  mode: "owner";
  message: string;
}
export type MySpace = PersonSpace | OwnerSpace;

/** One person on the owner's People page (GET /api/admin/people). Never a key, not even which model. */
export interface AdminPerson {
  id: string;
  name: string;
  email: string;
  joined: string;
  last_seen: string;
  blocked: boolean;
  builds: number;
  disk_used: number;
  active: number;
  calls_today: { server: number; own: number };
  has_key: boolean;
}
export interface AdminPeople {
  hosted: boolean;
  people: AdminPerson[];
  /** How many people there are in all (the list shows the first few when there are very many). */
  total?: number;
}

/** What deleting a library entry did (DELETE /api/library/{name}): the versions and backups removed, and whether something could not be removed from the disk. */
export interface DeleteReport {
  deleted: boolean;
  name: string;
  kind: string;
  versions: number;
  backups: number;
  leftover: boolean;
}

/** What erasing a person's data did (POST /api/admin/people/{id}/erase). */
export interface EraseReport {
  erased: boolean;
  builds: number;
  suggestion_runs: number;
  lab_runs: number;
  scan_runs: number;
  key_removed: boolean;
  files_left: boolean;
}

export type SaveMyModelResult ={ ok: true; view: MyModelView } | { ok: false; detail: string; problems: { name: string; message: string }[] };

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
      /** README and doc files kept next to the source (the guide reads them). null for a copy made before they were kept. */
      docs?: number | null;
    };

// ---- the architecture map (docs/architecture-map.md): folders as boxes, proven imports as arrows -----------------

export interface ArchFunction {
  name: string;
  file: string;
  line: number;
  size: number;
}

export interface ArchFile {
  path: string;
  lines: number;
}

/** One box: a top-level folder, the files at the top ("root"), or the smallest folders folded together ("other"). `id` is a position (m0, m1, ...), never a name. */
export interface ArchModule {
  id: string;
  label: string;
  kind: "folder" | "root" | "other";
  files: number;
  lines: number;
  test_files: number;
  tests_only: boolean;
  symbols: number;
  languages: Record<string, number>;
  /** False when none of its files is in a language whose imports are read: no arrow can start or end there, which is not the same as depending on nothing. */
  measured: boolean;
  column: number;
  top_functions: ArchFunction[];
  file_list: ArchFile[];
  /** The folders folded into an "other" box; empty otherwise. */
  members: string[];
}

/** `from` imports `to`; `count` is the number of distinct file pairs. */
export interface ArchArrow {
  from: string;
  to: string;
  count: number;
  /** Points against the main left-to-right direction: the weaker way of a pair that imports each other, the arrow that closes a loop. */
  back: boolean;
}

export interface Architecture {
  /** The folder every file sits inside (a `src/` or the focus folder), left out of the box names; "" when none. */
  base: string;
  modules: ArchModule[];
  arrows: ArchArrow[];
  /** Groups of box ids that import each other, directly or through others. */
  cycles: string[][];
  columns: number;
  measured: boolean;
  language_levels: Record<string, string>;
  /** Languages in this repository whose imports the graph does not turn into links between files (basic level, and C#). Their boxes have no arrows. */
  imports_not_read: string[];
  /** Links that were found but not drawn: name-only guesses, and imports written by tests or test scaffolding (an e2e suite, fixtures, mocks). */
  left_out: { guess: number; from_tests: number };
  notes: string[];
}

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
  /** Optional so an answer from an older server cannot break the page. */
  architecture?: Architecture;
}

// ---- the guide: how a project works, read from its README and docs (every quote checked by code) ----

/**
 * What is known about one step of a route: the code imports from the first part into the second (confirmed), only the other way (reversed), or each way
 * (both_ways); the two are one folder; the language has no import links (not_measured); a step between them was dropped (step_dropped); or only the docs say so.
 */
export type HopStatus = "confirmed" | "both_ways" | "reversed" | "same_folder" | "not_measured" | "step_dropped" | "docs_only";
/** Whether the folder a part names is in the code, only the docs mention the part, or the part is outside the repository by nature. */
export type PartStatus = "in_code" | "docs_only" | "external";

/** A sentence found word for word in one paragraph of a document, and where. `on_topic` is false when it does not even mention the part it is given for. */
export interface GuideQuote {
  text: string;
  source: string;
  line: number;
  on_topic: boolean;
}

export interface GuidePart {
  id: string;
  name: string;
  /** One of the guide's layer ids. */
  layer: string;
  /** The next five are the model's own words and are not checked; the quote and the folder are. */
  summary: string;
  takes_in: string;
  gives_out: string;
  plain: string;
  folder: string;
  status: PartStatus;
  files: number;
  lines: number;
  read_first: { files: { path: string; lines: number }[]; functions: { name: string; file: string; line: number }[] };
  quote: GuideQuote;
}

export interface GuideStep {
  part: string;
  does: string;
  quote: GuideQuote;
}

export interface GuideHop {
  from: string;
  to: string;
  status: HopStatus;
  /** Distinct file pairs in which the first part imports the second, and the other way round. */
  forward: number;
  reverse: number;
  /** A few of the pairs of the stronger direction (importer imports imported): so a reader can judge whether they are the real link. */
  evidence: { importer: string; imported: string }[];
}

export interface GuideJourney {
  title: string;
  steps: GuideStep[];
  /** One between each pair of steps, so one fewer than the steps. */
  hops: GuideHop[];
}

export interface Guide {
  /** ok: drawn. thin: too little could be checked, nothing is drawn. no_docs: there was no README or docs, and no model was asked. */
  status: "ok" | "thin" | "no_docs";
  name: string;
  focus: string | null;
  source: RepoSource;
  provider: string;
  model: string;
  attempts: number;
  /** The documents that were read, relative to the repository. */
  docs: { path: string; lines: number; chars: number; truncated: boolean }[];
  docs_skipped: Record<string, number>;
  layers: { id: string; label: string }[];
  parts: GuidePart[];
  journeys: GuideJourney[];
  dropped: { what: string; name: string; reason: string }[];
  notes: string[];
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

// ---- the Testing Lab (docs/testing-lab.md) -------------------------------------------------------------

/** What a run found, as a code the server decides (the page never parses the sentence). */
export type EvalOutcome = "helped" | "adds_nothing" | "no_difference" | "worse" | "too_few" | "with_only" | "not_run";
/** Why a skill cannot be run at all ("" when it can). */
export type EvalBlocker = "" | "no_cases" | "needs_tools" | "nothing_runnable";

export interface EvalCheckSpec {
  kind: string; // contains, not_contains, starts_with, regex, max_chars, max_lines, first_line_max_chars
  value: string;
  why: string;
}

export interface EvalPreviewCase {
  name: string;
  kind: string; // positive, negative, edge
  message: string;
  message_cut: boolean;
  checks: EvalCheckSpec[];
}

/** What a run of one version would do, before any model is asked. */
export interface EvalPreview {
  name: string;
  kind: string;
  version: number;
  tag: string;
  content_hash: string;
  skill_tokens: number;
  runnable: boolean;
  blocker: EvalBlocker;
  reason: string;
  cases: EvalPreviewCase[];
  skipped: string[];
  calls: { per_run: number; per_run_with_baseline: number };
  limits: { max_cases: number; min_cases: number; max_runs: number };
}

export interface EvalCheckResult extends EvalCheckSpec {
  passed: boolean;
  detail: string; // what was wrong, in numbers ("the first line is 54 characters, the limit is 50"); empty when it passed
}

export interface EvalTry {
  reply: string;
  cut: boolean; // the reply was longer than the server keeps
  passed: boolean;
  checks: EvalCheckResult[];
}

export interface EvalAttempt {
  passed: number;
  runs: number;
  tries: EvalTry[];
}

export interface EvalCase {
  name: string;
  kind: string;
  message: string;
  message_cut: boolean;
  with_skill: EvalAttempt;
  baseline: EvalAttempt | null;
}

export interface EvalTally {
  passed: number;
  total: number;
}

export interface EvalResult {
  outcome: EvalOutcome;
  verdict: string;
  limits: string;
  runnable: boolean;
  reason: string;
  runs: number;
  calls: number;
  skill_tokens: number;
  min_cases: number; // how many cases it takes before a run says whether the skill helps
  with_skill: EvalTally;
  baseline: EvalTally | null;
  skipped: string[];
  cases: EvalCase[];
}

export interface EvalRun {
  id: string;
  status: RunStatus;
  kind: string;
  name: string;
  version: number;
  tag: string;
  content_hash: string;
  runs: number;
  baseline: boolean;
  progress: { done: number; total: number };
  result: EvalResult | null;
  error: string;
  retryable: boolean;
  created_at: string;
  updated_at: string;
}

export interface EvalRunSummary extends Omit<EvalRun, "result"> {
  summary: { outcome: EvalOutcome; with_skill: EvalTally; baseline: EvalTally | null; calls: number } | null;
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

// ---- the Testing Lab's own test cases (docs/testing-lab.md, "Your own test cases") -----------------------

export interface CaseCheck {
  kind: string;
  value: string;
  why: string;
}

/** One test case of a skill version, as the editor reads it. A case saved before test cases could be run has an empty message and no checks. */
export interface CaseDoc {
  name: string;
  kind: string; // positive, negative, edge
  message: string;
  covers: string[];
  runnable: boolean;
  checks: CaseCheck[];
}

export interface CasesView {
  name: string;
  version: number;
  tag: string;
  content_hash: string;
  latest: boolean; // only the latest version can be edited
  needs_tools: string; // why the Lab cannot run these cases ("" when it can); they are still the person's to edit
  unreadable: number; // entries of tests/cases.json that could not be read: a save drops them
  limits: {
    max_cases: number; max_checks: number; max_name: number; max_message: number; max_value: number; max_why: number; max_covers: number; max_cover: number;
  };
  cases: CaseDoc[];
}

// ---- the Quality Report (docs/quality-report.md) -------------------------------------------------------

/** What a library check did since the skill was imported. "run_now": a design check, run today, that was never kept with the version. */
export type QualityChange = "same" | "worse" | "better" | "new" | "run_now";

export interface QualityRow {
  name: string;
  status: CheckStatus;
  detail: string;
  was: CheckStatus | null;
  change: QualityChange;
}

export interface QualityGroup {
  key: "library" | "design" | "written";
  title: string;
  rows: QualityRow[];
}

export interface QualityCriterion {
  id: string;
  text: string;
  tests: string[];
  runnable: number;
}

export interface QualityRun {
  id: string;
  tag: string;
  outcome: EvalOutcome;
  with_skill: EvalTally;
  baseline: EvalTally | null;
  calls: number;
  runs: number;
  created_at: string;
}

export interface QualityLab {
  state: "this_version" | "older_version" | "never_run" | "running" | "failed";
  run: QualityRun | null; // a run of THIS version
  other: QualityRun | null; // the newest run of another version, only when this one has none
  error?: string;
}

export type QualityLink = { page: "lab"; version: number } | { page: "skill" } | { page: "compare"; from: number; to: number } | null;

export interface QualitySuggestion {
  kind: "fix" | "write" | "run" | "read" | "shorten";
  text: string;
  link: QualityLink;
}

export interface QualityReport {
  name: string;
  version: number;
  tag: string;
  latest: boolean;
  versions: number;
  created_at: string;
  source_kind: string;
  source_label: string;
  note: string;
  content_hash: string;
  headline: { failed: number; warnings: number; not_run: number; passed: number };
  attention: { tone: "bad" | "warn" | "info"; text: string };
  groups: QualityGroup[];
  requirements: {
    source: "definition" | "spec" | "none";
    criteria: QualityCriterion[];
    uncovered: string[];
    unknown_cites: { test: string; ids: string[] }[];
  };
  tests: { total: number; runnable: number; blocker: EvalBlocker; reason: string; skipped: string[] };
  tokens: { always: number; when_used: number; on_demand: number; heavy: string[] };
  lab: QualityLab;
  changes: {
    from: string; to: string; from_version: number; to_version: number; level: "more_risk" | "look" | "less_risk" | "no_new_risk"; note: string;
    counts: { riskier: number; look: number; safer: number }; items: { direction: string; kind: string; detail: string; path: string }[]; more: number;
  } | null;
  evidence: { repo: string; places: number; taken_at: string; commit: string | null; dirty: boolean } | null;
  suggestions: QualitySuggestion[];
  suggestions_more: number;
  not_run: { what: string; why: string }[];
  limits: string[];
}
