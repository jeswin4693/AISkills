"""A repository in the web builder: checking the folder a person names, reading it into facts, and recording evidence for a build that
started from it.

Everything here reads the folder (the graph) and never runs anything in it. A folder's path is private to this computer: the pages
are shown its name only, and a build keeps the path only to record evidence when it ends.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..evidence import EVIDENCE_FILE, MAX_REFS, collect, evidence_bytes, fit, safe
from ..graph import query
from ..graph.build import build_graph
from .errors import BadRequest

EVIDENCE_KINDS = ("skill", "agent")  # text about code: an MCP server or a plugin makes no claims about a repository
MAX_NODE_TEXT = 400
BACKSLASH = chr(92)  # written this way so no tool can change it
NETWORK_PREFIXES = (BACKSLASH * 2, "//")  # a UNC path: opening it would reach out to another machine


def read_failure(exc: Exception) -> str:
    """Why a folder could not be read, in words that never repeat a path (an OSError's own text does)."""
    why = getattr(exc, "strerror", None) if isinstance(exc, OSError) else None
    return f"The repository could not be read ({type(exc).__name__}{': ' + why if why else ''})."


def check_repo(path: object) -> Path:
    """The folder a person named, or BadRequest saying what to fix. Nothing is read yet, and no message repeats the path."""
    text = path.strip() if isinstance(path, str) else ""
    if text.startswith(NETWORK_PREFIXES):
        raise BadRequest("Network paths are not read: use a folder on this computer (map the share to a drive letter first).")
    try:
        folder = Path(text).resolve() if text and Path(text).is_absolute() else None  # resolved, so `repo\..` is named by the folder it is
        if folder is None:
            raise BadRequest("Give the repository as an absolute folder path on this computer, such as C:" + BACKSLASH + "code" + BACKSLASH + "myrepo.")
        if not folder.is_dir():
            raise BadRequest("Not a directory on this computer: check the path.")
    except (OSError, ValueError) as exc:
        raise BadRequest("Not a directory on this computer: check the path.") from exc
    return folder


def folder_name(folder: Path) -> str:
    return folder.name or "repository"


def clean_focus(focus: object) -> str | None:
    text = focus.strip() if isinstance(focus, str) else ""
    return text or None


def analyze_repo(path: object, focus: object = None) -> dict[str, Any]:
    """What the graph knows about a repository, as the Repository page shows it. No model, nothing is run."""
    folder, focus_text = check_repo(path), clean_focus(focus)
    try:
        g = build_graph(folder, focus=focus_text)
    except (OSError, ValueError) as exc:
        raise BadRequest(read_failure(exc)) from exc
    stats = query.stats(g)
    stats.pop("root", None)  # a person's own path is not sent back
    notes = stats.pop("notes", [])
    hot = query.hotspots(g, 10)
    dead = query.dead_candidates(g)
    return {
        "name": folder_name(folder), "focus": focus_text, "stats": stats, "notes": notes,
        "hotspots": {"core_symbols": hot["core_symbols"][:10], "risky_files": hot["risky_files"][:10], "note": hot.get("note", "")},
        "dead_code": {"internal": len(dead["internal"]), "exported": len(dead["exported"]), "note": dead.get("note", "")},
    }


def check_seed(kind: str, repo: object, focus: object, nodes: object) -> dict[str, Any] | None:
    """The seed a build session keeps, or None when the build does not start from a repository. BadRequest when it is half given."""
    asked = [n for n in nodes if isinstance(n, str) and n.strip()] if isinstance(nodes, list) else []
    if not (isinstance(repo, str) and repo.strip()) and not asked:
        return None
    if not (isinstance(repo, str) and repo.strip()):
        raise BadRequest("Evidence needs the repository the places are in: give repo.")
    folder = check_repo(repo)
    if kind not in EVIDENCE_KINDS:
        raise BadRequest("Only skills and agents can cite a repository's code.")
    if not asked:
        raise BadRequest("Say which places of the repository the idea cites (evidence_nodes).")
    if len(asked) > MAX_REFS or any(len(n) > MAX_NODE_TEXT for n in asked):
        raise BadRequest(f"A skill can cite at most {MAX_REFS} places, each named in at most {MAX_NODE_TEXT} characters.")
    return {"repo": str(folder), "focus": clean_focus(focus), "nodes": list(dict.fromkeys(n.strip() for n in asked))}


def seed_view(seed: dict[str, Any] | None) -> dict[str, Any] | None:
    """What a session shows of its seed: the folder's name, never its path."""
    if not seed:
        return None
    return {"repo": folder_name(Path(seed["repo"])), "focus": seed.get("focus"), "places": len(seed["nodes"])}


def record_evidence(seed: dict[str, Any], folder: Path, summary: dict[str, Any], notes: list[str]) -> None:
    """When a build ends: write evidence.json into the built folder from the graph as it is now, and say so in the result. A repository
    that cannot be read now, or none of whose places exist, leaves the build as it is and adds a note: the skill itself is fine."""
    repo = Path(seed["repo"])
    try:
        g = build_graph(repo, focus=seed.get("focus"), with_history=False)
    except (OSError, ValueError):
        notes.append("Evidence was not recorded: the repository could not be read when the build finished (it may have been moved or deleted).")
        return
    got = collect(g, seed["nodes"], focus=seed.get("focus"))
    ev, too_big = fit(got.evidence)
    if not ev.refs:
        notes.append("Evidence was not recorded: none of the places the idea cited is in the repository now.")
        return
    (folder / EVIDENCE_FILE).write_bytes(evidence_bytes(ev))
    summary["files"] = sorted({*summary.get("files", []), EVIDENCE_FILE})
    summary["evidence"] = {"repo": ev.repo, "places": len(ev.refs), "skipped": [safe(text) for text, _ in got.skipped]}
    if too_big:
        notes.append(f"Evidence records only the first {len(ev.refs)} places: the file would have been too large to read back ({too_big} left out).")
