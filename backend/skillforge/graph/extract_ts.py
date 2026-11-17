"""Extract symbols, imports and call sites from TypeScript / JavaScript with tree-sitter."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace

import tree_sitter_javascript as _js
import tree_sitter_typescript as _ts
from tree_sitter import Language, Node, Parser

from .model import CallSite, ImportRef, Symbol

_PARSERS: dict[str, Parser] = {}


def _parser(lang: str) -> Parser:
    if lang not in _PARSERS:
        language = {
            "typescript": _ts.language_typescript,
            "tsx": _ts.language_tsx,
            "javascript": _js.language,
        }[lang]()
        _PARSERS[lang] = Parser(Language(language))
    return _PARSERS[lang]


def parses_cleanly(source: bytes, lang: str) -> bool:
    """True when the source has no syntax errors. Nothing is executed."""
    try:
        return not _parser(lang).parse(source).root_node.has_error
    except Exception:  # noqa: BLE001 - an unparseable file is simply "not clean"
        return False


FUNC_VALUES = {"arrow_function", "function_expression", "function", "generator_function"}
FUNC_DECLS = {"function_declaration", "generator_function_declaration"}
CLASS_DECLS = {"class_declaration", "abstract_class_declaration"}
REF_TYPES = {"identifier", "property_identifier", "shorthand_property_identifier"}
DECL_PARENTS = {
    "function_declaration", "generator_function_declaration", "class_declaration", "abstract_class_declaration",
    "method_definition", "variable_declarator", "public_field_definition", "field_definition",
}
NON_USE_PARENTS = {
    "import_specifier", "export_specifier", "namespace_import", "import_clause", "required_parameter",
    "optional_parameter", "import_require_clause", "namespace_export",
}
_EXTENDS = re.compile(r"\bextends\s+([A-Za-z_$][\w$.]*)")


@dataclass(frozen=True)
class _Ctx:
    owner: Symbol  # who the calls found here belong to
    cls: Symbol | None  # the class whose body we are directly in
    prefix: str  # qualified name prefix
    exported: bool


def _text(node: Node | None) -> str:
    return node.text.decode("utf-8", "replace") if node is not None and node.text is not None else ""


def _string_value(node: Node | None) -> str | None:
    if node is None or node.type not in ("string", "template_string"):
        return None
    raw = _text(node)
    if len(raw) >= 2 and raw[0] in "'\"`" and raw[-1] == raw[0]:
        return raw[1:-1]
    return raw


def _chain(node: Node | None) -> str | None:
    """`a`, `a.b.c` for a chain of plain names; None for anything else."""
    parts: list[str] = []
    while node is not None and node.type == "member_expression":
        prop = node.child_by_field_name("property")
        if prop is None:
            return None
        parts.append(_text(prop))
        node = node.child_by_field_name("object")
    if node is not None and node.type in ("identifier", "this"):
        parts.append(_text(node))
        return ".".join(reversed(parts))
    return None


def _shape(node: Node) -> tuple[int, str]:
    tokens: list[str] = []
    stack: list[tuple[Node, int]] = [(node, 0)]
    while stack:
        n, depth = stack.pop()
        if n.type == "comment":
            continue
        tokens.append(f"{depth}{n.type}")
        stack.extend((c, depth + 1) for c in reversed(n.children))
    return len(tokens), hashlib.sha1(",".join(tokens).encode()).hexdigest()[:16]


def _is_value_ref(node: Node) -> bool:
    """True when an identifier is a use of a name as a value, not a declaration, import, or call target."""
    p = node.parent
    if p is None:
        return True
    pt = p.type
    if pt in NON_USE_PARENTS:
        return False
    if pt in DECL_PARENTS and p.child_by_field_name("name") == node:
        return False
    if pt in ("public_field_definition", "field_definition") and p.child_by_field_name("property") == node:
        return False
    if pt == "call_expression" and p.child_by_field_name("function") == node:
        return False
    if pt == "member_expression" and p.child_by_field_name("property") == node:
        gp = p.parent
        if gp is not None and gp.type == "call_expression" and gp.child_by_field_name("function") == p:
            return False
    return True


def extract(path: str, source: bytes, lang: str) -> tuple[list[Symbol], list[ImportRef], list[str], str | None]:
    """Returns (symbols, imports, value references, error)."""
    try:
        tree = _parser(lang).parse(source)
    except Exception as exc:  # noqa: BLE001 - a parser failure must not stop the whole scan
        return [], [], [], f"{type(exc).__name__}: {exc}"
    root = tree.root_node

    symbols: list[Symbol] = []
    imports: list[ImportRef] = []
    refs: set[str] = set()
    exported_names: set[str] = set()
    seen_ids: set[str] = set()
    module = Symbol(f"{path}::<module>", "module", "<module>", "<module>", path, 1, 1)

    def new_symbol(kind: str, name: str, node: Node, ctx: _Ctx, **extra) -> Symbol:
        qual = f"{ctx.prefix}.{name}" if ctx.prefix else name
        sid = f"{path}::{qual}"
        if sid in seen_ids:
            sid = f"{sid}#{node.start_point[0] + 1}"
        seen_ids.add(sid)
        sym = Symbol(sid, kind, name, qual, path, node.start_point[0] + 1, node.end_point[0] + 1, **extra)
        symbols.append(sym)
        return sym

    def function_symbol(kind: str, name: str, node: Node, ctx: _Ctx, exported: bool, decorated: bool) -> Symbol:
        size, shape = _shape(node)
        parent = ctx.cls.qualname if kind == "method" and ctx.cls else None
        return new_symbol(
            kind, name, node, ctx, exported=exported, decorated=decorated, parent=parent, size=size, shape=shape
        )

    def require_import(call: Node, module_name: str) -> None:
        names: list[tuple[str, str]] = []
        decl = call.parent
        if decl is not None and decl.type == "variable_declarator" and decl.child_by_field_name("value") == call:
            target = decl.child_by_field_name("name")
            if target is not None and target.type == "identifier":
                names.append(("", _text(target)))
            elif target is not None and target.type == "object_pattern":
                for c in target.named_children:
                    if c.type == "shorthand_property_identifier_pattern":
                        names.append((_text(c), _text(c)))
                    elif c.type == "pair_pattern":
                        names.append((_text(c.child_by_field_name("key")), _text(c.child_by_field_name("value"))))
        imports.append(ImportRef(module_name, names, call.start_point[0] + 1))

    def handle_import(node: Node) -> None:
        module_name = _string_value(node.child_by_field_name("source"))
        names: list[tuple[str, str]] = []
        for c in node.children:
            if c.type == "import_clause":
                for part in c.children:
                    if part.type == "identifier":
                        names.append(("default", _text(part)))
                    elif part.type == "namespace_import":
                        ident = next((x for x in part.children if x.type == "identifier"), None)
                        names.append(("", _text(ident)))
                    elif part.type == "named_imports":
                        for spec in part.named_children:
                            name = spec.child_by_field_name("name")
                            alias = spec.child_by_field_name("alias")
                            names.append((_text(name), _text(alias or name)))
            elif c.type == "import_require_clause":
                module_name = module_name or _string_value(next((x for x in c.children if x.type == "string"), None))
                ident = next((x for x in c.children if x.type == "identifier"), None)
                names.append(("", _text(ident)))
        if module_name is not None:
            imports.append(ImportRef(module_name, names, node.start_point[0] + 1))

    def handle_export(node: Node, ctx: _Ctx, stack: list[tuple[Node, _Ctx]]) -> None:
        source_node = node.child_by_field_name("source")
        if source_node is not None:  # `export ... from "./x"` is a dependency and a re-export
            names: list[tuple[str, str]] = []
            for c in node.children:
                if c.type == "export_clause":
                    for spec in c.named_children:
                        name = spec.child_by_field_name("name")
                        alias = spec.child_by_field_name("alias")
                        names.append((_text(name), _text(alias or name)))
                elif c.type == "namespace_export":
                    ident = next((x for x in c.children if x.type == "identifier"), None)
                    names.append(("", _text(ident)))
            if not names and any(c.type == "*" for c in node.children):
                names.append(("*", "*"))
            module_name = _string_value(source_node)
            if module_name is not None:
                imports.append(ImportRef(module_name, names, node.start_point[0] + 1))
            return
        for c in node.children:
            if c.type == "export_clause":
                for spec in c.named_children:
                    exported_names.add(_text(spec.child_by_field_name("name")))
            else:
                if c.type == "identifier" and node.child_by_field_name("value") == c:
                    exported_names.add(_text(c))  # export default foo
                stack.append((c, replace(ctx, exported=True)))

    def handle_call(node: Node, ctx: _Ctx, stack: list[tuple[Node, _Ctx]]) -> None:
        fn = node.child_by_field_name("function")
        site: CallSite | None = None
        line = node.start_point[0] + 1
        skip = None
        if fn is not None and fn.type == "identifier":
            name = _text(fn)
            site = CallSite(name, line, "name")
            skip = fn
            if name == "require":
                arg = next((a for a in (node.child_by_field_name("arguments") or node).named_children), None)
                module_name = _string_value(arg)
                if module_name is not None:
                    require_import(node, module_name)
        elif fn is not None and fn.type == "member_expression":
            obj = fn.child_by_field_name("object")
            prop = fn.child_by_field_name("property")
            if prop is not None and prop.type in ("property_identifier", "private_property_identifier"):
                if obj is not None and obj.type == "this":
                    site = CallSite(_text(prop), line, "self", "this")
                elif obj is not None and obj.type == "super":
                    site = CallSite(_text(prop), line, "super", "super")
                else:
                    site = CallSite(_text(prop), line, "attr", _chain(obj))
            skip = fn
            if obj is not None:
                stack.append((obj, ctx))
        elif fn is not None and fn.type == "import":
            arg = next((a for a in (node.child_by_field_name("arguments") or node).named_children), None)
            module_name = _string_value(arg)
            if module_name is not None:
                imports.append(ImportRef(module_name, [], line))
            skip = fn
        if site is not None:
            ctx.owner.calls.append(site)
        for c in node.children:
            if skip is not None and c == skip:
                continue
            stack.append((c, ctx))

    def handle_new(node: Node, ctx: _Ctx, stack: list[tuple[Node, _Ctx]]) -> None:
        ctor = node.child_by_field_name("constructor")
        line = node.start_point[0] + 1
        skip = None
        if ctor is not None and ctor.type == "identifier":
            ctx.owner.calls.append(CallSite(_text(ctor), line, "name"))
            skip = ctor
        elif ctor is not None and ctor.type == "member_expression":
            prop = ctor.child_by_field_name("property")
            if prop is not None:
                ctx.owner.calls.append(CallSite(_text(prop), line, "attr", _chain(ctor.child_by_field_name("object"))))
            skip = ctor
            obj = ctor.child_by_field_name("object")
            if obj is not None:
                stack.append((obj, ctx))
        for c in node.children:
            if skip is not None and c == skip:
                continue
            stack.append((c, ctx))

    ctx0 = _Ctx(owner=module, cls=None, prefix="", exported=False)
    stack: list[tuple[Node, _Ctx]] = [(root, ctx0)]
    while stack:
        node, ctx = stack.pop()
        t = node.type
        if t == "comment":
            continue
        if t in REF_TYPES:
            if _is_value_ref(node):
                refs.add(_text(node))
            continue
        if t == "import_statement":
            handle_import(node)
            continue
        if t == "export_statement":
            handle_export(node, ctx, stack)
            continue
        if t == "call_expression":
            handle_call(node, ctx, stack)
            continue
        if t == "new_expression":
            handle_new(node, ctx, stack)
            continue

        if t in FUNC_DECLS:
            name = _text(node.child_by_field_name("name"))
            if name:
                sym = function_symbol("function", name, node, ctx, ctx.exported and not ctx.prefix, False)
                inner = _Ctx(sym, None, sym.qualname, False)
                stack.extend((c, inner) for c in node.children)
                continue
        elif t in CLASS_DECLS:
            name = _text(node.child_by_field_name("name"))
            if name:
                heritage = next((c for c in node.children if c.type == "class_heritage"), None)
                m = _EXTENDS.search(_text(heritage)) if heritage is not None else None
                sym = new_symbol(
                    "class", name, node, ctx, exported=ctx.exported and not ctx.prefix,
                    decorated=any(c.type == "decorator" for c in node.children),
                    bases=[m.group(1)] if m else [],
                )
                inner = _Ctx(sym, sym, sym.qualname, False)
                stack.extend((c, inner) for c in node.children)
                continue
        elif t == "method_definition" and ctx.cls is not None:
            name_node = node.child_by_field_name("name")
            name = _string_value(name_node) if name_node is not None and name_node.type == "string" else _text(name_node)
            if name and name_node is not None and name_node.type != "computed_property_name":
                private = name.startswith("#") or any(
                    c.type == "accessibility_modifier" and _text(c) in ("private", "protected") for c in node.children
                )
                sym = function_symbol(
                    "method", name, node, ctx, ctx.cls.exported and not private and not name.startswith("_"),
                    any(c.type == "decorator" for c in node.children),
                )
                inner = _Ctx(sym, None, sym.qualname, False)
                stack.extend((c, inner) for c in node.children)
                continue
        elif t in ("public_field_definition", "field_definition") and ctx.cls is not None:
            name_node = node.child_by_field_name("name") or node.child_by_field_name("property")
            value = node.child_by_field_name("value")
            if name_node is not None and value is not None and value.type in FUNC_VALUES:
                name = _text(name_node)
                private = name.startswith("#") or any(
                    c.type == "accessibility_modifier" and _text(c) in ("private", "protected") for c in node.children
                )
                sym = function_symbol(
                    "method", name, node, ctx, ctx.cls.exported and not private and not name.startswith("_"), False
                )
                inner = _Ctx(sym, None, sym.qualname, False)
                stack.extend((c, inner) for c in node.children)
                continue
        elif t in ("jsx_self_closing_element", "jsx_opening_element"):
            tag = node.child_by_field_name("name")  # <Button /> uses the component Button like a call
            if tag is not None and tag.type == "identifier" and _text(tag)[:1].isupper():
                ctx.owner.calls.append(CallSite(_text(tag), node.start_point[0] + 1, "name"))
        elif t == "variable_declarator":
            name_node = node.child_by_field_name("name")
            value = node.child_by_field_name("value")
            if name_node is not None and name_node.type == "identifier" and value is not None and value.type in FUNC_VALUES:
                sym = function_symbol("function", _text(name_node), node, ctx, ctx.exported and not ctx.prefix, False)
                inner = _Ctx(sym, None, sym.qualname, False)
                stack.extend((c, inner) for c in node.children)
                continue
        stack.extend((c, ctx) for c in node.children)

    if module.calls:
        symbols.append(module)
    for sym in symbols:
        if sym.qualname in exported_names and sym.kind != "module":
            sym.exported = True
        sym.calls.sort(key=lambda c: c.line)
    error = "syntax errors in file (partial result)" if root.has_error else None
    return symbols, imports, sorted(refs), error
