# Component Factory, Phase 0: Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the app ready for more than one kind of thing to build (a kind registry, a library per kind, a `kind` on sessions and the API, a picker in the UI) with **no change for skills**, plus two small skill improvements.

**Architecture:** A new `skillforge/kinds/` package holds a `Kind` base class and one adapter, `SkillKind`, over today's functions (strangler: nothing is rewritten). The library, the validator, the builder service and the API ask the registry instead of assuming "skill". With only `skill` registered, every old URL, file and screen behaves as before; the tests prove it by using a fake second kind.

**Tech Stack:** Python 3.13, pydantic 2, SQLAlchemy + Alembic, FastAPI, pytest. Frontend: Next.js 16, React 19, TypeScript, vitest.

**Spec:** [docs/component-factory.md](../../component-factory.md) (Phase 0 row, Architecture, Rules)

## Global Constraints

- Run Python from `backend/`: Git Bash `/c/dev/venvs/aiskills/Scripts/python.exe -m pytest -q` (below written as `python -m pytest`). Frontend from `frontend/` (`npm run typecheck`, `npm test`, `npm run build`, `npm run e2e`; run `scripts\frontend-node-modules.ps1` after any `npm install`, but this plan adds no package).
- Tests are offline: `MockProvider`, a temp data folder; no test reads `.env` or calls a model. This plan adds **no model call**.
- No new library. The graph (`skillforge/graph`) is not touched. The command line is not touched (no `--kind` flag in this slice).
- Every existing test keeps passing; a test may change only where a task says so.
- Existing names stay importable: `skillforge.library.skill_name_of`, `Library(root)`, `validate_files(files, folder=, problems=)`, `Builder.start(description, with_scripts)`.
- `kind` values are looked up in the registry, never joined into a path.
- After the slice: README, `docs/roadmap.md`, `docs/component-factory.md` and the touched docs updated; commit per task; push at the end (`timeout 75 git push origin main`). Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`; check `git diff --cached` for `.env` or key fragments first.

## Out of scope (decided while planning)

- **Run `eval` from the web pages** (listed under Phase 0 in the spec) is **deferred to its own plan**. An eval makes dozens of model calls and takes minutes; the hosted version forwards `/api/*` through a Next.js rewrite that I believe cuts a request at about 30 seconds (check before relying on it), and the `jobs` table only exists per builder session. It needs a job that is not a builder session. Deferring it is a deviation from the spec's Phase 0 list.
- Library tabs and per-kind skill/compare pages: they come with Phase 1, when a second real kind exists to look at. This slice adds the picker, the badge and `api` functions that accept a kind.

## Review Focus

- A database, a library folder or a URL from before this slice behaves exactly as now: old rows get `kind = "skill"`, `/api/library` with no `?kind` returns the same payload (tasks 4, 6).
- `?kind=../x`, `?kind=` and `kind: "a/b"` must be a plain 400 that names the kinds there are, and create no folder (tasks 3, 6).
- A session row whose kind is no longer registered can still be read, listed and discarded; continuing it ends in a plain failed state, not a 500 (task 5).
- `allowed-tools` **pre-approves** tools while a skill is active, which is a real grant: a text-only skill must get no `allowed-tools` line at all, and the same permissions must always give the same bytes (task 7).
- A SKILL.md with a front-matter key that is new to Claude Code must warn, never fail or block an import; a key the list wrongly misses would make `rescan` call every old skill that has it "worse" (task 8).

---

### Task 1: Kind registry and `SkillKind`

**Files:**
- Create: `backend/skillforge/kinds/__init__.py`, `backend/skillforge/kinds/base.py`, `backend/skillforge/kinds/skill.py`
- Modify: `backend/skillforge/validate/static.py` (one shared `MAX_NAME = 64`, used by the `name` check), `backend/skillforge/library/service.py` (`skill_name_of` becomes a re-export), `backend/skillforge/library/store.py` (import `MAX_NAME` from `validate.static`)
- Test: `backend/tests/test_kinds.py`

**Interfaces:**
- Produces (`kinds/base.py`): `@dataclass(frozen=True) class Slot(key: str, label: str, question: str)`; `class UnknownKind(ValueError)`; `class Kind(ABC)` with class attributes `key: str`, `label: str`, `library_dir: str`, `slots: tuple[Slot, ...]`, `install_targets: tuple[str, ...] = ("personal", "folder")` and abstract methods `name_of(self, files: Mapping[str, bytes]) -> str | None` and `personal_dir(self) -> Path`.
- Produces (`kinds/__init__.py`): `KINDS: dict[str, Kind]` (insertion order = display order), `get_kind(key: str) -> Kind` (raises `UnknownKind("'x' is not a kind this app builds. It builds: skill.")`), `all_kinds() -> list[Kind]`.
- `SkillKind`: `key="skill"`, `label="Skill"`, `library_dir="library"`, `slots` = `build.models.SLOTS` in order, each with its `build.requirements.QUESTIONS` text and the label the UI shows today (`SLOT_LABEL` in `frontend/src/lib/builder.ts`: "Goal", "What it receives", "What it produces", "Rules it must respect", "How we will know it works", "When something goes wrong"); `name_of` is the body of today's `skill_name_of`; `personal_dir()` is `Path.home() / ".claude" / "skills"`.
- Dependency direction: `kinds` imports `build` and `validate` only; `library` imports `kinds`, never the reverse.
- Also in `tests/test_kinds.py` (used by tasks 3, 5, 6): `FakeKind(Kind)` with `key="note"`, `label="Note"`, `library_dir="library-note"`, `name_of` = first line of `thing.txt` if it is a valid slug else `None`, `personal_dir` = a temp folder; and a fixture `fake_kind(monkeypatch)` that does `monkeypatch.setitem(KINDS, "note", FakeKind())` and returns it.

- [ ] **Step 1: Write the failing tests** in `test_kinds.py`:
  - `test_the_skill_kind_is_registered_and_an_unknown_kind_is_a_plain_error`: `[k.key for k in all_kinds()] == ["skill"]`; `get_kind("nope")` raises `UnknownKind` and the message contains `"skill"`.
  - `test_the_skill_kinds_slots_are_the_checklist_in_order`: `[s.key for s in get_kind("skill").slots] == list(SLOTS)`; each `s.question == QUESTIONS[s.key]`; `get_kind("skill").slots[1].label == "What it receives"`.
  - `test_name_of_reads_the_front_matter_name_and_refuses_unsafe_names`: `---\nname: a-b\n---\n` gives `"a-b"`; `name: ../x`, no front matter, bad YAML and a 65-character name give `None`; `skillforge.library.skill_name_of` is the same function's behaviour.
- [ ] **Step 2: Run** `python -m pytest tests/test_kinds.py -q`; expected: FAIL (`ModuleNotFoundError: skillforge.kinds`).
- [ ] **Step 3: Implement** the package per Interfaces. Registry is a module-level dict filled with `SkillKind()`.
- [ ] **Step 4: Run** `python -m pytest tests/test_kinds.py tests/test_library.py -q`; expected: PASS (library tests prove the re-export).
- [ ] **Step 5: Commit** `git add backend/skillforge/kinds backend/skillforge/validate backend/skillforge/library backend/tests/test_kinds.py` ("Add the kind registry and the skill kind").

### Task 2: The validator takes a `kind`

**Files:**
- Modify: `backend/skillforge/validate/static.py`, `backend/skillforge/validate/__init__.py`
- Test: `backend/tests/test_validate.py`

**Interfaces:**
- Produces: `DefinitionCheck = Callable[[Mapping[str, bytes], str | None], list[CheckResult]]`; `DEFINITION_CHECKS: dict[str, DefinitionCheck] = {"skill": _check_skill_md}` (exported from `skillforge.validate`); `validate_files(files, *, folder=None, problems=None, kind: str = "skill")`. The definition check is the **only** thing that varies by kind; every other check runs for every kind. An unregistered `kind` raises `ValueError("No checks are registered for kind 'x'.")`.

- [ ] **Step 1: Write the failing tests:**
  - `test_validating_with_no_kind_is_the_same_as_the_skill_kind`: `validate_files(files) == validate_files(files, kind="skill")` on a valid skill and on a broken one.
  - `test_another_kind_swaps_only_the_definition_check` (`monkeypatch.setitem(DEFINITION_CHECKS, "note", fn)` where `fn` returns `[CheckResult("thing.txt exists", PASSED)]`): the result list has `"thing.txt exists"`, has no `"SKILL.md exists and its front matter is valid"`, and still has `"no hidden or direction-changing characters in text files"`.
  - `test_an_unregistered_kind_is_refused`: `pytest.raises(ValueError, match="'nope'")`.
- [ ] **Step 2: Run** `python -m pytest tests/test_validate.py -q`; expected: the three new tests FAIL (`TypeError: unexpected keyword 'kind'`).
- [ ] **Step 3: Implement** the registry and the `kind` parameter; replace the direct `_check_skill_md` call in `validate_files`. `validate_skill_dir` is unchanged.
- [ ] **Step 4: Run** `python -m pytest tests/test_validate.py -q`; expected: all PASS.
- [ ] **Step 5: Commit** ("Let the validator take a kind; only the definition check varies").

### Task 3: One library per kind

**Files:**
- Modify: `backend/skillforge/library/store.py`, `backend/skillforge/library/service.py`, `backend/skillforge/library/rescan.py`
- Test: `backend/tests/test_kinds.py`

**Interfaces:**
- Consumes: `get_kind`, `Kind.name_of`, `Kind.library_dir` (task 1); `validate_files(..., kind=)` (task 2).
- Also: extend the `fake_kind` fixture so it additionally does `monkeypatch.setitem(DEFINITION_CHECKS, "note", ...)`, a check named `"thing.txt exists"` that fails when `thing.txt` is missing (tasks 5 and 6 reuse it).
- Produces: `Library(root: Path | None = None, kind: str = "skill")` with `self.kind`; default root `data_dir() / get_kind(kind).library_dir` (so the skill root is exactly where it is today); `Library.for_kind(kind: str) -> Library` (returns `self` for the same kind, otherwise `Library(self.root.parent / get_kind(kind).library_dir, kind)`); `backups` is `root.parent / "backups"` for skills and `root.parent / f"backups-{kind}"` for others. `check_source(src, kind="skill")`. `import_source`, `rollback`, `package_skill`, `install_skill`, `rescan` all gate with `kind=library.kind`; `import_source` takes the name from `get_kind(library.kind).name_of`.

- [ ] **Step 1: Write the failing tests** (use `fake_kind`):
  - `test_each_kind_has_its_own_library_root_and_names_never_cross`: import a `thing.txt` folder into `lib.for_kind("note")`; `lib.for_kind("note").root == tmp_path / "library-note"`; `lib.names() == []`; `lib.for_kind("note").names() == ["my-thing"]`; `lib.for_kind("skill") is lib`.
  - `test_a_kind_is_never_joined_into_a_path`: for `"../x"`, `""`, `"a/b"`: `Library(tmp_path / "library", kind=bad)` and `lib.for_kind(bad)` raise `UnknownKind`, and `sorted(p.name for p in tmp_path.iterdir())` is unchanged.
  - `test_importing_into_another_kind_uses_its_name_and_its_checks`: a folder with only `SKILL.md` is refused by the note library with the fake definition check's name among the failed checks; the same folder still imports into the skill library.
  - `test_rescan_and_rollback_use_the_libraries_kind`: with a note-kind version stored, `rescan(lib.for_kind("note"))` reports `same` (it would report `failing` if it ran the SKILL.md check); `rollback(lib.for_kind("note"), "my-thing", 1)` on a two-version history makes v3.
- [ ] **Step 2: Run** `python -m pytest tests/test_kinds.py -q`; expected: the four new tests FAIL.
- [ ] **Step 3: Implement** per Interfaces. `Library.__init__` validates `kind` through `get_kind` before touching the disk.
- [ ] **Step 4: Run** `python -m pytest tests/test_kinds.py tests/test_library.py tests/test_risk.py tests/test_api.py -q`; expected: all PASS.
- [ ] **Step 5: Commit** ("Give every kind its own library root and checks").

### Task 4: Migration 0003 and the model columns

**Files:**
- Create: `backend/skillforge/db/migrations/versions/0003_session_kind.py`
- Modify: `backend/skillforge/db/models.py`, `backend/skillforge/db/database.py`
- Test: `backend/tests/test_builder.py`

**Interfaces:**
- Produces: `BuildSession.kind: Mapped[str] = mapped_column(String(16), default="skill", server_default="skill")` and `BuildSession.parent_id: Mapped[str | None] = mapped_column(String(32), nullable=True)` (a plugin's child builds later; no foreign key, because SQLite cannot add one to an existing table). `Database.migrate(self, revision: str = "head") -> None`. Migration revision `"0003"`, down `"0002"`; downgrade drops both columns in `batch_alter_table`.

- [ ] **Step 1: Write the failing tests:**
  - `test_a_database_from_before_kinds_upgrades_and_old_sessions_become_skills`: `db.migrate("0002")`, insert a session row with raw SQL without `kind`, `db.migrate()`, then `select(BuildSession)` gives `kind == "skill"` and `parent_id is None`.
  - Update `test_the_migration_creates_exactly_what_the_models_describe_and_is_safe_to_repeat` only if it fails (it should still pass: same tables, `compare_metadata(...) == []`).
- [ ] **Step 2: Run** `python -m pytest tests/test_builder.py -q -k "migration or before_kinds"`; expected: the new test FAILS (`migrate()` takes no argument).
- [ ] **Step 3: Implement** the columns, the migration, and the `revision` parameter on `Database.migrate`.
- [ ] **Step 4: Run** `python -m pytest tests/test_builder.py tests/test_usage_db.py -q`; expected: PASS.
- [ ] **Step 5: Commit** ("Add kind and parent_id to builder sessions (migration 0003)").

### Task 5: The builder works through the kind

**Files:**
- Modify: `backend/skillforge/kinds/base.py`, `backend/skillforge/kinds/skill.py`, `backend/skillforge/builder/service.py`
- Test: `backend/tests/test_builder.py`

**Interfaces:**
- Consumes: `get_kind`, `Library.for_kind`, `BuildSession.kind`.
- Produces: `@dataclass class BuildOutcome(summary: dict, model_calls: int, notes: list[str])` in `kinds/base.py`; two more abstract methods on `Kind`: `understand(self, provider: LLMProvider, words: str, round_no: int, max_rounds: int) -> Round` (`Round` from `build.pipeline`) and `build(self, spec: dict, provider: LLMProvider, *, out_root: Path, with_scripts: bool, script_runner: ScriptRunner | None, sandbox_note: str, calls: int, notes: list[str], progress: Callable[[str], None]) -> BuildOutcome`. `SkillKind.understand` calls `understand_round`; `SkillKind.build` validates `spec` as `RequirementSpec`, calls `build_from_spec(..., force=True)` and returns today's `_summary(result)` (move `_summary` into `kinds/skill.py`). `Builder.start(description, with_scripts=False, kind="skill")` (an unknown kind raises `BadRequest(str(exc))`, stores nothing); `Builder.get()` and `Builder.list()` include `"kind"`; `_understand`/`_build` dispatch on `row.kind`; `save` imports into `self.library.for_kind(row.kind)`. `FakeKind` (task 1) gains `understand` and `build` that return a complete one-round `Round` and a folder `out_root/"thing"/thing.txt`, so the whole conversation can run.

- [ ] **Step 1: Write the failing tests:**
  - `test_a_session_records_its_kind_and_a_new_kind_runs_its_own_understand_and_build_and_saves_to_its_own_library` (`fake_kind`): start with `kind="note"`, approve, save; `session["kind"] == "note"`, the thing is in `lib.for_kind("note")` and `lib.names() == []`.
  - `test_starting_with_an_unknown_kind_is_a_bad_request_and_stores_nothing`: `BadRequest`; `select(BuildSession)` is empty.
  - `test_a_session_whose_kind_is_no_longer_registered_can_be_read_listed_and_discarded_but_not_continued`: insert a row with `kind="gone"` and `status="awaiting_approval"`; `get(sid)["kind"] == "gone"`; it is in `list()`; `approve` ends `failed`, `retryable is False`, error contains `"gone"`; `discard` works.
  - Every existing test in the file passes **unchanged** (the safety net for moving `_summary`).
- [ ] **Step 2: Run** `python -m pytest tests/test_builder.py -q`; expected: the three new tests FAIL.
- [ ] **Step 3: Implement** per Interfaces. In `_execute`, treat `UnknownKind` like `BuildError` (not retryable); in `save`, raise `BuilderError` with the same message.
- [ ] **Step 4: Run** `python -m pytest -q`; expected: everything PASS (a few sandbox tests skip without Docker).
- [ ] **Step 5: Commit** ("Make the builder work through the kind registry").

### Task 6: API: `GET /api/kinds`, `?kind=`, `kind` on start

**Files:**
- Modify: `backend/skillforge/api/app.py`, `backend/skillforge/api/builds.py`
- Test: `backend/tests/test_api.py`, `backend/tests/test_builder.py`

**Interfaces:**
- Consumes: `Library.for_kind`, `get_kind`, `all_kinds`, `Builder.start(..., kind=)`.
- Produces: `StartBody.kind: str = "skill"`; `GET /api/kinds` → `[{"key", "label", "install_targets": ["personal", "folder"], "slots": [{"key", "label", "question"}]}]`; a FastAPI dependency `library_for(request: Request, kind: str = "skill") -> Library` (`request.app.state.library.for_kind(kind)`; `UnknownKind` becomes `HTTPException(400, str(exc))`) used by **every** `/api/library*` and `/api/rescan` route in place of `_library(request)`; `/api/validate` also takes `?kind=`; the install route uses `get_kind(lib.kind).personal_dir()` for `target == "personal"`. `create_app` keeps its signature.

- [ ] **Step 1: Write the failing tests:**
  - `test_kinds_lists_the_skill_kind_with_its_slots`: `[k["key"] for k in client.get("/api/kinds").json()] == ["skill"]`, the first slot is `{"key": "goal", "label": "Goal", "question": QUESTIONS["goal"]}`, and `install_targets == ["personal", "folder"]`.
  - `test_the_library_routes_default_to_skills_and_take_a_kind` (`fake_kind`): an upload to `/api/library/import?kind=note` appears in `/api/library?kind=note`, not in `/api/library`.
  - `test_an_unknown_kind_is_a_400_that_names_the_kinds_on_every_library_route`: parametrized over `GET /api/library`, `/api/library/x`, `/api/library/x/diff`, `/api/rescan`, `/api/library/x/versions/1/files/a`, `/api/library/x/export`, `POST /api/library/import`, `/api/library/x/rollback`, `/api/library/x/install`, `/api/validate`, each with `kind=../x`: status 400, `"skill"` in `detail`, and no new folder under the library's parent.
  - (`test_builder.py`) `test_starting_a_build_over_http_with_an_unknown_kind_is_a_400`, and `test_the_default_kind_is_skill_and_the_session_says_so`.
- [ ] **Step 2: Run** `python -m pytest tests/test_api.py tests/test_builder.py -q`; expected: the new tests FAIL.
- [ ] **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Run** `python -m pytest -q`; expected: PASS (`tests/test_hosted.py` included: the sign-in rules are unchanged).
- [ ] **Step 5: Commit** ("Add GET /api/kinds, ?kind= on the library routes and a kind on builds").

### Task 7: `permissions` become `allowed-tools`

**Files:**
- Create: `backend/skillforge/kinds/tools.py`
- Modify: `backend/skillforge/build/render.py` (`frontmatter`), `docs/build.md`
- Test: `backend/tests/test_skill_build.py`

**Interfaces:**
- Produces: `TOOLS_FOR: dict[str, tuple[str, ...]] = {"read_files": ("Read", "Grep", "Glob"), "write_files": ("Edit", "Write"), "run_commands": ("Bash",), "network": ("WebFetch", "WebSearch")}` and `tools_for(permissions: Sequence[str]) -> list[str]` (order follows `TOOLS_FOR`, never the input; each tool once; an unknown permission raises `ValueError`). The Agent builder reuses it in Phase 1. `frontmatter(sdm)` adds `allowed-tools` as one space-separated string (the form the risk diff already reads, `library/risk.py:100`) only when `tools_for(sdm.permissions)` is not empty.
- Format fact to re-check before landing (not tested against a live Claude Code): that `allowed-tools` is read as a space-separated string in a skill's front matter. If the current Claude Code docs say otherwise, change the one line in `frontmatter` and say so in `docs/build.md`.

- [ ] **Step 1: Write the failing tests:**
  - `test_permissions_become_an_explicit_ordered_tool_list`: `tools_for(["network", "read_files", "read_files"]) == ["Read", "Grep", "Glob", "WebFetch", "WebSearch"]`; `tools_for([]) == []`; `tools_for(["root"])` raises `ValueError`.
  - `test_a_text_only_skill_has_no_allowed_tools_line`: the parsed front matter keys are exactly `["name", "description"]`.
  - `test_a_skill_with_permissions_declares_exactly_the_matching_tools`: permissions `["read_files", "run_commands"]` give front matter `allowed-tools == "Read Grep Glob Bash"`.
  - `test_the_risk_diff_sees_a_skill_gaining_allowed_tools`: `risk_diff(text_only_files, network_files, "v1", "v2")` has a `RiskChange` of kind `"tool"` that is `RISKIER` and names `WebFetch`.
- [ ] **Step 2: Run** `python -m pytest tests/test_skill_build.py -q`; expected: the new tests FAIL.
- [ ] **Step 3: Implement** `tools.py` and the `frontmatter` change.
- [ ] **Step 4: Run** `python -m pytest -q`; expected: PASS. If a token-count or SKILL.md-text assertion moves for a skill with permissions, update only that expectation.
- [ ] **Step 5: Commit** ("Write allowed-tools from a skill's permissions, by code").

### Task 8: Warn on unknown front-matter keys

**Files:**
- Create: `backend/skillforge/validate/formats.py`
- Modify: `backend/skillforge/validate/static.py` (`_check_skill_md`), `docs/validate.md`
- Test: `backend/tests/test_validate.py`

**Interfaces:**
- Produces (`validate/formats.py`): `SKILL_FRONT_MATTER_KEYS: frozenset[str]` and `SKILL_FORMAT_CHECKED_ON: str`. **Do not guess the list:** read the current skill front-matter reference in the official Claude Code docs, copy the keys, and record today's date. It includes at least `name`, `description`, `allowed-tools`. `_check_skill_md` adds one more result when the front matter is a mapping: `CheckResult("front matter uses only keys Claude Code knows", PASSED | WARNING, ...)`; the warning names the unknown keys and says the list was checked on `SKILL_FORMAT_CHECKED_ON` and a newer Claude Code may know them. Structure still fails only for the existing reasons.

- [ ] **Step 1: Write the failing tests:**
  - `test_known_front_matter_keys_pass`: `name`, `description`, `allowed-tools` give a `passed` result for the new check.
  - `test_an_unknown_key_warns_and_names_it_but_does_not_block_an_import` (also in `test_library.py` style via `import_source`): `colour: red` gives `warning` with `"colour"` in its detail; the import creates v1.
  - `test_a_skill_built_here_has_no_unknown_key_warning`: the front matter from `render.frontmatter` for a skill with every permission passes the check.
  - `test_front_matter_that_is_not_a_mapping_adds_no_second_result`.
- [ ] **Step 2: Run** `python -m pytest tests/test_validate.py -q`; expected: the new tests FAIL.
- [ ] **Step 3: Implement** the data file and the check.
- [ ] **Step 4: Run** `python -m pytest -q`; expected: PASS.
- [ ] **Step 5: Commit** ("Warn on front-matter keys Claude Code does not know").

### Task 9: UI: kinds from the server, picker, badge

**Files:**
- Modify: `frontend/src/lib/types.ts`, `frontend/src/lib/api.ts`, `frontend/src/lib/builder.ts`, `frontend/src/app/builder/page.tsx`, `frontend/src/components/builder/RequirementCard.tsx` (and the other callers of `specRows`)
- Create: `frontend/src/lib/useKinds.ts`
- Test: `frontend/src/lib/builder.test.ts`

**Interfaces:**
- Produces (`types.ts`): `KindInfo { key: string; label: string; install_targets: string[]; slots: { key: string; label: string; question: string }[] }`; `kind: string` on `BuildSession` and `BuildSummary`. (`api.ts`): `kinds(): Promise<KindInfo[]>`; `startBuild(description, withScripts, kind = "skill")` sends `kind`; the library functions (`listSkills`, `versions`, `diff`, `file`, `rescan`, `importZip`, `rollback`, `install`, `exportZip`) take an optional last `kind` and add `?kind=` **only when it is not `"skill"`**, so every skill URL is unchanged. (`builder.ts`): `specRows(spec, slots = DEFAULT_SLOTS)` where `DEFAULT_SLOTS` is today's `SLOT_ORDER`/`SLOT_LABEL`; `showKindPicker(kinds: KindInfo[] | undefined): boolean` (true only for two or more kinds). (`useKinds.ts`): `useKinds()` returning `useAsync(api.kinds, "kinds")`.
- Behaviour: `/builder` shows a kind picker above the text box only when `showKindPicker`, and the heading reads `Build a {label}`; recent sessions show a kind badge only when more than one kind exists; requirement rows use the session kind's slot labels from the server, falling back to `DEFAULT_SLOTS` when the API does not list them. With one kind the page looks exactly as today.

- [ ] **Step 1: Write the failing tests** in `builder.test.ts`: `specRows` with custom slots uses their labels and order; `specRows(spec)` equals today's rows; `showKindPicker(undefined)`, `showKindPicker([skill])` are false and `showKindPicker([skill, agent])` is true.
- [ ] **Step 2: Run** `npm test` (from `frontend/`); expected: the new tests FAIL.
- [ ] **Step 3: Implement** the types, the api functions, the helpers, the hook and the page changes.
- [ ] **Step 4: Run** `npm run typecheck && npm test`; expected: clean, all pass.
- [ ] **Step 5: Run** `npm run build && npm run e2e` (needs ports 3000 and 8000 and Edge); expected: the 39 existing behaviours still pass.
- [ ] **Step 6: Commit** ("Show kinds in the builder: picker, badge, labels from the server").

### Task 10: Documents, full check, push

**Files:**
- Modify: `README.md`, `CLAUDE.md` (the "Next:" sentence), `docs/roadmap.md`, `docs/component-factory.md`, `docs/api.md`, `docs/database.md`, `docs/library.md`, `docs/validate.md`, `docs/ui.md`, `docs/build.md`

- [ ] **Step 1:** `docs/roadmap.md`: add a row "O. Component Factory, Phase 0" (what is built, test counts, what was checked, what was **not**: no second kind exists yet, eval-from-web deferred, allowed-tools format not tried against a live Claude Code); change the D2 row's "Agent Builder last / Next" text to the real order (Phase 1 Agent Builder next). `docs/component-factory.md`: status line says Phase 0 built and lists the deferral. The other docs get the new routes, columns, `Library(kind)`, `validate_files(kind=)`, the picker and the two skill changes.
- [ ] **Step 2: Run** `python -m pytest -q` from `backend/` and `npm run typecheck && npm test` from `frontend/`; expected: all pass, with the counts written into the roadmap row as they really are.
- [ ] **Step 3: Check** `git status` shows only intended files and `git diff --cached` shows no `.env` content or key fragments.
- [ ] **Step 4: Commit** ("Record the Component Factory foundation in the docs") and `timeout 75 git push origin main`; expected: the push succeeds (a 403 means the work account is cached, see the push notes in memory).
