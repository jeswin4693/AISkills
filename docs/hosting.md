# Hosting: the version on your computer, and the version on a link

SkillForge AI runs in two ways. They are the same program; only the settings differ.

| | **Local** (the default; what you use in VS Code) | **Hosted** (a link you open on a phone or any computer) |
|---|---|---|
| Where it runs | your computer, `127.0.0.1` | a container on a host, behind one public address |
| Sign-in | none (only your own machine can reach it) | **an access token**; the server refuses to start without one |
| Install a skill into `~/.claude/skills` or a folder | yes | **no** (it would write on the server). Use **Export**, then install the zip on your own computer |
| Scripts tested in the Docker sandbox | yes, when Docker or WSL is available | **no sandbox in the container**: a skill with scripts is built as a DRAFT and says its scripts were not run |
| Interactive API docs (`/api/docs`) | yes | off |
| Settings and keys | `.env` or environment | host secrets / environment (never in the image) |

Turning hosted mode on changes nothing for local use: with no `SKILLFORGE_MODE`, everything is as it always was.

## What hosted mode does

- Everything under `/api/` needs a sign-in except `/api/health` (so the host can check the container) and `/api/auth/*`.
- Signing in swaps the access token for a **signed cookie** (HttpOnly, SameSite=Lax, 14 days, Secure on https). The cookie holds no
  secret and is signed with a key derived from the token, so **changing the token signs everyone out**. A script can send
  `Authorization: Bearer <token>` instead.
- **Five wrong tokens lock sign-in for a minute** (one lock for the whole server, so it cannot be dodged by changing address). The
  token must be at least 20 characters, so guessing it at five tries a minute is not realistic.
- Only `localhost` and the host names you list in `SKILLFORGE_ALLOWED_HOSTS` may be used; a page on any other site cannot make the
  browser change anything (the same `Origin` rule as the local version, extended to your own host names).
- Provider keys, the access token and the cookie key are never sent to the browser, and error text has keys removed.

## Settings

| Setting | Meaning |
|---|---|
| `SKILLFORGE_MODE=hosted` | turns the hosted version on (the image sets it) |
| `SKILLFORGE_ACCESS_TOKEN` | **required**: a long random string. Set it as a secret on the host |
| `SKILLFORGE_ALLOWED_HOSTS` | the host name people open (`skillforge.example.com`); comma separated; `*` allows any (the sign-in still applies) |
| `SKILLFORGE_UI_ORIGINS` | extra page addresses to trust, only if you serve the pages from a different address than the API |
| `SKILLFORGE_COOKIE_SECURE=1` | set on any https site, so the cookie is never sent over plain http |
| `SKILLFORGE_DATA_DIR` | where the library, the database and the builds live (`/data` in the image): **keep it on a persistent disk** |
| `PORT` | the public port (the image uses 8080; many hosts set it for you) |
| `LLM_PROVIDER`, `LLM_MODEL`, the key variables, `LLM_FALLBACKS`, `LLM_<TIER>_…` | the models, exactly as in [ai-engine.md](ai-engine.md) |

## Run it with Docker

```powershell
docker build -t skillforge .
docker run -p 8080:8080 -v skillforge-data:/data `
  -e SKILLFORGE_ACCESS_TOKEN="<a long random string>" -e SKILLFORGE_ALLOWED_HOSTS=localhost `
  -e LLM_PROVIDER=gemini -e LLM_MODEL=<a model> -e GOOGLE_API_KEY=<your key> `
  skillforge
