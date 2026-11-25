"""Which text files explain a project, and reading them safely.

The same rule (`is_doc_path`) and the same order (`sort_key`) decide what a downloaded GitHub copy keeps and what is read from a folder, always counted
from the top of the repository, so a link and a folder give the guide the same documents. Nothing here uses a model and nothing is run. A file is read
only if it is a regular file inside the repository: a symbolic link, a binary and an enormous file are skipped, and every path in an answer is relative
to the repository.

A focus (the folder a person narrowed the graph to) never decides what is searched, only what comes first: documents inside it are read before the rest.
It is compared as text and never looked up on the disk, so it cannot lead anywhere outside the repository.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from ..graph.files import PACKAGE_NAMED, SKIP_DIRS

DOC_SUFFIXES = frozenset({".md", ".markdown", ".rst", ".txt", ".adoc"})
DOC_FOLDERS = frozenset({"docs", "doc", "documentation"})
TOP_NAMES = frozenset({"architecture", "claude", "agents"})  # next to README at the top of the repository
MAX_DEPTH = 3  # folders a README may sit below the repository; a docs folder must be among the first this many
MAX_DOC_DEPTH = 4  # folders a text file inside a docs folder may sit below the repository
# A file inside a docs folder whose name says it explains the structure comes before the other pages.
STRUCTURE_WORDS = (
    "architecture", "overview", "design", "concept", "how-it-works", "how_it_works", "structure", "introduction", "getting-started", "getting_started", "guide",
)

MAX_FILES = 12  # documents given to the model
MAX_FILE_CHARS = 24_000  # characters of one document given to the model (the rest is cut, and said)
MAX_TOTAL_CHARS = 60_000  # characters of all the documents together
MAX_READ_BYTES = 400_000  # a file larger than this is skipped, not cut
MAX_DIRS = 3_000  # folders looked into while searching a repository
MIN_ROOM = 500  # no point opening another document with less room than this


def _in_docs_folder(folders: Sequence[str]) -> bool:
    return any(f.lower() in DOC_FOLDERS for f in folders[:MAX_DEPTH])


def is_doc_path(parts: Sequence[str]) -> bool:
    """Whether a file, named by the folders and name below the repository (`["docs", "intro.md"]`), is a document about the project: a README in the
    first few folders, `ARCHITECTURE`, `CLAUDE.md` or `AGENTS.md` at the top, or a text file inside a `docs` folder (one of the first three folders)."""
    if not parts:
        return False
    *folders, name = parts
    path = PurePosixPath(name.lower())
    stem, suffix = path.stem, path.suffix
    text_like = suffix in DOC_SUFFIXES or suffix == ""
    if stem.startswith("readme") and text_like and len(folders) <= MAX_DEPTH:
        return True
    if not folders and stem in TOP_NAMES and text_like:
        return True
    return _in_docs_folder(folders) and suffix in DOC_SUFFIXES and len(folders) <= MAX_DOC_DEPTH


def doc_rank(parts: Sequence[str]) -> int:
    """Which documents come first when there is no room for all: the README, then what describes the structure, then the rest."""
    *folders, name = parts
    stem = PurePosixPath(name.lower()).stem
    if not folders and stem.startswith("readme"):
        return 0
    if not folders and stem == "architecture":
        return 1
    if not folders and stem in ("claude", "agents"):
        return 2
    if _in_docs_folder(folders) and (stem in ("readme", "index") or any(word in stem for word in STRUCTURE_WORDS)):
        return 3
    if stem.startswith("readme"):
        return 4
    return 5


def sort_key(parts: Sequence[str]) -> tuple[int, int, str, str]:
    """The order documents are kept in, by the unpacker (when a cap would cut some) and by the folder reader: rank, then the shallower, then by name
    (case does not decide, so `Docs/` and `docs/` order alike on every system)."""
    path = "/".join(parts)
    return doc_rank(parts), len(parts), path.lower(), path


@dataclass(frozen=True)
class DocFile:
    path: str  # relative to the repository, with "/"
    text: str
    truncated: bool = False

    @property
    def lines(self) -> int:
        return self.text.count("\n") + 1


@dataclass
class DocSet:
    files: list[DocFile] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=dict)

    def view(self) -> list[dict]:
        return [{"path": d.path, "lines": d.lines, "chars": len(d.text), "truncated": d.truncated} for d in self.files]


def shrink(docs: DocSet, share: float) -> DocSet:
    """The same documents, best first, in `share` of their text (0.5: about half). Used when a model says the request is too big for it: the first
    documents stay whole, the one that does not fit is cut (and says so), the rest are left out and counted. The room never goes below MIN_ROOM, so the
    first document is always kept (at least that much of it), and a later document that would get less than MIN_ROOM is dropped rather than cut to a
    stub. The input is not changed."""
    room = max(MIN_ROOM, int(sum(len(d.text) for d in docs.files) * share))
    out = DocSet(skipped=dict(docs.skipped))
    for d in docs.files:
        if len(d.text) <= room:
            out.files.append(d)
            room -= len(d.text)
        elif room >= MIN_ROOM:
            out.files.append(DocFile(d.path, d.text[:room], True))
            room = 0
        else:
            out.skipped["limit"] = out.skipped.get("limit", 0) + 1
    return out


def _search(root: Path, skipped: dict[str, int]) -> dict[str, Path]:
    """The document files of the repository: a bounded walk that never follows a link and never goes into a folder the graph ignores."""
    found: dict[str, Path] = {}
    seen = 0
    for here, dirs, names in os.walk(root, followlinks=False):
        seen += 1
        if seen > MAX_DIRS:
            skipped["walk_limit"] = skipped.get("walk_limit", 0) + 1
            break
        inside = Path(here).relative_to(root).parts
        dirs[:] = sorted(d for d in dirs if not (d in SKIP_DIRS and d not in PACKAGE_NAMED) and len(inside) < MAX_DOC_DEPTH)
        for name in sorted(names):
            if is_doc_path((*inside, name)):
                found["/".join((*inside, name))] = Path(here) / name
    return found


def _focus_prefix(focus: object) -> str:
    """The focus as the start of a repository-relative path ("src/app/"), or "" when it is empty or not a plain relative folder name."""
    if not isinstance(focus, str):
        return ""
    text = focus.strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    text = text.strip("/")
    if not text or ":" in text or any(p in ("", ".", "..") for p in text.split("/")):
        return ""
    return text.lower() + "/"


def read_docs(folder: Path, focus: str | None = None) -> DocSet:
    """The documents of a repository, best first, within the caps above. Documents inside `focus` come before the rest. Never raises for a file it
    cannot use: it is counted in `skipped`."""
    docs = DocSet()
    try:
        root = folder.resolve()
    except OSError:
        return docs
    found = _search(root, docs.skipped)
    inside_focus = _focus_prefix(focus)

    def skip(reason: str) -> None:
        docs.skipped[reason] = docs.skipped.get(reason, 0) + 1

    def order(rel: str) -> tuple:
        return (0 if inside_focus and rel.lower().startswith(inside_focus) else 1, *sort_key(rel.split("/")))

    total = 0
    for rel in sorted(found, key=order):
        if len(docs.files) >= MAX_FILES:
            skip("limit")
            continue
        room = MAX_TOTAL_CHARS - total
        if room < MIN_ROOM:
            skip("limit")
            continue
        path = found[rel]
        try:
            if path.is_symlink() or not path.is_file() or root not in path.resolve().parents:
                skip("not_a_file")
                continue
            with open(path, "rb") as handle:
                raw = handle.read(MAX_READ_BYTES + 1)
        except OSError:
            skip("unreadable")
            continue
        if len(raw) > MAX_READ_BYTES:
            skip("too_large")
            continue
        if b"\x00" in raw[:2000]:
            skip("binary")
            continue
        text = raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
        cap = min(MAX_FILE_CHARS, room)
        cut = len(text) > cap
        text = text[:cap] if cut else text
        if not text.strip():
            skip("empty")
            continue
        docs.files.append(DocFile(rel, text, cut))
        total += len(text)
    return docs
