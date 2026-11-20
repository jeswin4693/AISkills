# Try every feature yourself

A hands-on guide for a person, not a test plan for code. Each step says what to do and what you should see.
**What was actually run (2026-11-20):** every command in Part 1 (except the full test suites) and the five sample zips, against a
throwaway library; the outputs quoted are the real ones. **Not run:** Part 2 was written from the page code and was not clicked
through in a browser for this guide (the Plugins page has never been clicked through; the earlier browser suite covered import,
refusal, compare and install of skills), and Part 3 needs a model key. If a screen differs from what is written, that is a finding:
tell me what you saw.

**Practice mode (do this first).** Everything the app keeps, the skill, agent and plugin libraries, the builder history and the graph
cache, lives in one data folder. Point it at a practice folder and your real library is never touched.

```powershell
cd "C:\Users\jj1\OneDrive - Aptean-online\Documents\GitHub\AISkills"
.\scripts\make-try-samples.ps1                           # writes sample skills, an agent and .zip files to C:\dev\skillforge-try\samples
$env:SKILLFORGE_DATA_DIR = "C:\dev\skillforge-try\data"  # the practice library. Set it in EVERY terminal you use for practice.
$py = "C:\dev\venvs\aiskills\Scripts\python.exe"
cd backend
```

If PowerShell refuses the script, run it as `powershell -ExecutionPolicy Bypass -File .\scripts\make-try-samples.ps1`.
The samples: `try-skill` (v1 is clean, v2 also asks for the web), `bad-skill` (no description), `sneaky-skill` (an attack-style
sentence and a script that uses the network) and `try-agent` (a read-only reviewer).

## Part 1. In the terminal, no key, no browser

### 1. Understand a repository (the graph, no AI)
Scenario: "I want to change `compose_plugin`. What would that touch?" Use this repository as the test subject.

```powershell
& $py -m skillforge graph stats      ..
& $py -m skillforge graph callers    .. compose_plugin --depth 2
& $py -m skillforge graph impact     .. backend/skillforge/library/plugin.py
& $py -m skillforge graph hotspots   .. --top 5
& $py -m skillforge graph duplicates ..
& $py -m skillforge languages
```
You should see: about 194 files (Python, TypeScript, TSX at "full"); `compose_plugin` called from `compose_for_keeping` and the API;
`impact` says risk LOW and lists the dependents; hotspots lists `cli.py` as the riskiest file; the duplicates list shows copies
such as `RepoGraph.callers_of` and its three neighbours. Every answer says whether a link is proven or a guess.

### 2. Suggest, facts only
```powershell
& $py -m skillforge suggest .. --facts-only
```
You should see numbered facts (F1, F2, ...) such as "X is called from 27 distinct places", each naming the real code it comes from.
The AI version (ideas, risks, skill ideas) needs a key: Part 3.

### 3. Check a skill folder (safety checks that run nothing)
```powershell
$s = "C:\dev\skillforge-try\samples"
& $py -m skillforge validate $s\v1\try-skill       # 13 passed, exit 0
& $py -m skillforge validate $s\broken\bad-skill   # FAILED: description is missing or empty, exit 1
& $py -m skillforge validate $s\risky\sneaky-skill # 2 warnings: attack-style wording, and a script that uses the network
```
The point: a missing description fails, suspicious wording and network use only warn, and the report always says it is a pattern
check, not proof of safety.

### 4. The library: versions, risk diff, refuse, rescan, rollback, export, install
Scenario: "I kept a skill. Later someone edited it to use the web. Will I notice?"

```powershell
& $py -m skillforge library import $s\v1\try-skill        # imported as v1
& $py -m skillforge library import $s\v2\try-skill        # v2: "MORE RISK ... allowed-tools now also lists: WebFetch, WebSearch"
& $py -m skillforge library import $s\broken\bad-skill    # Refused: nothing was added (exit 1)
& $py -m skillforge library import $s\risky\sneaky-skill  # kept, with 2 warnings and "not run: script test cases"
& $py -m skillforge library list
& $py -m skillforge library versions try-skill
& $py -m skillforge library diff try-skill                # shows the added allowed-tools line and the changed step
& $py -m skillforge library rescan                        # today's checks on every stored version: 3 same, 0 worse
& $py -m skillforge library rollback try-skill --to 1     # a NEW version v3 with v1's content; nothing is deleted
& $py -m skillforge library export try-skill --out C:\dev\skillforge-try\try-skill.zip
& $py -m skillforge library install try-skill --to C:\dev\skillforge-try\installed
```
Never use `--personal` while practising: that writes into your real `~/.claude/skills`.

