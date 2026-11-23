"""Static checks on a skill folder: structure, hidden text, suspicious wording, scripts and their capabilities.

Nothing here executes anything. Checks that rest on patterns report `warning`, not `failed`: a pattern is not
understanding, so a person has to read the finding. A skill that passes is not thereby safe.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Callable, Mapping
from pathlib import Path, PurePosixPath

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from ..evidence.model import EVIDENCE_FILE, EvidenceError, read_evidence
from ..graph import languages
from ..results import FAILED, NOT_RUN, PASSED, WARNING, CheckResult
from .formats import SKILL_FORMAT_CHECKED_ON, SKILL_FRONT_MATTER_KEYS

MAX_FILE = 1_000_000
MAX_TOTAL = 5_000_000
MAX_SKILL_MD = 100_000
MAX_DESCRIPTION = 1024
MAX_NAME = 64  # the longest skill name the checks, the library and the kinds all accept
SLUG = re.compile(r"^(?!(?:con|prn|aux|nul|com[1-9]|lpt[1-9])\Z)[a-z0-9]+(?:-[a-z0-9]+)*\Z")

TEXT_SUFFIXES = {".md", ".json", ".txt", ".yaml", ".yml", ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".toml", ".cfg", ".ini", ".csv"}
PY_SUFFIXES = {".py", ".pyw"}  # .pyw is Python too (Windows runs it without a console, and imports it)
JS_LANGS = {".ts": "typescript", ".mts": "typescript", ".cts": "typescript", ".tsx": "tsx", ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript"}
BINARY_SUFFIXES = {".exe", ".dll", ".so", ".dylib", ".bin", ".jar", ".class", ".pyc", ".msi", ".app", ".o", ".a"}
SHELL_SUFFIXES = {".sh", ".bash", ".zsh", ".bat", ".cmd", ".ps1"}

# Characters that hide or reorder text: invisible to a human reader, read by the model.
_HIDDEN_RANGES = [(0x200B, 0x200F), (0x202A, 0x202E), (0x2060, 0x2064), (0x2066, 0x2069), (0xE0000, 0xE007F)]
_JOINERS = {0x200C, 0x200D}  # legitimate between non-ASCII characters (emoji, Indic scripts)

SUSPICIOUS = [
    ("tells the agent to ignore its instructions",
     re.compile(r"\b(ignore|disregard|forget)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|any|system)\b[^.\n]{0,30}\b(instructions?|rules?|prompts?|guidelines?)\b", re.I)),
    ("pipes a download into a shell", re.compile(r"\b(curl|wget)\b[^\n|]*\|\s*(sudo\s+)?(ba|z)?sh\b", re.I)),
    ("decodes and runs a hidden payload", re.compile(r"base64\s+(-d|--decode)[^\n]*\|\s*(ba|z)?sh|\beval\s*\(\s*(atob|base64)", re.I)),
    ("deletes the filesystem root or home", re.compile(r"\brm\s+-[a-z]*r[a-z]*f?[a-z]*\s+(/|~|\$HOME)(\s|$)", re.I)),
    ("asks to send secrets to another place",
     re.compile(r"\b(send|upload|post|exfiltrate|transmit)\b[^.\n]{0,60}\b(credentials?|api[ _-]?keys?|tokens?|passwords?|secrets?|ssh keys?|\.env)\b[^.\n]{0,60}\b(to|at)\b\s+(https?://|an?\s+(remote|external))", re.I)),
    ("tells the agent to disable safety or approval", re.compile(r"\b(disable|turn off|bypass)\b[^.\n]{0,30}\b(safety|security|confirmation|permission|approval|sandbox)\b", re.I)),
]

NETWORK_MODULES = {"socket", "requests", "httpx", "urllib.request", "urllib3", "http.client", "http.server", "ftplib", "smtplib", "aiohttp", "websockets", "telnetlib", "xmlrpc.client"}
COMMAND_MODULES = {"subprocess", "pty", "multiprocessing"}
WRITE_CALLS = {"os.remove", "os.unlink", "os.rmdir", "os.rename", "os.replace", "os.makedirs", "os.mkdir", "shutil.rmtree", "shutil.copy", "shutil.copyfile", "shutil.move", "shutil.copytree"}
WRITE_METHODS = {"write_text", "write_bytes", "mkdir", "unlink", "rmdir", "rename", "touch"}

_JS_CAPS = {
    "run_commands": re.compile(r"child_process"),
    "network": re.compile(r"\bfetch\s*\(|from\s+['\"](node:)?(https?|net|tls|dgram|http2)['\"]|require\(\s*['\"](node:)?(https?|net|tls|dgram|http2|axios|node-fetch|got)['\"]|from\s+['\"](axios|node-fetch|got|ws)['\"]|XMLHttpRequest|WebSocket"),
    "write_files": re.compile(r"\bfs\.(promises\.)?(writeFile|writeFileSync|appendFile|appendFileSync|unlink|unlinkSync|rm|rmSync|rmdir|mkdir|mkdirSync|rename|copyFile)\b"),
}
_JS_DYNAMIC = re.compile(r"\beval\s*\(|new\s+Function\s*\(")


def read_dir(root: Path) -> tuple[dict[str, bytes], list[tuple[str, str]]]:
    """Read a folder into memory. Returns (files, problems) where problems are (kind, message)."""
    root = root.resolve()
    files: dict[str, bytes] = {}
    problems: list[tuple[str, str]] = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if p.is_symlink():
            problems.append(("symlink", f"{rel} is a symbolic link"))
        elif p.is_file():
            try:
                size = p.stat().st_size
                if size > MAX_FILE:
                    problems.append(("size", f"{rel} is {size} bytes (limit {MAX_FILE})"))
                    continue
                files[rel] = p.read_bytes()
            except OSError as exc:
                problems.append(("unreadable", f"{rel}: {exc}"))
    return files, problems


def _text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace").replace("\r\n", "\n")


def _loc(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


# ---- individual checks -------------------------------------------------------------------------------


def _check_skill_md(files: Mapping[str, bytes], folder: str | None) -> list[CheckResult]:
    name = "SKILL.md exists and its front matter is valid"
    if "SKILL.md" not in files:
        return [CheckResult(name, FAILED, "there is no SKILL.md at the top of the folder")]
    try:
        text = files["SKILL.md"].decode("utf-8").replace("\r\n", "\n")
    except UnicodeDecodeError:
        return [CheckResult(name, FAILED, "SKILL.md is not valid UTF-8")]
    match = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        return [CheckResult(name, FAILED, "SKILL.md has no front matter between --- lines")]
    try:
        meta = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        return [CheckResult(name, FAILED, f"front matter is not valid YAML: {exc}")]
    problems: list[str] = []
    if not isinstance(meta, dict):
        problems.append("front matter is not a set of key: value pairs")
    else:
        skill_name, desc = meta.get("name"), meta.get("description")
        if not isinstance(skill_name, str) or not SLUG.match(skill_name) or len(skill_name) > MAX_NAME:
            problems.append(f"name must be lowercase letters, digits and hyphens, at most {MAX_NAME} characters")
        if not isinstance(desc, str) or not desc.strip():
            problems.append("description is missing or empty")
        elif len(" ".join(desc.split())) > MAX_DESCRIPTION:
            problems.append(f"description is longer than {MAX_DESCRIPTION} characters")
    out = [CheckResult(name, FAILED, "; ".join(problems)) if problems else CheckResult(name, PASSED)]
    if isinstance(meta, dict):
        out.append(_check_front_matter_keys(meta))
    if folder is not None and isinstance(meta, dict) and isinstance(meta.get("name"), str) and meta["name"] != folder:
        out.append(CheckResult("folder name matches the skill name", WARNING, f"folder '{folder}' but name is '{meta['name']}'"))
    elif folder is not None:
        out.append(CheckResult("folder name matches the skill name", PASSED))
    return out


def _check_front_matter_keys(meta: dict) -> CheckResult:
    """A key that Claude Code does not know is ignored by it without a word, so a typo (`allowed_tools`) would quietly
    do nothing. A warning, never a failure: a newer Claude Code may know the key (see validate/formats.py)."""
    name = "front matter uses only keys Claude Code knows"
    unknown = sorted(str(key) for key in meta if key not in SKILL_FRONT_MATTER_KEYS)
    if not unknown:
        return CheckResult(name, PASSED)
    return CheckResult(
        name, WARNING,
        f"not in the list of keys Claude Code knows (read {SKILL_FORMAT_CHECKED_ON}): {', '.join(unknown)}. "
        "Claude Code ignores such a key without saying so; a newer version may know it.",
    )


def _check_paths_and_size(files: Mapping[str, bytes], problems: list[tuple[str, str]]) -> list[CheckResult]:
    bad = [msg for kind, msg in problems if kind in ("symlink", "duplicate")]  # a repeated name: which copy would an agent read?
    for rel in files:
        parts = PurePosixPath(rel).parts
        if ".." in parts or rel.startswith("/") or "\\" in rel or re.match(r"^[A-Za-z]:", rel):
            bad.append(f"{rel} points outside the folder")
        elif any(part != part.rstrip(" .") or ":" in part for part in parts):
            # Windows drops a trailing dot or space (`server.py.` IS `server.py`) and reads `name:stream` as a hidden stream of `name`: the checks
            # would look at one file while another is run
            bad.append(f"{rel} has a name Windows reads as another file (a trailing dot or space, or a colon)")
    paths = CheckResult("no symbolic links or paths that leave the folder", FAILED, "; ".join(bad)) if bad else CheckResult("no symbolic links or paths that leave the folder", PASSED)

    sizes = [msg for kind, msg in problems if kind == "size"] + [msg for kind, msg in problems if kind == "unreadable"]
    total = sum(len(b) for b in files.values())
    if total > MAX_TOTAL:
        sizes.append(f"the folder holds {total} bytes (limit {MAX_TOTAL})")
    if "SKILL.md" in files and len(files["SKILL.md"]) > MAX_SKILL_MD:
        sizes.append(f"SKILL.md is {len(files['SKILL.md'])} bytes (limit {MAX_SKILL_MD})")
    size = CheckResult("file sizes are within limits", FAILED, "; ".join(sizes)) if sizes else CheckResult("file sizes are within limits", PASSED, f"{len(files)} files, {total} bytes")
    return [paths, size]


def _is_hidden(cp: int) -> bool:
    return any(lo <= cp <= hi for lo, hi in _HIDDEN_RANGES)


def _check_hidden_characters(files: Mapping[str, bytes]) -> CheckResult:
    name = "no hidden or direction-changing characters in text files"
    found: list[str] = []
    for rel, data in files.items():
        if PurePosixPath(rel).suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = _text(data)
        for i, ch in enumerate(text):
            cp = ord(ch)
            if cp in _JOINERS:
                before = ord(text[i - 1]) if i > 0 else 0
                after = ord(text[i + 1]) if i + 1 < len(text) else 0
                if before > 127 and after > 127:
                    continue
            if _is_hidden(cp) or (cp == 0xFEFF and i > 0):
                found.append(f"{rel}:{_loc(text, i)} (U+{cp:04X})")
    return CheckResult(name, FAILED, "found at " + ", ".join(found[:5]) + (f" and {len(found) - 5} more" if len(found) > 5 else "")) if found else CheckResult(name, PASSED)


def markup_findings(files: Mapping[str, bytes]) -> list[tuple[str, str, int]]:
    """(file, the markup found, line) for each HTML comment or script-like tag in a Markdown file."""
    found: list[tuple[str, str, int]] = []
    for rel, data in files.items():
        if PurePosixPath(rel).suffix.lower() != ".md":
            continue
        text = _text(data)
        for m in re.finditer(r"<!--|<\s*(script|iframe|object|embed)\b", text, re.I):
            found.append((rel, m.group(0).strip(), _loc(text, m.start())))
    return found


def wording_findings(files: Mapping[str, bytes]) -> list[tuple[str, str, int]]:
    """(file, what the wording matches, line): the first match of each attack-like pattern, in each text file."""
    found: list[tuple[str, str, int]] = []
    for rel, data in files.items():
        if PurePosixPath(rel).suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = _text(data)
        for label, pattern in SUSPICIOUS:
            m = pattern.search(text)
            if m:
                found.append((rel, label, _loc(text, m.start())))
    return found


def _check_markup_and_wording(files: Mapping[str, bytes]) -> list[CheckResult]:
    markup = [f"{rel}:{line} ({what})" for rel, what, line in markup_findings(files)]
    wording = [f"{rel}:{line} {label}" for rel, label, line in wording_findings(files)]
    return [
        CheckResult("no hidden markup (HTML comments, script tags) in Markdown", WARNING, "found at " + ", ".join(markup[:5]) + ". Comments are invisible when the page is rendered, but an agent still reads them.") if markup else CheckResult("no hidden markup (HTML comments, script tags) in Markdown", PASSED),
        CheckResult("no wording that matches known attack patterns", WARNING, "; ".join(wording[:5]) + ". These are patterns, not understanding: read the lines, they may be harmless.") if wording else CheckResult("no wording that matches known attack patterns", PASSED, "a pattern check only; passing is not proof of safety"),
    ]


def _check_json(files: Mapping[str, bytes]) -> CheckResult:
    name = "JSON files parse and schemas are valid JSON Schema"
    problems: list[str] = []
    count = 0
    for rel, data in files.items():
        if PurePosixPath(rel).suffix.lower() != ".json":
            continue
        count += 1
        try:
            doc = json.loads(data.decode("utf-8"))
        except RecursionError:
            problems.append(f"{rel}: nested too deeply to read")  # a hostile file is a failed check, not a crash
            continue
        except (UnicodeDecodeError, ValueError) as exc:
            problems.append(f"{rel}: not valid JSON ({exc})")
            continue
        if rel.startswith("schemas/"):
            try:
                Draft202012Validator.check_schema(doc)
            except SchemaError as exc:
                problems.append(f"{rel}: not a valid JSON Schema ({exc.message})")
        if rel == "tests/cases.json" and not isinstance(doc, list):
            problems.append("tests/cases.json must be a list of test cases")
    return CheckResult(name, FAILED, "; ".join(problems)) if problems else CheckResult(name, PASSED, f"{count} JSON file(s)")


def _check_evidence(files: Mapping[str, bytes]) -> list[CheckResult]:
    """Only for a folder that has an evidence.json (a row for every skill would change every report): it must be data that
    the strict reader accepts. What it says about a repository is not checked here: that is `library recheck`."""
    if EVIDENCE_FILE not in files:
        return []
    name = f"{EVIDENCE_FILE} is well-formed evidence"
    try:
        ev = read_evidence(files)
    except EvidenceError as exc:
        return [CheckResult(name, FAILED, str(exc))]
    count = len(ev.refs) if ev else 0
    return [CheckResult(name, PASSED, f"{count} place{'' if count == 1 else 's'} cited from '{ev.repo if ev else ''}'")]


def _scripts(files: Mapping[str, bytes]) -> dict[str, bytes]:
    return {rel: data for rel, data in files.items() if rel.startswith("scripts/")}


def _check_scripts_parse(files: Mapping[str, bytes]) -> CheckResult:
    name = "scripts parse without syntax errors"
    scripts = _scripts(files)
    if not scripts:
        return CheckResult(name, PASSED, "this skill has no scripts")
    failed: list[str] = []
    unchecked: list[str] = []
    for rel, data in scripts.items():
        suffix = PurePosixPath(rel).suffix.lower()
        if suffix in PY_SUFFIXES:
            try:
                ast.parse(_text(data), filename=rel)
            except (SyntaxError, ValueError, RecursionError) as exc:
                failed.append(f"{rel}: {type(exc).__name__}")
        else:  # any language with a grammar: Java, Go, Rust, C, C++, C#, Ruby, PHP, Kotlin, Bash, ...
            lang = languages.language_of_path(rel)
            clean = languages.parses_cleanly(data, lang) if lang else None
            if clean is False:
                failed.append(f"{rel}: syntax errors")
            elif clean is None:
                unchecked.append(rel)
    if failed:
        return CheckResult(name, FAILED, "; ".join(failed))
    if unchecked:
        return CheckResult(name, WARNING, "cannot be checked (no grammar for this type, or it could not be loaded): " + ", ".join(unchecked))
    return CheckResult(name, PASSED, f"{len(scripts)} script(s) parsed; nothing was run")


def _check_script_references(files: Mapping[str, bytes]) -> CheckResult:
    name = "every script that SKILL.md mentions exists"
    if "SKILL.md" not in files:
        return CheckResult(name, PASSED, "no SKILL.md to read")
    mentioned = set(re.findall(r"\bscripts/[A-Za-z0-9_./-]+\.[A-Za-z0-9]+", _text(files["SKILL.md"])))
    missing = sorted(m for m in mentioned if m not in files)
    return CheckResult(name, FAILED, "missing: " + ", ".join(missing)) if missing else CheckResult(name, PASSED, f"{len(mentioned)} mentioned")


def _dotted(node: ast.AST) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def python_capabilities(source: str) -> tuple[set[str], set[str]]:
    """(capabilities used, dynamic-code findings) for a Python script, by syntax only."""
    caps: set[str] = set()
    dynamic: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        candidates: list[str] = []
        if isinstance(node, ast.Import):
            candidates = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            candidates = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
        for cand in candidates:
            if any(cand == m or cand.startswith(m + ".") for m in COMMAND_MODULES):
                caps.add("run_commands")
            if any(cand == m or cand.startswith(m + ".") for m in NETWORK_MODULES):
                caps.add("network")
            if cand in ("ctypes", "cffi"):
                dynamic.add("native code (" + cand + ")")
        if isinstance(node, ast.Call):
            fn = _dotted(node.func)
            if fn in ("os.system", "os.popen") or fn.startswith(("os.exec", "os.spawn")):
                caps.add("run_commands")
            if fn in ("eval", "exec", "compile", "__import__"):
                dynamic.add(f"{fn}()")
            if fn in WRITE_CALLS or (isinstance(node.func, ast.Attribute) and node.func.attr in WRITE_METHODS):
                caps.add("write_files")
            if fn == "open":
                mode = ""
                if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
                    mode = node.args[1].value
                for kw in node.keywords:
                    if kw.arg == "mode" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        mode = kw.value.value
                if any(c in mode for c in "wax+"):
                    caps.add("write_files")
    return caps, dynamic


def script_capabilities(rel: str, data: bytes) -> tuple[set[str], set[str]]:
    suffix = PurePosixPath(rel).suffix.lower()
    if suffix in PY_SUFFIXES:
        try:
            return python_capabilities(_text(data))
        except (SyntaxError, ValueError, RecursionError):
            return set(), set()
    if suffix in JS_LANGS:
        text = _text(data)
        caps = {cap for cap, pattern in _JS_CAPS.items() if pattern.search(text)}
        return caps, ({"eval / new Function"} if _JS_DYNAMIC.search(text) else set())
    return set(), set()


def _check_capabilities(files: Mapping[str, bytes]) -> CheckResult:
    name = "scripts use only the capabilities the skill declares"
    scripts = _scripts(files)
    if not scripts:
        return CheckResult(name, PASSED, "this skill has no scripts")
    observed: dict[str, set[str]] = {}
    dynamic: dict[str, set[str]] = {}
    for rel, data in scripts.items():
        caps, dyn = script_capabilities(rel, data)
        if caps:
            observed[rel] = caps
        if dyn:
            dynamic[rel] = dyn
    declared: set[str] | None = None
    if "skill.sdm.json" in files:
        try:
            declared = set(json.loads(files["skill.sdm.json"].decode("utf-8")).get("permissions", []))
        except (UnicodeDecodeError, ValueError, AttributeError):
            declared = None
    all_observed = set().union(*observed.values()) if observed else set()
    notes = [f"{rel} uses {', '.join(sorted(d))}" for rel, d in dynamic.items()]
    unanalysed = [
        rel for rel in scripts
        if PurePosixPath(rel).suffix.lower() not in PY_SUFFIXES and PurePosixPath(rel).suffix.lower() not in JS_LANGS
    ]
    if declared is not None and all_observed - declared:
        extra = sorted(all_observed - declared)
        return CheckResult(name, FAILED, f"scripts use {', '.join(extra)} but the skill declares only: {', '.join(sorted(declared)) or 'nothing'}")
    if declared is None and all_observed:
        return CheckResult(name, WARNING, "scripts use " + ", ".join(sorted(all_observed)) + "; there is no skill.sdm.json to compare with")
    if unanalysed:
        return CheckResult(
            name, WARNING,
            "capabilities are only analysed for Python and JavaScript/TypeScript, so these are not checked: " + ", ".join(unanalysed[:5]),
        )
    if notes:
        return CheckResult(name, WARNING, "; ".join(notes) + " (dynamic code cannot be analysed)")
    return CheckResult(name, PASSED, "by syntax analysis only: it cannot see calls made through other modules or at run time")


def _check_binaries(files: Mapping[str, bytes]) -> CheckResult:
    name = "no binary or executable files"
    binary: list[str] = []
    shell: list[str] = []
    for rel, data in files.items():
        suffix = PurePosixPath(rel).suffix.lower()
        if suffix in BINARY_SUFFIXES or b"\x00" in data[:8192]:
            binary.append(rel)
        elif suffix in SHELL_SUFFIXES:
            shell.append(rel)
    if binary:
        return CheckResult(name, FAILED, "binary content: " + ", ".join(binary[:5]))
    if shell:
        return CheckResult(name, WARNING, "shell scripts are not analysed: " + ", ".join(shell[:5]))
    return CheckResult(name, PASSED)


def split_tools(value: object) -> list[str]:
    """The entries of a tools field (`allowed-tools` or `tools`): a string split on commas and white space except inside brackets
    (so `Bash(git push *)` is ONE entry and keeps its scope), or a list."""
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if not isinstance(value, str):
        return []
    entries: list[str] = []
    current: list[str] = []
    depth = 0
    for ch in value:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if depth == 0 and (ch == "," or ch.isspace()):
            if current:
                entries.append("".join(current))
                current = []
        else:
            current.append(ch)
    if current:
        entries.append("".join(current))
    return entries


# ---- entry points ------------------------------------------------------------------------------------

# The one check that differs by kind: does the definition file exist and is it well formed. Every other check
# runs for every kind. A kind that is not listed here has no checks, so it is refused rather than let through.
DefinitionCheck = Callable[[Mapping[str, bytes], str | None], list[CheckResult]]
DEFINITION_CHECKS: dict[str, DefinitionCheck] = {"skill": _check_skill_md}
CODE_IN_COMPONENTS = {"plugin"}  # kinds whose code is not in a top-level scripts/ folder


def validate_files(
    files: Mapping[str, bytes], *, folder: str | None = None, problems: list[tuple[str, str]] | None = None, kind: str = "skill"
) -> list[CheckResult]:
    """Every static check, on a folder held in memory. `kind` picks only the definition check."""
    definition_check = DEFINITION_CHECKS.get(kind)
    if definition_check is None:
        raise ValueError(f"No checks are registered for kind '{kind}'.")
    problems = problems or []
    results: list[CheckResult] = []
    results += definition_check(files, folder)
    results += _check_paths_and_size(files, problems)
    results.append(_check_hidden_characters(files))
    results += _check_markup_and_wording(files)
    results.append(_check_json(files))
    results += _check_evidence(files)
    shared = [_check_scripts_parse(files), _check_script_references(files), _check_capabilities(files)]
    if kind in CODE_IN_COMPONENTS:  # these three read a top-level scripts/ folder only: they must not claim a pass for code they never saw
        shared = [CheckResult(c.name, NOT_RUN, "this kind keeps its code inside its components, whose own checks read it") for c in shared]
    results += shared
    results.append(_check_binaries(files))
    return results


def validate_skill_dir(path: Path) -> list[CheckResult]:
    files, problems = read_dir(path)
    return validate_files(files, folder=path.resolve().name, problems=problems)
