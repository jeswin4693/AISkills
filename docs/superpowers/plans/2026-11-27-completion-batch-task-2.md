# Completion batch, task 2: the two GitHub-link risks and the usage clean-up — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the two open risks of the GitHub-link slice (pruning a snapshot another request is reading; git seeing a repository above the data folder) and stop the `model_calls` table growing forever.

**Architecture:** (A) opening a snapshot writes a `used` marker with the time; `_prune` skips a snapshot marked in the last 15 minutes and any repository whose lock is busy. (B) one helper, `graph/gitenv.py::git_env`, gives the four `git` calls an environment with `GIT_CEILING_DIRECTORIES` when the folder is inside the data folder. (C) `builder/retention.py` deletes usage rows older than `SKILLFORGE_USAGE_KEEP_DAYS` days, never today's, at start and at most once a day, hooked into `ModelAccess.provider_for`.

**Tech Stack:** Python 3.11+, SQLAlchemy, pytest, real `git` (task B tests). No new library.

**Spec:** [docs/superpowers/specs/2026-11-26-completion-batch-design.md](../specs/2026-11-26-completion-batch-design.md), items 5 and 6 (task 2 of its task list). Task 1 of the batch is already committed (`139e225`).

## Global Constraints

- Run everything from `backend/`: `python -m pytest -q`. Tests are offline: `MockProvider` only, no real `.env`, no hosted model.
- No new library. Keys are never printed or documented.
- A check is "passed" only if it ran: a failure to write a marker or to clean usage rows is logged, never silent success and never a failed build.
- The usage rows are the daily allowance's ledger: **no code may delete today's rows** (UTC day, the same `midnight` text `ModelAccess` compares with).
- A folder a person points at themselves is untouched by task B (a subfolder of a repository must still work).
- Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

1. A snapshot read 14 minutes ago survives a prune; one idle for 16 minutes is pruned (task A: `test_a_snapshot_read_*`, `test_an_idle_*`).
2. A repository that is in use (read recently, or whose lock is held by a request) is not dropped by the "newest few repositories" rule (task A).
3. A request holding its own repository's lock never deadlocks `_prune` (the lock is not re-entrant; `_prune` must not lock `key_dir`) (task A: existing concurrency tests keep passing).
4. A folder written with `..` parts, or with other capitals on Windows, inside the data folder still gets the ceiling; a folder outside it does not (task B).
5. `keep_days=1` just after midnight UTC deletes rows older than a day but never a row of today; `0`, a negative number and non-numbers delete nothing (task C).

---

### Task A: A snapshot another request is reading is not pruned

**Files:**
- Modify: `backend/skillforge/builder/github.py` (constants near line 57, `_prune` at 519, the three `_snapshot(...)` returns inside `open_snapshot` at 565, 572, 609)
- Modify: `backend/tests/test_github_link.py` (two existing tests near 447 and 456, new tests after them)
- Modify: `docs/github-link.md`

**Interfaces:**
- Produces: `USED_GRACE = 15 * 60` (seconds); `_lock_for(key_dir: Path) -> threading.Lock` (the per-repository lock `open_snapshot` already makes with `_LOCKS.setdefault`, moved into a function); `_mark_used(stamp_dir: Path, now: float) -> None`; `_recently_used(stamp_dir: Path, now: float) -> bool`; `_prune(root: Path, key_dir: Path, link: GithubLink, now: float) -> None` (gains `now`).
- The marker is a file `used` in the stamp folder (next to `meta.json`, outside the folder of source files) holding `repr(now)`.

- [ ] **Step 1: Change two existing tests and write the new ones (they fail)**

In `test_only_the_newest_two_snapshots_of_a_repository_are_kept` replace `clock.t += 100` with `clock.t += gh.USED_GRACE + 1`; in `test_only_a_limited_number_of_repositories_are_kept_oldest_first` replace `clock.t += 10` with `clock.t += gh.USED_GRACE + 1` (a snapshot made a moment ago is now "used", on purpose). Add, using the existing `snap`, `Fetcher`, `Tick`:

