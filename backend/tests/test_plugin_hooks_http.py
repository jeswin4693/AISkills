"""Hooks in a plugin over HTTP: the catalogue listing, preview, keep, a second version with its risk diff, export, import and install
(Component Factory, Phase 4b, task 5). Offline: nothing is run."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from skillforge.api import create_app
from skillforge.library import Library, SkillSource, import_source, read_zip_bytes, rescan

HOOKS = "hooks/hooks.json"
BODY = {
    "name": "my-plugin", "description": "Safety hooks.", "author": "Jeswin",
    "components": [{"kind": "hook", "name": "block-secret-files", "options": {"also": ["secrets.json"]}}, {"kind": "hook", "name": "block-force-push"}],
}


def client_for(tmp_path):
    lib = Library(tmp_path / "library")
    return TestClient(create_app(lib), base_url="http://localhost"), lib


def test_the_catalogue_is_listed_with_what_each_hook_does_and_the_options_it_accepts(tmp_path):
    client, _ = client_for(tmp_path)
    r = client.get("/api/hooks")
    assert r.status_code == 200
    hooks = {h["id"]: h for h in r.json()}
    assert list(hooks) == ["block-secret-files", "block-force-push", "log-tool-calls"]
    secrets = hooks["block-secret-files"]
    assert (secrets["event"], secrets["matcher"], secrets["effect"], secrets["powers"], secrets["revision"]) == ("PreToolUse", "Read|Write|Edit|NotebookEdit", "blocks", [], 1)
    assert secrets["title"] and secrets["summary"] and secrets["sees"] and secrets["timeout"] == 10
    option = secrets["options"][0]
    assert option["key"] == "also" and option["label"] and option["help"] and option["max_items"] == 10 and option["max_length"] == 60 and option["pattern"]
    assert "flag" not in option  # how an option reaches the script is not the page's business
    assert hooks["log-tool-calls"]["powers"] == ["write_files"] and hooks["log-tool-calls"]["options"] == [] and hooks["log-tool-calls"]["effect"] == "observes"


def test_a_preview_shows_the_hooks_files_and_what_they_do_and_keeps_nothing(tmp_path):
    client, lib = client_for(tmp_path)
    r = client.post("/api/plugins/preview", json=BODY)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["failed"] is False and body["components"] == [
        {"kind": "hook", "name": "block-secret-files", "version": "r1"}, {"kind": "hook", "name": "block-force-push", "version": "r1"},
    ]
    paths = [f["path"] for f in body["files"]]
    assert HOOKS in paths and "hooks/block-secret-files.py" in paths and "hooks/block-force-push.py" in paths
    first = body["capabilities"]["hook_entries"][0]
    assert first["id"] == "block-secret-files" and first["options"] == {"also": ["secrets.json"]} and first["effect"] == "blocks"
    assert "outside any sandbox" in " ".join(body["capabilities"]["notes"])
    assert any(c["name"].startswith("hooks/hooks.json runs only catalogue hooks") and c["status"] == "passed" for c in body["checks"])
    assert lib.for_kind("plugin").names() == []


def test_keeping_then_changing_an_option_makes_a_new_version_and_the_risk_diff_says_what_changed(tmp_path):
    client, lib = client_for(tmp_path)
    first = client.post("/api/plugins", json=BODY)
    assert first.status_code == 200 and first.json()["created"] is True
    assert client.post("/api/plugins", json=BODY).json()["created"] is False  # the same hooks again: no second version
    changed = json.loads(json.dumps(BODY))
    changed["components"][0]["options"] = {"also": ["secrets.json", "*.token"]}
    second = client.post("/api/plugins", json=changed).json()
    assert second["created"] is True and second["version"]["tag"] == "v2"
    assert any(c["kind"] == "hook_options" and "*.token" in c["detail"] for c in second["risk"]["changes"])
    plugins = lib.for_kind("plugin")
    assert json.loads(plugins.read("my-plugin", 2)[1][".claude-plugin/plugin.json"])["version"] == "0.1.1"


def test_the_plugin_exports_imports_back_identical_and_installs_with_its_hooks(tmp_path):
    client, lib = client_for(tmp_path)
    client.post("/api/plugins", json=BODY)
    exported = client.get("/api/library/my-plugin/export", params={"kind": "plugin"})
    assert exported.status_code == 200
    elsewhere = Library(tmp_path / "elsewhere").for_kind("plugin")
    report = import_source(read_zip_bytes(exported.content, "x.zip"), elsewhere)
    assert not report.refused and report.version is not None and report.version.content_hash == lib.for_kind("plugin").pick("my-plugin").content_hash
    assert [scan.status for scan in rescan(lib.for_kind("plugin"))] == ["same"]
    out = tmp_path / "out"
    assert client.post("/api/library/my-plugin/install", params={"kind": "plugin"}, json={"target": "folder", "folder": str(out)}).status_code == 200
    assert (out / "my-plugin" / "hooks" / "hooks.json").exists() and (out / "my-plugin" / "hooks" / "block-force-push.py").exists()


def test_a_hook_that_is_not_in_the_catalogue_or_has_a_bad_option_is_a_plain_error_and_nothing_is_kept(tmp_path):
    client, lib = client_for(tmp_path)
    def body(*components):
        return {**BODY, "components": list(components)}
    for bad, why in (
        (body({"kind": "hook", "name": "run-anything"}), "not a hook in the catalogue"),
        (body({"kind": "hook", "name": "block-secret-files", "options": {"also": ["a;rm -rf /"]}}), "not allowed"),
        (body({"kind": "hook", "name": "block-secret-files", "options": {"nope": ["x"]}}), "no option"),
        (body({"kind": "hook", "name": "block-force-push", "version": 2}), "no version"),
        (body({"kind": "hook", "name": "block-force-push"}, {"kind": "hook", "name": "block-force-push"}), "twice"),
    ):
        for route in ("/api/plugins/preview", "/api/plugins"):
            r = client.post(route, json=bad)
            assert r.status_code == 400 and why in r.json()["detail"], (bad, route, r.text)
    for too_much in (
        {"kind": "hook", "name": "block-secret-files", "options": {"also": ["x"] * 21}},  # more than a request may carry
        {"kind": "hook", "name": "block-secret-files", "options": {"also": ["x" * 101]}},
        {"kind": "hook", "name": "block-secret-files", "options": {"also": "secrets.json"}},
    ):
        assert client.post("/api/plugins/preview", json=body(too_much)).status_code == 422
    assert lib.for_kind("plugin").names() == []


SHELL_HOOK = {"type": "command", "command": "sh", "args": ["-c", "echo hi"]}


def outside(tmp_path, groups: list[dict], drop: tuple[str, ...] = ()):
    """The kept plugin with its hooks file replaced, imported as a zip from outside would be."""
    client, lib = client_for(tmp_path)
    client.post("/api/plugins", json=BODY)
    files = {p: d for p, d in lib.for_kind("plugin").read("my-plugin")[1].items() if p not in drop}
    files[HOOKS] = json.dumps({"hooks": {"PreToolUse": groups}}).encode()
    return import_source(SkillSource(files, [], "outside", "my-plugin", "my-plugin"), Library(tmp_path / "elsewhere").for_kind("plugin"))


def test_a_plugin_from_outside_with_only_a_command_the_catalogue_does_not_have_has_nothing_to_describe_and_is_refused(tmp_path):
    report = outside(tmp_path, [{"hooks": [SHELL_HOOK]}], drop=("hooks/block-secret-files.py", "hooks/block-force-push.py"))
    assert report.refused and any(c.status == "failed" and "contains" in c.name for c in report.checks)


def test_a_plugin_from_outside_with_one_catalogue_hook_and_one_other_command_is_kept_with_a_warning_that_shows_the_command(tmp_path):
    force = {"matcher": "Bash|PowerShell", "hooks": [{"type": "command", "command": "python", "args": ["${CLAUDE_PLUGIN_ROOT}/hooks/block-force-push.py"], "timeout": 10}]}
    report = outside(tmp_path, [force, {"hooks": [SHELL_HOOK]}], drop=("hooks/block-secret-files.py",))
    assert not report.refused
    warned = [c for c in report.checks if c.status == "warning" and c.name.startswith("hooks/hooks.json")]
    assert warned and "sh -c echo hi" in warned[0].detail
