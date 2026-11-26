"""A canary report as text for a terminal. What happened comes first, task by task, then what did not run, then the verdict."""

from __future__ import annotations

from .corpus import Measurement
from .runner import MAX_TURNS, CanaryReport

MEASURE_LIMITS = (
    "The skills were written by the author of the scan, who knows what it looks for, so these numbers are optimistic. The corpus is small and made of text "
    "skills. Two bad skills are in it because the scan is expected to miss them."
)


def render_report(report: CanaryReport) -> str:
    lines = [
        f"Behaviour scan of {report.kind} '{report.skill}': {len(report.runs)} task run(s), {report.calls} model call(s). "
        "The tools were fake and nothing real was touched."
    ]
    controls = {c.scenario["id"]: c for c in reversed(report.controls)}  # one control line per task (the first control run of it)
    for run in report.runs:
        steps = max((t.step for t in run.turns), default=0)
        state = "finished" if run.finished else "stopped early" if run.error else f"did not finish in {MAX_TURNS} steps"
        lines.append(f'  task [{run.scenario["source"]}]: "{run.scenario["message"]}"  ({state}, {steps} step(s))')
        lines += [f"      {o.severity.upper():8} step {o.turn}  {o.detail}   <- {o.evidence}".rstrip(" <-") for o in run.observations]
        if not run.observations:
            lines.append("      nothing observed")
        if run.reply.strip():  # what the model finally said: a refusal ("I cannot do that") is the most telling line of a run with no steps, and code cannot judge it, so it is shown
            answer = " ".join(run.reply.split())
            lines.append(f'      answer: "{answer if len(answer) <= 160 else answer[:159] + "…"}"')
        control = controls.get(run.scenario["id"])
        if control is not None:
            what = "nothing observed" if not control.observations else "also did: " + ", ".join(sorted({o.kind for o in control.observations}))
            lines.append(f"      control without the skill: {what}")
    lines += [f"  did not run: {text}" for text in report.not_run]
    lines.append(report.verdict())
    return "\n".join(lines)


def render_measurement(m: Measurement) -> str:
    s = m.summary()
    lines = [f"{'SKILL':26} {'LABEL':5} {'SCAN':16} {'STATIC':7} WHAT IT DID"]
    for r in m.results:
        lines.append(f"{r.name:26} {r.label:5} {r.outcome:16} {'caught' if r.static_checks else '-':7} {r.finding or r.error}".rstrip())
    lines += [
        "",
        f"Bad skills: {s['bad']}. The behaviour scan flagged {s['caught_by_canary']}, the static checks about wording flagged {s['caught_by_static']}, "
        f"either caught {s['caught_by_either']}. Missed by the scan: {', '.join(s['missed_by_canary']) or 'none'}. Missed by both: {', '.join(s['missed_by_both']) or 'none'}.",
        f"Good skills: {s['good']}. False alarms (flagged): {s['false_alarms']}" + (f" ({', '.join(s['false_alarm_names'])})" if s['false_alarm_names'] else "")
        + f". Unclear: {s['unclear']}. Caution only: {s['caution']}. Flagged by the static wording checks: {s['static_false_alarms']}.",
    ]
    if s["not_run"]:
        lines.append(f"{s['not_run']} skill(s) could not be run (the model could not be asked) and are counted nowhere above.")
    lines.append(f"{s['calls']} model calls. {MEASURE_LIMITS}")
    return "\n".join(lines)
