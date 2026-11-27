# Completion batch, task 4: deleting a library entry, and erasing a person's data — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (a) A person, or the owner, can delete a skill, agent, plugin or MCP server from their own library, with every version and its backups, after typing its name. (b) The owner can erase a turned-off person's data, after typing their address, keeping the account row and every usage row.

**Architecture:** One shared helper, `library/remove.py::remove_tree`, deletes a file or folder without ever following a link and only strictly inside a given root. `Library.delete(name)` (task 1) hides the entry by a rename, then removes it and its backups. `DELETE /api/library/{name}?kind=&confirm=` (task 2) checks the typed name on the server. `builder/erase.py::erase_person` (task 3) deletes a person's rows in one transaction (after emptying `model_calls.session_id`, so the cascade cannot reach the usage rows) and then their folders; `POST /api/admin/people/{id}/erase` checks the typed address on the server. The web pages (task 4) only collect the typed text and show the words; the server decides.

**Tech Stack:** Python, FastAPI, SQLAlchemy, pytest; Next.js, TypeScript, vitest. No new library.

**Spec:** [docs/superpowers/specs/2026-11-26-completion-batch-design.md](../specs/2026-11-26-completion-batch-design.md), item 4 (task 4 of its task list), including its Anti-goals and Review focus 1 and 2.

## Global Constraints

- Run from `backend/` with `C:\dev\venvs\aiskills\Scripts\python.exe -m pytest -q -p no:cacheprovider`; web from `frontend/` (`npm test`, `npm run typecheck`). Tests offline. No new library.
- **Irreversible, so strict.** A path is built only from a name the library checked (`SLUG`, at most `MAX_NAME` characters) or an id this server made (32 hex characters), never from anything else; no link or junction is ever followed (a link inside what is deleted is refused, and the target is never touched); everything stays strictly inside the root it belongs to.
- **The server enforces the typed confirmation**; the page only helps. A request without the right typed text is refused with a 400, whatever page sent it.
- **Nothing is deleted while that person has work running** (a build, a Testing Lab run or a suggestion run).
- **The usage rows (`model_calls`) are the allowance's ledger: erase keeps every one**, including those of the builds it deletes (a bulk delete of sessions would cascade-delete them: empty their `session_id` first, as `Builder.discard` does).
- **Messages never contain an absolute path.** What could not be removed is reported honestly, never hidden.
- Only GET, POST and DELETE exist in the API's CORS policy: delete uses DELETE, erase uses POST.
- Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

1. A name that is odd (`Foo`, `..`, `a/b`, `a\b`, `foo..`, 65 characters, empty, not text) deletes nothing; `foo` never deletes `foo-bar`'s files or backups; another kind's `foo` and another person's `foo` are untouched.
2. A link or junction inside an entry, or the entry itself being one, is refused and its target is never touched.
3. Erase keeps every usage row (those of the erased builds too, despite the foreign-key cascade) and the account row (still turned off).
4. Delete and erase are refused while that person has anything working; erase is refused for a person who is not turned off, for the owner, and for an unknown or malformed id.
5. A person can only delete from their own library, and a script that omits the typed name or address is refused by the server.

---

### Task 1: The safe removal helper and `Library.delete`

**Files:**
- Create: `backend/skillforge/library/remove.py`
- Modify: `backend/skillforge/library/store.py` (`Library.delete`, `DeleteReport`), `backend/skillforge/library/__init__.py` (export `DeleteReport`)
- Create: `backend/tests/test_library_delete.py`

