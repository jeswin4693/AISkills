# Slice V: evidence-linked skills and `library recheck` (plan)

Written 2026-11-23. This is the second differentiator in [docs/differentiators.md](../../differentiators.md), item 1: a skill
that names code carries **evidence** (references to graph nodes with the facts the graph had), and a later **recheck**
says what changed in that code. The Suggest step already refuses to cite a node that does not exist; this extends the
rule from the day a skill is made to every later day.

## What it is, in one paragraph

`evidence.json` sits in the skill's folder (so it is versioned, hash-protected and exported with the skill). It lists
references: a file, or a function/method/class (`path::Class.method`). For each, the graph's facts at that time are stored:
for a symbol its kind, line range, whether it is exported, the hash of its body *structure* (the graph's `shape`), its
size, a hash of its source text, and its **resolved** callers and callees (guesses never count, as everywhere in this
project); for a file its language, line count, symbol names and the files that import it or that it imports.
`library recheck NAME --repo PATH` builds today's graph and compares. Nothing is run, no model is called.

## Decisions (my calls, to be corrected if wrong)

| Question | Call | Why |
|---|---|---|
| Where is it stored? | `evidence.json` in the package, like `spec.json` | travels with export/rollback; the manifest hash makes it tamper-evident; no new storage |
| What counts as a change? | missing / moved (a candidate, never applied) / changed (structure, callers, callees, exported, a file's symbols or importers) / edited (same structure, text differs) / holds | the graph facts are deterministic; a literal changing is only "edited" because it is noisy |
| Does a moved line count? | No, a line number moving alone is not a change | every edit above a function moves it |
| Languages with no call resolution ("basic") | callers and callees are **not measured** and said so, never "no callers" | the project rule: never claim more than the level gives |
| Does it say the skill is right? | No. It checks that **cited facts still hold**, not that the skill's advice is good | said in the report |
| How is evidence attached? | (1) `build --from-suggestions R --pick N --repo PATH` carries the idea's cited nodes; (2) `library cite NAME --repo PATH [--ref X] [--from-text]` by hand or from the code names in the skill's own text (the Task Plan's mention finder; an ambiguous name is listed, never picked) | the two real entry points; the Builder page has no repository yet |
| Accepting what changed | `library refresh NAME --repo PATH` records today's facts as a new version; no new version when nothing differs | a person reviewed the skill against the changed code first |
| Privacy | the file names a private repository's files and functions: `export --without-evidence` leaves it out, plugins never ship it, the CLI says so | same reasoning as `spec.json` |
| Web page | not in this slice | the person asked earlier for effort to go to the generator; the CLI and API come first |

## Not in this slice (said plainly)

A claim like "only called from `main`" is not parsed out of prose: only the references are checked. The Builder
sessions do not attach evidence (the UI has no repository input). Text that quotes a literal value is covered only by
the `edited` level. The graph is as deep as the language: calls are resolved for full and standard languages only.

## Steps (tests first, each fails before the code exists)

1. `evidence/`: model, snapshot from a graph, recheck against a graph. Unit tests on small repositories.
2. The static check: a malformed `evidence.json` fails an import; no file means no row.
3. Library: `cite`, `refresh`, `recheck`, export without evidence, plugin `LEFT_OUT`.
4. CLI: `library cite|recheck|refresh`, `build --repo`, exit codes, `--json`.
5. API: read the recorded evidence; recheck (local only, off in the hosted version).
6. Docs: `docs/evidence.md`, README, roadmap row V, CLAUDE.md, memory. Real run on this repository.
7. One independent review, with hostile `evidence.json` files among the inputs.
