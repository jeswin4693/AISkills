"""Render every file from the SkillDefinition. Same SDM in, same bytes out. No model is involved."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .models import IOField, RequirementSpec, SkillDefinition
from .scriptfiles import script_files, script_views

TEMPLATES = Path(__file__).parent / "templates"
MAX_NAME = 40
TYPE_MAP = {
    "string": "string", "integer": "integer", "number": "number", "boolean": "boolean",
    "list": "array", "object": "object",
}


def oneline(value: Any) -> str:
    return " ".join(str(value).split())


_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES)),
    undefined=StrictUndefined,
    keep_trailing_newline=True,
    trim_blocks=True,
    lstrip_blocks=True,
    autoescape=False,
)
_env.filters["oneline"] = oneline
_env.filters["cell"] = lambda v: oneline(v).replace("|", "\\|")  # safe inside a Markdown table cell


def slugify(text: str, limit: int = MAX_NAME) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:limit].strip("-")
    return slug or "skill"


def schema_for(title: str, fields: list[IOField]) -> dict[str, Any]:
    """A JSON Schema built from simple field records, so it is valid by construction."""
    props: dict[str, Any] = {}
    for f in fields:
        prop: dict[str, Any] = {"type": TYPE_MAP[f.type], "description": oneline(f.description)}
        if prop["type"] == "array":
            prop["items"] = {}
        props[f.name] = prop
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": title,
        "type": "object",
        "properties": props,
        "required": [f.name for f in fields if f.required],
        "additionalProperties": False,
    }


def frontmatter(sdm: SkillDefinition) -> str:
    body = yaml.safe_dump(
        {"name": sdm.name, "description": oneline(sdm.description)},
        sort_keys=False, allow_unicode=True, default_flow_style=False, width=100_000,
    )
    return f"---\n{body}---\n"


def _json(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def render_files(sdm: SkillDefinition, spec: RequirementSpec) -> dict[str, str]:
    """Relative path -> file text. `report.md` is added later, once every check has run."""
    ctx = {
        "sdm": sdm, "spec": spec, "frontmatter": frontmatter(sdm), "title": sdm.name.replace("-", " ").title(),
        "scripts": script_views(sdm.scripts),
    }
    files = {
        "SKILL.md": _env.get_template("SKILL.md.j2").render(**ctx),
        "README.md": _env.get_template("README.md.j2").render(**ctx),
        "schemas/input.schema.json": _json(schema_for(f"{sdm.name} input", sdm.inputs)),
        "schemas/output.schema.json": _json(schema_for(f"{sdm.name} output", sdm.outputs)),
        "tests/cases.json": _json([t.model_dump() for t in sdm.tests]),
        "skill.sdm.json": _json(sdm.model_dump()),
        "spec.json": _json(spec.model_dump()),
    }
    files.update(script_files(sdm.scripts, sdm.script_cases))  # scripts, fixtures and tests/script_cases.json
    return files


def render_report(sdm: SkillDefinition, checks: list, notes: list[str], draft_reason: str = "") -> str:
    ran = [c for c in checks if c.status != "not run"]
    failed = [c for c in ran if c.status == "failed"]
    warned = [c for c in ran if c.status == "warning"]
    skipped = [c for c in checks if c.status == "not run"]
    return _env.get_template("report.md.j2").render(
        sdm=sdm, ran=ran, skipped=skipped, passed=len(ran) - len(failed) - len(warned), failed=len(failed),
        warned=len(warned), notes=notes, title=sdm.name.replace("-", " ").title(), draft_reason=draft_reason,
    )


def write_files(out_dir: Path, files: dict[str, str], overwrite: bool) -> None:
    out_dir = out_dir.resolve()
    if out_dir.exists() and any(out_dir.iterdir()) and not overwrite:
        raise FileExistsError(f"{out_dir} already exists. Use --force to replace it, or choose another --out.")
    for rel, text in files.items():
        target = (out_dir / rel).resolve()
        if out_dir not in target.parents:  # file names are fixed by this program, but never trust a path
            raise ValueError(f"Refusing to write outside the output folder: {rel}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
