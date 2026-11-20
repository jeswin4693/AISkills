# Local HTTP API

The web UI (see [ui-and-database-plan.md](ui-and-database-plan.md)) talks to this API. It calls the same tested code
as the command line and adds no behaviour of its own. Interactive docs are served at `/api/docs`.

```powershell
cd backend
python -m skillforge serve              # http://127.0.0.1:8000/api/docs ; --port N to change it
```

## Endpoints (step H1)

| Method and path | What it does |
|---|---|
| `GET /api/health` | `{"status": "ok", "version": ..., "mode": "local" or "hosted"}`. Always public: a host can use it as its health check. |
| `GET /api/auth/status` | `{"required", "authenticated"}`. Local mode: `{false, true}`. The hosted version asks for a sign-in ([hosting.md](hosting.md)). |
| `POST /api/auth/login` | `{"token"}` sets the session cookie (hosted only; local mode answers 400). **401** wrong token, **429** after five wrong tries (locked for a minute, with `Retry-After`). |
| `POST /api/auth/logout` | Ends the session. |
| `POST /api/provider/check` | One tiny call to each distinct model that is set up, so each key and model is shown to really work: `{"configured", "detail", "checks": [{provider, model, roles, ok, kind, detail, latency_ms, input_tokens, output_tokens}]}`. It uses a little quota, so it runs only when asked. Never a key. |
| `GET /api/sandbox` | Is a Linux sandbox available here, and why or why not. |
| `GET /api/languages` | Every language with its level, grammar status and extensions. Never downloads a grammar. |
| `GET /api/kinds` | What the app builds: each kind's `key`, `label`, `install_targets` and checklist `slots` (`key`, `label`, `question`). `skill`, `agent`, `plugin` and `mcp`; also `definition_file` (`SKILL.md`, `AGENT.md`, `.claude-plugin/plugin.json`, `server.py`), `personal_label` (such as `~/.claude/agents`) `installs_as_file` and `conversational` (false for a plugin, which is composed, not described). |
| `POST /api/plugins/preview` | `{"name", "description", "author", "components": [{"kind": "skill" or "agent", "name", "version"}]}`. The files a plugin of those skills and agents would hold, what it can do on the machine (`capabilities`), every check and the version it would get. **Keeps nothing.** No model is used. 400 for a bad or reserved name, 404 for a component that is not in the library. |
| `POST /api/plugins` | The same body. Keeps the plugin as the next version in `library-plugin` through the checked import (422 and nothing kept when a check fails). Keeping the same plugin again makes no second version. |
| `POST /api/validate` | Body: a `.zip`. Runs every static check. Stores nothing, runs nothing. |
| `GET /api/library` | The skills, each with its version count and latest version. |
| `POST /api/library/import` | Body: a `.zip` (`?filename=`, `?note=`, `?test_scripts=true`). **200** when kept (or identical to the latest, `created: false`); **422** when a check failed, with the checks, and nothing is stored. `test_scripts` runs the skill's cases in the sandbox and the request waits for them. The answer has a `risk` object (as in `diff`) when it added a version after another, and `null` otherwise. |
| `GET /api/library/{name}` | Every version, newest first, with checks and file hashes. |
| `GET /api/library/{name}/diff` | `?frm=N&to=M`; default is the latest against the one before. Returns the file `changes` and a `risk` object: `level` (`more_risk`, `look`, `less_risk`, `no_new_risk`), `counts`, `changes` (each with `direction` riskier / look / safer, `kind`, a plain `detail`, `path`) and the `note` that says what code cannot see. See [library.md](library.md). |
| `GET /api/rescan` | `?name=<skill>&version=N` (both optional; a version needs a name). Today's static checks on stored versions: `{ok, counts: {same, worse, failing, damaged}, versions: [{name, tag, status, findings, message}]}`. Reads only: nothing is changed or run. **404** for an unknown skill. It is `/api/rescan`, not `/api/library/rescan`, so a skill named "rescan" is never shadowed. |
| `GET /api/library/{name}/versions/{n}/files/{path}` | One stored file's text, after the whole version was verified against its manifest. A lookup by name, never a disk path. |
| `POST /api/library/{name}/rollback` | `{"to": N}` makes a new version with the content of vN. |
| `GET /api/library/{name}/export` | The `.zip` (`?version=N`, `?without_spec=true`). |
| `POST /api/library/{name}/install` | `{"target": "personal" or "folder", "folder": "<absolute path>", "version": N, "force": false}`. **409** if the folder exists and `force` is not set. |

In the **hosted version** every route under `/api/` except health and `/api/auth/*` answers **401** `{"detail": "Sign in first."}` without a
valid cookie (or `Authorization: Bearer <token>`); installing into a folder (`POST /api/library/{name}/install`) answers **403**; the
interactive docs are off. Local mode is unchanged.

Status codes: 400 a problem the person can fix (message in `detail`), 404 not in the library, 409 something is
already there, 413 upload over 6 MB, 422 a skill that failed its checks (import) or a malformed request body.

**Kinds.** Every `/api/library*` route, `GET /api/rescan` and `POST /api/validate` take `?kind=` (default `skill`). The library of
each kind is its own folder, so a name in one kind never shows in another. A kind that is not registered (`?kind=../x` included) is a
400 whose message names the kinds there are, and nothing is created on disk for it. `POST /api/library/{name}/install` with
`"target": "personal"` goes to that kind's own personal folder (`~/.claude/skills` for a skill).

