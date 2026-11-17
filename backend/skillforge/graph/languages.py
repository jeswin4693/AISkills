"""Which languages the graph understands, how deeply, and how to get a parser for each.

Levels (never claim more than the level says):
  full      Python, TypeScript, JavaScript: symbols, imports resolved to files, calls resolved by scope and imports.
  standard  Java, Go, Rust, C, C++, C#, Ruby, PHP, Kotlin: symbols, imports, calls; links are labelled resolved or guess.
  basic     any other language with a tree-sitter grammar: definitions (functions, classes) and duplicate detection,
            but no calls or imports.
Files in a language with no grammar are not parsed at all.

Grammars beyond Python and TypeScript/JavaScript come from the `tree-sitter-language-pack` package, which downloads
each native grammar the first time it is used and caches it. Set SKILLFORGE_OFFLINE=1 to forbid downloads: only
grammars already cached are then used.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import PurePosixPath
from typing import Any

FULL_LANGS = ("python", "typescript", "tsx", "javascript")
BUILT_IN = {"typescript", "tsx", "javascript"}  # grammars shipped as ordinary Python packages
STANDARD_LANGS = ("java", "go", "rust", "c", "cpp", "csharp", "ruby", "php", "kotlin")


@dataclass(frozen=True)
class Language:
    name: str
    level: str  # "full" | "standard" | "basic"
    extensions: tuple[str, ...]
    scope: str = "file"  # where a bare name may refer to something defined in another file: file | directory | global
    import_style: str = "none"  # how imports map to files: relative | dotted | go | rust | none


# Programming languages only (not data formats). Names are the grammar names used by tree-sitter-language-pack.
EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript", ".mts": "typescript", ".cts": "typescript", ".tsx": "tsx",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".java": "java", ".kt": "kotlin", ".kts": "kotlin", ".scala": "scala", ".groovy": "groovy",
    ".go": "go", ".rs": "rust",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp", ".hxx": "cpp",
    ".cs": "csharp", ".rb": "ruby", ".php": "php", ".swift": "swift", ".dart": "dart", ".lua": "lua",
    ".r": "r", ".jl": "julia", ".pl": "perl", ".pm": "perl",
    ".sh": "bash", ".bash": "bash", ".zsh": "bash", ".ps1": "powershell",
    ".hs": "haskell", ".ex": "elixir", ".exs": "elixir", ".erl": "erlang", ".clj": "clojure", ".ml": "ocaml",
    ".zig": "zig", ".sql": "sql", ".al": "al", ".sol": "solidity", ".nim": "nim", ".cob": "cobol",
    ".f90": "fortran", ".pas": "pascal", ".d": "d", ".cr": "crystal", ".gleam": "gleam", ".elm": "elm",
    ".v": "verilog", ".vhd": "vhdl", ".tcl": "tcl", ".vim": "vim", ".gd": "gdscript",
}

_SCOPE = {"java": "directory", "kotlin": "directory", "go": "directory", "csharp": "global", "c": "global",
          "cpp": "global", "ruby": "global", "php": "global", "rust": "file"}
_STYLE = {"java": "dotted", "kotlin": "dotted", "php": "dotted", "go": "go", "rust": "rust", "c": "relative",
          "cpp": "relative", "ruby": "relative", "csharp": "none"}


def level_of(name: str) -> str:
    return "full" if name in FULL_LANGS else "standard" if name in STANDARD_LANGS else "basic"


def language_of_path(path: str) -> str | None:
    """Grammar name for a file, from its extension; None when it is not a programming language we know."""
    name = PurePosixPath(path).name.lower()
    if name.endswith((".d.ts", ".min.js", ".min.mjs")):
        return None
    return EXTENSIONS.get(PurePosixPath(path).suffix.lower())


def info(name: str) -> Language:
    exts = tuple(sorted(e for e, n in EXTENSIONS.items() if n == name))
    return Language(name, level_of(name), exts, _SCOPE.get(name, "file"), _STYLE.get(name, "none"))


# ---- parsers -----------------------------------------------------------------------------------------


def offline() -> bool:
    return os.environ.get("SKILLFORGE_OFFLINE", "").strip().lower() not in ("", "0", "false", "no")


@lru_cache(maxsize=1)
def _pack() -> Any | None:
    try:
        import tree_sitter_language_pack as pack
    except ImportError:
        return None
    return pack


@lru_cache(maxsize=1)
def _manifest() -> frozenset[str]:
    pack = _pack()
    try:
        return frozenset(pack.manifest_languages()) if pack else frozenset()
    except Exception:  # noqa: BLE001
        return frozenset()


_parsers: dict[str, Any] = {}
_failures: dict[str, str] = {}


def get_parser(name: str) -> tuple[Any | None, str | None]:
    """(parser, None) or (None, why not). Never raises: a missing grammar degrades one language, not the run."""
    if name in _parsers:
        return _parsers[name], None
    if name in _failures:
        return None, _failures[name]
    parser: Any = None
    reason: str | None = None
    if name in BUILT_IN:
        from .extract_ts import _parser

        parser = _parser(name)
    else:
        pack = _pack()
        if pack is None:
            reason = "tree-sitter-language-pack is not installed"
        elif name not in _manifest():
            reason = f"the grammar pack has no grammar named '{name}'"
        elif offline() and name not in set(pack.downloaded_languages()):
            reason = "offline mode (SKILLFORGE_OFFLINE) and this grammar is not downloaded"
        else:
            try:
                parser = pack.get_parser(name)  # downloads the grammar on first use, then caches it
            except Exception as exc:  # noqa: BLE001
                reason = f"could not get the grammar ({type(exc).__name__}: {str(exc)[:80]})"
    if parser is None:
        _failures[name] = reason or "unknown problem"
        return None, _failures[name]
    _parsers[name] = parser
    return parser, None


def grammar_status(name: str) -> str:
    """For `skillforge languages`: built in / ready / downloads on first use / unavailable."""
    if name == "python":
        return "built in (standard library)"
    if name in BUILT_IN:
        return "built in"
    pack = _pack()
    if pack is None:
        return "unavailable (grammar pack not installed)"
    if name not in _manifest():
        return "unavailable (no such grammar)"
    if name in set(pack.downloaded_languages()):
        return "ready (cached)"
    return "unavailable offline" if offline() else "downloads on first use"


def parses_cleanly(source: bytes, name: str) -> bool | None:
    """True/False for syntax errors, None when no grammar is available. Nothing is executed."""
    parser, _ = get_parser(name)
    if parser is None:
        return None
    try:
        return not parser.parse(source).root_node.has_error
    except Exception:  # noqa: BLE001
        return False
