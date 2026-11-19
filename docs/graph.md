# Understand: the repository graph

`skillforge graph ...` reads a repository and remembers its functions, classes, imports and calls as a graph.
**No AI is involved in building it.** Parsers and git do the work, so every answer can be checked, and
building costs nothing and needs no key. The design follows the author's own Repository Intelligence
Assistant (RIA): evidence only, honest confidence labels, an incremental cache. This version adds what RIA
does not have: function-level call edges from real parsers.

## What goes into the graph

| Thing | Source |
|---|---|
| Files, functions, methods, classes | Python: the standard `ast` module. Everything else: tree-sitter, in 45 languages at three honest levels (full, standard, basic). See [languages.md](languages.md). |
| Imports, resolved to repository files | per-language rules (Python relative and absolute, TS relative, `index`, `.js` to `.ts`, `@/`, re-exports, `export *`) |
| Calls, resolved to the function they reach | scope, imports, `self` / `this`, `super`, inheritance, namespaces |
| Git history | churn per file, files that change together (co-change) |
| Body structure hash per function | used to find duplicates (names and literal values are ignored) |

## How sure is each link

- **resolved**: proven by scope or imports.
- **guess**: only a unique *class method* name matched. Always shown as `[guess]` and never counted toward
  the risk score or test coverage.
- **ambiguous / external / unresolved**: counted but never turned into an edge. Calls on unknown receivers
  with built-in names (`get`, `push`, `join`, ...) are never matched by name.

## Memory

Parsed files are cached by size and modification time under the per-user data folder
(`%LOCALAPPDATA%\skillforge`, `~/Library/Application Support/skillforge`, or `$XDG_DATA_HOME/skillforge`;
override with `SKILLFORGE_DATA_DIR`). Nothing is ever written into the repository being analysed. A repeat
run re-parses only changed files (2,077 files / 250k lines: 2.6 s from scratch, 0.8 s cached).

## Commands

Run from `backend/`. Add `--json` for machine-readable output, `--no-cache`, `--no-history`, `--focus <dir>`.

```powershell
python -m skillforge graph stats      <repo>
python -m skillforge graph symbols    <repo> <text>
python -m skillforge graph callers    <repo> <function> [--depth 2]
python -m skillforge graph callees    <repo> <function> [--depth 2]
python -m skillforge graph impact     <repo> <file-or-function> [--depth 3]
python -m skillforge graph path       <repo> <from> <to>
python -m skillforge graph hotspots   <repo>
python -m skillforge graph duplicates <repo> [--min-size 30] [--min-lines 3]
python -m skillforge graph dead       <repo>
```

A function can be named `name`, `Class.method` or `file::name`. An ambiguous name lists the candidates.

## Known limits (stated, not hidden)

- Static analysis cannot see dynamic calls, reflection, or code generated at run time.
- A method call on a variable whose type is unknown (`thing.run()`) is only a guess, and is dropped when
  several classes share the method name. Using type annotations to resolve these is planned.
- Duplicate detection finds structural clones (same structure, different names or values). Near-duplicates
  with a few changed lines are not found yet.
- "Dead code" results are candidates: public APIs, framework entry points and dynamic use are invisible.
- How deeply a language is understood depends on its level (full, standard, basic; see
  [languages.md](languages.md)). File types that are not programming languages are skipped, not guessed.
- Some folders are never read: dependencies, caches and build output (`node_modules`, `.venv`, `dist`, `build`, `out`,
  `target`, `vendor`, ...). A folder named `build`, `dist` or `out` **is** read when it is a Python package (it has an
  `__init__.py` directly inside): this project's own `skillforge/build/` is one, and it was invisible until this was
  found by trying the plan on this repository. Build output in any other layout that happens to look like source is still
  skipped, and a project that keeps real source in a folder with another name on the list (say a Go package called
  `vendor`) is not read there.
- tsconfig path aliases other than `@/` and `~/`, and monorepo workspace packages, are not resolved.
- Co-change needs git, and ignores commits that touch more than 40 files.
