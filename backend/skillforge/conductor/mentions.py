"""Find the files and functions a prompt names, using the repository graph. No model.

A plain word is never taken for code: "build a skill" does not name the function `build`. Text counts as code only
when it is a path that exists, is written in backticks or with (), or has the shape of an identifier (snake_case,
camelCase, PascalCase, a.dotted.name). A name that matches several places is ambiguous: it is not measured, and the
plan asks which one is meant, instead of picking one.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..graph import query
from ..graph.model import RepoGraph, Symbol
from .models import Mention

MAX_MENTIONS = 20
MAX_OPTIONS = 5  # how many places an ambiguous name lists, so the question can offer them
_BACKTICK = re.compile(r"`([^`\n]{1,120})`")
_PATHISH = re.compile(r"[A-Za-z0-9_.\\-]+(?:[/\\][A-Za-z0-9_.\\-]+)+|[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*\.[A-Za-z0-9]{1,6}\b")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*(?:\(\))?")


def _code_shaped(token: str) -> bool:
    """snake_case, camelCase, PascalCase, a.dotted.name or name(): shapes that ordinary prose does not have."""
    bare = token.removesuffix("()")
    if token.endswith("()") or "_" in bare or "." in bare:
        return True
    return len(bare) > 1 and any(c.isupper() for c in bare[1:]) and any(c.islower() for c in bare)


def _candidates(text: str, extra: Iterable[str]) -> list[tuple[str, bool]]:
    """(text, certainly_code) in the order they appear, without repeats."""
    found: list[tuple[int, str, bool]] = []
    for m in _BACKTICK.finditer(text):
        found.append((m.start(), m.group(1).strip(), True))
    for m in _PATHISH.finditer(text):
        found.append((m.start(), m.group(0).rstrip(".,;:!?"), False))  # a path at the end of a sentence keeps no full stop
    for m in _IDENT.finditer(text):
        if _code_shaped(m.group(0)):
            found.append((m.start(), m.group(0), False))
    out: list[tuple[str, bool]] = []
    seen: set[str] = set()
    for _, token, sure in sorted(found, key=lambda f: f[0]):
        key = token.lower()
        if token and key not in seen:
            seen.add(key)
            out.append((token, sure))
    for token in extra:
        token = token.strip()
        if token and token.lower() not in seen:
            seen.add(token.lower())
            out.append((token, True))
    return out


def _looks_like_file(token: str) -> bool:
    t = token.replace("\\", "/")
    return "::" not in t and ("/" in t or "." in t.rsplit("/", 1)[-1])


def _files_ending_with(g: RepoGraph, token: str) -> list[str]:
    """The files a bare name such as `pipeline.py` could mean. Test files count only when no source file matches."""
    t = token.strip().replace("\\", "/").removeprefix("./")
    found = sorted(p for p in g.files if p.endswith("/" + t))
    source = [p for p in found if not g.files[p].is_test]
    return source or found


def _pick(g: RepoGraph, found: list[Symbol]) -> Symbol | None:
    """One symbol, or None when it is not one: several matches count as one only if exactly one is not test code."""
    if len(found) == 1:
        return found[0]
    non_test = [s for s in found if not g.files[s.file].is_test]
    return non_test[0] if len(non_test) == 1 else None


def find_mentions(g: RepoGraph, text: str, extra: Iterable[str] = (), source: str = "prompt") -> list[Mention]:
    """The files and functions that `text` names. `extra` are names a model claims the person wrote: they count only if
    they really match something in the graph, like everything else."""
    out: list[Mention] = []
    taken: set[str] = set()  # one mention per thing: `a/b.py` and `b.py` are the same file

    for token, sure in _candidates(text, extra):
        if len(out) >= MAX_MENTIONS:
            break
        if _looks_like_file(token):
            path = query.find_file(g, token)
            if path:
                if path not in taken:
                    taken.add(path)
                    out.append(Mention(kind="file", text=token, target=path, file=path, line=None, candidates=1, ambiguous=False, source=source))  # type: ignore[arg-type]
                continue
            several = _files_ending_with(g, token)
            if len(several) == 1:  # one source file and, say, a test with the same name: the source file is meant
                if several[0] not in taken:
                    taken.add(several[0])
                    out.append(Mention(kind="file", text=token, target=several[0], file=several[0], line=None, candidates=1, ambiguous=False, source=source))  # type: ignore[arg-type]
                continue
            if len(several) > 1:  # `pipeline.py` when two folders have one: not measured, and the person is asked which
                if token not in taken:
                    taken.add(token)
                    out.append(Mention(
                        kind="file", text=token, target="", file="", line=None, candidates=len(several), ambiguous=True,
                        source=source, options=several[:MAX_OPTIONS],  # type: ignore[arg-type]
                    ))
                continue
        name = token.removesuffix("()")
        if not sure and not _code_shaped(token):
            continue
        found = query.find_symbols(g, name)
        if not found:
            continue
        one = _pick(g, found)
        if one is not None:
            if one.id not in taken:
                taken.add(one.id)
                out.append(Mention(kind="symbol", text=token, target=one.id, file=one.file, line=one.line, candidates=1, ambiguous=False, source=source))  # type: ignore[arg-type]
        else:
            out.append(Mention(
                kind="symbol", text=token, target="", file="", line=None, candidates=len(found), ambiguous=True, source=source,  # type: ignore[arg-type]
                options=[s.id for s in found][:MAX_OPTIONS],
            ))
    return out
