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
| `GET /api/health` | `{"status": "ok", "version": ...}` |
| `GET /api/sandbox` | Is a Linux sandbox available here, and why or why not. |
| `GET /api/languages` | Every language with its level, grammar status and extensions. Never downloads a grammar. |
| `POST /api/validate` | Body: a `.zip`. Runs every static check. Stores nothing, runs nothing. |
| `GET /api/library` | The skills, each with its version count and latest version. |
| `POST /api/library/import` | Body: a `.zip` (`?filename=`, `?note=`, `?test_scripts=true`). **200** when kept (or identical to the latest, `created: false`); **422** when a check failed, with the checks, and nothing is stored. `test_scripts` runs the skill's cases in the sandbox and the request waits for them. |
| `GET /api/library/{name}` | Every version, newest first, with checks and file hashes. |
| `GET /api/library/{name}/diff` | `?frm=N&to=M`; default is the latest against the one before. |
| `GET /api/library/{name}/versions/{n}/files/{path}` | One stored file's text, after the whole version was verified against its manifest. A lookup by name, never a disk path. |
| `POST /api/library/{name}/rollback` | `{"to": N}` makes a new version with the content of vN. |
| `GET /api/library/{name}/export` | The `.zip` (`?version=N`, `?without_spec=true`). |
| `POST /api/library/{name}/install` | `{"target": "personal" or "folder", "folder": "<absolute path>", "version": N, "force": false}`. **409** if the folder exists and `force` is not set. |

Status codes: 400 a problem the person can fix (message in `detail`), 404 not in the library, 409 something is
already there, 413 upload over 6 MB, 422 a skill that failed its checks (import) or a malformed request body.

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
- Importing with `test_scripts=true` blocks until the cases finish. Jobs with progress come with step H2.
- Not yet covered: building skills, suggestions and graph queries over HTTP (steps H2 and H5).
