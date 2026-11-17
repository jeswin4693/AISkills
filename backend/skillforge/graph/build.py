"""Build the repository graph: discover, parse (only changed files), resolve, add git history."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from . import extract_python, extract_ts, history, store
from .files import discover, is_test_path, language_of
from .model import Edge, FileRecord, RepoGraph
from .resolve import Resolver


def _parse(root: Path, rel: str, size: int, mtime_ns: int) -> FileRecord:
    lang = language_of(rel) or "unknown"
    rec = FileRecord(rel, lang, 0, size, mtime_ns, is_test_path(rel))
    try:
        data = (root / rel).read_bytes()
    except OSError as exc:
        rec.error = f"unreadable: {exc}"
        return rec
    rec.lines = data.count(b"\n") + 1
    if lang == "python":
        text = data.decode("utf-8-sig", errors="replace")
        rec.symbols, rec.imports, rec.refs, rec.error = extract_python.extract(rel, text)
    else:
        rec.symbols, rec.imports, rec.refs, rec.error = extract_ts.extract(rel, data, lang)
    return rec


def build_graph(
    root: str | Path,
    *,
    focus: str | None = None,
    use_cache: bool = True,
    with_history: bool = True,
) -> RepoGraph:
    """Parse the repository at `root` into a graph. Writes only to the SkillForge data directory."""
    root = Path(root).resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"Not a directory: {root}")
    cache_file = store.cache_path(root)
    previous = store.load_records(cache_file) if use_cache and not focus else {}

    records: dict[str, FileRecord] = {}
    reused = parsed = 0
    for rel in discover(root, focus):
        st = (root / rel).stat()
        old = previous.get(rel)
        if old is not None and old.size == st.st_size and old.mtime_ns == st.st_mtime_ns:
            records[rel] = old
            reused += 1
        else:
            records[rel] = _parse(root, rel, st.st_size, st.st_mtime_ns)
            parsed += 1
    if use_cache and not focus:
        store.save_records(cache_file, records)

    graph = RepoGraph(root=str(root), files=records)
    resolver = Resolver(records)
    graph.symbols = resolver.symbols

    for path in records:  # fills resolver.deps and resolver.gaps
        resolver.table(path)
    for src, targets in resolver.deps.items():
        for dst, count in targets.items():
            graph.edges.append(Edge(src, dst, "imports", "resolved", count))
    graph.gaps = dict(resolver.gaps)

    stats: Counter[str] = Counter()
    calls: Counter[tuple[str, str, str]] = Counter()
    for sym in graph.symbols.values():
        for call in sym.calls:
            status, target = resolver.resolve_call(sym, call)
            if status == "builtin":  # counted as external, but the name may still be a method of ours
                status = "external"
                graph.loose_names.add(call.callee)
            stats[status] += 1
            if status in ("guess", "ambiguous"):
                graph.loose_names.add(call.callee)
            if target is not None and target.id != sym.id:
                calls[(sym.id, target.id, status)] += 1
    for (src, dst, conf), count in sorted(calls.items()):
        graph.edges.append(Edge(src, dst, "calls", conf, count))
    graph.call_stats = {k: stats.get(k, 0) for k in ("resolved", "guess", "ambiguous", "external", "unresolved")}

    if with_history:
        graph.commits, graph.churn, graph.co_change = history.collect(root, set(records))

    broken = sorted(p for p, r in records.items() if r.error)
    graph.notes.append(f"{parsed} files parsed, {reused} reused from the cache.")
    if broken:
        graph.notes.append(f"{len(broken)} file(s) had parse problems (partial or no symbols): {', '.join(broken[:5])}")
    return graph