**Interfaces:**
- Produces: `remove_tree(path: Path, inside: Path, *, allow_inner_links: bool = False) -> bool` in `library/remove.py` — removes `path` (file or folder); refuses with `LibraryError` when `path` itself is a symlink or junction, or its real path is not strictly inside the real path of `inside`, or (unless `allow_inner_links`) it contains a link; never follows a link (a link inside is removed as a link, the target untouched); returns True when nothing of it is left. `has_link(path: Path) -> bool` (itself or anything below). A missing `path` returns True. Library entries are removed with the default (a link inside one is tampering: refused); backups with `allow_inner_links=True` (`install_skill` copies a replaced folder with its links, so a real backup may hold some).
- Produces: `DeleteReport(name: str, versions: int, backups: int, leftover: bool)` and `Library.delete(self, name: str) -> DeleteReport`: validates the name with `_skill_dir` (so a bad name raises `LibraryError` before any path is joined); holds `_ADD_LOCK`; `NotFound` when absent; counts versions by folder name `v<N>` (a damaged manifest must not stop a delete); refuses a link as above; renames the entry to `<root>/.deleting-<32 hex>` (a `PermissionError` becomes `LibraryError`, "in use by another program, nothing was deleted", and the entry is intact); removes it with `remove_tree`; removes the backups of that name from `self.backups` — an entry matches only `<name>-<8 digits>-<6 digits>` followed by an optional `-<1 to 3 digits>` and an optional `.<extension>` (the form `library/service.py` writes), so `foo` never matches `foo-bar-…` (a backup that is itself a link is left alone and sets `leftover`); first sweeps stale `.deleting-*` folders of an earlier delete. `leftover` is True when anything could not be removed (it is then already out of the library: `names()` never shows a dotted folder).

- [ ] **Step 1: Write the failing tests** in `tests/test_library_delete.py` (build a library with `Library(tmp_path / "library")` and `import_skill`/`add` as `tests/test_library.py` does; a `make_link(link, target)` helper that tries `os.symlink`, then on Windows `cmd /c mklink /J`, else `pytest.skip("this account cannot create symbolic links")`; a `tree(path)` helper listing every file and folder). Tests:

```python
def test_delete_removes_every_version_and_only_that_entry():          # report.versions == 3; names() has no foo; bar and its files unchanged
@pytest.mark.parametrize("name", ["", ".", "..", "../x", "a/b", "a\\b", "Foo", "FOO", "foo bar", "foo..", "x" * 65, "foo\x00", None, 5])
def test_an_odd_name_deletes_nothing(tmp_path, name):                # raises LibraryError; tree(tmp_path) identical before and after
def test_a_missing_entry_is_not_found():                              # NotFound
def test_a_link_inside_an_entry_is_refused_and_the_target_untouched():    # the target folder outside keeps its files; the entry is still listed
def test_an_entry_that_is_itself_a_link_is_refused_and_the_target_untouched():
def test_only_the_backups_of_that_name_go(tmp_path):
    # backups dir holds: foo-20261127-101500 (dir), foo-20261127-101500-2 (dir), foo-20261127-101500.md (file),
    #                    foo-bar-20261127-101500, foo-2-20261127-101500, foo-notastamp, other-20261127-101500
    # after delete("foo"): the first three are gone (report.backups == 3, leftover False), the other four remain
def test_a_backup_folder_holding_a_link_is_removed_without_touching_the_target():   # the link inside goes as a link; the outside folder keeps its files
def test_a_backup_that_is_itself_a_link_is_left_alone_and_reported():               # target intact; report.leftover True; the real backups still go
def test_another_kind_and_another_person_are_untouched():              # agent library `foo` + backups-agent; users/<hex>/library `foo`
def test_a_delete_waits_for_a_writer_holding_the_library_lock():       # hold store._ADD_LOCK in a thread: delete has not finished until it is released
def test_an_entry_with_a_damaged_manifest_can_still_be_deleted():
def test_a_delete_that_cannot_rename_deletes_nothing(monkeypatch):     # Path.rename raises PermissionError -> LibraryError, entry intact
def test_what_could_not_be_removed_is_reported_and_already_out_of_the_library(monkeypatch):   # shutil.rmtree in library.remove does nothing -> leftover True, names() excludes it
def test_a_stale_hidden_folder_is_swept_by_the_next_delete():
def test_remove_tree_refuses_a_path_outside_its_root(tmp_path):         # remove_tree(tmp/x, inside=tmp/root) -> LibraryError and tmp/x intact
```

- [ ] **Step 2: Run to see them fail** — `pytest -q -p no:cacheprovider tests/test_library_delete.py`. Expected: FAIL (`ModuleNotFoundError: skillforge.library.remove`).
- [ ] **Step 3: Implement** `remove.py` and `Library.delete` as the Interfaces say. `remove_tree` checks links with `is_symlink()` and `os.path.isjunction` (via `getattr`, absent before Python 3.12 means "no"), walks with `os.walk(followlinks=False)`, and deletes with `shutil.rmtree` (which removes a link without following it); success is `not path.exists()` afterwards.
- [ ] **Step 4: Run** `tests/test_library_delete.py tests/test_library.py`. Expected: all pass.
- [ ] **Step 5: Commit** `Slice AK task 4a: Library.delete removes an entry, its versions and its backups, never following a link`.

