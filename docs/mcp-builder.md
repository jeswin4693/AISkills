# The MCP Builder (Component Factory, Phase 3)

Describe a small tool server in plain words and get a checked **Python MCP server** folder (for TypeScript see [mcp-builder-node.md](mcp-builder-node.md)): a `server.py` that code assembles from a design, a
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

Model text is data: it is inserted into the file, and the file is **tested** only in the sandbox (but you later run it without one, so it is checked hard: see below). Every tool returns text. The person's own rules, criteria and
failure behaviour are carried into the README word for word (a check fails if one is missing).

## The checks (all by code, none by asking a model)

Two readers, because a server is code that **you run on your own machine, with no sandbox**, once you add it to Claude Code.

**1. The library reader** (`validate/mcp.py`) runs for every server kept or imported, builder-made or not. It reads `server.py` with `ast`, by syntax.
It resolves imports and aliases first (`from os import system`, `import os as o`, `importlib`, `builtins`), then classifies every name the code touches,
**the import itself included**: it is the import that is flagged, not only the call.

| Fails | Warns |
|---|---|
| it does not parse; no `MCPServer`, no tool, no `mcp.run()`, more than one server; the folder name differs from the server name | a tool without a description |
| it starts programs (`subprocess`, `os.system`, `os.exec*`, `asyncio` subprocesses, `mcp.client`, `posix`, `nt` ...) | it can reach the network (`socket`, `urllib.request`, `ssl`, `asyncio.open_connection` ...) |
| code built from text or reaching Python's internals (`eval`, `exec`, `__import__`, `importlib`, `builtins`, `pickle`, `ctypes`, `globals`, `vars`, `getattr` with a computed name, dunder attributes, `.sys` / `.modules`) | it can write or delete files (any spelling of `open` with a writing or unknown mode, `os.write`, `shutil`, `sqlite3`, `tempfile`, `Path.write_text` ...) |
| a key written in the code, **also in pieces, as bytes or built with `+`** (OpenAI, Google, GitHub, GitLab, Slack, AWS, Stripe, PyPI, Hugging Face, npm, private keys, bearer and signed tokens); the report never repeats it | a package outside the standard library and `mcp`; an environment variable read by a computed name; a name used but never defined |
| an **encoding declaration or byte-order mark** that changes how Python reads the file (the checks would read something other than what runs) | `requirements.txt` naming a package other than the pinned SDK |
| **any other code beside `server.py`** (`colorsys.py`, `mcp/__init__.py`, `sitecustomize.py`, `.pth`, `.so`, `scripts/`, `bin/`): `python server.py` imports its neighbours first, and the checks never read them | |
| `requirements.txt` with an option, a URL or a VCS line (`--extra-index-url`, `git+https://...`) | |

**It cannot prove a file safe.** It is a best-effort reading by syntax, and someone determined may still hide something from it. Read a server you did
not build before you add it; the report says so on every pass.

**2. The builder's own rules** (`build/mcp_pipeline.py`), stricter because the model was told not to and code can hold it to that. A tool body may import
**only an allow-list** of safe standard-library modules (`json`, `re`, `math`, `datetime`, `collections`, `urllib.parse`, `hashlib`, ... the model is
told the list in its prompt): `os` only for `os.environ.get("NAME")`, `io` only for `StringIO` / `BytesIO`, `pathlib` only for names unless `read_files` is
declared, `urllib.request` / `http.client` / `ssl` only when `network` is declared, and no `print` (it would write into the protocol stream), `input`,
`getattr`, `setattr`. Anything else fails, so the spellings above cannot even be imported. It also fails: an undeclared or not-offered permission, an
environment variable that is not a plain listed name, a name used but never imported or defined, an import never used (the mark of a stub), a tool that
returns simulated or made-up data, a tool that returns nothing, invalid or repeated names, a test case that names a missing tool or whose arguments do not
match, an acceptance criterion with no case, no negative case, any other code or a `requirements.txt` other than exactly `mcp==2.3.0`. One repair is
allowed and is kept only if it is not worse.

