"""Resolve imports to repository files and calls to the functions they reach.

The resolver never invents a link. A call is `resolved` when scope or imports prove the target, `guess`
when only a unique name matches, and otherwise it is counted as ambiguous, external or unresolved.
"""

from __future__ import annotations

import posixpath
import sys
from dataclasses import dataclass

from .model import CallSite, FileRecord, Symbol

TS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts")
JS_TO_TS = (".ts", ".tsx", ".mts", ".cts")
INDEX_NAMES = ("index.ts", "index.tsx", "index.js", "index.jsx", "index.mjs", "index.cjs")
MAX_DEPTH = 4

# Method names that belong to built-in containers, strings, promises and streams in JavaScript and Python.
# With an unknown receiver, a call to one of these is never matched to a repository method by name alone.
BUILTIN_METHOD_NAMES = frozenset("""
get set has add delete clear push pop shift unshift map filter reduce forEach find findIndex some every includes
indexOf lastIndexOf join split slice splice concat keys values entries toString valueOf then catch finally test
exec match matchAll replace replaceAll trim trimStart trimEnd startsWith endsWith padStart padEnd toLowerCase
toUpperCase charAt sort reverse flat flatMap fill copyWithin at call apply bind on once off emit write read end
close open pipe resolve reject all race append extend insert remove update copy items count index pop popitem
setdefault strip lstrip rstrip lower upper format encode decode readline readlines writelines flush seek tell
sub subn findall finditer group groups
""".split())


@dataclass(frozen=True)
class _Entry:
    local: str  # the name bound in the importing file
    kind: str  # "module" | "name" | "star" | "external"
    file: str | None = None
    name: str | None = None  # imported name, for kind "name"


