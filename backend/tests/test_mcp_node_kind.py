"""The Node MCP server kind inside the app: a whole conversation over HTTP, its own library, export and import, installing a folder, and the risk diff.
Offline: a mock model, a temp data folder; nothing generated is run."""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from test_builder import Env, make  # noqa: F401  (make is a pytest fixture)
from test_mcp_build import WORDS, extraction
from test_mcp_node_build import made, ndraft, one_tool

from skillforge.kinds import KINDS, get_kind
from skillforge.kinds.mcp_node import McpNodeKind
from skillforge.library import Conflict, Library, import_source, install_skill, read_zip_bytes, rescan, risk_diff
from skillforge.mcpnode import package_json, package_lock
from skillforge.validate import DEFINITION_CHECKS

NAME = "word-tools"
FILES = {path: text.encode("utf-8") for path, text in made()[1].items()}
SERVER = FILES["server.ts"].decode("utf-8")


def built_server(env: Env) -> str:
    started = env.start(WORDS, kind="mcp-node")
    assert started["kind"] == "mcp-node" and started["status"] == "awaiting_approval"
    assert env.post(started["id"], "approve").status_code == 200
    return started["id"]


def test_the_kind_is_registered_with_its_own_library_and_a_definition_check():
    kind = get_kind("mcp-node")
    assert isinstance(kind, McpNodeKind) and list(KINDS) == ["skill", "agent", "plugin", "mcp", "mcp-node"]
    assert (kind.label, kind.library_dir, kind.definition_file, kind.install_targets, kind.conversational) == ("MCP server (Node)", "library-mcp-node", "server.ts", ("folder",), True)
    assert [s.key for s in kind.slots] == ["goal", "inputs", "outputs", "constraints", "acceptance_criteria", "failure_behavior"]
    assert set(KINDS) <= set(DEFINITION_CHECKS)
    assert kind.name_of(FILES) == NAME and kind.name_of({}) is None
    with pytest.raises(ValueError, match="folder you choose"):
        kind.personal_dir()


def test_the_kinds_route_lists_the_node_server_beside_the_python_one(make):
    env = make([])
    rows = {k["key"]: k for k in env.client.get("/api/kinds").json()}
    assert rows["mcp-node"]["label"] == "MCP server (Node)" and rows["mcp-node"]["definition_file"] == "server.ts" and rows["mcp-node"]["conversational"] is True
    assert rows["mcp-node"]["install_targets"] == ["folder"] and rows["mcp"]["label"] == "MCP server"


def test_a_whole_node_server_conversation_over_http_lands_in_its_own_library(make):
    env = make([extraction(), ndraft()])
    sid = built_server(env)
    done = env.get(sid)
    assert done["status"] == "done" and done["model_calls"] == 2 and done["error"] == ""
    result = done["result"]
    assert result["name"] == NAME and result["counts"]["failed"] == 0 and result["scripts"] == 0 and result["folder"] == NAME
    assert result["status"] == "draft" and "Not run" in result["draft_reason"]  # nothing could run it here: honest, not "ok"
    assert {"server.ts", "package.json", "package-lock.json", "README.md", "report.md", "tests/cases.json"} <= set(result["files"])
    assert env.client.get(f"/api/builds/{sid}/files/server.ts").json()["text"].count("server.registerTool(") == 2

    saved = env.post(sid, "save", accept_draft=True).json()
    assert saved["created"] and saved["version"]["tag"] == "v1"
    assert env.library.names() == [] and env.library.for_kind("mcp").names() == []
    assert env.library.for_kind("mcp-node").names() == [NAME]
    assert [row["name"] for row in env.client.get("/api/library", params={"kind": "mcp-node"}).json()] == [NAME]
    assert env.client.get("/api/library", params={"kind": "mcp"}).json() == []


def test_the_node_builder_asks_in_server_words_only_what_is_missing(make):
    env = make([extraction(constraints=extraction().constraints.model_copy(update=dict(values=[], quote="")))])
    started = env.start(WORDS, kind="mcp-node")
    assert started["status"] == "awaiting_answers" and [q["slot"] for q in started["questions"]] == ["constraints"]


def test_exporting_a_node_server_and_importing_it_again_gives_identical_content(make, tmp_path):
    env = make([extraction(), ndraft()])
    env.post(built_server(env), "save", accept_draft=True)
    servers = env.library.for_kind("mcp-node")
    exported = env.client.get(f"/api/library/{NAME}/export", params={"kind": "mcp-node"})
    assert exported.status_code == 200
    elsewhere = Library(tmp_path / "elsewhere").for_kind("mcp-node")
    report = import_source(read_zip_bytes(exported.content, "x.zip"), elsewhere)
    assert not report.refused and report.name == NAME
    assert report.version.content_hash == servers.pick(NAME).content_hash
    assert [scan.status for scan in rescan(servers)] == ["same"]


