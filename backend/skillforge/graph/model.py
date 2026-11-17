"""Data model for the repository graph.

Every fact in the graph comes from a parser or from git, never from a model. Edges say how sure we are:
`resolved` means the target was found through scope or imports, `guess` means only the name matched.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Bump when the content of a cached FileRecord changes, so old caches are ignored.
SCHEMA_VERSION = 1


@dataclass
class CallSite:
    callee: str  # the name being called: "foo", or the method name for self/attr calls
    line: int
    kind: str  # "name" | "self" | "super" | "attr"
    receiver: str | None = None  # dotted text of what the method is called on, when it is a plain name


@dataclass
class Symbol:
    id: str  # "<file>::<qualname>"
    kind: str  # "function" | "method" | "class" | "module"
    name: str
    qualname: str
    file: str
    line: int
    end_line: int
    exported: bool = False
    decorated: bool = False
    parent: str | None = None  # qualname of the enclosing class, for a method
    bases: list[str] = field(default_factory=list)  # classes only: base class names as written
    size: int = 0  # number of syntax nodes in the body (functions and methods)
    shape: str | None = None  # hash of the body structure with names and literals abstracted
    calls: list[CallSite] = field(default_factory=list)


@dataclass
class ImportRef:
    module: str  # as written: "./util", "os.path", "pkg.mod", ".sibling"
    # (imported name, local name). ("", local) = the module itself bound to `local`; ("*", "*") = star import
    names: list[tuple[str, str]] = field(default_factory=list)
    line: int = 0
    level: int = 0  # number of leading dots of a Python relative import


@dataclass
class FileRecord:
    path: str
    lang: str
    lines: int
    size: int
    mtime_ns: int
    is_test: bool
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[ImportRef] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)  # names used as values (not called), for dead-code checks
    error: str | None = None


@dataclass
class Edge:
    src: str  # file path (imports) or symbol id (calls)
    dst: str
    kind: str  # "imports" | "calls"
    conf: str = "resolved"  # "resolved" | "guess"
    count: int = 1


@dataclass
class RepoGraph:
    root: str
    files: dict[str, FileRecord] = field(default_factory=dict)
    symbols: dict[str, Symbol] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    gaps: dict[str, list[str]] = field(default_factory=dict)  # file -> relative imports that match no file
    call_stats: dict[str, int] = field(default_factory=dict)  # resolved/guess/ambiguous/external/unresolved
    co_change: list[tuple[str, str, int, float]] = field(default_factory=list)  # (a, b, shared commits, confidence)
    churn: dict[str, int] = field(default_factory=dict)  # file -> commits touching it
    commits: int | None = None  # commits read from git, None outside git
    notes: list[str] = field(default_factory=list)
    # names at call sites we could not pin to one target; a function with such a name may still be in use
    loose_names: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self._callers: dict[str, list[Edge]] | None = None
        self._callees: dict[str, list[Edge]] | None = None
        self._importers: dict[str, list[Edge]] | None = None
        self._imports: dict[str, list[Edge]] | None = None

    def _index(self) -> None:
        self._callers, self._callees, self._importers, self._imports = {}, {}, {}, {}
        for e in self.edges:
            if e.kind == "calls":
                self._callees.setdefault(e.src, []).append(e)
                self._callers.setdefault(e.dst, []).append(e)
            else:
                self._imports.setdefault(e.src, []).append(e)
                self._importers.setdefault(e.dst, []).append(e)

    def callers_of(self, symbol_id: str) -> list[Edge]:
        if self._callers is None:
            self._index()
        return self._callers.get(symbol_id, [])  # type: ignore[union-attr]

    def callees_of(self, symbol_id: str) -> list[Edge]:
        if self._callees is None:
            self._index()
        return self._callees.get(symbol_id, [])  # type: ignore[union-attr]

    def importers_of(self, path: str) -> list[Edge]:
        if self._importers is None:
            self._index()
        return self._importers.get(path, [])  # type: ignore[union-attr]

    def imports_of(self, path: str) -> list[Edge]:
        if self._imports is None:
            self._index()
        return self._imports.get(path, [])  # type: ignore[union-attr]
