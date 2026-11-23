"""Slice Y: read a public repository from its GitHub link. A link is parsed by a strict list, downloaded as a zip (never cloned), unpacked by
code that decides every file's name and place, and kept as a snapshot the rest of the pipeline reads like any folder. Offline: no test
touches the network (a fake opener or a fake download stands in for GitHub); hostile archives are built in memory."""

from __future__ import annotations

import io
import json
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_builder import FULL, finished, make  # noqa: F401  (make is a pytest fixture)
from test_evidence import APP, NOW, rebuild
from test_hosted import TOKEN, hosted
from test_library import NAME, write_skill
from test_skill_build import draft, round_two
from test_suggest import REPO, sug

from skillforge.api import create_app
from skillforge.builder import BadRequest, UpstreamError
from skillforge.builder import github as gh
from skillforge.builder.repository import check_repo
from skillforge.evidence import EVIDENCE_FILE
from skillforge.library import Library, import_skill
from skillforge.library.evidence import cite
from skillforge.suggest.models import SuggestionSet

LINK = "https://github.com/acme/shop-api"
LEAF = "acme__shop-api"
TOP = "acme-shop-api-0123abc"


def zip_of(files: dict[str, str | bytes], top: str = TOP) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, body in files.items():
            z.writestr(f"{top}/{name}", body)
    return buf.getvalue()


