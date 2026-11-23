# Phase 3b: the MCP Builder for Node (TypeScript), 2026-11-23

Goal: describe a small tool server in plain words and get a checked **TypeScript MCP server** folder, started in the sandbox and called over the real MCP protocol
before the build can say "ok". Same rules as the Python half ([docs/mcp-builder.md](../../mcp-builder.md)): the model drafts tools, code writes everything around them, every
check is code, the server is only ever run in the sandbox, and the report says what did not run.

## Facts settled by real runs (Node 24.13, `@modelcontextprotocol/server` 2.4.0, 2026-11-23, scratch folder)

- The official TypeScript SDK is now **v2**: `@modelcontextprotocol/server` (and `/client`) 2.4.0, the stable line; `@modelcontextprotocol/sdk` 1.32.2 is the old one. It needs `zod` 4.
- Names that work: `new McpServer({name, version}, {capabilities: {tools: {}}})`, `server.registerTool(name, {description, inputSchema: z.object({...}), annotations: {readOnlyHint, openWorldHint}}, handler)`,
  `await server.connect(new StdioServerTransport())` (`@modelcontextprotocol/server/stdio`). Client: `Client`, `StdioClientTransport` from `@modelcontextprotocol/client` and `/stdio`.
- **`node server.ts` runs a TypeScript file directly** (types are stripped, no build step) on Node 24, but only with a `package.json` beside it that says `"type": "module"`; without it Node reads the file as CommonJS and fails.
- A wrong-typed or missing argument is **refused by the schema** (the Python SDK coerced it). A tool that throws gives `isError` with **its own message** (Python: a generic text). An unknown tool is a protocol error, not `isError`.
- **Node's permission model works and is real:** `node --permission --allow-fs-read=<folder> server.ts` runs the server, and a write, a child process and a read outside the folder each fail with `ERR_ACCESS_DENIED`.
  It does not limit the network or environment variables. This is the runtime guard the Python half does not have: Node itself, not our reading of the code, stops a server from writing files or starting programs.
- The server's whole runtime is three packages (`core`, `server`, `zod`), no install scripts, only `registry.npmjs.org`: a 1.5 KB `package-lock.json`, accepted by `npm ci` under any package name.
- tree-sitter's `typescript` grammar is already a dependency of the graph and needs no download.

## Decisions (mine, to be corrected)

1. **A separate kind**, `mcp-node` ("MCP server (Node)", `library-mcp-node`, definition file `server.ts`). A kind is a registry key, so the library, the API, the Builder page and the Library tabs pick it up, and the plugin composer
   (which only lists the `mcp` kind) cannot include one by accident. Plugins carrying Node servers are **not** in this slice: a plugin cannot run `npm ci`, and a hook that does is not in the catalogue.
2. **The model writes function bodies and a list of imports as data.** Code writes the file: `import` lines only from a table of allowed modules and names (`node:crypto` `createHash`, `node:path`, and `node:fs` read functions only when `read_files` is declared),
   the zod schema from typed parameters, the handler, the annotations, `server.connect`. A body may use only: its parameters, what it declares, the imported names, and an allow-list of globals (`Math`, `JSON`, `Map`, `Set`, `RegExp`, `URL`, `fetch` only with `network`, `process.env.NAME` only for a listed name, ...).
   A property name from a deny-list (`constructor`, `__proto__`, `prototype`, `call`, `apply`, `bind`, ...) fails anywhere, also as a string. `console` is refused (stdout is the protocol stream).
3. **The server runs under `--permission`** in the sandbox test and in the README command, so what the checks claim is also enforced by Node. A server that declares `read_files` is told which flag to add and why.
4. **Pinned, with a lockfile:** the folder has `package.json` (exact versions, no `scripts`, `"type": "module"`) and the lockfile; the README says `npm ci --ignore-scripts`. The image is built once from the same pins:
   `python -m skillforge sandbox-build-mcp-node` (`skillforge-mcp-node:2.4.0`, `node:24-slim`).
5. **Two readers, as in Python:** `validate/mcp_node.py` reads any imported `server.ts` by tree-sitter (what runs programs, builds code from text, reaches the network, writes files, reads the environment; any other code beside it, an install script, a package other than the pinned two),
   and the builder's own stricter rules (`build/mcp_node_pipeline.py`) hold the model to the allow-lists. Neither can prove a file safe; the report and README say so.
6. **The harness is ours** (a fixed `.mjs`, the same verdict hardening as the Python one: cut or doubled output is a failure).

## Not in this slice, on purpose

Plugins that carry Node servers, HTTP transport, resources and prompts, OAuth, packages beyond the pinned two, a TypeScript compile or type check (the file has typed signatures, bodies are plain JavaScript statements), `eval` for servers, `claude mcp add` run for you.

## Order

1. Constants, lockfile, image and its build command. 2. The reader (`validate/mcp_node.py`) with tests. 3. The design, the file writer and the builder's checks. 4. The protocol harness and grading. 5. The kind, registration, risk diff and CLI.
6. Real runs: the image built, a generated server run in the real container, the exact `claude mcp add` command tried in an isolated config folder, one real model build. 7. Web pages. 8. Docs, roadmap, memory, an independent review.
