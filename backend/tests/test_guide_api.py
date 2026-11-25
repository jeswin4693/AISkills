"""Slice AB: the guide over HTTP and on the command line, for a folder and for a GitHub link. Offline: a mock model, the page's fake download, small
repositories in a temp folder."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from test_builder import make  # noqa: F401  (a pytest fixture)
from test_github_link import LINK, managed_path_leaks, served, zip_of  # noqa: F401  (served is a pytest fixture: the archive GitHub 'serves')
from test_guide import J, P, Q_API, Q_WEB, README, S
from test_hosted import TOKEN, hosted

from skillforge import cli
from skillforge.api import create_app
from skillforge.builder import github as gh
from skillforge.db import Database
from skillforge.guide.models import GuideDraft
from skillforge.providers import MockProvider, ProviderError

FILES = {
    "README.md": README,
    "web/app.py": "from api.routes import route\n\n\ndef page():\n    return route()\n",
    "api/routes.py": "def route():\n    return 1\n",
}
DRAFT = GuideDraft(parts=[P("web", "use", "web", Q_WEB), P("api", "door", "api", Q_API)], journeys=[J(S("web", Q_WEB), S("api", Q_API))])


def leaks(root, doc) -> bool:
    """Whether the folder the repository sits in (a person's own path) appears in a response, compared as JSON text so backslashes are not missed."""
    return json.dumps(str(root.parent))[1:-1] in json.dumps(doc)


def broken(message="No AI model is set up. Put its settings in the .env file."):
    def factory():
        raise ProviderError(message)

    return factory


# ---- the API ---------------------------------------------------------------------------------------------------------


def test_the_guide_for_a_folder_is_drawn_from_its_readme_and_checked_against_its_code(make, repo):
    root = repo(FILES)
    env = make([DRAFT])
    r = env.client.post("/api/repos/guide", json={"path": str(root)})
    doc = r.json()
    assert r.status_code == 200 and doc["status"] == "ok" and doc["name"] == root.name and doc["source"] == {"kind": "folder"}
    assert [(p["name"], p["status"], p["folder"]) for p in doc["parts"]] == [("Web", "in_code", "web"), ("Api", "in_code", "api")]
    hop = doc["journeys"][0]["hops"][0]  # web/app.py really imports api/routes.py, and the page is shown which file pair says so
    assert (hop["from"], hop["to"], hop["status"], hop["forward"], hop["reverse"]) == ("p1", "p2", "confirmed", 1, 0)
    assert hop["evidence"] == [{"importer": "web/app.py", "imported": "api/routes.py"}]
    assert [d["path"] for d in doc["docs"]] == ["README.md"] and len(env.mock.calls) == 1
    assert not leaks(root, doc) and str(root.parent) not in env.mock.calls[0]["prompt"]


def test_a_repository_with_no_readme_gets_an_answer_and_no_model_is_asked(make, repo):
    env = make([])
    env.builder.provider_factory = broken()  # not even a key is needed to be told there is nothing to read
    r = env.client.post("/api/repos/guide", json={"path": str(repo({"web/app.py": "x = 1\n"}))})
    assert r.status_code == 200 and r.json()["status"] == "no_docs" and r.json()["parts"] == [] and env.mock.calls == []


def test_without_a_model_the_person_is_told_and_nothing_is_drawn(make, repo):
    env = make([])
    env.builder.provider_factory = broken("No AI model is set up. Put its settings in the .env file.")
    r = env.client.post("/api/repos/guide", json={"path": str(repo(FILES))})
    assert r.status_code == 502 and "No AI model is set up" in r.json()["detail"]


def test_a_model_that_fails_is_a_plain_message_and_not_a_crash(make, repo):
    root = repo(FILES)
    r = make([ProviderError("The model has no quota left."), ProviderError("The model has no quota left.")]).client.post("/api/repos/guide", json={"path": str(root)})
    assert r.status_code == 502 and "quota" in r.json()["detail"] and not leaks(root, r.json())


def test_a_model_whose_quotes_are_not_in_the_readme_draws_nothing(make, repo):
    invented = GuideDraft(parts=[P("web", "use", "web", "The web page encrypts every order."), P("api", "door", "api", "The API signs every order.")], journeys=[])
    doc = make([invented]).client.post("/api/repos/guide", json={"path": str(repo(FILES))}).json()
    assert doc["status"] == "thin" and doc["parts"] == [] and [d["reason"] for d in doc["dropped"]] == ["quote_not_found"] * 2


def test_the_documents_inside_the_focus_folder_are_read_first(make, repo):
    root = repo({"README.md": "# Top\n", "pkg/README.md": README, "pkg/x.py": "x = 1\n"})
    env = make([GuideDraft(parts=[P("web", "use", "", Q_WEB), P("api", "door", "", Q_API)], journeys=[])])
    doc = env.client.post("/api/repos/guide", json={"path": str(root), "focus": "pkg"}).json()
    assert doc["status"] == "ok" and doc["focus"] == "pkg" and [d["path"] for d in doc["docs"]] == ["pkg/README.md", "README.md"]
    assert env.mock.calls[0]["prompt"].index('<doc path="pkg/README.md">') < env.mock.calls[0]["prompt"].index('<doc path="README.md">')


@pytest.mark.parametrize("path", ["", "relative/folder", "nowhere", "//server/share"])
def test_a_path_that_is_not_a_folder_on_this_computer_is_refused_in_plain_words(make, tmp_path, path):
    r = make([]).client.post("/api/repos/guide", json={"path": str(tmp_path / path) if path == "nowhere" else path})
    assert r.status_code == 400 and "nowhere" not in r.json()["detail"] and str(tmp_path) not in r.json()["detail"]


def test_the_guide_is_off_in_the_hosted_version(tmp_path, repo):
    from skillforge.builder import Builder, JobRunner
    from skillforge.library import Library

    db = Database(f"sqlite:///{(tmp_path / 'h.db').as_posix()}")
    db.migrate()
    lib = Library(tmp_path / "library")
    builder = Builder(db, lib, tmp_path / "builds", provider_factory=lambda: MockProvider([DRAFT]), runner=JobRunner(inline=True))
    client = TestClient(create_app(lib, builder=builder, hosted=hosted()), base_url="http://localhost")
    assert client.post("/api/auth/login", json={"token": TOKEN}).status_code == 200
    r = client.post("/api/repos/guide", json={"path": str(repo(FILES))})
    assert r.status_code == 403 and "hosted" in r.json()["detail"]
    builder.runner.shutdown()
    db.close()


# ---- a GitHub link ---------------------------------------------------------------------------------------------------


def test_a_link_is_downloaded_with_its_readme_and_drawn_like_a_folder(served, make):
    served["files"] = dict(FILES)
    doc = make([DRAFT]).client.post("/api/repos/guide", json={"path": LINK}).json()
    assert doc["status"] == "ok" and doc["name"] == "acme/shop-api" and doc["source"]["kind"] == "github" and doc["source"]["docs"] == 1
    assert [d["path"] for d in doc["docs"]] == ["README.md"] and doc["journeys"][0]["hops"][0]["status"] == "confirmed"
    assert not managed_path_leaks(doc) and served["calls"] == 1


def test_a_copy_made_before_documents_were_kept_is_downloaded_again(served, make):
    served["files"] = dict(FILES)
    env = make([DRAFT, DRAFT])
    assert env.client.post("/api/repos/guide", json={"path": LINK}).json()["status"] == "ok" and served["calls"] == 1
    assert env.client.post("/api/repos/guide", json={"path": LINK}).json()["source"]["reused"] is True and served["calls"] == 1  # a young copy is reused
    for meta_file in gh.snapshot_root().rglob("meta.json"):  # what an older version of SkillForge wrote: no record of documents
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        meta.pop("docs", None)
        meta_file.write_text(json.dumps(meta), encoding="utf-8")
    again = make([DRAFT]).client.post("/api/repos/guide", json={"path": LINK}).json()
    assert again["status"] == "ok" and served["calls"] == 2 and again["source"]["reused"] is False


def test_a_link_to_a_repository_without_a_readme_says_so_without_asking_a_model(served, make):
    served["files"] = {k: v for k, v in FILES.items() if k != "README.md"}
    env = make([])
    env.builder.provider_factory = broken()
    doc = env.client.post("/api/repos/guide", json={"path": LINK}).json()
    assert doc["status"] == "no_docs" and doc["source"]["kind"] == "github" and env.mock.calls == []


# ---- the command line ------------------------------------------------------------------------------------------------


def run(capsys, *argv: str):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_the_command_prints_the_outline_with_the_quote_behind_every_part(repo, monkeypatch, capsys):
    root = repo(FILES)
    monkeypatch.setattr(cli, "provider_from_env", lambda: MockProvider([DRAFT]))
    code, out, err = run(capsys, "guide", str(root))
    assert code == 0 and f"How {root.name} works, read from README.md" in out
    assert "WHAT PEOPLE USE" in out and "THE DOORS IN" in out and "folder found in the code: web (1 file)" in out
    assert f'docs say: "{Q_WEB}" (README.md:3)' in out and "JOURNEY: Place an order" in out
    assert "-> the code imports it (1 file pair, for example web/app.py imports api/routes.py)" in out
    assert "word for word" in out and str(root.parent) not in out + err


def test_the_command_can_print_the_same_answer_as_json(repo, monkeypatch, capsys):
    monkeypatch.setattr(cli, "provider_from_env", lambda: MockProvider([DRAFT]))
    code, out, _ = run(capsys, "guide", str(repo(FILES)), "--json")
    doc = json.loads(out)
    assert code == 0 and doc["status"] == "ok" and [p["id"] for p in doc["parts"]] == ["p1", "p2"]


def test_a_link_works_on_the_command_line_and_its_note_stays_out_of_the_json(served, monkeypatch, capsys):
    served["files"] = dict(FILES)
    monkeypatch.setattr(cli, "provider_from_env", lambda: MockProvider([DRAFT]))
    code, out, err = run(capsys, "guide", LINK, "--json")
    assert code == 0 and json.loads(out)["name"] == "acme/shop-api" and "Read acme/shop-api from GitHub" in err and "Read acme" not in out


def test_the_command_says_so_when_there_is_nothing_to_read_and_asks_no_model(repo, monkeypatch, capsys):
    def never():
        raise AssertionError("no model should be asked")

    monkeypatch.setattr(cli, "provider_from_env", never)
    code, out, _ = run(capsys, "guide", str(repo({"web/app.py": "x = 1\n"})))
    assert code == 0 and "No README or docs found" in out


def test_the_command_reports_a_missing_model_or_a_bad_folder_as_an_error(repo, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "provider_from_env", broken())
    code, _, err = run(capsys, "guide", str(repo(FILES)))
    assert code == 2 and "error:" in err and "No AI model is set up" in err
    code, _, err = run(capsys, "guide", str(tmp_path / "nowhere"))
    assert code == 2 and "Not a directory" in err and str(tmp_path) not in err
