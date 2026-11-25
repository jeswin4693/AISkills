# GitHub links on the command line (slice AA)

Until now the command line needed a folder ("clone it first"); only the web page read the link of a public GitHub repository. Now **every command that takes a repository
takes the link as well**. It is the same downloader the page uses (`resolve_repo`, the snapshot store and its safety rules and limits: [github-link.md](github-link.md)),
so there is no second one to trust. Design: [superpowers/specs/2026-11-25-cli-github-links-design.md](superpowers/specs/2026-11-25-cli-github-links-design.md),
plan: [superpowers/plans/2026-11-25-cli-github-links-slice-aa.md](superpowers/plans/2026-11-25-cli-github-links-slice-aa.md).

```powershell
cd backend
python -m skillforge graph stats       https://github.com/owner/repo
python -m skillforge graph hotspots    https://github.com/owner/repo/tree/some-branch --json
python -m skillforge suggest           https://github.com/owner/repo --facts-only
python -m skillforge plan "rename the function parse" --repo https://github.com/owner/repo --no-ai
python -m skillforge build --from-suggestions report.json --pick 1 --repo https://github.com/owner/repo
python -m skillforge library cite|recheck|refresh NAME --repo https://github.com/owner/repo
```

| Command | Takes a link in | Copy used |
|---|---|---|
| `graph stats\|symbols\|callers\|callees\|impact\|path\|hotspots\|duplicates\|dead` | the `repo` argument | a copy up to 15 minutes old is reused |
| `suggest` | the `repo` argument | the same |
| `plan` | `--repo` | the same |
| `build --from-suggestions ...` | `--repo` | the same |
| `library cite`, `library recheck`, `library refresh` | `--repo` | **always downloaded fresh**: what they answer is what the code is now |

`eval`, `validate`, `render` and `library import|export|install` work on skill folders, not repositories, and are unchanged.

## What you see

Everything a person reads about the download goes to **stderr**, so `stdout` is what the command printed before and `--json` is still pure JSON:

```
Read jeswin4693/AISkills from GitHub (default branch): 273 source files kept (2.5 MB), downloaded just now.
Left out: 72 files in languages or formats the graph does not read, 4 paths too long for this disk.
Nothing was run. Git history is not downloaded, so facts that come from it (how often a file changes) are missing.
```

A copy that was reused says how old it is (`a copy from 4 minutes ago`). `graph stats` shows `Repository: owner/repo` (and `(branch NAME)`) instead of the folder the copy is kept in. `plan` adds one line:
`CLAUDE.md and AGENTS.md are not downloaded, so the rules they hold are not read.`

A link that is refused (another site, `http`, a login, a port, a deeper path), a repository GitHub does not have (or a private one), and GitHub being out of reach are each **one line**, `error: ...`, with
exit code 2 and no traceback; what was typed is not repeated.

A folder behaves exactly as before: same output, same errors, and `skillforge.builder` (which pulls in the database layer and costs about 0.7 seconds to load) is imported **only for something that looks like a link**.

## Limits (said plainly)

- **Public repositories only**, and it needs a network. No ssh addresses, no other hosts, no `git clone`.
- **No git history.** Facts that come from it (how often a file changes, the commit) are missing, and a copy has **no `CLAUDE.md` or `AGENTS.md`** (only source files are downloaded), so `plan` reads no rules from a link and says so.
- **`build --repo LINK`** records the idea's evidence from the copy that is current when the build ends. The web page can pin the exact copy an idea was made from (a run records it); the command line has no stored run, so if the
  copy is older than 15 minutes, or the repository has changed since the suggest report was made, the places are looked up in newer code. `library cite` on a link records no commit.
- **Windows path length.** A file whose path would not fit on the disk is skipped and counted as `paths too long for this disk`; a deep data folder (for example a scratch folder inside another long path) makes that count larger.
- `library cite|recheck|refresh --repo LINK` print the link you typed back in their hints, which is your own text.

## Checked

- **Tests** (`tests/test_cli_github.py`, 40 tests, offline: the page's fake download stands in for GitHub and the real `cli.main` runs): each command above reads a link; the note goes to stderr and `--json` stays JSON; a branch link names its branch;
  a young copy is reused by `graph` while `cite`, `recheck` and `refresh` download fresh each time; a changed repository makes `recheck` say MISSING; `plan` says the rules files are not downloaded; `build` with a link records the evidence and a refused link stops it
  before a model is asked; refused links, a missing repository and an unreachable GitHub are one `error:` line with exit 2 and the typed text not repeated; a folder is unchanged and a child process shows that neither importing the CLI nor a folder argument loads the builder;
  and the cheap link check in `cli.py` agrees with the builder's own on 19 link-like and folder-like samples (so the two cannot drift apart). The whole backend suite: **2,569 passed, 3 skipped** (symbolic links).
- **Deliberate breaks: 14, all caught** (a link treated as a folder, the note on stdout, `cite`/`recheck`/`refresh` reading a young copy, a refusal not caught in either branch of `main()`, `plan` losing its rules note, everything looking like a link, the builder imported at the top, `stats`
  showing the copy's folder, the age of a reused copy not said, `build` reading a link as a folder, what was left out not said). One of them, the builder imported at the top, would have **survived my first version of the test** (it compared before and after instead of demanding that neither loads it); that is how it was found.
- **Real runs (2026-11-25, the real command against this repository's public link, a scratch data folder):** `graph stats` downloaded 273 source files (2.5 MB) in about 20 seconds and read them, and a second run reused the copy in under 9 seconds; `graph hotspots --json` printed pure JSON (`CheckResult`, 44 callers) with the
  note on stderr; `suggest --facts-only` and `plan --no-ai` worked and `plan` carried the extra line about the rules files; a link to another site and a link to a repository that does not exist were each one plain `error:` line with exit 2; and with a skill that names two places of the code,
  `library cite --repo LINK` recorded both (`from 'jeswin4693__aiskills'`, the name the page records too) and `library recheck --repo LINK` reported 2 holds from a fresh download.
- **Not verified:** `build --repo LINK` with a real model (the test uses the mock one, as the folder tests do); macOS and Linux; a repository close to the 80 MB limit. **No independent review** (an adapter over code that has just been reviewed; one can be run on request).