### 5. Plan a task (read-only)
```powershell
& $py -m skillforge plan "Add a --json option to the library list command. Do not change other commands." --repo .. --no-ai
```
You should see "A plan only. Nothing was run", the tier and the phases. Without a model it cannot read your request, so most of the
interesting part is empty; the full plan is in Part 3.

### 6. This machine
```powershell
& $py -m skillforge sandbox-status    # AVAILABLE: Docker inside WSL is running Linux containers (on this machine)
& $py -m skillforge models            # which models and keys are set up (no calls are made)
```

### 6b. Build the sandbox image for MCP servers (once)
```powershell
& $py -m skillforge sandbox-build-mcp      # needs Docker and a network, once; prints "skillforge-mcp:2.3.0 is ready."
```
Without it an MCP server is still built, but it can never be marked "ok": its test cases need this image to run.

### 7. The automatic tests
```powershell
& $py -m pytest -q                                                       # backend, offline (about 958; a few skip without Docker)
cd ..\frontend; npm run typecheck; npm test                              # UI helpers (77 unit tests)
```
For the real-browser suite (`npm run build` then `npm run e2e`) first stop your dev servers and make sure ports 3000 and 8000 are
free, and set `$env:SKILLFORGE_PYTHON = $py`. The suite starts its own app with its own scratch data folder, but if something is
already listening on those ports it talks to that app instead, and the test entries then land in that app's library (this happened
once).

## Part 2. The web pages, no key

Open two terminals. In **both**, set `$env:SKILLFORGE_DATA_DIR = "C:\dev\skillforge-try\data"` (use a fresh practice folder, for
example `data2`, to start empty again). First close any copy of the app you normally run.

```powershell
# terminal 1
cd backend; & C:\dev\venvs\aiskills\Scripts\python.exe -m skillforge serve     # http://127.0.0.1:8000/api/docs
# terminal 2
cd frontend; npm run dev                                                       # http://127.0.0.1:3000
```
**Sanity check:** open http://127.0.0.1:3000/library. It must be empty. If you see your real skills you are looking at the normal
app: stop everything and start again with the practice setting.

The pages: **Builder**, **Library** (tabs: Skills, Agents, Plugins, MCP servers) and **Plugins**.

### A. Import, refuse, and the risk diff
1. Library, Skills tab: drop `C:\dev\skillforge-try\samples\zips\try-skill-v1.zip`. You should see it kept as v1 with its checks.
2. Drop `try-skill-v2.zip`. It becomes v2 and shows **more risk**: the permissions now include WebFetch and WebSearch.
3. Drop `bad-skill.zip`. It is **refused** and nothing is added.
4. Drop `sneaky-skill.zip`. It is kept, with warnings you can read.
5. Open `try-skill`: see **Files**, **Checks when it was imported**, **Versions**, then **Compare versions** (From v1 To v2: added lines
   marked +). Use the re-check (rescan) box on the Library page: nothing should come out worse.

### B. An agent
1. Library, **Agents** tab: drop `try-agent.zip`. It is kept with its `tools` line (`Read, Grep, Glob`).
2. Open it and choose install. Pick **a folder** (for example `C:\dev\skillforge-try\installed-agents`), not Personal, unless you
   want it in your real Claude Code. An agent installs as a single `<name>.md` file.

