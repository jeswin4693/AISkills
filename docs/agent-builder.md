# Agent Builder

The second kind the app builds (Phase 1 of the [Component Factory](component-factory.md)). You describe a Claude Code
**subagent** in your own words, answer only what is missing, approve the requirement, and get an `AGENT.md` that is checked,
kept in its own library, exported, and installed as one file in `~/.claude/agents`. "Agent" here means a **definition file**,
not a running agent loop.

## Use it

In the web Builder pick **Agent** (the picker appears because the app now builds more than one kind), or call the API with
`"kind": "agent"` ([api.md](api.md)). The Library has an **Agents** tab. There is no `--kind` flag on the command line yet.

## What you get

```
AGENT.md          the subagent: front matter (name, description, tools) and its instructions
README.md         for people: what it can do on your machine, install, limits, what was not tested
agent.sdm.json    the design, with the tools code worked out
spec.json         your approved requirement and the words behind it
tests/cases.json  what a correct run looks like (data: nothing has run them)
report.md         every check, what failed, what warns, what did not run
```

`AGENT.md` has exactly three front-matter keys, written by a YAML library: `name`, `description` (the model's sentence plus
"Use when the request involves ..." made by code from the trigger phrases) and `tools`. The body is: who the agent is, the steps
for when it is called, what it reports back, **Rules** (your constraints word for word, then any the design added), **Done
when** (your acceptance criteria word for word) and **If something goes wrong** (your failure behaviour word for word).

## The rules it follows

- **Least privilege, by code.** `tools` is always written, explicitly, from the permissions the design asked for through the same
  mapping as skills (`read_files` = `Read, Grep, Glob`, `write_files` = `Edit, Write`, `run_commands` = `Bash`, `network` =
  `WebFetch, WebSearch`). An agent can always read, so the floor is `Read, Grep, Glob`: a missing or empty `tools` line would
  give it every tool. Anything beyond reading is flagged for a person to read in `report.md`. `permissionMode`, `model`,
  `hooks` and `mcpServers` are never written.
- **Completeness is a checklist in code**: the same six items as a skill (goal, inputs, outputs, constraints, acceptance
  criteria, failure behaviour) in agent wording, each answered only with a quote verified in your own words. What the model
  guesses the request to be never blocks an agent.
- **The checks decide, not the model.** Failures: an invalid name, no description, no role, steps or report format, a tools line
  that is not what the permissions give, an acceptance criterion with no test, no positive or no negative test, or one of your
  own lines missing from `AGENT.md`. Warnings: vague wording, more than 7 steps or a step over 60 words, no "when" in the
  description. One repair attempt is shown the exact problems and is kept only if it is not worse.
- **A check is "passed" only if it ran.** The agent's test cases are not run against a model, and `report.md` says so.

## Importing and installing an agent

The definition check for an imported `AGENT.md` fails on a missing or empty `tools` line (Claude Code would give it every tool),
invalid front matter, a bad name or no instructions, and **warns** on `permissionMode: bypassPermissions`, `hooks` and
`mcpServers`. Every other static check (hidden characters, attack wording, size) runs as for a skill.

**Install writes one file**, `<name>.md`, into `~/.claude/agents` (or a folder you give). It never replaces an existing file
unless you say so, and then the old one is copied to `backups-agent` first.

## Limits

- Nothing has run an agent builder against a **live model** yet; the tests use a mock model. Its prompts and the quality of what
  a real model drafts are unverified.
- Not checked: unknown front-matter keys for agents (the list of subagent keys is incomplete in the spec and was not verified),
  and whether Claude Code reads `tools` as a comma-separated string exactly this way (the form is from the documentation,
  not tried against a live Claude Code).
- The token-cost estimate and the `eval` harness are for skills only.
- The risk diff between versions is skill-shaped; it still works on the files but is not agent-aware (Phase 4).
- The web flow for agents was not run in a real browser; the 39 existing browser behaviours (skills) still pass.