class Resolver:
    def __init__(self, files: dict[str, FileRecord]) -> None:
        self.files = files
        self.paths = set(files)
        self.symbols: dict[str, Symbol] = {}
        self.top: dict[str, dict[str, Symbol]] = {}
        self.by_name: dict[str, list[Symbol]] = {}
        self.py_index: dict[str, list[str]] = {}
        self.gaps: dict[str, list[str]] = {}
        self.deps: dict[str, dict[str, int]] = {}
        self._tables: dict[str, list[_Entry]] = {}
        self._lookups: dict[tuple[str, str], Symbol | None] = {}

        for path, rec in files.items():
            for sym in rec.symbols:
                self.symbols[sym.id] = sym
                if sym.kind == "module":
                    continue
                if "." not in sym.qualname:
                    self.top.setdefault(path, {})[sym.name] = sym
                if sym.kind in ("function", "method"):
                    self.by_name.setdefault(sym.name, []).append(sym)
            if rec.lang == "python":
                parts = path[:-3].split("/")
                if parts[-1] == "__init__":
                    parts = parts[:-1]
                for i in range(len(parts)):
                    self.py_index.setdefault(".".join(parts[i:]), []).append(path)

    # ---- modules -> files -------------------------------------------------------------------------------

    def _py_absolute(self, importer: str, dotted: str) -> str | None:
        cands = self.py_index.get(dotted, [])
        here = importer.split("/")[:-1]
        if dotted.split(".")[0] in sys.stdlib_module_names:
            # a repo file that shadows a standard-library name only counts when it sits next to the importer
            cands = [c for c in cands if c.split("/")[:-1] == here[: len(c.split("/")[:-1])]]
        if len(cands) <= 1:
            return cands[0] if cands else None

        def shared(p: str) -> int:
            n = 0
            for a, b in zip(here, p.split("/")[:-1]):
                if a != b:
                    break
                n += 1
            return n

        ranked = sorted(cands, key=shared, reverse=True)
        return ranked[0] if shared(ranked[0]) > shared(ranked[1]) else None

    def _py_relative_dir(self, importer: str, level: int) -> str:
        base = posixpath.dirname(importer)
        for _ in range(level - 1):
            base = posixpath.dirname(base)
        return base

    def _py_module_in(self, base: str, dotted: str) -> str | None:
        if not dotted:  # the package itself
            init = posixpath.join(base, "__init__.py")
            return init if init in self.paths else None
        rel = posixpath.join(base, dotted.replace(".", "/"))
        for cand in (f"{rel}.py", posixpath.join(rel, "__init__.py")):
            if cand in self.paths:
                return cand
        return None

    def _py_submodule(self, module_file: str, name: str) -> str | None:
        if posixpath.basename(module_file) != "__init__.py":
            return None
        return self._py_module_in(posixpath.dirname(module_file), name)

    def _ts_file(self, base: str) -> str | None:
        if base in self.paths:
            return base
        stem, ext = posixpath.splitext(base)
        if ext in (".js", ".jsx", ".mjs", ".cjs"):
            for e in JS_TO_TS:
                if stem + e in self.paths:
                    return stem + e
        for e in TS_EXTS:
            if base + e in self.paths:
                return base + e
        for idx in INDEX_NAMES:
            cand = posixpath.join(base, idx)
            if cand in self.paths:
                return cand
        return None

    def _ts_module(self, importer: str, spec: str) -> str | None:
        if spec.startswith("."):
            base = posixpath.normpath(posixpath.join(posixpath.dirname(importer), spec))
            return None if base.startswith("..") else self._ts_file(base)
        if spec.startswith(("@/", "~/")):
            for root in ("src/", ""):
                found = self._ts_file(root + spec[2:])
                if found:
                    return found
        return None

    # ---- per-file import table --------------------------------------------------------------------------

    def table(self, path: str) -> list[_Entry]:
        cached = self._tables.get(path)
        if cached is not None:
            return cached
        rec = self.files[path]
        entries: list[_Entry] = []
        gaps: list[str] = []
        deps: dict[str, int] = {}

        def dep(target: str | None) -> None:
            if target and target != path:
                deps[target] = deps.get(target, 0) + 1

        for imp in rec.imports:
            if rec.lang == "python":
                self._table_python(path, imp, entries, gaps, dep)
            else:
                self._table_ts(path, imp, entries, gaps, dep)
        self._tables[path] = entries
        if gaps:
            self.gaps[path] = gaps
        self.deps[path] = deps
        return entries

    def _table_python(self, path, imp, entries, gaps, dep) -> None:
        if imp.level == 0 and imp.names and all(n == "" for n, _ in imp.names):  # `import a.b.c [as x]`
            target = self._py_absolute(path, imp.module)
            for _, local in imp.names:
                entries.append(_Entry(local, "module", target) if target else _Entry(local, "external"))
            dep(target)
            return
        if imp.level > 0:
            base = self._py_relative_dir(path, imp.level)
            mod_file = self._py_module_in(base, imp.module) if imp.module else self._py_module_in(base, "")
            sub_base = base if not imp.module else None
        else:
            mod_file = self._py_absolute(path, imp.module) if imp.module else None
            sub_base = None
        if mod_file is None and imp.level > 0 and not imp.module and not any(
            self._py_module_in(base, n) for n, _ in imp.names if n != "*"
        ):
            gaps.append("." * imp.level)
        elif mod_file is None and imp.level > 0 and imp.module:
            gaps.append("." * imp.level + imp.module)
        for name, local in imp.names:
            if name == "*":
                if mod_file:
                    entries.append(_Entry("*", "star", mod_file))
                    dep(mod_file)
                continue
            sub = None
            if sub_base is not None:
                sub = self._py_module_in(sub_base, name)
            elif mod_file:
                sub = self._py_submodule(mod_file, name)
            if sub:
                entries.append(_Entry(local, "module", sub))
                dep(sub)
            elif mod_file:
                entries.append(_Entry(local, "name", mod_file, name))
                dep(mod_file)
            else:
                entries.append(_Entry(local, "external"))

    def _table_ts(self, path, imp, entries, gaps, dep) -> None:
        target = self._ts_module(path, imp.module)
        if target is None:
            if imp.module.startswith("."):
                gaps.append(imp.module)
            for _, local in imp.names:
                if local != "*":
                    entries.append(_Entry(local, "external"))
            return
        dep(target)
        for name, local in imp.names:
            if name == "":
                entries.append(_Entry(local, "module", target))
            elif name == "*":
                entries.append(_Entry("*", "star", target))
            else:
                entries.append(_Entry(local, "name", target, name))

    # ---- names -> symbols -------------------------------------------------------------------------------

    def lookup(self, path: str, name: str, depth: int = MAX_DEPTH, _seen: frozenset | None = None) -> Symbol | None:
        """What does `name` mean inside file `path`: something it defines, imports, or re-exports."""
        top = self.top.get(path, {}).get(name)
        if top is not None:
            return top
        if depth <= 0:
            return None
        key = (path, name)
        seen = _seen or frozenset()
        if key in seen:
            return None
        seen = seen | {key}
        for entry in self.table(path):
            if entry.kind == "name" and entry.local == name and entry.file:
                imported = entry.name or name
                if imported == "default":
                    found = self._default_symbol(entry.file)
                else:
                    found = self.lookup(entry.file, imported, depth - 1, seen)
                if found is not None:
                    return found
        for entry in self.table(path):
            if entry.kind == "star" and entry.file:
                found = self.lookup(entry.file, name, depth - 1, seen)
                if found is not None:
                    return found
        return None

    def _default_symbol(self, path: str) -> Symbol | None:
        exported = [s for s in self.top.get(path, {}).values() if s.exported and s.kind in ("function", "class")]
        return exported[0] if len(exported) == 1 else None

    def module_alias(self, path: str, local: str) -> str | None:
        for entry in self.table(path):
            if entry.kind == "module" and entry.local == local:
                return entry.file
        return None

    def _is_external(self, path: str, receiver: str) -> bool:
        head = receiver.split(".")[0]
        return any(e.kind == "external" and (e.local == receiver or e.local == head) for e in self.table(path))

    # ---- classes ----------------------------------------------------------------------------------------

    def class_of(self, sym: Symbol) -> Symbol | None:
        if sym.parent:
            return self.symbols.get(f"{sym.file}::{sym.parent}")
        parts = sym.qualname.split(".")
        for i in range(len(parts) - 1, 0, -1):
            cand = self.symbols.get(f"{sym.file}::{'.'.join(parts[:i])}")
            if cand is not None and cand.kind == "class":
                return cand
        return None

    def _class_named(self, path: str, name: str) -> Symbol | None:
        if "." in name:
            head, _, rest = name.partition(".")
            mod = self.module_alias(path, head)
            return self.lookup(mod, rest) if mod and "." not in rest else None
        found = self.lookup(path, name)
        return found if found is not None and found.kind == "class" else None

    def find_method(self, cls: Symbol, name: str, skip_self: bool = False, depth: int = MAX_DEPTH) -> Symbol | None:
        if not skip_self:
            m = self.symbols.get(f"{cls.file}::{cls.qualname}.{name}")
            if m is not None and m.kind == "method":
                return m
        if depth <= 0:
            return None
        for base in cls.bases:
            base_cls = self._class_named(cls.file, base)
            if base_cls is not None and base_cls is not cls:
                found = self.find_method(base_cls, name, False, depth - 1)
                if found is not None:
                    return found
        return None

    # ---- calls ------------------------------------------------------------------------------------------

    def _enclosing_definition(self, caller: Symbol, name: str) -> Symbol | None:
        """A function defined inside `caller` or inside any function that encloses it (closures call siblings).

        Class bodies are skipped: a method cannot call another method of its class by bare name.
        """
        parts = caller.qualname.split(".")
        for i in range(len(parts), 0, -1):
            scope = ".".join(parts[:i])
            scope_sym = self.symbols.get(f"{caller.file}::{scope}")
            if scope_sym is not None and scope_sym.kind == "class" and scope != caller.qualname:
                continue
            found = self.symbols.get(f"{caller.file}::{scope}.{name}")
            if found is not None and found.kind in ("function", "class"):
                return found
        return None

    def _receiver_target(self, path: str, receiver: str, callee: str) -> tuple[Symbol | None, bool]:
        """(symbol, known). `known` is True when the receiver is a module or class of this repository."""
        parts = receiver.split(".")
        for i in range(len(parts), 0, -1):
            mod = self.module_alias(path, ".".join(parts[:i]))
            if mod is None:
                continue
            cur: str | None = mod
            for part in parts[i:]:
                cur = self._py_submodule(cur, part) if cur else None
            return (self.lookup(cur, callee) if cur else None), True
        if "." not in receiver:
            cls = self.lookup(path, receiver)
            if cls is not None and cls.kind == "class":
                return self.find_method(cls, callee), True
        return None, False

    def resolve_call(self, caller: Symbol, call: CallSite) -> tuple[str, Symbol | None]:
        path = caller.file
        if call.kind == "name":
            nested = self._enclosing_definition(caller, call.callee)
            if nested is not None:
                return "resolved", nested
            target = self.lookup(path, call.callee)
            return ("resolved", target) if target is not None else ("external", None)
        if call.kind in ("self", "super"):
            cls = self.class_of(caller)
            method = self.find_method(cls, call.callee, skip_self=call.kind == "super") if cls else None
            return ("resolved", method) if method is not None else ("unresolved", None)
        receiver = call.receiver
        if receiver:
            target, known = self._receiver_target(path, receiver, call.callee)
            if target is not None:
                return "resolved", target
            if known:
                return "unresolved", None
            if self._is_external(path, receiver):
                return "external", None
        if call.callee in BUILTIN_METHOD_NAMES:  # `x.get()` is far more likely a Map or dict than our code
            return "builtin", None
        caller_is_test = self.files[path].is_test
        cands = [  # only a class method can be reached as `obj.name()` when the receiver's type is unknown
            s for s in self.by_name.get(call.callee, [])
            if s.kind == "method" and s is not caller and (caller_is_test or not self.files[s.file].is_test)
        ]
        if len(cands) == 1:
            return "guess", cands[0]
        return ("ambiguous", None) if cands else ("external", None)
