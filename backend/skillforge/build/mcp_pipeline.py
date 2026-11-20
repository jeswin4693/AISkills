"""Build an MCP server from an approved requirement: design, one repair, checks, files, report.

Same shape as the agent build and the same rules: completeness and every check are decided by code, a repair is kept only if it
is not worse, a check is "passed" only if it ran, and the report says what did not run. The generated code is untrusted: it is
read here (parsed, never run), and it is only ever run through the sandbox (build/mcp_protocol.py). Stricter than the checks that
guard an import from outside: here a package outside the standard library, an undeclared permission or a secret that is not a
plain environment variable name FAILS, because the model was told not to do them.
"""

from __future__ import annotations

import ast
import json
import keyword
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..providers.base import LLMProvider
from ..results import FAILED, NOT_RUN, PASSED, WARNING, CheckResult
from ..validate import validate_files
from ..validate.mcp import SECRET_PATTERNS, analyze_server, third_party
from ..validate.static import MAX_DESCRIPTION, SLUG
from .agent import person_lines
from .mcp import OFFERED_PERMISSIONS, McpDefinition, assemble_mcp, design_mcp, render_mcp_files
from .mcp_protocol import PROTOCOL_ROW, McpRunner, run_protocol_tests
from .models import RequirementSpec
from .pipeline import BuildError
from .quality import VAGUE, norm
from .render import MAX_NAME, write_files

MAX_TOOLS = 8
# Words that mean a tool returns something other than the real answer. A tool does the real job or raises an error.
MADE_UP = re.compile(r"\b(simulat\w*|placeholder|dummy|fake\w*|mock\w*|hard-?coded|stub\w*)\b", re.I)
MAX_CASES = 30
MAX_BODY_LINES = 60
IDENT = re.compile(r"^[a-z][a-z0-9_]{0,63}\Z")
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{1,63}\Z")
Progress = Callable[[str], None]


@dataclass
class McpBuildResult:
    status: str  # "ok": every check passed and the server really ran. "draft": a check failed, or it never ran.
    out_dir: Path
    definition: McpDefinition
    spec: RequirementSpec
    checks: list[CheckResult]
    files: list[str]
    model_calls: int = 0
    notes: list[str] = field(default_factory=list)
    draft_reason: str = ""


def _valid_ident(name: str) -> bool:
    return bool(IDENT.match(name)) and not keyword.iskeyword(name)


def _types_match(value: object, kind: str) -> bool:
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, str)


def _returns_text(source: str) -> dict[str, bool]:
    """tool name -> whether the function contains a `return` with a value."""
    tree = ast.parse(source)
    out: dict[str, bool] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = any(isinstance(n, ast.Return) and n.value is not None for n in ast.walk(node))
    return out


