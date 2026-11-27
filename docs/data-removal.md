# Deleting and erasing (slice AK, task 4)

Two acts that **cannot be undone**, so they are strict, small and checked by the server:

1. **Delete a library entry**: a skill, an agent, a plugin or an MCP server, with every version and its backups. A person does it to their own library; the owner to the owner's.
2. **Erase a person's data**: the owner's act, for an account that is already turned off ([person-limits.md](person-limits.md)).

Plan and review notes: [the plan](superpowers/plans/2026-11-27-completion-batch-task-4.md); design: [the batch design](superpowers/specs/2026-11-26-completion-batch-design.md), item 4.

## Delete a library entry

On the entry's page, at the bottom: **Danger zone** → *Delete this skill…* (or agent, plugin, MCP server). The dialog says what goes, says it cannot be undone and asks for the **name typed**.

`DELETE /api/library/{name}?kind=<kind>&confirm=<name>`: answers `{"deleted": true, "name", "kind", "versions", "backups", "leftover"}`.

| | |
|---|---|
| **Goes** | every version of that entry (`<library>/<name>/v1…`), and the backups of that exact name in the library's backups folder (the copies made when an install with `--force` replaced a folder or file of that name). |
| **Stays** | other entries and kinds; another person's library; **plugins you already built** (a plugin holds its own copies); **folders you installed it into** (those are your own copies and are not touched); exports you made. |
| **Refused** | no `confirm`, or one that is not exactly the name (400, nothing deleted); the name is odd (not lowercase letters, digits and hyphens, or too long) (400); no such entry (404, the same text whoever asks); **work running** for that person (409): a plugin build reads the library while it works; an entry that is, or holds, a link (400). |

How it is kept safe (`library/remove.py`, `Library.delete`):

* **The name is checked first** with the library's own rule, so `..`, `a/b`, `a\b`, capitals and a 65-character name never reach a path.
* **Only that exact name's backups** go. A backup is named `<name>-<date>-<time>` (then `-2`, `-3`… when taken, then an extension for one file); the **whole shape** is matched, never "starts with the name", so deleting `foo` cannot reach the backups of `foo-bar`.
* **No link is followed.** An entry that is a symbolic link or a Windows junction, or holds one, is refused and its target is never touched (nothing here writes a link, so one means someone changed the folder). A backup that is itself a link is left alone and reported; a real backup of a folder that had links in it is removed as a copy, links removed as links.
* **Out of the library in one step.** The entry is renamed to a hidden name first. If the rename is refused (a virus scanner holding a file, say) nothing was deleted. What cannot then be removed is reported as `leftover` ("some files could not be removed from the disk") and swept by the next delete.
* **One writer at a time**: delete holds the same lock as saving, so a save and a delete of one name never interleave.
* **The server checks the typed name**, not the page: a script without it gets a 400.

## Erase a person's data

On the **People** page, for a turned-off person: *Erase their data…*. The dialog says what goes, what stays, that it cannot be undone, and asks for **their address typed**.

`POST /api/admin/people/{id}/erase` with `{"confirm": "<their address>"}` (owner only; only GET, POST and DELETE exist in the CORS policy): answers `{"erased": true, "builds", "suggestion_runs", "lab_runs", "key_removed", "files_left"}`.

| | |
|---|---|
| **Goes** | their folder (`<data>/users/<id>`: their library of every kind and its backups); their builds (rows, jobs and `<data>/builds/<id>` folders); their suggestion runs and Testing Lab runs; their saved model key. |
| **Stays, on purpose** | **the account**: the person is still turned off, and if the owner turns them back on they start empty. **Every usage row** (`model_calls`, counts and timings only): a person's daily allowance on the server's model is counted from them, so erasing them would let a person erase themselves and start again with a fresh allowance. |
| **Refused** | the person is not turned off (409); they have work running, a build, a Testing Lab run or a suggestion run (409); no or wrong address (400; the address is compared ignoring case and surrounding spaces); the owner (400); an unknown or malformed id (404); anyone but the owner (403); a local server, which has no accounts (400). |

The trap this avoids: `model_calls.session_id` is a foreign key that **cascades** from a build, so deleting a person's builds in one go would have deleted their usage rows (the same bug the review of slice AI found for *Discard*). Erase first empties those `session_id`s, and a test counts the usage rows before and after.

* One database transaction removes the rows; the files follow once it has committed. A disk that will not give a file up does not undo the rows: it is reported (`files_left`), and the files no longer belong to anything.
* A link inside the person's folder is removed as a link and never followed; their folder being itself a link is left alone and reported. Every folder is named by an id this server made (32 hex characters), checked, and removed only from strictly inside the folder it belongs to.
* Erasing twice is harmless.
* The People page's disk number is measured again straight after.

## What is not covered

* **Copies that left the server**: an export someone downloaded, a skill installed on their own computer.
* **Scan runs** (the behaviour scan's web page, slice AK's next task) are not stored yet; when they are, they are added to both `Builder.working_for` and `erase_person`.
* **A request that was already running** when the person was turned off finishes first: erase waits for `working_for(person) == 0`. A request that passed the sign-in check in the very moment of turning off could still start work; erasing again removes it.
* There is **no command-line delete** yet (the CLI's `library` commands only add and read).
* The two dialogs have been run through the unit tests and the type check; **the browser suite runs in the batch's last task**.

## Code and tests

`library/remove.py` (`remove_tree`, `has_link`), `library/store.py` (`Library.delete`), `api/app.py` (the delete route), `builder/service.py` (`Builder.working_for`), `builder/erase.py`, `api/admin.py` (the erase route), `builder/limits.py` (`PersonSpace.forget`); web: `lib/remove.ts`, `components/DeleteEntry.tsx`, `components/EraseDialog.tsx`.
Tests: `tests/test_library_delete.py`, `tests/test_library_delete_api.py`, `tests/test_erase_person.py`, `frontend/src/lib/remove.test.ts`. The link tests use a symbolic link where the account may make one and a Windows junction otherwise, so they run on a machine that cannot make symbolic links.

## What was verified

Backend **3,917 passed / 4 skipped** (the 4 are symbolic-link tests this account cannot run; this task's own link tests ran, with junctions) and 71 of them are new; web **440 passed** (16 new) with a clean type check; **15 deliberate breaks, all caught** (among them: matching backups by prefix, dropping the typed-name check on either route, dropping the check for work running, and leaving out the step that keeps the usage rows through the foreign-key cascade). Not yet run: the two dialogs in a real browser (the batch's last task).