**Names are data, never code.** A tool or parameter name is written into the file, so one that is not a plain identifier (an attempt to smuggle a statement
in) is refused **before** anything is written: the build fails with a plain message and no folder is created. Bodies are parsed and written out again, so a
comment cannot carry anything into the file and a multi-line string keeps its exact value. The `read_only_hint` / `open_world_hint` annotations are worked
out per tool from the tool's own code, aliases followed; a tool with a construct the analysis cannot follow gets **no hints at all**.

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
- **The verdict cannot be written by the server.** The harness and the server run in the same container, so the server can write into the harness's output.
  The grader therefore treats **cut output as a failure** (the real answer is written last and may be what was lost) and requires **exactly one** answer
  line (a second one was written by something else). A review forged a pass this way (260 lines of forged JSON written to PID 1's output) and it is now a
  test that runs in the real container and fails. The stronger design, not built, is to run the harness on the host and speak MCP over `docker run -i`, so the
  verdict is never produced inside the box.

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

## What an independent review found (2026-11-20), and what was done

Two fresh reviewers read this slice and the Plugin Builder without being told the code was correct. The MCP reviewer ran its attacks in a scratch folder (and,
for the sandbox forgery, in the real container); the first version of the checks was weaker than this document had said.

| Found | Done |
|---|---|
| An encoding declaration (`# coding: utf-7`) hid code from the checks but not from Python; any file beside `server.py` (`colorsys.py`, `mcp/__init__.py`) ran unchecked | Refused: non-UTF-8 declarations and byte-order marks; any other code in the folder |
| Plain alternate spellings of running a command passed (`from os import system`, `import os as o`, `importlib`, `builtins`, `asyncio` subprocess, `mcp.client`, `posix`, `nt`), and so did environment dumps, writes (`open(path, mode_variable)`, `os.open`, `sqlite3`, `shutil`), network (`asyncio.open_connection`, bare `urllib`) and keys written in pieces | The analyser resolves aliases and flags the import; the builder uses an allow-list; keys are folded before they are matched |
| The generated `read_only_hint=True` / `open_world_hint=False` were published for tools that did all of the above | Hints come from each tool's own analysed code, and are omitted when the code cannot be followed |
| A forged sandbox pass (flooding the harness's output) | Cut or doubled output is a failure; a live test proves it |
| A model-written tool name was written into the file as code, and a draft folder with that code could be saved | Names are validated before anything is written; no folder is created |
| `requirements.txt` was never read (`--extra-index-url`, VCS lines) | Read: only the pinned SDK is accepted |
| A docstring ending in a quote broke the file; a multi-line string was silently re-indented; the README said "does not write files" even when the code did | Fixed, with tests; the README now reports what was found and says it cannot prove it |

Not changed, said plainly: tools registered in another way are followed only for the usual `mcp.tool()(fn)` form; the made-up-data check is a list of words;
an `expect: error` case passes on any crash (a stub that always raises still fails the positive case); and a hostile server could still try the sandbox itself
(no network, a read-only disk, no capabilities, a non-root user, and the verdict hardening above are what stand in its way).

## Limits (honest)

- **Not browser-tested:** the MCP flow in the web Builder and Library was not clicked through in a real browser (the typecheck, unit tests and the existing 39 browser checks cover the shared pages).
- **Not run against a live Claude Code:** `claude mcp add` was not run (it changes your settings). The server was run over the protocol by our harness, not by Claude Code.
- **A server from outside cannot be proven safe by reading it.** The library reader is best-effort; read what you add.
- **Network tools stay DRAFT:** their cases cannot run in a box with no network. The real call is only read, not exercised.
- **Python only here; tools only.** The Node (TypeScript) half is its own kind, in [mcp-builder-node.md](mcp-builder-node.md). No HTTP transport, no resources or prompts, no OAuth, no packages beyond the standard library, no file writes, no commands.
- **Test cases are as good as the model's expectations.** A case passes when the reply matches what the case says; a wrong expectation that the server happens to meet proves nothing.
- Passing the checks is not proof the server does what you meant: they read the file and run its cases.
