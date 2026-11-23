# Slice Y: read a repository from a GitHub link (plan)

Written 2026-11-23. The Repository page takes the full path of a folder on this computer. The person asked: can I paste a GitHub link and have the
repository read the same way, so I can look at it and understand it? This slice makes the link work **everywhere the folder path works** (read it into
the graph, ideas, a build seeded from an idea, a recheck). The drawn architecture map is a separate slice and is not in this one.

## Calls I made (to be corrected if wrong)

| Question | Call | Why |
|---|---|---|
| `git clone`, or download a zip? | **Download GitHub's zip** (`codeload.github.com`) and unpack it myself | a clone can run hooks, filters and config from the repository, follow submodules and links, and has no size limit. A zip is only bytes: I decide which files to write, where, and how many |
| Which links? | `https://github.com/owner/repo`, with an optional `.git`, trailing slash, or `/tree/<branch-or-tag>` (one name, no slash). Anything else (another host, `http`, a login in the link, a deeper path) is refused with a plain message | a strict list is the only safe parser; `github.com.evil.com` and `https://github.com@evil.com` must not pass |
| Private repositories? | **No**, public only | a private one needs a token, and that is another key to store and protect. The message says so |
| What is unpacked? | **Only source files in languages the graph reads**, at most 1 MB each (the graph's own limit), skipping `.git`, `node_modules` and the other folders the graph skips; never a link, a file with an unsafe name, or one that would land outside the folder | the graph reads nothing else, and everything else is risk and disk for no value |
| Limits | 80 MB download, 20,000 files, 200 MB unpacked, 120 seconds, no redirect off `codeload.github.com` | a repository too big to read says so; the message suggests cloning it and giving the folder |
| Where does it live? | `<data dir>/github/<owner>__<repo>/<ref>/<time>-<hash>/<owner>__<repo>/`, the newest two kept, twelve repositories at most | the stored run, build seed and evidence need to find the same files again; the folder is named so evidence says which repository |
| Fresh or reused? | A snapshot is reused for 15 minutes (so read, ideas and a build see the same code); a **recheck always downloads fresh** (its point is what changed); a build's evidence reuses the snapshot its idea was made from | consistency inside one piece of work, freshness where it matters |
| What is stored for a link? | The normalized link, never the managed folder's path; pages are shown `owner/repo` | the same "no path is repeated" rule as for a folder |
| Hosted version | **Off (403)**, like every route that reads a folder | one rule; a hosted version could allow links later because no server path is involved, but that needs its own thought (download quota, disk) |
| Git history | Not downloaded, so facts that come from history (how often a file changes) are missing and the page says so | a zip has none |
| Not in this slice | The command line (`graph`, `suggest` still take a folder), private repositories, submodules, Git LFS contents, other hosts (GitLab, Bitbucket), a drawn map | said plainly at the end |

## Steps (tests first)

1. Backend `builder/github.py`: the link parser, the download (limits, redirect policy), the safe unpacking, the snapshot store.
2. Backend: `check_repo` accepts a link; analyze, suggestion runs, build seeds, evidence and recheck use it; a `502` for "GitHub could not be reached".
3. Frontend: link recognised and checked on the Repository page, the summary says where it came from and what was left out.
4. Real browser (a scripted fake download), then a real run against a real public repository.
5. Docs, README, roadmap, memory; one independent review; commit and push.
