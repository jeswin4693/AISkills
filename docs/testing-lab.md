# The Testing Lab (slice AD)

The page that answers **"does this skill really help?"** The Dashboard and the Library only say that a skill passed *static* checks (it is well formed, nothing in it looks dangerous). The Lab runs the
skill's **own test cases** against a model, once with the skill and once without it, and **code (never a model) grades every reply**. Design: [superpowers/specs/2026-11-25-testing-lab-design.md](superpowers/specs/2026-11-25-testing-lab-design.md).
The engine is the one `skillforge eval` already had ([evaluate.md](evaluate.md)); this slice puts it in the web UI and keeps what it finds.

## What a person sees

```
 Testing Lab
   Skill [ git-commit-writer v ]   Version [ v1 (latest) v ]

   What would run
     short change  [positive]   Message sent:  fixed the login button alignment on mobile
                                The reply must pass:  has a first line of at most 50 characters
     no description [negative]  ...
   Run it
     Repeat each test [ once v ]   [x] Also run without the skill (this is what shows whether the skill adds anything)
     This will make 6 model calls to your model (3 tests x 1 repeat x with and without the skill), about 392 tokens of skill each time.
     [ Run the tests ]

   The skill helped
     With the skill: 3 of 3 runs passed every check.  Without it: 1 of 3.   (6 model calls, each test once, about 392 tokens for the skill)
   Case by case
     short change   With the skill  passed 1 of 1      Without it  passed 0 of 1
                                                         - the first line is 54 characters, the limit is 50
                    [Show the reply]                    [Show the reply]
   Earlier runs of this version
     v1  3 min ago  the skill helped · with the skill 3/3 · without it 1/3
```

* **Before anything is asked of a model** the page lists the cases that would run, each check in words, and the **number of model calls** (cases x repeats x conditions). The button says what it will do.
* **A skill that cannot be run says why and what to do**, in its own words, and offers no button: it has no test cases; its test cases have no message or no check (it was saved before test cases could be run);
  or it needs tools (`read_files`, `run_commands`, `network`) or has scripts, which a model with no tools cannot stand in for. The advice never points at a button that does not exist.
* **A run is kept.** It is a row in the database (`eval_runs`, migration 0005) that the page polls, so a reload shows it again, a second click while it works gets the same run (the quota is not spent twice), and a
  restart marks an unfinished run failed and offers "Run it again".
* **The result is the comparison**, never a lone score. The headline says one of: *the skill helped*, *adds nothing* (the model passes everything without it, so its tokens are paid for nothing these tests can see), *no difference*,
  *made it worse*, *too few cases to say* (fewer than three), or *run without the comparison* (no claim about the skill). Each case shows both sides, **each failed check in numbers** ("the first line is 54 characters, the limit is 50")
  and the replies themselves as plain text behind a disclosure.
* **A result is about one version.** The run stores the version and its content hash. When a newer version exists the result says "This run tested v1. The latest version is v2, and this run says nothing about it", and v2 shows no verdict until it has been run.
* A single repeat says that **models vary** and suggests three. The limits sentence of `evaluate.md` is on every result.
* The Library's skill page has a **Test this skill** button that opens the Lab on that version.

## The rules (in code, each one tested)

| Rule | Why |
|---|---|
| The outcome is a **code the server decides** (`EvalReport.outcome()`); the verdict sentence is written from it. The page never parses English. | A reworded sentence must not change what a page does. |
| `plan_cases` is the **one** place that decides which cases run. The run and the preview both use it. | What a person is shown before a run is, by construction, what the run does. |
| A skill that cannot be run is **refused before a run is stored or a model is asked** (400 with the reason). | No run exists that can only say "not run"; no quota is spent. |
| One run per skill version at a time; a second click gets the one that is working. | A double click cannot spend the quota twice. |
| `runs` is 1 to 5, at most 12 cases, 2 calls per case per repeat: bounded before a model is asked (422). | A typo cannot start 5,000 calls. |
| The version is read through `Library.read`, which checks every file against the manifest first. | A skill changed on disk is refused, not tested. |
| Replies are cut at 3,000 characters and messages at 2,000, and **marked as cut**; a reply is rendered as text, never markup. | A stored result stays small, a hostile reply cannot add elements to the page. |
| An error that is not a model or library error is named **by type only**; its text is never stored or shown. | It could hold a path. |
| Only **skills** can be run; any other kind is a 400 that says so. | `eval` for agents is not built. |

## API ([api.md](api.md))

| Route | |
|---|---|
| `GET /api/evals/preview?name=&version=&kind=` | What a run would do, or why not. No model. |
| `POST /api/evals` `{name, version?, runs, baseline, kind}` | Start a run (201). 400 with the reason for a skill that cannot be run, 404 for an unknown skill or version. |
| `GET /api/evals?name=&version=` | Runs, newest first, each with a short `summary`, without the heavy result. |
| `GET /api/evals/{id}` | One run: `status` (`working`, `done`, `failed`), `progress` `{done, total}`, and when done `result`. |
| `POST /api/evals/{id}/retry` | Runs a failed run again. 409 for any other state. |