def raw_zip(entries: list[tuple[str, bytes | str, int | None]]) -> bytes:
    """Entries exactly as named (a hostile name is not tidied), each with an optional unix mode (0o120777 is a symbolic link)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, body, mode in entries:
            info = zipfile.ZipInfo(name)
            if mode is not None:
                info.external_attr = (mode & 0xFFFF) << 16
            z.writestr(info, body)
    return buf.getvalue()


SRC = {"src/a.py": "def a():\n    return 1\n", "README.md": "# hello\n", "docs/logo.png": b"\x89PNG"}


# ---- the link: a strict list ---------------------------------------------------------------------------------


@pytest.mark.parametrize("text, owner, repo, ref", [
    ("https://github.com/acme/shop-api", "acme", "shop-api", None),
    ("https://github.com/acme/shop-api/", "acme", "shop-api", None),
    ("https://github.com/acme/shop-api.git", "acme", "shop-api", None),
    ("https://www.github.com/acme/shop-api", "acme", "shop-api", None),
    ("HTTPS://GitHub.com/acme/shop-api", "acme", "shop-api", None),
    ("  https://github.com/acme/shop-api  ", "acme", "shop-api", None),
    ("github.com/acme/shop-api", "acme", "shop-api", None),
    ("https://github.com/acme/shop-api/tree/main", "acme", "shop-api", "main"),
    ("https://github.com/acme/shop-api/tree/v1.2.3/", "acme", "shop-api", "v1.2.3"),
    ("https://github.com/acme/shop-api?tab=readme-ov-file#top", "acme", "shop-api", None),
    ("https://github.com/a/b", "a", "b", None),
    ("https://github.com/Acme-Co/my.repo_x-y", "Acme-Co", "my.repo_x-y", None),
])
def test_a_github_link_is_read_into_owner_repo_and_branch(text, owner, repo, ref):
    link = gh.parse_link(text)
    assert link is not None and (link.owner, link.repo, link.ref) == (owner, repo, ref)
    assert link.url == f"https://github.com/{owner}/{repo}" + (f"/tree/{ref}" if ref else "")
    assert link.name == f"{owner}/{repo}" and link.leaf == f"{owner}__{repo}"


@pytest.mark.parametrize("text", [
    "http://github.com/acme/shop-api", "https://gitlab.com/acme/shop-api", "https://bitbucket.org/acme/shop-api",
    "https://github.com.evil.com/acme/shop-api", "https://evil.com/github.com/acme/shop-api", "https://github.com@evil.com/acme/shop-api",
    "https://user:pass@github.com/acme/shop-api", "https://github.com:8443/acme/shop-api", "https://githubXcom/acme/shop-api",
    "https://github.com/acme", "https://github.com/", "https://github.com", "github.com/acme", "github.com",
    "https://github.com/acme/shop-api/issues/1", "https://github.com/acme/shop-api/blob/main/a.py",
    "https://github.com/acme/shop-api/tree/feature/x", "https://github.com/acme/shop-api/tree/main/src", "https://github.com/acme/shop-api/tree/",
    "https://github.com/acme/../shop-api", "https://github.com/acme/..", "https://github.com/acme/.", "https://github.com/../shop-api",
    "https://github.com/-acme/shop-api", "https://github.com/acme-/shop-api", "https://github.com/ac_me/shop-api", "https://github.com/" + "a" * 40 + "/r",
    "https://github.com/acme/" + "r" * 101, "https://github.com/acme/shop%2Fapi", "https://github.com/acme/shop-api/tree/ma%69n",
    "https://github.com/acme/sh\u043ep-api", "https://github.com/acme/shop api", "https://github.com/acme/shop\tapi", "https://github.com/acme/shop;api",
    "ftp://github.com/acme/shop-api", "git://github.com/acme/shop-api", "ssh://git@github.com/acme/shop-api", "file:///C:/code/shop-api",
    "javascript://github.com/acme/shop-api", "data://github.com/acme/shop-api", "https://",
])
def test_anything_that_is_not_a_plain_github_repository_link_is_refused_without_repeating_it(text):
    with pytest.raises(BadRequest) as info:
        gh.parse_link(text)
    shown = str(info.value).replace(gh.HELP, "")  # the fixed help text names an example link; what the person typed must not come back
    assert text.strip() not in shown and "evil.com" not in str(info.value) and "pass" not in str(info.value).replace("passed", "")


@pytest.mark.parametrize("text", ["", "C:\\code\\shop-api", "C:/code/shop-api", "/home/me/shop-api", "relative/shop-api", "\\\\server\\share\\repo", "//server/share/repo",
                                  "C:\\github.com\\acme\\shop-api"])
def test_a_path_is_not_a_link_and_is_left_to_the_folder_rules(text):
    assert gh.parse_link(text) is None and not gh.looks_like_link(text)


def test_a_deeper_link_points_at_the_focus_box():
    with pytest.raises(BadRequest, match="Only this folder"):
        gh.parse_link("https://github.com/acme/shop-api/tree/main/src")


def test_the_download_address_is_built_only_from_checked_parts_on_the_download_host():
    assert gh.archive_urls(gh.parse_link(LINK)) == ["https://codeload.github.com/acme/shop-api/zip/HEAD"]
    assert gh.archive_urls(gh.parse_link(LINK + "/tree/v1.0")) == [
        "https://codeload.github.com/acme/shop-api/zip/refs/heads/v1.0", "https://codeload.github.com/acme/shop-api/zip/refs/tags/v1.0",
    ]


@pytest.mark.parametrize("url, ok", [
    ("https://codeload.github.com/acme/r/zip/HEAD", True), ("https://CodeLoad.GitHub.com/acme/r/zip/HEAD", True),
    ("https://evil.com/x", False), ("http://codeload.github.com/x", False), ("https://codeload.github.com.evil.com/x", False),
    ("https://codeload.github.com:444/x", False), ("https://user@codeload.github.com/x", False), ("https://github.com/acme/r/archive/HEAD.zip", False),
    ("file:///x", False), ("ftp://codeload.github.com/x", False), ("//codeload.github.com/x", False), ("", False),
])
def test_only_the_download_host_over_https_is_ever_followed(url, ok):
    assert gh.allowed_url(url) is ok


def test_a_redirect_to_any_other_place_is_refused():
    handler = gh._Redirects()
    req = urllib.request.Request("https://codeload.github.com/acme/r/zip/HEAD")
    with pytest.raises(UpstreamError, match="redirect"):
        handler.redirect_request(req, None, 302, "Found", {}, "https://evil.com/x")
    assert handler.redirect_request(req, None, 302, "Found", {}, "https://codeload.github.com/acme/r/zip/refs/heads/main") is not None


# ---- the download: limits and plain messages -----------------------------------------------------------------


class Resp:
    def __init__(self, body: bytes, length: str | None = "auto", clock=None, per_read: float = 0.0):
        self.body, self.pos, self.reads, self.per_read, self.clock = body, 0, 0, per_read, clock
        self.headers = {} if length is None else {"Content-Length": str(len(body)) if length == "auto" else length}

    def read(self, n: int = -1) -> bytes:
        self.reads += 1
        if self.clock is not None:
            self.clock.t += self.per_read
        chunk = self.body[self.pos:self.pos + (n if n and n > 0 else len(self.body))]
        self.pos += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Opener:
    def __init__(self, result):
        self.result, self.requests = result, []

    def open(self, req, timeout=None):
        self.requests.append((req, timeout))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


URL = "https://codeload.github.com/acme/shop-api/zip/HEAD"


def test_a_download_returns_the_zip_and_says_nothing_about_the_person():
    data = zip_of(SRC)
    opener = Opener(Resp(data))
    assert gh.download(URL, opener=opener) == data
    req, timeout = opener.requests[0]
    assert req.full_url == URL and timeout == gh.TIMEOUT
    sent = " ".join(f"{k}:{v}" for k, v in req.header_items()).lower()
    assert "skillforge" in sent and "cookie" not in sent and "authorization" not in sent


@pytest.mark.parametrize("error, exc_type, words", [
    (urllib.error.HTTPError(URL, 404, "Not Found", {}, None), BadRequest, "no public repository"),
    (urllib.error.HTTPError(URL, 403, "Forbidden", {}, None), UpstreamError, "refused"),
    (urllib.error.HTTPError(URL, 429, "Too Many", {}, None), UpstreamError, "refused"),
    (urllib.error.HTTPError(URL, 500, "Oops", {}, None), UpstreamError, "500"),
    (urllib.error.URLError("no route to host 10.0.0.7"), UpstreamError, "Could not reach GitHub"),
    (TimeoutError("timed out"), UpstreamError, "Could not reach GitHub"),
    (OSError("connection reset"), UpstreamError, "Could not reach GitHub"),
])
def test_a_failed_download_is_a_plain_message_that_repeats_nothing(error, exc_type, words):
    with pytest.raises(exc_type) as info:
        gh.download(URL, opener=Opener(error))
    assert words in str(info.value) and "10.0.0.7" not in str(info.value) and "acme" not in str(info.value)
    if words == "no public repository":
        assert "Private repositories cannot be read" in str(info.value)


def test_a_download_that_says_it_is_too_big_is_refused_before_it_is_read():
    resp = Resp(b"PK\x03\x04" + b"x" * 100, length=str(gh.MAX_DOWNLOAD + 1))
    with pytest.raises(BadRequest, match="too large"):
        gh.download(URL, opener=Opener(resp))
    assert resp.reads == 0


def test_a_download_that_lies_about_its_size_is_stopped_while_it_comes_in(monkeypatch):
    monkeypatch.setattr(gh, "MAX_DOWNLOAD", 200_000)
    monkeypatch.setattr(gh, "CHUNK", 50_000)
    resp = Resp(b"PK\x03\x04" + b"x" * 5_000_000, length=None)
    with pytest.raises(BadRequest, match="too large"):
        gh.download(URL, opener=Opener(resp))
    assert resp.pos <= 200_000 + 50_000


def test_a_download_that_takes_too_long_is_stopped():
    clock = Clock()
    resp = Resp(b"PK\x03\x04" + b"x" * 1_000_000, length=None, clock=clock, per_read=gh.DEADLINE / 3)
    with pytest.raises(UpstreamError, match="too long"):
        gh.download(URL, opener=Opener(resp), clock=clock)


def test_what_is_not_a_zip_is_refused():
    with pytest.raises(BadRequest, match="did not send a zip"):
        gh.download(URL, opener=Opener(Resp(b"<html>Not Found</html>")))


def test_a_download_is_only_ever_asked_of_the_download_host():
    with pytest.raises(BadRequest):
        gh.download("https://evil.com/x.zip", opener=Opener(Resp(zip_of(SRC))))


def test_a_branch_is_tried_as_a_branch_then_as_a_tag(monkeypatch):
    asked = []

    def fake(url, **kw):
        asked.append(url)
        if "/heads/" in url:
            raise gh.NotFound("no public repository")
        return b"zipbytes"

    monkeypatch.setattr(gh, "download", fake)
    assert gh.fetch_archive(gh.parse_link(LINK + "/tree/v1.0")) == b"zipbytes"
    assert asked == ["https://codeload.github.com/acme/shop-api/zip/refs/heads/v1.0", "https://codeload.github.com/acme/shop-api/zip/refs/tags/v1.0"]


def test_a_branch_that_is_neither_gives_the_not_found_message(monkeypatch):
    def fake(url, **kw):
        raise gh.NotFound("GitHub has no public repository (or branch) there.")

    monkeypatch.setattr(gh, "download", fake)
    with pytest.raises(BadRequest, match="no public repository"):
        gh.fetch_archive(gh.parse_link(LINK + "/tree/nope"))


# ---- unpacking: every name and place is decided here ----------------------------------------------------------


def tree(dest: Path) -> list[str]:
    return sorted(str(p.relative_to(dest)).replace("\\", "/") for p in dest.rglob("*") if p.is_file())


def test_only_source_files_are_written_and_the_top_folder_is_dropped(tmp_path):
    out = gh.extract_sources(zip_of({**SRC, "src/b.ts": "export const b = 1;\n", ".git/config": "x", "node_modules/m/i.js": "x", "__pycache__/a.py": "x"}), tmp_path / LEAF)
    assert tree(tmp_path / LEAF) == ["src/a.py", "src/b.ts"] and out.files == 2 and out.bytes > 0
    assert out.skipped["not_source"] == 2 and out.skipped["ignored_dir"] == 3 and sorted(p.name for p in tmp_path.iterdir()) == [LEAF]


def test_a_folder_that_the_graph_decides_about_is_kept(tmp_path):
    gh.extract_sources(zip_of({"build/__init__.py": "x = 1\n", "dist/m.py": "y = 2\n"}), tmp_path / LEAF)
    assert tree(tmp_path / LEAF) == ["build/__init__.py", "dist/m.py"]  # a Python package may be called build or dist: the graph reads it or not


@pytest.mark.parametrize("name", [
    "../evil.py", "src/../../evil.py", "src/../evil.py", "..\\evil.py", "src\\..\\..\\evil.py", "C:/evil.py", "src/C:/evil.py", "src/a:b.py",
    "src//x.py", "src/./x.py", "src/a\x1f.py", "src/a\x7f.py", "src/con.py", "src/CON.py", "aux/x.py", "src/nul.py", "src/COM1.py",
    "src/lpt9.py", "src/a.py.", "src/a.py ", "src/ a.py", "src/a*.py", "src/a?.py", 'src/a".py', "src/a<b.py", "src/a|b.py", "src/" + "n" * 130 + ".py",
    "/".join(["d"] * 120) + "/x.py",  # every name is fine; the path is over the limit
])
def test_an_unsafe_name_is_skipped_and_never_written_anywhere(tmp_path, name):
    dest = tmp_path / "out" / LEAF
    out = gh.extract_sources(raw_zip([(f"{TOP}/ok.py", "x = 1\n", None), (f"{TOP}/{name}", "pwned = 1\n", None)]), dest)
    assert tree(dest) == ["ok.py"] and out.skipped.get("unsafe_name", 0) == 1
    assert not [p for p in tmp_path.rglob("*") if p.is_file() and p.name.startswith("evil")]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["out"] and sorted(p.name for p in (tmp_path / "out").iterdir()) == [LEAF]


def test_a_nul_in_a_name_cannot_smuggle_anything_in(tmp_path):
    """Python's own zip reader cuts a name at the first NUL, so `a.py` + NUL + `.txt` is the name `a.py` and `a` + NUL + `.py` is `a`
    (not source). Either way only what the checks would have allowed is written, and the entry that should be refused is not written."""
    dest = tmp_path / LEAF
    nul = chr(0)
    gh.extract_sources(raw_zip([(f"{TOP}/ok.py", "x = 1\n", None), (f"{TOP}/src/a{nul}.py", "pwned = 1\n", None), (f"{TOP}/b.txt{nul}.py", "pwned = 2\n", None)]), dest)
    assert tree(dest) == ["ok.py"]
    assert not any("pwned" in p.read_text(encoding="utf-8") for p in dest.rglob("*") if p.is_file())


@pytest.mark.parametrize("entries", [
    [("/etc/x.py", "x", None), (f"{TOP}/ok.py", "x", None)],
    [("evil.py", "x", None), (f"{TOP}/ok.py", "x", None)],
    [("other-top/x.py", "x", None), (f"{TOP}/ok.py", "x", None)],
    [("../x.py", "x", None)],
    [("\\x.py", "x", None)],
])
def test_an_archive_that_is_not_one_folder_is_refused_whole_and_writes_nothing(tmp_path, entries):
    dest = tmp_path / "out" / LEAF
    with pytest.raises(BadRequest, match="layout"):
        gh.extract_sources(raw_zip(entries), dest)
    assert not [p for p in tmp_path.rglob("*") if p.is_file()]


def test_a_symbolic_link_or_a_device_is_never_written(tmp_path):
    dest = tmp_path / LEAF
    out = gh.extract_sources(raw_zip([
        (f"{TOP}/ok.py", "x = 1\n", 0o100644), (f"{TOP}/link.py", "../../secret.py", 0o120777), (f"{TOP}/dev.py", "x", 0o020666), (f"{TOP}/fifo.py", "x", 0o010644),
    ]), dest)
    assert tree(dest) == ["ok.py"] and out.skipped["link"] == 3


def test_a_file_over_the_limit_is_skipped(tmp_path):
    big = "x = 1\n" * 300_000  # 1.8 MB: the graph reads nothing over 1 MB, so it is not written
    out = gh.extract_sources(zip_of({"big.py": big, "ok.py": "y = 2\n"}), tmp_path / LEAF)
    assert tree(tmp_path / LEAF) == ["ok.py"] and out.skipped["too_large"] == 1


def test_a_zip_bomb_is_never_unpacked(tmp_path):
    bomb = zip_of({"boom.py": b"\x00" * 3_000_000, "ok.py": "z = 1\n"})  # 3 MB of zeros is a few KB compressed
    start = time.monotonic()
    out = gh.extract_sources(bomb, tmp_path / LEAF)
    assert tree(tmp_path / LEAF) == ["ok.py"] and out.skipped["too_large"] == 1 and time.monotonic() - start < 5


def test_the_number_of_files_and_the_unpacked_size_are_limited(tmp_path, monkeypatch):
    many = {f"d/f{i}.py": f"v{i} = {i}\n" for i in range(10)}
    monkeypatch.setattr(gh, "MAX_FILES", 4)
    out = gh.extract_sources(zip_of(many), tmp_path / "a" / LEAF)
    assert out.files == 4 and len(tree(tmp_path / "a" / LEAF)) == 4 and out.skipped["limit"] == 6
    monkeypatch.setattr(gh, "MAX_FILES", 20_000)
    monkeypatch.setattr(gh, "MAX_UNPACKED", 60)
    out = gh.extract_sources(zip_of(many), tmp_path / "b" / LEAF)
    assert 0 < out.files < 10 and out.bytes <= 60 and out.skipped["limit"] == 10 - out.files


def test_too_many_entries_are_refused_before_any_is_read(tmp_path, monkeypatch):
    monkeypatch.setattr(gh, "MAX_ENTRIES", 5)
    with pytest.raises(BadRequest, match="too many"):
        gh.extract_sources(zip_of({f"f{i}.py": "x" for i in range(9)}), tmp_path / LEAF)
    assert not (tmp_path / LEAF).exists() or not tree(tmp_path / LEAF)


def test_two_names_that_differ_only_in_case_are_one_file_where_the_disk_does_not_care(tmp_path):
    out = gh.extract_sources(raw_zip([(f"{TOP}/A.py", "one = 1\n", None), (f"{TOP}/a.py", "two = 2\n", None), (f"{TOP}/b.py", "b = 1\n", None)]), tmp_path / LEAF)
    assert len(tree(tmp_path / LEAF)) == 2 and out.skipped["duplicate"] == 1


def test_an_archive_with_no_source_in_a_language_that_is_read_says_so(tmp_path):
    with pytest.raises(BadRequest, match="No source files"):
        gh.extract_sources(zip_of({"README.md": "# x", "logo.png": b"x"}), tmp_path / LEAF)


def test_a_file_that_is_not_a_zip_is_refused_in_plain_words(tmp_path):
    with pytest.raises(BadRequest, match="not a valid zip"):
        gh.extract_sources(b"PK\x03\x04 truncated nonsense", tmp_path / LEAF)


def test_file_contents_are_written_exactly_and_without_the_execute_bit(tmp_path):
    gh.extract_sources(zip_of({"src/a.py": "def a():\n    return 'é'\n"}), tmp_path / LEAF)
    path = tmp_path / LEAF / "src" / "a.py"
    assert path.read_bytes() == "def a():\n    return 'é'\n".encode("utf-8")


# ---- snapshots: kept, reused, replaced, pruned -----------------------------------------------------------------


class Fetcher:
    def __init__(self, files=None):
        self.files, self.calls, self.lock = files or SRC, [], threading.Lock()

    def __call__(self, link):
        with self.lock:
            self.calls.append(link.url)
        time.sleep(0.02)
        return zip_of(self.files)


class Tick:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def snap(tmp_path, link=LINK, fetch=None, clock=None, **kw):
    return gh.open_snapshot(gh.parse_link(link), root=tmp_path / "snaps", now=clock or Tick(), fetch=fetch or Fetcher(), **kw)


def test_the_first_read_downloads_and_the_folder_is_named_for_the_repository(tmp_path):
    fetch = Fetcher()
    s = snap(tmp_path, fetch=fetch)
    assert s.path.name == LEAF and s.path.is_dir() and (s.path / "src" / "a.py").is_file() and s.reused is False
    assert s.files == 1 and s.skipped["not_source"] == 2 and s.fetched_at.endswith("Z") and fetch.calls == [LINK]
    assert (tmp_path / "snaps") in s.path.parents


def test_a_second_read_soon_after_reuses_the_snapshot_and_a_later_one_downloads_again(tmp_path):
    fetch, clock = Fetcher(), Tick()
    first = snap(tmp_path, fetch=fetch, clock=clock)
    clock.t += gh.SNAPSHOT_TTL - 1
    again = snap(tmp_path, fetch=fetch, clock=clock)
    assert again.path == first.path and again.reused is True and len(fetch.calls) == 1
    clock.t += 2
    later = snap(tmp_path, fetch=fetch, clock=clock)
    assert later.path != first.path and later.reused is False and len(fetch.calls) == 2


def test_fresh_always_downloads_and_no_age_limit_reuses_whatever_is_there(tmp_path):
    fetch, clock = Fetcher(), Tick()
    first = snap(tmp_path, fetch=fetch, clock=clock)
    clock.t += 30 * 24 * 3600
    assert snap(tmp_path, fetch=fetch, clock=clock, max_age=None).path == first.path and len(fetch.calls) == 1
    clock.t += 5
    assert snap(tmp_path, fetch=fetch, clock=clock, fresh=True).path != first.path and len(fetch.calls) == 2


def test_a_branch_and_the_default_branch_are_separate_snapshots(tmp_path):
    fetch = Fetcher()
    a, b = snap(tmp_path, LINK, fetch), snap(tmp_path, LINK + "/tree/dev", fetch)
    assert a.path != b.path and len(fetch.calls) == 2 and snap(tmp_path, LINK + "/tree/dev", fetch).reused is True


def test_only_the_newest_two_snapshots_of_a_repository_are_kept(tmp_path):
    fetch, clock = Fetcher(), Tick()
    paths = []
    for _ in range(4):
        paths.append(snap(tmp_path, fetch=fetch, clock=clock, fresh=True).path)
        clock.t += 100
    assert [p.is_dir() for p in paths] == [False, False, True, True]


def test_only_a_limited_number_of_repositories_are_kept_oldest_first(tmp_path, monkeypatch):
    monkeypatch.setattr(gh, "MAX_REPOS", 3)
    fetch, clock = Fetcher(), Tick()
    made = []
    for i in range(5):
        made.append(snap(tmp_path, f"https://github.com/acme/repo{i}", fetch, clock).path)
        clock.t += 10
    assert [p.is_dir() for p in made] == [False, False, True, True, True]


def test_a_failed_download_leaves_the_old_snapshot_usable_and_no_partial_folder(tmp_path):
    fetch, clock = Fetcher(), Tick()
    first = snap(tmp_path, fetch=fetch, clock=clock)
    clock.t += 5000

    def boom(link):
        raise UpstreamError("Could not reach GitHub (TimeoutError).")

    with pytest.raises(UpstreamError):
        snap(tmp_path, fetch=boom, clock=clock)
    assert first.path.is_dir() and not list((tmp_path / "snaps").rglob("*.partial"))
    assert snap(tmp_path, fetch=fetch, clock=clock, max_age=None).path == first.path


def test_a_snapshot_that_cannot_be_unpacked_leaves_nothing_behind(tmp_path):
    with pytest.raises(BadRequest, match="No source files"):
        snap(tmp_path, fetch=Fetcher({"README.md": "# nothing to read"}))
    assert not [p for p in (tmp_path / "snaps").rglob("*") if p.is_file()]


def test_a_leftover_partial_folder_is_cleaned_up_when_it_is_old(tmp_path):
    clock = Tick()
    snap(tmp_path, fetch=Fetcher(), clock=clock)
    stale = tmp_path / "snaps" / LEAF / "default" / "20200101T000000Z-deadbeef.partial"
    (stale / LEAF).mkdir(parents=True)
    old = time.time() - 3 * 3600
    import os
    os.utime(stale, (old, old))
    clock.t += 10
    snap(tmp_path, fetch=Fetcher(), clock=clock, fresh=True)
    assert not stale.exists()


def test_eight_requests_at_once_download_once_and_share_the_snapshot(tmp_path):
    fetch, results = Fetcher(), []

    def go():
        results.append(snap(tmp_path, fetch=fetch).path)

    threads = [threading.Thread(target=go) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(fetch.calls) == 1 and len(set(results)) == 1 and len(results) == 8


def hold(monkeypatch, times: int | None):
    """Make the move of a finished download into place fail the way Windows does while a scanner holds a file in it."""
    monkeypatch.setattr(gh, "RENAME_DELAY", 0)
    real, state = Path.rename, {"n": 0}

    def flaky(self, target):
        if self.name.endswith(".partial") and (times is None or state["n"] < times):
            state["n"] += 1
            raise PermissionError(5, "Access is denied")
        return real(self, target)

    monkeypatch.setattr(Path, "rename", flaky)
    return state


def test_a_folder_that_another_program_holds_for_a_moment_is_moved_into_place_when_it_lets_go(tmp_path, monkeypatch):
    state = hold(monkeypatch, 2)
    s = snap(tmp_path)
    assert s.path.is_dir() and (s.path / "src" / "a.py").is_file() and state["n"] == 2


def test_a_folder_that_stays_held_is_a_plain_message_and_leaves_nothing_behind(tmp_path, monkeypatch):
    state = hold(monkeypatch, None)
    with pytest.raises(BadRequest, match="another program"):
        snap(tmp_path)
    assert state["n"] == gh.RENAME_TRIES and not list((tmp_path / "snaps").rglob("*.partial"))


def test_a_file_whose_path_would_not_fit_on_this_disk_is_skipped_by_name_not_by_failing(tmp_path, monkeypatch):
    dest = tmp_path / LEAF
    monkeypatch.setattr(gh, "PATH_LIMIT", len(str(dest)) + 30)
    out = gh.extract_sources(zip_of({"short.py": "x = 1\n", "a/very/long/directory/name/that/goes/past/the/limit/x.py": "y = 2\n"}), dest)
    assert tree(dest) == ["short.py"] and out.skipped == {"path_too_long": 1}  # named, and not the vague 'unwritable'


def test_the_folder_a_download_is_unpacked_into_is_never_longer_than_its_final_place(tmp_path, monkeypatch):
    """Windows allows 260 characters of path. If the temporary folder were longer than the final one, a file that fits in its final
    place could still fail while unpacking."""
    seen = []
    real = gh.extract_sources

    def spy(data, dest):
        seen.append(len(str(dest)))
        return real(data, dest)

    monkeypatch.setattr(gh, "extract_sources", spy)
    s = snap(tmp_path)
    assert seen and seen[0] <= len(str(s.path))


def test_snapshot_folder_names_are_short_and_still_sort_by_time(tmp_path):
    fetch, clock = Fetcher(), Tick()
    names = []
    for _ in range(3):
        names.append(snap(tmp_path, fetch=fetch, clock=clock, fresh=True).path.parent.name)
        clock.t += 1000
    assert all(len(n) == 16 for n in names) and names == sorted(names) and len(set(names)) == 3


def test_simultaneous_requests_for_a_fresh_copy_share_one_download(tmp_path):
    """A plain read already reuses a copy that is young enough. A request that insists on a fresh one, made while another one is being
    downloaded, must not start a second download of the same thing as soon as the first finishes."""
    fetch, clock = Fetcher(), Tick()
    snap(tmp_path, fetch=fetch, clock=clock)
    clock.t += 5000
    results = []

    def go():
        results.append(snap(tmp_path, fetch=fetch, clock=clock, fresh=True).path)

    threads = [threading.Thread(target=go) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(fetch.calls) == 2 and len(set(results)) == 1  # the first read, and one shared fresh download


def test_a_damaged_snapshot_record_is_not_trusted(tmp_path):
    fetch, clock = Fetcher(), Tick()
    first = snap(tmp_path, fetch=fetch, clock=clock)
    (first.path.parent / "meta.json").write_text("{not json", encoding="utf-8")
    clock.t += 1
    again = snap(tmp_path, fetch=fetch, clock=clock)
    assert again.path != first.path and len(fetch.calls) == 2 and again.reused is False


def test_a_damaged_record_in_a_folder_of_the_very_same_name_is_replaced_not_kept(tmp_path):
    fetch, clock = Fetcher(), Tick()  # the same bytes in the same instant: the new folder would have the damaged one's name
    first = snap(tmp_path, fetch=fetch, clock=clock)
    (first.path.parent / "meta.json").write_text("{not json", encoding="utf-8")
    again = snap(tmp_path, fetch=fetch, clock=clock)
    assert again.path == first.path and (again.path / "src" / "a.py").is_file()
    assert snap(tmp_path, fetch=fetch, clock=clock).reused is True and len(fetch.calls) == 2  # and the replacement is trusted


# ---- the rest of the pipeline sees a link like a folder ----------------------------------------------------------


@pytest.fixture
def served(monkeypatch):
    """The archive GitHub 'serves' for any link, and how many times it was asked."""
    state = {"files": dict(REPO), "calls": 0, "error": None}

    def fetch(link):
        state["calls"] += 1
        if state["error"]:
            raise state["error"]
        return zip_of(state["files"])

    monkeypatch.setattr(gh, "fetch_archive", fetch)
    return state


def managed_path_leaks(doc) -> bool:
    return json.dumps(str(gh.snapshot_root()))[1:-1] in json.dumps(doc) or "codeload" in json.dumps(doc)


def test_check_repo_turns_a_link_into_a_folder_and_leaves_paths_alone(served, tmp_path):
    folder = check_repo(LINK)
    assert folder.is_dir() and folder.name == LEAF and (folder / "core.py").is_file()
    here = tmp_path / "github.com" / "x"
    here.mkdir(parents=True)
    assert check_repo(str(here)) == here.resolve()  # a path with "github.com" in it is still a path


def test_analyze_reads_a_link_and_says_where_it_came_from_without_a_path(served, make):
    env = make([])
    r = env.client.post("/api/repos/analyze", json={"path": LINK})
    doc = r.json()
    assert r.status_code == 200 and doc["name"] == "acme/shop-api" and doc["stats"]["files"] == 3 and "root" not in doc["stats"]
    src = doc["source"]
    assert src["kind"] == "github" and (src["owner"], src["repo"], src["ref"]) == ("acme", "shop-api", None) and src["url"] == LINK
    assert src["files"] == 3 and src["fetched_at"].endswith("Z") and isinstance(src["skipped"], dict) and src["reused"] is False
    assert not managed_path_leaks(doc)
    assert env.client.post("/api/repos/analyze", json={"path": LINK}).json()["source"]["reused"] is True and served["calls"] == 1


def test_analyze_of_a_folder_is_unchanged_apart_from_saying_it_is_a_folder(make, repo):
    root = repo(REPO)
    doc = make([]).client.post("/api/repos/analyze", json={"path": str(root)}).json()
    assert doc["name"] == root.name and doc["source"] == {"kind": "folder"}


@pytest.mark.parametrize("bad", ["https://gitlab.com/acme/shop-api", "https://github.com/acme", "http://github.com/acme/shop-api"])
def test_a_link_that_is_refused_is_a_plain_400(served, make, bad):
    r = make([]).client.post("/api/repos/analyze", json={"path": bad})
    assert r.status_code == 400 and bad not in r.text and served["calls"] == 0


def test_a_repository_that_is_not_there_is_a_400_and_an_unreachable_github_is_a_502(served, make):
    env = make([])
    served["error"] = gh.NotFound(gh.NOT_FOUND)
    r = env.client.post("/api/repos/analyze", json={"path": LINK})
    assert r.status_code == 400 and "Private repositories cannot be read" in r.json()["detail"]
    served["error"] = UpstreamError("Could not reach GitHub (TimeoutError).")
    r = env.client.post("/api/repos/analyze", json={"path": LINK})
    assert r.status_code == 502 and "Could not reach GitHub" in r.json()["detail"]


def test_a_link_is_off_in_the_hosted_version_and_nothing_is_downloaded(served, tmp_path):
    lib = Library(tmp_path / "library")
    client = TestClient(create_app(lib, hosted=hosted()), base_url="http://localhost")
    assert client.post("/api/auth/login", json={"token": TOKEN}).status_code == 200
    for path, body in (("/api/repos/analyze", {"path": LINK}), ("/api/suggestions", {"path": LINK}),
                       ("/api/builds", {"description": FULL, "repo": LINK, "evidence_nodes": ["core.py"]})):
        assert client.post(path, json=body).status_code == 403, path
    assert served["calls"] == 0


REVIEW = SuggestionSet(suggestions=[sug()])
IDEAS = SuggestionSet(suggestions=[sug(
    title="Explain what a change to shared touches", category="skill", evidence=["core.py::shared"],
    skill_requirement="A skill that, given a function name, lists the files a change to it would touch.",
)])


def test_a_suggestion_run_on_a_link_is_named_for_the_repository_and_stores_the_link_not_a_path(served, make):
    env = make([REVIEW, IDEAS])
    r = env.client.post("/api/suggestions", json={"path": LINK})
    run = env.client.get(f"/api/suggestions/{r.json()['id']}").json()
    assert r.status_code == 201 and run["status"] == "done" and run["repo"] == "acme/shop-api" and not managed_path_leaks(run)
    assert {s["title"] for s in run["result"]["suggestions"]} == {"Merge the duplicate normalisers", "Explain what a change to shared touches"}
    from sqlalchemy import select

    from skillforge.db import SuggestRun
    with env.db.session() as s:
        assert [row.repo for row in s.execute(select(SuggestRun)).scalars()] == [LINK]


def test_a_second_click_on_a_link_while_it_is_still_asked_gets_the_same_run(served, make):
    env = make([REVIEW, IDEAS], inline=False)
    a = env.client.post("/api/suggestions", json={"path": LINK}).json()
    b = env.client.post("/api/suggestions", json={"path": LINK + "/"}).json()
    assert a["id"] == b["id"]


def test_a_run_whose_repository_cannot_be_downloaded_fails_with_a_reason_and_can_be_retried(served, make):
    env = make([REVIEW, IDEAS])
    served["error"] = UpstreamError("Could not reach GitHub (TimeoutError).")
    r = env.client.post("/api/suggestions", json={"path": LINK})
    assert r.status_code == 502 and env.mock.calls == []  # checked before any model is asked


def seeded_link(env, nodes=("core.py::shared", "a.py", "gone.py")):
    return env.start(FULL, repo=LINK, evidence_nodes=list(nodes))["id"]


def test_a_build_seeded_from_a_link_ends_with_evidence_and_shows_the_repository_name(served, make):
    env = make([round_two(), draft()])
    sid = seeded_link(env)
    session = env.post(sid, "approve").json()
    assert session["status"] == "done" and session["seed"] == {"repo": "acme/shop-api", "focus": None, "places": 3} and not managed_path_leaks(session)
    assert EVIDENCE_FILE in session["result"]["files"] and session["result"]["evidence"]["places"] == 2
    assert session["result"]["evidence"]["repo"] == LEAF


def age_every_snapshot(seconds: float) -> int:
    """Make each snapshot on disk look `seconds` older, by changing the time its own record says it was made (patching the clock would
    not reach the code: it takes `time.time` as a default argument, which Python fixes once, when the function is defined)."""
    changed = 0
    for meta_file in gh.snapshot_root().rglob("meta.json"):
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        meta["epoch"] -= seconds
        meta_file.write_text(json.dumps(meta), encoding="utf-8")
        changed += 1
    return changed


def test_a_build_reuses_the_snapshot_its_idea_was_made_from_however_old_it_is(served, make):
    env = make([round_two(), draft()])
    sid = seeded_link(env)
    first = served["calls"]
    assert age_every_snapshot(3 * 24 * 3600) == 1  # days pass before the person approves: far older than a plain read would reuse
    session = env.post(sid, "approve").json()
    assert session["status"] == "done" and served["calls"] == first and EVIDENCE_FILE in session["result"]["files"]


def test_a_plain_read_of_an_old_snapshot_does_download_again(served, make):
    """The other side of the test above: age alone is what makes the difference, so the claim that a build ignores age is a real one."""
    env = make([])
    assert env.client.post("/api/repos/analyze", json={"path": LINK}).status_code == 200
    assert age_every_snapshot(3 * 24 * 3600) == 1
    assert env.client.post("/api/repos/analyze", json={"path": LINK}).json()["source"]["reused"] is False and served["calls"] == 2


def test_a_recheck_against_a_link_always_downloads_fresh_and_sees_what_changed(served, tmp_path):
    lib = Library(tmp_path / "library")
    assert not import_skill(write_skill(tmp_path / NAME), lib).refused
    served["files"] = dict(APP)
    cite(lib, NAME, rebuild(check_repo(LINK)), ["svc.py::parse", "svc.py::clean"], now=NOW)
    client = TestClient(create_app(lib), base_url="http://localhost")
    before = served["calls"]
    ok = client.post(f"/api/library/{NAME}/recheck", json={"repo": LINK}).json()
    assert ok["ok"] is True and ok["counts"] == {"holds": 2} and served["calls"] == before + 1
    served["files"] = {**APP, "svc.py": "def parse(raw):\n    return raw\n"}
    changed = client.post(f"/api/library/{NAME}/recheck", json={"repo": LINK}).json()
    assert served["calls"] == before + 2 and changed["ok"] is False and changed["counts"] == {"missing": 1, "changed": 1}
    assert not any("same repository" in n for n in changed["notes"]) and not managed_path_leaks(changed)


# ---- which names may be written at all (unsafe_part): refuse what is dangerous, keep what is ordinary ----------------------


def test_ordinary_names_are_never_refused():
    ordinary = [
        "a.py", "src", "__init__.py", "build", "my.module.py", "file-name_v2.0.py", ".gitignore", "...x.py", "context.py", "console.py", "aux2.py",
        "com10.py", "noc.py", "icon.ts", "a b.py", "a-b+c@d.py", "d" * 120, "caf" + chr(0xE9) + ".py", chr(0x4E2D) + chr(0x6587) + ".py",
    ]
    for name in ordinary:
        assert gh.unsafe_part(name) is False, name


def test_dangerous_names_are_refused():
    devices = ["con", "CON", "Con.txt", "con.tar.gz", "prn", "AUX.py", "nul", "com0", "com1", "COM9.py", "lpt1.py", "lpt0", "conin$", "CONOUT$.x",
               "con .py", "com1 .txt", "com" + chr(0xB9), "lpt" + chr(0xB2) + ".txt", "COM" + chr(0xB3)]
    shape = ["", ".", "..", "...", "a.py.", "a.py ", " a.py", "a" * 121]
    invisible = [
        "a" + chr(0) + "b", chr(0x1F), chr(0x7F), "a" + chr(0x80) + "b", "a" + chr(0x202E) + "b.py", "a" + chr(0x200B) + "b.py",
        chr(0xFEFF) + "a.py", "a" + chr(0x2028) + "b", "a" + chr(0x2029) + "b", "a" + chr(0xD800) + "b",
    ]
    forbidden = ["a" + ch + "b.py" for ch in chr(92) + ":*?" + chr(34) + "<>|"]
    for name in devices + shape + invisible + forbidden:
        assert gh.unsafe_part(name) is True, repr(name)


def test_the_whole_path_is_limited_as_well_as_each_name(tmp_path):
    deep = "/".join(["d" * 20] * 12) + "/x.py"  # every name is fine, the path is over the limit
    out = gh.extract_sources(zip_of({deep: "x = 1\n", "ok.py": "y = 2\n"}), tmp_path / LEAF)
    assert tree(tmp_path / LEAF) == ["ok.py"] and out.skipped["unsafe_name"] == 1


def test_a_long_branch_name_in_the_top_folder_does_not_stop_the_download(tmp_path):
    top = "shop-api-" + "feature-" * 30  # the top folder is dropped, never written
    gh.extract_sources(zip_of({"a.py": "x = 1\n"}, top=top), tmp_path / LEAF)
    assert tree(tmp_path / LEAF) == ["a.py"]
