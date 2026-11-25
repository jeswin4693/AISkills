# The Dashboard (slice AC)

The first page of the app. Until now `/` only redirected to the Builder, and the original vision (docs/START_PROMPT.md) lists a Dashboard among its nine pages. It answers
what a person wants to know on opening the app: **does anything need me, what do I have, and where do I start?** Design: [superpowers/specs/2026-11-25-dashboard-design.md](superpowers/specs/2026-11-25-dashboard-design.md).

It needs **no new server code**: everything it shows already has an endpoint, and nothing here asks a model or runs anything.

## What a person sees

```
 Dashboard                                                        [Check again]

 Needs attention
   Problem   agent-x v2 fails 2 checks today          (a link to the skill)
             no wording that matches known attack patterns, file sizes are within limits
   Warning   No AI model is set up                    (a link to Settings)
   To do     Waiting for your answers: todo-counter   (a link to the build)

 Your library                        Recent builds
   Skill          3 saved · 7 versions     todo-counter   Built   saved v1   2 min ago
   Agent          1 saved · 1 version      ...
   Plugin         0 saved
   Saved most recently
     todo-counter v2          2 min ago

 Start something   [Build something] [Read a repository] [Import into the library] [Combine into a plugin]
```

* **Needs attention**, worst first. From today's rescan of every kind (`GET /api/rescan?kind=`): a version whose files are **damaged** or that **fails** checks now is a *Problem*; one whose
  checks **got worse** since it was imported is a *Warning*. From the builds: waiting for your answers or approval and finished-but-not-saved are *To do*; a failed build is a *Problem*; a
  draft that was never saved is a *Warning*. From the system: no model set up (*Warning*, links to Settings) and no sandbox (*To do*, nowhere to go).
  At most **ten** are listed, the rest are counted. Inside one severity the order is the order the data came in (builds newest first).
* **When nothing needs the person**, the page says what it looked at ("today's checks on N stored versions, M builds, the model and the sandbox"), so "nothing" is a checked statement.
* **Your library**: per kind how many are saved and how many versions in all, and the five versions saved most recently across kinds. Each links to its page.
* **Recent builds**: the last five, with the Builder's own status words.
* **Start something**: four links.

## The rules (all in `lib/dashboard.ts`, all tested without a browser)

| Rule | Why |
|---|---|
| A failure to read a part is **said in that part**, never shown as zero or as "nothing needs you". A kind whose library cannot be read has a *could not be read* row with the reason; a kind whose checks cannot be run adds "Something could not be checked". | The anti-goal of this slice: a dashboard that hides a failure. |
| Every part loads **on its own**: one slow or failing endpoint does not blank the page. | Robustness. |
| Severity order is bad, warning, info; a tone keeps the data's own order; at most ten. | Predictable, and the worst is never pushed off the list by something minor. |
| Two kinds with the same name stay apart (the key and the link carry the kind). | The library is per kind. |
| A build that is still **working** is not an item (that is progress), and a saved build is not either. | Only what the person can act on. |
| What is not yet known (the model, the sandbox still being asked) is **not** reported as a problem. | No false alarms while loading. |

## Checked

**Tests (2026-11-25).** Web: **259 unit tests** (238 before; 21 new in `lib/dashboard.test.ts`: every item kind and its tone and link, the order, the cap, two kinds with one name, an unknown model or sandbox, the library counts and the recent list) and a clean
typecheck. The server was not touched (the last full backend run, 2,842 passed, is from slice AB's follow-up). Browser: the real-Edge suite is **76 of 76** on free side ports (72 before; the first step used to expect the redirect and now expects the dashboard with the
model not set up and nothing saved; four new steps): what is saved, with the newest version taken from the real API (a first version of this step insisted on a fixed name and failed because newer things had been saved: a test of mine was wrong, not the page); what needs
the person, with every unfinished build on the list and "Check again"; **an endpoint made to fail on purpose** (`page.route` answers 500 for the agent library and its rescan), which proves the page says "could not be read" and "Something could not be checked", never shows
"0 saved" for it, never says "Nothing needs you right now", and recovers when the API does (the two deliberate 500s are accounted for exactly, so the suite's console check still means something); and phone width with no sideways scroll. Both screenshots (empty and populated) were read by eye.

**Deliberate breaks: 26, all caught** (damaged only a warning, failing counted wrongly, the kind or the encoding missing from a link, a key without the kind, a saved build listed, a draft only information, severity ignored, the order reversed within a tone, no cap, the rest not counted,
an unknown model or sandbox reported as missing, a long reason not cut, the label rules, versions counted as one each, the newest listed last, a tie not broken, the recent list not limited, a skill with no latest version listed, and an unreadable library looking empty). The first run caught 25:
nothing tested that a very long reason from the model or the sandbox is cut to 200 characters, and a test now does.

**Not verified:** a library of hundreds of skills (the page rescans everything in the browser on every visit); the hosted version's sign-in with this page (the page itself is unchanged by it); a screen reader and keyboard use beyond what the shared components give; any browser but Edge.

## Limits (said plainly)

* **It reads everything in the browser, on every visit**, including a rescan of the whole library (it only reads; nothing is run or changed). That is fine for a personal library and would not suit hundreds of skills. A server-side summary would be the next step then.
* **"Checked" means today's static checks** (the same ones the skill page's rescan runs), not that a skill works: that is what the Testing Lab (not built yet) is for.
* Not a history: nothing is saved, charted or compared over time.
* No sandbox is a *To do* with no link: it cannot be fixed from a page (see docs/sandbox-wsl.md).
