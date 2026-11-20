"""The local HTTP API, offline: routes over the library, and the protections that keep a local server local."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_kinds import fake_kind  # noqa: F401  (a pytest fixture: it registers a second kind for one test)
from test_library import GOOD, NAME, hostile

from skillforge import cli
from skillforge.api import create_app
from skillforge.api import app as api_module
from skillforge.build.requirements import QUESTIONS
from skillforge.library import Library
from skillforge.sandbox import SandboxStatus

UI = "http://localhost:3000"


def zbytes(entries: dict[str, str | bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buffer.getvalue()


def skill_zip(body: str = "Body.\n") -> bytes:
    return zbytes({f"{NAME}/SKILL.md": GOOD["SKILL.md"].replace("Body.\n", body), f"{NAME}/README.md": "Demo.\n"})


@pytest.fixture
def lib(tmp_path) -> Library:
    return Library(tmp_path / "library")


@pytest.fixture
def client(lib) -> TestClient:
    return TestClient(create_app(lib), base_url="http://localhost")


def upload(client: TestClient, data: bytes, path: str = "/api/library/import", headers: dict | None = None, **kw):
    return client.post(path, content=data, headers={"Content-Type": "application/zip", **(headers or {})}, **kw)


def thing_zip() -> bytes:
    """A folder of the fake kind (see test_kinds.py): a thing.txt whose first line is the name. The files sit at the top of
    the zip, because a zip's single top folder is only unwrapped when it holds a SKILL.md (library/package.py)."""
    return zbytes({"thing.txt": "my-thing\nhello\n"})


# ---- kinds -------------------------------------------------------------------------------------------


def test_kinds_lists_the_skill_kind_with_its_slots(client):
    kinds = client.get("/api/kinds").json()
    assert [k["key"] for k in kinds] == ["skill", "agent"]
    assert kinds[0]["label"] == "Skill" and kinds[0]["install_targets"] == ["personal", "folder"]
    assert kinds[0]["slots"][0] == {"key": "goal", "label": "Goal", "question": QUESTIONS["goal"]}


def test_the_library_routes_default_to_skills_and_take_a_kind(client, fake_kind):
    r = upload(client, thing_zip(), path="/api/library/import?kind=note")
    assert r.status_code == 200, r.text
    assert [s["name"] for s in client.get("/api/library", params={"kind": "note"}).json()] == ["my-thing"]
    assert client.get("/api/library").json() == []  # no kind means skills
    assert client.get("/api/library/my-thing", params={"kind": "note"}).status_code == 200
    assert client.get("/api/library/my-thing").status_code == 404
    assert upload(client, skill_zip(), path="/api/library/import?kind=note").status_code == 422  # a skill is not a note


def test_validate_takes_a_kind(client, fake_kind):
    assert upload(client, thing_zip(), path="/api/validate?kind=note").json()["failed"] == 0
    assert upload(client, skill_zip(), path="/api/validate?kind=note").json()["failed"] >= 1


def test_installing_for_me_goes_where_the_kind_says(client, fake_kind, tmp_path, monkeypatch):
    monkeypatch.setattr(type(fake_kind), "personal_dir", lambda self: tmp_path / "mine")
    upload(client, thing_zip(), path="/api/library/import?kind=note")
    r = client.post("/api/library/my-thing/install", params={"kind": "note"}, json={"target": "personal"})
    assert r.status_code == 200, r.text
    assert (tmp_path / "mine" / "my-thing" / "thing.txt").exists()


ZIP_HEADERS = {"Content-Type": "application/zip"}


