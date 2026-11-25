"""A skill's test cases, read for editing and written back as a new version: the library's side of the Testing Lab's editor.

Tests that a person writes are the stronger answer to the Lab's main limit (the model that wrote a skill also wrote its tests). A save never
edits a stored version: it makes the next one through the library's checked import, so the static checks run, a refusal leaves the library
untouched, older versions stay, and the risk diff and history work as for any other change.

Two copies of the tests exist in a built skill: `tests/cases.json` (what the Lab and the harness read) and the `tests` list inside the definition
file `skill.sdm.json` (what a rebuild renders from). A save writes both, so a later rebuild cannot bring the old tests back. If the definition
cannot be read the save stops, rather than leave two copies that disagree.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime

from ..build.models import Assertion, SkillTest
from ..evaluate import assertion_problem, load_files, tests_of
from ..kinds import get_kind
from ..library import Conflict, ImportReport, Library, LibraryError, SkillSource, import_source

CASES_FILE = "tests/cases.json"
DEFINITION_FILE = "skill.sdm.json"
SOURCE_KIND = "tests"
SOURCE_LABEL = "edited in the Testing Lab"

MAX_CASES = 30  # stored; a run asks the model about the first 12 (evaluate.MAX_CASES)
MAX_CHECKS = 3
MAX_NAME = 80
MAX_MESSAGE = 4000
MAX_VALUE = 500
MAX_WHY = 200
MAX_COVERS = 100  # the criteria a case cites are not edited here, only kept: a limit a built skill could already exceed would make it impossible to save
MAX_COVER = 120
LIMITS = {
    "max_cases": MAX_CASES, "max_checks": MAX_CHECKS, "max_name": MAX_NAME, "max_message": MAX_MESSAGE, "max_value": MAX_VALUE, "max_why": MAX_WHY,
    "max_covers": MAX_COVERS, "max_cover": MAX_COVER,
}


@dataclass
class CaseDraft:
    """One test case as a person writes it: a name, a kind, the message to send, and the checks the reply must pass."""

    name: str
    kind: str
    message: str
    checks: list[Assertion] = field(default_factory=list)
    covers: list[str] = field(default_factory=list)


def _json(obj: object) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"  # exactly how the builder writes its files


def describe_check(a: Assertion) -> str:
    """A check as a person would say it (the same words the page uses)."""
    value = a.value.strip()
    return {
        "contains": f'contains "{value}"', "not_contains": f'does not contain "{value}"', "starts_with": f'starts with "{value}"',
        "regex": f"matches the pattern {value}", "max_chars": f"is at most {value} characters", "max_lines": f"is at most {value} lines",
        "first_line_max_chars": f"has a first line of at most {value} characters",
    }.get(a.kind, f"{a.kind} {value}")


def view_cases(library: Library, name: str, version: int | None = None) -> dict:
    """Every case of a version, the ones that cannot be run too (so they can be fixed), and what the editor needs to know about the skill."""
    v, files = library.read(name, version)  # checks every file against the manifest first
    tests, unreadable = tests_of(files)
    try:
        needs_tools = load_files(files).needs_tools
    except ValueError as exc:
        raise LibraryError(f"{name} {v.tag}: {exc}") from exc
    return {
        "name": v.name, "version": v.version, "tag": v.tag, "content_hash": v.content_hash, "latest": library.versions(name)[-1].version == v.version,
        "needs_tools": needs_tools, "unreadable": unreadable, "limits": LIMITS,
        "cases": [
            {
                "name": t.name, "kind": t.kind, "message": t.run_input, "covers": list(t.covers), "runnable": bool(t.run_input.strip() and t.assertions),
                "checks": [{"kind": a.kind, "value": a.value, "why": a.why} for a in t.assertions],
            }
            for t in tests
        ],
    }


def problems_of(drafts: list[CaseDraft]) -> list[str]:
    """Everything that stops these cases from being run, in plain words and naming the case, so one save can fix them all."""
    if not drafts:
        return ["Add at least one case, or leave the skill as it is."]
    out: list[str] = []
    seen: dict[str, int] = {}
    for i, d in enumerate(drafts, 1):
        name = d.name.strip()
        issues: list[str] = []
        if not name:
            issues.append("it needs a name")
        elif name.casefold() in seen:
            issues.append(f"its name is used twice (Case {seen[name.casefold()]} has it too)")
        else:
            seen[name.casefold()] = i
        if not d.message.strip():
            issues.append("it needs a message to send")
        if not d.checks:
            issues.append("it needs at least one check the reply must pass")
        issues += [p for a in d.checks if (p := assertion_problem(a))]
        if issues:
            out.append(f"Case {i}" + (f" ('{name[:40]}')" if name else "") + ": " + "; ".join(issues) + ".")
    return out


def _same_checks(a: list[Assertion], b: list[Assertion]) -> bool:
    key = lambda xs: [(x.kind, x.value.strip(), x.why.strip()) for x in xs]  # noqa: E731
    return key(a) == key(b)


def build_tests(drafts: list[CaseDraft], base: list[SkillTest]) -> list[SkillTest]:
    """The cases as the harness reads them. A case whose message and checks did not change keeps the descriptions it had (they were written with
    it); one that changed, or is new, gets descriptions worked out from what the person wrote, never left stale."""
    old = {t.name.strip().casefold(): t for t in base}
    out: list[SkillTest] = []
    for d in drafts:
        name, message = d.name.strip(), d.message.strip()
        checks = [Assertion(kind=a.kind, value=a.value.strip(), why=a.why.strip()) for a in d.checks]  # type: ignore[arg-type]
        before = old.get(name.casefold())
        if before is not None and before.run_input.strip() == message and _same_checks(before.assertions, checks):
            described = (before.input_description, before.expected_result)
        else:
            described = (message[:300], "The reply " + ", and ".join(describe_check(a) for a in checks))
        out.append(SkillTest(
            name=name, kind=d.kind, input_description=described[0], expected_result=described[1],  # type: ignore[arg-type]
            covers=list(d.covers), run_input=message, assertions=checks,
        ))
    return out


def save_cases(
    library: Library, name: str, base_version: int, drafts: list[CaseDraft], note: str = "", now: datetime | None = None,
) -> ImportReport:
    """Keep these cases as the next version of the skill. `base_version` must be the latest: a person never silently drops a newer change."""
    latest = library.pick(name)  # NotFound when there is no such skill
    if base_version != latest.version:
        raise Conflict(
            f"The version you edited ({name} v{base_version}) is not the latest. The latest version is {latest.tag}: "
            f"open it and make the change there, so nothing newer is lost."
        )
    _, files = library.read(name, latest.version)
    own_name = get_kind(library.kind).name_of(files)
    if own_name != name:  # the import files a version under the name the skill gives itself: never let a save write somewhere else
        raise LibraryError(f"{name} v{latest.version} names itself '{own_name}', so a new version of it cannot be made from here. Nothing was saved.")
    issues = problems_of(drafts)
    if issues:
        raise LibraryError("\n".join(issues))
    tests = build_tests(drafts, tests_of(files)[0])
    payload = [t.model_dump() for t in tests]
    new_files = dict(files)
    new_files[CASES_FILE] = _json(payload).encode("utf-8")
    if DEFINITION_FILE in files:
        try:
            definition = json.loads(files[DEFINITION_FILE].decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            definition = None
        if not isinstance(definition, dict):
            raise LibraryError(
                f"{DEFINITION_FILE} cannot be read as a definition, so the new test cases cannot be kept in step with it. Fix or remove that file first; nothing was saved."
            )
        if "tests" in definition:  # only a definition that already holds its tests gets them updated: nothing is added to one that has none
            definition["tests"] = payload
            new_files[DEFINITION_FILE] = _json(definition).encode("utf-8")
    # The latest was looked at above, but the static checks inside the import take a moment: expect_latest makes the store itself refuse if another
    # version arrived in between (two saves from one version cannot both win, and a newer one is never overwritten).
    return import_source(SkillSource(new_files, [], SOURCE_KIND, SOURCE_LABEL, None), library, note=note, now=now, expect_latest=latest.version)
