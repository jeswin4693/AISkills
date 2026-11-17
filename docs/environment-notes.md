# Environment notes (Step 0)

Checked 2026-11-17 on the dev machine (Windows 11 Enterprise, PowerShell).

## Machine

- 31.5 GB RAM, Intel Core Ultra 7 265U (12 cores), integrated Intel graphics only (no NVIDIA), 183 GB free disk.
- No admin rights. Everything installed so far is per-user.

## Python

- venv lives **outside OneDrive**: `C:\dev\venvs\aiskills` (Python 3.13.15, created with `uv`).
- Dependencies are pinned in `backend/requirements.txt` (`anthropic`, `openai`, `pydantic`, `python-dotenv`).
- Python 3.14 is the machine default but was not used, because some packages lack 3.14 builds.

## LLM provider

- First provider: **Google Gemini**, using the project owner's own API key, through Gemini's
  OpenAI-compatible endpoint (`https://generativelanguage.googleapis.com/v1beta/openai/`) with the
  `openai` client. OpenAI and Anthropic are additional adapters.
- Keys come only from `.env` (git-ignored). `LLM_MODEL` has no default; set a model your key can use.
- `backend/scripts/hello_structured.py` is the smoke test. `LLM_PROVIDER` selects `gemini`, `openai` or
  `anthropic`. Every branch requests schema-constrained output from a Pydantic model.

### Verified live

- Gemini, `gemini-3.5-flash-lite`: structured output validated against the Pydantic model, about 5.6 s
  (21 tokens in, 54 out).

### Gotchas found

- `gemini-2.5-flash` and `gemini-2.5-flash-lite` still appear in the key's model list but return 404
  ("no longer available to new users"). Listing a model does not mean the key can use it.
- `gemini-3.8-flash` returned 503 (overloaded) once, after the SDK's two automatic retries.
- The Gemini key's native `generateContent` endpoint wants the key in the `x-goog-api-key` header; a
  `Bearer` header is rejected (401). The OpenAI-compatible endpoint takes it as a normal API key.

### Not verified live

- OpenAI branch: the key authenticates and lists models, but chat calls return **429 "no credits
  remaining"**. Checked only with a mocked HTTP transport.
- Anthropic branch (`claude-sonnet-5-5`, server-side refusal fallback): checked only with a mocked HTTP
  transport. There is no Anthropic API key. Sonnet 5.5 rejects forced `tool_choice`, so structured output
  must not be built on forced tool calls.

## Docker: Linux containers are NOT available yet

- `docker` here is a native **Docker Engine service** (installed via Chocolatey), not Docker Desktop.
  There is no "Switch to Linux containers" toggle.
- The engine runs Windows containers only (`OSType=windows`, default isolation `hyperv`).
- Verified: `docker run --rm alpine echo ok` fails with `no matching manifest for windows/amd64`.
- WSL is not installed, and enabling Windows features needs admin rights, so nothing was changed.

Options for the sandbox (needed in Step 2, not Step 1):

| Option | Notes |
|---|---|
| A. WSL2 + Docker Engine inside WSL | Free. Needs admin to run `wsl --install`; company policy may block it. Recommended first thing to ask IT. |
| B. Docker Desktop (WSL2 backend) | Easiest, but Desktop needs a paid license at larger companies and also needs WSL2/admin. |
| C. Windows containers as the sandbox | Works today (`--network none`, `--memory`, `--cpus`, Hyper-V isolation), but images are large and the filesystem and mount controls are weaker. |
| D. Remote Linux runner (VM, Codespaces, cloud container) | No local changes needed. Adds cost and network setup. |

Decision pending: pick A/B/C/D before Step 2.
