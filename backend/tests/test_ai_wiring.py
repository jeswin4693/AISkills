"""Every model call in the program names its task, and the entry points build the AI service from the environment."""

from __future__ import annotations

import json

import pytest

from skillforge import cli
from skillforge.ai import AIService, Profile, ProfileSet, Tier
from skillforge.ai.service import service_from_env
from skillforge.build import architect, scripts
from skillforge.build.models import RequirementSpec
from skillforge.build.requirements import extract_spec
from skillforge.builder.provider import env_provider, provider_status
from skillforge.conductor import intake, rules
from skillforge.conductor.models import Rule
from skillforge.evaluate import runner
from skillforge.providers import CallOptions, MockProvider, ProviderError
from skillforge.suggest import pipeline as suggest_pipeline

GEMINI = {"LLM_PROVIDER": "gemini", "LLM_MODEL": "m-default", "GOOGLE_API_KEY": "key-one-1234567890"}


class Spy:
    """Records that it was called, then fails for good, so no valid model answer has to be invented."""

    def __init__(self, name):
        self.name, self.model, self.calls = name, f"{name}-model", 0

    def generate_structured(self, schema, prompt, *, system=None):
        self.calls += 1
        raise ProviderError("stop", kind="bad_request")


class Rows:
    def __init__(self):
        self.rows = []

    def record(self, rec):
        self.rows.append(rec)


def spied_service():
    rows = Rows()
    tiers = {t: Profile(t.value, Spy(t.value), CallOptions()) for t in Tier}
    return AIService(ProfileSet(Profile("default", Spy("default"), CallOptions()), tiers), recorder=rows, sleep=lambda s: None), rows


SPEC = RequirementSpec(goal="count the TODO comments in a folder")
RULE = Rule(id="R1", source="CLAUDE.md", line=1, heading="h", text="never print keys")

CASES = [
    ("requirements", lambda s: extract_spec(s, "a skill that counts todos"), "extract", "fast"),
    ("task intake", lambda s: intake.read_task(s, "fix the login bug", None), "extract", "fast"),
    ("rule selection", lambda s: rules.select_rules(s, "fix the login bug", [RULE]), "select", "fast"),
    ("skill design", lambda s: architect.design(s, SPEC), "design", "design"),
    ("suggest", lambda s: suggest_pipeline._ask(s, "facts", "system", 2), "suggest", "design"),
    ("helper scripts", lambda s: scripts.design_scripts(s, SPEC), "code", "code"),
    ("eval reply", lambda s: runner._ask(s, "system", "a message"), "act", "actor"),
]


@pytest.mark.parametrize("label, call, task, tier", CASES, ids=[c[0] for c in CASES])
def test_each_feature_asks_for_its_task(label, call, task, tier):
    svc, rows = spied_service()
    with pytest.raises(ProviderError):
        call(svc)
    last = rows.rows[-1]
    assert (last.task, last.tier, last.provider) == (task, tier, tier)


def test_service_from_env_reads_the_call_budget_and_the_tiers():
    svc = service_from_env({**GEMINI, "LLM_MAX_CALLS": "5", "LLM_CODE_MODEL": "m-code"})
    assert isinstance(svc, AIService) and svc.max_calls == 5
    assert (svc.name, svc.model) == ("gemini", "m-default")
    assert svc.profiles.profile_for(Tier.CODE).provider.model == "m-code"
    assert service_from_env(GEMINI).max_calls is None


def test_a_bad_call_budget_names_the_variable():
    with pytest.raises(ProviderError, match="LLM_MAX_CALLS"):
        service_from_env({**GEMINI, "LLM_MAX_CALLS": "many"})


def test_env_provider_and_the_cli_name_return_a_service(monkeypatch):
    for key, value in GEMINI.items():
        monkeypatch.setenv(key, value)
    assert isinstance(env_provider(), AIService)
    assert isinstance(cli.provider_from_env(), AIService)  # the name tests patch is still the one the commands call


def test_provider_status_lists_the_tiers_and_never_a_key():
    status = provider_status(lambda: service_from_env({**GEMINI, "LLM_CODE_MODEL": "m-code", "LLM_ESCALATION_MODEL": "m-big"}))
    assert status["configured"] and (status["provider"], status["model"]) == ("gemini", "m-default")
    assert {t["tier"]: t["model"] for t in status["tiers"]} == {"fast": "m-default", "design": "m-default", "code": "m-code", "actor": "m-default"}
    assert status["escalation"] == {"provider": "gemini", "model": "m-big"}
    assert status["capabilities"]["structured_output"] == "json_schema"
    assert "key-one-1234567890" not in json.dumps(status)


def test_provider_status_for_a_bare_provider_and_for_no_provider():
    bare = provider_status(lambda: MockProvider([]))
    assert bare["configured"] and bare["tiers"] == [] and bare["escalation"] is None

    def missing():
        raise ProviderError("GOOGLE_API_KEY is empty.")

    none = provider_status(missing)
    assert none["configured"] is False and none["tiers"] == [] and "GOOGLE_API_KEY" in none["detail"]
