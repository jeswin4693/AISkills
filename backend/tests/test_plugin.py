"""Composing a plugin from skills and agents already in the library, and keeping it. Offline: no model is involved at all."""

from __future__ import annotations

import json

import pytest
from test_agent_kind import agent_files
from test_library import NAME as SKILL, write_skill

from skillforge.library import Library, LibraryError, NotFound, import_skill
from skillforge.library.plugin import ComponentRef, PluginError, compose_plugin
from skillforge.results import FAILED, PASSED
from skillforge.validate import validate_files

AGENT = "demo-agent"
BOTH = [ComponentRef("skill", SKILL), ComponentRef("agent", AGENT)]


def make_library(tmp_path, skill_extra: dict[str, str] | None = None, agent_tools: str = "Read, Grep, Glob") -> Library:
    """A library holding one skill (demo-skill) and one agent (demo-agent)."""
    lib = Library(tmp_path / "library")
    assert not import_skill(write_skill(tmp_path / SKILL, **(skill_extra or {})), lib).refused
    src = tmp_path / AGENT
    src.mkdir()
    (src / "AGENT.md").write_bytes(agent_files(agent_tools)["AGENT.md"])
    assert not import_skill(src, lib.for_kind("agent")).refused
    return lib


def compose(lib: Library, components=None, **kw):
    args = dict(name="my-plugin", description="Two helpers.", version="0.1.0", author="Jeswin")
    args.update(kw)
    return compose_plugin(lib, BOTH if components is None else components, **args)


def test_a_plugin_has_exactly_these_files_and_leaves_out_the_requesters_words(tmp_path):
    plan = compose(make_library(tmp_path, {"spec.json": "{}"}))
    assert sorted(plan.files) == [
        ".claude-plugin/marketplace.json", ".claude-plugin/plugin.json", "README.md", f"agents/{AGENT}.md",
        f"skills/{SKILL}/README.md", f"skills/{SKILL}/SKILL.md",
    ]  # spec.json holds the requester's own words, so it stays in the library
    lib_files = make_library(tmp_path / "again").for_kind("agent").read(AGENT)[1]
    assert plan.files[f"agents/{AGENT}.md"] == lib_files["AGENT.md"]  # the agent is written as agents/<name>.md, as it is
    assert plan.files[f"skills/{SKILL}/SKILL.md"].startswith(b"---\nname: demo-skill\n")


def test_the_manifest_and_the_local_marketplace_carry_the_name_and_point_at_the_folder_itself(tmp_path):
    plan = compose(make_library(tmp_path))
    assert json.loads(plan.files[".claude-plugin/plugin.json"]) == {
        "name": "my-plugin", "version": "0.1.0", "description": "Two helpers.", "author": {"name": "Jeswin"},
    }
    assert json.loads(plan.files[".claude-plugin/marketplace.json"]) == {
        "name": "my-plugin-local", "description": "Two helpers.", "owner": {"name": "Jeswin"},
        "plugins": [{"name": "my-plugin", "source": "./", "description": "Two helpers."}],
    }
    anonymous = compose(make_library(tmp_path / "x"), author="")
    assert json.loads(anonymous.files[".claude-plugin/plugin.json"])["author"] == {"name": "me"}  # `claude plugin validate --strict` wants one
    assert json.loads(anonymous.files[".claude-plugin/marketplace.json"])["owner"] == {"name": "me"}


def test_the_readme_says_what_is_inside_what_it_can_do_and_how_to_add_it(tmp_path):
    readme = compose(make_library(tmp_path)).files["README.md"].decode("utf-8")
    assert "my-plugin" in readme and SKILL in readme and AGENT in readme
    assert "claude plugin marketplace add" in readme and "claude plugin install my-plugin@my-plugin-local" in readme
    assert "only read and search files" in readme