```python
def test_copies_made_within_the_grace_are_all_kept(tmp_path):
    fetch, clock = Fetcher(), Tick()
    paths = []
    for _ in range(4):
        paths.append(snap(tmp_path, fetch=fetch, clock=clock, fresh=True).path)
        clock.t += 60
    assert all(p.is_dir() for p in paths)


def test_an_idle_snapshot_is_pruned_once_the_grace_has_passed(tmp_path):
    fetch, clock = Fetcher(), Tick()
    paths = []
    for _ in range(3):
        paths.append(snap(tmp_path, fetch=fetch, clock=clock, fresh=True).path)
        clock.t += 60
    clock.t += gh.USED_GRACE + 1
    paths.append(snap(tmp_path, fetch=fetch, clock=clock, fresh=True).path)
    assert [p.is_dir() for p in paths] == [False, False, True, True]


def test_a_snapshot_read_a_moment_ago_survives_pruning_then_goes_when_idle(tmp_path):
    fetch, clock = Fetcher(), Tick()
    first = snap(tmp_path, fetch=fetch, clock=clock)
    clock.t += 3600
    snap(tmp_path, fetch=fetch, clock=clock, fresh=True)
    clock.t += 3600
    assert snap(tmp_path, fetch=fetch, clock=clock, stamp=first.stamp).path == first.path  # a read marks it used
    clock.t += 60
    snap(tmp_path, fetch=fetch, clock=clock, fresh=True)  # now three are older than the newest two
    assert first.path.is_dir()
    clock.t += gh.USED_GRACE + 1
    snap(tmp_path, fetch=fetch, clock=clock, fresh=True)
    assert not first.path.is_dir()


def test_a_repository_read_a_moment_ago_is_not_dropped_by_the_repository_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(gh, "MAX_REPOS", 1)
    fetch, clock = Fetcher(), Tick()
    a = snap(tmp_path, "https://github.com/acme/repo-a", fetch, clock)
    clock.t += 3600
    snap(tmp_path, "https://github.com/acme/repo-a", fetch, clock, max_age=None)  # read: marked used
    clock.t += 1
    snap(tmp_path, "https://github.com/acme/repo-b", fetch, clock)
    assert a.path.is_dir()
    clock.t += gh.USED_GRACE + 1
    snap(tmp_path, "https://github.com/acme/repo-b", fetch, clock, fresh=True)
    assert not a.path.is_dir()


def test_a_repository_whose_lock_is_held_is_left_alone_by_the_repository_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(gh, "MAX_REPOS", 1)
    fetch, clock = Fetcher(), Tick()
    a = snap(tmp_path, "https://github.com/acme/repo-a", fetch, clock)
    clock.t += 10 * 3600  # long idle: only the lock protects it
    lock = gh._lock_for(gh._key_dir(tmp_path / "snaps", gh.parse_link("https://github.com/acme/repo-a")))
    with lock:
        snap(tmp_path, "https://github.com/acme/repo-b", fetch, clock)
        assert a.path.is_dir()
    clock.t += 1
    snap(tmp_path, "https://github.com/acme/repo-b", fetch, clock, fresh=True)
    assert not a.path.is_dir()


def test_a_marker_that_cannot_be_written_does_not_fail_the_read(tmp_path):
    fetch, clock = Fetcher(), Tick()
    first = snap(tmp_path, fetch=fetch, clock=clock)
    (first.path.parent / "used").unlink()
    (first.path.parent / "used").mkdir()  # writing a file there now raises an OSError
    assert snap(tmp_path, fetch=fetch, clock=clock, max_age=None).path == first.path
```

- [ ] **Step 2: Run to see them fail**

Run: `python -m pytest -q tests/test_github_link.py -k "grace or idle or read_a_moment or lock_is_held or marker or newest_two or limited_number"`
Expected: FAIL (`AttributeError: ... USED_GRACE`).

- [ ] **Step 3: Implement in `builder/github.py`**

