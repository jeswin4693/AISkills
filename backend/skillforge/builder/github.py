"""Reading a public GitHub repository from its link.

A link is parsed by a strict list, the repository is **downloaded as a zip** (never cloned: a clone can run hooks, filters and
submodule addresses that the repository itself controls, and has no size limit), and **unpacked by code that decides every file's name
and place**: only source files in a language the graph reads, never a link, never a name that could leave the folder, with limits on how
many files and how many bytes. The result is a snapshot folder that the rest of the pipeline reads like any other folder.

Nothing is run, no git is used, and no key is needed (public repositories only). The download goes only to `codeload.github.com` over
https and follows no redirect anywhere else. No message repeats the link a person typed or a path on this computer.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import shutil
import stat
import threading
import time
import unicodedata
import urllib.error
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from ..graph.files import MAX_BYTES, PACKAGE_NAMED, SKIP_DIRS
from ..graph.languages import language_of_path
from ..graph.store import data_dir
from ..guide.docs import is_doc_path, sort_key
from .errors import BadRequest, UpstreamError

log = logging.getLogger(__name__)

CODELOAD_HOST = "codeload.github.com"
MAX_DOWNLOAD = 80_000_000  # bytes of zip
MAX_ENTRIES = 200_000  # members of the archive, before any is read
MAX_FILES = 20_000  # source files written
MAX_UNPACKED = 200_000_000  # bytes written
MAX_FILE = MAX_BYTES  # the graph reads no file over this, so none is written
MAX_DOCS = 60  # README and doc files kept (they are text for the guide to read, and the graph ignores them)
MAX_DOC_FILE = 200_000  # bytes of one of them
MAX_DOC_BYTES = 3_000_000  # bytes of all of them together
MAX_PATH = 200  # characters of a file's path below the repository's folder
# Characters of a whole path on this disk. Windows refuses a path of 260 (and a folder of about 248), so a file that would not fit is
# skipped by name instead of failing half way. The temporary folder is never shorter than the final one, so fitting there means fitting here.
PATH_LIMIT = 240 if os.name == "nt" else 4000
TIMEOUT = 30.0  # seconds to wait for a connection or one read
DEADLINE = 120.0  # seconds for the whole download
CHUNK = 65_536
SNAPSHOT_TTL = 15 * 60  # seconds a snapshot is reused by a plain read
KEEP_PER_REPO = 2  # snapshots of one repository kept
MAX_REPOS = 12  # repositories (and branches) kept
PARTIAL_AGE = 3600  # seconds after which a half-made snapshot is cleaned away
USED_GRACE = 15 * 60  # seconds after a snapshot was last opened during which it is never pruned (a request may still be reading it)
RENAME_TRIES = 8
RENAME_DELAY = 0.15  # seconds, growing with each try
USER_AGENT = "skillforge-repository-reader"

HELP = (
    "Give the link of a public GitHub repository, such as https://github.com/owner/repo (or https://github.com/owner/repo/tree/branch). "
    "Other sites and other kinds of link are not read."
)
NOT_FOUND = "GitHub has no public repository (or branch) there. Private repositories cannot be read: check the link."

OWNER = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?")  # GitHub: 1 to 39 letters, digits and hyphens, not at either end
NAME = re.compile(r"[A-Za-z0-9._-]{1,100}")  # a repository or a branch (one name: no slash)
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://")


class NotFound(BadRequest):
    """GitHub says there is no public repository (or branch) at that link."""


# ---- the link -----------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class GithubLink:
    owner: str
    repo: str
    ref: str | None = None

    @property
    def url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}" + (f"/tree/{self.ref}" if self.ref else "")

    @property
    def name(self) -> str:
        return f"{self.owner}/{self.repo}"

    @property
    def leaf(self) -> str:
        """The snapshot's folder name. `__` cannot be in an owner's name, so two repositories never share one."""
        return f"{self.owner}__{self.repo}"


def looks_like_link(text: object) -> bool:
    """Whether this is meant as a link (so a refusal should be about links) and not as a folder path."""
    raw = text.strip() if isinstance(text, str) else ""
    return bool(SCHEME.match(raw)) or raw.lower().startswith(("github.com/", "www.github.com/")) or raw.lower() in ("github.com", "www.github.com")


def parse_link(text: object) -> GithubLink | None:
    """The repository a link names, None when this is not meant as a link, and BadRequest (never repeating the text) when it is a link
    that is not a plain public GitHub repository link."""
    raw = text.strip() if isinstance(text, str) else ""
    if not looks_like_link(raw):
        return None
    candidate = raw if SCHEME.match(raw) else "https://" + raw
    if any(ord(c) <= 32 or ord(c) == 127 for c in candidate):
        raise BadRequest(HELP)
    try:
        parts = urlsplit(candidate)
    except ValueError:
        raise BadRequest(HELP) from None
    if parts.scheme.lower() == "http" and parts.netloc.lower() in ("github.com", "www.github.com"):
        raise BadRequest("Use an https:// link.")
    if parts.scheme.lower() != "https" or parts.netloc.lower() not in ("github.com", "www.github.com"):  # the netloc holds any login or port
        raise BadRequest(HELP)
    if "%" in parts.path:
        raise BadRequest(HELP)
    segments = parts.path.split("/")[1:]
    if segments and segments[-1] == "":
        segments.pop()  # one trailing slash
    if len(segments) < 2 or any(s == "" for s in segments):
        raise BadRequest(HELP)
    owner, repo = segments[0], segments[1]
    if repo.endswith(".git") and len(repo) > 4:
        repo = repo[:-4]
    ref = None
    if len(segments) > 2:
        if segments[2] != "tree":
            raise BadRequest(HELP)
        if len(segments) > 4:
            raise BadRequest("To read one folder of the repository, use the 'Only this folder inside it' box and give the repository's own link. "
                             "A branch name with a slash cannot be given in a link.")
        if len(segments) != 4:
            raise BadRequest(HELP)
        ref = segments[3]
    if not OWNER.fullmatch(owner) or not NAME.fullmatch(repo) or set(repo) <= {"."} or (ref is not None and (not NAME.fullmatch(ref) or set(ref) <= {"."})):
        raise BadRequest(HELP)
    return GithubLink(owner, repo, ref)


def archive_urls(link: GithubLink) -> list[str]:
    """Where GitHub serves this repository's zip, built only from the checked parts. A branch is tried as a branch, then as a tag."""
    base = f"https://{CODELOAD_HOST}/{link.owner}/{link.repo}/zip"
    if link.ref is None:
        return [f"{base}/HEAD"]
    return [f"{base}/refs/heads/{link.ref}", f"{base}/refs/tags/{link.ref}"]


