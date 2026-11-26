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
| `SKILLFORGE_UI_ORIGINS` | extra page addresses to trust, only if you serve the pages from a different address than the API. **A signed-in session cannot work that way**: the session is a cookie, and a browser neither stores nor sends a cookie between two different origins (found by driving the sign-in screen: after a correct token the browser held no session cookie). The supported hosted setup serves the pages and the API from **one address**, as the image does |
| `SKILLFORGE_COOKIE_SECURE=1` | set on any https site, so the cookie is never sent over plain http |
| `SKILLFORGE_DATA_DIR` | where the library, the database and the builds live (`/data` in the image): **keep it on a persistent disk** |
| `SKILLFORGE_GOOGLE_CLIENT_ID`, `SKILLFORGE_ALLOWED_EMAILS` | optional, **both or neither**: "Sign in with Google" for other people, and who may sign in. Each person then has their own builds and library. See [accounts.md](accounts.md) |
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

### Free hosting: what a search found (2026-11-26; free offers change, check the page before you sign up)

None of these has been tried with this image. Vercel and Supabase are **not hosts** for this app: Vercel runs short-lived functions with no persistent disk, and this app
is a long-running Python server with background jobs and files; Supabase is a database, login and storage service (it could later give PostgreSQL and real accounts, but PostgreSQL has never been tried here).

