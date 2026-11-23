"""A plugin that holds an MCP server, over HTTP: preview, keep, a second version with a risk diff, export, import and install
(Component Factory, Phase 4a, task 4). Offline: nothing is run."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from test_mcp_validate import GOOD as SERVER
from test_plugin_mcp import KEYED, NAME
from test_plugin_mcp_compose import server_files

from skillforge.api import create_app
from skillforge.library import Library, import_source, read_zip_bytes, rescan

BODY = {"name": "my-plugin", "description": "Word tools.", "author": "Jeswin", "components": [{"kind": "mcp", "name": NAME}]}
NETWORK = SERVER.replace("return text.upper()", "import urllib.request\n    return urllib.request.urlopen(text).read().decode()")


def client_for(tmp_path, source: str = KEYED):
    lib = Library(tmp_path / "library")
    lib.for_kind("mcp").add(NAME, server_files(source), source_kind="test", source_label="test")
    return TestClient(create_app(lib), base_url="http://localhost"), lib


def test_a_preview_lists_the_server_what_it_can_do_and_the_option_it_will_ask_for_and_keeps_nothing(tmp_path):
    client, lib = client_for(tmp_path)
    r = client.post("/api/plugins/preview", json=BODY)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["failed"] is False and body["components"] == [{"kind": "mcp", "name": NAME, "version": "v1"}]
    assert ".mcp.json" in [f["path"] for f in body["files"]] and f"servers/{NAME}/server.py" in [f["path"] for f in body["files"]]
    assert body["capabilities"]["servers"][0]["environment"] == ["WEATHER_API_KEY"] and body["capabilities"]["servers"][0]["name"] == NAME
    assert "starts on this machine" in " ".join(body["capabilities"]["notes"])
    assert list(json.loads(body["manifest"])["userConfig"]) == ["word_tools_weather_api_key"]
    assert lib.for_kind("plugin").names() == []


def test_keeping_a_plugin_with_a_server_and_then_a_riskier_server_shows_the_risk_diff(tmp_path):
    client, lib = client_for(tmp_path)
    first = client.post("/api/plugins", json=BODY)
    assert first.status_code == 200 and first.json()["created"] is True and first.json()["capabilities"]["servers"][0]["name"] == NAME
    lib.for_kind("mcp").add(NAME, server_files(NETWORK), source_kind="test", source_label="test")  # the same server, now able to reach the network
    second = client.post("/api/plugins", json=BODY).json()
    assert second["created"] is True and second["version"]["tag"] == "v2"
    assert second["risk"]["level"] == "more_risk"
    assert any(c["direction"] == "riskier" and "network" in c["detail"] and c["detail"].startswith("MCP server") for c in second["risk"]["changes"])


def test_the_plugin_exports_imports_back_identical_and_installs_with_its_servers_and_mcp_json(tmp_path):
    client, lib = client_for(tmp_path)
    client.post("/api/plugins", json=BODY)
    exported = client.get("/api/library/my-plugin/export", params={"kind": "plugin"})
    assert exported.status_code == 200
    elsewhere = Library(tmp_path / "elsewhere").for_kind("plugin")
    report = import_source(read_zip_bytes(exported.content, "x.zip"), elsewhere)
    assert not report.refused and report.version.content_hash == lib.for_kind("plugin").pick("my-plugin").content_hash
    assert [scan.status for scan in rescan(lib.for_kind("plugin"))] == ["same"]
    out = tmp_path / "out"
    assert client.post("/api/library/my-plugin/install", params={"kind": "plugin"}, json={"target": "folder", "folder": str(out)}).status_code == 200
    assert (out / "my-plugin" / ".mcp.json").exists() and (out / "my-plugin" / "servers" / NAME / "server.py").exists()


def test_a_plugin_zip_from_outside_that_starts_something_it_does_not_ship_is_kept_with_a_warning_that_shows_the_command(tmp_path):
    client, lib = client_for(tmp_path, SERVER)
    client.post("/api/plugins", json=BODY)
    files = {p: d for p, d in lib.for_kind("plugin").read("my-plugin")[1].items()}
    files[".mcp.json"] = json.dumps({"mcpServers": {NAME: {"command": "sh", "args": ["-c", "echo hi"]}}}).encode()
    elsewhere = Library(tmp_path / "elsewhere").for_kind("plugin")
    from skillforge.library import SkillSource

    report = import_source(SkillSource(files, [], "outside", "my-plugin", "my-plugin"), elsewhere)
    assert not report.refused
    warned = [c for c in report.checks if c.status == "warning" and ".mcp.json" in c.name]
    assert warned and "sh -c echo hi" in warned[0].detail
