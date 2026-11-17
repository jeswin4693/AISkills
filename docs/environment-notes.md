# Environment notes (Step 0)

Checked 2026-11-17 on the dev machine (Windows 11 Enterprise, PowerShell).

## Python

- venv lives **outside OneDrive**: `C:\dev\venvs\aiskills` (Python 3.13.15, created with `uv`).
- Dependencies are pinned in `backend/requirements.txt` (`anthropic`, `pydantic`, `python-dotenv`).
- Python 3.14 is the machine default but was not used, because some packages lack 3.14 builds.

## LLM provider

- First provider: Anthropic. Default model: `claude-sonnet-5-5`, set through `LLM_MODEL` in `.env`.
- Key comes only from `.env` (`ANTHROPIC_API_KEY`). `.env` is git-ignored.
- `backend/scripts/hello_structured.py` is the smoke test. It uses structured output (Pydantic schema,
  `output_config.format`) and the server-side refusal fallback. Sonnet 5.5 rejects forced `tool_choice`,
  so structured output must not be built on forced tool calls.

## Docker: Linux containers are NOT available yet

- `docker` here is a native **Docker Engine service** (installed via Chocolatey), not Docker Desktop.
  There is no "Switch to Linux containers" toggle.
- The engine runs Windows containers only (`OSType=windows`, default isolation `hyperv`).
- Verified: `docker run --rm alpine echo ok` fails with `no matching manifest for windows/amd64`.
- WSL is not installed, and enabling Windows features needs admin rights, so I did not change anything.

Options for the sandbox (needed in Step 2, not Step 1):

| Option | Notes |
|---|---|
| A. WSL2 + Docker Engine inside WSL | Free. Needs admin to run `wsl --install`; company policy may block it. Recommended first thing to ask IT. |
| B. Docker Desktop (WSL2 backend) | Easiest, but Desktop needs a paid license at larger companies and also needs WSL2/admin. |
| C. Windows containers as the sandbox | Works today (`--network none`, `--memory`, `--cpus`, Hyper-V isolation), but images are large and the filesystem and mount controls are weaker. |
| D. Remote Linux runner (VM, Codespaces, cloud container) | No local changes needed. Adds cost and network setup. |

Decision pending: pick A/B/C/D before Step 2.