@pytest.mark.parametrize("bad", ["claude-helpers", "anthropic-x", "Bad Name", "UPPER", "a" * 65, "", "-x", "x-", "a_b", "../x"])
def test_a_reserved_or_invalid_plugin_name_is_refused(tmp_path, bad):
    with pytest.raises(PluginError):
        compose(make_library(tmp_path), name=bad)


def test_a_plugin_needs_a_description_and_at_least_one_component_and_no_component_twice(tmp_path):
    lib = make_library(tmp_path)
    with pytest.raises(PluginError, match="description"):
        compose(lib, description="  ")
    with pytest.raises(PluginError, match="at least one"):
        compose(lib, components=[])
    with pytest.raises(PluginError, match="twice"):
        compose(lib, components=[ComponentRef("skill", SKILL), ComponentRef("skill", SKILL)])
    with pytest.raises(PluginError, match="skill, an agent or an MCP server"):
        compose(lib, components=[ComponentRef("plugin", "x")])


def test_a_component_that_is_not_in_the_library_is_not_found(tmp_path):
    lib = make_library(tmp_path)
    with pytest.raises(NotFound):
        compose(lib, components=[ComponentRef("skill", "no-such-skill")])
    with pytest.raises(NotFound):
        compose(lib, components=[ComponentRef("agent", SKILL)])  # the skill's name is not an agent's name
    with pytest.raises(NotFound):
        compose(lib, components=[ComponentRef("skill", SKILL, version=9)])


def test_a_damaged_component_can_never_end_up_inside_a_plugin(tmp_path):
    lib = make_library(tmp_path)
    stored = lib.root / SKILL / "v1" / "skill" / "SKILL.md"
    stored.write_bytes(stored.read_bytes() + b"\nSneaked in after import.\n")
    with pytest.raises(LibraryError, match="changed after import"):
        compose(lib)


def test_what_the_plugin_can_do_is_computed_from_its_tools_and_its_scripts(tmp_path):
    skill = {
        "SKILL.md": "---\nname: demo-skill\ndescription: Reads a file.\nallowed-tools: Read Bash\n---\n# Demo\n\nBody\n",
        "scripts/fetch.py": "import requests\n", "skill.sdm.json": json.dumps({"permissions": ["network"]}),
    }
    caps = compose(make_library(tmp_path, skill, agent_tools="Read, Grep, Glob, Write")).capabilities
    assert caps.tools == ["Bash", "Glob", "Grep", "Read", "Write"]
    assert caps.scripts == [f"skills/{SKILL}/scripts/fetch.py"] and caps.script_capabilities == ["network"]
    assert caps.hooks == [] and caps.mcp_servers == []  # a v1 plugin has neither
    by = {(c["kind"], c["name"]): c for c in caps.by_component}
    assert by[("skill", SKILL)]["tools"] == ["Bash", "Read"] and by[("agent", AGENT)]["tools"] == ["Glob", "Grep", "Read", "Write"]
    text = " ".join(caps.notes)
    assert "run any shell command" in text and "Bash" in text and "demo-skill" in text
    assert "create or overwrite files" in text and "demo-agent" in text
    assert "1 script" in text and "network" in text


def test_a_read_only_plugin_says_so(tmp_path):
    caps = compose(make_library(tmp_path)).capabilities
    assert caps.tools == ["Glob", "Grep", "Read"] and caps.scripts == [] and caps.notes == ["It can only read and search files."]


def test_the_composed_plugin_passes_its_own_checks_and_a_failing_one_is_reported(tmp_path):
    plan = compose(make_library(tmp_path))
    assert not [c for c in plan.checks if c.status == FAILED]
    assert any(c.name == "plugin.json exists and is a valid plugin manifest" and c.status == PASSED for c in plan.checks)
    assert plan.checks == validate_files(plan.files, folder="my-plugin", kind="plugin")  # the same checks an import would run
    assert [c["name"] for c in plan.components] == [SKILL, AGENT] and [c["version"] for c in plan.components] == ["v1", "v1"]


