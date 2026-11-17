"""Extract symbols, imports and call sites from Python source with the standard `ast` module."""

from __future__ import annotations

import ast
import hashlib

from .model import CallSite, ImportRef, Symbol


def _dotted(node: ast.AST) -> str | None:
    """`a`, `a.b.c` for a chain of plain names; None for anything else."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _call_site(node: ast.Call) -> CallSite | None:
    f = node.func
    if isinstance(f, ast.Name):
        return CallSite(f.id, node.lineno, "name")
    if isinstance(f, ast.Attribute):
        v = f.value
        if isinstance(v, ast.Name) and v.id in ("self", "cls"):
            return CallSite(f.attr, node.lineno, "self", v.id)
        if isinstance(v, ast.Call) and isinstance(v.func, ast.Name) and v.func.id == "super":
            return CallSite(f.attr, node.lineno, "super", "super")
        return CallSite(f.attr, node.lineno, "attr", _dotted(v))
    return None


def _scan(roots: list[ast.AST]) -> tuple[list[CallSite], set[str], list[ast.AST]]:
    """Calls and value-references in `roots`, and the function/class definitions directly inside them.

    Nested definitions are returned, not entered: each one owns its own calls. Decorators, base classes
    and default values run in the enclosing scope, so they are scanned here.
    """
    calls: list[CallSite] = []
    refs: set[str] = set()
    defs: list[ast.AST] = []
    stack: list[ast.AST] = list(reversed(roots))
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defs.append(n)
            stack.extend(n.decorator_list)
            stack.extend(n.args.defaults)
            stack.extend(d for d in n.args.kw_defaults if d is not None)
            continue
        if isinstance(n, ast.ClassDef):
            defs.append(n)
            stack.extend(n.decorator_list)
            stack.extend(n.bases)
            stack.extend(k.value for k in n.keywords)
            continue
        if isinstance(n, ast.Call):
            site = _call_site(n)
            if site is not None:
                calls.append(site)
            f = n.func
            if isinstance(f, ast.Attribute):
                if site is None or site.kind != "super":  # `super().m()` is one call, not two
                    stack.append(f.value)
            elif not isinstance(f, ast.Name):
                stack.append(f)
            stack.extend(n.args)
            stack.extend(k.value for k in n.keywords)
            continue
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            refs.add(n.id)
        elif isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Load):
            refs.add(n.attr)
        stack.extend(ast.iter_child_nodes(n))
    calls.sort(key=lambda c: c.line)
    return calls, refs, defs


def _shape(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[int, str]:
    """Size and structure hash of a function. Names and literal values are ignored, so renamed copies match."""
    body = list(node.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]  # the docstring is not part of the behaviour
    tokens: list[str] = []
    stack: list[tuple[ast.AST, int]] = [(r, 0) for r in reversed([node.args, *body])]
    while stack:
        n, depth = stack.pop()
        tokens.append(f"{depth}{type(n).__name__}")
        stack.extend((c, depth + 1) for c in reversed(list(ast.iter_child_nodes(n))))
    digest = hashlib.sha1(",".join(tokens).encode()).hexdigest()[:16]
    return len(tokens), digest


def _imports(tree: ast.AST) -> list[ImportRef]:
    found: list[ImportRef] = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for alias in n.names:
                found.append(ImportRef(alias.name, [("", alias.asname or alias.name)], n.lineno, 0))
        elif isinstance(n, ast.ImportFrom):
            names = [("*", "*") if a.name == "*" else (a.name, a.asname or a.name) for a in n.names]
            found.append(ImportRef(n.module or "", names, n.lineno, n.level or 0))
    return found


def extract(path: str, source: str) -> tuple[list[Symbol], list[ImportRef], list[str], str | None]:
    """Returns (symbols, imports, value references, error)."""
    try:
        tree = ast.parse(source, filename=path)
    except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
        return [], [], [], f"{type(exc).__name__}: {exc}"

    symbols: list[Symbol] = []
    all_refs: set[str] = set()

    def visit_scope(body: list[ast.AST], owner: Symbol | None, prefix: str, cls: Symbol | None) -> None:
        calls, refs, defs = _scan(body)
        all_refs.update(refs)
        if owner is not None:
            owner.calls.extend(calls)
        elif calls:  # calls made when the module is loaded
            mod = Symbol(f"{path}::<module>", "module", "<module>", "<module>", path, 1, 1, calls=calls)
            symbols.append(mod)
        for d in defs:
            qual = f"{prefix}.{d.name}" if prefix else d.name  # type: ignore[attr-defined]
            if isinstance(d, ast.ClassDef):
                exported = not prefix and not d.name.startswith("_")
                sym = Symbol(
                    f"{path}::{qual}", "class", d.name, qual, path, d.lineno, d.end_lineno or d.lineno,
                    exported=exported, decorated=bool(d.decorator_list),
                    bases=[b for b in (_dotted(x) for x in d.bases) if b],
                )
                symbols.append(sym)
                visit_scope(d.body, sym, qual, sym)
            else:
                is_method = cls is not None and prefix == cls.qualname
                exported = (
                    (cls.exported if is_method and cls else not prefix) and not d.name.startswith("_")  # type: ignore[attr-defined]
                )
                size, shape = _shape(d)  # type: ignore[arg-type]
                sym = Symbol(
                    f"{path}::{qual}", "method" if is_method else "function", d.name, qual, path,
                    d.lineno, d.end_lineno or d.lineno, exported=exported,
                    decorated=bool(d.decorator_list), parent=cls.qualname if is_method and cls else None,
                    size=size, shape=shape,
                )
                symbols.append(sym)
                visit_scope(d.body, sym, qual, None)  # type: ignore[attr-defined]

    visit_scope(tree.body, None, "", None)
    return symbols, _imports(tree), sorted(all_refs), None
