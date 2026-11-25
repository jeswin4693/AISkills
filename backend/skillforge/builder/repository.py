"""A repository in the web builder: checking the folder a person names, reading it into facts, and recording evidence for a build that
started from it.

Everything here reads the folder (the graph) and never runs anything in it. A folder's path is private to this computer: the pages
are shown its name only, and a build keeps the path only to record evidence when it ends.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..evidence import EVIDENCE_FILE, MAX_REFS, collect, evidence_bytes, fit, safe
from ..graph import query
from ..graph.architecture import architecture
from ..graph.build import build_graph
from . import github
from .errors import BadRequest, BuilderError

EVIDENCE_KINDS = ("skill", "agent")  # text about code: an MCP server or a plugin makes no claims about a repository
MAX_NODE_TEXT = 400
BACKSLASH = chr(92)  # written this way so no tool can change it
NETWORK_PREFIXES = (BACKSLASH * 2, "//")  # a UNC path: opening it would reach out to another machine


def read_failure(exc: Exception) -> str:
    """Why a folder could not be read, in words that never repeat a path (an OSError's own text does)."""
    why = getattr(exc, "strerror", None) if isinstance(exc, OSError) else None
    return f"The repository could not be read ({type(exc).__name__}{': ' + why if why else ''})."


@dataclass(frozen=True)
class Repo:
    """A repository ready to read: the folder, and (for a GitHub link) the link and the snapshot it was downloaded into."""

    folder: Path
    link: github.GithubLink | None = None
    snapshot: github.Snapshot | None = None


def check_repo(path: object, *, fresh: bool = False, max_age: float | None = github.SNAPSHOT_TTL, stamp: str | None = None) -> Path:
    """The folder a person named, or BadRequest saying what to fix. A GitHub link is downloaded into a snapshot folder first (see
    builder/github.py). Nothing else is read yet, and no message repeats the path."""
    return resolve_repo(path, fresh=fresh, max_age=max_age, stamp=stamp).folder


def resolve_repo(path: object, *, fresh: bool = False, max_age: float | None = github.SNAPSHOT_TTL, stamp: str | None = None) -> Repo:
    """`check_repo`, keeping what a link was and where it was downloaded to. `fresh` downloads again, `max_age` (None: any age) is how old a
    snapshot may be and still be reused, `stamp` asks for one particular copy of a link (see `github.open_snapshot`; a folder has none)."""
    link = github.parse_link(path)  # BadRequest for a link that is not a public GitHub repository link
    if link is not None:
        snapshot = github.open_snapshot(link, fresh=fresh, max_age=max_age, stamp=stamp)
        return Repo(snapshot.path, link, snapshot)
    return Repo(_check_folder(path))


def _check_folder(path: object) -> Path:
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


def source_of(repo: Repo) -> str:
    """What is stored to find this repository again: the link for a GitHub repository, the folder's path otherwise. Never a path inside
    the snapshot store."""
    return repo.link.url if repo.link is not None else str(repo.folder)


def display_name(source: str) -> str:
    """What a page shows for a stored source: `owner/repo` for a link, the folder's name otherwise. Never a path."""
    link = github.parse_link(source) if github.looks_like_link(source) else None
    return link.name if link is not None else folder_name(Path(source))


def clean_focus(focus: object) -> str | None:
    text = focus.strip() if isinstance(focus, str) else ""
    return text or None


def analyze_repo(path: object, focus: object = None) -> dict[str, Any]:
    """What the graph knows about a repository, as the Repository page shows it. No model, nothing is run."""
    repo, focus_text = resolve_repo(path), clean_focus(focus)
    folder = repo.folder
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
        "name": display_name(source_of(repo)), "source": source_view(repo), "focus": focus_text, "stats": stats, "notes": notes,
        "hotspots": {"core_symbols": hot["core_symbols"][:10], "risky_files": hot["risky_files"][:10], "note": hot.get("note", "")},
        "dead_code": {"internal": len(dead["internal"]), "exported": len(dead["exported"]), "note": dead.get("note", "")},
        "architecture": architecture(g),  # folders as boxes, proven imports as arrows; repository-relative names only
    }


