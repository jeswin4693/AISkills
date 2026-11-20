"""The agent kind inside the app: a whole conversation over HTTP, its own library, export and import, and installing one file.
Offline: a mock model, a temp data folder."""

from __future__ import annotations

import pytest
from test_agent_build import WORDS, agent_draft, agent_extraction
from test_builder import Env, make  # noqa: F401  (make is a pytest fixture)

from skillforge.kinds import KINDS, get_kind
from skillforge.kinds.agent import AgentKind
from skillforge.library import Conflict, Library, import_skill, import_source, install_skill, read_zip_bytes, rescan, risk_diff
from skillforge.library.risk import RISKIER, SAFER

NAME = "pr-security-reviewer"


def built_agent(env: Env) -> str:
    """Start, approve and finish an agent build (the model says everything is answered in one round) and return the session id."""
    started = env.start(WORDS, kind="agent")
    assert started["kind"] == "agent" and started["status"] == "awaiting_approval"
    assert env.post(started["id"], "approve").status_code == 200
    return started["id"]


def test_a_whole_agent_conversation_over_http_lands_in_the_agent_library(make):
    env = make([agent_extraction(), agent_draft()])
    sid = built_agent(env)
    done = env.get(sid)
    assert done["status"] == "done" and done["model_calls"] == 2 and done["error"] == ""
    result = done["result"]
    assert result["name"] == NAME and result["status"] == "ok" and result["counts"]["failed"] == 0 and result["scripts"] == 0
    assert "AGENT.md" in result["files"] and "report.md" in result["files"] and result["folder"] == NAME
    assert env.client.get(f"/api/builds/{sid}/files/AGENT.md").json()["text"].startswith(f"---\nname: {NAME}\n")

    saved = env.post(sid, "save").json()
    assert saved["created"] and saved["version"]["tag"] == "v1"
    assert env.library.names() == []  # not in the skill library
    assert env.library.for_kind("agent").names() == [NAME]
    assert [row["name"] for row in env.client.get("/api/library", params={"kind": "agent"}).json()] == [NAME]
    assert env.client.get("/api/library").json() == []


def test_an_agent_request_is_never_refused_for_what_the_extraction_called_it(make):
    env = make([agent_extraction(kind="skill"), agent_draft()])  # the model's guess of the kind must not block an agent
    assert env.start(WORDS, kind="agent")["status"] == "awaiting_approval"


def test_the_agent_builder_asks_in_agent_words_only_what_is_missing(make):
    env = make([agent_extraction(constraints=agent_extraction().constraints.model_copy(update=dict(values=[], quote="")))])
    started = env.start(WORDS, kind="agent")
    assert started["status"] == "awaiting_answers" and [q["slot"] for q in started["questions"]] == ["constraints"]
    assert "may touch" in started["questions"][0]["text"]  # the agent wording, not the skill's


def test_exporting_an_agent_and_importing_it_again_gives_identical_content(make, tmp_path):
    env = make([agent_extraction(), agent_draft()])
    env.post(built_agent(env), "save")
    agents = env.library.for_kind("agent")
    exported = env.client.get(f"/api/library/{NAME}/export", params={"kind": "agent"})
    assert exported.status_code == 200
    elsewhere = Library(tmp_path / "elsewhere").for_kind("agent")
    report = import_source(read_zip_bytes(exported.content, "x.zip"), elsewhere)  # the zip has one top folder with AGENT.md in it
    assert not report.refused and report.name == NAME
    assert report.version.content_hash == agents.pick(NAME).content_hash
    assert [scan.status for scan in rescan(agents)] == ["same"]


def test_installing_an_agent_writes_one_file_and_never_replaces_one_without_force(make, tmp_path):
    env = make([agent_extraction(), agent_draft()])
    env.post(built_agent(env), "save")
    agents = env.library.for_kind("agent")
    target = tmp_path / "agents"
    report = install_skill(agents, NAME, None, target)
    assert sorted(p.name for p in target.iterdir()) == [f"{NAME}.md"] and report.path == target / f"{NAME}.md"
    _, files = agents.read(NAME)
    assert report.path.read_bytes() == files["AGENT.md"]
    with pytest.raises(Conflict, match="already exists"):
        install_skill(agents, NAME, None, target)
    report.path.write_text("my own edits", encoding="utf-8")
    forced = install_skill(agents, NAME, None, target, force=True)
    assert forced.backup is not None and forced.backup.read_text(encoding="utf-8") == "my own edits"
    assert forced.backup.parent == agents.backups and forced.path.read_bytes() == files["AGENT.md"]
    assert sorted(p.name for p in target.iterdir()) == [f"{NAME}.md"]  # no staging file left behind


