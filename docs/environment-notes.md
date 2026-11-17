# Environment notes (Step 0)

Checked 2026-11-17 on the dev machine (Windows 11 Enterprise, PowerShell).

## Python

- venv lives **outside OneDrive**: `C:\dev\venvs\aiskills` (Python 3.13.15, created with `uv`).
- Dependencies are pinned in `backend/requirements.txt` (`anthropic`, `pydantic`, `python-dotenv`).
- Python 3.14 is the machine default but was not used, because some packages lack 3.14 builds.

## LLM provider

- No Anthropic API key is available (Claude Code access only), so the active provider is **Ollama Cloud**,
  reached through its OpenAI-compatible endpoint (`https://ollama.com/v1`) with the `openai` client.
  Default model: `deepseek-v4.1-flash` (confirmed visible to the key; 24 models listed).
- Keys come only from `.env` (`OLLAMA_API_KEY`, `ANTHROPIC_API_KEY`). `.env` is git-ignored.
- `backend/scripts/hello_structured.py` is the smoke test. `LLM_PROVIDER` selects `ollama` or `anthropic`.
  Both branches request schema-constrained output from a Pydantic model.
- The Anthropic branch (`claude-sonnet-5-5`, server-side refusal fallback) is kept for later. Sonnet 5.5
  rejects forced `tool_choice`, so structured output must not be built on forced tool calls.

### Status of the live call

- Auth works: the key lists models.
- Inference currently returns **402 Payment Required** ("Add usage credits or subscribe") for both
  `deepseek-v4.1-flash` and `gpt-oss:20b`. The account needs credits or a plan before any chat call works.
- Request construction and response parsing for both branches were checked offline with a mocked HTTP
  transport. That does not prove a live call works.

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
