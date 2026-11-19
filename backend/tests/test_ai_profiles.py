"""Model profiles per tier, read from an environment mapping. Never the real environment, never a real key."""

from __future__ import annotations

import pytest

from skillforge.ai.profiles import load_profiles
from skillforge.ai.tasks import Tier
from skillforge.providers import ProviderError

GEMINI = {"LLM_PROVIDER": "gemini", "LLM_MODEL": "m-default", "GOOGLE_API_KEY": "key-one"}


def test_no_overrides_means_one_default_for_every_tier():
    ps = load_profiles(GEMINI)
    assert (ps.default.provider.name, ps.default.provider.model) == ("gemini", "m-default")
    assert all(ps.profile_for(t).provider is ps.default.provider for t in Tier)
    assert ps.escalation is None


def test_a_tier_can_use_another_model_of_the_same_provider():
    ps = load_profiles({**GEMINI, "LLM_CODE_MODEL": "m-code"})
    assert (ps.profile_for(Tier.CODE).provider.name, ps.profile_for(Tier.CODE).provider.model) == ("gemini", "m-code")
    assert ps.profile_for(Tier.FAST).provider is ps.default.provider


def test_a_tier_can_use_another_provider_with_its_own_key():
    ps = load_profiles({**GEMINI, "LLM_ACTOR_PROVIDER": "anthropic", "LLM_ACTOR_MODEL": "m-claude", "ANTHROPIC_API_KEY": "key-two"})
    actor = ps.profile_for(Tier.ACTOR).provider
    assert (actor.name, actor.model, actor.secrets) == ("anthropic", "m-claude", ("key-two",))
    assert ps.default.provider.secrets == ("key-one",)


def test_another_provider_without_a_model_fails_naming_the_variable():
    with pytest.raises(ProviderError, match="LLM_CODE_MODEL is empty"):
        load_profiles({**GEMINI, "LLM_CODE_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "k"})


def test_a_missing_key_for_an_override_fails_naming_the_key_and_the_tier():
    with pytest.raises(ProviderError, match=r"(?s)code.*ANTHROPIC_API_KEY is empty"):
        load_profiles({**GEMINI, "LLM_CODE_PROVIDER": "anthropic", "LLM_CODE_MODEL": "m"})


def test_a_bad_number_fails_naming_the_variable():
    for name in ("LLM_TIMEOUT_S", "LLM_FAST_TIMEOUT_S", "LLM_DESIGN_MAX_OUTPUT_TOKENS", "LLM_MAX_INPUT_TOKENS"):
        for bad in ("abc", "0", "-5"):
            with pytest.raises(ProviderError, match=name):
                load_profiles({**GEMINI, name: bad})


def test_timeouts_default_to_90_and_180_for_code_and_can_be_set():
    ps = load_profiles(GEMINI)
    assert [ps.profile_for(t).options.timeout_s for t in (Tier.FAST, Tier.DESIGN, Tier.ACTOR, Tier.CODE)] == [90.0, 90.0, 90.0, 180.0]
    assert ps.default.options.timeout_s == 90.0
    every = load_profiles({**GEMINI, "LLM_TIMEOUT_S": "30"})  # an explicit global value applies to every tier, code included
    assert all(every.profile_for(t).options.timeout_s == 30.0 for t in Tier)
    own = load_profiles({**GEMINI, "LLM_CODE_TIMEOUT_S": "240"})
    assert own.profile_for(Tier.CODE).options.timeout_s == 240.0 and own.profile_for(Tier.FAST).options.timeout_s == 90.0


def test_output_and_input_limits_are_off_unless_set():
    ps = load_profiles(GEMINI)
    assert ps.profile_for(Tier.CODE).options.max_output_tokens is None and ps.default.max_input_tokens is None
    ps = load_profiles({**GEMINI, "LLM_CODE_MAX_OUTPUT_TOKENS": "4000", "LLM_MAX_INPUT_TOKENS": "50000"})
    assert ps.profile_for(Tier.CODE).options.max_output_tokens == 4000 and ps.profile_for(Tier.FAST).options.max_output_tokens is None
    assert all(ps.profile_for(t).max_input_tokens == 50000 for t in Tier)


def test_an_escalation_profile_exists_only_when_set():
    ps = load_profiles({**GEMINI, "LLM_ESCALATION_MODEL": "m-big"})
    assert ps.escalation is not None and (ps.escalation.provider.name, ps.escalation.provider.model) == ("gemini", "m-big")
    assert ps.escalation.tier == "escalation"


def test_every_secret_is_listed_for_redaction():
    ps = load_profiles({**GEMINI, "LLM_ESCALATION_PROVIDER": "anthropic", "LLM_ESCALATION_MODEL": "m", "ANTHROPIC_API_KEY": "key-two"})
    assert set(ps.secrets()) == {"key-one", "key-two"}


def test_default_errors_are_the_ones_provider_from_env_gives():
    with pytest.raises(ProviderError, match="LLM_PROVIDER is ''"):
        load_profiles({})
    with pytest.raises(ProviderError, match="GOOGLE_API_KEY is empty"):
        load_profiles({"LLM_PROVIDER": "gemini", "LLM_MODEL": "m"})