@pytest.mark.parametrize("method,path,kwargs", [
    ("get", "/api/library", {}),
    ("get", "/api/library/x", {}),
    ("get", "/api/library/x/diff", {}),
    ("get", "/api/rescan", {}),
    ("get", "/api/library/x/versions/1/files/a", {}),
    ("get", "/api/library/x/export", {}),
    ("post", "/api/library/import", {"content": skill_zip(), "headers": ZIP_HEADERS}),
    ("post", "/api/validate", {"content": skill_zip(), "headers": ZIP_HEADERS}),
    ("post", "/api/library/x/rollback", {"json": {"to": 1}}),
    ("post", "/api/library/x/install", {"json": {"target": "personal"}}),
])
@pytest.mark.parametrize("bad", ["../x", "", "a/b"])
def test_an_unknown_kind_is_a_400_that_names_the_kinds_on_every_library_route(client, tmp_path, method, path, kwargs, bad):
    before = sorted(p.name for p in tmp_path.iterdir())
    r = getattr(client, method)(path, params={"kind": bad}, **kwargs)
    assert r.status_code == 400 and "skill" in r.json()["detail"]
    assert sorted(p.name for p in tmp_path.iterdir()) == before  # nothing was made on disk for it


# ---- keeping the local API local ---------------------------------------------------------------------