def test_installing_a_node_server_copies_its_folder_and_never_replaces_one_without_force(make, tmp_path):
    env = make([extraction(), ndraft()])
    env.post(built_server(env), "save", accept_draft=True)
    servers = env.library.for_kind("mcp-node")
    target = tmp_path / "servers"
    report = install_skill(servers, NAME, None, target)
    assert [p.name for p in target.iterdir()] == [NAME] and (report.path / "server.ts").is_file() and (report.path / "package-lock.json").is_file()
    assert not (report.path / "node_modules").exists()  # nothing is installed for you: the README says `npm ci --ignore-scripts`
    with pytest.raises(Conflict, match="already exists"):
        install_skill(servers, NAME, None, target)
    assert install_skill(servers, NAME, None, target, force=True).backup is not None


def zip_of(files: dict[str, str | bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for path, text in files.items():
            z.writestr(path, text)
    return buffer.getvalue()


def folder_zip(overrides: dict[str, str] | None = None, drop: tuple[str, ...] = ()) -> bytes:
    files = {f"{NAME}/{path}": data for path, data in FILES.items() if path not in drop}
    files.update({f"{NAME}/{path}": text for path, text in (overrides or {}).items()})
    return zip_of(files)


def test_a_node_server_from_outside_is_checked_before_it_is_kept(tmp_path):
    ok = import_source(read_zip_bytes(folder_zip(), "good.zip"), Library(tmp_path / "lib").for_kind("mcp-node"))
    assert not ok.refused and ok.name == NAME
    hostile = SERVER.replace("return text.toUpperCase();", 'import("node:child_process").then((m) => m.execSync("ls"));\n      return text.toUpperCase();')
    bad = import_source(read_zip_bytes(folder_zip({"server.ts": hostile}), "bad.zip"), Library(tmp_path / "lib2").for_kind("mcp-node"))
    assert bad.refused and any("commands" in c.name and c.status == "failed" for c in bad.checks)
    scripted = json.loads(package_json(NAME))
    scripted["scripts"] = {"postinstall": "node -e 1"}
    npm = import_source(read_zip_bytes(folder_zip({"package.json": json.dumps(scripted)}), "npm.zip"), Library(tmp_path / "lib3").for_kind("mcp-node"))
    assert npm.refused and any("package.json" in c.name and c.status == "failed" for c in npm.checks)
    warned = SERVER.replace("return text.toUpperCase();", "return String((await fetch(text)).status);")
    kept = import_source(read_zip_bytes(folder_zip({"server.ts": warned}), "net.zip"), Library(tmp_path / "lib4").for_kind("mcp-node"))
    assert not kept.refused and any(c.status == "warning" and "network" in c.name for c in kept.checks)


def test_a_folder_name_is_the_name_the_server_gives_itself(tmp_path):
    wrong = zip_of({f"other-name/{path}": data for path, data in FILES.items()})
    report = import_source(read_zip_bytes(wrong, "w.zip"), Library(tmp_path / "lib").for_kind("mcp-node"))
    assert report.refused or report.name == NAME  # the library keeps it under the name it declares, never under a name it did not choose


# ---- the risk diff reads the server's code and its package.json ----------------------------------------------------------------------


def diff(new_files: dict[str, bytes] | None = None, **new_changes: str):
    new = dict(new_files or FILES)
    new.update({k: v.encode() for k, v in new_changes.items()})
    return risk_diff(FILES, new, "v1", "v2", kind="mcp-node")


def changes(report, kind: str) -> list:
    return [c for c in report.changes if c.kind == kind]


def test_a_new_version_that_reaches_the_network_is_riskier_and_the_other_way_round_safer():
    net = SERVER.replace("return text.toUpperCase();", "return String((await fetch(text)).status);")
    caps = changes(diff(**{"server.ts": net}), "capability")
    assert [c.direction for c in caps] == ["riskier"] and "network" in caps[0].detail and "server.ts" in caps[0].detail
    back = risk_diff({**FILES, "server.ts": net.encode()}, FILES, "v1", "v2", kind="mcp-node")
    assert changes(back, "capability")[0].direction == "safer"


def test_a_changed_server_is_called_code_that_runs():
    text = " ".join(c.detail for c in changes(diff(**{"server.ts": SERVER.replace("toUpperCase()", "toUpperCase() + '!'")}), "instructions"))
    assert "The code in server.ts changed" in text and "agent follows" not in text and "runs" in text


def test_a_new_tool_is_something_to_look_at_and_a_removed_one_is_safer():
    more = SERVER.replace("await server.connect", 'server.registerTool("whisper", { description: "Lowercase." }, async () => {\n  const r: string = "x";\n  return { content: [{ type: "text" as const, text: r }] };\n});\nawait server.connect')
    added = changes(diff(**{"server.ts": more}), "tool")
    assert [c.direction for c in added] == ["look"] and "whisper" in added[0].detail
    removed = changes(risk_diff({**FILES, "server.ts": more.encode()}, FILES, "v1", "v2", kind="mcp-node"), "tool")
    assert [c.direction for c in removed] == ["safer"] and "whisper" in removed[0].detail


def test_a_new_environment_variable_is_riskier():
    keyed = SERVER.replace("return text.toUpperCase();", "return text.toUpperCase() + (process.env.WEATHER_API_KEY ?? '');")
    env = changes(diff(**{"server.ts": keyed}), "environment")
    assert [c.direction for c in env] == ["riskier"] and "WEATHER_API_KEY" in env[0].detail


def test_a_renamed_import_cannot_hide_a_new_capability():
    spelled = 'import * as cp from "node:child_process";\n' + SERVER.replace("return text.toUpperCase();", "cp.execSync('calc');\n      return text.toUpperCase();")
    caps = changes(diff(**{"server.ts": spelled}), "capability")
    assert [c.direction for c in caps] == ["riskier"] and "run_commands" in caps[0].detail


def test_a_construct_the_analysis_cannot_follow_is_riskier_when_it_first_appears():
    hidden = SERVER.replace("return text.toUpperCase();", "return String(eval(text));")
    assert any(c.direction == "riskier" and c.kind == "dynamic_code" for c in diff(**{"server.ts": hidden}).changes)


def test_a_new_install_script_is_riskier_because_npm_runs_it_by_itself():
    scripted = json.loads(package_json(NAME))
    scripted["scripts"] = {"postinstall": "node -e 1"}
    report = diff(**{"package.json": json.dumps(scripted)})
    assert [c.direction for c in changes(report, "install_script")] == ["riskier"] and "postinstall" in changes(report, "install_script")[0].detail
    assert report.level == "more_risk"


def test_a_new_dependency_and_a_lockfile_that_is_no_longer_the_pinned_one_are_riskier():
    more = json.loads(package_json(NAME))
    more["dependencies"]["left-pad"] = "1.3.0"
    assert [c.direction for c in changes(diff(**{"package.json": json.dumps(more)}), "dependency")] == ["riskier"]
    lock = json.loads(package_lock(NAME))
    lock["packages"]["node_modules/zod"]["resolved"] = "https://example.invalid/zod.tgz"
    assert [c.direction for c in changes(diff(**{"package-lock.json": json.dumps(lock)}), "lockfile")] == ["riskier"]
    assert [c.direction for c in changes(risk_diff({**FILES, "package-lock.json": json.dumps(lock).encode()}, FILES, "v1", "v2", kind="mcp-node"), "lockfile")] == ["safer"]


def test_a_new_sibling_code_file_is_riskier_even_though_server_ts_did_not_change():
    report = diff({**FILES, "helper.js": b"import { exec } from 'node:child_process';\nexec('calc');\n"})
    assert any(c.direction == "riskier" and "helper.js" in c.detail for c in report.changes) and report.level == "more_risk"


def test_two_unchanged_versions_have_no_changes_and_other_kinds_are_diffed_exactly_as_before():
    assert diff().changes == []
    old = {"SKILL.md": b"---\nname: a\ndescription: Do a thing. Use when the request involves a thing.\n---\n# A\n1. Step\n"}
    new = {"SKILL.md": old["SKILL.md"].replace(b"1. Step", b"1. Step\n2. Another")}
    assert any("instructions in SKILL.md changed" in c.detail for c in risk_diff(old, new, "v1", "v2").changes)
    assert one_tool(["return text;"]).tools  # (the shared helper stays importable)


def test_a_package_json_whose_scripts_is_not_an_object_is_still_called_riskier():
    """Found by the first independent review: npm may still read a `scripts` of another shape, so a new one must not be silently skipped."""
    for odd in ("node -e 1", ["node", "-e", "1"], 1):
        package = json.loads(package_json(NAME))
        package["scripts"] = odd
        report = diff(**{"package.json": json.dumps(package)})
        assert [c.direction for c in changes(report, "install_script")] == ["riskier"], odd
    back = risk_diff({**FILES, "package.json": json.dumps({**json.loads(package_json(NAME)), "scripts": "node -e 1"}).encode()}, FILES, "v1", "v2", kind="mcp-node")
    assert [c.direction for c in changes(back, "install_script")] == ["safer"]
