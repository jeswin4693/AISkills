"""Skill packages: read a folder or a zip into memory safely, and write a zip that is the same every time.

Nothing here runs or evaluates anything. A downloaded zip is untrusted: it is read with limits (entry count, size
per file, size in total), links and encrypted entries are reported, and a name that would leave the folder is kept
as it is so that the static validator fails it. Nothing is extracted to disk by this module.
"""

from __future__ import annotations

import io
import os
import stat
import time
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ..kinds import all_kinds
from ..validate.static import MAX_FILE, MAX_TOTAL, read_dir

MAX_ENTRIES = 1000
ZIP_DATE = (1980, 1, 1, 0, 0, 0)  # a fixed time stamp, so the same files always give the same zip
IGNORED = ("__MACOSX/",)  # what macOS adds to a zip; never part of a skill


class LibraryError(Exception):
    """Something the person can act on. Nothing was changed."""


class NotFound(LibraryError):
    """The skill or version asked for is not in the library."""


class Conflict(LibraryError):
    """Something is already there and was left alone; `force` replaces it where that is allowed."""


@dataclass
class SkillSource:
    files: dict[str, bytes]
    problems: list[tuple[str, str]]  # (kind, message), as read_dir reports them
    kind: str  # "folder" or "zip"
    label: str  # the name of the folder or file, never its full path
    folder: str | None  # the folder name the skill sat in, when there was one


def read_source(path: Path) -> SkillSource:
    path = Path(path)
    if path.is_dir():
        files, problems = read_dir(path)
        return SkillSource(files, problems, "folder", path.resolve().name, path.resolve().name)
    if path.is_file():
        if zipfile.is_zipfile(path):
            return _read_zip(path, path.name)
        raise LibraryError(f"{path.name} is a file but not a zip. Give a skill folder or a .zip of one.")
    raise LibraryError(f"{path} does not exist. Give a skill folder or a .zip of one.")


def read_zip_bytes(data: bytes, label: str) -> SkillSource:
    """A zip that arrived as bytes (an upload). Read in memory with the same limits; nothing touches the disk."""
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise LibraryError(f"{label} is not a zip file.")
    return _read_zip(io.BytesIO(data), label)


def _read_zip(source: Path | io.BytesIO, label: str) -> SkillSource:
    problems: list[tuple[str, str]] = []
    files: dict[str, bytes] = {}
    try:
        archive = zipfile.ZipFile(source)
    except (zipfile.BadZipFile, OSError) as exc:
        raise LibraryError(f"{label} cannot be read as a zip: {exc}") from exc
    with archive:
        infos = [i for i in archive.infolist() if not i.is_dir() and not i.filename.startswith(IGNORED)]
        infos = [i for i in infos if PurePosixPath(i.filename).name != ".DS_Store"]
        if len(infos) > MAX_ENTRIES:
            problems.append(("size", f"the zip holds {len(infos)} files (limit {MAX_ENTRIES})"))
            return SkillSource({}, problems, "zip", label, None)
        total = 0
        spelled: dict[str, str] = {}  # a file's name with case and path spelling ignored -> the name it came in as
        for info in infos:
            name = info.filename
            if name in files:
                problems.append(("duplicate", f"{name} appears twice in the zip"))
                continue
            same = spelled.setdefault(PurePosixPath(name).as_posix().casefold(), name)  # "./a", "a//b" and "A" are the same file on some systems
            if same != name:
                problems.append(("duplicate", f"{name} and {same} are the same file once capital letters and path spelling are ignored"))
                continue
            if stat.S_ISLNK(info.external_attr >> 16):
                problems.append(("symlink", f"{name} is a symbolic link"))
                continue
            if info.flag_bits & 0x1:
                problems.append(("unreadable", f"{name} is encrypted"))
                continue
            if info.file_size > MAX_FILE:
                problems.append(("size", f"{name} is {info.file_size} bytes (limit {MAX_FILE})"))
                continue
            try:
                with archive.open(info) as handle:
                    data = handle.read(MAX_FILE + 1)  # never trust the size the zip declares
            except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError, EOFError) as exc:
                problems.append(("unreadable", f"{name}: {exc}"))
                continue
            if len(data) > MAX_FILE:
                problems.append(("size", f"{name} unpacks to more than {MAX_FILE} bytes"))
                continue
            total += len(data)
            if total > MAX_TOTAL:
                problems.append(("size", f"the zip unpacks to more than {MAX_TOTAL} bytes"))
                break
            files[name] = data
    return _strip_top_folder(files, problems, label)


def _strip_top_folder(files: dict[str, bytes], problems: list[tuple[str, str]], label: str) -> SkillSource:
    """A skill zip usually holds one folder named after the skill. Use what is inside it."""
    definition_files = {kind.definition_file for kind in all_kinds()}  # SKILL.md, AGENT.md, ...
    tops = {PurePosixPath(n).parts[0] for n in files if PurePosixPath(n).parts}
    if not definition_files & files.keys() and len(tops) == 1:
        top = next(iter(tops))
        if top not in ("", ".", "..") and any(f"{top}/{d}" in files for d in definition_files):
            stripped = {n[len(top) + 1:]: d for n, d in files.items() if n.startswith(top + "/")}
            return SkillSource(stripped, problems, "zip", label, top)
    return SkillSource(files, problems, "zip", label, None)


def zip_bytes(name: str, files: Mapping[str, bytes]) -> bytes:
    """A zip holding `<name>/<file>` for every file, sorted, with fixed time stamps and modes.

    The same files always give the same bytes on the same machine (the compressed bytes can differ between
    versions of the zlib library)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for rel in sorted(files):
            info = zipfile.ZipInfo(f"{name}/{rel}", ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            info.create_system = 3
            archive.writestr(info, files[rel])
    return buffer.getvalue()


def replace_dir(src: Path, dst: Path, attempts: int = 6) -> None:
    """Move a folder into place. On Windows a virus scanner or the search indexer can hold a file that was just written
    for a moment, and the rename then fails with "Access is denied". Waiting a little and trying again is the usual fix:
    0.05 s, then twice as long each time, about 1.5 s in all. A refusal that lasts is raised as a plain error."""
    for n in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError as exc:
            if n == attempts - 1:
                raise LibraryError(
                    "Windows refused to move the new files into place (an antivirus scan or another program may be holding "
                    f"them). Nothing was kept. Try again in a moment. ({exc.strerror or 'access denied'})"
                ) from exc
            time.sleep(0.05 * 2**n)


def write_tree(out_dir: Path, files: Mapping[str, bytes]) -> None:
    """Write files under out_dir. A path that leaves the folder is refused, whatever checked it before."""
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    for rel, data in files.items():
        parts = PurePosixPath(rel).parts
        if not parts or rel.startswith("/") or "\\" in rel or ".." in parts or (len(rel) > 1 and rel[1] == ":"):
            raise ValueError(f"Refusing to write outside the folder: {rel}")
        target = (out_dir / rel).resolve()
        if out_dir not in target.parents:
            raise ValueError(f"Refusing to write outside the folder: {rel}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
