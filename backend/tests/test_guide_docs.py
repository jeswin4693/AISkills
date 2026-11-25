"""Slice AB: which files are documents, reading them safely, and a GitHub copy keeping them. Offline, no model."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from test_github_link import LEAF, Fetcher, snap, tree, zip_of

from skillforge.builder import BadRequest
from skillforge.builder import github as gh
from skillforge.guide import docs as gd

# ---- which files are documents -----------------------------------------------------------------------------


@pytest.mark.parametrize("parts,expected", [
    (["README.md"], True), (["README"], True), (["readme.rst"], True), (["Readme.txt"], True), (["README.markdown"], True),
    (["backend", "README.md"], True), (["a", "b", "c", "README.md"], True), (["a", "b", "c", "d", "README.md"], False),
    (["ARCHITECTURE.md"], True), (["CLAUDE.md"], True), (["AGENTS.md"], True), (["claude.md"], True),
    (["notes.md"], False), (["src", "CLAUDE.md"], False), (["src", "ARCHITECTURE.md"], False),
    (["docs", "guide.md"], True), (["docs", "a", "b", "c.md"], True), (["docs", "a", "b", "c", "d.md"], True), (["docs", "a", "b", "c", "d", "e.md"], False),
    (["Docs", "Intro.MD"], True), (["doc", "x.rst"], True), (["documentation", "x.adoc"], True),
    (["backend", "docs", "x.md"], True), (["src", "docs", "x.md"], True), (["a", "b", "docs", "x.md"], True),
    (["a", "b", "c", "docs", "x.md"], False), (["a", "b", "docs", "c", "d", "x.md"], False),  # the docs folder must be among the first three
    (["docs", "logo.png"], False), (["docs", "script.py"], False), (["docs", "noext"], False), (["src", "notdocs", "x.md"], False),
    (["readme.py"], False), (["readme_helper.py"], False), (["docs", ".md"], False), ([], False),
])
def test_a_document_is_a_readme_a_known_top_file_or_a_text_file_in_docs(parts, expected):
    assert gd.is_doc_path(parts) is expected


# ---- reading them from a folder ----------------------------------------------------------------------------


def test_documents_come_best_first_with_paths_relative_to_the_repository(repo):
    root = repo({
        "docs/zeta.md": "z\n" * 5, "docs/alpha.md": "a\n" * 5, "CLAUDE.md": "rules\n", "README.md": "# Shop\nIt sells.\n",
        "ARCHITECTURE.md": "layers\n", "docs/overview.md": "overview\n", "backend/README.md": "backend\n", "src/app.py": "x = 1\n",
    })
    got = gd.read_docs(root)
    assert [d.path for d in got.files] == [
        "README.md", "ARCHITECTURE.md", "CLAUDE.md", "docs/overview.md", "backend/README.md", "docs/alpha.md", "docs/zeta.md",
    ]
    assert all(not d.truncated and "\r" not in d.text for d in got.files)
    assert not any(p.startswith("/") or ":" in p or str(root) in p for p in (d.path for d in got.files))


def test_folders_the_graph_ignores_are_not_searched(repo):
    root = repo({"README.md": "# x\n", "node_modules/pkg/README.md": "junk\n", ".git/docs/a.md": "junk\n", "docs/real.md": "real\n"})
    assert [d.path for d in gd.read_docs(root).files] == ["README.md", "docs/real.md"]


def test_no_documents_is_an_empty_answer_not_an_error(repo):
    got = gd.read_docs(repo({"src/app.py": "x = 1\n"}))
    assert got.files == [] and got.view() == []


def test_a_binary_an_empty_file_and_a_huge_file_are_skipped_and_counted(repo, monkeypatch):
    root = repo({"README.md": "# ok\n", "docs/empty.md": "   \n", "docs/huge.md": "x" * 200})
    (root / "docs" / "bin.md").write_bytes(b"abc\x00def" * 10)
    monkeypatch.setattr(gd, "MAX_READ_BYTES", 150)
    got = gd.read_docs(root)
    assert [d.path for d in got.files] == ["README.md"]
    assert got.skipped == {"empty": 1, "too_large": 1, "binary": 1}


def test_a_long_document_is_cut_and_says_so(repo, monkeypatch):
    monkeypatch.setattr(gd, "MAX_FILE_CHARS", 1000)
    got = gd.read_docs(repo({"README.md": "word " * 1000}))
    assert len(got.files[0].text) == 1000 and got.files[0].truncated is True and got.view()[0]["truncated"] is True


def test_the_number_and_the_total_size_of_documents_are_limited(repo, monkeypatch):
    root = repo({"README.md": "r" * 900, "docs/a.md": "a" * 900, "docs/b.md": "b" * 900, "docs/c.md": "c" * 900})
    monkeypatch.setattr(gd, "MAX_FILES", 3)
    assert [d.path for d in gd.read_docs(root).files] == ["README.md", "docs/a.md", "docs/b.md"]
    monkeypatch.setattr(gd, "MAX_FILES", 12)
    monkeypatch.setattr(gd, "MAX_TOTAL_CHARS", 1500)
    got = gd.read_docs(root)
    assert [d.path for d in got.files] == ["README.md", "docs/a.md"] and got.files[1].truncated and sum(len(d.text) for d in got.files) == 1500
    assert got.skipped["limit"] == 2


def test_windows_line_endings_become_plain_ones(repo):
    root = repo({"src/app.py": "x = 1\n"})
    (root / "README.md").write_bytes(b"# Title\r\nline two\r\n")
    assert gd.read_docs(root).files[0].text == "# Title\nline two\n"


TREE = {"README.md": "# top\n", "docs/a.md": "a\n", "backend/README.md": "# backend\n", "backend/docs/api.md": "api\n", "backend/x.py": "x = 1\n"}


def test_a_focus_puts_the_documents_inside_it_first_and_leaves_the_rest_in_their_usual_order(repo):
    root = repo(TREE)
    assert [d.path for d in gd.read_docs(root).files] == ["README.md", "backend/README.md", "docs/a.md", "backend/docs/api.md"]
    assert [d.path for d in gd.read_docs(root, "backend").files] == ["backend/README.md", "backend/docs/api.md", "README.md", "docs/a.md"]


def test_a_focus_decides_what_is_read_first_when_there_is_no_room_for_all(repo, monkeypatch):
    monkeypatch.setattr(gd, "MAX_FILES", 2)
    assert [d.path for d in gd.read_docs(repo(TREE), "backend").files] == ["backend/README.md", "backend/docs/api.md"]
    assert [d.path for d in gd.read_docs(repo(TREE)).files] == ["README.md", "backend/README.md"]


@pytest.mark.parametrize("focus", ["../elsewhere", "nope", "/etc", "C:\\x", "README.md", "", "  ", "back", "backend/../docs", None, 7])
def test_a_focus_that_is_not_a_folder_inside_the_repository_changes_nothing(repo, focus):
    root = repo(TREE)
    assert [d.path for d in gd.read_docs(root, focus).files] == [d.path for d in gd.read_docs(root).files]  # "back" is not "backend"


def test_a_focus_is_never_looked_up_on_the_disk(repo, monkeypatch):
    seen = []
    real = Path.resolve

    def spy(self, *a, **k):
        seen.append(str(self))
        return real(self, *a, **k)

    root = repo(TREE)
    monkeypatch.setattr(Path, "resolve", spy)
    gd.read_docs(root, "../outside-the-repository")
    assert not any("outside-the-repository" in s for s in seen)


def test_pages_that_explain_the_structure_come_before_the_other_pages_and_case_does_not_decide(repo):
    root = repo({"README.md": "# top\n", "docs/Zebra.md": "z\n", "docs/alpha.md": "a\n", "docs/architecture-map.md": "m\n", "docs/how-it-works.md": "h\n", "src/x.py": "x = 1\n"})
    assert [d.path for d in gd.read_docs(root).files] == ["README.md", "docs/architecture-map.md", "docs/how-it-works.md", "docs/alpha.md", "docs/Zebra.md"]  # `alpha` before `Zebra`


def test_the_order_is_one_rule_for_the_unpacker_and_the_folder_reader():
    names = [["docs", "Zebra.md"], ["README.md"], ["Docs", "alpha.md"], ["backend", "README.md"], ["docs", "overview.md"], ["CLAUDE.md"], ["ARCHITECTURE.md"]]
    assert ["/".join(p) for p in sorted(names, key=gd.sort_key)] == [
        "README.md", "ARCHITECTURE.md", "CLAUDE.md", "docs/overview.md", "backend/README.md", "Docs/alpha.md", "docs/Zebra.md",
    ]  # `Docs/alpha.md` before `docs/Zebra.md`: the folder's case and the file's case do not decide


def test_a_huge_tree_is_searched_only_so_far(repo, monkeypatch):
    root = repo({"README.md": "# top\n", **{f"d{i:02d}/x.py": "x = 1\n" for i in range(10)}})
    monkeypatch.setattr(gd, "MAX_DIRS", 3)
    got = gd.read_docs(root)
    assert got.skipped.get("walk_limit") == 1 and [d.path for d in got.files] == ["README.md"]  # the top folder was looked into first


def test_a_focus_that_leads_to_another_real_folder_outside_the_repository_is_never_read(repo):
    root = repo({"README.md": "# mine\n", "src/a.py": "x = 1\n"})
    other = repo({"README.md": "# SOMEONE ELSE'S\n", "x.py": "y = 2\n"})  # a sibling folder: a real folder, outside the repository
    for focus in (f"../{other.name}", str(other), f"src/../../{other.name}"):
        got = gd.read_docs(root, focus)
        assert [d.path for d in got.files] == ["README.md"] and "SOMEONE ELSE" not in got.files[0].text, focus


def doc(path, size):
    return gd.DocFile(path, "x" * size)


def test_shrinking_keeps_the_best_documents_first_and_cuts_the_one_that_does_not_fit():
    docs = gd.DocSet([doc("README.md", 10_000), doc("CLAUDE.md", 10_000), doc("docs/a.md", 10_000)], {"binary": 1})
    got = gd.shrink(docs, 0.5)  # room for 15,000 of the 30,000 characters
    assert [(d.path, len(d.text), d.truncated) for d in got.files] == [("README.md", 10_000, False), ("CLAUDE.md", 5_000, True)]
    assert got.skipped == {"binary": 1, "limit": 1}  # the third was left out, and counted with the rest


def test_shrinking_leaves_the_input_alone_and_a_share_of_one_changes_nothing():
    docs = gd.DocSet([doc("README.md", 3_000), doc("docs/a.md", 2_000)], {"empty": 2})
    gd.shrink(docs, 0.25)
    assert [len(d.text) for d in docs.files] == [3_000, 2_000] and docs.skipped == {"empty": 2}
    same = gd.shrink(docs, 1.0)
    assert [(d.path, len(d.text), d.truncated) for d in same.files] == [("README.md", 3_000, False), ("docs/a.md", 2_000, False)]
    same.skipped["x"] = 1
    assert docs.skipped == {"empty": 2}  # the answer has its own copy of the counts


def test_the_first_document_is_always_kept_however_little_room_there_is():
    got = gd.shrink(gd.DocSet([doc("README.md", 5_000), doc("docs/a.md", 5_000)]), 0.0001)
    assert [(d.path, len(d.text), d.truncated) for d in got.files] == [("README.md", gd.MIN_ROOM, True)] and got.skipped == {"limit": 1}


def test_small_documents_all_stay_because_the_room_never_goes_below_the_floor():
    docs = gd.DocSet([doc("README.md", 300), doc("docs/a.md", 100)])
    assert [len(d.text) for d in gd.shrink(docs, 0.25).files] == [300, 100]


def test_a_document_with_almost_no_room_left_is_dropped_and_not_cut_to_a_stub():
    got = gd.shrink(gd.DocSet([doc("README.md", 10_000), doc("docs/a.md", 10_300)]), 0.5)  # room 10,150: 150 left after the first
    assert [d.path for d in got.files] == ["README.md"] and got.skipped == {"limit": 1}


@pytest.mark.skipif(os.name != "nt", reason="a junction is a Windows folder link")
def test_a_junction_inside_the_repository_that_points_outside_is_never_read(repo):
    root = repo({"README.md": "# mine\n", "src/a.py": "x = 1\n"})
    outside = repo({"README.md": "# SECRET\n", "docs/x.md": "secret words\n", "y.py": "y = 1\n"})
    made = subprocess.run(["cmd", "/c", "mklink", "/J", str(root / "docs"), str(outside / "docs")], capture_output=True)
    if made.returncode != 0:
        pytest.skip("this account cannot create a junction")
    got = gd.read_docs(root)
    assert [d.path for d in got.files] == ["README.md"] and "secret" not in json.dumps([d.text for d in got.files])
    assert got.skipped.get("not_a_file") == 1  # the file was found through the junction and refused, not silently missed


def test_a_symbolic_link_is_never_followed(repo, tmp_path):
    root = repo({"README.md": "# real\n"})
    secret = tmp_path / "secret.md"
    secret.write_text("TOP SECRET\n", encoding="utf-8")
    try:
        os.symlink(secret, root / "docs.md")
        os.symlink(secret, root / "ARCHITECTURE.md")
        os.symlink(tmp_path, root / "docs", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this account cannot create symbolic links")
    got = gd.read_docs(root)
    assert [d.path for d in got.files] == ["README.md"] and "TOP SECRET" not in json.dumps([d.text for d in got.files])


# ---- a GitHub copy keeps the documents -------------------------------------------------------------------------

SOURCE = {"src/a.py": "def a():\n    return 1\n"}


def test_documents_are_kept_next_to_the_source_and_everything_else_is_still_left_out(tmp_path):
    files = {**SOURCE, "README.md": "# hello\n", "docs/guide.md": "guide\n", "docs/logo.png": b"\x89PNG", "notes.md": "x\n", "LICENSE": "MIT\n"}
    out = gh.extract_sources(zip_of(files), tmp_path / LEAF)
    assert tree(tmp_path / LEAF) == ["README.md", "docs/guide.md", "src/a.py"]
    assert out.files == 1 and out.docs == 2 and out.skipped["not_source"] == 3
    assert [d.path for d in gd.read_docs(tmp_path / LEAF).files] == ["README.md", "docs/guide.md"]  # the folder rule and the copy rule agree


def test_documents_alone_are_still_not_a_repository_that_can_be_read(tmp_path):
    with pytest.raises(BadRequest, match="No source files"):
        gh.extract_sources(zip_of({"README.md": "# only docs\n", "docs/a.md": "x\n"}), tmp_path / LEAF)


def test_documents_have_their_own_limits_and_never_use_up_the_source_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(gh, "MAX_DOCS", 2)
    monkeypatch.setattr(gh, "MAX_FILES", 1)
    out = gh.extract_sources(zip_of({**SOURCE, "README.md": "1\n", "docs/a.md": "2\n", "docs/b.md": "3\n", "src/b.py": "x = 1\n"}), tmp_path / LEAF)
    assert out.files == 1 and out.docs == 2 and out.skipped["limit"] == 2  # the second source file and the third document


def test_a_document_over_its_size_limit_or_the_total_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(gh, "MAX_DOC_FILE", 10)
    out = gh.extract_sources(zip_of({**SOURCE, "README.md": "short\n", "docs/long.md": "x" * 11}), tmp_path / LEAF)
    assert tree(tmp_path / LEAF) == ["README.md", "src/a.py"] and out.skipped["too_large"] == 1
    monkeypatch.setattr(gh, "MAX_DOC_FILE", 100)
    monkeypatch.setattr(gh, "MAX_DOC_BYTES", 12)
    out = gh.extract_sources(zip_of({**SOURCE, "README.md": "12345678\n", "docs/b.md": "12345678\n"}), tmp_path / "again")
    assert out.docs == 1 and out.skipped["limit"] == 1


@pytest.mark.parametrize("name", ["docs/con.md", "docs/a:b.md", "docs/../../evil.md", "docs/x.md.", "docs/ x.md"])
def test_a_document_with_an_unsafe_name_is_skipped_like_any_other_file(tmp_path, name):
    from test_github_link import TOP, raw_zip

    dest = tmp_path / "out" / LEAF
    out = gh.extract_sources(raw_zip([(f"{TOP}/ok.py", "x = 1\n", None), (f"{TOP}/{name}", "pwned\n", None)]), dest)
    assert tree(dest) == ["ok.py"] and out.skipped.get("unsafe_name", 0) == 1 and out.docs == 0


def test_a_document_that_is_a_symbolic_link_is_never_written(tmp_path):
    from test_github_link import TOP, raw_zip

    out = gh.extract_sources(raw_zip([(f"{TOP}/ok.py", "x = 1\n", None), (f"{TOP}/README.md", "/etc/passwd", 0o120777)]), tmp_path / LEAF)
    assert tree(tmp_path / LEAF) == ["ok.py"] and out.skipped["link"] == 1


def test_the_readme_is_kept_even_when_many_doc_pages_come_before_it_in_the_archive(tmp_path):
    files = {**SOURCE, **{f"docs/page{i:02d}.md": f"# {i}\n" for i in range(70)}, "readme.md": "# the real readme\n"}  # `docs/` sorts before `readme.md`
    out = gh.extract_sources(zip_of(files), tmp_path / LEAF)
    assert out.docs == gh.MAX_DOCS == 60 and (tmp_path / LEAF / "readme.md").is_file() and out.skipped["limit"] == 11


def test_documents_are_kept_best_first_when_a_cap_cuts_some(tmp_path, monkeypatch):
    monkeypatch.setattr(gh, "MAX_DOCS", 3)
    files = {**SOURCE, "docs/z.md": "z\n", "docs/architecture.md": "arch\n", "docs/a.md": "a\n", "backend/README.md": "b\n", "README.md": "top\n"}
    gh.extract_sources(zip_of(files), tmp_path / LEAF)
    assert [p for p in tree(tmp_path / LEAF) if not p.endswith(".py")] == ["README.md", "backend/README.md", "docs/architecture.md"]


def test_a_copy_and_a_folder_keep_the_same_documents_when_there_is_no_room_for_all(tmp_path, repo, monkeypatch):
    files = {**SOURCE, "README.md": "top\n", "CLAUDE.md": "rules\n", "docs/zebra.md": "z\n", "docs/Alpha.md": "a\n", "docs/overview.md": "o\n", "backend/README.md": "b\n"}
    monkeypatch.setattr(gh, "MAX_DOCS", 4)
    monkeypatch.setattr(gd, "MAX_FILES", 4)
    gh.extract_sources(zip_of(files), tmp_path / LEAF)
    assert [d.path for d in gd.read_docs(tmp_path / LEAF).files] == [d.path for d in gd.read_docs(repo(files)).files]


def test_a_snapshot_records_how_many_documents_it_kept(tmp_path):
    s = snap(tmp_path, fetch=Fetcher({**SOURCE, "README.md": "# hello\n", "docs/a.md": "a\n"}))
    assert s.docs == 2 and (s.path / "README.md").is_file() and (s.path / "docs" / "a.md").is_file()
    assert snap(tmp_path, fetch=Fetcher({"src/z.py": "x = 1\n"})).docs == 2  # a reused copy says the same


def test_a_snapshot_made_before_documents_were_kept_says_it_does_not_know(tmp_path):
    s = snap(tmp_path, fetch=Fetcher(SOURCE))
    meta_file = s.path.parent / "meta.json"
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    meta.pop("docs")
    meta_file.write_text(json.dumps(meta), encoding="utf-8")
    assert snap(tmp_path, fetch=Fetcher(SOURCE)).docs is None
