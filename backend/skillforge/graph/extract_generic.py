"""Symbols, imports and calls for many languages from tree-sitter, driven by one small spec per language.

Standard languages (Java, Go, Rust, C, C++, C#, Ruby, PHP, Kotlin) get functions, classes, imports and calls. Any
other language with a grammar gets "basic" extraction: definitions only. Every language gets the same structure hash
per function, so duplicate detection works everywhere there is a grammar.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass, replace

from tree_sitter import Node

from . import languages
from .model import CallSite, ImportRef, Symbol

COMMENTS = {"comment", "line_comment", "block_comment", "doc_comment", "documentation_comment"}
IDENT_TYPES = {
    "identifier", "field_identifier", "property_identifier", "type_identifier", "simple_identifier", "name",
    "constant", "namespace_identifier", "package_identifier", "variable_name",
}
MEMBER_TYPES = {
    "field_access", "member_access_expression", "selector_expression", "field_expression", "scoped_identifier",
    "navigation_expression", "member_expression", "qualified_identifier", "scope_resolution", "qualified_name",
}


def _t(node: Node | None) -> str:
    return node.text.decode("utf-8", "replace") if node is not None and node.text is not None else ""


def _f(node: Node | None, field: str) -> Node | None:
    return node.child_by_field_name(field) if node is not None else None


def _recv(node: Node | None) -> str | None:
    """Dotted text of a receiver made only of plain names (a, a.b, this.x); None for anything else."""
    if node is None:
        return None
    if node.type in IDENT_TYPES or node.type in ("this", "self", "super"):
        return _t(node)
    if node.type in MEMBER_TYPES:
        text = _t(node)
        return text if re.fullmatch(r"[\w$@.\\:>-]+", text) else None
    return None


def _shape(node: Node) -> tuple[int, str]:
    tokens: list[str] = []
    stack: list[tuple[Node, int]] = [(node, 0)]
    while stack:
        n, depth = stack.pop()
        if n.type in COMMENTS:
            continue
        tokens.append(f"{depth}{n.type}")
        stack.extend((c, depth + 1) for c in reversed(n.children))
    return len(tokens), hashlib.sha1(",".join(tokens).encode()).hexdigest()[:16]


# ---- the spec ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Spec:
    class_types: frozenset[str]
    func_types: frozenset[str]
    call: Callable[[Node, frozenset[str]], tuple[CallSite, Node | None] | None]
    imports: Callable[[Node], list[ImportRef]] = lambda n: []
    import_types: frozenset[str] = frozenset()
    impl_types: frozenset[str] = frozenset()  # blocks that add methods to a named type (Rust impl)
    class_name: Callable[[Node], str | None] = lambda n: _t(_f(n, "name")) or None
    func_name: Callable[[Node], tuple[str | None, str | None]] = lambda n: (_t(_f(n, "name")) or None, None)
    class_ok: Callable[[Node], bool] = lambda n: True
    impl_name: Callable[[Node], str | None] = lambda n: None
    bases: Callable[[Node], list[str]] = lambda n: []
    exported: Callable[[Node, str], bool] = lambda n, name: True
    decorated: Callable[[Node], bool] = lambda n: False
    self_names: Callable[[Node], frozenset[str]] = lambda n: frozenset()


def _site(name: str, node: Node, kind: str, receiver: str | None = None) -> CallSite:
    return CallSite(name, node.start_point[0] + 1, kind, receiver)


def _last(text: str) -> str:
    return re.split(r"[.:\\]", re.sub(r"<.*", "", text.strip()))[-1]


def _kind_for_receiver(obj: Node | None, selfs: frozenset[str]) -> tuple[str, str | None]:
    """('self'|'super'|'attr', receiver text) for the object a method is called on."""
    if obj is None:
        return "name", None
    text = _t(obj)
    if obj.type in ("this", "this_expression") or text in ("this", "$this", "self", "Self") or text in selfs:
        return "self", text
    if obj.type == "super" or text in ("super", "base", "parent", "parent::"):
        return "super", text
    return "attr", _recv(obj)


# ---- Java --------------------------------------------------------------------------------------------


def _java_call(n: Node, selfs: frozenset[str]):
    if n.type == "method_invocation":
        name = _f(n, "name")
        kind, recv = _kind_for_receiver(_f(n, "object"), selfs)
        return _site(_t(name), n, kind, recv), name
    if n.type == "object_creation_expression":
        return _site(_last(_t(_f(n, "type"))), n, "name"), _f(n, "type")
    return None


def _java_import(n: Node) -> list[ImportRef]:
    text = " ".join(_t(n).replace(";", " ").split())
    text = re.sub(r"^import\s+(static\s+)?", "", text)
    if text.endswith(".*"):
        return [ImportRef(text[:-2], [("*", "*")], n.start_point[0] + 1)]
    module, _, name = text.rpartition(".")
    return [ImportRef(module or text, [(name, name)] if module else [], n.start_point[0] + 1)]


def _java_bases(n: Node) -> list[str]:
    out = []
    sup = _f(n, "superclass")
    if sup is not None:
        out.append(_last(_t(sup).replace("extends", "")))
    return out


JAVA = Spec(
    class_types=frozenset({"class_declaration", "interface_declaration", "enum_declaration", "record_declaration"}),
    func_types=frozenset({"method_declaration", "constructor_declaration"}),
    call=_java_call, imports=_java_import, import_types=frozenset({"import_declaration"}), bases=_java_bases,
    exported=lambda n, name: any(c.type == "modifiers" and "public" in _t(c) for c in n.children),
    decorated=lambda n: any(c.type == "modifiers" and "@" in _t(c) for c in n.children),
)


# ---- Go ----------------------------------------------------------------------------------------------


def _go_call(n: Node, selfs: frozenset[str]):
    if n.type != "call_expression":
        return None
    fn = _f(n, "function")
    if fn is None:
        return None
    if fn.type == "identifier":
        return _site(_t(fn), n, "name"), fn
    if fn.type == "selector_expression":
        field = _f(fn, "field")
        kind, recv = _kind_for_receiver(_f(fn, "operand"), selfs)
        return _site(_t(field), n, "attr" if kind == "name" else kind, recv), fn
    return None


def _go_method(n: Node) -> tuple[str | None, str | None]:
    name = _t(_f(n, "name")) or None
    if n.type != "method_declaration":
        return name, None
    recv = _f(n, "receiver")
    decl = next((c for c in (recv.named_children if recv else []) if c.type == "parameter_declaration"), None)
    typ = _f(decl, "type")
    return name, _last(_t(typ).lstrip("*")) if typ is not None else None


def _go_self_names(n: Node) -> frozenset[str]:
    recv = _f(n, "receiver")
    decl = next((c for c in (recv.named_children if recv else []) if c.type == "parameter_declaration"), None)
    nm = _t(_f(decl, "name"))
    return frozenset({nm}) if nm else frozenset()


def _go_import(n: Node) -> list[ImportRef]:
    out = []
    for spec in ([n] if n.type == "import_spec" else [c for c in n.named_children if c.type == "import_spec"]):
        path = _t(_f(spec, "path")).strip("\"`")
        parts = [p for p in path.split("/") if p]
        local = _t(_f(spec, "name")) or next((p for p in reversed(parts) if not re.fullmatch(r"v\d+", p)), path)
        if path:
            out.append(ImportRef(path, [("", local)], spec.start_point[0] + 1))
    return out


GO = Spec(
    class_types=frozenset({"type_spec"}),
    func_types=frozenset({"function_declaration", "method_declaration"}),
    call=_go_call, imports=_go_import, import_types=frozenset({"import_spec"}),
    class_ok=lambda n: (_f(n, "type") is not None and _f(n, "type").type in ("struct_type", "interface_type")),
    func_name=_go_method, self_names=_go_self_names,
    exported=lambda n, name: name[:1].isupper(),
)


# ---- Rust --------------------------------------------------------------------------------------------


def _rust_call(n: Node, selfs: frozenset[str]):
    if n.type != "call_expression":
        return None
    fn = _f(n, "function")
    while fn is not None and fn.type == "generic_function":
        fn = _f(fn, "function")
    if fn is None:
        return None
    if fn.type == "identifier":
        return _site(_t(fn), n, "name"), fn
    if fn.type == "scoped_identifier":
        path = _t(_f(fn, "path"))
        kind = "self" if path in ("Self", "self") else "attr"
        return _site(_t(_f(fn, "name")), n, kind, path), fn
    if fn.type == "field_expression":
        kind, recv = _kind_for_receiver(_f(fn, "value"), selfs)
        return _site(_t(_f(fn, "field")), n, "attr" if kind == "name" else kind, recv), fn
    return None


def _rust_import(n: Node) -> list[ImportRef]:
    line = n.start_point[0] + 1
    if n.type == "mod_item":
        if _f(n, "body") is not None:
            return []  # an inline module, not a file
        name = _t(_f(n, "name"))
        return [ImportRef(f"self::{name}", [("", name)], line)]
    text = " ".join(_t(_f(n, "argument")).split())
    if not text:
        return []
    m = re.match(r"^(.*?)::\{(.*)\}$", text)
    if m:
        names = []
        for part in m.group(2).split(","):
            part = part.strip()
            if not part or "{" in part:
                continue
            name, _, alias = part.partition(" as ")
            names.append((name.strip(), (alias or name).strip()) if name.strip() != "*" else ("*", "*"))
        return [ImportRef(m.group(1), names, line)]
    if text.endswith("::*"):
        return [ImportRef(text[:-3], [("*", "*")], line)]
    base, _, alias = text.partition(" as ")
    module, _, name = base.rpartition("::")
    return [ImportRef(module or base, [(name, (alias or name).strip())] if module else [], line)]


RUST = Spec(
    class_types=frozenset({"struct_item", "enum_item", "trait_item", "union_item"}),
    func_types=frozenset({"function_item"}),
    call=_rust_call, imports=_rust_import, import_types=frozenset({"use_declaration", "mod_item"}),
    impl_types=frozenset({"impl_item"}), impl_name=lambda n: _last(_t(_f(n, "type"))) or None,
    exported=lambda n, name: any(c.type == "visibility_modifier" for c in n.children),
)


# ---- C and C++ ---------------------------------------------------------------------------------------


def _c_declarator_name(n: Node) -> tuple[str | None, str | None]:
    d = _f(n, "declarator")
    while d is not None and d.type in (
        "pointer_declarator", "reference_declarator", "function_declarator", "parenthesized_declarator", "array_declarator",
    ):
        d = _f(d, "declarator")
    if d is None:
        return None, None
    if d.type == "qualified_identifier":
        return _t(_f(d, "name")) or None, _last(_t(_f(d, "scope"))) or None
    return (_t(d) or None), None


def _c_call(n: Node, selfs: frozenset[str]):
    if n.type != "call_expression":
        return None
    fn = _f(n, "function")
    if fn is None:
        return None
    if fn.type == "template_function":
        fn = _f(fn, "name") or fn
    if fn.type in ("identifier", "field_identifier"):
        return _site(_t(fn), n, "name"), fn
    if fn.type == "field_expression":
        kind, recv = _kind_for_receiver(_f(fn, "argument"), selfs)
        return _site(_t(_f(fn, "field")), n, "attr" if kind == "name" else kind, recv), fn
    if fn.type == "qualified_identifier":
        return _site(_t(_f(fn, "name")), n, "attr", _t(_f(fn, "scope"))), fn
    return None


def _c_include(n: Node) -> list[ImportRef]:
    path = _f(n, "path")
    if path is None or path.type != "string_literal":
        return []  # <system headers> are external
    return [ImportRef(_t(path).strip('"'), [], n.start_point[0] + 1)]


def _c_exported(n: Node, name: str) -> bool:
    return not any(c.type == "storage_class_specifier" and _t(c) == "static" for c in n.children)


C = Spec(
    class_types=frozenset({"struct_specifier", "union_specifier"}),
    func_types=frozenset({"function_definition"}),
    call=_c_call, imports=_c_include, import_types=frozenset({"preproc_include"}),
    class_ok=lambda n: _f(n, "body") is not None, func_name=_c_declarator_name, exported=_c_exported,
)
CPP = replace(C, class_types=frozenset({"class_specifier", "struct_specifier", "union_specifier"}))


# ---- C# ----------------------------------------------------------------------------------------------


def _cs_call(n: Node, selfs: frozenset[str]):
    if n.type == "invocation_expression":
        fn = _f(n, "function")
        if fn is None:
            return None
        if fn.type == "generic_name":
            fn = next((c for c in fn.children if c.type == "identifier"), fn)
        if fn.type == "identifier":
            return _site(_t(fn), n, "name"), fn
        if fn.type == "member_access_expression":
            name = _f(fn, "name")
            first = fn.children[0] if fn.children else None
            kind, recv = _kind_for_receiver(first, selfs)
            return _site(_last(_t(name)), n, "attr" if kind == "name" else kind, recv), fn
        return None
    if n.type == "object_creation_expression":
        return _site(_last(_t(_f(n, "type"))), n, "name"), _f(n, "type")
    return None


def _cs_bases(n: Node) -> list[str]:
    bl = next((c for c in n.children if c.type == "base_list"), None)
    return [_last(_t(c)) for c in (bl.named_children if bl else [])][:1]


CSHARP = Spec(
    class_types=frozenset({"class_declaration", "struct_declaration", "interface_declaration", "record_declaration"}),
    func_types=frozenset({"method_declaration", "constructor_declaration", "local_function_statement"}),
    call=_cs_call,
    imports=lambda n: [ImportRef(_t(n.named_children[0]), [], n.start_point[0] + 1)] if n.named_children else [],
    import_types=frozenset({"using_directive"}), bases=_cs_bases,
    exported=lambda n, name: any(c.type == "modifier" and _t(c) == "public" for c in n.children),
    decorated=lambda n: any(c.type == "attribute_list" for c in n.children),
)


# ---- Ruby --------------------------------------------------------------------------------------------


def _rb_call(n: Node, selfs: frozenset[str]):
    if n.type == "call":
        method = _f(n, "method")
        recv = _f(n, "receiver")
        if method is None:
            return None
        if recv is None:
            return _site(_t(method), n, "name"), method
        kind, text = _kind_for_receiver(recv, selfs)
        return _site(_t(method), n, "attr" if kind == "name" else kind, text), method
    if n.type == "identifier" and n.parent is not None and n.parent.type in ("body_statement", "then", "else", "do_block"):
        return _site(_t(n), n, "name"), n  # a bare `step` statement is a method call
    return None


def _rb_import(n: Node) -> list[ImportRef]:
    if n.type != "call" or _f(n, "receiver") is not None:
        return []
    if _t(_f(n, "method")) not in ("require", "require_relative", "load"):
        return []
    arg = next((c for c in (_f(n, "arguments").named_children if _f(n, "arguments") else []) if c.type == "string"), None)
    if arg is None:
        return []
    rel = _t(_f(n, "method")) != "require"
    return [ImportRef(("./" if rel else "") + _t(arg).strip("'\""), [], n.start_point[0] + 1)]


RUBY = Spec(
    class_types=frozenset({"class", "module"}),
    func_types=frozenset({"method", "singleton_method"}),
    call=_rb_call, imports=_rb_import, import_types=frozenset({"call"}),
    class_name=lambda n: _last(_t(_f(n, "name"))) or None,
    bases=lambda n: [_last(_t(_f(n, "superclass")).lstrip("< "))] if _f(n, "superclass") is not None else [],
)


# ---- PHP ---------------------------------------------------------------------------------------------


def _php_call(n: Node, selfs: frozenset[str]):
    if n.type == "function_call_expression":
        fn = _f(n, "function")
        return (_site(_last(_t(fn)), n, "name"), fn) if fn is not None else None
    if n.type == "member_call_expression":
        kind, recv = _kind_for_receiver(_f(n, "object"), selfs)
        return _site(_t(_f(n, "name")), n, "attr" if kind == "name" else kind, recv), _f(n, "name")
    if n.type == "scoped_call_expression":
        scope = _t(_f(n, "scope"))
        kind = "self" if scope in ("self", "static") else "super" if scope == "parent" else "attr"
        return _site(_t(_f(n, "name")), n, kind, scope), _f(n, "name")
    if n.type == "object_creation_expression":
        target = next((c for c in n.named_children if c.type in ("name", "qualified_name")), None)
        return (_site(_last(_t(target)), n, "name"), target) if target is not None else None
    return None


def _php_import(n: Node) -> list[ImportRef]:
    line = n.start_point[0] + 1
    if n.type.startswith(("require", "include")):
        s = next((c for c in n.named_children if c.type in ("string", "encapsed_string")), None)
        return [ImportRef("./" + _t(s).strip("'\"").lstrip("./"), [], line)] if s is not None and "$" not in _t(s) and "." not in _t(s)[:1] else []
    text = " ".join(_t(n).replace(";", " ").split())
    text = re.sub(r"^use\s+(function\s+|const\s+)?", "", text)
    m = re.match(r"^(.*?)\\\{(.*)\}$", text)
    if m:
        return [ImportRef(m.group(1).replace("\\", "."), [((p.strip().split(" as ")[0]), (p.strip().split(" as ")[-1])) for p in m.group(2).split(",") if p.strip()], line)]
    full, _, alias = text.partition(" as ")
    module, _, name = full.strip().rpartition("\\")
    return [ImportRef(module.replace("\\", ".") or full, [(name, alias.strip() or name)] if module else [], line)]


PHP = Spec(
    class_types=frozenset({"class_declaration", "interface_declaration", "trait_declaration", "enum_declaration"}),
    func_types=frozenset({"function_definition", "method_declaration"}),
    call=_php_call, imports=_php_import,
    import_types=frozenset({"namespace_use_declaration", "require_expression", "require_once_expression", "include_expression", "include_once_expression"}),
    bases=lambda n: [_last(_t(c)) for c in n.children if c.type == "base_clause"][:1] and [_last(_t(next(c for c in n.children if c.type == "base_clause")).replace("extends", ""))] or [],
    exported=lambda n, name: not any(c.type == "visibility_modifier" and _t(c) in ("private", "protected") for c in n.children),
)


# ---- Kotlin (this grammar has no field names, so children are read by position) ----------------------


def _kt_first(n: Node, types: tuple[str, ...]) -> Node | None:
    return next((c for c in n.children if c.type in types), None)


def _kt_call(n: Node, selfs: frozenset[str]):
    if n.type != "call_expression" or not n.children:
        return None
    head = n.children[0]
    if head.type == "simple_identifier":
        return _site(_t(head), n, "name"), head
    if head.type == "navigation_expression" and head.children:
        suffix = head.children[-1]
        name = _kt_first(suffix, ("simple_identifier",))
        kind, recv = _kind_for_receiver(head.children[0], selfs)
        return (_site(_t(name), n, "attr" if kind == "name" else kind, recv), head) if name is not None else None
    return None


def _kt_import(n: Node) -> list[ImportRef]:
    text = re.sub(r"^import\s+", "", " ".join(_t(n).split()))
    text, _, alias = text.partition(" as ")
    if text.endswith(".*"):
        return [ImportRef(text[:-2], [("*", "*")], n.start_point[0] + 1)]
    module, _, name = text.rpartition(".")
    return [ImportRef(module or text, [(name, alias.strip() or name)] if module else [], n.start_point[0] + 1)]


KOTLIN = Spec(
    class_types=frozenset({"class_declaration", "object_declaration"}),
    func_types=frozenset({"function_declaration"}),
    call=_kt_call, imports=_kt_import, import_types=frozenset({"import_header"}),
    class_name=lambda n: _t(_kt_first(n, ("type_identifier", "simple_identifier"))) or None,
    func_name=lambda n: (_t(_kt_first(n, ("simple_identifier",))) or None, None),
    bases=lambda n: [_last(re.sub(r"\(.*", "", _t(c))) for c in n.children if c.type == "delegation_specifier"][:1],
    exported=lambda n, name: not any(c.type == "modifiers" and "private" in _t(c) for c in n.children),
    decorated=lambda n: any(c.type == "modifiers" and "@" in _t(c) for c in n.children),
)

SPECS: dict[str, Spec] = {
    "java": JAVA, "go": GO, "rust": RUST, "c": C, "cpp": CPP, "csharp": CSHARP, "ruby": RUBY, "php": PHP,
    "kotlin": KOTLIN,
}


# ---- the walker --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Ctx:
    owner: Symbol
    parent: str | None  # enclosing type, for methods
    parent_exported: bool
    prefix: str
    selfs: frozenset[str] = frozenset()


def extract(path: str, source: bytes, lang: str) -> tuple[list[Symbol], list[ImportRef], list[str], str | None]:
    """Returns (symbols, imports, value references, error). Never raises."""
    parser, reason = languages.get_parser(lang)
    if parser is None:
        return [], [], [], f"grammar unavailable: {reason}"
    try:
        root = parser.parse(source).root_node
    except Exception as exc:  # noqa: BLE001
        return [], [], [], f"{type(exc).__name__}: {exc}"
    spec = SPECS.get(lang)
    if spec is None:
        symbols = _basic(path, root)
        return symbols, [], [], ("syntax errors in file (partial result)" if root.has_error else None)

    symbols: list[Symbol] = []
    imports: list[ImportRef] = []
    refs: set[str] = set()
    skip: set[int] = set()
    seen_ids: set[str] = set()
    module = Symbol(f"{path}::<module>", "module", "<module>", "<module>", path, 1, 1)

    def new_symbol(kind: str, name: str, node: Node, qual: str, **extra) -> Symbol:
        sid = f"{path}::{qual}"
        if sid in seen_ids:
            sid = f"{sid}#{node.start_point[0] + 1}"
        seen_ids.add(sid)
        sym = Symbol(sid, kind, name, qual, path, node.start_point[0] + 1, node.end_point[0] + 1, **extra)
        symbols.append(sym)
        return sym

    stack: list[tuple[Node, _Ctx]] = [(root, _Ctx(module, None, True, ""))]
    while stack:
        node, ctx = stack.pop()
        t = node.type
        if t in COMMENTS:
            continue
        if t in spec.import_types:
            got = spec.imports(node)
            if got:
                imports.extend(got)
                continue
        if t in spec.impl_types:
            target = spec.impl_name(node)
            inner = replace(ctx, parent=target or ctx.parent, parent_exported=True)
            stack.extend((c, inner) for c in node.children)
            continue
        if t in spec.class_types and spec.class_ok(node):
            name = spec.class_name(node)
            if name:
                qual = f"{ctx.prefix}.{name}" if ctx.prefix else name
                exported = spec.exported(node, name)
                sym = new_symbol("class", name, node, qual, exported=exported, decorated=spec.decorated(node), bases=spec.bases(node))
                inner = _Ctx(sym, qual, exported, qual)
                stack.extend((c, inner) for c in node.children)
                continue
        if t in spec.func_types:
            name, parent = spec.func_name(node)
            if name:
                parent = parent or ctx.parent
                qual = f"{parent}.{name}" if parent else (f"{ctx.prefix}.{name}" if ctx.prefix else name)
                size, shape = _shape(node)
                exported = spec.exported(node, name) and (ctx.parent_exported if parent else True)
                sym = new_symbol(
                    "method" if parent else "function", name, node, qual, exported=exported,
                    decorated=spec.decorated(node), parent=parent, size=size, shape=shape,
                )
                inner = _Ctx(sym, None, True, qual, spec.self_names(node))
                name_node = _f(node, "name")
                if name_node is not None:
                    skip.add(name_node.id)
                stack.extend((c, inner) for c in node.children)
                continue
        got_call = spec.call(node, ctx.selfs)
        if got_call is not None:
            site, callee_node = got_call
            if site.callee:
                ctx.owner.calls.append(site)
            if callee_node is not None:
                skip.add(callee_node.id)
        if t in IDENT_TYPES and node.id not in skip:
            refs.add(_t(node))
        stack.extend((c, ctx) for c in node.children)

    if module.calls:
        symbols.append(module)
    for sym in symbols:
        sym.calls.sort(key=lambda c: c.line)
    return symbols, imports, sorted(r for r in refs if r), ("syntax errors in file (partial result)" if root.has_error else None)


# ---- basic: definitions only, for every other language -----------------------------------------------

_FUNC_RE = re.compile(r"^(function|method|procedure|subroutine|constructor|fun|func|fn|def)_?(declaration|definition|item|def|decl|statement|specification)?$")
_CLASS_RE = re.compile(r"^(class|struct|interface|trait|module|object|protocol|enum|record|namespace|type)_?(declaration|definition|item|specifier|def|decl)?$")


def _basic_name(node: Node) -> str | None:
    named = _f(node, "name")
    if named is not None:
        return _t(named) or None
    first = next((c for c in node.children if c.type in IDENT_TYPES), None)
    return _t(first) or None if first is not None else None


def _basic(path: str, root: Node) -> list[Symbol]:
    symbols: list[Symbol] = []
    seen: set[str] = set()
    stack: list[tuple[Node, str]] = [(root, "")]
    while stack:
        node, prefix = stack.pop()
        is_func = bool(_FUNC_RE.match(node.type))
        is_class = not is_func and bool(_CLASS_RE.match(node.type))
        name = _basic_name(node) if (is_func or is_class) else None
        child_prefix = prefix
        if name:
            qual = f"{prefix}.{name}" if prefix else name
            sid = f"{path}::{qual}"
            if sid in seen:
                sid = f"{sid}#{node.start_point[0] + 1}"
            seen.add(sid)
            size, shape = _shape(node) if is_func else (0, None)
            kind = "class" if is_class else ("method" if prefix else "function")
            symbols.append(Symbol(
                sid, kind, name, qual, path, node.start_point[0] + 1, node.end_point[0] + 1,
                exported=not prefix, parent=prefix or None if kind == "method" else None, size=size, shape=shape,
            ))
            child_prefix = qual
        stack.extend((c, child_prefix) for c in reversed(node.children))
    return symbols
