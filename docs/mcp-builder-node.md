# The MCP Builder for Node (Component Factory, Phase 3b)

Describe a small tool server in plain words and get a checked **TypeScript MCP server** folder: a `server.ts` that code assembles from a design, a `package.json` and a lockfile with exact versions, the test
cases, a README with the exact command that adds it to Claude Code, and a report. The server is **started in the sandbox and called over the real MCP protocol** before the build can say "ok". It is the
Node half of [the MCP Builder](mcp-builder.md) (same questions, same rules, same grading); plan: [superpowers/plans/2026-11-23-mcp-node-phase-3b.md](superpowers/plans/2026-11-23-mcp-node-phase-3b.md).

It is its own kind, `mcp-node` ("MCP server (Node)", library `library-mcp-node`, definition file `server.ts`), so the Builder page, the Library tabs, the API and the CLI-less library commands pick it up as they
picked up the Python kind. A Python server and a Node server never share a library.

## Facts settled by real runs (Node 24.13, `@modelcontextprotocol/server` 2.4.0, 2026-11-23)

- The official TypeScript SDK is now **v2**: `@modelcontextprotocol/server` (and `/client`) 2.4.0, the stable line, which needs `zod` 4. The old `@modelcontextprotocol/sdk` (1.32.2) is the previous line.
- Names that work: `new McpServer({name, version}, {capabilities: {tools: {}}, instructions})`, `server.registerTool(name, {description, inputSchema: z.object({...}), annotations: {readOnlyHint, openWorldHint}}, handler)`,
  `await server.connect(new StdioServerTransport())` from `@modelcontextprotocol/server/stdio`. A tool with no parameters is registered without `inputSchema`. Client: `Client`, `StdioClientTransport`.
- **`node server.ts` runs TypeScript directly** (types are removed, nothing is compiled), but only with a `package.json` beside it that says `"type": "module"`: without it Node reads the file as CommonJS and fails to start.
  That also means only syntax that can be removed works: an enum, a namespace, a decorator or a constructor parameter with a modifier does not start, so the checks fail them.
- **A wrong-typed or missing argument is refused by the schema** (the Python SDK coerced a string into a bool), a tool that throws gives `isError` with **its own message** (Python: a generic text), and an unknown tool is a protocol error.
- **Node's permission model works, with a gap.** `node --permission --allow-fs-read=<folder> server.ts` runs the server, and in the real container a file write through `fs`, a child process and a read outside the folder each failed with `ERR_ACCESS_DENIED`, also when the
  code was written to try (`tests/test_mcp_node_build.py`). It does not limit the network or environment variables, and **it does not cover everything: `node:sqlite` creates a database file with no write grant** (found by the first independent review, pinned by a live test). So it is a second line of
  defence the Python half does not have, not a proof; the reader counts `node:sqlite` as writing files and `process.getBuiltinModule` as loading code while running, and a generated tool cannot import either.
- The server's whole runtime is **three packages** (`core`, `server`, `zod`), no install scripts, all from `registry.npmjs.org`: a 1.5 KB lockfile that `npm ci --ignore-scripts` installs under any package name.
- **Real Claude Code (2.1.325, Windows):** `claude mcp add word-tools -e WORDS_KEY=... -- node --permission --allow-fs-read=<folder> <folder>/server.ts` (the README command with real paths, tried in an isolated config folder, so your settings were not touched) was
  accepted and `claude mcp list` showed it **Connected**; a real session (`claude -p --mcp-config`, haiku) called its `word_count` tool and got the right number.

## How it works

```
words -> extract -> CHECKLIST -> ask -> APPROVE -> design -> assemble -> CHECKS -> repair x1 -> RUN IN THE SANDBOX -> files + report
         (model)    (code)              (you)      (model)    (code)      (code)               (code, over the protocol)
```

