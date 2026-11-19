"""The Task Plan (step C1): read-only planning. Offline: a mock model, synthetic repositories, no network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skillforge import cli
from skillforge.conductor import PlanError, make_plan, render_markdown
from skillforge.conductor import intake, process, rules, sizing, tokens
from skillforge.conductor.mentions import find_mentions
from skillforge.conductor.models import (
    AssumptionMade, GapAsked, NewFile, Quoted, Reach, RuleRef, RuleSelection, StatedItem, TaskReading,
)
from skillforge.graph.build import build_graph
from skillforge.providers import MockProvider

ROOT_CLAUDE = Path(__file__).resolve().parents[2] / "CLAUDE.md"


def reading(**kw) -> TaskReading:
    base = dict(
        task_type="feature", summary="Add a rounding rule to the charge.", stated=[], constraints=[], out_of_scope=[],
        declared_risks=[], named_targets=[], gaps=[], assumptions=[], files_to_create=[],
    )
    return TaskReading(**{**base, **kw})


def q(text: str, quote: str) -> Quoted:
    return Quoted(text=text, quote=quote)


def files_of(path: Path) -> set[str]:
    return {p.relative_to(path).as_posix() for p in path.rglob("*") if p.is_file()}


SMALL = {
    "src/util.py": "def parse_config(path):\n    return open(path).read()\n\n\ndef helper():\n    return 1\n",
    "src/app.py": "from src.util import parse_config\n\n\ndef main():\n    return parse_config('x')\n",
    "tests/test_util.py": "from src.util import parse_config\n\n\ndef test_parse_config():\n    assert parse_config('x')\n",
    "CLAUDE.md": "# Rules\n\n- Never commit secrets.\n- Keep functions small.\n- No new dependency without approval.\n",
}


@pytest.fixture
def small(repo):
    return repo(SMALL)


def fan_out(repo, n: int, with_test: bool = False) -> Path:
    files = {"core/engine.py": "def shared():\n    return 1\n"}
    for i in range(n):
        files[f"mods/m{i}.py"] = f"from core.engine import shared\n\n\ndef f{i}():\n    return shared()\n"
    if with_test:
        files["tests/test_engine.py"] = "from core.engine import shared\n\n\ndef test_shared():\n    assert shared() == 1\n"
    return repo(files)


# ---- rules: found by parsing, each with a file and line ----------------------------------------------------


def test_every_top_level_item_is_a_rule_with_its_file_and_line():
    text = "# Rules\n\n- First rule.\n- Second rule\n  wraps here\n  - and a nested point\n1. Numbered rule\n\nProse is not a rule.\n\n- After prose\n"
    found = rules.parse_rules(text, "CLAUDE.md")
    assert [(r.line, r.heading) for r in found] == [(3, "Rules"), (4, "Rules"), (7, "Rules"), (11, "Rules")]
    assert found[1].text == "Second rule wraps here - and a nested point"
    assert all(r.source == "CLAUDE.md" for r in found)


def test_code_blocks_are_not_rules_and_headings_are_tracked():
    text = "## Commands\n\n```bash\n- not a rule\n- nor this\n```\n\n## Rules for working here\n\n- A real rule.\n"
    found = rules.parse_rules(text, "x.md")
    assert [r.text for r in found] == ["A real rule."]
    assert found[0].heading == "Rules for working here"


def test_rule_ids_run_across_all_rule_files(repo):
    root = repo({"CLAUDE.md": "- One.\n- Two.\n", "AGENTS.md": "- Three.\n", "src/a.py": "x = 1\n"})
    found, used = rules.load_rules(root)
    assert used == ["CLAUDE.md", "AGENTS.md"]
    assert [(r.id, r.source, r.text) for r in found] == [("R1", "CLAUDE.md", "One."), ("R2", "CLAUDE.md", "Two."), ("R3", "AGENTS.md", "Three.")]


def test_a_repository_without_rule_files_has_no_rules(repo):
    assert rules.load_rules(repo({"a.py": "x = 1\n"})) == ([], [])


def test_this_repositorys_own_claude_md_is_read_with_real_line_numbers():
    found = rules.parse_rules(ROOT_CLAUDE.read_text(encoding="utf-8"), "CLAUDE.md")
    assert len(found) >= 8
    lines = ROOT_CLAUDE.read_text(encoding="utf-8").splitlines()
    for r in found:
        assert r.text.split()[0].strip("*") in lines[r.line - 1], r  # the line number points at the rule


def test_the_model_can_only_choose_rules_that_exist():
    found = [rules.Rule(id=f"R{i}", source="CLAUDE.md", line=i, heading="", text=f"rule {i}") for i in range(1, 4)]
    mock = MockProvider([RuleSelection(applicable=[RuleRef(id="R2", why="touches it"), RuleRef(id="R9", why="invented"), RuleRef(id="R2", why="again")])])
    chosen, notes, calls = rules.select_rules(mock, "Change rule two in the code.", found)
    assert [(r.id, why) for r, why in chosen] == [("R2", "touches it")]
    assert any("R9" in n and "does not exist" in n for n in notes) and calls == 1


def test_rules_from_the_prompt_say_where_they_came_from_and_that_nothing_enforces_them():
    items = [StatedItem(text="do not change the public API", quote="do not change the public API")]
    r = rules.from_prompt(items)[0]
    assert (r.id, r.source, r.quote) == ("P1", "your prompt", "do not change the public API") and "not enforced" in r.enforcement


# ---- mentions: what the prompt names, found in the graph ---------------------------------------------------


def test_plain_words_are_never_mistaken_for_code(repo):
    g = build_graph(repo({"src/tools.py": "def build():\n    return 1\n\n\ndef report():\n    return 2\n"}), use_cache=False, with_history=False)
    assert find_mentions(g, "Please build a report for the team.") == []
    assert [m.text for m in find_mentions(g, "Change `build` and report() please.")] == ["build", "report()"]


def test_code_shaped_names_paths_and_classes_are_found(repo):
    g = build_graph(repo({"src/util.py": "class TaskPlanner:\n    pass\n\n\ndef parse_config():\n    return 1\n"}), use_cache=False, with_history=False)
    found = {m.text: m for m in find_mentions(g, "Update parse_config and TaskPlanner in src/util.py")}
    assert set(found) == {"parse_config", "TaskPlanner", "src/util.py"}
    assert found["parse_config"].line == 5 and found["src/util.py"].kind == "file" and found["TaskPlanner"].kind == "symbol"


def test_a_path_at_the_end_of_a_sentence_still_matches(repo):
    g = build_graph(repo({"src/util.py": "def a_b():\n    return 1\n"}), use_cache=False, with_history=False)
    for text in ("Please edit src/util.py.", "Edit (src/util.py), then stop", "Is it src/util.py?", "Edit src/util.py, please"):
        assert [m.text for m in find_mentions(g, text)] == ["src/util.py"], text


def test_one_file_named_two_ways_is_one_mention(repo):
    g = build_graph(repo({"backend/pkg/util.py": "def a_b():\n    return 1\n"}), use_cache=False, with_history=False)
    found = find_mentions(g, "Look at pkg/util.py and util.py again")
    assert [m.target for m in found] == ["backend/pkg/util.py"]


def test_a_name_that_matches_two_places_is_ambiguous_and_is_not_measured(repo):
    g = build_graph(repo({"a.py": "def handle_event():\n    return 1\n", "b.py": "def handle_event():\n    return 2\n"}), use_cache=False, with_history=False)
    (m,) = find_mentions(g, "Fix handle_event")
    assert m.ambiguous and m.candidates == 2 and m.target == "" and m.file == ""


def test_a_name_in_source_and_in_a_test_means_the_source(repo):
    g = build_graph(repo({"src/a.py": "def load_data():\n    return 1\n", "tests/test_a.py": "def load_data():\n    return 2\n"}), use_cache=False, with_history=False)
    (m,) = find_mentions(g, "Fix load_data")
    assert not m.ambiguous and m.file == "src/a.py"


def test_a_name_the_model_claims_counts_only_if_it_is_really_in_the_graph(repo):
    g = build_graph(repo(SMALL), use_cache=False, with_history=False)
    found = find_mentions(g, "", extra=["parse_config", "invented_function"], source="model")
    assert [(m.text, m.source) for m in found] == [("parse_config", "model")]


# ---- size: the tier comes from measured facts, highest signal wins -----------------------------------------


@pytest.mark.parametrize("kind, expected", [("docs", 0), ("bugfix", 1), ("investigation", 1), ("feature", 2), ("refactor", 2), ("migration", 3), ("other", 2)])
def test_each_kind_of_task_has_a_starting_tier(kind, expected):
    d = sizing.decide_tier(kind, [], [], [])
    assert d.tier == expected and d.baseline == expected


def test_code_work_with_nothing_measured_says_so():
    d = sizing.decide_tier("bugfix", [], [], [])
    assert not d.measured and "Name the files or functions" in d.note
    assert sizing.decide_tier("docs", [], [], []).note == ""


def test_a_wide_change_raises_the_tier_by_the_number_of_files_it_reaches():
    reach = lambda n: [Reach(target="x", files_reached=[f"m{i}.py" for i in range(n)], tests_tied=["t.py"], risk="low", possible=0)]  # noqa: E731
    assert sizing.decide_tier("bugfix", reach(2), ["x.py"], []).tier == 1
    assert sizing.decide_tier("bugfix", reach(6), ["x.py"], []).tier == 2
    wide = sizing.decide_tier("bugfix", reach(25), ["x.py"], [])
    assert wide.tier == 3 and any("reaches 26 files" in s.evidence for s in wide.signals)


def test_only_a_high_risk_rating_raises_the_tier_not_a_medium_one():
    base = Reach(target="x", files_reached=["a.py"], tests_tied=[], risk="medium", possible=0)
    assert sizing.decide_tier("bugfix", [base], ["x.py"], []).tier == 1
    assert sizing.decide_tier("bugfix", [base.model_copy(update={"risk": "high"})], ["x.py"], []).tier == 3


@pytest.mark.parametrize("path, sensitive", [
    ("src/auth/login.py", True), ("app/billing/invoice.py", True), ("db/migrations/001.sql", True), (".env.local", True),
    (".github/workflows/ci.yml", True), ("src/tokens.py", False), ("src/oauth_client.py", True), ("docs/readme.md", False),
])
def test_sensitive_paths_are_recognised_by_whole_words_not_by_substrings(path, sensitive):
    assert (sizing.sensitive_reason(path) is not None) is sensitive


def test_touching_sensitive_code_or_naming_a_risk_makes_it_tier_3_and_says_why():
    d = sizing.decide_tier("bugfix", [], ["src/auth/login.py"], [])
    assert d.tier == 3 and any("src/auth/login.py has 'auth' in its path" in s.evidence for s in d.signals)
    d = sizing.decide_tier("bugfix", [], [], [StatedItem(text="runs in production", quote="this runs in production")])
    assert d.tier == 3 and any('you said: "this runs in production"' in s.evidence for s in d.signals)


def test_a_custom_sensitive_pattern_counts():
    assert sizing.decide_tier("docs", [], ["src/ledger/post.py"], [], sensitive=["src/ledger/*"]).tier == 3


def test_a_person_can_raise_the_tier_but_lowering_needs_an_explicit_confirmation():
    assert sizing.decide_tier("docs", [], [], [], override=2).tier == 2
    kept = sizing.decide_tier("migration", [], [], [], override=1)
    assert kept.tier == 3 and "Lowering needs an explicit confirmation" in kept.note
    lowered = sizing.decide_tier("migration", [], [], [], override=1, allow_lower=True)
    assert lowered.tier == 1 and "You lowered the tier from 3 to 1" in lowered.note


# ---- the process ---------------------------------------------------------------------------------------------


def test_each_tier_has_more_process_than_the_one_below():
    ids = {t: [p.id for p in process.phases_for(t)] for t in range(4)}
    assert ids[0] == ["intake", "change", "verify", "report"]
    assert ids[1][:2] == ["intake", "reproduce"] and "test" in ids[1]
    assert {"requirements", "design", "tasks", "implement", "test", "review"} <= set(ids[2])
    assert {"risk", "decision", "security"} <= set(ids[3]) and set(ids[2]) < set(ids[3])
    assert all(len(set(v)) == len(v) for v in ids.values())


def test_a_person_approves_the_plan_first_and_every_phase_of_a_tier_3_task():
    assert process.phases_for(0)[0].approval and not any(p.approval for p in process.phases_for(0)[1:])
    assert all(p.approval for p in process.phases_for(3))
    assert [p.title for p in process.phases_for(2) if p.approval] == ["Plan", "Design", "Review"]


def test_stop_triggers_grow_with_the_tier():
    assert len(process.stop_triggers_for(0)) < len(process.stop_triggers_for(1)) < len(process.stop_triggers_for(3))
    assert any("blocking" in s for s in process.stop_triggers_for(0)) and any("broken" in s for s in process.stop_triggers_for(0))


# ---- tokens: what to read, cheapest first, within a budget --------------------------------------------------


def test_a_token_is_about_four_characters_and_nothing_costs_nothing():
    assert tokens.estimate_tokens("") == 0 and tokens.estimate_tokens("abcd") == 1 and tokens.estimate_tokens("abcde") == 2


def plan_for(root, text, tier=2, budget=None, new_files=()):
    g = build_graph(root, use_cache=False, with_history=False)
    mentions = find_mentions(g, text)
    from skillforge.conductor.plan import _reach

    return tokens.plan_tokens(g, root, mentions, _reach(g, mentions), ["CLAUDE.md"] if (root / "CLAUDE.md").exists() else [], list(new_files), tier, budget, prompt=text)


def test_a_named_function_is_read_as_its_own_lines_not_as_the_whole_file(small):
    plan, _ = plan_for(small, "Change parse_config please")
    first = [r for r in plan.reads if r.symbol == "parse_config"][0]
    assert first.kind == "slice" and first.lines == "1-2" and first.tokens < first.whole_file_tokens
    assert plan.whole_files_total > plan.read_total


def test_the_reading_order_is_rules_then_the_named_code_then_its_neighbours_then_tests(small):
    plan, _ = plan_for(small, "Change parse_config please")
    assert plan.reads[0].path == "CLAUDE.md" and plan.reads[0].priority == 0
    assert [r.priority for r in plan.reads] == sorted(r.priority for r in plan.reads)
    why = " ".join(r.why for r in plan.reads)
    assert "main is called" not in why and "main calls it" in why  # a caller of the named function
    assert any("test_parse_config" in r.symbol for r in plan.reads)  # the test that calls it


def test_a_whole_file_that_is_read_already_holds_its_functions(small):
    plan, notes = plan_for(small, "Change parse_config in src/util.py")
    assert not [r for r in plan.reads if r.symbol == "parse_config"]
    assert any(r.kind == "file" and r.path == "src/util.py" for r in plan.reads)


def test_what_does_not_fit_the_budget_is_left_out_lowest_priority_first_and_listed(small):
    plan, notes = plan_for(small, "Change parse_config please", budget=60)
    assert plan.dropped and not plan.fits_budget
    assert max(r.priority for r in plan.reads) <= min(r.priority for r in plan.dropped) or plan.reads[0].priority == 0
    assert any("do not fit" in n for n in notes)


def test_the_rule_files_are_always_read_even_when_they_alone_exceed_the_budget(small):
    plan, notes = plan_for(small, "Change parse_config please", budget=1)
    assert plan.reads[0].path == "CLAUDE.md" and any("rule files alone cost" in n for n in notes)


def test_words_are_split_from_snake_case_camel_case_and_paths_and_filler_is_ignored():
    assert tokens.words_of("export_library in src/ExportLibrary.py, and the Library") == {"export", "library", "src"}
    assert tokens.relevance({"library", "export"}, "tests/test_library.py") == 1
    assert tokens.relevance({"library"}, "tests/test_scripts.py") == 0


def test_a_widely_imported_file_plans_only_the_few_most_relevant_tests_and_says_what_it_left_out(repo):
    files = {"core/engine.py": "def shared():\n    return 1\n"}
    for name in ("alpha", "beta", "engine", "gamma", "delta"):
        files[f"tests/test_{name}.py"] = f"from core.engine import shared\n\n\ndef test_{name}():\n    assert shared() == 1\n"
    root = repo(files)
    plan, notes = plan_for(root, "Make the engine in core/engine.py return two values")
    planned = [r.path for r in plan.reads if r.path.startswith("tests/")]
    assert len(planned) == tokens.MAX_TESTS and "tests/test_engine.py" in planned  # the one whose name matches "engine" is kept
    assert len(plan.dropped) == 2 and all("only the 3 most relevant of 5" in d.why for d in plan.dropped)
    assert plan.fits_budget  # leaving tests out for relevance is not a budget problem
    assert not any("do not fit" in n for n in notes)


def test_a_big_file_named_whole_gets_a_hint_to_name_the_function_that_matches_the_words(repo):
    body = "    total = 0\n" + "    total += len('x' * 40)\n" * 160
    root = repo({"cli.py": f"def export_library():\n{body}    return total\n\n\ndef unrelated_thing():\n{body}    return total\n"})
    plan, notes = plan_for(root, "Add a json option to the library export in cli.py")
    hint = [n for n in notes if n.startswith("`cli.py` costs")]
    assert len(hint) == 1 and "`export_library`" in hint[0] and "unrelated_thing" not in hint[0] and "not a measurement" in hint[0]


def test_a_small_file_gets_no_hint(repo):
    plan, notes = plan_for(repo({"cli.py": "def export_library():\n    return 1\n"}), "Add a json option to the library export in cli.py")
    assert not any("costs" in n for n in notes)


def test_files_to_create_are_costed_by_size_and_a_plan_without_a_repository_says_so():
    plan, notes = tokens.plan_tokens(None, None, [], [], [], [("docs/a.md", "notes", "small"), ("src/b.py", "code", "large")], 1)
    assert [c.tokens for c in plan.create] == [400, 3000] and plan.create_total == 3400
    assert plan.reads == [] and any("No repository" in n for n in notes)


# ---- intake: the model reads, code verifies ------------------------------------------------------------------


WORDS = "Add a rounding rule to src/billing/charge.py. Do not change the public API. This runs in production."


def test_only_what_the_persons_own_words_support_is_kept():
    raw = reading(
        stated=[q("add a rounding rule", "Add a rounding rule"), q("invented goal", "make it faster")],
        constraints=[q("keep the API", "Do not change the public API")],
        declared_risks=[q("production", "This runs in production"), q("also risky", "it handles payments")],
        named_targets=["src/billing/charge.py", "made_up_module"],
    )
    got, notes, targets = intake.verify_reading(raw, WORDS)
    assert [s.quote for s in got.stated] == ["Add a rounding rule"] and len(got.constraints) == 1 and len(got.declared_risks) == 1
    assert targets == ["src/billing/charge.py"]
    assert sum("dropped because its quote is not in your words" in n for n in notes) == 2
    assert any('"made_up_module" was dropped because you did not write it' in n for n in notes)


def test_questions_are_deduplicated_capped_and_marked_as_the_models():
    many = [GapAsked(question=f"Question {i}?", why="because", blocking=i == 0) for i in range(12)] + [GapAsked(question="question 0?", why="again", blocking=False)]
    got, notes, _ = intake.verify_reading(reading(gaps=many, assumptions=[AssumptionMade(text=f"a{i}", why="w") for i in range(9)]), WORDS)
    assert len(got.gaps) == intake.MAX_GAPS and got.gaps[0].blocking and all(g.source == "model" for g in got.gaps)
    assert len(got.assumptions) == intake.MAX_ASSUMPTIONS and any("only the first 8" in n for n in notes)


def test_the_graph_raises_its_own_questions(repo):
    g = build_graph(repo({"a.py": "def handle_event():\n    return 1\n", "b.py": "def handle_event():\n    return 2\n"}), use_cache=False, with_history=False)
    asked = intake.code_gaps(find_mentions(g, "Fix handle_event"), "bugfix", True, measured=False)
    assert len(asked) == 1 and asked[0].blocking and asked[0].source == "code" and "matches 2 places" in asked[0].question
    none = intake.code_gaps([], "feature", True, measured=False)
    assert len(none) == 1 and not none[0].blocking and "Which files or functions" in none[0].question
    assert intake.code_gaps([], "docs", True, measured=False) == [] and intake.code_gaps([], "feature", False, measured=False) == []


@pytest.mark.parametrize("path, ok", [
    ("docs/notes.md", True), ("a.py", True), ("../x.py", False), ("/etc/x", False), ("C:/x.py", False), ("a/../b.py", False),
    ("a//b.py", False), ("", False), ("x" * 130, False),
])
def test_a_file_to_create_must_be_a_plain_relative_path(path, ok):
    assert intake.safe_new_path(path) is ok


def test_the_model_sees_names_and_counts_never_file_contents(repo):
    g = build_graph(repo(SMALL), use_cache=False, with_history=False)
    facts = json.loads(intake.facts_for_model(find_mentions(g, "Change parse_config"), {"python": 3}, 4))
    assert facts["named_in_the_request"][0]["file"] == "src/util.py" and facts["files"] == 4
    assert "open(path)" not in json.dumps(facts)


# ---- the whole plan -------------------------------------------------------------------------------------------


def model_for(repo_root, **kw):
    r = reading(
        task_type="bugfix", summary="Fix how parse_config reads a path.",
        stated=[q("fix parse_config", "Fix parse_config")], constraints=[q("do not change the API", "Do not change the public API")],
        named_targets=["parse_config"], gaps=[GapAsked(question="Which file formats must it read?", why="The fix depends on it.", blocking=True)],
        assumptions=[AssumptionMade(text="UTF-8 files", why="Nothing says otherwise.")],
        files_to_create=[NewFile(path="docs/notes.md", purpose="what changed", size="small"), NewFile(path="../escape.md", purpose="bad", size="small")],
    )
    return MockProvider([r.model_copy(update=kw) if kw else r, RuleSelection(applicable=[RuleRef(id="R3", why="a dependency would be a change"), RuleRef(id="R99", why="invented")])])


PROMPT = "Fix parse_config in src/util.py. Do not change the public API."


def test_a_plan_with_a_model_has_every_section_and_every_claim_is_checked(small):
    mock = model_for(small)
    plan = make_plan(PROMPT, provider=mock, repo=small)
    assert plan.mode == "model" and plan.model == "mock/mock-1" and plan.model_calls == 2
    assert plan.reading.task_type == "bugfix" and [s.quote for s in plan.reading.stated] == ["Fix parse_config"]
    assert plan.reading.gaps[0].blocking and plan.reading.gaps[0].question == "Which file formats must it read?"
    assert plan.reading.assumptions[0].text == "UTF-8 files"
    assert {m.text for m in plan.mentions} == {"parse_config", "src/util.py"}
    assert plan.tier.tier == 1 and plan.tier.measured
    assert [r.id for r in plan.rules] == ["R3", "P1"]
    assert (plan.rules[0].source, plan.rules[0].line, plan.rules[0].text) == ("CLAUDE.md", 5, "No new dependency without approval.")
    assert plan.rules_found == 3 and all("not enforced" in r.enforcement for r in plan.rules)
    assert [c.path for c in plan.token_plan.create] == ["docs/notes.md"]
    assert any("../escape.md" in n and "not a plain relative path" in n for n in plan.notes)
    assert any("R99" in n for n in plan.notes)
    assert any("Nothing was run" in n for n in plan.not_checked)


def test_the_model_never_sees_the_contents_of_a_file(repo):
    root = repo({
        "src/secret_logic.py": "def compute_discount(price):\n    SECRET_BODY_MARKER = 'internal formula 42'\n    return price * 0.9\n",
        "CLAUDE.md": "- Never log customer names.\n",
    })
    mock = MockProvider([reading(named_targets=["compute_discount"]), RuleSelection(applicable=[])])
    make_plan("Change compute_discount in src/secret_logic.py to round up.", provider=mock, repo=root)
    sent = "\n".join(c["prompt"] for c in mock.calls)
    assert "SECRET_BODY_MARKER" not in sent and "internal formula 42" not in sent and "price * 0.9" not in sent
    assert "compute_discount" in sent and "src/secret_logic.py" in sent  # names and places, as promised
    assert "Never log customer names." in sent  # the rule lines, as promised


def test_a_plan_changes_nothing_in_the_repository(small):
    before = {p: (small / p).read_bytes() for p in files_of(small)}
    make_plan(PROMPT, provider=model_for(small), repo=small)
    make_plan(PROMPT, repo=small, task_type="bugfix")
    assert files_of(small) == set(before) and all((small / p).read_bytes() == b for p, b in before.items())


def test_without_a_model_nothing_is_read_or_sent_and_the_plan_says_so(small):
    plan = make_plan(PROMPT, repo=small, task_type="bugfix")
    assert plan.mode == "facts only" and plan.model == "" and plan.model_calls == 0
    assert plan.reading.stated == [] and plan.tier.tier == 1
    assert len(plan.rules) == 3 and all("not filtered" in r.why for r in plan.rules)
    assert any("No model was used" in n for n in plan.not_checked)
    text = render_markdown(plan)
    assert "**Not read.**" in text and "Run again without `--no-ai`" in text and "## 2. What it does NOT say" not in text


def test_a_wide_and_untested_change_becomes_tier_3_because_of_what_the_graph_found(repo):
    root = fan_out(repo, 12)
    plan = make_plan("Change shared in core/engine.py to return two values.", repo=root, task_type="feature")
    assert plan.tier.tier == 3
    assert any(s.name == "risk of the named code" and "high" in s.evidence for s in plan.tier.signals)
    assert len(plan.reach[0].files_reached) == 12 and plan.reach[0].tests_tied == []
    assert all(p.approval for p in plan.phases) and {"risk", "decision", "security"} <= {p.id for p in plan.phases}


def test_a_narrow_change_to_tested_code_stays_small(repo):
    root = fan_out(repo, 2, with_test=True)
    plan = make_plan("Fix shared in core/engine.py", repo=root, task_type="bugfix")
    assert plan.tier.tier == 1 and plan.reach[0].tests_tied == ["tests/test_engine.py"]


def test_an_ambiguous_name_becomes_a_blocking_question_and_is_not_measured(repo):
    root = repo({"a.py": "def handle_event():\n    return 1\n", "b.py": "def handle_event():\n    return 2\n"})
    plan = make_plan("Fix handle_event so it retries.", repo=root, task_type="bugfix")
    assert not plan.tier.measured and plan.reach == []
    assert plan.reading.gaps[0].blocking and plan.reading.gaps[0].source == "code"
    assert any(m.ambiguous for m in plan.mentions)


def test_the_tier_can_be_raised_and_lowering_it_is_recorded(small):
    assert make_plan(PROMPT, repo=small, task_type="bugfix", tier=3).tier.tier == 3
    kept = make_plan(PROMPT, repo=small, task_type="migration", tier=1)
    assert kept.tier.tier == 3 and "explicit confirmation" in kept.tier.note
    assert make_plan(PROMPT, repo=small, task_type="migration", tier=1, allow_lower=True).tier.tier == 1


def test_the_budget_can_be_set_and_a_plan_with_no_repository_still_works():
    plan = make_plan("Write a short guide to our release process for new people.", task_type="docs", budget=5000)
    assert plan.repo == "" and plan.token_plan.budget == 5000 and plan.tier.tier == 0
    assert any("No repository was given" in n for n in plan.not_checked)


def test_bad_input_is_a_plain_error(small, tmp_path):
    with pytest.raises(PlanError, match="at least a sentence"):
        make_plan("fix it", repo=small)
    with pytest.raises(PlanError, match="0, 1, 2 or 3"):
        make_plan(PROMPT, repo=small, tier=7)
    with pytest.raises(NotADirectoryError):
        make_plan(PROMPT, repo=tmp_path / "nope")


def test_the_written_plan_shows_what_it_contains_what_it_does_not_and_what_was_not_checked(small):
    text = render_markdown(make_plan(PROMPT, provider=model_for(small), repo=small))
    for part in (
        "# Task plan", "A plan only.", "## 1. What your request contains", '— "Fix parse_config"', "## 2. What it does NOT say",
        "**[BLOCKING]** Which file formats must it read?", "Assumptions", "UTF-8 files", "## 3. Size and process", "Tier 1: Small fix",
        "It stops and asks when:", "## 4. Rules that apply", "None is enforced yet", "R3", "## 5. Token plan (estimates)", "Read in this order",
        "## What was NOT checked", "no file contents",
    ):
        assert part in text, part


def test_a_plan_round_trips_through_json(small):
    plan = make_plan(PROMPT, provider=model_for(small), repo=small)
    again = type(plan).model_validate(json.loads(json.dumps(plan.model_dump())))
    assert again == plan


# ---- the command line -------------------------------------------------------------------------------------------


def test_the_command_prints_a_plan_without_a_model(small, capsys):
    assert cli.main(["plan", PROMPT, "--repo", str(small), "--no-ai", "--type", "bugfix"]) == 0
    captured = capsys.readouterr()
    assert "# Task plan" in captured.out and "Tier 1: Small fix" in captured.out and captured.err == ""  # nothing is sent: no notice either


def test_the_command_can_print_json_and_save_a_file(small, tmp_path, capsys):
    out = tmp_path / "plan.json"
    assert cli.main(["plan", PROMPT, "--repo", str(small), "--no-ai", "--type", "docs", "--json", "--save", str(out)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["mode"] == "facts only" and json.loads(out.read_text(encoding="utf-8")) == printed


def test_with_a_model_the_command_first_says_exactly_what_is_sent(small, monkeypatch, capsys):
    monkeypatch.setattr(cli, "provider_from_env", lambda: model_for(small))
    assert cli.main(["plan", PROMPT, "--repo", str(small)]) == 0
    captured = capsys.readouterr()
    assert "Sent to the model" in captured.err and "not the contents" in captured.err and "--no-ai" in captured.err
    assert "**[BLOCKING]**" in captured.out


def test_no_ai_never_asks_for_a_provider(small, monkeypatch, capsys):
    def boom():
        raise AssertionError("a provider was requested")

    monkeypatch.setattr(cli, "provider_from_env", boom)
    assert cli.main(["plan", PROMPT, "--repo", str(small), "--no-ai", "--type", "bugfix"]) == 0


def test_the_command_reads_the_task_from_a_file_and_refuses_a_bad_call(small, tmp_path, capsys):
    task = tmp_path / "task.txt"
    task.write_text(PROMPT, encoding="utf-8")
    assert cli.main(["plan", "--file", str(task), "--repo", str(small), "--no-ai", "--type", "bugfix"]) == 0
    capsys.readouterr()
    assert cli.main(["plan", "--no-ai"]) == 2 and "Give the task" in capsys.readouterr().err
    assert cli.main(["plan", PROMPT, "--file", str(task), "--no-ai"]) == 2 and "not both" in capsys.readouterr().err
    assert cli.main(["plan", "fix it", "--no-ai"]) == 2 and "at least a sentence" in capsys.readouterr().err
    assert cli.main(["plan", PROMPT, "--repo", str(tmp_path / "missing"), "--no-ai"]) == 2