def check_mcp(defn: McpDefinition, spec: RequirementSpec, files: dict[str, str]) -> list[CheckResult]:
    """Everything code can say about a design and its rendered files. Failures are structural or unsafe; wording is a warning."""
    out: list[CheckResult] = []

    def row(name: str, problems: list[str], ok_detail: str = "", status: str = FAILED) -> None:
        out.append(CheckResult(name, status, "; ".join(problems)) if problems else CheckResult(name, PASSED, ok_detail))

    row("the server name is a valid name", [] if SLUG.match(defn.name) and len(defn.name) <= MAX_NAME else
        [f"'{defn.name}' is not lowercase letters, digits and hyphens of at most {MAX_NAME} characters"])
    description = " ".join(defn.description.split())
    row("description is present and within the limit",
        ([] if description else ["the description is empty"]) + ([f"longer than {MAX_DESCRIPTION} characters"] if len(description) > MAX_DESCRIPTION else []))
    row("there are between 1 and %d tools" % MAX_TOOLS, [] if 1 <= len(defn.tools) <= MAX_TOOLS else [f"{len(defn.tools)} tools"], f"{len(defn.tools)} tools")

    names = [t.name for t in defn.tools]
    problems = [f"tool '{n}' is not a valid name" for n in names if not _valid_ident(n)]
    problems += [f"tool '{n}' appears more than once" for n in sorted({n for n in names if names.count(n) > 1})]
    for tool in defn.tools:
        pnames = [p.name for p in tool.params]
        problems += [f"parameter '{p}' of {tool.name} is not a valid name" for p in pnames if not _valid_ident(p)]
        problems += [f"parameter '{p}' of {tool.name} appears more than once" for p in sorted({p for p in pnames if pnames.count(p) > 1})]
    row("tool and parameter names are valid and unique", problems)

    server = files.get("server.py", "")
    facts = None
    try:
        facts = analyze_server(server)
        found = [t.name for t in facts.tools]
        row("server.py parses and holds exactly the designed tools", [] if found == names else [f"the file has {found}, the design has {names}"])
    except (SyntaxError, ValueError, RecursionError) as exc:
        row("server.py parses and holds exactly the designed tools", [f"it does not parse: {exc}"])
    if facts is not None:
        returns = _returns_text(server)
        row("every tool returns text", [f"{n} never returns a value" for n in names if not returns.get(n)])
        unused = sorted(facts.unused_imports)
        row("every import in a tool is used", [f"{', '.join(unused)} is imported but never used: a tool that imports what its job needs and does not use it has been stubbed"] if unused else [])
        row("every name a tool uses is defined (write the imports inside the tool)", [f"{', '.join(sorted(facts.undefined))} is used but never imported or defined"] if facts.undefined else [])
        observed = facts.capabilities
        declared = set(defn.permissions)
        not_offered = sorted(declared - set(OFFERED_PERMISSIONS))
        row("only permissions the builder offers are declared", [f"{', '.join(not_offered)} is not offered by the MCP builder yet"] if not_offered else [])
        undeclared = sorted(observed - declared)
        row("the permissions declared cover what the code does", [f"the code can {', '.join(undeclared)} but the design does not declare it"] if undeclared else [], ", ".join(sorted(declared)) or "none")
        unused = sorted((declared & set(OFFERED_PERMISSIONS)) - observed)
        row("no permission is declared that the code does not use", [f"{', '.join(unused)} is declared but the code never uses it"] if unused else [], status=WARNING)
        extra = third_party(facts)
        row("only the standard library and mcp are imported", [f"it also imports {', '.join(extra)}: nothing else is installed"] if extra else [])
        invalid = [n for n in defn.env_vars if not ENV_NAME.match(n)]
        env_problems = [f"'{n[:40]}' is not an environment variable name (capital letters, digits and underscores): give names, never values" for n in invalid]
        env_problems += [f"it reads {n} but the design does not list it in env_vars" for n in sorted(facts.env_names - set(defn.env_vars))]
        if facts.env_dynamic:
            env_problems.append("it reads an environment variable whose name is not written in the code, or all of them")
        row("environment variables are plain names, listed, and read by name", env_problems, ", ".join(defn.env_vars) or "none")
        never_read = sorted(set(defn.env_vars) - facts.env_names)
        row("every environment variable listed is read", [f"{', '.join(never_read)} is listed but never read"] if never_read else [], status=WARNING)
        pretend = sorted({f"{t.name} ({m.group(0).lower()})" for t in defn.tools for m in MADE_UP.finditer("\n".join(map(str, t.body)))})
        row("no tool returns simulated or made-up data", [f"{', '.join(pretend)}: a tool must do the real job or raise an error, never pretend"] if pretend else [])
        big = [t.name for t in defn.tools if len([ln for item in t.body for ln in str(item).splitlines() if ln.strip()]) > MAX_BODY_LINES]
        row("tool bodies are short", [f"{', '.join(big)} is over {MAX_BODY_LINES} lines"] if big else [], status=WARNING)

    leaks = sorted({f"{path}: {label}" for path, text in files.items() for label, pattern in SECRET_PATTERNS if pattern.search(text)})
    row("no key or token in any file", [f"{'; '.join(leaks)}. Never type a key: name the environment variable it is read from"] if leaks else [], "none found")

    by_name = {t.name: t for t in defn.tools}
    ids, covered = set(defn.acceptance_criteria), {c for case in defn.cases for c in case.covers}
    case_problems = [f"case '{c.name}' calls '{c.tool}', which the server does not have" for c in defn.cases if c.tool not in by_name]
    case_problems += [f"{len(defn.cases)} cases (at most {MAX_CASES})"] if len(defn.cases) > MAX_CASES else []
    row("test cases name a tool the server has", case_problems, f"{len(defn.cases)} cases")
    arg_problems: list[str] = []
    for case in defn.cases:
        tool = by_name.get(case.tool)
        if tool is None:
            continue
        try:
            arguments = json.loads(case.arguments_json)
        except ValueError:
            arg_problems.append(f"case '{case.name}': the arguments are not valid JSON")
            continue
        if not isinstance(arguments, dict):
            arg_problems.append(f"case '{case.name}': the arguments are not a JSON object")
            continue
        want = {p.name: p.type for p in tool.params}
        if set(arguments) != set(want):
            arg_problems.append(f"case '{case.name}': the arguments are {sorted(arguments)} but {case.tool} takes {sorted(want)}")
        arg_problems += [f"case '{case.name}': {k} should be {want[k]}" for k, v in arguments.items() if k in want and not _types_match(v, want[k])]
        if case.expect in ("contains", "equals") and not case.expected_text:
            arg_problems.append(f"case '{case.name}' expects {case.expect} but gives no text")
    row("test case arguments match the tool's parameters and each case says what to expect", arg_problems)
    row("every acceptance criterion is covered by a test case", [f"{i} has no test case" for i in sorted(ids - covered)], f"{len(ids)} criteria")
    row("test case ids all refer to a real acceptance criterion", [f"unknown id {i}" for i in sorted(covered - ids)], status=WARNING)
    kinds = {c.kind for c in defn.cases}
    row("there is a positive and a negative test case", [f"no {k} test case" for k in ("positive", "negative") if k not in kinds])

    text = norm(files.get("README.md", ""))
    missing = [line for group in person_lines(spec).values() for line in group if norm(line) not in text]
    row("the person's rules, criteria and failure behaviour are in README.md word for word", [f'missing: "{m}"' for m in missing])
    prose = " ".join(t.description for t in defn.tools)
    found_vague = sorted({m.group(0).lower() for m in VAGUE.finditer(prose)})
    row("no vague wording in the tool descriptions", [f"vague: {', '.join(found_vague)}"] if found_vague else [], status=WARNING)
    return out