| Who | Does |
|---|---|
| The model | Drafts the tools (a name and one sentence each, typed parameters `str`, `int`, `float`, `bool`, the statements of each function body), the **list of imports as data** (`{"module": "node:crypto", "names": ["createHash"]}`), declared permissions (`read_files`, `network`), the **names** of environment variables, and test cases. |
| Code | Writes everything around that: the import lines, the zod schema, the handler that turns the string a body returns into the MCP reply, the **tool annotations** (read-only and open-world, worked out per tool from what its own code does), the transport, `package.json`, the lockfile, the README and every check. |

A body is wrapped in `await (async (): Promise<string> => { ... })()`, so a body is only statements and cannot import, register or export anything. Comments are removed from a body before it is written. A body that closes its function early to put code beside it
(`});` ... `(async () => {`) is refused: each body, alone, must parse as exactly the statements of one function.

## The checks (all by code, none by asking a model)

Two readers, as in Python, because a server is code you run on your own machine.

**1. The library reader** (`validate/mcp_node.py`) runs for every Node server kept or imported, builder-made or not. It reads `server.ts` with tree-sitter's TypeScript grammar (already a dependency of the graph, no download), by syntax,
resolving imports and aliases first (`import * as fs from "node:fs"`, `import { exec as e } from "child_process"`, `const w = fs.writeFileSync`, `const { exec } = cp`, `globalThis.fetch`).

| Fails | Warns |
|---|---|
| it does not parse (a file that cannot be read is never a pass); no `McpServer`, no tool, no connected transport, more than one server; the folder name differs from the server name | a tool without a description |
| it starts programs (`child_process`, `cluster`, `worker_threads`, `new Worker`, `process.binding`, `process.dlopen`) | it can reach the network (`fetch`, `http`, `net`, `WebSocket`, `axios` ...) |
| code built from text or loaded while running (`eval`, `Function`, `import()`, `require`, `vm`, `WebAssembly`, `setTimeout("...")`, a property chosen by a computed name on `globalThis`, a module passed around as a value) or reaching the language's internals (`.constructor`, `__proto__`) | it can write or delete files (`fs.writeFileSync`, `rm`, `open` with a writing mode ...); it can read them |
| a key written in the code, **also in pieces** (`"sk-" + "..."`); the report never repeats it | a package other than Node's own modules, the SDK and zod; an environment variable read by a computed name or all of them (`{...process.env}`); a name used but never defined (`require` and `__dirname` do not exist in an ES module) |
| syntax `node server.ts` cannot run (enum, namespace, decorator, parameter property) | writing to standard output (`console.log`, `process.stdout`): it is the protocol channel and a message there breaks the connection |
| **any other code beside `server.ts`** (`.js` `.mjs` `.ts` `.node` `.wasm`, `scripts/`, `bin/`), a **`node_modules`** folder, an **`.npmrc`** or similar | a `package.json` that installs more than the pinned packages, or has `overrides`, `imports`, `exports`, `bin` |
| a `package.json` with **`scripts`** (npm runs `preinstall`, `install`, `postinstall` and `prepare` by itself), one without `"type": "module"`, or none | a `package-lock.json` that is not the one this builder writes, or none |

**It cannot prove a file safe.** It is a best-effort reading by syntax. Read a server you did not build before you add it; the report says so on every pass.

**2. The builder's own rules** (`build/mcp_node_pipeline.py`), stricter because the model was told not to and code can hold it to that:

- a tool body may use only **its parameters, what it declares, the names it imports and an allow-list of globals** (`Math`, `JSON`, `Map`, `Set`, `RegExp`, `URL`, `Buffer`, `Error` ..., and `fetch` only with `network` declared); `process` only as `process.env.NAME` for a listed name;
  no `console`, `require`, `import()`, `eval`, `Function`, `globalThis`, `setTimeout`, `Date` (a tool must be deterministic), `Reflect`, `Proxy`, `Symbol`;
