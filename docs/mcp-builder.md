# The MCP Builder (Component Factory, Phase 3)

Describe a small tool server in plain words and get a checked **Python MCP server** folder: a `server.py` that code assembles from a design, a
pinned `requirements.txt`, the test cases, a README with the exact command that adds it to Claude Code, and a report. The server is **started in
the sandbox and called over the real MCP protocol** before the build can say "ok". Plan: [superpowers/plans/2026-11-20-mcp-builder-phase-3.md](superpowers/plans/2026-11-20-mcp-builder-phase-3.md).

A simple example. You say: *"Two tools. word_count returns how many words a text has. reverse_words returns its words in reverse order. An empty text is refused."*
You get `word-tools/server.py` with two `@mcp.tool()` functions, four test cases, and a report that says each case was called in a locked container and what came back.

## How it works

```
words -> extract -> CHECKLIST -> ask -> APPROVE -> design -> assemble -> CHECKS -> repair x1 -> RUN IN THE SANDBOX -> files + report
         (model)    (code)              (you)      (model)    (code)      (code)               (code, over the protocol)
```

| Who | Does |
|---|---|
| The model | Drafts the tools: a name and one-sentence description for each, typed parameters (`str`, `int`, `float`, `bool`), the statements of each function body, declared permissions (`read_files`, `network`), the **names** of environment variables, and test cases. |
| Code | Writes everything around that: the imports, the signatures, the docstrings, the decorators, the **tool annotations** (read-only and open-world, worked out per tool from what its own code does), `mcp.run()`, the pinned `requirements.txt`, the README, the command that adds it, and every check. |

Model text is data: it is inserted into the file and the file is only ever run in the sandbox. Every tool returns text. The person's own rules, criteria and
failure behaviour are carried into the README word for word (a check fails if one is missing).

## The checks (all by code, none by asking a model)

**The server's own file** (`validate/mcp.py`, runs for the builder *and* for every server imported from outside):

| Fails | Warns |
|---|---|
| it does not parse; it never creates an `MCPServer`, defines no tool or never calls `mcp.run()`; the folder name differs from the server name | a tool without a description (docstring) |
| it starts other programs (`subprocess`, `os.system`), builds code from text (`eval`, `exec`, `__import__`) or loads native code (`ctypes`) | it can reach the network; it can write or delete files |
| a key or token is written in the code (OpenAI, Google, GitHub, Slack, AWS, a private key, a bearer token, a signed web token); **the report never repeats it** | it imports a package outside the standard library and `mcp` |
| | an environment variable read by a computed name, or all of them |
| | a name that is used but never defined or imported (a `NameError` waiting for the first call) |

**The builder's own rules** (`build/mcp_pipeline.py`, stricter because the model was told not to): a package outside the standard library, an undeclared or
not-offered permission (only `read_files` and `network` are offered; the code must not do more than the design declares), an environment variable that is not a plain
name or is read but not listed, a name used but never imported or defined, an import that is never used (the mark of a stub), a tool that returns simulated or
made-up data (placeholder, dummy, fake, mock, hard-coded, stub), a tool that never returns a value, invalid or repeated tool and parameter names, a test case that names
a tool the server does not have or whose arguments do not match the parameters (right keys, right types), an acceptance criterion with no test case, and no negative case.
One repair is allowed and is kept only if it is not worse.

## Run over the protocol, in the sandbox only

The server is model-written code, so it never runs on this machine. `build/mcp_protocol.py` copies it into a temporary folder with one **fixed harness**
(written by us, never by a model) and runs both in the locked container (no network, a read-only disk, no extra privileges, nobody) from the image
`skillforge-mcp:2.3.0`. The harness starts the server the way Claude Code would (over stdio), lists its tools, calls every test case and prints one line of JSON.
Code then compares: the tools listed must be exactly the designed tools, and each reply must **contain**, **equal** or **refuse** what the case expects.

- **The image is built once**, with a network, from two lines (`FROM python:3.13-slim` and `pip install mcp==2.3.0`): `python -m skillforge sandbox-build-mcp`.
  Testing a server never builds or pulls anything.
- **Not run is never passed.** No sandbox, no image, or a tool whose own code can reach the network (the box has no network) is reported "not run", and the build is a
  **DRAFT** with that reason. A DRAFT can still be kept (the existing "keep it anyway" box).
