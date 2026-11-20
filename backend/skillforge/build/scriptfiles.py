"""Where script files live and how they are run. Pure layout: no model, no sandbox, no checks.

Code decides every file name and command line. The model supplies a script's name (forced to a safe form here),
its language (one of a fixed list) and its source text, and never a path or a command.
"""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Sequence

from ..sandbox.images import RUNNERS
from .models import Fixture, Script, ScriptCase

EXTENSIONS = {
    "python": ".py", "javascript": ".js", "typescript": ".ts", "bash": ".sh", "ruby": ".rb", "php": ".php", "java": ".java",
}
SCRIPT_NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}\Z")
CASE_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*\Z")
# A fixture path: plain segments of letters, digits, '_', '.', '-'; a segment never starts with '.', so there is no '..'.
FIXTURE_PATH = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*(/[A-Za-z0-9_][A-Za-z0-9_.\-]*)*\Z")
FIXTURES = "{fixtures}"  # the placeholder a case writes for its own fixture folder (replaced as plain text, never evaluated)


def script_name(text: str) -> str:
    name = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    if not name:
        return "script"
    if not name[0].isalpha():
        name = "s_" + name
    return name[:40].rstrip("_")


def case_slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40].strip("-") or "case"


def script_path(script: Script) -> str:
    return f"scripts/{script_name(script.name)}{EXTENSIONS[script.language]}"


def run_command(script: Script) -> str:
    """How an agent runs the script from the skill folder, built from the sandbox's own interpreter table."""
    return " ".join((*RUNNERS[script.language][1], script_path(script)))


def case_dir(case: ScriptCase) -> str:
    return f"tests/fixtures/{case_slug(case.name)}"


def safe_fixtures(case: ScriptCase) -> list[Fixture]:
    """Only plain relative paths are ever turned into files. The structural check already fails the rest, and a
    draft is still rendered, so an unsafe path must never reach the disk (defence in depth)."""
    return [f for f in case.fixtures if len(f.path) <= 100 and FIXTURE_PATH.match(f.path)]


def expand(text: str, case: ScriptCase) -> str:
    return text.replace(FIXTURES, case_dir(case))


def script_views(scripts: Sequence[Script]) -> list[dict[str, str]]:
    return [
        {"path": script_path(s), "language": s.language, "purpose": s.purpose, "usage": s.usage, "run": run_command(s)}
        for s in scripts
    ]


def _case_record(case: ScriptCase, scripts: Sequence[Script]) -> dict[str, object]:
    by_name = {script_name(s.name): s for s in scripts}
    script = by_name.get(script_name(case.script))
    args = [expand(a, case) for a in case.args]
    command = (run_command(script) + (" " + shlex.join(args) if args else "")) if script else ""
    return {
        "name": case.name,
        "script": script_path(script) if script else case.script,
        "command": command,
        "stdin": expand(case.stdin, case),
        "fixtures": [f"{case_dir(case)}/{f.path}" for f in safe_fixtures(case)],
        "expect_exit_code": case.expect_exit_code,
        "stdout_contains": case.stdout_contains,
        "stderr_contains": case.stderr_contains,
    }


def script_files(scripts: Sequence[Script], cases: Sequence[ScriptCase]) -> dict[str, str]:
    """Relative path -> text for every script, every fixture and the case list. Same input, same bytes."""
    files: dict[str, str] = {}
    for s in scripts:
        files[script_path(s)] = s.code
    for c in cases:
        for f in safe_fixtures(c):
            files[f"{case_dir(c)}/{f.path}"] = f.text
    if cases:
        files["tests/script_cases.json"] = json.dumps(
            [_case_record(c, scripts) for c in cases], indent=2, ensure_ascii=False
        ) + "\n"
    return files


def normalize(scripts: Sequence[Script], cases: Sequence[ScriptCase]) -> tuple[list[Script], list[ScriptCase], list[str]]:
    """Make names safe and line endings plain. Returns the cleaned lists and what was changed, for the report."""
    notes: list[str] = []
    cleaned: list[Script] = []
    for s in scripts:
        name = script_name(s.name)
        if name != s.name:
            notes.append(f"The script name '{s.name}' was changed to '{name}' because it was not a safe name.")
        code = s.code.replace("\r\n", "\n").replace("\r", "\n")
        cleaned.append(s.model_copy(update={"name": name, "code": code if code.endswith("\n") else code + "\n"}))
    fixed_cases = [c.model_copy(update={"script": script_name(c.script)}) for c in cases]
    return cleaned, fixed_cases, notes