- imports come only from a table of module and names (`node:crypto` `createHash` and `createHmac`, `node:path` names, and `node:fs` read functions only when `read_files` is declared): a module or name outside it fails, and an import name is validated before it is written as code;
- a property called `constructor`, `__proto__`, `prototype`, `call`, `apply`, `bind`, `getPrototypeOf`, `defineProperty` ... fails anywhere, **also as a string** (`x["constructor"]`), and reaching a property by a computed name is a warning (use a `Map`);
- an undeclared or not-offered permission, an environment variable that is not a plain listed name, an import never used (the mark of a stub), a tool that returns simulated or made-up data, a tool that returns nothing, invalid or repeated names (a parameter may not be a JavaScript keyword),
  a test case that names a missing tool or whose arguments do not match, an acceptance criterion with no case, no negative case, and `package.json` and the lockfile other than exactly what the builder writes. One repair is allowed and is kept only if it is not worse.

**Names are data, never code.** A parameter or import name is written into the file, so one that is not a plain name (an attempt to smuggle a statement in) is refused **before** anything is written and no folder is created.

## Run over the protocol, in the sandbox only

The server is model-written code, so it never runs on this machine. `build/mcp_node_protocol.py` copies it into a temporary folder with one **fixed harness** (a `.mjs` written by us, never by a model) and runs both in the locked container (no network, a read-only disk, no extra privileges,
nobody) from the image `skillforge-mcp-node:2.4.0` (`node:24-slim` with the pinned SDK, the client the harness uses and zod, installed in `/opt/sdk` and linked at `/node_modules`; built once, with a network: `python -m skillforge sandbox-build-mcp-node`).
The harness starts the server the way Claude Code would, **as `node --permission --allow-fs-read=<folder> server.ts`**, lists its tools and calls every test case. The grading is the Python half's, unchanged: the tools listed must be exactly the designed tools, each reply must **contain**, **equal** or **refuse**
what the case expects, cut or doubled output is a failure, and a missing sandbox or image, or a tool whose own code can reach the network, is reported as **not run** and the build is a **DRAFT**, never "ok".

One honest difference from a person's machine: in the image the packages are outside the folder, so the run also allows reading `/opt/sdk` and `/node_modules`. On your machine they are inside the folder.

## Using it

- **Web:** Builder, pick **MCP server (Node)**, describe it, answer only what is missing, approve, build, save. The Library has a tab for it (export, install into a folder, compare, re-check).
- **API:** `POST /api/builds` with `"kind": "mcp-node"`; the library routes take `?kind=mcp-node`. `GET /api/kinds` lists it (`definition_file` `server.ts`, `install_targets` `["folder"]`).
- **Install** copies the folder to a place you choose (it does not run `npm`). Then follow the README: `npm ci --ignore-scripts` in the folder, and the one `claude mcp add` command.
- **Risk diff** (`library diff`): a changed `server.ts` is "code that runs on your machine", a new capability (network, writes, programs) is **riskier**, a new tool is "something to look at", a new environment variable is **riskier**, a construct the checks cannot follow is **riskier**,
  and for `package.json`: a new `scripts` entry, a new or changed dependency, an `overrides` key, and a lockfile that stopped being the pinned one are **riskier**; any other code file beside the server is new code that runs.

## Limits (honest)

- **Not in a plugin.** A plugin cannot run `npm ci`, and a hook that does is not in the catalogue, so the plugin composer lists only Python servers. Node servers in plugins are a later slice.
- **TypeScript in the file, JavaScript in the bodies.** The signatures are typed and the file runs as TypeScript, but the model writes plain JavaScript statements and nothing runs the TypeScript compiler (`tsc`), so a type error is not found.
- **Node 24 or newer** (tested with 24.13): `node server.ts` and `--permission` are recent. Older Node versions do not start it.
- **`--permission` does not limit the network or environment variables**, so a server that declares `network` can still send a secret it reads; and it only helps when you use the command from the README.
- **Tools only.** No HTTP transport, no resources or prompts, no OAuth, no packages beyond the pinned two, no file writes, no commands.
- **Test cases are as good as the model's expectations**, and passing the checks is not proof the server does what you meant: they read the file and run its cases.
