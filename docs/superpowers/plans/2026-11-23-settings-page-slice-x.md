# Slice X: the Settings page (plan)

Written 2026-11-23. Until now a model, its key and its limits could only be set by editing the git-ignored `.env` by hand, and the
server read that file once (a later edit needed a restart). The web UI showed only a one-line "Model" status. This slice adds a
**Settings** page: see what is set (never a key), change it, and test it. It is the "Settings" part of the old H5.

## Calls I made (to be corrected if wrong)

| Question | Call | Why |
|---|---|---|
| Write a key into `.env`, or only show how? (the open question in `ui-and-database-plan.md`) | **Write it**, with the safeguards below | a page that only says "edit the file" is no easier than today; the plan said this would be asked when reached, and I answered it from what I told you the page is for |
| Which names can the page change? | A fixed allow-list in code (`settings/catalogue.py`): the provider, the model, one key per provider, the custom address, backup models, a model for one kind of work, the escalation model, four limits, the cache switch | the page must never become a way to write any line into any file. Hosted-mode names (`SKILLFORGE_MODE`, the access token) are not on it |
| Is a key ever sent back? | **Never.** Not the value, not the end of it, not its length. The page learns only "set" or "not set" and where it comes from | the key must not reach the browser, the logs or an error message |
| Values | One line, a short list of safe characters, a length limit, no hidden or direction-changing characters; a value outside it is refused with the field named and the value never repeated | `.env` has quoting rules; refusing odd characters is simpler and safer than getting quoting wrong. A key with an unusual character can still be put in `.env` by hand |
| A setting that comes from the computer's own environment | Shown as "set outside .env", read-only | real environment variables win over the file, so a save would silently not apply after a restart |
| When does a change apply? | At once, with no restart: the server re-reads `.env` on each model lookup, and a save updates the running process | removes the "first load wins" trap listed as a non-goal in `ai-engine.md` |
| The file | Written atomically (a temp file in the same folder, then a replace), other lines and comments kept, the file's own line endings kept, the file created if missing (owner-only on Linux and macOS) | a half-written `.env` would lose every key |
| Hosted version | **All settings routes are 403**; the page says so | writing into a server's file is the same risk as installing into a server folder |
| Cross-site | Already covered by the API's origin check; the new POST adds no new door. A body over 20 KB is refused; the body is parsed by hand so no error can repeat a secret | |
| Testing a key | The existing `POST /api/provider/check` (one tiny call per model). The page just uses it | it already never returns a key |
| In tests | The file and the "environment" are passed in; a test never reads the real `.env` or the real environment | CLAUDE.md rule |
| Not in this slice | Per-tier timeouts and output limits, `SKILLFORGE_DATA_DIR` and the other server options, choosing the Docker/sandbox settings, model lists fetched from a provider (models retire while still listed: test with a real call), the hosted version's own settings | said plainly at the end |

## Steps (tests first)

1. Backend `skillforge/settings/`: the catalogue, a safe `.env` reader and writer, `EnvSettings` (view, apply, re-sync).
2. Backend: `GET /api/settings`, `POST /api/settings`; `env_provider` re-reads the file; hosted 403.
3. Frontend: types and client, `lib/settings.ts` (pure helpers, unit tests), the Settings page, the menu.
4. Real browser: the page against the real API with a temporary `.env` and the scripted fake model.
5. Real run: change and test a setting against a copy of the real `.env`.
6. Docs, README, roadmap, memory; one independent review; commit and push.
