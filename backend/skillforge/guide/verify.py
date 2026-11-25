"""The model proposes, code judges.

A part or a step survives only if its quote is found, word for word, in the documents that were given, and that is decided here by looking the
text up, never by asking a model. A quote must lie inside one paragraph (it cannot join a heading to the text under it, or one paragraph to the next)
and must start and end on whole words. A folder a part names is looked up in the graph. What the graph adds (how big a part is, which files and
functions to read first, whether one part really imports another) is computed from parsed code.

What this proves, and what it does not: a kept quote IS in the documents. Whether the quote even mentions the part is only flagged (`on_topic`), not
decided, and it does not prove the quote is right about it, that the documents are current, or that the model's words around the quote (summary, in,
out, "plain") are right. Those words are shown as the model's own.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from ..graph.architecture import reads_imports
from ..graph.files import is_test_support_path
from ..graph.model import RepoGraph
from .docs import DocSet
from .models import GuideDraft

MAX_PARTS = 16
MAX_JOURNEYS = 4
MAX_STEPS = 8  # steps of one journey
MIN_STEPS = 2  # a journey of one step is not a route
QUOTE_MIN_CHARS = 20  # after the marks are taken out
QUOTE_MIN_WORDS = 4
QUOTE_MAX_CHARS = 400
READ_FIRST_FILES = 4
READ_FIRST_FUNCTIONS = 3
EVIDENCE_PAIRS = 3  # file pairs a hop shows as an example of the imports behind it
# What the page shows of the model's own words: cut here, so a long answer cannot fill the page.
NAME, LINE, PLAIN, TITLE = 60, 200, 300, 80
# Words too common in a part's name or folder to show that a quote is about it.
COMMON_WORDS = frozenset({"the", "and", "for", "with", "src", "lib", "app", "code", "core", "main", "backend", "frontend", "skillforge"})

_FOLD = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})
_MARKS = frozenset("`*")  # inline markup that is not part of the words
_HIDDEN = ("Cc", "Cf", "Cs", "Co", "Zl", "Zp")  # control, format (bidirectional overrides, zero width), surrogate, private use, separators
_LEAD = re.compile(r"^(?:[-*•>#|]+\s*|\d+[.)]\s+)+")  # a list marker or heading mark the model copied along with the sentence
_TAIL = re.compile(r"(?:\.\.\.|…)\s*$")
_FILES_NOTE = re.compile(r"\s*\(\d+ files?\)\s*$")  # the count the prompt printed after a folder name
_BLOCK_START = re.compile(r"^\s{0,3}(?:#{1,6}\s|[-*+]\s|\d+[.)]\s|\||```|>)")  # a heading, a list item, a table row, a quote mark or a code fence
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s")
_WORD = re.compile(r"[a-z0-9]+")


def clean(text: object, limit: int) -> str:
    """Text the page may show: invisible and control characters gone, white space collapsed, cut at `limit` (with an ellipsis)."""
    raw = text if isinstance(text, str) else ""
    kept = "".join(" " if ch.isspace() else ch for ch in raw if ch.isspace() or unicodedata.category(ch) not in _HIDDEN)
    flat = " ".join(kept.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def slug(text: object) -> str:
    """The id a model gave, made safe: lower case, letters, digits and hyphens. Empty when nothing is left."""
    return re.sub(r"[^a-z0-9]+", "-", (text if isinstance(text, str) else "").lower()).strip("-")[:32]


# ---- quotes --------------------------------------------------------------------------------------------------------------


def fold(text: str) -> tuple[str, list[int]]:
    """The text with inline marks and invisible characters taken out, curly quotes and long dashes made plain, and white space collapsed, and for every
    character of the result where it stood in the original (so a line number can be worked out). Invisible characters are dropped on both sides of a
    comparison, so a quote can never show a reversed or hidden character that the page would draw differently from how it is stored."""
    out: list[str] = []
    where: list[int] = []
    space = True  # white space at the start is dropped
    for i, ch in enumerate(text):
        ch = ch.translate(_FOLD)
        if ch in _MARKS or (not ch.isspace() and unicodedata.category(ch) in _HIDDEN):
            continue
        if ch.isspace():
            if not space:
                out.append(" ")
                where.append(i)
                space = True
            continue
        out.append(ch)
        where.append(i)
        space = False
    if out and out[-1] == " ":
        out.pop()
        where.pop()
    return "".join(out), where


def paragraphs(text: str) -> list[tuple[int, int]]:
    """Where the paragraphs of a document start and end (offsets in the text). A blank line, a heading, a list item, a table row, a quote mark or a code
    fence starts a new one, and a quote must lie inside one."""
    spans: list[tuple[int, int]] = []
    start: int | None = None
    pos = 0
    for line in text.splitlines(keepends=True):
        if not line.strip():
            if start is not None:
                spans.append((start, pos))
                start = None
        elif _HEADING.match(line):  # a heading is a paragraph of one line, even with no blank line under it
            if start is not None:
                spans.append((start, pos))
            spans.append((pos, pos + len(line)))
            start = None
        elif start is None:
            start = pos
        elif _BLOCK_START.match(line):
            spans.append((start, pos))
            start = pos
        pos += len(line)
    if start is not None:
        spans.append((start, pos))
    return spans


@dataclass(frozen=True)
class Folded:
    """One paragraph of one document, ready to be searched."""

    path: str
    text: str  # the whole document (a line number is counted in it)
    flat: str  # this paragraph, folded
    where: list[int]  # for each character of `flat`, its offset in `text`


def fold_docs(docs: DocSet) -> list[Folded]:
    out: list[Folded] = []
    for d in docs.files:
        for start, end in paragraphs(d.text):
            flat, where = fold(d.text[start:end])
            if flat:
                out.append(Folded(d.path, d.text, flat, [start + w for w in where]))
    return out


@dataclass(frozen=True)
class Found:
    text: str  # the quote as the documents have it (marks out, white space collapsed)
    source: str  # the document, decided here and not by the model
    line: int


def _boundary(flat: str, at: int, end: int) -> bool:
    """Whether a match starts and ends on whole words: the character outside it is not a letter or a digit (unless the quote itself starts or ends with a
    mark, which is its own edge)."""
    left = not flat[at].isalnum() or at == 0 or not flat[at - 1].isalnum()
    right = not flat[end - 1].isalnum() or end == len(flat) or not flat[end].isalnum()
    return left and right


def find_quote(quote: object, folded: list[Folded]) -> tuple[Found | None, str]:
    """Look a quote up. (found, "") when one paragraph of some document contains it word for word (case and order exact, whole words), else (None, why)."""
    q = quote.strip().strip("\"“”") if isinstance(quote, str) else ""
    q = _TAIL.sub("", _LEAD.sub("", q))
    needle, _ = fold(q)
    if len(needle) < QUOTE_MIN_CHARS or len(needle.split()) < QUOTE_MIN_WORDS:
        return None, "quote_too_short"
    if len(needle) > QUOTE_MAX_CHARS:
        return None, "quote_too_long"
    for para in folded:
        at = para.flat.find(needle)
        while at >= 0:
            if _boundary(para.flat, at, at + len(needle)):
                return Found(needle, para.path, para.text.count("\n", 0, para.where[at]) + 1), ""
            at = para.flat.find(needle, at + 1)
    return None, "quote_not_found"


def on_topic(quote: str, *names: str) -> bool:
    """Whether a quote mentions the part at all: a word of its name, its id or its folder (or a word that begins like one) is in the quote. A flag for the
    reader, never a reason to drop: a model may name a part differently from the documents."""
    words = _WORD.findall(quote.lower())
    every = {w for name in names for w in _WORD.findall(name.lower()) if len(w) >= 2}
    for t in (every - COMMON_WORDS) or every:  # a part named only with common words ("Backend") is judged by those
        for w in words:
            if w == t or (len(t) >= 4 and len(w) >= 4 and (w.startswith(t[:4]) or t.startswith(w[:4]))):
                return True
    return False


# ---- folders -------------------------------------------------------------------------------------------------------------


def clean_folder(text: object) -> str:
    """A folder or file a part names, as a path relative to the repository, or "" when it is not one (a drive, a colon, `..`)."""
    t = _FILES_NOTE.sub("", clean(text, 200)).replace("\\", "/")
    while t.startswith("./"):
        t = t[2:]
    t = t.strip("/")
    if not t or ":" in t or any(p in ("", ".", "..") for p in t.split("/")):
        return ""
    return t


def under(paths: list[str], folder: str) -> list[str]:
    """The files of the graph that are `folder` or inside it."""
    prefix = folder + "/"
    return [p for p in paths if p == folder or p.startswith(prefix)]


def place_facts(g: RepoGraph, paths: list[str]) -> dict[str, Any]:
    """What the graph knows about a part's files: how many, how big, and where to start reading (the biggest files and functions, never tests
    unless the folder is only tests)."""
    real = [p for p in paths if not g.files[p].is_test] or paths
    biggest = sorted(real, key=lambda p: (-g.files[p].lines, p))[:READ_FIRST_FILES]
    funcs = sorted(
        (s for p in real for s in g.files[p].symbols if s.kind in ("function", "method")),
        key=lambda s: (-s.size, s.file, s.line, s.name),
    )[:READ_FIRST_FUNCTIONS]
    return {
        "files": len(paths),
        "lines": sum(g.files[p].lines for p in paths),
        "read_first": {
            "files": [{"path": p, "lines": g.files[p].lines} for p in biggest],
            "functions": [{"name": s.name, "file": s.file, "line": s.line} for s in funcs],
        },
    }


# ---- the check -----------------------------------------------------------------------------------------------------------


@dataclass
class Checked:
    parts: list[dict[str, Any]]
    journeys: list[dict[str, Any]]
    dropped: list[dict[str, str]]


def _hop(a: str, b: str, files: dict[str, set[str]], measured: dict[str, bool], links: set[tuple[str, str]]) -> dict[str, Any]:
    """What is known about one step of a route, with the numbers behind it. `confirmed`: the code imports from the first part into the second;
    `reversed`: only the other way; `both_ways`: each way (the counts say how much); `same_folder`: the two parts are one folder; `not_measured`: a
    language here has no import links to check; `docs_only`: only the documents say it. `evidence` shows a few of the file pairs of the stronger
    direction, so a reader can judge whether they are the real link."""
    fa, fb = files.get(a, set()), files.get(b, set())
    nothing: dict[str, Any] = {"forward": 0, "reverse": 0, "evidence": []}
    if not fa or not fb:
        return {"status": "docs_only", **nothing}
    if fa & fb:
        return {"status": "same_folder", **nothing}
    forward = sorted((s, d) for s, d in links if s in fa and d in fb)
    reverse = sorted((s, d) for s, d in links if s in fb and d in fa)
    status = "both_ways" if forward and reverse else "confirmed" if forward else "reversed" if reverse else None
    if status is None:
        return {"status": "docs_only" if measured[a] and measured[b] else "not_measured", **nothing}
    shown = forward if len(forward) >= len(reverse) else reverse
    return {"status": status, "forward": len(forward), "reverse": len(reverse), "evidence": [{"importer": s, "imported": d} for s, d in shown[:EVIDENCE_PAIRS]]}


def check(draft: GuideDraft, docs: DocSet, g: RepoGraph) -> Checked:
    folded = fold_docs(docs)
    paths = sorted(g.files)
    dropped: list[dict[str, str]] = []

    def drop(what: str, name: object, reason: str) -> None:
        dropped.append({"what": what, "name": clean(name, NAME), "reason": reason})

    parts: list[dict[str, Any]] = []
    ids: dict[str, str] = {}  # the id the model gave -> the id the answer uses (its position: p1, p2, ...)
    files: dict[str, set[str]] = {}
    measured: dict[str, bool] = {}
    topic: dict[str, tuple[str, ...]] = {}  # the words that say a quote is about a part
    for p in draft.parts:
        name = clean(p.name, NAME)
        mid = slug(p.id)
        if len(parts) >= MAX_PARTS:
            drop("part", p.name, "over_limit")
            continue
        if not mid or not name:
            drop("part", p.name, "bad_id")
            continue
        if mid in ids:
            drop("part", p.name, "duplicate_id")
            continue
        found, why = find_quote(p.quote, folded)
        if found is None:
            drop("part", p.name, why)
            continue
        folder = clean_folder(p.folder)
        mine = under(paths, folder) if folder else []
        pid = f"p{len(parts) + 1}"
        ids[mid] = pid
        topic[pid] = (name, mid, folder)
        status = "in_code" if mine else ("external" if p.layer == "outside" and not folder else "docs_only")
        # What a hop can be confirmed by: the part's own files, never a test and never a folder of fixtures or a test server (an import from there
        # says nothing about how the project works).
        real = [x for x in mine if not g.files[x].is_test and not is_test_support_path(x)]
        files[pid] = set(real)
        measured[pid] = any(reads_imports(g.files[x].lang) for x in real)
        parts.append({
            "id": pid, "name": name, "layer": p.layer, "summary": clean(p.summary, LINE), "takes_in": clean(p.takes_in, LINE),
            "gives_out": clean(p.gives_out, LINE), "plain": clean(p.plain, PLAIN), "folder": folder, "status": status,
            **(place_facts(g, mine) if mine else {"files": 0, "lines": 0, "read_first": {"files": [], "functions": []}}),
            "quote": {"text": found.text, "source": found.source, "line": found.line, "on_topic": on_topic(found.text, *topic[pid])},
        })

    # Proven imports (never a guess): the only thing that can confirm a hop. A test file's import cannot, because a hop is looked up only among
    # the files of the two parts, and a part's files never include tests.
    links = {(e.src, e.dst) for e in g.edges if e.kind == "imports" and e.conf == "resolved"}
    journeys: list[dict[str, Any]] = []
    for j in draft.journeys:
        if len(journeys) >= MAX_JOURNEYS:
            drop("journey", j.title, "over_limit")
            continue
        steps: list[dict[str, Any]] = []
        gaps: list[bool] = []  # for each kept step: was a step dropped just before it (so its hop would join two steps the documents never joined)
        gap = False
        for s in j.steps:
            if len(steps) >= MAX_STEPS:
                drop("step", s.does, "over_limit")
                continue
            pid = ids.get(slug(s.part))
            if pid is None:
                drop("step", s.does, "unknown_part")
                gap = True
                continue
            if steps and steps[-1]["part"] == pid:
                continue  # the same part twice in a row is one step
            found, why = find_quote(s.quote, folded)
            if found is None:
                drop("step", s.does, why)
                gap = True
                continue
            steps.append({
                "part": pid, "does": clean(s.does, LINE),
                "quote": {"text": found.text, "source": found.source, "line": found.line, "on_topic": on_topic(found.text, *topic[pid])},
            })
            gaps.append(gap)
            gap = False
        if len(steps) < MIN_STEPS:
            drop("journey", j.title, "too_few_steps")
            continue
        hops = [
            {"from": a["part"], "to": b["part"], **(
                {"status": "step_dropped", "forward": 0, "reverse": 0, "evidence": []} if gaps[i + 1] else _hop(a["part"], b["part"], files, measured, links)
            )}
            for i, (a, b) in enumerate(zip(steps, steps[1:]))
        ]
        journeys.append({"title": clean(j.title, TITLE) or f"Journey {len(journeys) + 1}", "steps": steps, "hops": hops})
    return Checked(parts, journeys, dropped)