Add `USED_GRACE`, `_lock_for` (move the `with _GUARD: lock = _LOCKS.setdefault(...)` lookup into it; `open_snapshot` still reads `_GENERATION` under `_GUARD`), `_mark_used` (write `repr(now)` to `stamp_dir / "used"`; on `OSError` log a warning and return), `_recently_used` (read the float; `now - t < USED_GRACE`, so a time in the future counts as used; missing or unreadable is `False`). At each of the three `return _snapshot(...)` in `open_snapshot`, call `_mark_used(stamp_dir_or_final, now())` first (the new copy is marked with `epoch`, before `_prune` runs). `_prune(root, key_dir, link, now)`: in the keep-two loop skip a stamp that is `_recently_used`; in the repository-limit loop skip `ref == key_dir` first (its lock is held by the caller and is not re-entrant), then skip a repository where any stamp is `_recently_used` or where `_lock_for(ref).acquire(blocking=False)` fails; hold the lock around that repository's `rmtree` and release it in `finally`.

- [ ] **Step 4: Run the whole github test files**

Run: `python -m pytest -q tests/test_github_link.py tests/test_cli_github.py`
Expected: all pass (including the eight-requests-at-once test).

- [ ] **Step 5: Document and commit**

Add to `docs/github-link.md` (the part about copies kept): a copy that was opened in the last 15 minutes is never pruned, so a long read is not cut off; a few extra copies may live a little longer; the check and the delete take the repository's lock so they cannot cross.

```bash
git add backend/skillforge/builder/github.py backend/tests/test_github_link.py docs/github-link.md
git commit -m "Slice AK task 2a: pruning skips a snapshot opened in the last 15 minutes"
```

---

### Task B: Git never looks above the data folder

**Files:**
- Create: `backend/skillforge/graph/gitenv.py`
- Modify: `backend/skillforge/graph/files.py:55-72` (`_git_files`, two calls), `backend/skillforge/graph/history.py:23`, `backend/skillforge/evidence/snapshot.py:66` and `:76`
- Create: `backend/tests/test_git_ceiling.py`
- Modify: `docs/github-link.md`

**Interfaces:**
- Produces: `git_env(root: Path | str) -> dict[str, str] | None` — `None` (the call inherits the environment, as today) unless `root` is strictly inside `data_dir()`; otherwise a copy of `os.environ` with `GIT_CEILING_DIRECTORIES` set to the real path of `data_dir()` (an existing value is kept: `existing + os.pathsep + data`).
- Consumes: `graph.store.data_dir()`.

- [ ] **Step 1: Write the failing tests** in `tests/test_git_ceiling.py`

A helper `make_repo(tmp_path)` that runs the real `git` (`init -q`, `add -A`, `-c user.name=t -c user.email=t@t commit -q -m m`) in `tmp_path / "repo"` holding `top.py` and `data/github/k/s/proj/a.py`. Tests (each sets `SKILLFORGE_DATA_DIR` with `monkeypatch.setenv`):

```python
def test_a_folder_inside_the_data_folder_does_not_see_the_repository_above_it(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    monkeypatch.setenv("SKILLFORGE_DATA_DIR", str(repo / "data"))
    folder = repo / "data" / "github" / "k" / "s" / "proj"
    assert files._git_files(folder) is None
    assert git_head(folder) is None and git_dirty(folder) is False
    assert history.collect(folder, set())[0] is None


def test_a_folder_the_person_points_at_inside_a_repository_still_works(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    monkeypatch.setenv("SKILLFORGE_DATA_DIR", str(tmp_path / "elsewhere"))
    folder = repo / "data" / "github" / "k" / "s" / "proj"
    assert "a.py" in files._git_files(folder)
    assert git_head(folder) is not None
    assert history.collect(folder, {"a.py"})[0] == 1


def test_git_env_is_for_folders_strictly_inside_the_data_folder_however_they_are_written(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "github" / "x").mkdir(parents=True)
    monkeypatch.setenv("SKILLFORGE_DATA_DIR", str(data))
    assert git_env(tmp_path) is None and git_env(data) is None
    assert git_env(tmp_path / "other") is None
    env = git_env(data / "github" / "x")
    assert env is not None and os.path.normcase(env["GIT_CEILING_DIRECTORIES"]) == os.path.normcase(os.path.realpath(data))
    assert git_env(data / "github" / ".." / "github" / "x") is not None
    assert git_env(str(data / "github" / "x").upper()) is not None or os.name != "nt"
```

