"""Build a Node MCP server from an approved requirement: design, one repair, checks, files, report.

Same shape as build/mcp_pipeline.py and the same rules (completeness and every check are decided by code, a repair is kept only if it is not worse, a check
is "passed" only if it ran, and the report says what did not run). Stricter than the checks that guard an import from outside (validate/mcp_node.py): here
a tool body may use only the names, properties and imports on the allow-lists in build/mcp_node.py, because the model was told to and code can hold it to that.
The generated code is untrusted: it is read here (parsed, never run), and it is only ever run through the sandbox (build/mcp_node_protocol.py).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..mcpnode import SERVER_FILE, SERVER_SDK, is_our_lock, package_json
from ..providers.base import LLMProvider
from ..results import FAILED, NOT_RUN, PASSED, WARNING, CheckResult
from ..validate import validate_files
from ..validate.mcp import SECRET_PATTERNS
from ..validate.mcp_node import KNOWN_GLOBALS, analyze_node_server, other_node_code
from ..validate.static import SLUG
from .mcp_node import (
    BODY_IMPORTS, DENY_PROPS, FILE_IMPORTS, GLOBALS_ALLOWED, NETWORK_GLOBALS, NodeDefinition, NodeDesignError, assemble_node, body_is_whole, body_returns_value,
    clean_body, design_node, render_node_files, valid_param,
)
from .mcp_node_protocol import run_node_protocol_tests
from .mcp_pipeline import (
    ENV_NAME, MADE_UP, MAX_BODY_LINES, MAX_TOOLS, McpBuildResult, Progress, _problems, _report, check_cases_and_words, check_names,
)
from .mcp_protocol import PROTOCOL_ROW, McpRunner
from .models import RequirementSpec
from .pipeline import BuildError
from .render import MAX_NAME, write_files

OFFERED = ("read_files", "network")
MIN_ECHO = 4  # a test input shorter than this is too common to mean anything when it appears in a tool's text
HEADER_MODULES = frozenset({SERVER_SDK, f"{SERVER_SDK}/stdio", "zod"})
HIDEABLE = KNOWN_GLOBALS | {"server", "z", "McpServer", "StdioServerTransport"}  # names a declaration in a body must not take: it would hide the real one


def _plain(module: str) -> str:
    return module[5:] if module.startswith("node:") else module


def check_node(defn: NodeDefinition, spec: RequirementSpec, files: dict[str, str]) -> list[CheckResult]:
    """Everything code can say about a design and its rendered files. Failures are structural or unsafe; wording is a warning."""
    out: list[CheckResult] = []

    def row(name: str, problems: list[str], ok_detail: str = "", status: str = FAILED) -> None:
        out.append(CheckResult(name, status, "; ".join(problems)) if problems else CheckResult(name, PASSED, ok_detail))

    names = [t.name for t in defn.tools]
    check_names(defn, row, valid_param)
    server = files.get(SERVER_FILE, "")
    facts = None
    try:
        facts = analyze_node_server(server)
        found = [t.name for t in facts.tools]
        row("server.ts parses and holds exactly the designed tools", [] if found == names else [f"the file has {found}, the design has {names}"])
    except (SyntaxError, ValueError, RecursionError) as exc:
        row("server.ts parses and holds exactly the designed tools", [f"it does not parse: {getattr(exc, 'msg', None) or exc}"])
    declared = set(defn.permissions)
    network, read_files = "network" in declared, "read_files" in declared

    parts = [(t.name, clean_body(t.body)) for t in defn.tools]
    row("every tool body is exactly the statements of one function", [f"{n}'s body closes the function early or does not parse" for n, b in parts if not body_is_whole(b)])
    row("every tool returns text", [f"{n} never returns a value" for n, b in parts if not body_returns_value(b)])

    if facts is not None:
        unused = sorted(facts.unused_imports)
        row("every import in a tool is used", [f"{', '.join(unused)} is imported but never used: a tool that imports what its job needs and does not use it has been stubbed"] if unused else [])
        allowed_imports = {**BODY_IMPORTS, **(FILE_IMPORTS if read_files else {})}
        import_problems = []
        for item in defn.imports:
            if item.module not in allowed_imports:
                import_problems.append(f"imports from '{item.module[:40]}', which is not on the allow-list ({', '.join(sorted(allowed_imports))})")
            else:
                extra_names = sorted(set(item.names) - allowed_imports[item.module])
                if extra_names:
                    import_problems.append(f"imports {', '.join(extra_names)} from {item.module}, which is not on the allow-list for that module")
        listed = {_plain(i.module) for i in defn.imports}
        unexpected = sorted(m for m in facts.imports if m not in listed and m not in HEADER_MODULES)
        import_problems += [f"the file imports '{m or 'a file'}', which the design does not list" for m in unexpected]
        row("only allow-listed modules and names are imported", import_problems)

        observed = facts.capabilities
        not_offered = sorted(declared - set(OFFERED))
        row("only permissions the builder offers are declared", [f"{', '.join(not_offered)} is not offered by the MCP builder yet"] if not_offered else [])
        undeclared = sorted(observed - declared)
        row("the permissions declared cover what the code does", [f"the code can {', '.join(undeclared)} but the design does not declare it"] if undeclared else [], ", ".join(sorted(declared)) or "none")
        never_used = sorted((declared & set(OFFERED)) - observed)
        row("no permission is declared that the code does not use", [f"{', '.join(never_used)} is declared but the code never uses it"] if never_used else [], status=WARNING)

        body_problems: list[str] = []
        local = {n for i in defn.imports for n in i.names}
        for tool, designed in zip(facts.tools, defn.tools, strict=False):
            ok_names = {p.name for p in designed.params} | local | GLOBALS_ALLOWED | (NETWORK_GLOBALS if network else set()) | {"process"}
            outside = sorted(tool.free - ok_names)
            if outside:
                body_problems.append(f"{designed.name} uses {', '.join(outside[:6])}, which is not on the allow-list of names")
            bad_props = sorted((tool.props | tool.strings) & DENY_PROPS)
            if bad_props:
                body_problems.append(f"{designed.name} uses {', '.join(bad_props)}, even as text: that is how a program reaches the language's internals")
            if tool.unsafe_index:
                body_problems.append(f"{designed.name} reaches a property by a computed name ({', '.join(sorted(set(tool.unsafe_index))[:3])}): use a Map, .at(), or an index that is a number")
            hidden = sorted((tool.declared - {p.name for p in designed.params} - {"text_result"}) & HIDEABLE)
            if hidden:
                body_problems.append(f"{designed.name} declares {', '.join(hidden[:4])}, a name that hides a built-in: a declaration anywhere in a body would change what the real name means")
            if tool.mutates:
                body_problems.append(f"{designed.name} changes {', '.join(sorted(set(tool.mutates))[:3])}, a built-in that every tool and the SDK share")
            if tool.meta:
                body_problems.append(f"{designed.name} uses import.meta, which tells where the server lives")
            if tool.process_other:
                body_problems.append(f"{designed.name} uses process for something other than reading an environment variable by name")
        row("tool bodies use only allow-listed names and properties", body_problems)
        row("no code is built from text or loaded while running, and nothing Node cannot run", sorted(facts.dynamic) + [f"it uses {w}" for w in sorted(facts.non_erasable)])
        invalid = [n for n in defn.env_vars if not ENV_NAME.match(n)]
        env_problems = [f"'{n[:40]}' is not an environment variable name (capital letters, digits and underscores): give names, never values" for n in invalid]
        env_problems += [f"it reads {n} but the design does not list it in env_vars" for n in sorted(facts.env_names - set(defn.env_vars))]
        if facts.env_dynamic:
            env_problems.append("it reads an environment variable whose name is not written in the code, or all of them")
        row("environment variables are plain names, listed, and read by name", env_problems, ", ".join(defn.env_vars) or "none")
        never_read = sorted(set(defn.env_vars) - facts.env_names)
        row("every environment variable listed is read", [f"{', '.join(never_read)} is listed but never read"] if never_read else [], status=WARNING)
        pretend = sorted({f"{t.name} ({m.group(0).lower()})" for t in defn.tools for m in MADE_UP.finditer("\n".join(map(str, t.body)))})
        row("no tool returns simulated or made-up data", [f"{', '.join(pretend)}: a tool must do the real job or throw an error, never pretend"] if pretend else [])
        test_inputs = set()
        for case in defn.cases:
            try:
                given = json.loads(case.arguments_json)
            except ValueError:
                continue
            test_inputs |= {v.strip() for v in (given.values() if isinstance(given, dict) else []) if isinstance(v, str) and len(v.strip()) >= MIN_ECHO}
        echoes = sorted({f"{tool.name} writes '{v}'" for tool in facts.tools for v in test_inputs for s in tool.strings if v in s})
        row("no tool writes a test case's own input as text", [f"{', '.join(echoes[:4])}: it may be answering the test instead of doing the job"] if echoes else [], status=WARNING)
        big = [t.name for t in defn.tools if len([ln for item in t.body for ln in str(item).splitlines() if ln.strip()]) > MAX_BODY_LINES]
        row("tool bodies are short", [f"{', '.join(big)} is over {MAX_BODY_LINES} lines"] if big else [], status=WARNING)

    beside = other_node_code({path: text.encode("utf-8") for path, text in files.items()})
    row("server.ts is the only code in the folder", [f"{', '.join(beside[:6])} would be loaded or run beside it, and the checks do not read it"] if beside else [], "only server.ts")
    pinned = files.get("package.json", "").replace("\r\n", "\n") == package_json(defn.name) and is_our_lock(files.get("package-lock.json", ""), defn.name)
    row("package.json and package-lock.json are exactly the pinned ones", [] if pinned else ["they are not the files this builder writes (exact versions, no scripts, the pinned lockfile)"], "pinned")
    leaks = sorted({f"{path}: {label}" for path, text in files.items() for label, pattern in SECRET_PATTERNS if pattern.search(text)})
    row("no key or token in any file", [f"{'; '.join(leaks)}. Never type a key: name the environment variable it is read from"] if leaks else [], "none found")
    check_cases_and_words(defn, spec, files, row)
    return out


def _render(defn: NodeDefinition, spec: RequirementSpec) -> tuple[dict[str, str] | None, str]:
    """(files, why not). A name in the design that is not a name is refused here, before any of it is written as code."""
    try:
        return render_node_files(defn, spec), ""
    except NodeDesignError as exc:
        return None, str(exc)


def _score(defn: NodeDefinition, spec: RequirementSpec) -> tuple[int, int]:
    """(failed checks, warnings): smaller is better, and a failure outweighs any number of warnings."""
    files, _ = _render(defn, spec)
    if files is None:
        return (10_000, 0)
    checks = check_node(defn, spec, files)
    return (sum(c.status == FAILED for c in checks), sum(c.status == WARNING for c in checks))


def build_node_from_spec(
    spec: RequirementSpec, provider: LLMProvider, *, out_root: Path, force: bool = False, now: datetime | None = None,
    calls: int = 0, notes: list[str] | None = None, progress: Progress | None = None, runner: McpRunner | None = None,
) -> McpBuildResult:
    """Everything after the person approved the requirement. Costs one model call, or two when the first design had problems.
    `runner` starts the server in the sandbox (None: the real sandbox); a design that failed its checks is never started."""
    now = now or datetime.now(timezone.utc)
    say = progress or (lambda message: None)
    notes = list(notes or [])
    say("Designing the server from your approved requirement")
    draft, used = design_node(provider, spec)
    calls += used
    defn = assemble_node(draft, spec, provider, now)
    first_files, why = _render(defn, spec)
    problems = [f"design: {why}"] if first_files is None else _problems(check_node(defn, spec, first_files))
    if problems:
        say(f"The design has {len(problems)} problem(s); asking the model to fix them once")
        first = _score(defn, spec)
        draft, used = design_node(provider, spec, problems)
        calls += used
        second = assemble_node(draft, spec, provider, now)
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
    files, why = _render(defn, spec)
    if files is None:
        raise BuildError(f"The design cannot be written as a server: {why}.")
    static = validate_files({path: text.encode("utf-8") for path, text in files.items()}, folder=defn.name, kind="mcp-node")
    static_and_design = [*check_node(defn, spec, files), *static]
    if any(c.status == FAILED for c in static_and_design):
        protocol = [CheckResult(PROTOCOL_ROW, NOT_RUN, "a check failed, so the server was not started")]
        complete, reason = False, "a check failed, so read it before keeping this server."
    else:
        say("Starting the server in the sandbox and calling its test cases over the MCP protocol")
        run = run_node_protocol_tests(defn, files, runner)
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
    return McpBuildResult(status, out_dir, defn, spec, checks, sorted(files), calls, notes, "" if failed or status == "ok" else reason)  # type: ignore[arg-type]


__all__ = ["HEADER_MODULES", "OFFERED", "build_node_from_spec", "check_node"]
