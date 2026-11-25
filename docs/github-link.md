# Reading a repository from a GitHub link (slice Y)

The Repository page took the full path of a folder on this computer. Now the same box takes the link of a **public GitHub repository**, and the link
works everywhere the folder path works: read it into the graph, ask for ideas, build a skill from an idea (with evidence), and recheck that skill.
Plan: [superpowers/plans/2026-11-23-github-link-slice-y.md](superpowers/plans/2026-11-23-github-link-slice-y.md).

```
https://github.com/owner/repo  --parse (strict list)-->  GithubLink(owner, repo, branch)
        |
        +-- download GitHub's zip from codeload.github.com only (size and time limited, no other redirect)
        +-- unpack it ourselves: source files only, safe names only, size limits, never a link
        v
   <data dir>/github/<hash of owner/repo>/<default | ref-hash>/<time>-<hash>/owner__repo/...   (a "snapshot": a folder like any other;
                                                                                              the outer names are hashes, so a long or look-alike name cannot use up the path)
        |
        +--> analyze / suggestions / a build's evidence / recheck read it exactly as they read a folder
```

## What a person sees

* The box says **Folder or GitHub link**. A link is checked as it is typed ("Use an https:// link", "Give the link of a public GitHub repository..."), so the button stays off until it is usable.
* After **Read the repository** the summary is named `owner/repo`, has a **from GitHub** badge and says what happened: *From GitHub (default branch), downloaded just now: 312 source
  files kept (2.4 MB). Nothing was run.*, what was left out (other files, folders such as `node_modules`, files over 1 MB, ...) and that **git history is not downloaded**, so
  facts that come from it (how often a file changes) are missing.
* Ideas, builds and the recheck are made for `owner/repo`. A build records evidence as before; the evidence names the repository `owner__repo` (lower case, and cut with a hash after 48 characters for a very long name).

## Why a zip, and not `git clone`

A clone runs things the repository controls (hooks, filters, the addresses of submodules) and has no size limit. A zip is only bytes: **our own code decides which files are written,
where, and how many.** No `git` program is run and no key is needed.

## The rules it keeps

* **A strict list of links.** `https://github.com/owner/repo`, with an optional `.git`, a trailing slash, a query or fragment (ignored) or `/tree/<branch-or-tag>` (one name, no slash); `github.com/owner/repo` without `https://` is accepted.
  Everything else is refused with a plain message that does not repeat what was typed: another site, `http`, a login in the link, a port, `github.com.evil.com`, a percent-encoded or look-alike name, a deeper path
  (the message points at the **Only this folder inside it** box). Owner and repository names are checked with GitHub's own rules.