---

### Task 2: `DELETE /api/library/{name}` and `Builder.working_for`

**Files:**
- Modify: `backend/skillforge/api/app.py` (the route, after `/library/{name}`), `backend/skillforge/builder/service.py` (`Builder.working_for`)
- Create: `backend/tests/test_library_delete_api.py`

**Interfaces:**
- Consumes: `Library.delete` from task 1.
- Produces: `Builder.working_for(self, user_id: str) -> int` — how many builds, Testing Lab runs and suggestion runs of this person have status `working` (used by tasks 2 and 3; slice AK's task 5 adds scan runs to it).
- Produces: `DELETE /api/library/{name}?kind=<kind>&confirm=<name>` → `{"deleted": true, "name", "kind", "versions", "backups", "leftover"}`. The person is `user_id(request)`; the library is `library_for` (that person's own; the owner's for the owner). `confirm` must equal `name` exactly, else **400** `"Type the name to confirm: nothing was deleted."`; `working_for(person) > 0` → **409** (`Conflict`) `"You have work running. Wait for it to finish, then delete."`; unknown kind → 400 (existing `kind_of`); missing → 404; odd name → 400.

- [ ] **Step 1: Write the failing tests** (`tests/test_library_delete_api.py`, using the hosted-with-people helpers `tests/test_accounts_isolation.py` uses, and a plain local server for the owner):

```python
def test_the_owner_deletes_with_the_typed_name_and_the_answer_counts_what_went():
def test_no_confirm_or_a_different_one_is_refused_and_nothing_is_deleted(confirm): # parametrize: omitted, "", "FOO", "foo ", "bar"; 400; entry intact
def test_a_person_deletes_only_from_their_own_library():       # same name in the owner's, person A's and person B's libraries; A deletes; the other two remain
def test_another_person_cannot_reach_it_by_any_name():         # B deleting a name only A has: 404 identical to a name nobody has
def test_every_kind_can_be_deleted():                           # skill, agent, plugin, mcp, mcp-node: ?kind= routes to that kind's library only
def test_delete_is_refused_while_the_person_has_work_running(): # a working BuildSession row -> 409, nothing deleted; another person's working row does not block
def test_an_odd_name_or_an_unknown_kind_is_a_400_and_deletes_nothing():
def test_working_for_counts_builds_lab_runs_and_suggestion_runs_of_that_person_only():
```

- [ ] **Step 2: Run to see them fail.** Expected: 405 or 404 on DELETE; `AttributeError: working_for`.
- [ ] **Step 3: Implement** the route and `working_for`.
- [ ] **Step 4: Run** the new file and `tests/test_api.py tests/test_builder.py`. Expected: pass.
- [ ] **Step 5: Commit** `Slice AK task 4b: DELETE /api/library/{name} with the typed name checked by the server`.

---

### Task 3: Erasing a person's data

**Files:**
- Create: `backend/skillforge/builder/erase.py`
- Modify: `backend/skillforge/api/admin.py` (the route, `EraseBody`)
- Create: `backend/tests/test_erase_person.py`

**Interfaces:**
- Consumes: `Builder.working_for` (task 2), `remove_tree` (task 1), `UserStore.get`, `Builder.library_for`, `Builder.builds_root`, `UserModelRow`.
- Produces: `EraseReport(builds: int, suggestion_runs: int, lab_runs: int, key_removed: bool, files_left: bool)` and `erase_person(builder: Builder, user_id: str) -> EraseReport`: refuses (`WrongState`, 409) when the person is not turned off (`"Turn this person off first: erasing is only for an account that is off."`) or `builder.working_for(user_id) > 0` (`"... has work running..."`); `BadRequest` (400) for the owner or an id that is not 32 hex characters. In ONE transaction: collect the person's build ids; `update(ModelCall).where(ModelCall.session_id.in_(ids)).values(session_id=None)`; delete their `Job`, `BuildSession`, `SuggestRun`, `EvalRun` and `UserModelRow` rows. **Kept: the `users` row and every `model_calls` row.** After the commit, remove `builds_root/<id>` for each collected id and the person's folder (`builder.library_for(user_id).root.parent`, which must be named exactly the id, inside the users folder), with `remove_tree`; `files_left` is True if anything remains. Idempotent: a second erase deletes nothing and succeeds.
- Produces: `POST /api/admin/people/{who}/erase` with body `{"confirm": "<their address>"}`: owner only and hosted (the existing `person_store` guard); the typed address must equal the person's email ignoring case and surrounding spaces, else **400** `"Type the person's address to confirm: nothing was erased."`; answers `{"erased": true, builds, suggestion_runs, lab_runs, key_removed, files_left}`.

- [ ] **Step 1: Write the failing tests** (`tests/test_erase_person.py`, hosted env with the owner and two people, A and B, each with a library entry, a finished build with a folder, a suggestion run, a Testing Lab run and a saved model key; usage rows for both, including rows whose `session_id` is one of A's builds):

```python
def test_erasing_removes_the_persons_folder_builds_runs_and_key_and_nothing_of_anybody_elses():
def test_every_usage_row_survives_including_those_of_the_erased_builds():   # count before == after, ids unchanged; session_id of A's rows is now NULL
def test_the_account_row_stays_and_the_person_is_still_turned_off():          # users row present, blocked True; after unblock they start empty
def test_a_person_who_is_not_turned_off_is_refused_409_and_nothing_is_touched():
def test_a_person_with_work_running_is_refused_409(): # working build / eval run / suggestion run each
def test_a_wrong_or_missing_confirmation_is_refused_400_and_nothing_is_touched(confirm):   # omitted, "", another person's address, "a@b" ; case and spaces around the right address are accepted
def test_the_owner_an_unknown_id_and_a_malformed_id_cannot_be_erased(who):    # "local", 32 hex that does not exist, "../x", "zz", 31 and 33 characters
def test_only_the_owner_may_erase():                                          # a signed-in person gets 403 for their own and another's id; the local server says it has no accounts
def test_erasing_twice_is_harmless():
def test_a_folder_that_cannot_be_removed_is_reported(monkeypatch):            # files_left True; the rows are still gone
def test_a_link_inside_the_persons_folder_is_not_followed():                   # the outside target keeps its files; files_left True
def test_the_response_and_errors_never_contain_a_path():
```

- [ ] **Step 2: Run to see them fail.** Expected: 404 on the route; `ModuleNotFoundError: skillforge.builder.erase`.
- [ ] **Step 3: Implement** `erase.py` and the route.
- [ ] **Step 4: Run** the new file and `tests/test_admin_block.py tests/test_person_limits.py tests/test_accounts_isolation.py`. Expected: pass.
- [ ] **Step 5: Commit** `Slice AK task 4c: the owner can erase a turned-off person's data, keeping the account and every usage row`.

---

### Task 4: The web pages

**Files:**
- Create: `frontend/src/lib/remove.ts`, `frontend/src/lib/remove.test.ts`
- Modify: `frontend/src/lib/api.ts` (`deleteEntry`, `erasePerson`), `frontend/src/lib/types.ts` (`DeleteReport`, `EraseReport`), `frontend/src/lib/admin.ts` + `admin.test.ts`, `frontend/src/app/library/[name]/page.tsx` (a **Danger zone** card), `frontend/src/app/admin/page.tsx` (an **Erase their data…** dialog)

**Interfaces:**
- Produces in `lib/remove.ts`: `typedName(typed: string, name: string): boolean` (exact, after trimming the typed text; never true for an empty name); `typedEmail(typed: string, email: string): boolean` (ignoring case, trimmed; never true for an empty email); `deleteWords(kindLabel: string, versions: number): string[]` (the lines the dialog shows: every version, the backups made when installing over an existing copy, **cannot be undone**, plugins already built keep their own copies, folders it was installed into are not touched); `deletedNotice(r: DeleteReport, name: string): string`; `eraseWords(): { removes: string[]; keeps: string[] }`; `erasedNotice(r: EraseReport): string` (says plainly when `files_left`).
- `api.deleteEntry(name: string, confirm: string, kind?: string): Promise<DeleteReport>` — `DELETE /api/library/<name>?[kind=…&]confirm=<confirm>`; `api.erasePerson(id: string, confirm: string): Promise<EraseReport>` — `POST /api/admin/people/<id>/erase` with `{confirm}`.
- `lib/admin.ts`: `eraseBlockedReason(p: AdminPerson): string | null` — null only when `p.blocked` and `p.active === 0`; otherwise the words ("Turn this account off first." / "Wait for their running work to finish.").
- UI: the Danger zone card on the version page has a button that opens a modal (existing `Modal`) with `deleteWords`, a text box labelled with the name, and a danger button disabled until `typedName`; on success it goes to the library page with the notice. The People page shows **Erase their data…** only for a turned-off person (disabled with `eraseBlockedReason` words when they have work running), a modal with `eraseWords`, a text box for their address, a danger button disabled until `typedEmail`; on success it reloads the list and shows the notice. Buttons are at least `min-h-11` (phone-size touch targets, as the other People buttons).

- [ ] **Step 1: Write the failing tests** (`remove.test.ts`, `admin.test.ts`, plus the api tests beside the existing `api` tests with the repo's `reply`/`vi.fn` fetch helper): `typedName` exact/trim/empty, `typedEmail` case/trim/empty, `deleteWords` mentions "cannot be undone" and plugins and installed folders, `erasedNotice` with and without `files_left`, `eraseBlockedReason` for not-off, running, and ready; `api.deleteEntry` sends `DELETE` with `confirm` and `kind` URL-encoded and raises the server's message on a 400/409; `api.erasePerson` sends `POST` with the body.
- [ ] **Step 2: Run to see them fail** — `npm test -- remove admin`. Expected: FAIL (missing module/functions).
- [ ] **Step 3: Implement** the logic first (it is what the tests pin), then the two pieces of UI.
- [ ] **Step 4: Run** `npm test` and `npm run typecheck`. Expected: all pass, no type errors.
- [ ] **Step 5: Commit** `Slice AK task 4d: the Danger zone on a library entry and Erase on the People page`.

---

### Task 5: Docs and the batch's own checks

**Files:** Create `docs/data-removal.md`; modify `docs/api.md`, `docs/person-limits.md`, `docs/library.md`, `docs/ui.md`.

- [ ] **Step 1:** `docs/data-removal.md` (what each delete touches and does not touch, the confirmations, what erase keeps and why, what is reported when something could not be removed, the cascade trap, what is NOT covered: another copy of the files someone exported or installed, scan runs until slice AK's task 5 adds them to `erase_person` and `working_for`). One-line additions in the other four docs.
- [ ] **Step 2:** Run the whole backend suite with `-rs` and the web unit tests and typecheck; expected: all pass, the same 4 symbolic-link skips (this machine can make junctions, so the link tests run here with junctions).
- [ ] **Step 3: Commit** `Slice AK task 4e: docs for deleting and erasing`.

---

### Deliberate breaks (after task 3; restore each)

1. `Library.delete` skips the name check → the odd-name test fails.
2. The backup match becomes a prefix (`startswith(name + "-")`) → `foo-bar`'s backups are deleted, the only-that-name test fails.
3. `remove_tree` drops the link check → the link tests fail.
4. `remove_tree` drops the "strictly inside" check → the outside-root test fails.
5. `Library.delete` drops `_ADD_LOCK` → the lock test fails.
6. The route drops the `confirm` check → the no-confirm test fails.
7. The route stops using `working_for` → the work-running test fails.
8. `erase_person` does not empty `session_id` before deleting sessions → the usage-rows test fails (the cascade).
9. `erase_person` deletes the `users` row → the account-row test fails.
10. `erase_person` skips the "turned off" check → the 409 test fails.
11. `erase_person` forgets `SuggestRun` rows → the removal test fails.
12. The erase route skips the confirm check → the wrong-confirmation test fails.
13. `erase_person` removes `builds_root` itself instead of one session's folder (a path built wrongly) → the nobody-else's test fails.

### After the tasks

One independent review of this task (irreversible deletes, as the design says): read the plan's Review Focus and the break results first.
