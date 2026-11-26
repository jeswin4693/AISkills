"""What a person may type for their own model (slice AI): the same safe characters as the Settings page, minus the provider that takes an address.

A refusal names the field and says why; it never repeats the key.
"""

from __future__ import annotations

import pytest

from skillforge.settings import SettingsError
from skillforge.settings.rules import PERSON_PROVIDERS, check_person_model

KEY = "AIzaSyDistinctiveFakeKeyForTests_0123456789"


def problems(provider: str, model: str, key: str) -> dict[str, str]:
    with pytest.raises(SettingsError) as caught:
        check_person_model(provider, model, key)
    return {p["name"]: p["message"] for p in caught.value.problems}


def test_the_providers_a_person_may_choose_leave_out_custom():
    assert "custom" not in PERSON_PROVIDERS
    assert {"gemini", "openai", "groq", "anthropic", "openrouter", "mistral"} <= set(PERSON_PROVIDERS)


def test_a_good_choice_comes_back_cleaned():
    assert check_person_model(" Gemini ", " gemini-3.5-flash-lite ", f" {KEY} \n") == ("gemini", "gemini-3.5-flash-lite", KEY)


def test_custom_is_refused_because_it_sends_the_server_to_an_address_the_person_types():
    message = problems("custom", "m", KEY)["provider"]
    assert "address" in message.lower() and KEY not in message


def test_an_unknown_provider_is_refused_with_the_choices():
    message = problems("skynet", "m", KEY)["provider"]
    assert "gemini" in message and "custom" not in message


@pytest.mark.parametrize("model", ["", "a b", 'a"b', "a\\b", "a\x00b", "a​b", "a\nb", "x" * 129])
def test_a_model_name_with_anything_odd_in_it_is_refused(model):
    assert "model" in problems("gemini", model, KEY)


def test_a_model_name_at_the_limit_is_fine():
    assert check_person_model("gemini", "m" * 128, KEY)[1] == "m" * 128  # the width of model_calls.model: a usage row can always hold it


@pytest.mark.parametrize("quoted", ['"AIzaKEY123"', "'AIzaKEY123'", "`AIzaKEY123`", '"AIzaKEY123'])
def test_a_key_in_quotes_is_refused_and_told_what_to_remove(quoted):
    message = problems("gemini", "m", quoted)["key"]
    assert "quote" in message.lower() and "AIzaKEY123" not in message


@pytest.mark.parametrize("pasted", ["Bearer AIzaKEY123", "bearer   AIzaKEY123", "BEARER"])
def test_a_key_with_the_word_bearer_in_front_is_refused_and_told_what_to_remove(pasted):
    message = problems("gemini", "m", pasted)["key"]
    assert "bearer" in message.lower() and "AIzaKEY123" not in message


@pytest.mark.parametrize("key", ["", "   ", "a" * 401, "AIza key", "AIza\x00key", "AIza​key", "AIza$key", "AIza#key"])
def test_an_empty_too_long_or_unsafe_key_is_refused(key):
    assert "key" in problems("gemini", "m", key)


def test_a_key_with_whitespace_around_it_is_accepted_after_trimming():
    assert check_person_model("openai", "gpt-x", "\t sk-proj-ABC_123-xyz \r\n")[2] == "sk-proj-ABC_123-xyz"


@pytest.mark.parametrize("key", ['"SECRET-VALUE-123"', "Bearer SECRET-VALUE-123", "SECRET VALUE 123", "SECRET\x00VALUE", "S" * 500 + "SECRET-VALUE-123"])
def test_no_refusal_ever_repeats_the_key(key):
    found = problems("gemini", "m", key)
    assert "SECRET" not in " ".join(found.values())


def test_every_problem_is_reported_together():
    assert set(problems("skynet", "a b", "")) == {"provider", "model", "key"}