* **Public repositories only.** A private one needs a token, which would be one more key to store and protect. GitHub answers "not found" for a private repository and the message says so.
* **The download goes to `codeload.github.com` over https and nowhere else.** A redirect anywhere else is refused. At most **80 MB**, **120 seconds**, and the zip must really be a zip.
* **Unpacking is ours, and fails closed.** Only files in a language the graph reads, at most 1 MB each (the graph's own limit), at most 20,000 files and 200 MB. Skipped, never written: symbolic links and devices;
  names that could leave the folder or that this disk cannot hold (see `unsafe_part` in `builder/github.py`); folders the graph ignores (`.git`, `node_modules`, ...); a second name that differs only in case;
  anything over the limits. Every file is created without overwriting, and its resolved place must be inside the snapshot, or it is skipped. The archive must be one folder (GitHub's layout) and have at most 200,000 members, or nothing is unpacked.
* **Nothing is run.** The graph reads the files; nothing in the repository is executed, imported or built.
* **Snapshots are bounded.** The newest two of each repository and branch are kept, and twelve repositories at most; half-made snapshots are cleaned away. A snapshot is **reused for 15 minutes** so reading, ideas and a build see the same code; a
  **recheck always downloads fresh** (what changed is its point). Simultaneous requests for one repository share one download.
* **A build's evidence is looked up in the copy its idea was made from.** A suggestion run records the copy it read (its `snapshot` name), a build started from one of its ideas keeps that name in its seed, and the evidence is recorded from exactly that
  copy, however old, because its places must be looked up in the same code. Only the newest two copies of a repository are kept, so if that copy has been pruned the evidence is recorded from a newer one and the build's notes **say so**
  ("the code may differ"). (Until the review of 2026-11-25 this section said the same, but the code took the newest copy.) A folder has no copies: its evidence is always from the folder as it is when the build ends.
* **Folder names cannot collide.** A repository's copies live under a hash of `owner/repo` (lower case, as GitHub treats them) and a branch under a hash of its exact name, so `Main` and `main` (or `main.`) are different on a disk that ignores case or a
  trailing dot; a copy's record must name this very repository and branch or it is not trusted.
* **No path is repeated.** A suggestion run and a build seed store the link, never the snapshot's path; pages are shown `owner/repo`; no response or error names where the copy is kept.
* **Off in the hosted version** (403), like every route that reads a folder. (A hosted version could allow links because no server path is involved, but that needs its own thought: a download quota and disk use per person.)

## The API

| Route | |
|---|---|
| `POST /api/repos/analyze` | `path` may be a link. The answer now has `source`: `{"kind": "folder"}` or `{"kind": "github", owner, repo, ref, url, fetched_at, files, bytes, skipped, reused}` (`skipped` counts files left out by reason), and `name` is `owner/repo`. |
| `POST /api/suggestions`, `POST /api/builds` (`repo` or `from_run`), `POST /api/library/{name}/recheck` | take a link wherever they took a folder. |
| Errors | 400 for a link that is refused, a repository or branch that is not there (or is private), an archive that is too large or has no source in a language that is read; **502** when GitHub could not be reached, refused (too many requests) or took too long. |

## Checked

* **Backend** (`tests/test_github_link.py`, 182 tests, all offline: a fake download and in-memory hostile archives stand in for GitHub): the strict link list, the download limits and the redirect policy,
  hostile archives (a path that leaves the folder, links and devices, Windows device names, invisible characters, a zip bomb, too many files, a file whose name differs only in case), snapshots (reuse, replace,
  prune, simultaneous requests, Windows holding a folder for a moment), and the whole pipeline (read, a suggestion run, a build with evidence, a recheck). The whole backend suite: **BACKEND_TOTAL passed, 3 skipped** (symbolic links).
* **Frontend:** unit tests for the link rules and the "where it came from" lines (214 UI unit tests in all, typecheck clean). The real-browser run has two behaviours for links. It was re-run on 2026-11-25 on the final code of this
  slice (**60 of 60** before slice Z, **64 of 64** with it, on free ports with a scripted fake download), which closes the re-run this slice still owed.
* **A real run against the real GitHub (2026-11-23):** this repository's public link read **257 source files (2.3 MB) in 7 seconds** and the graph matched the local counts (198 Python, 25 TypeScript, 27 TSX files); a second read
  a moment later reused the copy in 0.4 seconds. A repository with no source, a branch that does not exist, an owner that does not exist, another site and a link with a login each gave a plain message. No `.git` or half-made folder
  was left behind and no response named where the copy is kept. It also found two real problems that tests with a fake download could not: on Windows a folder cannot be renamed while a virus scanner has a file in it open (now retried), and a long
  temporary folder name made files that would fit fail to unpack (now the temporary name is short, and a file whose path is too long is skipped **by name**, `path_too_long`, instead of a vague "unwritable").
* **Deliberate breaks:** 38 one-line breaks of the new code, one at a time. 35 were caught at once. Two change nothing here: the `%` check (the name pattern already refuses `%`) and the check for names that differ only in case
  (on Windows the exclusive file create refuses the second one too; it matters on Linux and macOS). One was a real gap in a test, which claimed to age a snapshot by patching the clock where the code had already fixed it; it now ages the
  snapshot's own record and the break is caught.
* **One independent review (2026-11-25, together with slice Z)**: a fresh reader on the strongest model, about 142,000 tokens and 30 tool calls, who read all of `builder/github.py` and wrote its own probe scripts (hostile links, zips built in
  memory, a real HTTP response over a socket pair), with no network and no `.env`. **No Critical finding.** What it confirmed: every link bypass tried was refused (a look-alike host, a login, a port, a trailing dot, backslashes, `..`, `%`, control
  characters), owner, repository and branch can only use `[A-Za-z0-9._-]` so the download address cannot be steered, a redirect is checked inside the redirect handler, a lying Content-Length does not matter because bytes are counted as they arrive,
  the per-file limit is applied to the bytes actually decompressed, and a symbolic link, `CON.py`, `a.py` + `A.py`, `a.py/b.py` and a right-to-left-override name were all skipped. **Four Important findings, all reproduced, all fixed test-first** (see below).

## What the review found, and what was done

| # | Finding (all reproduced by the reviewer) | Fix |
|---|---|---|
| 1 | The folder for a branch was `ref-{branch}`: on Windows and macOS `Main` and `main` (and `main.`) were one folder, and the record was never checked, so for 15 minutes a different branch showed `main`'s code under its own name. | Folders are hashes of the exact branch (and of `owner/repo` in lower case); a record must name this repository and branch. |
| 2 | The doc said a build's evidence reuses the copy its idea was made from. The code took the **newest** copy (and a run read the repository when it executed, a build read it later), so evidence could describe code the idea never saw. | A run records the copy it read, the seed keeps it, the evidence is looked up in exactly that copy; if it was pruned the build's notes say that a newer copy was used. |
| 3 | `owner__repo` was in every file's path twice: at the default data folder a file had about 80 characters left, so deep Java and Kotlin layouts were skipped as `path_too_long`. | Outer folders are short hashes (about 76 characters in front of a file for a typical name, from 101); the inner folder keeps the repository's name. |
| 4 | A long but valid name made `mkdir` fail with an unexplained 500 whose message held the data folder's path. | The hashed names remove the cause; any disk error while storing a copy is now a plain message with no path (the details go to the server's log). |
| (note) | The temporary folder was 2 characters **shorter** than the final one, and a test asserted that, which is the unsafe direction (a path that fits the shorter one may not fit the longer). | The temporary folder is now at least as long as the final one, and the test asserts that. |

**Found, not fixed (Minor, listed so they are not forgotten):** the 120-second limit is checked between 64 KB reads, so a server that sends a byte every few seconds could hold a worker (only codeload over TLS could do it); a Content-Length written
with a superscript digit passes `isdigit()` and then crashes `int()` (a 500 from an odd header); after the 200 MB budget is spent, later entries are still decompressed before being skipped, so a crafted 80 MB zip of identical files costs about 77 seconds
of CPU (local use only). **Not reproduced, kept as open risks:** pruning can delete a copy another request is reading (no reference counting across repositories), and a data folder inside a git work tree lets `git ls-files` and `git log` see the parent
repository. The reviewer also noted, and left alone, that the page's TypeScript link reader accepts forms the server refuses (the server decides, so the only effect is a later error).

## What is not here

* The command line (`graph`, `suggest`, `library recheck` still take a folder). Clone a repository and give the folder, or use the page.
* Private repositories, submodules (GitHub's zip leaves them out), Git LFS contents (only pointers), other hosts (GitLab, Bitbucket), and the repository's git history.
* A repository whose zip is over 80 MB cannot be read from a link; clone it and give the folder.
* (The drawn architecture map was built afterwards, in slice Z, and works for a link exactly as for a folder: [architecture-map.md](architecture-map.md). A flat repository such as a three-file one is one box, and the page says so.)
