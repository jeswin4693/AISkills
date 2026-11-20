"""The MCP server kind inside the app: a whole conversation over HTTP, its own library, export and import, and installing a
folder. Offline: a mock model, a temp data folder; nothing generated is run."""

from __future__ import annotations

import io
import zipfile

import pytest
from test_builder import Env, make  # noqa: F401  (make is a pytest fixture)
from test_mcp_build import WORDS, draft, extraction
from test_mcp_validate import GOOD

from skillforge.kinds import KINDS, get_kind
from skillforge.kinds.mcp import McpKind
from skillforge.library import Conflict, Library, import_source, install_skill, read_zip_bytes, rescan
from skillforge.validate import DEFINITION_CHECKS

NAME = "word-tools"


def built_server(env: Env) -> str:
    """Start, approve and finish a server build (the model says everything is answered in one round) and return the session id."""
    started = env.start(WORDS, kind="mcp")
    assert started["kind"] == "mcp" and started["status"] == "awaiting_approval"
    assert env.post(started["id"], "approve").status_code == 200
    return started["id"]


def test_the_kind_is_registered_with_its_own_library_and_a_definition_check():
    kind = get_kind("mcp")
    assert isinstance(kind, McpKind) and list(KINDS) == ["skill", "agent", "plugin", "mcp"]
    assert (kind.label, kind.library_dir, kind.definition_file, kind.install_targets, kind.conversational) == ("MCP server", "library-mcp", "server.py", ("folder",), True)
    assert [s.key for s in kind.slots] == ["goal", "inputs", "outputs", "constraints", "acceptance_criteria", "failure_behavior"]
    assert set(KINDS) <= set(DEFINITION_CHECKS)
    assert kind.name_of({"server.py": GOOD.encode()}) == NAME and kind.name_of({}) is None
    with pytest.raises(ValueError, match="folder you choose"):
        kind.personal_dir()


def test_the_kinds_route_lists_the_server_with_its_wording(make):
    env = make([])
    row = next(k for k in env.client.get("/api/kinds").json() if k["key"] == "mcp")
    assert row["label"] == "MCP server" and row["definition_file"] == "server.py" and row["conversational"] is True
    assert row["install_targets"] == ["folder"] and row["installs_as_file"] is False
    assert [s["key"] for s in row["slots"]][0] == "goal" and "Claude" in row["slots"][0]["question"]


def test_a_whole_server_conversation_over_http_lands_in_the_mcp_library(make):
    env = make([extraction(), draft()])
    sid = built_server(env)
    done = env.get(sid)
    assert done["status"] == "done" and done["model_calls"] == 2 and done["error"] == ""
    result = done["result"]
    assert result["name"] == NAME and result["counts"]["failed"] == 0 and result["scripts"] == 0 and result["folder"] == NAME
    assert result["status"] == "draft" and "Not run" in result["draft_reason"]  # nothing could run it here: honest, not "ok"
    assert {"server.py", "README.md", "requirements.txt", "report.md", "tests/cases.json"} <= set(result["files"])
    assert env.client.get(f"/api/builds/{sid}/files/server.py").json()["text"].count("@mcp.tool(") == 2

    saved = env.post(sid, "save", accept_draft=True).json()
    assert saved["created"] and saved["version"]["tag"] == "v1"
    assert env.library.names() == [] and env.library.for_kind("agent").names() == []
    assert env.library.for_kind("mcp").names() == [NAME]
    assert [row["name"] for row in env.client.get("/api/library", params={"kind": "mcp"}).json()] == [NAME]


def test_the_server_builder_asks_in_server_words_only_what_is_missing(make):
    env = make([extraction(constraints=extraction().constraints.model_copy(update=dict(values=[], quote="")))])
    started = env.start(WORDS, kind="mcp")
    assert started["status"] == "awaiting_answers" and [q["slot"] for q in started["questions"]] == ["constraints"]
    assert "network" in started["questions"][0]["text"]


def test_exporting_a_server_and_importing_it_again_gives_identical_content(make, tmp_path):
    env = make([extraction(), draft()])
    env.post(built_server(env), "save", accept_draft=True)
    servers = env.library.for_kind("mcp")
    exported = env.client.get(f"/api/library/{NAME}/export", params={"kind": "mcp"})
    assert exported.status_code == 200
    elsewhere = Library(tmp_path / "elsewhere").for_kind("mcp")
    report = import_source(read_zip_bytes(exported.content, "x.zip"), elsewhere)
    assert not report.refused and report.name == NAME
    assert report.version.content_hash == servers.pick(NAME).content_hash
    assert [scan.status for scan in rescan(servers)] == ["same"]


