"""The function explorer's graphs, kept in memory (slice AL).

Drawing one function and then the next is a series of requests about the same repository. Reading the whole repository for each of them takes
a second or more (and a few seconds when a focus folder is given, which the on-disk cache does not cover), so the last few graphs are kept.

A kept graph is used only while every file the graph would read is exactly as it was: the same names, sizes and modification times, which is
the test the on-disk cache already applies to a file. Anything else reads it afresh. The fingerprint is taken BEFORE the graph is read, so a file
that changes during the read leaves an older fingerprint behind and the next request reads again, never the other way round.

A graph is shared by requests that run at the same moment, so it is only ever read: its lookup tables are built before it is kept, and nothing in
the explorer changes it. History from git is not read (the explorer does not use it).
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from pathlib import Path

from ..graph.build import build_graph
from ..graph.files import discover
from ..graph.model import RepoGraph

KEEP = 2  # graphs kept; the one unused for longest goes first

_lock = threading.Lock()
_kept: OrderedDict[tuple[str, str], tuple[object, RepoGraph]] = OrderedDict()


def _fingerprint(folder: Path, focus: str | None) -> object:
    """What the graph of this folder would be made from. A folder that cannot be listed gives a value that equals nothing, so it is read afresh
    (and the read says why it cannot be)."""
    try:
        return tuple((rel, st.st_size, st.st_mtime_ns) for rel in discover(folder, focus) for st in ((folder / rel).stat(),))
    except OSError:
        return object()


def graph_for(folder: Path, focus: str | None) -> RepoGraph:
    """The graph of a folder (or of one folder inside it), from memory when nothing in it has changed since it was read."""
    key = (str(folder), focus or "")
    seen = _fingerprint(folder, focus)
    with _lock:
        hit = _kept.get(key)
        if hit is not None and hit[0] == seen:
            _kept.move_to_end(key)
            return hit[1]
    graph = build_graph(folder, focus=focus, with_history=False)
    graph.callers_of("")  # builds all four lookup tables now: a graph several requests read at once is never changed by a read
    with _lock:
        _kept[key] = (seen, graph)
        _kept.move_to_end(key)
        while len(_kept) > KEEP:
            _kept.popitem(last=False)
    return graph


def clear() -> None:
    with _lock:
        _kept.clear()
