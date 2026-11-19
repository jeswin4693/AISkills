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

`jobs`: a sequence id (a higher id is a later job), the session, kind (`understand` or `build`), status
(`queued`, `running`, `succeeded`, `failed`), times, the progress events the UI shows, and the error.

Generated files of a session are in `<data folder>\builds\<session id>\<skill name>\` until the session is
discarded; **saving** copies a checked version into the library.

## Changing the schema

The migrations are configured in code (`Database.migrate`), and there is no `alembic.ini`, so there is no ready-made
`alembic revision` command. To change a table: edit `models.py`, then add a file next to
`versions/0001_build_sessions_and_jobs.py` with the next revision id and `down_revision`, written with
`op.batch_alter_table` (SQLite cannot alter a table in place). The test
`test_the_migration_creates_exactly_what_the_models_describe_and_is_safe_to_repeat` fails if the models and the
migrations drift apart. Only the first migration exists so far, so adding a second has not been tried yet.

## Limits

- Sessions hold what the person typed, which can be private. The file is only as private as your user account.
- No sign-in and one writer at a time (SQLite). A shared, hosted version would need PostgreSQL and real accounts.
- Not tried on PostgreSQL.
- Sessions are kept until discarded; there is no automatic clean-up yet.