def test_installing_for_me_goes_to_the_agents_folder_the_kind_names(make, tmp_path, monkeypatch):
    monkeypatch.setattr(AgentKind, "personal_dir", lambda self: tmp_path / "mine")
    env = make([agent_extraction(), agent_draft()])
    env.post(built_agent(env), "save")
    r = env.client.post(f"/api/library/{NAME}/install", params={"kind": "agent"}, json={"target": "personal"})
    assert r.status_code == 200, r.text
    assert (tmp_path / "mine" / f"{NAME}.md").exists()


def agent_files(tools: str, body: str = "You are a reviewer.\n", description: str = "Reviews a diff.") -> dict[str, bytes]:
    return {"AGENT.md": f"---\nname: demo-agent\ndescription: {description}\ntools: {tools}\n---\n\n{body}".encode()}


def test_the_risk_diff_sees_an_agent_gaining_tools_and_names_its_own_file():
    read, more = agent_files("Read, Grep, Glob"), agent_files("Read, Grep, Glob, Bash, Write")
    diff = risk_diff(read, more, "v1", "v2", kind="agent")
    tool = [c for c in diff.changes if c.kind == "tool"]
    assert len(tool) == 1 and tool[0].direction == RISKIER and tool[0].path == "AGENT.md"
    assert tool[0].detail.startswith("tools now also lists") and "Bash" in tool[0].detail and "Write" in tool[0].detail
    assert diff.level == "more_risk"
    safer = [c for c in risk_diff(more, read, "v2", "v3", kind="agent").changes if c.kind == "tool"]
    assert len(safer) == 1 and safer[0].direction == SAFER and "no longer lists" in safer[0].detail


def test_the_risk_diff_talks_about_the_agents_own_file_not_a_skill_file():
    changed = risk_diff(agent_files("Read"), agent_files("Read", body="You are a reviewer. Also be kind.\n", description="Reviews code."), kind="agent")
    kinds = {c.kind: c for c in changed.changes}
    assert "AGENT.md" in kinds["instructions"].detail and kinds["description"].path == "AGENT.md" and "use the agent" in kinds["description"].detail
    assert not any("SKILL.md" in c.detail for c in changed.changes)


def test_a_new_agent_version_that_adds_a_tool_is_reported_riskier_on_import(tmp_path):
    agents = Library(tmp_path / "library").for_kind("agent")
    src = tmp_path / "demo-agent"
    src.mkdir()
    (src / "AGENT.md").write_bytes(agent_files("Read, Grep, Glob")["AGENT.md"])
    assert import_skill(src, agents).risk is None  # a first version has nothing before it
    (src / "AGENT.md").write_bytes(agent_files("Read, Grep, Glob, Bash")["AGENT.md"])
    second = import_skill(src, agents)
    assert second.created and second.risk is not None
    assert any(c.kind == "tool" and c.direction == RISKIER and "Bash" in c.detail for c in second.risk.changes)


def test_the_kinds_endpoint_lists_both_kinds_with_their_definition_files(make):
    env = make([])
    kinds = {k["key"]: k for k in env.client.get("/api/kinds").json()}
    assert list(kinds) == ["skill", "agent", "plugin"]
    assert kinds["skill"]["definition_file"] == "SKILL.md" and kinds["agent"]["definition_file"] == "AGENT.md"
    assert [s["key"] for s in kinds["agent"]["slots"]][:2] == ["goal", "inputs"] and kinds["agent"]["slots"][0]["label"] == "What it is for"
    # what the install dialog says, so the page does not hard-code folder names
    assert (kinds["skill"]["personal_label"], kinds["skill"]["installs_as_file"]) == ("~/.claude/skills", False)
    assert (kinds["agent"]["personal_label"], kinds["agent"]["installs_as_file"]) == ("~/.claude/agents", True)


def test_the_agent_kind_in_the_registry(tmp_path, monkeypatch):
    kind = get_kind("agent")
    assert isinstance(kind, AgentKind) and list(KINDS) == ["skill", "agent", "plugin"]
    assert (kind.library_dir, kind.definition_file, kind.install_file) == ("library-agent", "AGENT.md", "AGENT.md")
    assert kind.name_of({"AGENT.md": b"---\nname: demo-agent\n---\nbody"}) == "demo-agent"
    assert kind.name_of({"AGENT.md": b"---\nname: ../x\n---\nbody"}) is None and kind.name_of({"SKILL.md": b"---\nname: a\n---\n"}) is None
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    assert kind.personal_dir() == tmp_path / ".claude" / "agents"