- A server that failed its checks is never started.
- Secrets: a server gets only the environment variable **names** the design declared, with a dummy value. No real secret is ever in the box.

## Facts settled by a real install (2026-11-20, `pip install mcp` in a scratch venv)

These replace the "sources disagree" note in [component-factory.md](component-factory.md).

- The official package is **`mcp` 2.3.0**. `FastMCP` is gone in 2.x: the class is **`MCPServer`**, `from mcp.server.mcpserver import MCPServer` (1.x had `mcp.server.fastmcp.FastMCP`).
- `MCPServer("name", instructions=...)`, `@mcp.tool()` (the docstring is the description, including `Args:` lines; the type hints become the input schema), `mcp.run()` serves over stdio.
- Client: `ClientSession` with `stdio_client(StdioServerParameters(command, args, env))`. Protocol version seen: 2025-11-25.
- `ToolAnnotations(read_only_hint, destructive_hint, idempotent_hint, open_world_hint, title)`, all defaulting to `None`.
- A tool that raises, or a call without a required argument, returns `is_error=True` with a short generic text (no stack trace); an unknown tool is also an error.
- **A server started through `stdio_client` does not inherit the caller's environment.** A secret reaches it only if passed by name in `env`.
- **A wrong-typed argument can be coerced** (the string "yes" was accepted for a `bool`), so a negative test case must rely on a tool *refusing a value*, not on a bad type.
- Adding it to Claude Code: `claude mcp add <name> -e KEY=value -- python <path>\server.py` (from `claude mcp add --help`, CLI 2.1.325). The app never runs it: it changes your Claude settings.

## A real run, and what it found

Two real builds with the configured model (Gemini), through the real API, on 2026-11-20, in a scratch data folder.

1. *Word tools:* 2 model calls, 16 seconds, status **ok**, 46 checks passed, 0 failed, 0 not run. The server was started and every case called in a real container.
2. *Weather tools* (a network tool and a key kept in `WEATHER_API_KEY`): it showed two real defects that tests with a mock model could not have found, both now fixed and covered by tests:
   - **Missing imports.** The model wrote `os.environ` and `urllib.request` in a tool body without importing them. Code reading could not see the network use, so the build said
     "ok" and the one case that ran passed only because its error fires before the first missing name. Fixed: a name that is never defined or imported fails the build, and the
     design prompt now says every import is written inside the body.
   - **A tool that pretended.** The repaired design imported `urllib` and then returned `"... 20 C (simulated)"` instead of calling the service. Fixed: an import that is never
     used fails, wording such as simulated, placeholder, dummy, fake, mock, hard-coded or stub fails, and the prompt says never to invent data.

   The third run wrote the real call (the key read by name, a real request, an error on an empty city) and the build was an honest **DRAFT**: "1 case(s) call current_weather, which can reach the
   network; the sandbox has no network, so they were not run".

## Using it

- **Web:** Builder, pick **MCP server**, describe it, answer only what is missing, approve, build, save. The Library has an **MCP servers** tab (export, install into a folder, compare, re-check).
- **API:** `POST /api/builds` with `"kind": "mcp"`; the library routes take `?kind=mcp`. `GET /api/kinds` lists it (`definition_file` `server.py`, `install_targets` `["folder"]`).
- **Install** copies the folder to a place you choose. Then run the command in its README to add it to Claude Code.
- **Risk diff** (`library diff`): a changed `server.py` is called "code that runs on your machine", a new capability (network, writes, commands) is **riskier**, a new tool is "something to look at",
  a new environment variable is **riskier**, and a removed tool or variable is safer.

## Limits (honest)

- **Not browser-tested:** the MCP flow in the web Builder and Library was not clicked through in a real browser (the typecheck, unit tests and the existing 39 browser checks cover the shared pages).
- **Not run against a live Claude Code:** `claude mcp add` was not run (it changes your settings). The server was run over the protocol by our harness, not by Claude Code.
- **Network tools stay DRAFT:** their cases cannot run in a box with no network. The real call is only read, not exercised.
- **Python only; tools only.** No TypeScript, no HTTP transport, no resources or prompts, no OAuth, no packages beyond the standard library, no file writes, no commands.
- **Test cases are as good as the model's expectations.** A case passes when the reply matches what the case says; a wrong expectation that the server happens to meet proves nothing.
- Passing the checks is not proof the server does what you meant: they read the file and run its cases.
