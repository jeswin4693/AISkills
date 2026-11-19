from __future__ import annotations

import json

import httpx2
import openai
import pytest
from pydantic import BaseModel

from skillforge.providers import (
    CallOptions, Capabilities, Generation, MockProvider, OpenAICompatibleProvider, ProviderError, Usage, provider_from_env,
)


class Answer(BaseModel):
    word: str
    count: int


# ---- factory -----------------------------------------------------------------------------------------


def test_factory_builds_gemini_and_openai():
    g = provider_from_env({"LLM_PROVIDER": "gemini", "LLM_MODEL": "m1", "GOOGLE_API_KEY": "k"})
    assert (g.name, g.model) == ("gemini", "m1")
    o = provider_from_env({"LLM_PROVIDER": "OpenAI", "LLM_MODEL": "m2", "OPENAI_API_KEY": "k"})
    assert (o.name, o.model) == ("openai", "m2")


def test_factory_presets_use_their_own_address_and_key_variable():
    for name, key_env, host in (
        ("groq", "GROQ_API_KEY", "api.groq.com"),
        ("openrouter", "OPENROUTER_API_KEY", "openrouter.ai"),
        ("mistral", "MISTRAL_API_KEY", "api.mistral.ai"),
    ):
        p = provider_from_env({"LLM_PROVIDER": name, "LLM_MODEL": "m", key_env: "k"})
        assert p.name == name and host in str(p._client.base_url)


def test_factory_custom_provider_needs_an_address_and_a_key():
    base = {"LLM_PROVIDER": "custom", "LLM_MODEL": "m"}
    with pytest.raises(ProviderError, match="LLM_BASE_URL is empty"):
        provider_from_env({**base, "LLM_API_KEY": "k"})
    with pytest.raises(ProviderError, match="LLM_API_KEY is empty"):
        provider_from_env({**base, "LLM_BASE_URL": "https://example.test/v1"})
    p = provider_from_env({**base, "LLM_BASE_URL": "https://example.test/v1", "LLM_API_KEY": "k"})
    assert "example.test" in str(p._client.base_url)


@pytest.mark.parametrize(
    "env, message",
    [
        ({}, "LLM_PROVIDER is ''"),
        ({"LLM_PROVIDER": "nonsense"}, "Supported: custom, gemini, groq, mistral, openai, openrouter"),
        ({"LLM_PROVIDER": "gemini"}, "LLM_MODEL is empty"),
        ({"LLM_PROVIDER": "gemini", "LLM_MODEL": "m"}, "GOOGLE_API_KEY is empty"),
        ({"LLM_PROVIDER": "openai", "LLM_MODEL": "m"}, "OPENAI_API_KEY is empty"),
    ],
)
def test_factory_explains_what_is_missing(env, message):
    with pytest.raises(ProviderError, match=message):
        provider_from_env(env)


# ---- mock provider -----------------------------------------------------------------------------------


def test_mock_provider_returns_validates_raises_and_records():
    mock = MockProvider([Answer(word="a", count=1), {"word": "b", "count": 2}, ProviderError("boom")])
    assert mock.generate_structured(Answer, "p1", system="s").word == "a"
    assert mock.generate_structured(Answer, "p2").count == 2
    with pytest.raises(ProviderError, match="boom"):
        mock.generate_structured(Answer, "p3")
    with pytest.raises(ProviderError, match="no response left"):
        mock.generate_structured(Answer, "p4")
    assert [c["prompt"] for c in mock.calls] == ["p1", "p2", "p3", "p4"]
    assert mock.calls[0]["system"] == "s"


def test_mock_provider_can_compute_its_answer():
    mock = MockProvider(lambda schema, prompt, system: {"word": prompt.upper(), "count": 0})
    assert mock.generate_structured(Answer, "hi").word == "HI"


# ---- the OpenAI-compatible adapter, against a mocked HTTP server -------------------------------------


def completion(content: str) -> dict:
    return {
        "id": "x", "object": "chat.completion", "created": 0, "model": "m",
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def adapter(handler) -> OpenAICompatibleProvider:
    client = openai.OpenAI(
        api_key="k", base_url="https://example.test/v1", max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
    )
    return OpenAICompatibleProvider(name="x", model="m", api_key="k", key_env="MY_KEY", client=client)


def test_adapter_sends_system_prompt_and_schema_and_parses_the_answer():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, json=completion(json.dumps({"word": "ok", "count": 3})))

    result = adapter(handler).generate_structured(Answer, "question", system="rules")
    assert result == Answer(word="ok", count=3)
    messages = seen["body"]["messages"]
    assert [m["role"] for m in messages] == ["system", "user"] and messages[0]["content"] == "rules"
    assert seen["body"]["response_format"]["type"] == "json_schema"
    assert seen["body"]["response_format"]["json_schema"]["name"] == "Answer"


@pytest.mark.parametrize(
    "status, body, message, retryable",
    [
        (401, {"error": {"message": "bad key"}}, "rejected .401.. Check MY_KEY", False),
        (404, {"error": {"message": "model retired"}}, "model retired", False),
        (429, {"error": {"message": "no credits"}}, "no credits", False),
        (503, {"error": {"message": "overloaded"}}, "API error 503", True),
    ],
)
def test_adapter_maps_http_errors_to_actionable_messages(status, body, message, retryable):
    with pytest.raises(ProviderError, match=message) as info:
        adapter(lambda request: httpx2.Response(status, json=body)).generate_structured(Answer, "q")
    assert info.value.retryable is retryable


def test_adapter_treats_malformed_model_output_as_retryable():
    provider = adapter(lambda request: httpx2.Response(200, json=completion('{"word": "x"}')))
    with pytest.raises(ProviderError, match="did not match the schema") as info:
        provider.generate_structured(Answer, "q")
    assert info.value.retryable


def test_adapter_reports_a_refusal():
    body = completion("")
    body["choices"][0]["message"]["refusal"] = "I cannot help with that."
    with pytest.raises(ProviderError, match="refused"):
        adapter(lambda request: httpx2.Response(200, json=body)).generate_structured(Answer, "q")


# ---- the provider contract ---------------------------------------------------------------------------


def test_provider_error_keeps_old_calls_working():
    plain = ProviderError("x")
    assert plain.retryable is False and plain.kind == "other" and plain.retry_after_s is None and plain.detail == ""
    assert ProviderError("x", retryable=True).retryable is True


def test_provider_error_carries_kind_and_wait():
    err = ProviderError("slow down", kind="rate_limit", retry_after_s=7.5, detail="why")
    assert (err.kind, err.retry_after_s, err.detail) == ("rate_limit", 7.5, "why")


def test_generation_defaults():
    g = Generation(1)
    assert g.value == 1 and g.usage == Usage() and g.latency_s == 0.0 and g.model == ""
    assert Usage(3, 4).input_tokens == 3 and CallOptions().timeout_s is None and Capabilities().structured_output == "json_schema"
