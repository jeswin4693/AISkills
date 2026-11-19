# Library: import, versions, export, install

`skillforge library` keeps skills as numbered versions, and is the only door a skill passes through to get in
(import) or out (export, install). Every door runs the static checks from [validate.md](validate.md) first.
Works on any skill folder: made here, downloaded, or written by hand. Needs no AI and no key.

```
 folder or .zip --> IMPORT (checks) --> LIBRARY v1, v2, v3 ... --> EXPORT (.zip to share)
                    refused if a                |                --> INSTALL (to .claude/skills)
                    check fails                 +--> diff + risk diff, rescan, rollback
```

## Run it

```powershell
cd backend
python -m skillforge library import generated-skills\my-skill          # or a .zip; add --test-scripts to re-run its script cases
python -m skillforge library list
python -m skillforge library versions my-skill
python -m skillforge library diff my-skill                             # latest against the one before (--from N --to M), with what got riskier
python -m skillforge library rescan [my-skill] [--version N]           # today's checks on stored versions: which are now worse?
python -m skillforge library rollback my-skill --to 1                  # a NEW version with the content of v1
python -m skillforge library export my-skill --out my-skill.zip        # --version N, --without-spec, --force
python -m skillforge library install my-skill --project                # or --personal, or --to <skills folder>
```

## What each command does

| Command | What happens |
|---|---|
| `import <folder or .zip>` | Reads the source into memory (nothing is unpacked to disk), runs every static check, and keeps it as the next version only if **no check failed**. Warnings are allowed and stored. The same content again makes no new version. |
| `list`, `versions` | The skills, and each version with its date, source, file count, content hash and check counts. |
| `diff <name>` | Files added, removed or changed between two versions, with the changed lines. Long diffs are cut and say so. It starts with the **risk diff** (below). `import` prints the same risk section when it adds a version after another. |
| `rescan [name]` | Runs **today's** static checks on versions already stored and says which are now worse than at import (below). Changes nothing; exit code 1 if a version fails today or is damaged. |
| `rollback <name> --to N` | A **new** version with the content of vN. History only grows; nothing is deleted. |
| `export <name>` | A `.zip` holding one `<name>/` folder (the shape Claude and other agents accept). Same files, same bytes. Checked again first. Never overwrites a file without `--force`. `--without-spec` leaves out `spec.json`, which holds the requester's own words. |
| `install <name>` | Copies a version to `<skills folder>/<name>`. You **must** say where: `--personal` (`~/.claude/skills`, every Claude Code session on this machine), `--project` (`.claude/skills` here), or `--to DIR`. Checked again first. An existing folder is left alone unless `--force`, and then it is copied to a backup first. |

## Risk diff: what got riskier since the version before

Why: research on skill marketplaces found that a skill can pass a scan, then be edited into a bad one, so **a scan that
happens once is a scan an attacker can wait out** ([differentiators.md](differentiators.md)). The library already keeps
every version and refuses a stored file that was changed. The risk diff adds the missing question: *what did this new
version change that matters?* Code answers it, from the two versions' files. No model reads the skill and nothing is run.

| Looks at | Says "more risk" when | Says "less risk" when |
|---|---|---|
| Scripts | a script was added (always, with what it uses); a script now uses `network`, `run_commands` or `write_files`, or `eval` and similar (Python, JavaScript, TypeScript, by syntax analysis) | a script was removed, or no longer uses one of those |
| Permissions | `skill.sdm.json` declares more, or `allowed-tools` in the SKILL.md front matter lists more tools | fewer |
| Attack wording and hidden markup | a text file now matches a known attack pattern, or a Markdown file now has an HTML comment or script-like tag (a pattern match: the line is shown, it may be harmless) | the match is gone |
| Web addresses | a script now mentions an address the version before did not | an address is no longer mentioned |
| Any other check | a check that did not fail before now warns or fails | a check got better |

Two more kinds of change are labelled **worth a look**, because code can count them but cannot judge them: the
**description** changed (an agent reads it to decide when to use the skill; both texts are shown), and **instructions**
changed (how many lines of `SKILL.md`, and of any other Markdown file an agent may be sent to read, were added or
removed), and a new web address in plain text. Both versions are checked with **today's** checks, so a rule added after
v1 was imported is not mistaken for a change in v2 (that is what `rescan` is for).

The headline is one of: *more risk*, *worth a look*, *less risk*, *no new risk found by these checks*. It is never
"safe". The limits are printed with every result:

- It compares only what code can see. **Reworded instructions can change what an agent does and no pattern sees it.**
  `diff` shows the lines: read them.
- Capabilities are found by syntax, only for Python and JavaScript/TypeScript. Other languages and shell scripts are
  reported as "not analysed". Code that is built while it runs cannot be analysed.
- A new script is always flagged as more risk, even if nothing was found in it: it is new code that runs on a machine.
- Wording patterns and web addresses are heuristics. A harmless link counts as "worth a look"; a rewritten attack can
  slip past.
- It never blocks anything. A version with more risk is still imported (it passed the checks); you decide what to do.

