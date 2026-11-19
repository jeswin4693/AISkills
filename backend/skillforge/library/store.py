"""The skill library: every imported skill is kept as numbered, never-changed versions (v1, v2, ...).

    <library>/<skill name>/v<N>/skill/...        the files, exactly as imported
    <library>/<skill name>/v<N>/manifest.json    when, from where, a SHA-256 for every file, what the checks said

History only grows: a rollback makes a new version with the old content. Every read compares the stored files with
the manifest, so a file that was edited, added or removed behind the library's back is noticed and refused.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..graph.store import data_dir
from ..results import CheckResult
from ..validate.static import SLUG, read_dir
from .package import Conflict, LibraryError, NotFound, replace_dir, write_tree

MAX_NAME = 64
SCHEMA = 1
MAX_DIFF_LINES = 200
_VERSION_DIR = re.compile(r"^v(\d+)$")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def content_hash(files: Mapping[str, bytes]) -> str:
    """One hash for a whole skill: the same files (names and bytes) always give the same value."""
    lines = "".join(f"{rel}\0{sha256(files[rel])}\n" for rel in sorted(files))
    return sha256(lines.encode("utf-8"))


@dataclass
class Version:
    name: str
    version: int
    created_at: str
    content_hash: str
    files: dict[str, str]  # path -> sha256
    source_kind: str  # folder, zip, rollback
    source_label: str  # a folder or file name, or "v2" for a rollback; never a full path
    note: str = ""
    skill_version: str = ""  # the "version" in skill.sdm.json, when the skill has one
    checks: list[dict[str, str]] = field(default_factory=list)  # name, status, detail of every check at import
    schema: int = SCHEMA

    @property
    def tag(self) -> str:
        return f"v{self.version}"

    def count(self, status: str) -> int:
        return sum(c["status"] == status for c in self.checks)


@dataclass
class FileChange:
    path: str
    status: str  # added, removed, changed
    text: str = ""  # a unified diff for text files, possibly cut
    binary: bool = False


def checks_as_dicts(checks: Sequence[CheckResult]) -> list[dict[str, str]]:
    return [{"name": c.name, "status": c.status, "detail": c.detail} for c in checks]


def diff_files(old: Mapping[str, bytes], new: Mapping[str, bytes]) -> list[FileChange]:
    out: list[FileChange] = []
    for rel in sorted(set(old) | set(new)):
        if rel in old and rel in new and old[rel] == new[rel]:
            continue
        status = "added" if rel not in old else "removed" if rel not in new else "changed"
        a, b = old.get(rel, b""), new.get(rel, b"")
        try:
            if b"\x00" in a[:8192] or b"\x00" in b[:8192]:
                raise UnicodeDecodeError("utf-8", b"", 0, 1, "binary")
            lines = list(difflib.unified_diff(
                a.decode("utf-8").splitlines(), b.decode("utf-8").splitlines(),
                fromfile=f"{rel} (before)" if rel in old else "/dev/null",
                tofile=f"{rel} (after)" if rel in new else "/dev/null", lineterm="", n=2,
            ))
        except UnicodeDecodeError:
            out.append(FileChange(rel, status, binary=True))
            continue
        if len(lines) > MAX_DIFF_LINES:
            lines = lines[:MAX_DIFF_LINES] + [f"... {len(lines) - MAX_DIFF_LINES} more line(s) not shown"]
        out.append(FileChange(rel, status, "\n".join(lines)))
    return out


class Library:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else data_dir() / "library"

    @property
    def backups(self) -> Path:
        return self.root.parent / "backups"

    # ---- reading -----------------------------------------------------------------------------------

    def _skill_dir(self, name: str) -> Path:
        if not isinstance(name, str) or not SLUG.match(name) or len(name) > MAX_NAME:
            raise LibraryError(f"'{name}' is not a valid skill name (lowercase letters, digits and hyphens).")
        return self.root / name

    def names(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_dir() and SLUG.match(p.name))

    def versions(self, name: str) -> list[Version]:
        skill = self._skill_dir(name)
        if not skill.is_dir():
            return []
        found: list[Version] = []
        for p in skill.iterdir():
            m = _VERSION_DIR.match(p.name)
            if not (m and p.is_dir()):
                continue
            try:
                data = json.loads((p / "manifest.json").read_text(encoding="utf-8"))
                v = Version(**data)
            except (OSError, ValueError, TypeError) as exc:
                raise LibraryError(f"The manifest of {name} {p.name} is damaged ({type(exc).__name__}). Nothing was used.") from exc
            if v.schema != SCHEMA or v.version != int(m.group(1)) or v.name != name:
                raise LibraryError(f"The manifest of {name} {p.name} does not belong there. Nothing was used.")
            found.append(v)
        return sorted(found, key=lambda v: v.version)

    def pick(self, name: str, version: int | None = None) -> Version:
        found = self.versions(name)
        if not found:
            raise NotFound(f"There is no skill named '{name}' in the library. See: library list")
        if version is None:
            return found[-1]
        for v in found:
            if v.version == version:
                return v
        raise NotFound(f"'{name}' has no version v{version}. It has: " + ", ".join(v.tag for v in found))

    def read(self, name: str, version: int | None = None) -> tuple[Version, dict[str, bytes]]:
        """A version and its files, after checking every file against the manifest."""
        v = self.pick(name, version)
        files, problems = read_dir(self.root / name / v.tag / "skill")
        if problems:
            raise LibraryError(f"{name} {v.tag} was changed after import ({problems[0][1]}). Nothing was used.")
        actual = {rel: sha256(data) for rel, data in files.items()}
        if actual != v.files:
            odd = sorted(p for p in set(actual) | set(v.files) if actual.get(p) != v.files.get(p))
            raise LibraryError(
                f"{name} {v.tag} was changed after import ({', '.join(odd[:5])}). Nothing was used. "
                f"Import the skill again to make a clean new version."
            )
        return v, files

    # ---- writing -----------------------------------------------------------------------------------

    def add(
        self, name: str, files: Mapping[str, bytes], *, source_kind: str, source_label: str, note: str = "",
        skill_version: str = "", checks: Sequence[CheckResult] = (), now: datetime | None = None,
    ) -> tuple[Version, bool]:
        """Store files as the next version. Returns (version, created); identical content makes no new version."""
        skill = self._skill_dir(name)
        existing = self.versions(name)
        digest = content_hash(files)
        if existing and existing[-1].content_hash == digest:
            return existing[-1], False
        number = (existing[-1].version if existing else 0) + 1
        stamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
        version = Version(
            name, number, stamp, digest, {rel: sha256(d) for rel, d in sorted(files.items())},
            source_kind, source_label, note, skill_version, checks_as_dicts(checks),
        )
        skill.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".tmp-", dir=skill))  # built aside, then renamed: never half-written
        try:
            write_tree(staging / "skill", files)
            (staging / "manifest.json").write_text(json.dumps(asdict(version), indent=2) + "\n", encoding="utf-8", newline="\n")
            final = skill / version.tag
            if final.exists():
                raise Conflict(f"{final.name} of '{name}' already exists. Another run may be using the library.")
            replace_dir(staging, final)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return version, True
