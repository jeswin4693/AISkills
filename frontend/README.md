# SkillForge AI: web UI

The browser front end for the local API. What it does, and why it looks the way it does, is in
[../docs/ui.md](../docs/ui.md). This file is only how to run it.

## Run it

Two terminals. The UI needs the API.

```powershell
# 1. the API (from the repository's backend folder)
cd backend
python -m skillforge serve                 # http://127.0.0.1:8000

# 2. the UI (from this folder)
cd frontend
npm run dev                                # http://127.0.0.1:3000
```

Open **http://127.0.0.1:3000**. (`http://localhost:3000` also works: the API trusts both.) For a faster, production
build: `npm run build` then `npm start`.

The UI finds the API at `http://127.0.0.1:8000`. To change that, set `NEXT_PUBLIC_API_URL` before `npm run dev` or
`npm run build`. If you serve the UI from another address, tell the API with `SKILLFORGE_UI_ORIGINS`
(comma separated), otherwise it refuses requests that change anything.

## First-time setup

```powershell
cd frontend
npm install
powershell -File ..\scripts\frontend-node-modules.ps1
```

The second command moves `node_modules` (about 12,000 files) and the `.next` build cache to `C:\dev\frontend` and
leaves junctions in their place, so OneDrive does not sync them. **Run it again after every `npm install`**, because
npm replaces a junction with a real folder. It is safe to run at any time.

The scripts pass `--webpack` on purpose: with those folders outside the project, Turbopack (Next 16's default
bundler) refuses to follow the links.

## Checks

```powershell
npm run typecheck      # TypeScript, no emit
npm test               # unit tests (api client, diff reader, formatters), no browser, no server
npm run e2e            # a real browser against the real API and the built UI (see below)
```

`npm run e2e` starts a real API (`e2e/mock_server.py`: real database, checklist and checks, but a **scripted fake model**,
so it needs no key and no network) and the production build, drives **Microsoft Edge** with `playwright-core` (no browser
is downloaded; set `E2E_BROWSER_CHANNEL=chrome` to use Chrome), and checks 39 behaviours from import to install (with the risk diff and re-check), the whole
builder conversation, and "the API is gone". Run `npm run build` first, and point it at the Python that has the backend
installed: `$env:SKILLFORGE_PYTHON = "C:\dev\venvs\aiskills\Scripts\python.exe"`. Set `E2E_SHOTS` to a folder to keep
screenshots of each state.

It uses ports 3000 and 8000 by default. **If your own `serve` or `npm run dev` is running, use other ports**: the UI
learns the API's address when it is built, so build for the new address first.

```powershell
$env:NEXT_PUBLIC_API_URL = "http://127.0.0.1:8100"; npm run build
$env:E2E_UI_PORT = "3100"; $env:E2E_API_PORT = "8100"; npm run e2e
```

(Run `npm run build` again without `NEXT_PUBLIC_API_URL` afterwards if you then want `npm start` against port 8000.)

**A run against your real model** (uses the key in `.env` and a few model calls; the key is never printed):
`node e2e/live.mjs`, with the same ports and build as above. It is not part of `npm run e2e`, which stays repeatable
and free.

## Telemetry

Next.js collects anonymous usage statistics by default. To switch that off for this machine:
`npx next telemetry disable`, or set `NEXT_TELEMETRY_DISABLED=1`. (The e2e script sets it for its own run.)
