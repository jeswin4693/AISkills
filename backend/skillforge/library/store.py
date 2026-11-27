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
import threading
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..graph.store import data_dir
from ..kinds import get_kind
from ..results import CheckResult
from ..validate.static import MAX_NAME, SLUG, read_dir
from .package import Conflict, LibraryError, NotFound, replace_dir, write_tree
from .remove import has_link, is_link, remove_tree

SCHEMA = 1
MAX_DIFF_LINES = 200
_VERSION_DIR = re.compile(r"^v(\d+)\Z")
_HIDDEN = re.compile(r"^\.deleting-[0-9a-f]{32}\Z")  # an entry being deleted: renamed to this first, so it is out of the library at once
# What `library/service.py` names a backup of a folder an install replaced: `<name>-<date>-<time>`, then `-2`, `-3`... when taken, then an extension for one file.
# The whole shape is matched (never just "starts with the name"), so deleting `foo` cannot reach the backups of `foo-bar`.
_BACKUP_TAIL = r"-\d{8}-\d{6}(?:-\d{1,3})?(?:\.[A-Za-z0-9]{1,10})?\Z"


@dataclass(frozen=True)
class DeleteReport:
    """What a delete did: the versions it removed, the backups it removed, and whether anything could not be removed (it is out of the library either way)."""

    name: str
    versions: int
    backups: int
    leftover: bool


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


_ADD_LOCK = threading.RLock()  # one writer at a time in this process: the look at the latest version and the store are one step


class Library:
    """The versions of one kind of thing (skills, and later agents and the rest). Each kind has its own root, so names
    never collide across kinds. The skill library stays exactly where it always was."""

    def __init__(self, root: Path | None = None, kind: str = "skill") -> None:
        spec = get_kind(kind)  # an unknown kind is refused here, before anything is joined into a path or touched on disk
        self.kind = kind
        self.root = Path(root) if root else data_dir() / spec.library_dir

    def for_kind(self, kind: str) -> "Library":
        """The library of another kind, next to this one (this very object for the same kind)."""
        if kind == self.kind:
            return self
        return Library(self.root.parent / get_kind(kind).library_dir, kind)

    @property
    def backups(self) -> Path:
        return self.root.parent / ("backups" if self.kind == "skill" else f"backups-{self.kind}")

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
        skill_version: str = "", checks: Sequence[CheckResult] = (), now: datetime | None = None, expect_latest: int | None = None,
    ) -> tuple[Version, bool]:
        """Store files as the next version. Returns (version, created); identical content makes no new version.

        `expect_latest` is for a change made FROM a version (editing its test cases): the number of the version the change was made on. If another
        version was stored while it was being checked, nothing is stored and `Conflict` says so, so a newer change is never overwritten. The look at
        the latest version and the store happen together, one writer at a time within this process."""
        with _ADD_LOCK:
            return self._add(name, files, source_kind, source_label, note, skill_version, checks, now, expect_latest)

    def _add(
        self, name: str, files: Mapping[str, bytes], source_kind: str, source_label: str, note: str, skill_version: str,
        checks: Sequence[CheckResult], now: datetime | None, expect_latest: int | None,
    ) -> tuple[Version, bool]:
        skill = self._skill_dir(name)
        existing = self.versions(name)
        if expect_latest is not None and (existing[-1].version if existing else 0) != expect_latest:
            now_latest = existing[-1].tag if existing else "no version"
            raise Conflict(
                f"The version you edited ({name} v{expect_latest}) is not the latest: {name} is now at {now_latest}, which was stored while this was being "
                f"checked. Open {now_latest} and make the change there, so nothing newer is lost. Nothing was saved."
            )
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

    # ---- deleting ----------------------------------------------------------------------------------

    def delete(self, name: str) -> DeleteReport:
        """Delete one entry: every version of it, and the backups made when an install replaced a folder of that name. It cannot be undone.

        The name is checked first (`_skill_dir`), so nothing odd is ever joined into a path. A link, as the entry or inside it, is refused and nothing is touched:
        nothing here is written with a link in it, so one means somebody changed the folder. The entry is first renamed to a hidden name (`.deleting-<id>`), which takes it
        out of the library in one step; if the rename is refused (a program holds a file) nothing was deleted. Then it is removed; whatever cannot be is reported as
        `leftover` and swept by the next delete. Held under the same lock as `add`, so a save and a delete of one name never interleave."""
        skill = self._skill_dir(name)
        with _ADD_LOCK:
            self._sweep_hidden()
            if not skill.exists() and not skill.is_symlink():
                raise NotFound(f"There is no skill named '{name}' in the library.")
            if is_link(skill):
                raise LibraryError(f"'{name}' is a link. It was left alone: nothing was deleted.")
            if has_link(skill):
                raise LibraryError(f"'{name}' holds a link. It was left alone: nothing was deleted.")
            versions = sum(1 for p in skill.iterdir() if _VERSION_DIR.match(p.name) and p.is_dir())  # by folder name: a damaged manifest must not stop a delete
            hidden = self.root / f".deleting-{uuid.uuid4().hex}"
            try:
                skill.rename(hidden)
            except OSError as exc:
                raise LibraryError(
                    f"'{name}' is in use by another program (a virus scanner or the search indexer, perhaps). Nothing was deleted: try again in a moment."
                ) from exc
            try:
                leftover = not remove_tree(hidden, self.root)
            except LibraryError:  # a link appeared after the look above: left alone, out of the library, reported
                leftover = True
            backups = 0
            if self.backups.is_dir() and not is_link(self.backups):
                shape = re.compile(re.escape(name) + _BACKUP_TAIL)
                for entry in sorted(self.backups.iterdir()):
                    if not shape.match(entry.name):
                        continue
                    try:
                        gone = remove_tree(entry, self.backups, allow_inner_links=True)  # a backup of a folder with links in it is a copy with those links
                    except LibraryError:  # the backup is itself a link: left alone
                        leftover = True
                        continue
                    backups += gone
                    leftover = leftover or not gone
            return DeleteReport(name, versions, backups, leftover)

    def _sweep_hidden(self) -> None:
        """Remove what an earlier delete could not (a hidden `.deleting-<id>` folder). Best effort: whatever still cannot go stays for the next time."""
        if not self.root.is_dir():
            return
        for p in self.root.iterdir():
            if _HIDDEN.match(p.name) and p.is_dir():
                try:
                    remove_tree(p, self.root)
                except LibraryError:
                    pass