def _problems(checks: Sequence[CheckResult]) -> list[str]:
    return [f"{c.name}: {c.detail}" for c in checks if c.status in (FAILED, WARNING)]


def _score(defn: McpDefinition, spec: RequirementSpec) -> tuple[int, int]:
    """(failed checks, warnings): smaller is better, and a failure outweighs any number of warnings."""
    checks = check_mcp(defn, spec, render_mcp_files(defn, spec))
    return (sum(c.status == FAILED for c in checks), sum(c.status == WARNING for c in checks))


def _report(defn: McpDefinition, checks: Sequence[CheckResult], notes: Sequence[str], status: str, reason: str) -> str:
    ran = [c for c in checks if c.status != NOT_RUN]
    failed = [c for c in ran if c.status == FAILED]
    warned = [c for c in ran if c.status == WARNING]
    skipped = [c for c in checks if c.status == NOT_RUN]
    head = defn.name.replace("-", " ").title()
    lines = [
        f"# Build report: {head}", "",
        "Status: " + ("every check passed and the server was run." if status == "ok" else f"DRAFT: {reason}"), "",
        f"{len(ran) - len(failed) - len(warned)} passed, {len(warned)} warning(s), {len(failed)} failed, {len(skipped)} not run.", "",
    ]
    for title, group in (("Failed", failed), ("Warnings (read these)", warned), ("Not run", skipped)):
        if group:
            lines += [f"## {title}", ""] + [f"- {c.name}: {c.detail}" if c.detail else f"- {c.name}" for c in group] + [""]
    lines += ["## Passed", ""] + [f"- {c.name}" for c in ran if c.status == PASSED] + [""]
    if notes:
        lines += ["## Notes", ""] + [f"- {n}" for n in notes] + [""]
    lines += ["Passing these checks is not proof that the server is good: they read the file, and a run shows only what its test cases ask.", ""]
    return "\n".join(lines)