- [ ] **Step 2: Run to see them fail**

Run: `python -m pytest -q tests/test_git_ceiling.py`
Expected: FAIL (`ModuleNotFoundError: skillforge.graph.gitenv`).

- [ ] **Step 3: Implement `git_env` and pass `env=git_env(root)`** to all four places (`_git_files` both `subprocess.run` calls, `history.collect`, `git_head`, `git_dirty`). Compare with `os.path.realpath` on both sides, then `os.path.normcase`; `os.path.commonpath` raises `ValueError` across drives, which means outside. Only one entry is set, so the separator question never arises unless an existing value is kept (then use `os.pathsep`).

- [ ] **Step 4: Run**

Run: `python -m pytest -q tests/test_git_ceiling.py tests/test_graph_build.py tests/test_evidence.py`
Expected: pass. (If the real-git test fails on Windows only because of the path form git expects, fix the form in `git_env`; the test is the reason it exists.)

- [ ] **Step 5: Document and commit**

`docs/github-link.md`: for any folder inside the data folder git is told not to look above it (`GIT_CEILING_DIRECTORIES`); a folder the person points at is untouched.

```bash
git add backend/skillforge/graph/gitenv.py backend/skillforge/graph/files.py backend/skillforge/graph/history.py backend/skillforge/evidence/snapshot.py backend/tests/test_git_ceiling.py docs/github-link.md
git commit -m "Slice AK task 2b: git never looks above the data folder"
```

---

### Task C: The usage table is cleaned, and today's rows never are

**Files:**
- Create: `backend/skillforge/builder/retention.py`
- Modify: `backend/skillforge/builder/model_access.py` (`ModelAccess.__init__` and `provider_for`), `backend/skillforge/builder/service.py` (`Builder.__init__`, `Builder.default`)
- Create: `backend/tests/test_usage_retention.py`
- Modify: `.env.example` (after the `SKILLFORGE_PERSON_*` lines), `docs/hosting.md` (env table), `docs/database.md`

**Interfaces:**
- Produces in `builder/retention.py`: `DEFAULT_KEEP_DAYS = 90`; `keep_days_from_env(environ: Mapping[str, str]) -> int`; `prune_usage(db: Database, keep_days: int, now: datetime) -> int`; `class UsageRetention(db: Database, keep_days: int, clock: Callable[[], datetime] = utc_now)` with `run_if_due() -> int`.
- `ModelAccess.__init__(..., housekeeping: Callable[[], object] = lambda: None)`; `provider_for` calls `self.housekeeping()` first.
- `Builder.__init__(..., usage_keep_days: int = 0)` (0 = off, so every existing test is unaffected) makes `self.retention = UsageRetention(db, usage_keep_days, model_options.clock)` and passes `housekeeping=self.retention.run_if_due` to `ModelAccess`. `Builder.default(..., usage_keep_days: int | None = None)`: `None` reads `keep_days_from_env(os.environ)`; it then calls `run_if_due()` once, after `recover_interrupted()`.

Rules: `keep_days_from_env`: unset or blank → `90`; a whole number `0..36500` (surrounding spaces allowed) → that number; anything else → `0` (delete nothing: never guess how long to keep) and one logged warning. `prune_usage`: `0` deletes nothing; otherwise delete rows with `created_at < cutoff`, where `cutoff = min(now - keep_days days, today's UTC midnight)` written as `%Y-%m-%dT%H:%M:%S` text (the same form `ModelAccess` uses for `midnight`, so the text comparison agrees). `run_if_due`: runs the first time asked, then only when 24 hours have passed since the last attempt (a failed attempt counts, so a broken database is not hit on every build); it catches every exception, logs it, and returns the rows deleted (0 when not due or failed).

