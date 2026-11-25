# Design: GitHub links on the command line (slice AA)

Date: 2026-11-25. Status: **go-ahead from the user** ("Start with the next process to develop"), given before this design was shown; the choice of this item
over the other two on the roadmap (the canary scan, Node servers in plugins) and the calls below are mine, and the user can redirect. Size: a small slice
(one helper, five call sites, tests, docs), so this is the short design.

## Intent and why

The Repository page reads a **public GitHub link** as well as a folder, but every command-line command that takes a repository still needs a folder ("clone it
first", said in [github-link.md](../../github-link.md)). The roadmap lists "GitHub links on the command line" first among what is left. After this slice
`python -m skillforge graph stats https://github.com/owner/repo` works, like the page.

## Goals

- These commands take a link wherever they take a repository: `graph <command> <repo>` (all nine), `suggest <repo>`, `plan --repo`, `build --from-suggestions ... --repo`,
  and `library cite|recheck|refresh --repo`.
- **One downloader.** The link is read by the same code the page uses (`resolve_repo`, the snapshot store, the same limits and the same safety rules), never a second one.
- Say where the code came from, what was left out, and that git history is not downloaded; never print a path on this computer.
- **A folder behaves exactly as before**: same output, same errors, and no new import (so no new start-up cost) when the argument is a folder.
- A refused link or an unreachable GitHub is one plain `error: ...` line and exit code 2, never a traceback.

## Non-goals

- Private repositories, other hosts, `git clone`, ssh addresses; any change to what the web page does.
- `eval`, `validate`, `render` and `library import|export|install` take skill folders, not repositories: unchanged.

## Anti-goals (a failure even if it technically works)

- A command that answers "what changed" from a copy that is up to 15 minutes old. `library cite`, `recheck` and `refresh` always download a fresh copy, as the page's recheck does.
- `plan` on a link quietly reporting "no rules found": a copy holds only source files, so a repository's `CLAUDE.md` and `AGENTS.md` are **not downloaded**, and the output must say so.
- Notes that corrupt machine-readable output: with `--json` everything a person reads about the download goes to stderr, stdout stays the JSON.

## Constraints

- No new library; tests offline (the page's fake download stands in for GitHub); the graph package stays free of network code.
- Reading a folder must not import `skillforge.builder` (it pulls in the database layer): the helper imports it only for something that looks like a link.

## Approaches considered

| Approach | Trade-off | Verdict |
|---|---|---|
| **A. One helper in `cli.py`, called at each of the five places** | Small, explicit, the folder path is untouched | **Chosen** |
| B. Make `build_graph` itself accept a link | Every caller would get it, but the graph package would need the network and the builder | Rejected: the graph is deterministic and offline by rule |
| C. A separate `skillforge github ...` command family | No risk to existing commands | Rejected: it would duplicate nine commands for one idea |

## The design

- `_repo_arg(text, *, fresh=False) -> str` in `cli.py`. Text that does not look like a link is returned unchanged. A link is resolved with `resolve_repo(text, fresh=fresh)`
  (imported at that moment), a note is written to **stderr**, and the downloaded copy's folder is returned as text for the existing `build_graph(...)` calls.
- The note says: `Read owner/repo from GitHub (default branch or the branch): N source files kept, downloaded just now (or: a copy from N minutes ago).`, what was left out
  by reason, `Nothing was run.`, and `Git history is not downloaded, so facts that come from it are missing.` For `plan` it adds that `CLAUDE.md` and `AGENTS.md` are not downloaded.
- A `RepoError` (a new small exception in `cli.py`) carries the message of a `BuilderError` (a refused link, a missing repository, an unreachable GitHub); `main()` handles it
  in both branches (`graph` and the others) as `error: ...`, exit 2.
- Freshness: `cite`, `recheck`, `refresh` use `fresh=True`; `graph`, `suggest`, `plan` and `build` use the page's 15-minute reuse.
- Help texts for `repo` and every `--repo` say that a public GitHub link is accepted.

## What is left to the builder

The exact wording of the note lines, and where the small function that turns a download into those lines lives, as long as the rules above hold.

## How it is checked

- Offline tests with the page's fake download, running the real `cli.main`: a link read by `graph stats`, `suggest --facts-only` and `plan --no-ai`; a folder argument unchanged (same output
  as before, and the builder package not imported); a refused link and an unreachable GitHub as one `error:` line with exit 2 and no echo of what was typed; `--json` leaves stdout as JSON;
  `cite`, `recheck` and `refresh` download fresh each time while `graph` reuses a young copy; `plan` says the rules files are not downloaded.
- Deliberate breaks of each rule, a real run of the real command against this repository's public link, then the full suites.
- No independent review is planned for a slice this small that adds only an adapter over code already reviewed; it is offered at the end with its cost.

## Honest limits to state in the docs

A link is public repositories only, a copy has no git history and no `CLAUDE.md`/`AGENTS.md`, an idea's evidence recorded from a link by `build --repo` is looked up in the copy that is current when the
build ends (the command line has no stored run to pin a copy), and `cite` on a link records no commit.