| Option | What the sources say | Concern |
|---|---|---|
| Oracle Cloud *Always Free* VM | [Oracle's docs](https://docs.oracle.com/en-us/iaas/Content/FreeTier/resourceref.htm): free for an unlimited time; its [FAQ](https://www.oracle.com/cloud/free/faq/) says sign-up uses a **card** for identity (no virtual, prepaid or PIN-debit cards) and that capacity is limited | **Idle VMs may be reclaimed** (CPU under 20% for 7 days), and [InfoQ reports](https://infoq.com/news/2026/07/oracle-cloud-free-tier-limits/) the free allowance was cut to 2 OCPU / 12 GB in mid-2026 (the sources disagree on the date) |
| Google Cloud *Free Tier* e2-micro | [Google's docs](https://docs.cloud.google.com/free): one e2-micro VM a month in listed US regions; the limits "do not expire but are subject to change"; a billing account is verified | The VM is small (about 1 GB of memory as I recall). **This image was measured: about 185 MiB for the whole container when idle** (see "The https front door" below), so it fits with room to spare; a build's peak was **not** measured, and a swap file is cheap insurance |
| A card-free route | a free container host plus a free database for the data | More code (the library lives in files today, not in a database) and a host that sleeps |

### The address must be one Google accepts (matters only for "Sign in with Google")

Google's page on [managing OAuth clients](https://support.google.com/cloud/answer/15549257) says a JavaScript origin must use **https** (only `localhost` is exempt), cannot be a **raw IP address**,
and cannot carry a path or query; it also says a host's top-level domain must be on the Public Suffix List. So `http://35.1.2.3:8080` can never be used for Google sign-in, and **a free VM gives you only an IP address**:
you need a **name** that points at it, with an https certificate (Caddy gets one by itself, see `deploy/`).

| Kind of name | Status |
|---|---|
| A domain you own (a few dollars a year) | works; the safe choice |
| A name the host gives you (`*.onrender.com`, `*.fly.dev`, `*.up.railway.app`, `*.run.app`) | https comes with it; those hosts are the ones in the table above with their own limits (sleeping, no free disk, a card) |
| A free wildcard-DNS name (`<ip>.sslip.io`, `<ip>.nip.io`) or a free dynamic-DNS name | **not confirmed.** One developer's report says Google refused both with "origin not allowed" (the cause may have been something else, such as the 5-minute-to-hours delay Google states). Test it before relying on it |

**A two-minute test that costs nothing and needs no host:** in Google Cloud Console, open the OAuth client and try to add the origin you plan to use (for example `https://skillforge-yourname.duckdns.org`).
The console checks the rules when you press Save, so a refusal appears at once; whether the sign-in then really works also needs the page to be served from that name, which is the real test.
Without Google sign-in the host needs no such name: the access token works on any https address.

Then open the address on your phone, sign in once (the cookie lasts 14 days), and use it like the local version: describe a skill,
answer, approve, save to the library. To get a skill into your agent, **Export** the zip and install it on your own computer.

## The https front door (`docker-compose.https.yml`, `deploy/Caddyfile`)

For a small server with a public name: Caddy listens on 80 and 443, gets and renews a free https certificate by itself, and forwards to the app, which publishes **no port**. Steps are at the top of `docker-compose.https.yml`:
point a name at the machine, open ports 80 and 443, fill `.env.hosted` (add `SKILLFORGE_DOMAIN`, `SKILLFORGE_ALLOWED_HOSTS` with the same name, `SKILLFORGE_COOKIE_SECURE=1`), then
`docker compose --env-file .env.hosted -f docker-compose.https.yml up -d --build`. The Caddy container receives **only** the domain name (the `--env-file` flag fills in `${...}`; it does not hand the file to the container), never the app's keys.

**Checked (2026-11-26, Docker 29 inside WSL, the real image and the real Caddyfile on a private network, requests sent through Caddy with `curl`):**
the Caddyfile passes `caddy validate` with the domain set and fails loudly without it; the health check answers over https in about 2 seconds; an API call with no sign-in is 401; the app is **not** reachable except through Caddy;
Caddy adds `Strict-Transport-Security` and `X-Content-Type-Options` and sends no `Server` header; plain http is redirected (308) to https; `/api/auth/status` shows the Client ID; the nonce cookie is `HttpOnly; Secure; Path=/api/auth; Max-Age=600`; the owner's access-token sign-in works through Caddy and its cookie is `HttpOnly; Secure`, **and an authenticated request with that cookie then succeeds over https (200) while the same request without it is 401, also when Google's own `g_state` cookie comes first in the header**;
a made-up Google ticket is a 401; and the container's log holds neither the token nor the ticket. **The image is 628 MB on disk and the running container used about 182 to 185 MiB of memory when idle** (Docker's own figure; python about 153 MB of that), measured after a handful of requests and **not** under a real build.
The test was run twice: on an image built before the independent review's fixes, and again on **an image rebuilt from the final committed code**, which also added the authenticated-request checks; the results above are the final image's.
The compose file was parsed and its structure checked (the app publishes no port, Caddy has no `env_file`, the certificate has a volume), but **not run**: the Compose plugin is not installed in that WSL, so the two containers were started by hand with the same settings.

**Not checked:** a real certificate from Let's Encrypt (it needs a public name and open ports 80 and 443; Caddy used its own local certificate authority for `localhost`), a real server, memory under a build or on a 1 GB machine, and Google sign-in through this front door (needs a name Google accepts, see above).

## Using Gemini and Groq (or any other keys) together

Put every key in the host's secrets, choose the main model with `LLM_PROVIDER` and `LLM_MODEL`, and list the others in
`LLM_FALLBACKS=groq:<model>,openai:<model>`. The next model answers when the first is rate limited, out of quota, overloaded or
unreachable. `python -m skillforge models --test` (or `POST /api/provider/check` once signed in) tests each one with a tiny call.

## What this does not protect against

- **The access token is the owner's key.** Anyone with it has the owner's full access, including your model quota. Treat it like a password and
  change it if it leaks. With only the token there is one person and no audit log. **With Google sign-in** ([accounts.md](accounts.md)) other
  people have their own data and cannot see each other's, but **everyone who signs in still spends the host's model key** (per-person keys are
  not built yet), so the allow-list matters.
- **The sign-in lock is global, and it is the access token's alone.** Someone who knows the address can keep sign-in **by token** locked for you by sending wrong tokens (you can
  still use the Bearer header, or wait a minute). Google sign-in has no such lock (nothing about a Google ticket can be guessed), so wrong tickets never lock anyone out,
  and a good Google sign-in does not reset a token guesser's count. Putting the site behind your host's own access controls closes the token one.
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
- **The sign-in screen in a browser** is covered by unit tests of its logic and by the existing real-browser suite showing the local
  version unchanged. **Updated 2026-11-26:** the hosted sign-in screen is now driven in a real browser at phone size and with touch (`npm run e2e:phone`, 13 checks, see
  [accounts.md](accounts.md)); that is an emulation of a phone in Edge, **not a real phone**, and Google's button was drawn but could not finish a sign-in (the Client ID was made up).

**Not verified:** any real hosting service (Fly.io, Railway, Render and the others in the table are untried), https and the Secure
cookie on a real https address, the pages opened on an actual phone, and several people or tabs signing in at once. Whether the web
server's forwarder keeps the client's original host name is not needed (the API accepts loopback), but it is why
`SKILLFORGE_ALLOWED_HOSTS` must name your public address for pages that change things.
