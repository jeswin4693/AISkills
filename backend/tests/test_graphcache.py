"""Slice AL: the graphs the function explorer reads are kept in memory, so a click is not a re-read of the whole repository.

A kept graph is used only while every file is exactly as it was (same name, size and modification time); anything else reads it afresh. The graph is
shared by requests that run at the same time, so reading it must never change it."""

from __future__ import annotations

import os
import threading

import pytest

from skillforge.builder import graphcache
from skillforge.graph.callgraph import call_graph

SHOP = {
    "shop.py": "def price():\n    return 1\n\n\ndef checkout():\n    return price()\n",
    "web.py": "from shop import checkout\n\n\ndef handle():\n    return checkout()\n",
}


@pytest.fixture(autouse=True)
def fresh():
    graphcache.clear()
    yield
    graphcache.clear()


@pytest.fixture
def builds(monkeypatch):
    calls: list[dict] = []
    real = graphcache.build_graph

    def counting(*args, **kwargs):
        calls.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(graphcache, "build_graph", counting)
    return calls


def test_the_second_read_of_an_unchanged_folder_does_not_read_it_again(repo, builds):
    folder = repo(SHOP)
    first = graphcache.graph_for(folder, None)
    second = graphcache.graph_for(folder, None)
    assert second is first and len(builds) == 1


def test_an_edited_file_is_read_afresh_and_the_new_graph_shows_the_edit(repo, builds):
    folder = repo(SHOP)
    assert "audit" not in {s.name for s in graphcache.graph_for(folder, None).symbols.values()}
    (folder / "shop.py").write_text(SHOP["shop.py"] + "\n\ndef audit():\n    return 3\n")
    assert "audit" in {s.name for s in graphcache.graph_for(folder, None).symbols.values()}
    assert len(builds) == 2


def test_an_edit_that_keeps_the_size_is_still_noticed_by_its_modification_time(repo, builds):
    folder = repo(SHOP)
    graphcache.graph_for(folder, None)
    shop = folder / "shop.py"
    stat = shop.stat()
    shop.write_text(SHOP["shop.py"].replace("def price", "def rpice"))  # same number of characters
    os.utime(shop, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))  # and a clearly later time, whatever the disk's clock resolution
    assert shop.stat().st_size == stat.st_size
    assert "rpice" in {s.name for s in graphcache.graph_for(folder, None).symbols.values()}
    assert len(builds) == 2


def test_an_edit_that_keeps_the_modification_time_is_still_noticed_by_its_size(repo, builds):
    folder = repo(SHOP)
    graphcache.graph_for(folder, None)
    shop = folder / "shop.py"
    stat = shop.stat()
    shop.write_text(SHOP["shop.py"] + "\n\ndef audit():\n    return 3\n")
    os.utime(shop, ns=(stat.st_atime_ns, stat.st_mtime_ns))  # a tool that puts the old time back
    assert shop.stat().st_mtime_ns == stat.st_mtime_ns and shop.stat().st_size != stat.st_size
    assert "audit" in {s.name for s in graphcache.graph_for(folder, None).symbols.values()}
    assert len(builds) == 2


def test_a_renamed_file_is_noticed_although_its_size_and_time_are_the_same(repo, builds):
    folder = repo(SHOP)
    graphcache.graph_for(folder, None)
    (folder / "shop.py").rename(folder / "store.py")  # a rename keeps the size and the modification time
    files = graphcache.graph_for(folder, None).files
    assert "store.py" in files and "shop.py" not in files
    assert len(builds) == 2


def test_a_folder_that_cannot_be_listed_is_never_trusted_from_memory(repo, builds, monkeypatch):
    folder = repo(SHOP)

    def cannot_list(*args, **kwargs):
        raise OSError("cannot list")

    monkeypatch.setattr(graphcache, "discover", cannot_list)
    graphcache.graph_for(folder, None)
    graphcache.graph_for(folder, None)
    assert len(builds) == 2


