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
| `GET /api/kinds` | What the app builds: each kind's `key`, `label`, `install_targets` and checklist `slots` (`key`, `label`, `question`). `skill`, `agent`, `plugin`, `mcp` and `mcp-node` ("MCP server (Node)"); also `definition_file` (`SKILL.md`, `AGENT.md`, `.claude-plugin/plugin.json`, `server.py`, `server.ts`), `personal_label` (such as `~/.claude/agents`) `installs_as_file` and `conversational` (false for a plugin, which is composed, not described). |
| `GET /api/hooks` | The hook catalogue, the only hooks a plugin may carry: for each `id`, `title`, `summary`, `event`, `matcher`, `effect` (`blocks` or `observes`), `sees`, `timeout`, `powers`, `revision` and the `options` it accepts (`key`, `label`, `help`, `max_items`, `max_length`, `pattern`). |
| `POST /api/plugins/preview` | `{"name", "description", "author", "components": [{"kind": "skill", "agent", "mcp" or "hook", "name", "version", "options"}]}` (a `hook` is named by its catalogue id, has no `version`, and may carry `options` such as `{"also": ["secrets.json"]}`; a bad id or option is a 400). The files a plugin of those skills, agents and MCP servers would hold (an `mcp` component adds `servers/<name>/`, a `.mcp.json` and, for each variable the server reads, a `userConfig` option), what it can do on the machine (`capabilities`, with a `servers` list: name, tools, capabilities, environment, command), every check and the version it would get. **Keeps nothing.** No model is used. 400 for a bad or reserved name, 404 for a component that is not in the library. |
| `POST /api/plugins` | The same body. Keeps the plugin as the next version in `library-plugin` through the checked import (422 and nothing kept when a check fails). Keeping the same plugin again makes no second version. |
| `POST /api/validate` | Body: a `.zip`. Runs every static check. Stores nothing, runs nothing. |
| `GET /api/library` | The skills, each with its version count and latest version. |
| `POST /api/library/import` | Body: a `.zip` (`?filename=`, `?note=`, `?test_scripts=true`). **200** when kept (or identical to the latest, `created: false`); **422** when a check failed, with the checks, and nothing is stored. `test_scripts` runs the skill's cases in the sandbox and the request waits for them. The answer has a `risk` object (as in `diff`) when it added a version after another, and `null` otherwise. |
| `GET /api/library/{name}` | Every version, newest first, with checks and file hashes. |
| `GET /api/library/{name}/diff` | `?frm=N&to=M`; default is the latest against the one before. Returns the file `changes` and a `risk` object: `level` (`more_risk`, `look`, `less_risk`, `no_new_risk`), `counts`, `changes` (each with `direction` riskier / look / safer, `kind`, a plain `detail`, `path`) and the `note` that says what code cannot see. See [library.md](library.md). |
| `GET /api/rescan` | `?name=<skill>&version=N` (both optional; a version needs a name). Today's static checks on stored versions: `{ok, counts: {same, worse, failing, damaged}, versions: [{name, tag, status, findings, message}]}`. Reads only: nothing is changed or run. **404** for an unknown skill. It is `/api/rescan`, not `/api/library/rescan`, so a skill named "rescan" is never shadowed. |
| `GET /api/library/{name}/versions/{n}/files/{path}` | One stored file's text, after the whole version was verified against its manifest. A lookup by name, never a disk path. |
| `POST /api/library/{name}/rollback` | `{"to": N}` makes a new version with the content of vN. |
| `DELETE /api/library/{name}` | `?kind=&confirm=<name>`. **Cannot be undone.** Deletes the entry of the person asking (the owner's for the owner), every version and the backups of that exact name. `confirm` must be exactly the name, else 400; 409 while that person has work running; links are never followed. Answers `{deleted, name, kind, versions, backups, leftover}`. See [data-removal.md](data-removal.md). |
| `POST /api/admin/people/{id}/erase` | Owner only, hosted only. `{"confirm": "<their address>"}`. **Cannot be undone.** Erases a **turned-off** person's folder, builds, runs and saved key, keeping the account and every usage row; 409 if they are not turned off or have work running. See [data-removal.md](data-removal.md). |
| `GET /api/library/{name}/export` | The `.zip` (`?version=N`, `?without_spec=true`, `?without_evidence=true`: `evidence.json` names the files and functions of the repository a skill cites). |
| `GET /api/library/{name}/evidence` | `?version=N`. The places the version cites with the facts recorded for each, or `evidence: null`. Reads what is stored. See [evidence.md](evidence.md). |
| `POST /api/library/{name}/recheck` | `{"repo": "<absolute path>", "version": N, "focus": "..."}`. What changed in the cited code: `{ok, counts, findings: [{ref, status (missing/moved/changed/edited/holds), details, candidates, not_measured}], notes, limits}`. Reads the repository, changes nothing. **403 in the hosted version** (it reads a folder on the server); **400** for a relative path, a folder that is not there, or a skill with no evidence. |
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

## A repository (slice W)

The routes behind the web **Repository** page ([repository-page.md](repository-page.md)). Each reads a folder on the machine the server runs on, so **each is off in the hosted
version (403)**. The path a person sends is never sent back, in a result or in an error: pages are shown the folder's name. Network paths (`\\server\share`) are refused.

| Route | |
|---|---|
| `POST /api/repos/analyze` | `{"path": "<absolute folder, or the link of a public GitHub repository>", "focus": "src"}` returns `{name, source, focus, stats, notes, hotspots, dead_code}` (`source` is `{"kind": "folder"}`, or for a link what was downloaded and what was left out: [github-link.md](github-link.md); a link GitHub could not serve is a 502): the graph's facts (no model, nothing is run). 400 for a relative path, a missing folder or a file. |
| `POST /api/repos/guide` | `{"path": "<absolute folder, or the link of a public GitHub repository>", "focus": "src"}` returns how the project works, read from its README and docs ([how-it-works.md](how-it-works.md)): `{status, name, source, docs, layers, parts, journeys, dropped, notes, provider, model}`. One model call that this request waits for, **nothing saved**; every quote is looked up in the documents by code and a part or step without a real quote is dropped. `status` is `ok`, `thin` (too little could be checked, nothing drawn) or `no_docs` (no README: no model is asked, so no key is needed). 400 for a bad path or link, **502 when the model could not be used** (no key, no quota, unreachable) or GitHub could not be reached, 403 in the hosted version. |
| `POST /api/suggestions` | `{"path", "focus", "with_ideas": true}` starts a run (201): the model is asked in the background, as a row in `suggest_runs`. The folder is checked before any model is asked, and a second request for the same folder and focus while that run is still working returns that run. |
| `GET /api/suggestions` | The runs, newest first, without their results: `{id, status, repo (the folder's name), focus, ideas, error, retryable, created_at, updated_at}`. |
| `GET /api/suggestions/{id}` | One run: `status` (`working`, `done`, `failed`) and, when done, `result`: the suggest report (`suggestions` each with `evidence_nodes`, `skill_requirement`, `unverified_numbers`; `dropped`; `notes`). 404 for an unknown id. Poll it while `working`. |
| `POST /api/suggestions/{id}/retry` | Runs a failed run again (a missing key, an unreachable model). 409 for any other state. |
| `GET /api/evals/preview` | `?name=&version=&kind=` ([testing-lab.md](testing-lab.md)): what a Testing Lab run of that skill version would do, with **no model asked**: `{name, version, tag, content_hash, skill_tokens, runnable, blocker, reason, cases[{name, kind, message, checks}], skipped, calls: {per_run, per_run_with_baseline}, limits}`. `blocker` is `""`, `no_cases`, `needs_tools` or `nothing_runnable` (a code for the page; `reason` is the words). 404 for an unknown skill or version, 400 for a version changed on disk, for an unknown kind, and for any kind but skill. |
| `POST /api/evals` | `{"name", "version": null, "runs": 1, "baseline": true, "kind": "skill"}` starts a run (201): the skill's own test cases are asked of the model in the background, with the skill and (unless `baseline` is false) without it, graded by code. `runs` is 1 to 5 (422 otherwise). A skill that cannot be run is a **400 with the reason** and nothing is stored or asked. A second request for the same version while its run is working returns that run. Also works hosted. |
| `GET /api/evals` | `?name=&version=` The runs, newest first, without their results: the run's fields and `summary: {outcome, with_skill, baseline, calls}` (null until it is done). |
| `GET /api/evals/{id}` | One run: `status` (`working`, `done`, `failed`), `progress: {done, total}` and, when done, `result: {outcome, verdict, limits, min_cases, runs, calls, skill_tokens, with_skill, baseline, skipped, cases[{name, kind, message, with_skill, baseline}]}` where each side is `{passed, runs, tries[{reply, cut, passed, checks[{kind, value, why, passed, detail}]}]}`. `outcome` is `helped`, `adds_nothing`, `no_difference`, `worse`, `too_few`, `with_only` or `not_run`. 404 for an unknown id. Poll it while `working`. |
| `POST /api/evals/{id}/retry` | Runs a failed run again (no model, an unreachable model, a restart). 409 for any other state. |
| `GET /api/scans/preview` | `?name=&version=&kind=&runs=&scenarios=&control=&draft=` ([canary-scan.md](canary-scan.md)): the tasks a behaviour scan would run, the most model calls, what the entry declares, its scripts (never run) and the limits sentence, with **no model asked**. Skills and agents only (400 otherwise); `runs` 1 to 3, `scenarios` 1 to 6 (422 outside). |
| `POST /api/scans` | `{"name", "version": null, "runs": 1, "scenarios": 5, "control": true, "draft": true, "kind": "skill"}` starts a scan (201) of the person's own library entry, spending that person's model; a second click on a running scan of the same version returns it; 429 at the person's runs-at-once limit. |
| `GET /api/scans` | `?name=&version=` This person's scans, newest first, without their results: the run's fields and `summary: {outcome, calls, findings, finished, total}`. |
| `GET /api/scans/{id}` | One scan: `status` (`working`, `done`, `failed`), `progress: {done, total}` and, when done, `result: {outcome, verdict, limits, runs, controls, not_run, calls, ...}` (every step as plain text, long text cut). Another person's scan is a 404. |
| `POST /api/scans/{id}/retry` | Runs a failed scan again. 409 for any other state. |
| `GET /api/library/{name}/quality` | `?version=` ([quality-report.md](quality-report.md)): the **Quality Report** of one skill version, assembled by code from stored files and stored Testing Lab runs (a GET: no model, nothing run, nothing changed): `{name, version, tag, latest, versions, created_at, source_kind, source_label, note, content_hash, headline: {failed, warnings, not_run, passed}, attention: {tone, text}, groups: [{key: library\|design\|written, title, rows: [{name, status, detail, was, change}]}], requirements: {source, criteria[{id, text, tests, runnable}], uncovered, unknown_cites}, tests: {total, runnable, blocker, reason, skipped}, tokens: {always, when_used, on_demand, heavy}, lab: {state, run, other}, changes, evidence, suggestions[{kind, text, link}], suggestions_more, not_run[{what, why}], limits}`. `change` is `same`, `worse`, `better`, `new` (library checks, compared with the import) or `run_now` (design and written-file checks, which were not kept at import). The version is read through the library, so a changed one is a 400; 404 for an unknown skill or version, 400 for a kind other than skill, 422 for a bad version. |
| `GET /api/library/{name}/tests` | `?version=` ([testing-lab.md](testing-lab.md), "Your own test cases"): every test case of a skill version, **the ones that cannot be run too** (so they can be fixed): `{name, version, tag, content_hash, latest, needs_tools, unreadable, limits, cases[{name, kind, message, covers, runnable, checks[{kind, value, why}]}]}`. `unreadable` counts entries of `tests/cases.json` that are not test cases (a save drops them). 404 for an unknown skill or version, 400 for a version changed on disk. |
| `POST /api/library/{name}/tests` | `{"base_version", "cases": [{"name", "kind", "message", "checks": [{"kind", "value", "why"}], "covers"}], "note"}` keeps the cases as a **new version** (a POST, not a PUT: the CORS policy allows GET, POST and DELETE only). Goes through the library's checked import: 200 with the import report, **422 when a static check refuses it** (for example a message with a hidden character), nothing stored. `base_version` must be the latest (**409**), a case that could not be run is a **400 that names every such case** ("Case 2 ('x'): it needs a message to send"), at most 30 cases, 3 checks each, texts bounded (422). Writes `tests/cases.json` and, when the definition file already holds a `tests` list, that too; stops (400) when the definition cannot be read. Identical content makes no new version. |
| `POST /api/builds` | now also takes **`from_run` and `idea`** (a finished suggestion run and the idea's position in it: the server uses that run's own folder and the idea's cited places) or, for scripts, `repo` (absolute folder), `focus` and `evidence_nodes` (at most 60 places); not both. A half-given seed, an idea that is not a buildable skill or automation, a run that is not finished, a folder that is not there, or a kind other than skill or agent is a 400; an unknown run is a 404. The session then shows `seed: {repo, focus, places}` and, when it ends, the result `evidence: {repo, places, skipped}`; the built folder carries `evidence.json`. |

## Settings (slice X)

The routes behind the web **Settings** page ([settings.md](settings.md)). **Both are off in the hosted version (403)**: a save would be written on the server.

| Route | |
|---|---|
| `GET /api/settings` | `{file, file_exists, groups, settings, status}`. Each setting has `name, group, label, help, kind, provider, choices, set, source (file, environment, unset), editable` and, **except for a key**, `value`. A key is never sent: not its value, not its end, not its length. |
| `POST /api/settings` | `{"changes": {"LLM_MODEL": "a-model", "GOOGLE_API_KEY": "...", "LLM_FALLBACKS": null}}`: a text sets, `null` or an empty text removes; all or nothing; applied to the running server at once. 200 = the new state. 400 `{detail, problems: [{name, message}]}` for an unknown name, a name set in the environment, an unsafe or wrong value or a body of the wrong shape (never repeating a value); 413 over 20 KB. |

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