def test_composing_the_same_things_twice_gives_the_same_bytes(tmp_path):
    lib = make_library(tmp_path)
    assert compose(lib).files == compose(lib).files


# ---- over HTTP: preview, keep, export, install ---------------------------------------------------------

from fastapi.testclient import TestClient  # noqa: E402

from skillforge.api import create_app  # noqa: E402
from skillforge.library import import_source, read_zip_bytes, rescan  # noqa: E402

BODY = {
    "name": "my-plugin", "description": "Two helpers.", "author": "Jeswin",
    "components": [{"kind": "skill", "name": SKILL}, {"kind": "agent", "name": AGENT}],
}


def client_for(tmp_path):
    lib = make_library(tmp_path)
    return TestClient(create_app(lib), base_url="http://localhost"), lib


def test_a_preview_shows_files_capabilities_and_checks_and_keeps_nothing(tmp_path):
    client, lib = client_for(tmp_path)
    r = client.post("/api/plugins/preview", json=BODY)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version"] == "0.1.0" and body["failed"] is False and body["name"] == "my-plugin"
    assert [f["path"] for f in body["files"]] == [
        ".claude-plugin/marketplace.json", ".claude-plugin/plugin.json", "README.md", f"agents/{AGENT}.md",
        f"skills/{SKILL}/README.md", f"skills/{SKILL}/SKILL.md",
    ]
    assert body["capabilities"]["tools"] == ["Glob", "Grep", "Read"] and body["capabilities"]["notes"] == ["It can only read and search files."]
    assert json.loads(body["manifest"])["name"] == "my-plugin" and any(c["status"] == "passed" for c in body["checks"])
    assert lib.for_kind("plugin").names() == []  # a preview keeps nothing


def test_keeping_a_plugin_puts_it_in_its_own_library_and_the_same_content_makes_no_new_version(tmp_path):
    client, lib = client_for(tmp_path)
    saved = client.post("/api/plugins", json=BODY)
    assert saved.status_code == 200, saved.text
    assert saved.json()["created"] is True and saved.json()["version"]["tag"] == "v1"
    assert lib.names() == [SKILL] and lib.for_kind("plugin").names() == ["my-plugin"]
    assert [row["name"] for row in client.get("/api/library", params={"kind": "plugin"}).json()] == ["my-plugin"]
    again = client.post("/api/plugins", json=BODY)
    assert again.status_code == 200 and again.json()["created"] is False  # nothing changed, so no second version
    assert len(lib.for_kind("plugin").versions("my-plugin")) == 1


def test_a_changed_component_makes_a_new_plugin_version_with_the_next_version_number(tmp_path):
    client, lib = client_for(tmp_path)
    client.post("/api/plugins", json=BODY)
    import_skill(write_skill(tmp_path / SKILL, body="A different body.\n"), lib)  # demo-skill is now v2
    second = client.post("/api/plugins", json=BODY).json()
    assert second["created"] is True and second["version"]["tag"] == "v2"
    plugins = lib.for_kind("plugin")
    assert json.loads(plugins.read("my-plugin", 1)[1][".claude-plugin/plugin.json"])["version"] == "0.1.0"
    assert json.loads(plugins.read("my-plugin", 2)[1][".claude-plugin/plugin.json"])["version"] == "0.1.1"  # a pinned version must change to update
    assert [c["version"] for c in json.loads(client.post("/api/plugins/preview", json=BODY).text)["components"]] == ["v2", "v1"]


def test_bad_input_is_a_plain_error_and_nothing_is_kept(tmp_path):
    client, lib = client_for(tmp_path)
    for bad, code in (
        ({**BODY, "name": "claude-helpers"}, 400), ({**BODY, "name": "Bad Name"}, 400), ({**BODY, "description": " "}, 400),
        ({**BODY, "components": [{"kind": "skill", "name": "no-such-skill"}]}, 404),
        ({**BODY, "components": [{"kind": "skill", "name": SKILL}, {"kind": "skill", "name": SKILL}]}, 400),
        ({**BODY, "components": []}, 422), ({**BODY, "components": [{"kind": "plugin", "name": "x"}]}, 422),
    ):
        for route in ("/api/plugins/preview", "/api/plugins"):
            assert client.post(route, json=bad).status_code == code, (bad, route)
    assert lib.for_kind("plugin").names() == []
    assert "reserved" in client.post("/api/plugins", json={**BODY, "name": "claude-helpers"}).json()["detail"]


