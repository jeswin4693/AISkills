"""Make a Task Plan: read the request, measure it against the repository, plan the process, the rules and the tokens.

READ-ONLY. Nothing is run, and nothing is changed or created in the repository. With a model, the scope is read by the
model and verified by code. Without one ("facts only"), only what code can measure is planned. Either way the size of
the task comes from the repository graph, and the numbers are computed by code.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from ..graph import query
from ..graph.build import build_graph
from ..providers.base import LLMProvider
from . import intake, process, rules, sizing, tokens
from .mentions import find_mentions
from .models import Mention, Reach, Reading, TaskPlan

MIN_WORDS = 10


class PlanError(Exception):
    """The plan could not be made for a reason the person can act on."""


def _no_model_reading(task_type: str) -> Reading:
    return Reading(
        task_type=task_type, summary="(no model was used, so the request was not read)", stated=[], constraints=[], out_of_scope=[],
        declared_risks=[], gaps=[], assumptions=[],
    )


def _reach(g, mentions: list[Mention]) -> list[Reach]:
    out: list[Reach] = []
    for m in mentions:
        if m.ambiguous or not m.target:
            continue
        try:
            imp = query.impact(g, m.target, depth=3)
        except query.QueryError:
            continue
        files = sorted({d["path"] for d in imp["dependents"] if not d["test"] and d["conf"] == "resolved"})
        out.append(Reach(
            target=m.text, files_reached=files, tests_tied=imp["tests_tied"], risk=imp["risk"]["level"],
            possible=imp["risk"]["factors"]["possible_dependents"],
        ))
    return out


def make_plan(
    prompt: str, *, provider: LLMProvider | None = None, repo: str | Path | None = None, task_type: str | None = None,
    tier: int | None = None, allow_lower: bool = False, budget: int | None = None, sensitive: tuple[str, ...] = (),
    now: datetime | None = None,
) -> TaskPlan:
    words = prompt.strip()
    if len(words.split()) < 3 or len(words) < MIN_WORDS:
        raise PlanError("Describe the task in at least a sentence.")
    if tier is not None and not 0 <= tier <= 3:
        raise PlanError("The tier must be 0, 1, 2 or 3.")
    notes: list[str] = []
    calls = 0

    g = None
    root: Path | None = None
    if repo is not None:
        root = Path(repo).resolve()
        g = build_graph(root, use_cache=True, with_history=False)  # NotADirectoryError says what is wrong
    mentions = find_mentions(g, words) if g else []

    raw = None
    if provider is not None:
        facts = None
        if g is not None:
            facts = intake.facts_for_model(mentions, dict(Counter(f.lang for f in g.files.values())), len(g.files))
        raw, used = intake.read_task(provider, words, facts)
        calls += used
        reading, vnotes, targets = intake.verify_reading(raw, words)
        notes += vnotes
        if g is not None and targets:
            known = {m.text.lower() for m in mentions}
            mentions += [m for m in find_mentions(g, "", extra=targets, source="model") if m.text.lower() not in known]
    else:
        reading = _no_model_reading(task_type or "other")
    if task_type:
        reading = reading.model_copy(update={"task_type": task_type})

    reach = _reach(g, mentions) if g else []
    resolved = [m for m in mentions if not m.ambiguous and m.target]
    measured = bool(reach)
    code_gaps = intake.code_gaps(mentions, reading.task_type, g is not None, measured)
    gaps = sorted([*code_gaps, *reading.gaps], key=lambda x: not x.blocking)
    reading = reading.model_copy(update={"gaps": gaps})

    decision = sizing.decide_tier(
        reading.task_type, reach, [m.file for m in resolved], reading.declared_risks, sensitive=sensitive, override=tier, allow_lower=allow_lower,
    )

    all_rules, rule_files = rules.load_rules(root) if root else ([], [])
    applied: list = []
    if provider is not None and all_rules:
        chosen, rnotes, used = rules.select_rules(provider, words, all_rules)
        calls += used
        notes += rnotes
        applied += [rules.applied(r, why) for r, why in chosen]
    elif all_rules:
        applied += [rules.applied(r, "not filtered: no model was used to pick the ones that apply") for r in all_rules]
    applied += rules.from_prompt([*reading.constraints, *reading.out_of_scope])

    new_files: list[tuple[str, str, str]] = []
    if raw is not None:
        for nf in raw.files_to_create[: intake.MAX_NEW_FILES]:
            path = nf.path.strip().replace("\\", "/")
            if not intake.safe_new_path(path):
                notes.append(f'A file to create, "{nf.path[:60]}", was ignored: it is not a plain relative path inside the project.')
            elif g is not None and path in g.files:
                notes.append(f'"{path}" already exists, so the work would change it, not create it.')
            else:
                new_files.append((path, " ".join(nf.purpose.split()), nf.size))
    token_plan, tnotes = tokens.plan_tokens(g, root, mentions, reach, rule_files, new_files, decision.tier, budget, prompt=words)
    notes += tnotes

    not_checked = [
        "Nothing was run, and nothing in the repository was changed or created. This is a plan.",
        "Token numbers are estimates (about 4 characters a token). They cover context to read and files to create, not the model's own reasoning or replies.",
        "No rule is enforced yet: a person must review each one. Enforcement comes with the hooks step.",
        "Names are matched exactly. A plain word such as build is not taken for a function unless it is written `build` or build().",
        "Only proven links count toward the size of a change. Dynamic calls and name-only matches are not counted.",
    ]
    if g is not None:
        not_checked.append("The size reflects only the code your request names. If the work turns out to touch other code, that was not measured.")
    if provider is not None:
        not_checked.append(
            "The model saw your words, the names and places of what you mentioned, file and language counts, and the lines of your rule files. It saw no file contents."
        )
    else:
        not_checked.append("No model was used, so what the request contains and does not say was not read. Only the repository facts were planned.")
    if g is None:
        not_checked.append("No repository was given, so the size of the change, the rules and the reading plan could not be measured.")

    return TaskPlan(
        created_at=(now or datetime.now(timezone.utc)).isoformat(timespec="seconds"), prompt=words,
        mode="model" if provider is not None else "facts only", model=f"{provider.name}/{provider.model}" if provider is not None else "",
        repo=root.name if root else "", reading=reading, mentions=mentions, reach=reach, tier=decision,
        phases=process.phases_for(decision.tier), stop_triggers=process.stop_triggers_for(decision.tier), rules=applied,
        rules_found=len(all_rules), token_plan=token_plan, notes=notes, not_checked=not_checked, model_calls=calls,
    )


# ---- reading it ---------------------------------------------------------------------------------------


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def _bullets(items, fmt) -> list[str]:
    return [fmt(i) for i in items] or ["- (none)"]


def render_markdown(p: TaskPlan) -> str:
    r, t, tp = p.reading, p.tier, p.token_plan
    out = ["# Task plan", "", "> **A plan only.** Nothing was run, and nothing was changed or created.", ""]
    out += [f"**Request:** {p.prompt}", "", f"**Read by:** {p.model if p.mode == 'model' else 'no model (facts only)'}" + (f" · repository `{p.repo}`" if p.repo else ""), ""]

    named = [m for m in p.mentions if not m.ambiguous]
    named_lines = ["**Code your request names (matched in the repository):**", *_bullets(named, lambda m: f"- `{m.text}` → {m.file}" + (f":{m.line}" if m.line else "")), ""]
    blocking = [g for g in r.gaps if g.blocking]
    question_lines = _bullets(r.gaps, lambda g: f"- {'**[BLOCKING]** ' if g.blocking else ''}{g.question} _{g.why}_ ({'found by the code graph' if g.source == 'code' else 'asked by the model'})")
    if p.mode == "model":
        out += ["## 1. What your request contains", "", f"**Kind of task:** {r.task_type}. {r.summary}", ""]
        out += ["**You asked for:**", *_bullets(r.stated, lambda i: f'- {i.text} — "{i.quote}"'), ""]
        out += ["**Rules you gave:**", *_bullets(r.constraints, lambda i: f'- {i.text} — "{i.quote}"'), ""]
        out += ["**You said NOT to:**", *_bullets(r.out_of_scope, lambda i: f'- {i.text} — "{i.quote}"'), ""]
        out += ["**Risks you named:**", *_bullets(r.declared_risks, lambda i: f'- {i.text} — "{i.quote}"'), ""]
        out += named_lines
        out += ["## 2. What it does NOT say", ""]
        out += [f"**Questions** ({len(blocking)} blocking, {len(r.gaps) - len(blocking)} other). Answer these before work starts:", "", *question_lines]
        out += ["", "**Assumptions** (not facts: none is used until you approve it):", *_bullets(r.assumptions, lambda a: f"- {a.text} _{a.why}_"), ""]
    else:
        out += ["## 1. What your request contains, and what it does not say", "",
                f"**Not read.** No model was used, so what the request asks for, the rules and limits in it, and what it leaves out were not worked out. "
                f"Kind of task, as you gave it: **{r.task_type}**. Run again without `--no-ai` to get that part.", ""]
        out += named_lines
        out += ["**Questions the code graph found:**", "", *question_lines, ""]

    out += ["## 3. Size and process", "", f"**Tier {t.tier}: {process.TIER_NAMES[t.tier]}** (starting point for this kind of task: {t.baseline}). The highest signal wins:", ""]
    out += [f"- {s.name}: tier {s.floor}+ — {s.evidence}" for s in t.signals]
    if t.note:
        out += ["", f"_{t.note}_"]
    out += ["", f"Phases, each reading one file and writing one file under `{process.ARTIFACT_DIR}`:", "", "| # | Phase | Reads | Writes | Done when | A person approves |", "|---|---|---|---|---|---|"]
    out += [f"| {i} | {ph.title} | {ph.reads} | {ph.writes} | {ph.gate} | {'yes' if ph.approval else 'no'} |" for i, ph in enumerate(p.phases, start=1)]
    out += ["", "**It stops and asks when:**", *[f"- {s}" for s in p.stop_triggers], ""]

    out += ["## 4. Rules that apply", "", f"{len(p.rules)} listed, from {p.rules_found} found in the repository's rule files and your own words. **None is enforced yet.**", ""]
    out += ["| Id | Source | Rule | Why it applies |", "|---|---|---|---|"]
    out += [f"| {x.id} | {x.source}{':' + str(x.line) if x.line else ''} | {_cut(x.text.replace('|', '/'), 220)} | {x.why.replace('|', '/')} |" for x in p.rules] or ["| | | (none) | |"]
    out += [""]

    out += ["## 5. Token plan (estimates)", "", f"Budget to read: {tp.budget:,} tokens. Planned reading: **{tp.read_total:,}**" + (f" (the same files read whole would cost about {tp.whole_files_total:,})" if tp.whole_files_total > tp.read_total else "") + f". Method: {tp.method}.", ""]
    out += ["Read in this order, cheapest useful context first:", "", "| # | What | Tokens | Why |", "|---|---|---|---|"]
    out += [f"| {i} | `{x.path}`{(' ' + x.symbol + ' lines ' + x.lines) if x.kind == 'slice' else ' (whole file)'} | {x.tokens:,} | {x.why} |" for i, x in enumerate(tp.reads, start=1)] or ["| | (nothing to read) | | |"]
    if tp.dropped:
        out += ["", "**Not planned (over the budget, or beyond the most relevant tests):**", *[f"- `{x.path}` {x.symbol} ({x.tokens:,} tokens): {x.why}" for x in tp.dropped]]
    out += ["", "Files the work would create:", "", "| Path | For | Size | Tokens |", "|---|---|---|---|"]
    out += [f"| `{c.path}` | {c.purpose} | {c.size} | {c.tokens:,} |" for c in tp.create] or ["| (none) | | | |"]
    out += [""]

    if p.notes:
        out += ["## Notes", "", *[f"- {n}" for n in p.notes], ""]
    out += ["## What was NOT checked", "", *[f"- {n}" for n in p.not_checked], ""]
    return "\n".join(out)
