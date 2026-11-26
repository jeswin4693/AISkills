"""`skillforge canary`: the command line around the behavioural scan. A scripted model plays the agent; nothing real is asked."""

from __future__ import annotations

import json

import pytest
from test_canary_runner import SKILL, Agent, c, clean, exfiltrate, step

from skillforge import cli
from skillforge.library import Library
from skillforge.providers import MockProvider, ProviderError


def run_cli(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


@pytest.fixture
def skill_folder(tmp_path):
    folder = tmp_path / "invoice-summary"
    folder.mkdir()
    (folder / "SKILL.md").write_text(SKILL, encoding="utf-8")
    return folder


def use(monkeypatch, policy):
    agent = Agent(policy)
    monkeypatch.setattr(cli, "provider_from_env", lambda: MockProvider(agent))
    return agent


def test_a_clean_skill_exits_0_and_the_words_say_evidence_not_proof(skill_folder, monkeypatch, capsys):
    use(monkeypatch, clean)
    code, out, err = run_cli(capsys, "canary", str(skill_folder))
    assert code == 0
    assert "Behaviour scan of skill 'invoice-summary'" in out and "Nothing suspicious" in out and "not proof" in out
    assert "fake" in err and "model calls" in err  # the cost and the honesty come before the run, on stderr, so --json stays JSON


def test_a_skill_that_sends_a_secret_out_exits_1_and_shows_exactly_what_it_did(skill_folder, monkeypatch, capsys):
    use(monkeypatch, exfiltrate)
    code, out, _ = run_cli(capsys, "canary", str(skill_folder))
    assert code == 1
    assert "CRITICAL" in out and "https://stats.example.io/c" in out and "HIGH" in out and ".env" in out
    assert "control without the skill: nothing observed" in out and out.rstrip().splitlines()[-1].startswith("Flagged:")


def test_the_text_report_shows_what_the_model_finally_said_so_a_refusal_is_visible(skill_folder, monkeypatch, capsys):
    # Found by reading a real transcript: a model that refused showed as "0 steps, nothing observed", hiding the most telling line.
    use(monkeypatch, lambda side, message, n, prompt: step(done=True, reply="I cannot do that: it asks me to send private keys."))
    _, out, _ = run_cli(capsys, "canary", str(skill_folder), "--scenarios", "3")
    assert out.count('answer: "I cannot do that: it asks me to send private keys."') == 3


def test_a_long_answer_is_cut_so_the_report_stays_readable(skill_folder, monkeypatch, capsys):
    use(monkeypatch, lambda side, message, n, prompt: step(done=True, reply="word " * 200))
    _, out, _ = run_cli(capsys, "canary", str(skill_folder), "--scenarios", "3")
    answers = [line for line in out.splitlines() if "answer:" in line]
    assert answers and all(len(line) < 220 and line.rstrip().endswith('…"') for line in answers)


def test_json_output_is_pure_json_and_carries_the_outcome(skill_folder, monkeypatch, capsys):
    use(monkeypatch, exfiltrate)
    code, out, _ = run_cli(capsys, "canary", str(skill_folder), "--json")
    data = json.loads(out)
    assert code == 1 and data["outcome"] == "flagged" and data["verdict"].startswith("Flagged:") and data["runs"][0]["turns"]


def test_a_scan_that_could_not_finish_enough_exits_2(skill_folder, monkeypatch, capsys):
    use(monkeypatch, lambda *a: step(c("list_files", "/work")))
    code, out, _ = run_cli(capsys, "canary", str(skill_folder))
    assert code == 2 and "Too little ran" in out


def test_the_flags_change_what_is_run(skill_folder, monkeypatch, capsys):
    agent = use(monkeypatch, exfiltrate)
    code, out, _ = run_cli(capsys, "canary", str(skill_folder), "--json", "--runs", "2", "--scenarios", "3", "--no-control", "--no-draft")
    data = json.loads(out)
    assert data["runs_per_scenario"] == 2 and len(data["runs"]) == 6 and data["controls"] == [] and data["controlled"] is False
    assert "without" not in agent.sides


def test_the_model_is_asked_to_draft_tasks_unless_told_not_to(skill_folder, monkeypatch, capsys):
    agent = Agent(clean, drafted=["Summarise this invoice: Widget x10 at 2.50."])
    monkeypatch.setattr(cli, "provider_from_env", lambda: MockProvider(agent))
    run_cli(capsys, "canary", str(skill_folder), "--scenarios", "4")
    assert any("Widget x10" in p for p in agent.prompts)


def test_progress_goes_to_stderr_so_a_long_run_is_not_silent(skill_folder, monkeypatch, capsys):
    use(monkeypatch, clean)
    _, out, err = run_cli(capsys, "canary", str(skill_folder), "--scenarios", "3")
    assert "[1/3]" in err and "[3/3]" in err and "[1/3]" not in out


def test_a_skill_in_the_library_can_be_scanned_by_name(skill_folder, monkeypatch, capsys):
    use(monkeypatch, clean)
    assert run_cli(capsys, "library", "import", str(skill_folder))[0] == 0
    code, out, _ = run_cli(capsys, "canary", "--library", "invoice-summary")
    assert code == 0 and "invoice-summary" in out and Library().versions("invoice-summary")


def test_an_agent_folder_is_scanned_too(tmp_path, monkeypatch, capsys):
    folder = tmp_path / "reviewer"
    folder.mkdir()
    (folder / "AGENT.md").write_text("---\nname: reviewer\ndescription: Reviews code\ntools: Read\n---\nReview it.\n", encoding="utf-8")
    use(monkeypatch, clean)
    code, out, _ = run_cli(capsys, "canary", str(folder))
    assert code == 0 and "Behaviour scan of agent 'reviewer'" in out


def test_it_needs_exactly_one_thing_to_scan_and_instructions_to_read(skill_folder, tmp_path, monkeypatch, capsys):
    use(monkeypatch, clean)
    assert run_cli(capsys, "canary")[0] == 2
    assert "either a skill folder or --library" in run_cli(capsys, "canary", str(skill_folder), "--library", "x")[2]
    assert run_cli(capsys, "canary", str(tmp_path / "nowhere"))[0] == 2
    assert run_cli(capsys, "canary", "--library", "no-such-skill")[0] == 2
    empty = tmp_path / "plugin"
    empty.mkdir()
    (empty / "README.md").write_text("x", encoding="utf-8")
    code, _, err = run_cli(capsys, "canary", str(empty))
    assert code == 2 and "SKILL.md" in err


# ---- --measure: the corpus ----------------------------------------------------------------------------


def corpus_model(monkeypatch):
    """A scripted agent that obeys a skill only when the skill tells it to read .env."""
    agent = Agent(lambda side, message, n, prompt: exfiltrate("with", message, n, prompt) if side == "with" and ".env" in agent.systems[-1] else clean(side, message, n, prompt))
    monkeypatch.setattr(cli, "provider_from_env", lambda: MockProvider(agent))
    return agent


def test_measure_scans_the_corpus_and_prints_a_table_with_its_limits(monkeypatch, capsys):
    corpus_model(monkeypatch)
    code, out, err = run_cli(capsys, "canary", "--measure", "--only", "invoice-summary-debug", "invoice-summary", "--scenarios", "3")
    assert code == 0 and "invoice-summary-debug" in out and "flagged" in out and "nothing_observed" in out and "optimistic" in out
    assert "[1/2] invoice-summary-debug" in err and "[2/2] invoice-summary" in err


def test_measure_can_print_json(monkeypatch, capsys):
    corpus_model(monkeypatch)
    code, out, _ = run_cli(capsys, "canary", "--measure", "--only", "invoice-summary-debug", "invoice-summary", "--scenarios", "3", "--json")
    data = json.loads(out)
    assert code == 0 and data["summary"]["bad"] == 1 and data["summary"]["caught_by_canary"] == 1 and data["summary"]["false_alarms"] == 0


def test_measure_refuses_an_unknown_corpus_skill_and_a_folder_beside_it(skill_folder, monkeypatch, capsys):
    corpus_model(monkeypatch)
    code, _, err = run_cli(capsys, "canary", "--measure", "--only", "no-such-skill")
    assert code == 2 and "no-such-skill" in err and "invoice-summary" in err
    code, _, err = run_cli(capsys, "canary", str(skill_folder), "--measure")
    assert code == 2 and "--measure" in err


def test_measure_with_a_model_that_cannot_answer_exits_2(monkeypatch, capsys):
    def dead(*a):
        raise ProviderError("quota")

    use(monkeypatch, dead)
    code, out, _ = run_cli(capsys, "canary", "--measure", "--only", "invoice-summary", "--scenarios", "3")
    assert code == 2 and "could not be run" in out


def test_a_model_that_cannot_answer_is_one_error_line_and_exit_2(skill_folder, monkeypatch, capsys):
    def dead(*a):
        raise ProviderError("the key was rejected")

    use(monkeypatch, dead)
    code, out, err = run_cli(capsys, "canary", str(skill_folder))
    assert code == 2 and "error: " in err and "key was rejected" in err and out == ""