## Rescan: today's checks on what is already stored

Checks improve. A skill that passed last month may not pass this month's rules, and a one-time scan can be waited out.
`library rescan` runs the current static checks on every stored version (or one skill, or one version) and compares the
result with what the checks said at import. Each version is one of:

| Result | Meaning |
|---|---|
| **same** | no check is worse than it was at import (a warning that was already there at import is not "worse") |
| **worse** | a check that passed now warns, or a check that did not exist at import now warns |
| **failing** | a check fails today: the version would be refused if imported now, and `export` and `install` already refuse it |
| **damaged** | the stored files no longer match their manifest, or the manifest cannot be read, so nothing was checked |

It **changes nothing** (stored versions are never edited: the history only grows) and **runs nothing**. It is also
static checks only. Exit code 1 if any version is failing or damaged; a warning alone exits 0.

## Where things are kept

```
<per-user data folder>/skillforge/library/<name>/v<N>/skill/...        the files, exactly as imported
<per-user data folder>/skillforge/library/<name>/v<N>/manifest.json    when, from where, a SHA-256 per file, the check results
<per-user data folder>/skillforge/backups/<name>-<time>/               copies made by install --force
```

The data folder is `%LOCALAPPDATA%` on Windows (the same place as the graph cache, or `SKILLFORGE_DATA_DIR`): never
inside a repository and never inside OneDrive. The manifest stores the *name* of the folder or file a skill came
from, not its full path.

## What keeps this safe

- **Import is checked first.** A skill with hidden characters, a missing or broken `SKILL.md`, bad JSON, binaries,
  scripts that do more than the skill declares, links, or a path that leaves the folder is **refused**, and the
  library is not touched.
- **Zips are read as untrusted.** At most 1,000 files, 1 MB per file and 5 MB in total *after* unpacking (the size a
  zip declares is never trusted), no symbolic links, no repeated names, no absolute or `..` paths. Nothing is
  extracted: bytes are read into memory, checked, and only then written by code to a fixed layout.
- **The library is tamper-evident.** Every read compares each stored file with the SHA-256 in its manifest. A file
  edited, added or removed behind the library's back makes the version unusable (`export`, `install`, `diff`,
  `rollback` all refuse), and the message names the file.
- **Nothing is run by importing.** `--test-scripts` is opt-in. It re-runs the skill's own script cases in the Linux
  sandbox (see [scripts.md](scripts.md)); without a sandbox they are reported `not run`, never `passed`.
- **Install never guesses and never overwrites quietly.** No default target, no replacing without `--force`, and a
  backup first. A folder that is a link is left alone.

## What a re-test (`--test-scripts`) can and cannot do

Test cases exist only for skills built here: they live in `skill.sdm.json`. So:

- A skill **built here**: the cases run in the sandbox, but first the folder's scripts and fixtures must be
  **exactly** what `skill.sdm.json` says. If they differ (someone edited a script), the re-test is `not run` and says
  why, because it would not be testing what ships. A case that fails **refuses** the import.
- A skill **from somewhere else** (no `skill.sdm.json`): there are no machine-readable cases, so the row is `not
  run`. Its scripts are still checked statically, never run.

## Decisions (change them if you disagree)

- **Versions are plain numbers** (v1, v2, ...), assigned by the library, because an imported skill may have no
  version of its own. A skill's own `version` from `skill.sdm.json` is stored next to it for reference.
- **Same name means same skill.** Importing a skill whose name already exists adds a new version of it. The import
  output says "new version after v2" and lists the changed files, and nothing is installed automatically.
- **Rollback adds a version** instead of moving a pointer, so the history is a straight line you can always read.
- **Export and install work from the library, not from a loose folder**, so nothing leaves that was not checked.

## Limits

- The checks are the ones in [validate.md](validate.md): structure and patterns, not understanding. A skill that
  passes is not thereby safe, and installing it puts its instructions in front of an agent.
- Scripts in an installed skill run **on your machine** when an agent uses them, not in the sandbox.
  `export` and `install` say so when a skill has scripts. Read them first.
- Identical zips come out the same on one machine; the compressed bytes can differ between versions of the zlib
  library, so compare content hashes (`versions`) across machines, not zip bytes.
- No remote sources: import takes a local folder or `.zip`, not a URL or a registry. No signing or publisher
  identity: a manifest records where a skill came from, it does not prove who made it.
- One person, one machine: there is no locking for two processes writing at once (a clash is detected and refused,
  not merged). Sharing a library between people is for the database step.
- Tests that need a symbolic-link-capable account skip where there is none.
- **The risk diff only advises.** There is no setting that refuses or holds an import because it got riskier, and a
  rollback or an install does not print one (use `diff`). A rescan is computed when you ask: its results are not stored,
  so the library has no "last scanned" date and nothing runs a rescan by itself.
- The risk diff and the rescan were tested on synthetic skills (a script that gains the network, hidden markup, a new
  rule added after import, a file edited behind the library's back), not on a collection of real skills from other people.
  How often they raise a false alarm on real skills is not measured.
