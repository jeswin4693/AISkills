# Database

What changes while you work lives in a database: **builder sessions** (the conversation, the requirement waiting
for approval, the result) and the **jobs** that serve them. The skill library does **not**: it stays as files with
SHA-256 manifests ([library.md](library.md)), so a file edited behind its back is noticed.

## Where and how

| | |
|---|---|
| Default | SQLite, one file: `%LOCALAPPDATA%\skillforge\skillforge.db` (the per-user data folder, never inside a repository or OneDrive). `SKILLFORGE_DATA_DIR` moves it. |
| Another database | Set `SKILLFORGE_DATABASE_URL` to any SQLAlchemy URL, for example `postgresql+psycopg://user:pass@host/db` (install that driver yourself). Nothing else changes. Only SQLite has been run so far. |
| Schema | **Alembic migrations** in `backend/skillforge/db/migrations/`, run when the server starts (`serve`) or the builder is first used. Never `create_all`, so the schema has one history. A test proves the migration creates exactly what the models describe. |
| SQLite settings | Foreign keys on (a deleted session removes its jobs), WAL mode (readers do not block the writer), a 5 second wait on a short lock. |

## Tables

`build_sessions`: id (random 32-hex, also its folder name), status, what the person typed and all of it so far,
the round, the questions being asked, the requirement spec, the result summary (checks, file list, `report.md`
text), the error and whether a retry can help, model calls, notes, and the library name and version once saved.

Migration 0003 added `kind` (a key of the kind registry; `skill` by default, so every earlier session is a skill) and `parent_id`
(for a plugin's child builds, later; no foreign key, because SQLite cannot add one to an existing table). A session whose kind is no
longer registered can still be read, listed and discarded.

`jobs`: a sequence id (a higher id is a later job), the session, kind (`understand` or `build`), status
(`queued`, `running`, `succeeded`, `failed`), times, the progress events the UI shows, and the error.

`model_calls` (migration 0002): one row per **attempt** at a model for a session: the session and job, the task
(`extract`, `select`, `design`, `suggest`, `code`, `act`), the tier, provider and model, the attempt number, ok or
error and the error kind, the input and output tokens as the provider reported them (null when it gave none) and the
time taken. **Never any prompt or reply text.** Deleting a session deletes its rows. See [ai-engine.md](ai-engine.md).

`eval_runs` (migration 0005, [testing-lab.md](testing-lab.md)): one row per Testing Lab run: the kind, skill name and **version** it tested with that
version's content hash (a newer version later does not change what a run is about), how many times each case was repeated, whether the same cases were also run
without the skill, how many cases there are and how many are done (the progress the page polls), the result as plain data (the outcome as a code, the counts,
every case with its replies and checks; replies cut at 3,000 characters), the error and whether a retry can help. Not tied to a builder session, so deleting a
session never touches it. A run that was `working` when the server stopped is marked failed and retryable at the next start.

Generated files of a session are in `<data folder>\builds\<session id>\<skill name>\` until the session is
discarded; **saving** copies a checked version into the library.

## Changing the schema

The migrations are configured in code (`Database.migrate`), and there is no `alembic.ini`, so there is no ready-made
`alembic revision` command. To change a table: edit `models.py`, then add a file next to
`versions/0001_build_sessions_and_jobs.py` with the next revision id and `down_revision`, written with
`op.batch_alter_table` (SQLite cannot alter a table in place). The test
`test_the_migration_creates_exactly_what_the_models_describe_and_is_safe_to_repeat` fails if the models and the
migrations drift apart (and lists the tables it expects, so it changes when a table is added). Two migrations exist now.
`0002_model_calls.py` only creates a table, so the in-place alteration of an existing table (`batch_alter_table`) has
still not been tried.

## Limits

- Sessions hold what the person typed, which can be private. The file is only as private as your user account.
- No sign-in and one writer at a time (SQLite). A shared, hosted version would need PostgreSQL and real accounts.
- Not tried on PostgreSQL.
- Sessions are kept until discarded; there is no automatic clean-up yet.