def test_health_answers_on_localhost(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


@pytest.mark.parametrize("host", ["localhost:8000", "127.0.0.1:8000", "[::1]:8000", "LOCALHOST"])
def test_loopback_names_with_or_without_a_port_are_accepted(client, host):
    assert client.get("/api/health", headers={"Host": host}).status_code == 200


@pytest.mark.parametrize("host", ["evil.example", "localhost.evil.example", "127.0.0.1.evil.example:8000", "192.168.1.5:8000", ""])
def test_any_other_host_name_is_refused_so_dns_rebinding_cannot_reach_it(client, host):
    r = client.get("/api/health", headers={"Host": host})
    assert r.status_code == 403 and "localhost" in r.json()["detail"]


def test_a_change_requested_from_an_unknown_web_page_is_refused_and_stores_nothing(client, lib):
    r = client.post("/api/library/import", content=skill_zip(), headers={"Origin": "https://evil.example", "Content-Type": "application/zip"})
    assert r.status_code == 403 and lib.names() == []
    r = client.post("/api/library/import", content=skill_zip(), headers={"Origin": "null", "Content-Type": "application/zip"})
    assert r.status_code == 403 and lib.names() == []


def test_the_ui_origin_and_a_command_line_client_may_change_things(client, lib):
    assert upload(client, skill_zip(), headers={"Origin": UI}).status_code == 200
    assert upload(client, skill_zip("Two.\n")).status_code == 200  # no Origin: not a web page
    assert [v.tag for v in lib.versions(NAME)] == ["v1", "v2"]


def test_cors_is_open_to_the_ui_and_to_nobody_else(client):
    ok = client.options("/api/library/import", headers={"Origin": UI, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"})
    assert ok.status_code == 200 and ok.headers["access-control-allow-origin"] == UI
    bad = client.options("/api/library/import", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in bad.headers
    assert "access-control-allow-origin" not in client.get("/api/health", headers={"Origin": "https://evil.example"}).headers


def test_extra_ui_origins_can_be_added(lib, monkeypatch):
    monkeypatch.setenv("SKILLFORGE_UI_ORIGINS", "http://localhost:5173/")
    c = TestClient(create_app(lib), base_url="http://localhost")
    assert upload(c, skill_zip(), headers={"Origin": "http://localhost:5173"}).status_code == 200


# ---- the library over HTTP ---------------------------------------------------------------------------


def test_the_whole_library_cycle_over_http(client, lib, tmp_path):
    assert client.get("/api/library").json() == []
    first = upload(client, skill_zip(), params={"filename": "C:\\Users\\me\\demo.zip", "note": "first"})
    body = first.json()
    assert first.status_code == 200 and body["created"] and body["version"]["tag"] == "v1" and not body["refused"]
    assert body["version"]["source_label"] == "demo.zip" and body["version"]["note"] == "first"  # a name, never a path
    assert upload(client, skill_zip()).json()["created"] is False
    assert upload(client, skill_zip("Version two.\n")).json()["previous"] == "v1"

    listing = client.get("/api/library").json()
    assert listing[0]["name"] == NAME and listing[0]["versions"] == 2 and listing[0]["latest"]["tag"] == "v2"
    versions = client.get(f"/api/library/{NAME}").json()["versions"]
    assert [v["tag"] for v in versions] == ["v2", "v1"]

    diff = client.get(f"/api/library/{NAME}/diff").json()
    assert diff["from"] == "v1" and diff["to"] == "v2"
    assert any(c["path"] == "SKILL.md" and "+Version two." in c["text"] for c in diff["changes"])
    assert client.get(f"/api/library/{NAME}/diff", params={"frm": 1, "to": 2}).status_code == 200

    f = client.get(f"/api/library/{NAME}/versions/1/files/SKILL.md").json()
    assert f["binary"] is False and "Body." in f["text"]

    rolled = client.post(f"/api/library/{NAME}/rollback", json={"to": 1}).json()
    assert rolled["created"] and rolled["version"]["tag"] == "v3"

    exported = client.get(f"/api/library/{NAME}/export")
    assert exported.status_code == 200 and exported.headers["content-type"] == "application/zip"
    assert f'{NAME}-v3.zip' in exported.headers["content-disposition"]
    assert sorted(zipfile.ZipFile(io.BytesIO(exported.content)).namelist()) == [f"{NAME}/README.md", f"{NAME}/SKILL.md"]

    target = tmp_path / "skills"
    done = client.post(f"/api/library/{NAME}/install", json={"target": "folder", "folder": str(target)})
    assert done.status_code == 200 and (target / NAME / "SKILL.md").exists() and done.json()["backup"] is None
    again = client.post(f"/api/library/{NAME}/install", json={"target": "folder", "folder": str(target)})
    assert again.status_code == 409 and "already exists" in again.json()["detail"]
    forced = client.post(f"/api/library/{NAME}/install", json={"target": "folder", "folder": str(target), "force": True})
    assert forced.status_code == 200 and Path(forced.json()["backup"]).is_dir()


def test_a_round_trip_through_export_and_import_over_http_changes_nothing(client):
    upload(client, skill_zip())
    zip_back = client.get(f"/api/library/{NAME}/export").content
    assert upload(client, zip_back).json()["created"] is False


def test_export_can_leave_out_the_spec(client):
    upload(client, zbytes({"SKILL.md": GOOD["SKILL.md"], "spec.json": '{"user_words": "private"}'}))
    full = zipfile.ZipFile(io.BytesIO(client.get(f"/api/library/{NAME}/export").content)).namelist()
    lean = zipfile.ZipFile(io.BytesIO(client.get(f"/api/library/{NAME}/export", params={"without_spec": "true"}).content)).namelist()
    assert f"{NAME}/spec.json" in full and f"{NAME}/spec.json" not in lean


def test_install_to_the_personal_folder_uses_the_home_directory(client, tmp_path, monkeypatch):
    upload(client, skill_zip())
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    assert client.post(f"/api/library/{NAME}/install", json={"target": "personal"}).status_code == 200
    assert (tmp_path / "home" / ".claude" / "skills" / NAME / "SKILL.md").exists()


@pytest.mark.parametrize("body", [
    {"target": "folder"}, {"target": "folder", "folder": "relative/path"}, {"target": "folder", "folder": ""},
])
def test_installing_to_a_folder_needs_an_absolute_path(client, body):
    upload(client, skill_zip())
    r = client.post(f"/api/library/{NAME}/install", json=body)
    assert r.status_code == 400 and "absolute" in r.json()["detail"]


def test_an_unknown_install_target_is_a_validation_error(client):
    upload(client, skill_zip())
    assert client.post(f"/api/library/{NAME}/install", json={"target": "everywhere"}).status_code == 422


# ---- refusals ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["dotdot", "absolute", "symlink", "duplicate", "one-huge-file"])
def test_a_hostile_zip_is_refused_with_422_and_the_checks_that_failed(client, lib, tmp_path, kind):
    r = upload(client, hostile(tmp_path, kind).read_bytes())
    body = r.json()
    assert r.status_code == 422 and body["refused"] and body["version"] is None
    assert any(c["status"] == "failed" for c in body["checks"]) and lib.names() == []


def test_validate_checks_an_upload_and_stores_nothing(client, lib):
    good = upload(client, skill_zip(), "/api/validate").json()
    assert good["failed"] == 0 and good["files"] == 2
    bad = upload(client, zbytes({"SKILL.md": "no front matter"}), "/api/validate").json()
    assert bad["failed"] >= 1
    assert lib.names() == []


def test_an_upload_over_the_cap_is_refused_whether_or_not_it_declares_its_size(client, lib, monkeypatch):
    monkeypatch.setattr(api_module, "MAX_UPLOAD", 100)
    assert upload(client, b"x" * 101).status_code == 413
    chunks = (b"x" * 40 for _ in range(5))  # no Content-Length: sent in chunks
    assert client.post("/api/library/import", content=chunks, headers={"Content-Type": "application/zip"}).status_code == 413
    assert lib.names() == []


def test_an_empty_body_and_something_that_is_not_a_zip_are_plain_400s(client):
    assert client.post("/api/library/import").status_code == 400
    r = upload(client, b"just some text")
    assert r.status_code == 400 and "not a zip" in r.json()["detail"]


def test_unknown_things_are_404_and_bad_names_are_400(client):
    upload(client, skill_zip())
    for url in ("/api/library/nothing-here", "/api/library/nothing-here/diff", "/api/library/nothing-here/export",
                f"/api/library/{NAME}/versions/1/files/no/such/file.md", f"/api/library/{NAME}/versions/9/files/SKILL.md"):
        assert client.get(url).status_code == 404, url
    assert client.post("/api/library/nothing-here/rollback", json={"to": 1}).status_code == 404
    assert client.get("/api/library/Bad Name").status_code == 400
    assert client.get(f"/api/library/{NAME}/diff").status_code == 400  # only one version: nothing before it


def test_a_file_changed_behind_the_librarys_back_is_refused_over_http_too(client, lib):
    upload(client, skill_zip())
    (lib.root / NAME / "v1" / "skill" / "SKILL.md").write_text("tampered", encoding="utf-8")
    for url in (f"/api/library/{NAME}/export", f"/api/library/{NAME}/versions/1/files/SKILL.md"):
        r = client.get(url)
        assert r.status_code == 400 and "changed after import" in r.json()["detail"]


def test_a_stored_file_is_looked_up_by_name_not_opened_by_path(client):
    upload(client, skill_zip())
    for path in ("../../manifest.json", "..%2F..%2Fmanifest.json", "/etc/passwd", "C:/Windows/win.ini"):
        assert client.get(f"/api/library/{NAME}/versions/1/files/{path}").status_code in (404, 400)


# ---- risk diff and rescan ----------------------------------------------------------------------------


def skill_zip_with_script() -> bytes:
    return zbytes({
        f"{NAME}/SKILL.md": GOOD["SKILL.md"], f"{NAME}/README.md": "Demo.\n",
        f"{NAME}/scripts/fetch.py": "import requests\nrequests.get('https://api.example.test/x')\n",
    })


def test_an_import_that_adds_a_version_carries_what_got_riskier_and_a_first_version_carries_nothing(client):
    first = upload(client, skill_zip())
    assert first.status_code == 200 and first.json()["risk"] is None
    second = upload(client, skill_zip_with_script())
    risk = second.json()["risk"]
    assert second.status_code == 200 and risk["level"] == "more_risk" and (risk["older"], risk["newer"]) == ("v1", "v2")
    assert risk["counts"]["riskier"] >= 1 and "cannot read meaning" in risk["note"]
    assert {"direction", "kind", "detail", "path"} <= set(risk["changes"][0])
    assert risk["changes"][0]["direction"] == "riskier" and risk["changes"][0]["kind"] == "script_added"
    assert upload(client, skill_zip_with_script()).json()["risk"] is None  # the same content again: no new version


def test_a_refused_import_has_no_risk_because_nothing_was_compared(client):
    upload(client, skill_zip())
    refused = upload(client, zbytes({f"{NAME}/SKILL.md": GOOD["SKILL.md"], f"{NAME}/tool.bin": b"\x00\x01\x02"}))
    assert refused.status_code == 422 and refused.json()["risk"] is None


def test_the_diff_endpoint_carries_the_same_risk_as_the_import(client):
    upload(client, skill_zip())
    imported = upload(client, skill_zip_with_script()).json()["risk"]
    diff = client.get(f"/api/library/{NAME}/diff").json()
    assert diff["risk"] == imported and [c["path"] for c in diff["changes"]] == ["scripts/fetch.py"]
    back = client.get(f"/api/library/{NAME}/diff", params={"frm": 2, "to": 1}).json()
    assert back["risk"]["level"] == "less_risk" and back["risk"]["older"] == "v2"


def test_rescan_over_http_reports_every_stored_version_and_changes_nothing(client, lib):
    upload(client, skill_zip())
    upload(client, skill_zip_with_script())
    before = {p: p.read_bytes() for p in lib.root.rglob("*") if p.is_file()}
    r = client.get("/api/rescan")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["counts"] == {"same": 2, "worse": 0, "failing": 0, "damaged": 0}
    assert [(v["name"], v["tag"], v["status"]) for v in body["versions"]] == [(NAME, "v2", "same"), (NAME, "v1", "same")]
    assert {p: p.read_bytes() for p in lib.root.rglob("*") if p.is_file()} == before
    assert client.get("/api/rescan", params={"name": NAME, "version": 1}).json()["counts"]["same"] == 1


def test_rescan_over_http_says_when_a_stored_file_was_changed_behind_the_librarys_back(client, lib):
    upload(client, skill_zip())
    (lib.root / NAME / "v1" / "skill" / "README.md").write_text("tampered\n", encoding="utf-8")
    body = client.get("/api/rescan").json()
    assert body["ok"] is False and body["counts"]["damaged"] == 1
    assert body["versions"][0]["status"] == "damaged" and "README.md" in body["versions"][0]["message"]


def test_rescan_over_http_answers_plainly_to_unknown_skills_and_unclear_requests(client):
    assert client.get("/api/rescan", params={"name": "no-such-skill"}).status_code == 404
    assert client.get("/api/rescan", params={"version": 1}).status_code == 400
    assert client.get("/api/rescan").json() == {"ok": True, "counts": {"same": 0, "worse": 0, "failing": 0, "damaged": 0}, "versions": []}


def test_a_skill_that_is_named_rescan_is_still_reachable(client):
    """The rescan route is /api/rescan, not /api/library/rescan, so the name of a skill can never hide it."""
    named = zbytes({"rescan/SKILL.md": "---\nname: rescan\ndescription: Scans again.\n---\nBody.\n"})
    assert upload(client, named).status_code == 200
    assert client.get("/api/library/rescan").json()["versions"][0]["name"] == "rescan"
    assert client.get("/api/rescan", params={"name": "rescan"}).json()["ok"] is True


# ---- machine facts -----------------------------------------------------------------------------------


def test_sandbox_status_is_reported_as_the_engine_answers(client, monkeypatch):
    monkeypatch.setattr(api_module, "probe_sandbox", lambda: SandboxStatus(False, "No Linux container engine."))
    assert client.get("/api/sandbox").json() == {"available": False, "reason": "No Linux container engine."}


def test_the_language_table_lists_levels_and_extensions(client):
    table = {row["name"]: row for row in client.get("/api/languages").json()}
    assert table["python"]["level"] == "full" and ".py" in table["python"]["extensions"]
    assert table["java"]["level"] == "standard" and table["swift"]["level"] == "basic"


def test_no_endpoint_is_about_keys_or_settings(client):
    paths = " ".join(client.get("/api/openapi.json").json()["paths"])
    assert not any(word in paths.lower() for word in ("key", "secret", "token", "env"))


def test_the_serve_command_exists_and_defaults_to_port_8000():
    assert cli._parser().parse_args(["serve"]).port == 8000
    assert cli._parser().parse_args(["serve", "--port", "9100"]).port == 9100