def source_view(repo: Repo) -> dict[str, Any]:
    """Where the repository came from, for the page: a folder says only that. A link says what was downloaded and what was left out."""
    snap, link = repo.snapshot, repo.link
    if snap is None or link is None:
        return {"kind": "folder"}
    return {
        "kind": "github", "owner": link.owner, "repo": link.repo, "ref": link.ref, "url": link.url, "fetched_at": snap.fetched_at,
        "files": snap.files, "bytes": snap.bytes, "skipped": snap.skipped, "reused": snap.reused,
        "docs": snap.docs,  # README and doc files kept next to the source (None: a copy made before they were kept)
    }


def check_seed(kind: str, repo: object, focus: object, nodes: object, snapshot: object = None) -> dict[str, Any] | None:
    """The seed a build session keeps, or None when the build does not start from a repository. BadRequest when it is half given.

    `snapshot` is the copy of a GitHub repository an idea was made from (a run records it). The seed keeps the copy it ended up with, and
    says so (`newer`) when that is not the one asked for, so the evidence can be recorded from the same code the idea saw, or say it was not."""
    asked = [n for n in nodes if isinstance(n, str) and n.strip()] if isinstance(nodes, list) else []
    if not (isinstance(repo, str) and repo.strip()) and not asked:
        return None
    if not (isinstance(repo, str) and repo.strip()):
        raise BadRequest("Evidence needs the repository the places are in: give repo.")
    wanted = snapshot if isinstance(snapshot, str) and snapshot else None
    found = resolve_repo(repo, stamp=wanted, max_age=None if wanted else github.SNAPSHOT_TTL)
    if kind not in EVIDENCE_KINDS:
        raise BadRequest("Only skills and agents can cite a repository's code.")
    if not asked:
        raise BadRequest("Say which places of the repository the idea cites (evidence_nodes).")
    if len(asked) > MAX_REFS or any(len(n) > MAX_NODE_TEXT for n in asked):
        raise BadRequest(f"A skill can cite at most {MAX_REFS} places, each named in at most {MAX_NODE_TEXT} characters.")
    seed: dict[str, Any] = {"repo": source_of(found), "focus": clean_focus(focus), "nodes": list(dict.fromkeys(n.strip() for n in asked))}
    if found.snapshot is not None:
        seed["snapshot"] = found.snapshot.stamp
        if wanted and found.snapshot.stamp != wanted:
            seed["newer"] = True
    return seed


def seed_view(seed: dict[str, Any] | None) -> dict[str, Any] | None:
    """What a session shows of its seed: the folder's name, never its path."""
    if not seed:
        return None
    return {"repo": display_name(seed["repo"]), "focus": seed.get("focus"), "places": len(seed["nodes"])}


def record_evidence(seed: dict[str, Any], folder: Path, summary: dict[str, Any], notes: list[str]) -> None:
    """When a build ends: write evidence.json into the built folder from the graph as it is now, and say so in the result. A repository
    that cannot be read now, or none of whose places exist, leaves the build as it is and adds a note: the skill itself is fine."""
    try:
        # the copy the idea was made from, however old (a build can last hours, and its places must be looked up in the same code)
        wanted = seed.get("snapshot")
        found = resolve_repo(seed["repo"], max_age=None, stamp=wanted)
        g = build_graph(found.folder, focus=seed.get("focus"), with_history=False)
    except (OSError, ValueError, BuilderError):
        notes.append("Evidence was not recorded: the repository could not be read when the build finished (it may have been moved or deleted).")
        return
    if found.snapshot is not None and (seed.get("newer") or (wanted and found.snapshot.stamp != wanted)):
        notes.append("The copy of the repository this idea was made from is no longer kept, so the evidence was recorded from a newer copy: the code may differ.")
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