### C. Compose a plugin (no model)
Scenario: "Bundle my word counter and my reviewer into one thing I can share."
1. **Plugins** page. Name it `my-helpers`, give a one-line purpose, tick `try-skill` and `try-agent`, press **Preview the plugin**.
2. You should see the files that would be written, **what it can do on your machine** (the WebFetch/WebSearch badges come from the
   skill's latest version, v2), and the checks.
3. Press **Keep this plugin**. It is stored as plugin version 0.1.0; open it from the link in the confirmation box.
4. Press Preview and Keep again without changing anything: **Unchanged: identical to the version you kept**, no new version.
   Change only the purpose, keep again: the plugin version becomes 0.1.1.
5. Type `claude-helpers` as the name: a hint says the name is reserved by Claude Code, and Preview stays disabled.
6. Library, **Plugins** tab: export it as a zip, or install it into a folder, for example `C:\dev\skillforge-try\installed-plugins`.
7. Optional, changes nothing: check the folder with Claude's own validator,
   `claude plugin validate "C:\dev\skillforge-try\installed-plugins\my-helpers" --strict`.
   Adding it to Claude Code (`claude plugin marketplace add` then `claude plugin install`, both written in the plugin's README) changes
   your Claude settings, so it is your call; this guide did not run those two commands.

### D. An MCP server (needs the model key, see Part 3)
Not clicked through in a browser yet, so this is the first time anyone does. 1. Builder, pick **MCP server**, describe two tiny tools (for example: *word_count returns how many words a text has; reverse_words returns its words in reverse order; an empty text is refused*). 2. Answer only what it asks, approve. 3. On the result card look at the checks: with the sandbox image built, each test case shows as **passed** and the card says **ok**; without it the server shows **DRAFT: Not run ...**. 4. Open `server.py` in the file viewer and read it: two `@mcp.tool()` functions you could have written. 5. Keep it, then open it in the Library under **MCP servers**, and use **Install** into a folder. 6. The README in that folder has the `claude mcp add ...` command; this guide does not run it, because it changes your Claude settings.

## Part 3. Needs a model key (a handful of model calls)

Your `.env` already has Gemini (main) and Groq (backup). Each of these is a few calls. Check first:
`& $py -m skillforge models --test` asks each model one tiny question.

| What | How | You should see |
|---|---|---|
| **Skill builder, web** | Builder, pick **Skill**: "A skill that counts TODO and FIXME comments in a folder." | Questions only for what is missing; a requirement list where each line sits beside your own words; a build; checks, token cost estimate and test cases; save to the library. |
| **MCP server builder, web** | Builder, pick **MCP server**: "Two tools: word_count returns how many words a text has, reverse_words returns its words in reverse order. An empty text is refused." | A `server.py` written by code around the tools, a README with the `claude mcp add` command, and each test case run in the sandbox (needs `sandbox-build-mcp` first). Try a request with a key in an environment variable: only the variable's *name* may appear, and a tool that needs the network makes the build a DRAFT. |
| **Agent builder, web** | Builder, pick **Agent**: "Review a pull request diff for hard-coded passwords and report the file and line. Never change files." | An `AGENT.md` with `tools: Read, Grep, Glob` only, and "Use proactively when the request involves ..." in the description. Then ask for "also run the project's tests": `Bash` should appear and be flagged for you to read. |
| **Skill builder, terminal** | `& $py -m skillforge build "A skill that counts TODO and FIXME comments in a folder."` | The same conversation in the terminal, a folder and a report at the end. |
| **Does the skill help?** | `& $py -m skillforge build "..." --eval`, or `& $py -m skillforge eval <the folder it printed>` | Test replies graded by code with and without the skill: helped, adds nothing, or worse. Text-only skills only. |
| **Suggest with AI** | `& $py -m skillforge suggest ..` | Refactor, test and risk findings and skill ideas, each citing real graph nodes. |
| **Full task plan** | `& $py -m skillforge plan "..." --repo ..` (no `--no-ai`) | What your request contains (with your quotes), what it does not say, the size, and which functions to read. |

The web **Builder** history keeps past builds with a kind badge. A built skill or agent saved to the library is in your practice
library, so you can send it through Part 2 as well.

## Not testable yet (say so, do not hunt for it)
- Plugins that carry hooks or MCP servers (Phase 4), and the TypeScript half of the MCP builder.
- The web pages for the graph, suggestions and Settings. Use the terminal commands in Part 1.
- `eval` for agents, and a live-model run of the agent builder's own test cases.
- The hosted version needs a Docker deploy: see [hosting.md](hosting.md). Local use is unchanged.

## Clean up
Close both terminals (this drops the practice setting), then:
```powershell
Remove-Item -Recurse -Force C:\dev\skillforge-try
```
Your real library and `~/.claude` were never touched unless you used `--personal`, chose Personal in an install dialog, or ran the
two Claude plugin commands yourself.