def build_mcp_from_spec(
    spec: RequirementSpec, provider: LLMProvider, *, out_root: Path, force: bool = False, now: datetime | None = None,
    calls: int = 0, notes: list[str] | None = None, progress: Progress | None = None, runner: McpRunner | None = None,
) -> McpBuildResult:
    """Everything after the person approved the requirement. Costs one model call, or two when the first design had problems.
    `runner` starts the server in the sandbox (None: the real sandbox); a design that failed its checks is never started."""
    now = now or datetime.now(timezone.utc)
    say = progress or (lambda message: None)
    notes = list(notes or [])
    say("Designing the server from your approved requirement")
    draft, used = design_mcp(provider, spec)
    calls += used
    defn = assemble_mcp(draft, spec, provider, now)
    problems = _problems(check_mcp(defn, spec, render_mcp_files(defn, spec)))
    if problems:
        say(f"The design has {len(problems)} problem(s); asking the model to fix them once")
        first = _score(defn, spec)
        draft, used = design_mcp(provider, spec, problems)
        calls += used
        second = assemble_mcp(draft, spec, provider, now)
        if _score(second, spec) <= first:
            defn = second
            now_score = _score(defn, spec)
            notes.append(
                f"The first design had {len(problems)} problem(s); the model was asked to fix them once. "
                f"Failed checks and warnings went from {first[0]} and {first[1]} to {now_score[0]} and {now_score[1]}."
            )
        else:  # a repair must never make the server worse
            notes.append(f"The first design had {len(problems)} problem(s); the model was asked to fix them once, but its second design was worse, so the first was kept.")
    say("Writing the files and running every check")
    if not SLUG.match(defn.name) or len(defn.name) > MAX_NAME:  # the name becomes a folder name: never trust it
        raise BuildError(f"'{defn.name}' is not a valid server name (lowercase letters, digits and hyphens, max {MAX_NAME}).")
    if defn.provenance.name_adjusted:
        notes.append(f"The model's name was changed to '{defn.name}' because it was not a valid name.")
    files = render_mcp_files(defn, spec)
    static = validate_files({path: text.encode("utf-8") for path, text in files.items()}, folder=defn.name, kind="mcp")
    static_and_design = [*check_mcp(defn, spec, files), *static]
    if any(c.status == FAILED for c in static_and_design):
        protocol = [CheckResult(PROTOCOL_ROW, NOT_RUN, "a check failed, so the server was not started")]
        complete, reason = False, "a check failed, so read it before keeping this server."
    else:
        say("Starting the server in the sandbox and calling its test cases over the MCP protocol")
        run = run_protocol_tests(defn, files, runner)
        protocol, complete = run.checks, run.complete
        reason = "" if complete else (run.reason or "a check failed, so read it before keeping this server.")
    checks = [*static_and_design, *protocol]
    failed = any(c.status == FAILED for c in checks)
    status = "ok" if complete and not failed else "draft"
    if failed:
        reason = "a check failed, so read it before keeping this server."
    files["report.md"] = _report(defn, checks, notes, status, reason)
    out_dir = out_root / defn.name
    try:
        write_files(out_dir, files, overwrite=force)
    except FileExistsError as exc:
        raise BuildError(str(exc)) from exc
    return McpBuildResult(status, out_dir, defn, spec, checks, sorted(files), calls, notes, "" if failed or status == "ok" else reason)
