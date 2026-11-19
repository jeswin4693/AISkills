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
- Groq (2026-11-19, through the AI service): a structured call works on its gpt-oss models (about 0.5 to 1 s), with token counts.
  Not every Groq model takes JSON-schema output: one answered 400 "does not support response format `json_schema`", another
  400 "Failed to generate JSON"; both are classified `bad_request` and are not retried. A made-up key is `auth` (the key is not
  echoed back) and a made-up model is `model_missing`. Which models a key can use changes, so ask the provider's model list.

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
  must not be built on forced tool calls. The app's adapter (`providers/anthropic_native.py`, `LLM_PROVIDER=anthropic`)
  therefore sends a JSON schema in `output_config.format` and validates the reply text itself, with no beta flags. It is
  checked against a mocked HTTP server only; it has never made a real call.

## Docker and the sandbox

- Native `docker` here is a Docker Engine service installed via Chocolatey. It runs **Windows containers only**
  (`docker run alpine` fails with `no matching manifest for windows/amd64`), so the sandbox refuses it.
- **The sandbox works through Docker inside WSL**: WSL 3.0.5 with an imported Ubuntu 24.04.5 distribution
  (`skillforge-ubuntu`, kept in `C:\dev\wsl`, outside OneDrive) running Docker Engine 29.1.3. See
  [sandbox-wsl.md](sandbox-wsl.md) for how it was set up, why `wsl --install -d` could not be used here (this
  network resets connections to `raw.githubusercontent.com`), and the real-container tests that prove the locks.
- Check it any time with `python -m skillforge sandbox-status`.
