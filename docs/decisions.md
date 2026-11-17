# Design decisions

## D1 - Audience and deployment model (2026-11-17)

**Decision:** open source, for anyone to use. Self-hosted and bring-your-own-model first
(each user runs the app and uses their own provider API key).
Hosted with per-user encrypted keys can follow with the UI step. A hosted service where we
supply and pay for the model is not planned.

**Consequences**

- The LLM layer stays provider-neutral. Each adapter declares what it supports (JSON-schema output,
  context size) and the app warns when a model is too weak.
- Every generated skill records which model produced it.
- The sandbox must **fail closed**: if no safe sandbox is available, testing refuses to run.
  It must never fall back to running generated code on the host.
- Keys come only from the environment or settings. No key is ever stored in the repo.
- Install must be simple and work on Windows, macOS and Linux (CI on all three).
- Quality checks (validators, sandbox tests) matter more, because users will bring models of very
  different quality.

**Open items before the repo is made public**

- Choose a license (the repo has none yet, so by default nobody may reuse the code).
- Add a contributing guide and a security-reporting policy.
- Review docs for personal or employer information.
- Confirm that publishing is allowed under your employment / IP terms.

## D2 - Provider: bring your own API key, OpenAI first (2026-11-17)

**Decision:** the first provider is OpenAI, using the project owner's own API key. Anthropic stays
supported as a second adapter. This replaces an earlier idea of a free local-model default.

**Consequences**

- Usage is billed by the provider to whoever owns the key. This repo ships no key, no bundled model and
  no hosted service, so the project itself has no running cost.
- `.env.example` defaults to `LLM_PROVIDER=openai`. `LLM_MODEL` has no default, because the model a
  key can use depends on the account.
- Automated tests use a mock provider, never a paid or hosted model.
- People without a paid API key have no free path in the default setup.
- Docker Desktop is not assumed, because it needs a paid license at larger companies. Docker Engine or
  Podman are the free options for the sandbox.