# open http://localhost:8080 and sign in with the token
```

Or with Compose: copy `.env.example` to `.env.hosted`, fill it in (the token, the allowed host, the models and keys, optionally
`LLM_FALLBACKS`), then `docker compose up --build`. `.env.hosted` is private (git ignores it) and is not copied into the image.

Inside the container the Python API listens only on `127.0.0.1:8000`; the web server on `$PORT` forwards `/api/*` to it, so the
pages and the API share one address and one cookie. Run **one** instance: the builder's jobs and the SQLite file are not meant
to be shared by several processes.

## Put it on a link

The image is generic: any host that runs a container, gives it a port, a persistent disk and HTTPS will do. You need to set the
secrets (`SKILLFORGE_ACCESS_TOKEN`, your model keys), `SKILLFORGE_ALLOWED_HOSTS` to the address the host gives you,
`SKILLFORGE_COOKIE_SECURE=1`, and mount a disk at `/data`.

| Host | Notes (none of these hosts has been tried: the image was tested only with Docker on this machine) |
|---|---|
| Fly.io | `fly launch` from the repo (it finds the Dockerfile), `fly volumes create` and mount it at `/data`, `fly secrets set SKILLFORGE_ACCESS_TOKEN=… GOOGLE_API_KEY=…`, set `internal_port = 8080` |
| Railway | deploy from the repo, add a volume at `/data`, set the variables; it gives a public https address |
| Render | a Docker web service with a persistent disk at `/data` (disks need a paid plan; the free plan sleeps and forgets the disk) |
| Your own server | `docker compose up -d`, with Caddy or another proxy in front for https; point it at port 8080 |
| Not suitable | hosts with no persistent disk (the library and your sessions would vanish on every restart), for example Cloud Run without a volume |

Then open the address on your phone, sign in once (the cookie lasts 14 days), and use it like the local version: describe a skill,
answer, approve, save to the library. To get a skill into your agent, **Export** the zip and install it on your own computer.

## Using Gemini and Groq (or any other keys) together

Put every key in the host's secrets, choose the main model with `LLM_PROVIDER` and `LLM_MODEL`, and list the others in
`LLM_FALLBACKS=groq:<model>,openai:<model>`. The next model answers when the first is rate limited, out of quota, overloaded or
unreachable. `python -m skillforge models --test` (or `POST /api/provider/check` once signed in) tests each one with a tiny call.

## What this does not protect against

- **One shared token, no accounts.** Anyone with the token has full access, including your model quota. There is no per-person
  access and no audit log. Treat the token like a password and change it if it leaks.
- **The sign-in lock is global.** Someone who knows the address can keep sign-in locked for you by sending wrong tokens (you can
  still use the Bearer header or wait a minute). Putting the site behind your host's own access controls closes that.
- **Prompts go to the model providers**, and what you type is kept in the session database on the disk you mounted.
- **No sandbox in the container.** Generated scripts are never run there, so a skill built with scripts is a DRAFT. Do not mount the
  Docker socket into this container.
- **The Next.js web server forwards API calls.** Large uploads (the API allows 6 MB) go through that forwarder; they were not tried
  through it.

## What was checked (2026-11-19)

- **Offline tests** (`tests/test_hosted.py`, 19 of them): the settings and the refusal to start without a strong token; the cookie
  (signature, expiry, a changed token, tampering); the bearer token; the sign-in lock and its unlocking; every API route refused
  without a sign-in except health and sign-in; Secure cookies behind https; sign-out; the install block; docs off; allowed hosts and
  the cross-site page rule; local mode unchanged; no response ever containing the token.
- **The image was really built and run** with Docker (inside WSL on the development machine): a 24-step build, then the container
  with this machine's own `.env` settings. Through its public port, checked by `curl`: the web page is served; an API call without a
  sign-in gets 401; a wrong token gets 401; the right token sets a cookie (HttpOnly, SameSite=Lax) and opens the API; the install
  endpoint answers 403 with the reason; a request from another site's page answers 403; a small upload and a **3.6 MB** upload both
  went through the web server's forwarder and were imported; both models (Gemini and Groq) answered a tiny call **from inside the
  container**; a real build started, asked its first questions and recorded its usage (273 tokens in, 207 out); signing out ended the
  session; the container's own health check reported healthy after running for several minutes.
- **A false alarm worth knowing about:** during testing the container seemed to stop by itself about 16 seconds after starting, with
  "the API stopped with exit code 143" (SIGTERM). It was not the image: **Docker inside WSL is shut down by WSL itself shortly after the
  last `wsl.exe` session ends**, taking its containers with it. Two idle containers (with and without a health check) died at the same
  moment, and with a `wsl.exe` session kept open they ran healthy for the whole test. If you test the image with Docker in WSL, keep a
  session open (for example `wsl.exe --exec sleep 600`). A normal Docker host does not do this.
- **The sign-in screen in a browser** is covered by unit tests of its logic (4) and by the existing real-browser suite showing the local
  version unchanged. The hosted sign-in screen itself was **not** driven in a real browser, and not on a phone.

**Not verified:** any real hosting service (Fly.io, Railway, Render and the others in the table are untried), https and the Secure
cookie on a real https address, the pages opened on an actual phone, and several people or tabs signing in at once. Whether the web
server's forwarder keeps the client's original host name is not needed (the API accepts loopback), but it is why
`SKILLFORGE_ALLOWED_HOSTS` must name your public address for pages that change things.