def test_installing_a_server_copies_its_folder_and_never_replaces_one_without_force(make, tmp_path):
    env = make([extraction(), draft()])
    env.post(built_server(env), "save", accept_draft=True)
    servers = env.library.for_kind("mcp")
    target = tmp_path / "servers"
    report = install_skill(servers, NAME, None, target)
    assert [p.name for p in target.iterdir()] == [NAME] and (report.path / "server.py").is_file() and (report.path / "requirements.txt").is_file()
    with pytest.raises(Conflict, match="already exists"):
        install_skill(servers, NAME, None, target)
    assert install_skill(servers, NAME, None, target, force=True).backup is not None


def zip_of(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for path, text in files.items():
            z.writestr(path, text)
    return buffer.getvalue()


def test_a_server_from_outside_is_checked_before_it_is_kept(tmp_path):
    servers = Library(tmp_path / "lib").for_kind("mcp")
    ok = import_source(read_zip_bytes(zip_of({f"{NAME}/server.py": GOOD}), "good.zip"), servers)
    assert not ok.refused and ok.name == NAME
    hostile = GOOD.replace("return text.upper()", "import os\n    os.system('ls')\n    return text.upper()")
    bad = import_source(read_zip_bytes(zip_of({f"{NAME}/server.py": hostile}), "bad.zip"), Library(tmp_path / "lib2").for_kind("mcp"))
    assert bad.refused and any("commands" in c.name and c.status == "failed" for c in bad.checks)
    warned = GOOD.replace("return text.upper()", "import urllib.request\n    return urllib.request.urlopen(text).read().decode()")
    kept = import_source(read_zip_bytes(zip_of({f"{NAME}/server.py": warned}), "net.zip"), Library(tmp_path / "lib3").for_kind("mcp"))
    assert not kept.refused and any(c.status == "warning" and "network" in c.name for c in kept.checks)


# ---- the risk diff reads the server's code -------------------------------------------------------------


def diff(new_source: str, old_source: str = GOOD):
    from skillforge.library import risk_diff

    return risk_diff({"server.py": old_source.encode()}, {"server.py": new_source.encode()}, "v1", "v2", kind="mcp")


def changes(report, kind: str) -> list:
    return [c for c in report.changes if c.kind == kind]


def test_a_new_version_that_reaches_the_network_is_riskier():
    net = GOOD.replace("return text.upper()", "import urllib.request\n    return urllib.request.urlopen(text).read().decode()")
    report = diff(net)
    caps = changes(report, "capability")
    assert [c.direction for c in caps] == ["riskier"] and "network" in caps[0].detail and "server.py" in caps[0].detail
    assert diff(GOOD, net).changes and changes(diff(GOOD, net), "capability")[0].direction == "safer"  # and the other way round


def test_a_changed_server_is_called_code_that_runs_not_instructions_an_agent_follows():
    report = diff(GOOD.replace("text.upper()", "text.upper() + '!'"))
    text = " ".join(c.detail for c in changes(report, "instructions"))
    assert "The code in server.py changed" in text and "agent follows" not in text and "runs" in text


def test_a_new_tool_is_something_to_look_at_and_a_removed_one_is_safer():
    more = GOOD.replace('\n\nif __name__', '\n\n@mcp.tool()\ndef whisper(text: str) -> str:\n    """Return the text in small letters."""\n    return text.lower()\n\n\nif __name__')
    added = changes(diff(more), "tool")
    assert [c.direction for c in added] == ["look"] and "whisper" in added[0].detail
    removed = changes(diff(GOOD, more), "tool")
    assert [c.direction for c in removed] == ["safer"] and "whisper" in removed[0].detail


def test_a_new_environment_variable_is_riskier():
    keyed = GOOD.replace("return text.upper()", 'import os\n    return text.upper() + os.environ.get("WEATHER_API_KEY", "")')
    env = changes(diff(keyed), "environment")
    assert [c.direction for c in env] == ["riskier"] and "WEATHER_API_KEY" in env[0].detail
    assert changes(diff(GOOD, keyed), "environment")[0].direction == "safer"


def test_skills_and_agents_are_diffed_exactly_as_before():
    from skillforge.library import risk_diff

    old = {"SKILL.md": b"---\nname: a\ndescription: Do a thing. Use when the request involves a thing.\n---\n# A\n1. Step\n"}
    new = {"SKILL.md": old["SKILL.md"].replace(b"1. Step", b"1. Step\n2. Another")}
    texts = [c.detail for c in risk_diff(old, new, "v1", "v2").changes]
    assert any("instructions in SKILL.md changed" in t and "An agent follows them" in t for t in texts)