It works in the hosted version too: it reads the server's library and asks the server's model, like a build does (nothing reads a folder).

## Limits (said plainly)

* **A skill that needs tools cannot be run here**, and that is **most skills about code**. On 2026-11-25 none of the three skills saved on the author's machine could be run: one needs `read_files`, one was saved before test cases had messages, one was imported with no test cases.
  The Lab says so honestly; it does not pretend a model with no tools is an agent. For those skills the test that matters is still installing the skill and using it.
* **The tests were written by the same model that wrote the skill** (for a built skill), so a skill can pass weak tests. Read the cases the page lists before believing a verdict. (Slice AE adds test cases written by the person.)
* **One model, a small sample, repeats of 1 to 5.** A single run is noisy: the first and second runs of the same build in `evaluate.md` said 0 of 3 and 2 of 6 without the skill.
* **Only what the seven checks can say** is checked (text, a pattern, length). Not facts, not tone, not "is this a good summary".
* **A run spends the model's quota**, and the page says how much before it starts. Nothing is counted in tokens per run (the AI engine's usage table is per builder session).
* The result of a run is kept forever (no clean-up yet); a run that was working when the server stopped is marked failed.

## Checked (2026-11-25)

**Tests.** Backend: **2,886 collected, 4 skipped (symbolic links), 0 failed** (2,842 passed before the slice, so 40 are new: `test_testing_lab.py` for the engine, `test_testing_lab_api.py` for the service and the routes; one existing test that
pins the list of tables was changed on purpose, and it also proves migration 0005 equals the model). Web: **294 unit tests** (35 new, `lib/testing.test.ts`) and a clean typecheck. Browser (real Edge, the real API, a scripted fake model, side ports 3100/8100):
**86 of 86** (76 before; 10 new steps: the menu and the empty page; a skill with no test cases says why and offers no run; a skill that needs tools says a model with no tools cannot stand in; the preview lists the cases and the cost, 6 then 18 then 9 calls as the choices change;
a run shows progress and then the verdict with both sides, each failed check in numbers and a reply behind a disclosure; the result is still there after a reload and listed under earlier runs; the skill page links in with its version; a model that cannot be reached fails the
run and "Run it again" finishes it; a newer version says so and has no verdict of its own; no sideways scrolling at phone width). Screenshots were read by eye, which found two things to fix: the same sentence shown twice on the "needs tools" page, and a skill name capitalised into "Todo-counter-e2e".

**The browser suite found a real fragility, not a test mistake.** The first run failed 9 of the 10 new steps because the picker could not be found by its label: the label wrapped the `<select>`, so its text included every option. Each label is now tied to its control by an `id`.

**Deliberate breaks: 36, all caught** (20 on the backend, 16 on the page's logic). The first run of the page's breaks caught 15 of 16: replacing the advice for a skill that needs tools with "Add more test cases" went unnoticed because my test accepted any of three phrases, one of which was elsewhere in the text. The test now demands the right advice and rejects the wrong kind, and the break is caught.

**Real run (2026-11-25, the configured model, `gemini-3.5-flash-lite`, through the real HTTP API and a throwaway data folder, so the real library was not touched):** a text-only commit-message skill with three cases was imported, previewed (3 cases, 6 calls), run, and polled
(progress 0, 1, 2, 3 of 3) in **12 seconds**: *The skill helped*, with the skill 3 of 3, without it 1 of 3. Without the skill the model answered "write me a commit message" with an invented `feat: add initial project structure and configuration` (it never asked what changed) and wrote a 53-character title for the refactor;
with the skill it asked, and kept the title short. **That run showed that the result said 7 model calls where the page had promised 6**: a call that is tried again counts as an attempt. The page now says so before the run. One run, one model, three cases: it shows the path works with a real model, not how good the skill is.

**Not verified:** the hosted version's sign-in with this page (it adds nothing of its own); a skill with many cases and repeats (a run of 12 cases x 5 repeats x 2 is 120 calls: bounded, but not timed); a model that is slow for minutes (the page polls and tolerates five failed polls, which was not forced in the browser);
macOS and Linux; a screen reader beyond the native controls (labels are tied to controls by id; the progress bar has `role=progressbar`); any browser but Edge.

## Next (slice AE and AF)

* **AE: the person's own test cases.** The Lab's "cannot be run" advice for a skill with no usable cases should become a button: write cases (a message and checks from the seven kinds) and keep them as a new version through the library's checked import
  ([design](superpowers/specs/2026-11-25-testing-lab-design.md)). That is what makes `git-commit-writer` and `meeting-notes-summarizer` runnable.
* **AF: the Quality Report**, built after this one on purpose: it gathers the checks, the token cost, the criteria and their tests, and (now) the latest test result for a version, and had little to show before the Lab kept results.