## The skill builder (step H2)

The builder is a **session** you talk to across requests. The two slow steps (reading your words, writing the skill)
run as background jobs: the request that starts one returns at once with `status: "working"`, and the browser polls
`GET /api/builds/{id}`. Sessions and jobs are kept in the database ([database.md](database.md)).

```
 POST /builds ──► working ──► awaiting_answers ──POST answers──► working ──► ... ──► awaiting_approval
                     │                                                                    │ POST approve
                     └─► failed ◄── (retry, when it can help) ◄──────── working ◄─────────┘
                                                                          └──► done ──POST save──► the library
```

| Method and path | What it does |
|---|---|
| `GET /api/provider` | `{"configured", "provider", "model", "detail", "tiers", "escalation", "capabilities"}`: is a model set up, and which model serves each tier of work (`tiers`: fast, design, code, actor, each with provider and model; `escalation`: the stronger model, or null). Never a key, and no call to the model. See [ai-engine.md](ai-engine.md). |
| `POST /api/builds` | `{"description", "with_scripts", "kind"}` (`kind` defaults to `skill`; an unknown kind is a 400 and nothing is stored) starts a session (201). A sentence under 10 characters is a 400. |
| `GET /api/builds` | Sessions, newest first, each with its status and what became of it. |
| `GET /api/builds/{id}` | The whole session: `status`, `questions` (when it is waiting for answers), `spec` (the requirement waiting for approval), `result` (when done), `error`, `retryable`, `usage` (`{calls, errors, input_tokens, output_tokens, models}`: attempts at the model with failed ones counted, and the tokens the provider reported, null when it gave none), and `job` with its progress `events`. |
| `POST /api/builds/{id}/answers` | `{"answers": {"<slot>": "text"}}`. Only slots that were asked; at least one non-empty answer. |
| `POST /api/builds/{id}/approve` | The person approves the requirement shown in `spec`. **Only then is anything built.** |
| `POST /api/builds/{id}/retry` | Runs the step that failed again, when a second try can help (a missing key, an unreachable model). |
| `GET /api/builds/{id}/files/{path}` | A generated file's text, looked up by name among the files that were written. |
| `POST /api/builds/{id}/save` | `{"accept_draft", "note"}` keeps the skill in the library through the same checked import as any other skill (422 if it is refused). A **DRAFT** (a check failed, or its scripts were not all tested) is a 409 until `accept_draft` is true. |
| `DELETE /api/builds/{id}` | Removes the session, its jobs and its generated files. 409 while it is running. |

`409` on a builder action means the session is not at that step, or another click just moved it: each move is a
conditional update in the database, so two approvals can never both build.

**Same rules as the command line**, because the same code runs: completeness is decided by the fixed checklist, an
answer counts only through a quote that code verified is in the person's own words (extraction runs again on all of
their words each round), nothing is built before approval, and scripts run only in the sandbox. A model that says it
has answers the person never gave is not believed (a test covers it).

**Verified live (2026-11-19):** a real server with a real SQLite file and Gemini (`gemini-3.5-flash-lite`): start,
one question round, approve, build, save took about 15 seconds and produced `count-todos` with 21 checks passed and
0 failed, saved as v1. The same flow is covered offline with a mock model, including on real background threads.
Building *with scripts* over HTTP has only been run with a fake sandbox runner, not live.

## Why a local server is still locked down

A web page on another site can ask your browser to talk to `localhost`. Two defences, both in
`skillforge/api/security.py`. Both have automated tests, and both were also checked by hand with `curl` against a real
running server (the automated tests use a test client, not a real port):

- **Host check (DNS rebinding).** A request whose `Host` is not `localhost`, `127.0.0.1` or `[::1]` gets 403.
- **Origin check (cross-site requests).** A request that changes something and names an `Origin` that is not the UI's
  own gets 403. CORS allows only those origins. The UI is expected at `http://localhost:3000` or
  `http://127.0.0.1:3000`; add others with `SKILLFORGE_UI_ORIGINS` (comma separated). A request with no `Origin` is a
  command-line client and is allowed.

Also: the server binds to `127.0.0.1` only; an upload is read into memory under a 6 MB cap (checked on the declared
size and again while streaming) and never unpacked to disk; no endpoint returns an API key; nothing runs a script
except through the sandbox.

## Limits

- **No sign-in.** Anyone who can already run programs on this machine can call the API. It is a personal tool, not a
  shared server. A hosted version needs real accounts first (see D1 in [decisions.md](decisions.md)).
- `install` writes to `~/.claude/skills` or to a folder the request names, so it can write wherever your user can.
  That is why the Origin check exists; keep the server on `127.0.0.1`.
- Importing with `test_scripts=true` blocks until the cases finish (builds do not: they are jobs).
- **A running job cannot be cancelled.** Work is on threads; the way out is to wait for it. If the server stops, the
  work that was running is marked failed on the next start and can be retried.
- Jobs run in this one server process, two at a time. This is a personal tool, not a job queue for many people.
- Not yet covered over HTTP: suggestions and graph queries (step H5).