- [ ] **Step 1: Write the failing tests** in `tests/test_usage_retention.py`

Fixture `db` like `test_usage_db.py`; helper `add_call(db, created_at, user="u1")` inserting a `ModelCall` (`task="extract", tier="fast", provider="p", model="m", attempt=1, status="ok", latency_ms=1`). A fixed `NOW = datetime(2026, 11, 27, 10, 0, tzinfo=timezone.utc)`. Tests, with the assertions that matter:

```python
def test_rows_older_than_the_days_go_and_newer_ones_stay(db):
    old, edge_in, today = "2026-10-27T10:00:00.000+00:00", "2026-10-29T10:00:00.000+00:00", "2026-11-27T01:00:00.000+00:00"
    for t in (old, edge_in, today):
        add_call(db, t)
    assert prune_usage(db, 30, NOW) == 1 and remaining(db) == [edge_in, today]

@pytest.mark.parametrize("hour,minute", [(0, 0), (0, 5), (9, 30), (23, 59)])
def test_todays_rows_are_never_deleted_even_with_one_day_kept(db, hour, minute):
    now = NOW.replace(hour=hour, minute=minute)
    add_call(db, "2026-11-27T00:00:00.000+00:00"); add_call(db, "2026-11-25T08:00:00.000+00:00")
    prune_usage(db, 1, now)
    assert remaining(db) == ["2026-11-27T00:00:00.000+00:00"]

def test_zero_deletes_nothing(db): ...                 # a 2020 row is still there after prune_usage(db, 0, NOW) == 0
def test_the_allowance_count_is_unchanged(db): ...     # rows with created_at >= "2026-11-27T00:00:00" counted before and after are equal
@pytest.mark.parametrize("text,expected", [(None, 90), ("", 90), ("  ", 90), ("30", 30), (" 7 ", 7), ("0", 0), ("36500", 36500),
                                           ("-1", 0), ("abc", 0), ("1.5", 0), ("36501", 0)])
def test_the_setting_is_read_safely(text, expected, caplog): ...   # a warning is logged for the 0-by-mistake cases only
def test_run_if_due_runs_first_then_once_a_day(db): ...            # fake clock: delete, no-op the same hour, delete again after 24 h
def test_a_failing_clean_up_never_raises_and_waits_a_day(db, monkeypatch): ...  # monkeypatch retention.prune_usage to raise; run_if_due() == 0; not retried before 24 h
def test_a_build_start_triggers_the_clean_up(tmp_path): ...        # Builder(..., usage_keep_days=30) with MockProvider server model: builder.access.provider_for(LOCAL_USER_ID) removes the old row
def test_the_real_start_cleans_once(tmp_path, monkeypatch): ...   # SKILLFORGE_DATA_DIR + SKILLFORGE_USAGE_KEEP_DAYS=30, a 2020 row seeded through Database(): Builder.default(Library(...)) removes it; close the builder
```

- [ ] **Step 2: Run to see them fail**

Run: `python -m pytest -q tests/test_usage_retention.py`
Expected: FAIL (`ModuleNotFoundError: skillforge.builder.retention`).

- [ ] **Step 3: Implement** `builder/retention.py` per the rules above (a `delete(ModelCall).where(ModelCall.created_at < cutoff)` in one `db.session()`; `utc_now` imported from `.model_access`, so `retention.py` imports from `model_access` and `model_access` never imports `retention`), then the two wiring changes.

- [ ] **Step 4: Run, then the full suite**

Run: `python -m pytest -q tests/test_usage_retention.py` then `python -m pytest -q`
Expected: new tests pass; whole suite passes (3,786 passed / 4 skipped before this task, plus the new tests).

- [ ] **Step 5: Document and commit**

`.env.example`: `#SKILLFORGE_USAGE_KEEP_DAYS=90  # days of model-call records (counts and timings, never prompts) kept; 0 keeps them forever; today's are never deleted`. `docs/hosting.md` env table: the same row. `docs/database.md`: what is deleted, when (at start and at most once a day), and that the daily allowance reads only today's rows.

