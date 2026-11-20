# Component Factory, Phase 3: the MCP Builder v1, Python (short plan)

> Executed inline with TDD, one commit per task. Spec: [docs/component-factory.md](../../component-factory.md) (Phase 3, "Decisions", "Rules this adds", "Format facts").

**Goal:** describe a tool server in plain words and get a checked **Python MCP server** folder: a `server.py` that code assembles from a design, a pinned `requirements.txt`, the person's tests, a README with the exact commands that add it to Claude Code, kept in its own library, exported and installable to a folder, and **run over the real MCP protocol inside the sandbox** (fails closed).

**SDK facts (settled 2026-11-20 by a real install, `pip install mcp` in a scratch venv; they replace the "sources disagree" note):**
- The official package `mcp` is at **2.3.0**. `FastMCP` is **gone** in 2.x: the class is `MCPServer`, `from mcp.server.mcpserver import MCPServer` (1.x had `mcp.server.fastmcp.FastMCP`).
- `mcp = MCPServer("name")`, `@mcp.tool()` (the docstring is the tool description, the type hints become the input schema), `mcp.run()` serves over stdio.
- A client is `ClientSession` with `stdio_client(StdioServerParameters(command, args, env))` (`from mcp import ClientSession, StdioServerParameters`, `from mcp.client.stdio import stdio_client`). Protocol version seen: 2025-11-25.
- `@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))` (`from mcp.types import ToolAnnotations`); fields `title`, `read_only_hint`, `destructive_hint`, `idempotent_hint`, `open_world_hint`, all default `None`.
- A tool that raises, or is called without a required argument, returns `is_error=True` with a short generic text, not a stack trace.
- **A server started through `stdio_client` does not inherit the caller's environment** (a variable set in the parent was `(no var)` in the child): a secret reaches a server only when it is passed by name in `env`.
- Adding to Claude Code: `claude mcp add <name> -e KEY=value -- python <path>\server.py` (read from `claude mcp add --help`, CLI 2.1.325). The app never runs it.

**Decisions:**
- Kind `mcp`, label "MCP server", library `library-mcp`, definition file `server.py`, install target `("folder",)` only (nothing writes Claude's settings or `.mcp.json`), conversational.
- **The model drafts, code assembles.** The draft is a name, a description, tools (name, description, typed parameters `str|int|float|bool`, a body of Python statements, read-only flag), declared permissions (`read_files`, `network`), environment-variable **names**, and test cases (tool, arguments, an expectation). Code writes the imports, the signatures, the decorators, the annotations and `mcp.run()`. Every tool returns `str`.
- **Offline first.** A tool that uses the network needs `network` declared, is flagged riskier, and its test cases are reported "not run" (the sandbox has no network). No file writes, no commands, no dynamic code, no native code, no packages beyond the standard library and `mcp` (builder rules, failures). A server imported from outside gets the same dangerous-thing failures (commands, dynamic code, native code, a hard-coded secret, a server that does not parse) and **warnings** for the rest (network, writes, third-party packages), the way skill scripts are treated.
- **Secrets are names only.** The requirement text is scanned; the server may read an environment variable only by a string-literal name it declared; a key-shaped literal in the code fails the check.
- **Tested over the protocol, by code.** One fixed harness (not model-written) starts `python /skill/server.py`, lists the tools, calls each case and prints JSON; code compares tool names with the design and each reply with the case's expectation (`contains`, `equals`, `error`). Image: `skillforge-mcp:2.3.0`, built once with network from `docker/mcp-python.Dockerfile`, never pulled at run time. No sandbox or no image means "not run", never "passed", and the build is a DRAFT.
- Models: the design call uses `Task.DESIGN` like the agent; one repair, kept only if not worse.

**Out of scope:** TypeScript, HTTP transport, MCP resources and prompts (tools only), OAuth, running a built server against a live Claude Code, `claude mcp add` (the person runs it), plugin v2 bundling (Phase 4), `eval` for servers.

**Global constraints:** Python from `backend/`; tests offline (a live sandbox test skips without the image); no new backend library (`mcp` is only in the sandbox image and in the generated `requirements.txt`); skill, agent and plugin behaviour unchanged; commits end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus
- Model-written code can never reach the person's machine unchecked: every dangerous construct fails the build and fails an import (task 1, 2).
- The server is only ever *run* through the sandbox; a missing sandbox or image reads "not run" (task 3).
- Declared permissions and environment variables equal what the AST shows; nothing is claimed that code did not compute (task 1, 2).
- No secret value enters a session or a file: names only (task 1, 2).
- An imported zip with a hostile `server.py` is refused or warned exactly as the checks say (task 1).

### Task 1: the server's own checks
`validate/mcp.py`: `check_server_py(files, folder)` (registered in `validate/__init__.py` for kind `mcp`), `mcp_name_of(files)`, `analyze_server(source)` (tools, imports, capabilities, environment names). Tests: a good server passes; syntax error, no `MCPServer`, no tool, name differing from the folder fail; commands, dynamic code, native code, a hard-coded key fail; network and writes and a third-party package warn; environment access by a non-literal or an undeclared name warns; every registered kind still has a definition check.

### Task 2: design, assemble, build
`build/mcp.py` (`McpDraft`, `McpDefinition`, prompts, `design_mcp`, `assemble_mcp`, `render_mcp_files`), `build/mcp_pipeline.py` (`check_mcp`, `build_mcp_from_spec`, report), `kinds/mcp.py` and the registry. Tests with the mock model: exact files, the person's words carried in, one repair kept only if not worse, the builder-only rules (third-party import, writes, undeclared network) failing, secrets as names.

### Task 3: run it over the protocol in the sandbox
`docker/mcp-python.Dockerfile`, `sandbox/images.py` (the image and its build command), `build/mcp_protocol.py` (the fixed harness, the runner, the grader). Tests with a fake runner for every outcome (pass, wrong reply, missing tool, crash, timeout, no sandbox, no image); one live test that skips without the image. Then build the image and run a real server in the real sandbox.

### Task 4: library, API, web
Risk diff reads `server.py` (capabilities, tools added, environment names). `/api/kinds` lists `mcp`; sessions, library routes, import, export and install work for it; the Builder picker and the Library tab list it; wording that says "skill" on these pages. Tests: API per kind, risk diff, hostile zip. Then typecheck, unit tests, build and the browser suite (ports free first).

### Task 5: verify, document, finish
A real build through the API with a real model if a key is set, otherwise the mock; the built server run in the real sandbox. Docs (`docs/mcp-builder.md`, component-factory, roadmap row R, api, library, validate, build, README, CLAUDE.md), full runs, one review (cost stated first), commit, push, memory notes.
