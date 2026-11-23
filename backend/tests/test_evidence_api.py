"""Evidence over the local API: read what a skill cites, recheck it against a repository, export without it. Offline."""

from __future__ import annotations

import io
import zipfile

import pytest
from fastapi.testclient import TestClient
from test_evidence import APP, NOW, rebuild
from test_hosted import TOKEN, hosted
from test_library import NAME, write_skill

from skillforge.api import create_app
from skillforge.evidence import EVIDENCE_FILE
from skillforge.library import Library, import_skill
from skillforge.library.evidence import cite


@pytest.fixture
def world(tmp_path, repo):
    lib = Library(tmp_path / "library")
    assert not import_skill(write_skill(tmp_path / NAME), lib).refused
    root = repo(APP)
    return lib, root, TestClient(create_app(lib), base_url="http://localhost")


def cited(lib, root, *refs):
    cite(lib, NAME, rebuild(root), list(refs), now=NOW)


def test_a_skill_without_evidence_says_so(world):
    _, _, client = world
    r = client.get(f"/api/library/{NAME}/evidence")
    assert r.status_code == 200 and r.json() == {"name": NAME, "version": "v1", "evidence": None}


def test_the_recorded_evidence_is_readable(world):
    lib, root, client = world
    cited(lib, root, "svc.py::parse")
    doc = client.get(f"/api/library/{NAME}/evidence").json()
    assert doc["version"] == "v2" and doc["evidence"]["repo"] == root.name
    assert doc["evidence"]["refs"][0]["id"] == "svc.py::parse" and doc["evidence"]["refs"][0]["callers_total"] == 2
    assert client.get(f"/api/library/{NAME}/evidence", params={"version": 1}).json()["evidence"] is None


def test_an_unknown_skill_is_a_404(world):
    _, _, client = world
    assert client.get("/api/library/not-there/evidence").status_code == 404


def test_recheck_reports_what_changed(world):
    lib, root, client = world
    cited(lib, root, "svc.py::parse", "svc.py::clean")
    (root / "svc.py").write_text("def parse(raw):\n    return raw\n", encoding="utf-8")
    r = client.post(f"/api/library/{NAME}/recheck", json={"repo": str(root)})
    doc = r.json()
    assert r.status_code == 200 and doc["ok"] is False and doc["skill"] == NAME and doc["version"] == "v2"
    assert doc["counts"] == {"missing": 1, "changed": 1} and "advice" in doc["limits"]
    assert {f["ref"]: f["status"] for f in doc["findings"]} == {"svc.py::parse": "changed", "svc.py::clean": "missing"}
    assert [v.tag for v in lib.versions(NAME)] == ["v1", "v2"]  # reading only


@pytest.mark.parametrize("repo_value, why", [("relative/path", "absolute"), ("", "absolute")])
def test_recheck_wants_an_absolute_path(world, repo_value, why):
    lib, root, client = world
    cited(lib, root, "svc.py::parse")
    r = client.post(f"/api/library/{NAME}/recheck", json={"repo": repo_value})
    assert r.status_code == 400 and why in r.json()["detail"]


def test_recheck_of_a_missing_folder_is_a_plain_400(world, tmp_path):
    lib, root, client = world
    cited(lib, root, "svc.py::parse")
    r = client.post(f"/api/library/{NAME}/recheck", json={"repo": str(tmp_path / "nowhere")})
    assert r.status_code == 400 and "Not a directory" in r.json()["detail"]


def test_recheck_without_evidence_is_a_400_that_says_how_to_add_some(world):
    _, root, client = world
    r = client.post(f"/api/library/{NAME}/recheck", json={"repo": str(root)})
    assert r.status_code == 400 and "library cite" in r.json()["detail"]


def test_recheck_is_off_in_the_hosted_version(tmp_path, repo):
    lib = Library(tmp_path / "library")
    assert not import_skill(write_skill(tmp_path / NAME), lib).refused
    root = repo(APP)
    cited(lib, root, "svc.py::parse")
    client = TestClient(create_app(lib, hosted=hosted()), base_url="http://localhost")
    assert client.post("/api/auth/login", json={"token": TOKEN}).status_code == 200
    r = client.post(f"/api/library/{NAME}/recheck", json={"repo": str(root)})
    assert r.status_code == 403 and "hosted" in r.json()["detail"]
    assert client.get(f"/api/library/{NAME}/evidence").status_code == 200  # reading what is stored is fine


def names_in(response) -> set[str]:
    return set(zipfile.ZipFile(io.BytesIO(response.content)).namelist())


def test_export_keeps_evidence_unless_asked(world):
    lib, root, client = world
    cited(lib, root, "svc.py::parse")
    assert any(n.endswith(EVIDENCE_FILE) for n in names_in(client.get(f"/api/library/{NAME}/export")))
    assert not any(n.endswith(EVIDENCE_FILE) for n in names_in(client.get(f"/api/library/{NAME}/export", params={"without_evidence": "true"})))
