"""Which files are test scaffolding: end-to-end suites, fixtures and mocks as well as the tests themselves. The architecture map and the guide both use
this to decide that an import written there says nothing about how the project works (`graph.files.is_test_support_path`)."""

from __future__ import annotations

import pytest

from skillforge.graph.files import is_test_path, is_test_support_path


@pytest.mark.parametrize("path", [
    "e2e/run.mjs", "frontend/e2e/mock_server.py", "FRONTEND/E2E/a.py", "a/b/c/e2e/d/e.py",
    "src/fixtures/data.py", "src/mocks/a.ts", "src/__mocks__/a.ts", "src/testing/helpers.py",
    "tests/a.py", "src/tests/a.py", "src/test/a.py", "src/__tests__/a.ts", "spec/a.rb", "src/specs/a.rb",
])
def test_a_file_inside_a_folder_of_tests_or_test_scaffolding_is_scaffolding(path):
    assert is_test_support_path(path) is True


@pytest.mark.parametrize("path", [
    "src/app.py", "e2e.py", "src/e2e.py", "src/mocks", "tests", "",  # a file named like a folder is not inside one
    "src/latest/a.py", "src/e2e-tools/a.py", "src/mocking/a.py", "src/fixturesque/a.py", "contests/a.py", "src/testsuite/a.py", "src/specification/a.py",
])
def test_only_a_whole_folder_name_counts_and_a_file_named_like_one_does_not(path):
    assert is_test_support_path(path) is False


def test_everything_the_graph_calls_a_test_by_folder_is_scaffolding_too():
    """So `is_test or is_test_support_path` can be asked of any file, and the second covers the first for every folder the first knows."""
    for folder in ("tests", "test", "__tests__", "spec", "specs"):
        path = f"src/{folder}/a.py"
        assert is_test_path(path) and is_test_support_path(path)


def test_scaffolding_is_wider_than_what_the_graph_calls_a_test():
    """The graph's own rule is left alone (test counts, risk and coverage all depend on it): an e2e folder is scaffolding, not a test by that rule."""
    for folder in ("e2e", "fixtures", "mocks", "__mocks__", "testing"):
        path = f"src/{folder}/a.py"
        assert not is_test_path(path) and is_test_support_path(path)