def test_a_kept_plugin_exports_and_imports_back_identical_and_rescans_the_same(tmp_path):
    client, lib = client_for(tmp_path)
    client.post("/api/plugins", json=BODY)
    exported = client.get("/api/library/my-plugin/export", params={"kind": "plugin"})
    assert exported.status_code == 200
    elsewhere = Library(tmp_path / "elsewhere").for_kind("plugin")
    report = import_source(read_zip_bytes(exported.content, "x.zip"), elsewhere)  # the zip's one top folder holds .claude-plugin/
    assert not report.refused and report.name == "my-plugin"
    assert report.version.content_hash == lib.for_kind("plugin").pick("my-plugin").content_hash
    assert [scan.status for scan in rescan(lib.for_kind("plugin"))] == ["same"]


def test_a_plugin_installs_from_a_folder_only(tmp_path):
    client, lib = client_for(tmp_path)
    client.post("/api/plugins", json=BODY)
    out = tmp_path / "out"
    ok = client.post("/api/library/my-plugin/install", params={"kind": "plugin"}, json={"target": "folder", "folder": str(out)})
    assert ok.status_code == 200, ok.text
    assert json.loads((out / "my-plugin" / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["name"] == "my-plugin"
    assert (out / "my-plugin" / "agents" / f"{AGENT}.md").exists() and (out / "my-plugin" / "skills" / SKILL / "SKILL.md").exists()
    personal = client.post("/api/library/my-plugin/install", params={"kind": "plugin"}, json={"target": "personal"})
    assert personal.status_code == 400 and "folder" in personal.json()["detail"]


def test_a_plugin_that_fails_its_own_checks_is_refused_in_the_usual_shape_and_nothing_is_kept(tmp_path):
    client, lib = client_for(tmp_path)
    sneaky = {**BODY, "description": "Two helpers.‮ hidden direction change"}  # a bidi override hides text from a reader
    preview = client.post("/api/plugins/preview", json=sneaky).json()
    assert preview["failed"] is True
    refused = client.post("/api/plugins", json=sneaky)
    assert refused.status_code == 422
    body = refused.json()
    assert body["refused"] is True and body["created"] is False and body["version"] is None and body["name"] == "my-plugin"
    assert any(c["status"] == "failed" and "hidden" in c["name"] for c in body["checks"]) and body["changes"] == [] and body["risk"] is None
    assert lib.for_kind("plugin").names() == []


def test_a_reserved_name_in_a_zip_from_outside_is_refused_on_import(tmp_path):
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr(".claude-plugin/plugin.json", json.dumps({"name": "claude-helpers", "version": "0.1.0"}))
        z.writestr("skills/demo-skill/SKILL.md", "---\nname: demo-skill\ndescription: Says hello.\n---\n\nSay hello.\n")
    plugins = Library(tmp_path / "plugins").for_kind("plugin")
    report = import_source(read_zip_bytes(buffer.getvalue(), "outside.zip"), plugins)
    assert report.refused and plugins.names() == []
    assert any(c.status == FAILED and "reserved" in c.detail for c in report.checks)


@pytest.mark.parametrize("path", ["../x", "a/../b", "/abs", "..", ""])
def test_a_component_file_that_would_leave_the_plugin_folder_is_refused(path):
    from skillforge.library.plugin import _inside

    with pytest.raises(PluginError, match="outside"):
        _inside(path)
    assert _inside("scripts/a.py") == "scripts/a.py"
