"""Run a generated MCP server over the real protocol, and only inside the sandbox.

The server is model-written code, so it never runs on this machine: a fixed harness (below, written by us, never by a model) is
copied next to it and both run in the locked container (no network, a read-only disk, no extra privileges) from an image that has
the pinned SDK. The harness starts the server the way Claude Code would (over stdio), asks it for its tools, calls every test case
and prints one line of JSON. Code, not a model, compares that with what the design said: the tools listed, and for each case
whether the reply contains, equals or refuses what the case expects. A check is "passed" only if it ran; no sandbox, no image or a
tool that needs the network is reported as "not run", never as passed.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from ..results import FAILED, NOT_RUN, PASSED, CheckResult
from ..sandbox import DockerRunner, ImageNotPulled, Limits, RunResult, SandboxStatus, SandboxUnavailable, probe_sandbox
from ..sandbox.images import MCP_IMAGE
from ..validate.mcp import analyze_server
from .mcp import McpCase, McpDefinition

HARNESS_FILE = "_skillforge_harness.py"
CASES_FILE = "_skillforge_cases.json"
PROTOCOL_ROW = "the server was started and its tools called over the MCP protocol in the sandbox"
TOOLS_ROW = "the server lists exactly the designed tools"
BUILD_COMMAND = "python -m skillforge sandbox-build-mcp"
SNIPPET = 400
McpRunner = Callable[[Path], RunResult]  # given the folder to mount, run the harness in the container

# The one program that talks to a server. It uses only names that were checked against a real install of the SDK (docs/mcp-builder.md).
# The server gets only the environment variable NAMES the design declared, with a dummy value: no real secret is ever in the box.
HARNESS = '''\
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = os.path.dirname(os.path.abspath(__file__))


def text_of(result):
    return "\\n".join(getattr(part, "text", "") for part in result.content)


async def main():
    with open(os.path.join(ROOT, "%(cases)s"), encoding="utf-8") as handle:
        plan = json.load(handle)
    out = {"started": False, "tools": [], "results": [], "problem": ""}
    env = {name: "skillforge-test-value" for name in plan["env"]}
    params = StdioServerParameters(command=sys.executable, args=[os.path.join(ROOT, "server.py")], env=env or None)
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), 30)
                out["started"] = True
                listed = await asyncio.wait_for(session.list_tools(), 30)
                out["tools"] = sorted(tool.name for tool in listed.tools)
                for case in plan["cases"]:
                    row = {"name": case["name"], "is_error": None, "text": "", "problem": ""}
                    try:
                        reply = await asyncio.wait_for(session.call_tool(case["tool"], case["arguments"]), 20)
                        row["is_error"] = bool(reply.is_error)
                        row["text"] = text_of(reply)[:2000]
                    except Exception as exc:
                        row["problem"] = (type(exc).__name__ + ": " + str(exc))[:300]
                    out["results"].append(row)
    except BaseException as exc:
        out["problem"] = (type(exc).__name__ + ": " + str(exc))[:500]
    print(json.dumps(out))


asyncio.run(main())
''' % {"cases": CASES_FILE}


@dataclass
class ProtocolReport:
    checks: list[CheckResult] = field(default_factory=list)
    started: bool = False  # the server really started and answered
    complete: bool = False  # it started, listed the right tools, and every case ran and passed
    reason: str = ""  # why a build is not "ok" because of this run, or ""


class SandboxMcpRunner:
    """Runs the harness in the locked container. Probes the engine once, never falls back to this machine."""

    def __init__(
        self, limits: Limits | None = None, probe: Callable[[], SandboxStatus] = probe_sandbox, execute: Callable = subprocess.run,
    ) -> None:
        self.limits = limits or Limits(timeout_s=90, memory="512m", pids=128)
        self._probe = probe
        self._execute = execute
        self._status: SandboxStatus | None = None

    def probe(self) -> SandboxStatus:
        if self._status is None:
            self._status = self._probe()
        return self._status

    def __call__(self, folder: Path) -> RunResult:
        status = self.probe()
        box = DockerRunner(MCP_IMAGE, self.limits, probe=lambda: status, runner=self._execute)
        result = box.run(folder, ["python", f"/skill/{HARNESS_FILE}"])
        if result.exit_code == 125 and "Unable to find image" in result.stderr:
            raise ImageNotPulled(MCP_IMAGE, BUILD_COMMAND)
        return result


def _clip(text: str, limit: int = SNIPPET) -> str:
    one = " ".join(text.split())
    return one if len(one) <= limit else "..." + one[-limit:]  # the end of the output is where errors are


def tools_needing_network(source: str) -> set[str]:
    """The tools whose own code can reach the network, by syntax. Their cases cannot run in a box with no network."""
    try:
        facts = analyze_server(source)
    except (SyntaxError, ValueError, RecursionError):
        return set()
    return {tool.name for tool in facts.tools if "network" in tool.capabilities}


def grade_case(case: McpCase, row: Mapping) -> CheckResult:
    """Code decides: a reply passes only if it is exactly what the case expects. The reply is data, never evaluated."""
    name = f"MCP test: {case.tool} / {case.name}"
    if row.get("problem"):
        return CheckResult(name, FAILED, f"the call did not complete: {row['problem']}")
    is_error, text = bool(row.get("is_error")), str(row.get("text", ""))
    if case.expect == "error":
        ok, wanted = is_error, "the tool to refuse"
    elif case.expect == "equals":
        ok, wanted = (not is_error and text == case.expected_text), f"exactly '{case.expected_text}'"
    else:
        ok, wanted = (not is_error and case.expected_text in text), f"a reply containing '{case.expected_text}'"
    if ok:
        return CheckResult(name, PASSED, f"answered over the protocol as expected ({case.expect})")
    got = f"an error ({_clip(text) or 'no text'})" if is_error else f"'{_clip(text) or '(empty)'}'"
    return CheckResult(name, FAILED, f"expected {wanted}, got {got}")


def run_protocol_tests(defn: McpDefinition, files: Mapping[str, str], runner: McpRunner | None = None) -> ProtocolReport:
    """Start the server in the sandbox and call its cases. Nothing runs without a sandbox and the image."""
    runner = runner or SandboxMcpRunner()
    needs_network = tools_needing_network(files.get("server.py", ""))
    runnable = [c for c in defn.cases if c.tool not in needs_network]
    skipped = [c for c in defn.cases if c.tool in needs_network]
    plan = {
        "env": list(defn.env_vars),
        "cases": [
            {"name": c.name, "tool": c.tool, "arguments": _arguments(c), "expect": c.expect, "expected_text": c.expected_text}
            for c in runnable
        ],
    }
    with tempfile.TemporaryDirectory(prefix="skillforge-mcp-", ignore_cleanup_errors=True) as tmp:
        folder = Path(tmp)
        for rel, text in files.items():
            target = folder / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8", newline="\n")
        (folder / HARNESS_FILE).write_text(HARNESS, encoding="utf-8", newline="\n")
        (folder / CASES_FILE).write_text(json.dumps(plan), encoding="utf-8", newline="\n")
        try:
            raw = runner(folder)
        except SandboxUnavailable as exc:  # includes ImageNotPulled: both say what to do, and neither counts as passed
            return ProtocolReport([CheckResult(PROTOCOL_ROW, NOT_RUN, str(exc))], reason=str(exc))

    if raw.timed_out:
        why = f"it ran out of time. stderr: {_clip(raw.stderr) or '(empty)'}"
        return ProtocolReport([CheckResult(PROTOCOL_ROW, FAILED, why)], reason=why)
    if raw.truncated:
        # The server runs beside the harness and can write to the same output. If the output was cut, the real answer (written last) may be
        # exactly the part that was lost, and what is left may be someone else's.
        why = "the output was cut: far more was written than the harness would write, and the part that was lost may have been its real answer"
        return ProtocolReport([CheckResult(PROTOCOL_ROW, FAILED, why)], reason=why)
    answers: list[dict] = []
    for line in raw.stdout.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and "started" in value and "results" in value:
            answers.append(value)
    if len(answers) > 1:  # the harness writes one answer: a second one was written by something else
        why = f"the harness's answer appears more than once on the output ({len(answers)} times): the server may have written one of them"
        return ProtocolReport([CheckResult(PROTOCOL_ROW, FAILED, why)], reason=why)
    if not answers:
        why = f"the test harness did not answer (exit code {raw.exit_code}). stdout: {_clip(raw.stdout) or '(empty)'} stderr: {_clip(raw.stderr) or '(empty)'}"
        return ProtocolReport([CheckResult(PROTOCOL_ROW, FAILED, why)], reason=why)
    data = answers[0]

    checks: list[CheckResult] = []
    started = bool(data.get("started"))
    problem = str(data.get("problem") or "")
    if not started:
        checks.append(CheckResult(PROTOCOL_ROW, FAILED, f"the server did not start: {problem or 'no reason given'}. stderr: {_clip(raw.stderr) or '(empty)'}"))
        return ProtocolReport(checks, started=False, reason="the server did not start")
    rows = [r for r in data.get("results", []) if isinstance(r, dict)]
    if problem:
        checks.append(CheckResult(PROTOCOL_ROW, FAILED, f"the server stopped answering: {problem}. stderr: {_clip(raw.stderr) or '(empty)'}"))
    else:
        checks.append(CheckResult(PROTOCOL_ROW, PASSED, f"started, listed {len(data.get('tools', []))} tool(s), answered {len(rows)} case(s)"))
    listed, designed = sorted(map(str, data.get("tools", []))), sorted(t.name for t in defn.tools)
    if listed == designed:
        checks.append(CheckResult(TOOLS_ROW, PASSED, ", ".join(listed)))
    else:
        checks.append(CheckResult(TOOLS_ROW, FAILED, f"the server lists {listed}, the design has {designed} (missing: {sorted(set(designed) - set(listed))}, extra: {sorted(set(listed) - set(designed))})"))
    for index, case in enumerate(runnable):
        checks.append(grade_case(case, rows[index]) if index < len(rows) else CheckResult(f"MCP test: {case.tool} / {case.name}", FAILED, "the server never answered this case"))
    if skipped:
        names = sorted({c.tool for c in skipped})
        checks.append(CheckResult(
            "MCP test cases that need the network", NOT_RUN,
            f"{len(skipped)} case(s) call {', '.join(names)}, which can reach the network; the sandbox has no network, so they were not run",
        ))
    failed = any(c.status == FAILED for c in checks)
    complete = not failed and not problem and not skipped
    reason = "" if complete or failed else (checks[-1].detail if skipped else "")
    return ProtocolReport(checks, started=True, complete=complete, reason=reason)


def _arguments(case: McpCase) -> dict:
    try:
        value = json.loads(case.arguments_json)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}