def test_a_file_that_changes_while_the_graph_is_being_read_is_read_again_next_time(repo, monkeypatch):
    folder = repo(SHOP)
    real = graphcache.build_graph
    reads: list[int] = []

    def read_then_edit(*args, **kwargs):
        graph = real(*args, **kwargs)
        reads.append(1)
        if len(reads) == 1:  # the file changes after it was read, before the request is over
            (folder / "shop.py").write_text(SHOP["shop.py"] + "\n\ndef audit():\n    return 3\n")
        return graph

    monkeypatch.setattr(graphcache, "build_graph", read_then_edit)
    graphcache.graph_for(folder, None)
    assert "audit" in {s.name for s in graphcache.graph_for(folder, None).symbols.values()}  # the next request does not trust the older read
    assert len(reads) == 2


def test_an_added_or_removed_file_is_read_afresh(repo, builds):
    folder = repo(SHOP)
    graphcache.graph_for(folder, None)
    (folder / "extra.py").write_text("def more():\n    return 1\n")
    assert "extra.py" in graphcache.graph_for(folder, None).files
    (folder / "extra.py").unlink()
    assert "extra.py" not in graphcache.graph_for(folder, None).files
    assert len(builds) == 3


def test_a_different_focus_is_a_different_graph_and_each_is_kept(repo, builds):
    folder = repo({"pkg/a.py": "def inside():\n    return 1\n", "other/b.py": "def outside():\n    return 2\n"})
    everything = graphcache.graph_for(folder, None)
    only_pkg = graphcache.graph_for(folder, "pkg")
    assert set(only_pkg.files) == {"pkg/a.py"} and set(everything.files) == {"pkg/a.py", "other/b.py"}
    assert graphcache.graph_for(folder, None) is everything and graphcache.graph_for(folder, "pkg") is only_pkg
    assert len(builds) == 2


def test_only_a_few_graphs_are_kept_and_the_longest_unused_goes_first(repo, builds):
    folders = [repo({"m.py": f"def f{i}():\n    return {i}\n"}) for i in range(graphcache.KEEP + 1)]
    for folder in folders:
        graphcache.graph_for(folder, None)
    assert len(builds) == graphcache.KEEP + 1
    graphcache.graph_for(folders[-1], None)  # the newest is still kept
    assert len(builds) == graphcache.KEEP + 1
    graphcache.graph_for(folders[0], None)  # the oldest was let go
    assert len(builds) == graphcache.KEEP + 2


def test_reading_a_kept_graph_again_makes_it_the_newest(repo, builds):
    a, b, c = (repo({"m.py": f"def f{i}():\n    return {i}\n"}) for i in range(3))
    assert graphcache.KEEP == 2
    graphcache.graph_for(a, None)
    graphcache.graph_for(b, None)
    graphcache.graph_for(a, None)  # a is now the newest, so the next new graph pushes b out
    graphcache.graph_for(c, None)
    before = len(builds)
    graphcache.graph_for(a, None)
    assert len(builds) == before
    graphcache.graph_for(b, None)
    assert len(builds) == before + 1


def test_the_graph_is_read_without_git_history_and_its_lookups_are_ready(repo, builds):
    g = graphcache.graph_for(repo(SHOP), None)
    assert builds[0]["with_history"] is False and g.commits is None
    # the lookup tables are built when the graph is kept, so requests that read it at the same moment never build them under each other
    assert g._callers is not None and g._callees is not None and g._importers is not None and g._imports is not None


def test_a_folder_that_cannot_be_read_is_an_error_and_nothing_is_kept(tmp_path):
    with pytest.raises(OSError):
        graphcache.graph_for(tmp_path / "nowhere", None)


def test_many_requests_reading_one_kept_graph_at_once_all_get_the_same_answer(repo):
    folder = repo(SHOP)
    symbol = "shop.py::checkout"
    expected = call_graph(graphcache.graph_for(folder, None), symbol, 2)
    graphcache.clear()  # start the threads from nothing, so they race to build and to read
    answers: list[dict] = []
    errors: list[BaseException] = []

    def work():
        try:
            for _ in range(3):
                answers.append(call_graph(graphcache.graph_for(folder, None), symbol, 2))
        except BaseException as exc:  # noqa: BLE001  (a failure in a thread must reach the test)
            errors.append(exc)

    threads = [threading.Thread(target=work) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == [] and len(answers) == 36 and all(a == expected for a in answers)