```bash
git add backend/skillforge/builder/retention.py backend/skillforge/builder/model_access.py backend/skillforge/builder/service.py backend/tests/test_usage_retention.py .env.example docs/hosting.md docs/database.md
git commit -m "Slice AK task 2c: usage rows older than 90 days are cleaned, today's never"
```

---

### Deliberate breaks (run after task C, restore each one)

Each must make at least one test fail; a break nothing catches means a weak test:

1. `_recently_used` always `False` → task A tests fail.
2. `_prune` skips the `ref == key_dir` check → the concurrency tests hang or fail.
3. `_prune` ignores the lock → `test_a_repository_whose_lock_is_held...` fails.
4. `git_env` returns `None` always → both ceiling tests fail.
5. `git_env` also returns a ceiling for a folder outside the data folder → `test_a_folder_the_person_points_at...` fails.
6. `prune_usage` uses `cutoff = now` (no keep window and no midnight floor) → the today's-rows test and the keep-window test fail.
7. `keep_days_from_env` returns `90` for garbage → the safe-reading test fails.
8. `run_if_due` without its try/except → the failing-clean-up test fails.

---

## Outcome (2026-11-27)

Built in commits `193a08e` (A), `6fe5e4b` (B), `2295297` (C) and `13c5199` (the review's fix). Backend: **3,821 passed / 4 skipped / 0 failed** (the 4 skips are symbolic-link tests this account cannot run); 34 new tests plus 1 for the review's finding.

**Deliberate breaks:** 12 run (the plan's 8 and 4 for the markers and wiring): 11 caught. The survivor, break 2 (dropping the `ref == key_dir` clause in `_prune`), is an equivalent change: the caller holds that lock and the next line tries it without waiting, which fails and skips, the same result the clause gives. The plan expected a hang; that expectation was wrong. The clause is kept because it states the intent. Also, the `min(..., midnight)` floor in `prune_usage` cannot be pinned by a test for `keep_days >= 1` (a day ago is always before today's midnight); it is belt and braces, and the today's-rows tests pin the behaviour.

**One independent review** (fresh context, most capable model): no Critical, 1 Important, 7 Minor.
- **Important, fixed test-first:** `_prune` asked "was this copy used lately?" before taking the repository's lock, so a request that opened the repository in that gap was handed a folder deleted a moment later. The question is now asked while the lock is held (`test_a_request_that_opens_a_repository_between_the_check_and_the_delete_is_not_cut_off`: it failed on the old code with `reused=True` and a missing folder).
- **Minor, deferred (not fixed):**
  1. Extra copies kept by the 15-minute grace are trimmed only when that same repository is downloaded again (the newest-two rule runs only on the repository being downloaded); the doc's "a little longer" understates it.
  2. A `used` marker with a time in the future counts as used for ever; `abs(now - opened) < USED_GRACE` would cap it.
  3. `UsageRetention.run_if_due` says it never raises, but `self.clock()` and `now - self._last` are outside its `try` (unreachable with `utc_now`).
  4. `docs/per-person-keys.md` line 31 and the slice AI text in `CLAUDE.md` say no code may delete usage rows; they should say "today's rows". README and `docs/roadmap.md` do not mention task 2 yet (due at the end of the batch).
  5. A kept build older than the keep period loses its "Model use while building" line (the page hides a zero); undocumented.
  6. `SKILLFORGE_USAGE_KEEP_DAYS` is read once at start; a change needs a restart.
  7. Tests do not pin real git with a path in capitals or with `..`, a non-UTC clock in `prune_usage`, or two threads calling `run_if_due` (the reviewer's probes confirmed all three behave).

**Rulings made while building:** working on `main` (as every slice did), not pushed; two more existing tests (`age_every_snapshot`, `test_asking_for_a_snapshot_that_is_gone...`) also had to age the new marker or step past the grace; of three identical full runs one showed 11 skips instead of 4 with no reason printed, the cause was not found (the other two showed exactly the 4 symbolic-link skips).
