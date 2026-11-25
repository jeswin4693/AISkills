# GitHub links on the command line (slice AA) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every command-line command that takes a repository also takes the link of a public GitHub repository.

**Architecture:** One helper in `cli.py` turns a link into the downloaded copy the web page already uses (`builder.repository.resolve_repo`) and returns its folder; the five call sites use it and keep the original text for their own messages. A `RepoError` carries a refusal as one `error:` line.

**Tech Stack:** Python 3.13, argparse, pytest (offline: the page's fake download).

**Spec:** [docs/superpowers/specs/2026-11-25-cli-github-links-design.md](../specs/2026-11-25-cli-github-links-design.md)

## Global Constraints

- No new library; tests offline; the graph package gets no network code; backend tests from `backend/` with `C:\dev\venvs\aiskills\Scripts\python.exe -m pytest <file> -p no:cacheprovider` (no `-q`).
- A folder argument behaves exactly as before and imports nothing new: `skillforge.builder` is imported only for text that looks like a link.
- Notes about a download go to **stderr**; stdout stays what it was (so `--json` is still JSON). No message prints a path on this computer.
- Never type a backslash-u escape in source or tests (use `chr(...)`). Match each file's line endings. Grep the docs for placeholders before every push.
- Work on branch `slice-aa-cli-github-links`, one commit per task, trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`; at the end fast-forward `main` and push (`git push origin main` run in the background; a first attempt can hang on the credential manager).

## Review Focus

1. A refused link, a missing repository, a private one and an unreachable GitHub: one `error:` line, exit 2, no traceback, the typed text not repeated (Task 1).
2. A folder argument: same result as before, and `skillforge.builder` still not imported by it (Task 1, subprocess test).
3. `--json`: stdout parses as JSON while the note is on stderr (Task 1).
4. "What changed" commands must not read a stale copy: `library cite`, `recheck`, `refresh` download fresh each time, `graph` reuses a young copy (Task 2).
5. `plan` on a link must say the rules files are not downloaded (Task 2).

---

### Task 1: the helper, the error, `graph` and `suggest`

**Files:**
- Modify: `backend/skillforge/cli.py` (new `RepoError`, `_source_lines`, `_repo_arg`; `main()`'s two `except` tuples; `_run_suggest`; the graph branch of `main()`; help text of `repo`)
- Test: `backend/tests/test_cli_github.py` (create)

**Interfaces:**
- Produces: `class RepoError(Exception)`; `_source_lines(view: dict, now: float | None = None) -> list[str]` where `view` is `builder.repository.source_view(repo)` for a link (keys `owner`, `repo`, `ref`, `fetched_at`, `files`, `bytes`, `skipped`, `reused`); `_repo_arg(text: str | None, *, fresh: bool = False, extra: str = "") -> str | None` (None and `""` give `None`; a folder gives the same text; a link gives the folder of its copy and writes `_source_lines` plus `extra` to stderr).
- Consumes: `builder.repository.resolve_repo(path, fresh=...) -> Repo` and `source_view(repo)`, `builder.github.looks_like_link(text) -> bool`, `builder.errors.BuilderError`.

- [ ] **Step 1: Write the failing tests** in `test_cli_github.py`. Import the page's fixtures (`from test_github_link import LINK, served  # noqa: F401`, `served` is a pytest fixture; `REPO` files come from there), and a `run(capsys, *argv)` helper returning `(code, out, err)`. Tests:
  - `test_a_link_is_read_by_graph_stats_and_the_note_says_where_it_came_from`: `run("graph", "stats", LINK, "--no-history")` gives code 0, stdout has the file count of the fake repository (3), stderr contains `Read acme/shop-api from GitHub`, `Nothing was run` and `Git history is not downloaded`, stderr and stdout contain neither the snapshot folder (`str(gh.snapshot_root())`) nor `codeload`; `served["calls"] == 1`.
  - `test_a_young_copy_is_reused_by_graph`: two `graph stats` runs make one download.
  - `test_json_output_stays_json_and_the_note_goes_to_stderr`: `graph stats LINK --json --no-history`: `json.loads(out)["files"] == 3`, `"Read acme/shop-api" in err`.
  - `test_suggest_facts_only_reads_a_link`: `suggest LINK --facts-only --no-history` exits 0 with non-empty stdout and the note on stderr.
  - `test_a_branch_link_names_the_branch_in_the_note`: `LINK + "/tree/dev"` gives `branch dev` in the note.
  - `test_a_link_that_is_refused_is_one_error_line_and_exit_2` (parametrised: another site, `http://`, a login in the link, a port): code 2, stderr starts with `error:`, contains no `Traceback`, does not contain the typed host text, `served["calls"] == 0`.
  - `test_a_missing_repository_and_an_unreachable_github_are_one_error_line`: `served["error"] = gh.NotFound(gh.NOT_FOUND)` then `UpstreamError("Could not reach GitHub (TimeoutError).")`: code 2 each, the message in stderr, no traceback.
  - `test_a_folder_argument_is_unchanged`: `cli._repo_arg(str(folder)) == str(folder)`, `cli._repo_arg(None) is None`, `cli._repo_arg("") is None`, nothing on stderr; and `graph stats <folder>` prints exactly what it printed before (compare with `query.stats` rendering through `cli._render_stats`).
  - `test_reading_a_folder_does_not_import_the_builder` (subprocess, current interpreter, `cwd=backend`): a child process imports `skillforge.cli`, calls `_repo_arg("C:/some/folder")`, and prints whether `skillforge.builder` is in `sys.modules`; expected `False`. (If importing `cli` alone already imports it, the test pins that the helper adds nothing: compare the answer before and after the call.)
  - `test_source_lines_for_a_copy_that_was_reused_and_one_that_was_just_downloaded` (pure): the reused one says `a copy from 4 minutes ago` for a `fetched_at` four minutes before `now`; the fresh one says `downloaded just now`; `skipped={"not_source": 2, "too_large": 1}` gives a `Left out:` line naming both reasons in words.
- [ ] **Step 2:** Run `python -m pytest tests/test_cli_github.py -p no:cacheprovider`. Expected: the new tests FAIL (`_repo_arg` missing, or a graph error for a link as a folder).
- [ ] **Step 3: Implement** in `cli.py`. `_repo_arg`: if `text` is falsy return `None`; import `looks_like_link` lazily only when the text contains `://` or starts with `github.com/` or `www.github.com/` (otherwise return the text); for a link call `resolve_repo`, convert a `BuilderError` to `RepoError(str(exc))`, print the note lines to `sys.stderr`, return `str(repo.folder)`. `_source_lines`: the first line `Read owner/repo from GitHub (default branch | branch NAME): N source files kept (X MB), downloaded just now | a copy from N minutes ago.`; a `Left out: ...` line in words (reasons `not_source`, `ignored_dir`, `too_large`, `link`, `unsafe_name`, `duplicate`, `limit`, `path_too_long`, `unwritable`, `unreadable`); then `Nothing was run. Git history is not downloaded, so facts that come from it (how often a file changes) are missing.` Use it in the graph branch of `main()` and `_run_suggest`; add `RepoError` to both `except` tuples in `main()`; update the `repo` help text.
- [ ] **Step 4:** Run the same command. Expected: PASS; then `python -m pytest tests/test_cache_history_cli.py tests/test_evidence_cli.py -p no:cacheprovider` still passes.
- [ ] **Step 5:** Commit: `git add backend && git commit -m "Slice AA: GitHub links in graph and suggest"`.

---

### Task 2: `plan`, `build --repo` and `library cite|recheck|refresh`

**Files:** Modify `backend/skillforge/cli.py` (`_run_plan`, `_run_build`, `_run_evidence`, help texts of the `--repo` options); extend `backend/tests/test_cli_github.py`.

**Interfaces:** Consumes `_repo_arg` from Task 1; `cite`, `recheck`, `refresh` call `_repo_arg(args.repo, fresh=True)`; `plan` passes `extra="CLAUDE.md and AGENTS.md are not downloaded, so the rules they hold are not read."`. Each handler keeps `args.repo` (the person's own text) for the messages that print it back.

- [ ] **Step 1: Write the failing tests:**
  - `test_plan_on_a_link_says_the_rules_files_are_not_downloaded`: `plan "rename shared" --repo LINK --no-ai` exits 0, stderr has the link note and `CLAUDE.md` and `not downloaded`, stdout holds the plan.
  - `test_cite_recheck_and_refresh_download_a_fresh_copy_each_time_and_graph_does_not`: import a skill (`write_skill` from `test_library`, through `library import`); two `graph stats LINK` runs make 1 download; then `library cite NAME --repo LINK --ref core.py::shared` makes 2, `library recheck NAME --repo LINK` 3, `library refresh NAME --repo LINK` 4; cite exits 0 and its text prints the link back in the `recheck` hint, recheck says everything holds (exit 0).
  - `test_recheck_of_a_link_names_what_changed`: after the cite, change `served["files"]` (remove `shared` from `core.py`), `library recheck` exits 1 and names the missing place.
  - `test_build_with_a_link_records_the_ideas_evidence`: copy the pattern of `test_build_with_a_repository_records_the_ideas_evidence` in `test_evidence_cli.py` (mock provider through `monkeypatch.setattr(cli, "provider_from_env", ...)`) with `--repo LINK` instead of a folder: exit 0, the build prints the evidence line, `evidence.json` exists in the built folder.
  - `test_a_refused_link_stops_build_before_a_model_is_asked`: `build --from-suggestions ... --repo https://gitlab.com/a/b` exits 2 and the mock provider got no call.
- [ ] **Step 2:** Run the file. Expected: the five new tests FAIL.
- [ ] **Step 3: Implement:** in `_run_plan` call `_repo_arg(args.repo, extra=...)` before `make_plan` and pass the folder; in `_run_build` `graph = build_graph(_repo_arg(args.repo), ...)` (so a refused link stops before a model is asked); in `_run_evidence` use `fresh=True` for all three commands. Update the help of `plan --repo`, `build --repo` and `library cite|recheck|refresh --repo` to say a public GitHub link is accepted.
- [ ] **Step 4:** Run the file and `python -m pytest tests/test_evidence_cli.py tests/test_conductor.py -p no:cacheprovider`. Expected: PASS.
- [ ] **Step 5:** Commit: `git add backend && git commit -m "Slice AA: GitHub links in plan, build and the evidence commands"`.

---

### Task 3: real runs, breaks, docs, merge

**Files:** `README.md`, `CLAUDE.md`, `docs/roadmap.md` (new row AA, update the Next row), `docs/github-link.md` ("What is not here"), `docs/try-it.md` (section A), a short `docs/cli-github-links.md`.

- [ ] **Step 1: Real runs** (real GitHub, scratch `SKILLFORGE_DATA_DIR`): `python -m skillforge graph stats https://github.com/jeswin4693/AISkills`, the same again (reused), `graph hotspots ... --json | python -m json.tool`, `suggest ... --facts-only`, `plan "..." --repo <link> --no-ai`, a refused link, and a link to a repository that does not exist. Note what each printed; a surprise is a finding: fix it with a test first.
- [ ] **Step 2: Deliberate breaks**, one at a time, each must fail a test (restore after): the helper returns the link text unchanged; the note goes to stdout; `cite`/`recheck`/`refresh` stop using `fresh=True`; the `RepoError` is not caught in `main()`; `plan` loses its rules note; a folder is run through `resolve_repo`; the helper is imported at the top of `cli.py`.
- [ ] **Step 3: Docs.** `docs/cli-github-links.md`: the commands, the freshness rule, the note, the limits (public only, no history, no `CLAUDE.md`/`AGENTS.md`, `build --repo` looks the idea's places up in the copy that is current when the build ends, `cite` on a link records no commit). Roadmap row AA (what, checked, not verified), README and `CLAUDE.md` status and Next, `github-link.md` first bullet of "What is not here", a step in `try-it.md` section A.
- [ ] **Step 4:** Full backend suite, `npm test` and typecheck (the UI is untouched but the suite must stay green); scan changed files for hidden characters and keys; grep the docs for placeholders.
- [ ] **Step 5:** Commit; `git switch main`; `git merge --ff-only slice-aa-cli-github-links`; `git push origin main` in the background; confirm `origin/main`.