# ---- the download -------------------------------------------------------------------------------------------------


def allowed_url(url: object) -> bool:
    """Only the download host, over https, on the usual port and with no login: the one place a download is ever fetched from."""
    if not isinstance(url, str) or not url:
        return False
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    return (
        parts.scheme == "https" and (parts.hostname or "").lower() == CODELOAD_HOST and parts.username is None and parts.password is None
        and port in (None, 443)
    )


class _Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_url(newurl):
            raise UpstreamError("GitHub sent the download somewhere else (a redirect), which is not followed.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener():
    return urllib.request.build_opener(_Redirects)


def _http_failure(code: int) -> Exception:
    if code == 404:
        return NotFound(NOT_FOUND)
    if code in (403, 429):
        return UpstreamError("GitHub refused the download (too many requests, perhaps). Try again in a few minutes.")
    return UpstreamError(f"GitHub answered {code}.")


def download(url: str, *, opener=None, clock=time.monotonic) -> bytes:
    """The zip at `url`, or BadRequest / UpstreamError saying in plain words what went wrong. The size and the time are limited."""
    if not allowed_url(url):
        raise BadRequest(HELP)
    opener = opener or _opener()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/zip"})
    try:
        response = opener.open(request, timeout=TIMEOUT)
    except urllib.error.HTTPError as exc:
        raise _http_failure(exc.code) from None
    except UpstreamError:
        raise
    except (urllib.error.URLError, OSError) as exc:  # a timeout, a refused connection, a certificate that does not match
        raise UpstreamError(f"Could not reach GitHub ({type(exc).__name__}).") from None
    chunks: list[bytes] = []
    total = 0
    try:
        with response:
            length = response.headers.get("Content-Length")
            if length and length.isascii() and length.isdigit() and int(length) > MAX_DOWNLOAD:  # isdigit() alone accepts a superscript two, which int() refuses
                raise BadRequest(_too_large())
            deadline = clock() + DEADLINE
            # read1 gives back whatever has arrived (at least one byte), so the deadline is looked at after every receive; read(n) waits until
            # n bytes have come, and a server sending one byte every few seconds could hold this for hours.
            read = getattr(response, "read1", None) or response.read
            while True:
                if clock() > deadline:
                    raise UpstreamError("The download took too long and was stopped.")
                chunk = read(CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_DOWNLOAD:
                    raise BadRequest(_too_large())
                chunks.append(chunk)
    except OSError as exc:
        raise UpstreamError(f"Could not reach GitHub ({type(exc).__name__}).") from None
    data = b"".join(chunks)
    if not data.startswith(b"PK\x03\x04"):
        raise BadRequest("GitHub did not send a zip file.")
    return data


def _too_large() -> str:
    return (f"The repository is too large to read from a link (the limit is {MAX_DOWNLOAD // 1_000_000} MB). "
            "Clone it, and give the folder instead.")


def fetch_archive(link: GithubLink, *, opener=None) -> bytes:
    """The repository's zip. A branch name that is not a branch is tried as a tag."""
    last: Exception | None = None
    for url in archive_urls(link):
        try:
            return download(url, opener=opener)
        except NotFound as exc:
            last = exc
    assert last is not None
    raise last


# ---- unpacking ------------------------------------------------------------------------------------------------------


MAX_PART = 120  # characters in one name
# What Windows will not have in a name, and what a path separator or an NTFS stream (`a.py:stream`) would make of it.
FORBIDDEN_CHARS = frozenset([chr(92), ":", "*", "?", chr(34), "<", ">", "|"])
# Characters nobody can see, or that change how a name reads: controls (NUL included), format characters (zero width, bidirectional
# overrides), line and paragraph separators, lone surrogates. Matched by Unicode category, so a name in any language is still fine.
HIDDEN_CATEGORIES = frozenset(["Cc", "Cf", "Zl", "Zp", "Cs"])
# Windows device names: opening `con.py` or `aux` opens a device, not a file. The superscript digits are devices too.
RESERVED_NAMES = frozenset(
    ["con", "prn", "aux", "nul", "conin$", "conout$"]
    + [f"{device}{digit}" for device in ("com", "lpt") for digit in "0123456789" + chr(0xB9) + chr(0xB2) + chr(0xB3)]
)


def unsafe_part(part: str) -> bool:
    """True when one name in a path inside the archive (the text between two slashes) must never be written to this disk.

    The archive is hostile data and this disk may be Windows, so the rules are Windows' even on other systems: skipping a name is cheap,
    writing a wrong one is not. A name is refused when it is empty, `.` or `..`; is longer than MAX_PART; starts with a space or ends
    with a dot or a space (Windows drops those, so `a.py.` and `a.py` would be one file); holds a character Windows forbids or an
    invisible one; or is a device name once its extension is taken off (`con`, `CON.py`, `com1.txt`, `aux`). The caller adds the
    limit on the whole path and checks that the file's resolved place is inside the snapshot."""
    if part in ("", ".", "..") or len(part) > MAX_PART:
        return True
    if part[0] == " " or part[-1] in ". ":
        return True
    if any(ch in FORBIDDEN_CHARS or unicodedata.category(ch) in HIDDEN_CATEGORIES for ch in part):
        return True
    return part.split(".", 1)[0].rstrip(" ").lower() in RESERVED_NAMES


@dataclass
class Extracted:
    files: int  # source files (the ones the graph reads)
    bytes: int  # bytes of source files and documents
    skipped: dict[str, int]
    docs: int = 0  # README and doc files kept next to them (see skillforge.guide.docs)


LAYOUT = "The download does not have the layout of a GitHub archive (one folder holding the repository), so it was not unpacked."


def extract_sources(data: bytes, dest: Path) -> Extracted:
    """Write the source files of the archive under `dest`, and the README and doc files that explain them (`guide.docs.is_doc_path`, with limits
    of their own), and nothing else, anywhere. Raises BadRequest, before writing anything, for an archive that is not one folder or has too many
    members; and when no source file is left (documents alone are not a repository that can be read)."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError, OSError):
        raise BadRequest("The download is not a valid zip file.") from None
    skipped: dict[str, int] = {}

    def skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_ENTRIES:
            raise BadRequest("The repository has too many files to read from a link. Clone it, and give the folder instead.")
        tops = {info.filename.split("/", 1)[0] for info in infos}
        # the top folder is dropped, never written, so only its shape matters (a long branch name makes a long one)
        if len(tops) != 1 or next(iter(tops)) in ("", ".", "..") or any("/" not in info.filename and not info.filename.endswith("/") for info in infos):
            raise BadRequest(LAYOUT)

        def doc_order(info: zipfile.ZipInfo) -> tuple[int, int, str, str] | None:
            """Where a document stands among the others, or None for a file that is not one."""
            if info.filename.endswith("/"):
                return None
            parts = info.filename.split("/")[1:]
            return sort_key(parts) if parts and language_of_path(parts[-1]) is None and is_doc_path(parts) else None

        # Documents are looked at first, best first (the README before a pile of doc pages, however the archive happens to order them), so that
        # their cap cuts the least useful ones. They are small and limited apart from the source, so they cannot use up its room. The source files
        # keep the archive's own order.
        keyed = [(doc_order(info), n, info) for n, info in enumerate(infos)]
        infos = [info for _, _, info in sorted((k for k in keyed if k[0] is not None), key=lambda k: (k[0], k[1]))] + [info for key, _, info in keyed if key is None]
        dest.mkdir(parents=True, exist_ok=True)
        base = dest.resolve()
        seen: set[str] = set()
        files = written = read_bytes = docs = doc_bytes = 0  # written: bytes kept; read_bytes: every byte decompressed, kept or not
        for info in infos:
            if info.filename.endswith("/"):
                continue  # a folder entry
            parts = info.filename.split("/")[1:]
            if any(unsafe_part(p) for p in parts) or len("/".join(parts)) > MAX_PATH:
                skip("unsafe_name")
                continue
            if any(p in SKIP_DIRS and p not in PACKAGE_NAMED for p in parts[:-1]):
                skip("ignored_dir")
                continue
            kind = stat.S_IFMT((info.external_attr >> 16) & 0xFFFF)
            if kind not in (0, stat.S_IFREG):  # a symbolic link, a device, a pipe
                skip("link")
                continue
            doc = False  # a README or a doc file: kept for the guide, counted and limited apart from the source
            if language_of_path(parts[-1]) is None:
                if not is_doc_path(parts):
                    skip("not_source")
                    continue
                doc = True
            cap = MAX_DOC_FILE if doc else MAX_FILE
            if info.file_size > cap:
                skip("too_large")
                continue
            key = "/".join(parts).lower()
            if key in seen:  # a disk that ignores case would make these one file
                skip("duplicate")
                continue
            if (docs >= MAX_DOCS or doc_bytes >= MAX_DOC_BYTES) if doc else files >= MAX_FILES:
                skip("limit")
                continue
            if read_bytes >= MAX_UNPACKED:  # decompressing is the cost, and it counts for entries that are then skipped too: stop reading
                skip("limit")
                continue
            room = MAX_UNPACKED - written
            try:
                with archive.open(info) as handle:
                    body = handle.read(min(cap, room) + 1)  # what the header says is not trusted; and never more than there is room for
            except (zipfile.BadZipFile, RuntimeError, OSError, EOFError):
                skip("unreadable")
                continue
            read_bytes += len(body)
            if len(body) > cap:
                skip("too_large")
                continue
            if len(body) > room or (doc and doc_bytes + len(body) > MAX_DOC_BYTES):
                skip("limit")
                continue
            target = dest.joinpath(*parts)
            if len(str(target)) > PATH_LIMIT:
                skip("path_too_long")
                continue
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                if base != target.parent.resolve() and base not in target.parent.resolve().parents:  # belt and braces: never outside `dest`
                    skip("unsafe_name")
                    continue
                with open(target, "xb") as handle:
                    handle.write(body)
            except FileExistsError:
                skip("duplicate")
                continue
            except OSError:  # a path this disk cannot hold
                skip("unwritable")
                continue
            seen.add(key)
            if doc:
                docs += 1
                doc_bytes += len(body)
            else:
                files += 1
            written += len(body)
    if files == 0:
        raise BadRequest("No source files in a language SkillForge reads were found in this repository.")
    return Extracted(files, written, skipped, docs)


# ---- snapshots ------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Snapshot:
    path: Path  # the folder holding the repository's source files, named for the repository
    link: GithubLink
    fetched_at: str
    epoch: float
    files: int
    bytes: int
    skipped: dict[str, int]
    reused: bool
    stamp: str = ""  # this copy's own name: a later request can ask for exactly this one (open_snapshot's `stamp`)
    docs: int | None = None  # README and doc files kept; None for a copy made before they were kept (it has none, and does not know)


_GUARD = threading.Lock()
_LOCKS: dict[str, threading.Lock] = {}
_GENERATION: dict[str, int] = {}


def snapshot_root() -> Path:
    return data_dir() / "github"


def _lock_for(key_dir: Path) -> threading.Lock:
    """The lock of one repository's folder: a request holds it while it opens or downloads a copy, and pruning will not delete under it."""
    with _GUARD:
        return _LOCKS.setdefault(str(key_dir), threading.Lock())


def _mark_used(stamp_dir: Path, now: float) -> None:
    """Write down that this copy was opened at `now`. Pruning skips a copy opened in the last USED_GRACE seconds, so a request that is still
    reading the copy it was handed is not cut off. Failing to write it is logged and never fails the read: the copy is then pruned as before."""
    try:
        (stamp_dir / "used").write_text(repr(now), encoding="utf-8")
    except OSError as exc:
        log.warning("could not mark a snapshot as used: %s", exc)


def _recently_used(stamp_dir: Path, now: float) -> bool:
    """Whether the copy was opened less than USED_GRACE seconds ago. A time in the future (the clock moved back) counts as used; a missing or
    damaged marker (a copy made before markers existed) counts as not used."""
    try:
        opened = float((stamp_dir / "used").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return now - opened < USED_GRACE


def _digest(text: str, length: int) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def _key_dir(root: Path, link: GithubLink) -> Path:
    """Where this repository's copies live. Both levels are hashes of the exact text, never the text itself: a branch called `Main` and one
    called `main` (or `main.`) must not share a folder on a disk that ignores case or a trailing dot, and a long name must not eat the path.
    GitHub treats owner and repository names as one whatever their case, so those are lower-cased before hashing; a branch is exact."""
    repo_key = _digest(f"{link.owner}/{link.repo}".lower(), 12)
    return root / repo_key / ("default" if link.ref is None else "ref-" + _digest(link.ref, 10))


INNER_MAX = 48  # characters of the folder the source files are in


def _inner(link: GithubLink) -> str:
    """The folder the source files are in, named for the repository (an evidence file records this name, so it must be the same every time
    for the same repository). Lower case, so a link typed with other capitals finds the same folder on a disk that cares; a very long name is
    cut and given a hash, so it can never use up the path."""
    leaf = link.leaf.lower()
    return leaf if len(leaf) <= INNER_MAX else leaf[: INNER_MAX - 13] + "-" + _digest(leaf, 12)


def _read_meta(stamp_dir: Path, link: GithubLink) -> dict | None:
    """The record of a copy, only if it is well formed AND says it is a copy of this very repository and branch."""
    try:
        meta = json.loads((stamp_dir / "meta.json").read_text(encoding="utf-8"))
        ok = (
            isinstance(meta, dict) and isinstance(meta.get("epoch"), (int, float)) and isinstance(meta.get("fetched_at"), str)
            and isinstance(meta.get("files"), int) and isinstance(meta.get("bytes"), int) and isinstance(meta.get("skipped"), dict)
            and str(meta.get("owner", "")).lower() == link.owner.lower() and str(meta.get("repo", "")).lower() == link.repo.lower()
            and meta.get("ref") == link.ref
            and (stamp_dir / _inner(link)).is_dir()
        )
        return meta if ok else None
    except (OSError, ValueError):
        return None


def _stamps(key_dir: Path) -> list[Path]:
    try:
        return sorted((d for d in key_dir.iterdir() if d.is_dir() and not d.name.endswith(".partial")), key=lambda d: d.name, reverse=True)
    except OSError:
        return []


def _snapshot(stamp_dir: Path, link: GithubLink, meta: dict, reused: bool) -> Snapshot:
    return Snapshot(
        stamp_dir / _inner(link), link, meta["fetched_at"], float(meta["epoch"]), meta["files"], meta["bytes"], dict(meta["skipped"]), reused,
        stamp_dir.name, meta["docs"] if isinstance(meta.get("docs"), int) and not isinstance(meta.get("docs"), bool) else None,
    )


def _base36(n: int) -> str:
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = ""
    while True:
        n, rest = divmod(n, 36)
        out = digits[rest] + out
        if n == 0:
            return out


def _move_into_place(partial: Path, final: Path) -> None:
    """Windows refuses to rename a folder while a program (a virus scanner, the search indexer) has a file in it open, which is likely for
    files that were just written. Try again for a moment before giving up."""
    for attempt in range(RENAME_TRIES):
        try:
            partial.rename(final)
            return
        except PermissionError:
            if attempt == RENAME_TRIES - 1:
                raise BadRequest(
                    "The downloaded copy could not be put in place: another program (a virus scanner, perhaps) is holding it. Try again in a moment."
                ) from None
            time.sleep(RENAME_DELAY * (attempt + 1))


def _prune(root: Path, key_dir: Path, link: GithubLink, now: float) -> None:
    """Keep the newest few snapshots of this repository and the newest few repositories, and clean away old half-made ones.

    A copy opened in the last USED_GRACE seconds is never removed (a request may be reading it), so a few extra copies may live a little longer.
    A repository whose lock is held (a request is opening or downloading it right now) is left alone for this round."""
    for old in _stamps(key_dir)[KEEP_PER_REPO:]:
        if not _recently_used(old, now):
            shutil.rmtree(old, ignore_errors=True)
    entries: list[tuple[str, Path]] = []
    try:
        for leaf in root.iterdir():
            for ref in leaf.iterdir() if leaf.is_dir() else []:
                for partial in [d for d in ref.iterdir() if d.is_dir() and d.name.endswith(".partial")] if ref.is_dir() else []:
                    if time.time() - partial.stat().st_mtime > PARTIAL_AGE:
                        shutil.rmtree(partial, ignore_errors=True)
                newest = _stamps(ref)
                if newest and ref != key_dir:
                    entries.append((newest[0].name, ref))
    except OSError:
        return
    entries.append((_stamps(key_dir)[0].name if _stamps(key_dir) else "", key_dir))
    entries.sort(key=lambda e: e[0], reverse=True)
    for _, ref in entries[MAX_REPOS:]:
        if ref == key_dir or any(_recently_used(d, now) for d in _stamps(ref)):  # key_dir's lock is held by our caller and is not re-entrant
            continue
        lock = _lock_for(ref)
        if not lock.acquire(blocking=False):  # a request is working on that repository: not now
            continue
        try:
            shutil.rmtree(ref, ignore_errors=True)
        finally:
            lock.release()
        try:
            ref.parent.rmdir()  # the repository's folder, once no branch of it is left
        except OSError:
            pass


def open_snapshot(
    link: GithubLink, *, fresh: bool = False, max_age: float | None = SNAPSHOT_TTL, root: Path | None = None,
    now=time.time, fetch=None, stamp: str | None = None,
) -> Snapshot:
    """The repository as a folder of source files on this computer, downloaded when there is none (or it is older than `max_age` seconds,
    None meaning any age, or `fresh` asks for a new one). Requests for the same repository at the same moment share one download.

    `stamp` asks for one particular copy (a `Snapshot.stamp`): the one an idea was made from. If it is still kept it is returned, whatever its
    age; if it has been pruned the usual rules apply and the caller can see from the returned stamp that it is another copy."""
    root = root if root is not None else snapshot_root()
    key_dir = _key_dir(root, link)
    key = str(key_dir)
    lock = _lock_for(key_dir)
    with _GUARD:
        generation = _GENERATION.get(key, 0)
    with lock:
        if stamp is not None:
            for d in _stamps(key_dir):
                wanted = _read_meta(d, link) if d.name == stamp else None
                if wanted is not None:
                    _mark_used(d, now())
                    return _snapshot(d, link, wanted, True)
        found = next(((d, m) for d in _stamps(key_dir) if (m := _read_meta(d, link)) is not None), None)
        if found is not None:
            stamp_dir, meta = found
            with _GUARD:
                fetched_meanwhile = _GENERATION.get(key, 0) != generation  # another request downloaded while this one waited
            if fetched_meanwhile or (not fresh and (max_age is None or now() - meta["epoch"] <= max_age)):
                _mark_used(stamp_dir, now())
                return _snapshot(stamp_dir, link, meta, True)
        data = (fetch or fetch_archive)(link)
        epoch = now()
        # 16 characters: the time in milliseconds in base 36 (padded, so names sort by time) and 6 of the content's hash. Short on purpose:
        # the snapshot's path is part of every file's path, and Windows allows 260.
        stamp = _base36(int(epoch * 1000)).rjust(9, "0") + "-" + hashlib.sha256(data).hexdigest()[:6]
        # 17 characters, at least as long as the stamp's 16: a file path that fits in the temporary folder is never longer than the room the final
        # place has (the other way round, a file could pass the check while unpacking and still not fit where it is kept).
        partial = key_dir / f"{uuid.uuid4().hex[:9]}.partial"
        final = key_dir / stamp
        try:
            partial.mkdir(parents=True, exist_ok=True)
            got = extract_sources(data, partial / _inner(link))
            meta = {
                "v": 2, "owner": link.owner, "repo": link.repo, "ref": link.ref, "epoch": epoch,
                "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch)), "files": got.files, "bytes": got.bytes, "skipped": got.skipped,
                "docs": got.docs,
            }
            (partial / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
            if final.exists() and _read_meta(final, link) is not None:  # the same bytes in the same millisecond: what is there is what this would be
                shutil.rmtree(partial, ignore_errors=True)
            else:
                if final.exists():  # a folder of that name whose record is damaged: replaced by the good copy
                    shutil.rmtree(final, ignore_errors=True)
                _move_into_place(partial, final)
        except OSError as exc:  # a disk that cannot hold it (a path too long, no room): said without the path the system's own text repeats
            shutil.rmtree(partial, ignore_errors=True)
            log.warning("a downloaded repository could not be stored: %s", exc)
            raise BadRequest(
                f"The downloaded copy could not be stored on this computer ({type(exc).__name__}). Check the free space and the data folder."
            ) from None
        except BaseException:
            shutil.rmtree(partial, ignore_errors=True)
            raise
        with _GUARD:
            _GENERATION[key] = _GENERATION.get(key, 0) + 1
        _mark_used(final, epoch)  # before pruning: the copy being handed out is in use, so it counts and is never the one removed
        _prune(root, key_dir, link, epoch)
        return _snapshot(final, link, meta, False)
