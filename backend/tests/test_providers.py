from __future__ import annotations

import json

import httpx2
import openai
import pytest
from pydantic import BaseModel

from skillforge.providers import (
    CallOptions, Capabilities, Generation, MockProvider, OpenAICompatibleProvider, ProviderError, Usage, build_provider,
    provider_from_env,
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


def test_factory_builds_anthropic_and_build_provider_takes_a_timeout():
    a = provider_from_env({"LLM_PROVIDER": "Anthropic", "LLM_MODEL": "m3", "ANTHROPIC_API_KEY": "k"})
    assert (a.name, a.model, type(a).__name__) == ("anthropic", "m3", "AnthropicProvider")
    p = build_provider("gemini", "m", {"GOOGLE_API_KEY": "k"}, timeout_s=12.0)
    assert (p.name, p.model, p._client.timeout.read) == ("gemini", "m", 12.0)


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
        ({"LLM_PROVIDER": "nonsense"}, "Supported: anthropic, custom, gemini, groq, mistral, openai, openrouter"),
        ({"LLM_PROVIDER": "gemini"}, "LLM_MODEL is empty"),
        ({"LLM_PROVIDER": "gemini", "LLM_MODEL": "m"}, "GOOGLE_API_KEY is empty"),
        ({"LLM_PROVIDER": "openai", "LLM_MODEL": "m"}, "OPENAI_API_KEY is empty"),
        ({"LLM_PROVIDER": "anthropic", "LLM_MODEL": "m"}, "ANTHROPIC_API_KEY is empty"),
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


# ---- usage, options and error kinds ------------------------------------------------------------------


def ok_handler(seen=None, usage=None):
    def handler(request):
        if seen is not None:
            seen["body"] = json.loads(request.content)
            seen["request"] = request
        body = completion(json.dumps({"word": "ok", "count": 3}))
        if usage:
            body["usage"] = usage
        return httpx2.Response(200, json=body)
    return handler


def test_adapter_returns_usage_latency_and_served_model():
    g = adapter(ok_handler(usage={"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18})).generate(Answer, "q")
    assert g.value == Answer(word="ok", count=3)
    assert (g.usage.input_tokens, g.usage.output_tokens) == (11, 7)
    assert g.model == "m" and g.latency_s >= 0


def test_adapter_without_usage_reports_none_not_zero():
    body = completion(json.dumps({"word": "ok", "count": 3}))
    del body["usage"]
    g = adapter(lambda request: httpx2.Response(200, json=body)).generate(Answer, "q")
    assert (g.usage.input_tokens, g.usage.output_tokens) == (None, None)


def test_adapter_forwards_options_only_when_set():
    seen = {}
    adapter(ok_handler(seen)).generate(Answer, "q", options=CallOptions(max_output_tokens=50, timeout_s=5.0))
    assert seen["body"]["max_completion_tokens"] == 50
    assert seen["request"].extensions["timeout"]["read"] == 5.0
    seen.clear()
    adapter(ok_handler(seen)).generate(Answer, "q")
    assert "max_completion_tokens" not in seen["body"] and "max_tokens" not in seen["body"]


def test_generate_structured_still_returns_just_the_value():
    assert adapter(ok_handler()).generate_structured(Answer, "q") == Answer(word="ok", count=3)


def test_default_client_has_no_hidden_retries_and_a_bounded_timeout():
    p = OpenAICompatibleProvider(name="x", model="m", api_key="k", key_env="K", base_url="https://example.test/v1")
    assert p._client.max_retries == 0
    assert p._client.timeout.read == 90.0 and p._client.timeout.connect == 5.0
    assert OpenAICompatibleProvider(name="x", model="m", api_key="k", key_env="K", timeout_s=30.0)._client.timeout.read == 30.0


def test_adapter_declares_its_capabilities_and_secrets():
    p = OpenAICompatibleProvider(name="x", model="m", api_key="the-key-value", key_env="K")
    assert p.capabilities.structured_output == "json_schema" and p.secrets == ("the-key-value",)


@pytest.mark.parametrize(
    "status, body, kind",
    [
        (401, {"error": {"message": "bad key"}}, "auth"),
        (403, {"error": {"message": "no permission"}}, "auth"),
        (404, {"error": {"message": "model retired"}}, "model_missing"),
        (400, {"error": {"message": "bad shape"}}, "bad_request"),
        (408, {"error": {"message": "too slow"}}, "timeout"),
        (429, {"error": {"message": "slow down"}}, "rate_limit"),
        (429, {"error": {"message": "pay up", "code": "insufficient_quota"}}, "quota"),
        (429, {"error": {"message": "You have no credits remaining"}}, "quota"),
        (500, {"error": {"message": "oops"}}, "overloaded"),
        (503, {"error": {"message": "overloaded"}}, "overloaded"),
    ],
)
def test_http_errors_get_kinds(status, body, kind):
    with pytest.raises(ProviderError) as info:
        adapter(lambda request: httpx2.Response(status, json=body)).generate(Answer, "q")
    assert info.value.kind == kind


def test_network_failures_are_timeout_or_connection_and_retryable():
    def timeout(request):
        raise httpx2.ReadTimeout("slow", request=request)

    def refused(request):
        raise httpx2.ConnectError("down", request=request)

    with pytest.raises(ProviderError) as t:
        adapter(timeout).generate(Answer, "q")
    with pytest.raises(ProviderError) as c:
        adapter(refused).generate(Answer, "q")
    assert (t.value.kind, t.value.retryable) == ("timeout", True)
    assert (c.value.kind, c.value.retryable) == ("connection", True)


def test_429_reads_retry_after_from_the_header_or_the_message():
    with pytest.raises(ProviderError) as h:
        adapter(lambda request: httpx2.Response(429, json={"error": {"message": "x"}}, headers={"retry-after": "7"})).generate(Answer, "q")
    assert h.value.retry_after_s == 7.0
    with pytest.raises(ProviderError) as m:
        adapter(lambda request: httpx2.Response(429, json={"error": {"message": "Quota hit. Please retry in 12.5s."}})).generate(Answer, "q")
    assert m.value.retry_after_s == 12.5
    with pytest.raises(ProviderError) as n:
        adapter(lambda request: httpx2.Response(429, json={"error": {"message": "x"}}, headers={"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"})).generate(Answer, "q")
    assert n.value.retry_after_s is None


def test_a_length_cut_off_is_too_long_and_is_not_retried_with_the_same_prompt():
    body = completion('{"word": "ok", "co')
    body["choices"][0]["finish_reason"] = "length"
    with pytest.raises(ProviderError) as info:
        adapter(lambda request: httpx2.Response(200, json=body)).generate(Answer, "q")
    assert info.value.kind == "too_long" and info.value.retryable is False


def test_a_request_the_model_says_is_too_big_is_input_too_large_and_is_not_retried():
    """Found by a real run: Groq answered 413 ("Request too large ... tokens per minute") and that was `other`, which says nothing a caller can act on."""
    with pytest.raises(ProviderError) as big:
        adapter(lambda request: httpx2.Response(413, json={"error": {"message": "Request too large: limit 8000, requested 16728"}})).generate(Answer, "q")
    with pytest.raises(ProviderError) as ctx:
        adapter(lambda request: httpx2.Response(
            400, json={"error": {"message": "This model's maximum context length is 8192 tokens.", "code": "context_length_exceeded"}}
        )).generate(Answer, "q")
    for info in (big, ctx):
        assert info.value.kind == "input_too_large" and info.value.retryable is False


def groq_failed_json(produced='{"parts":[{"id":"kinds"}]}'):
    """What Groq answers (HTTP 400, code json_validate_failed) when the model's JSON does not match the schema; found by a real run of the guide."""
    return httpx2.Response(400, json={"error": {
        "message": "Failed to validate JSON. Please adjust your prompt. See 'failed_generation' for more details.",
        "type": "invalid_request_error", "code": "json_validate_failed", "failed_generation": produced,
    }})


def test_a_json_the_provider_says_failed_validation_is_invalid_output_and_keeps_what_the_model_wrote():
    with pytest.raises(ProviderError) as info:
        adapter(lambda request: groq_failed_json()).generate(Answer, "q")
    e = info.value
    assert e.kind == "invalid_output" and e.retryable is True
    assert "kinds" in e.detail and 0 < len(e.detail) <= 600  # the model is told what it wrote, capped like every detail


def test_a_very_long_failed_generation_is_cut_in_the_detail():
    with pytest.raises(ProviderError) as info:
        adapter(lambda request: groq_failed_json("x" * 5000)).generate(Answer, "q")
    assert info.value.kind == "invalid_output" and len(info.value.detail) <= 600


def test_that_failure_is_asked_again_once_with_what_was_wrong_in_the_prompt():
    from skillforge.ai.policy import NO_WAIT
    from skillforge.ai.profiles import Profile, ProfileSet
    from skillforge.ai.service import AIService
    from skillforge.ai.tasks import Task
    from skillforge.providers import CallOptions

    seen = []

    def handler(request):
        seen.append(json.loads(request.content)["messages"][-1]["content"])
        return groq_failed_json() if len(seen) == 1 else httpx2.Response(200, json=completion(json.dumps({"word": "ok", "count": 3})))

    service = AIService(ProfileSet(Profile("default", adapter(handler), CallOptions())), policy=NO_WAIT, sleep=lambda seconds: None)
    value, calls = service.generate(Task.DESIGN, Answer, "question")
    assert value == Answer(word="ok", count=3) and calls == 2
    assert "What was wrong" in seen[1] and "kinds" in seen[1] and seen[0] == "question"  # the second prompt carries the feedback, the first was plain


def test_an_ordinary_bad_request_and_a_server_error_keep_their_own_kinds():
    with pytest.raises(ProviderError) as bad:
        adapter(lambda request: httpx2.Response(400, json={"error": {"message": "bad field", "code": "invalid_value"}})).generate(Answer, "q")
    with pytest.raises(ProviderError) as server:
        adapter(lambda request: httpx2.Response(500, json={"error": {"message": "boom"}})).generate(Answer, "q")
    assert bad.value.kind == "bad_request" and server.value.kind == "overloaded"


def test_invalid_json_is_invalid_output_with_a_short_detail():
    provider = adapter(lambda request: httpx2.Response(200, json=completion('{"word": "x"}')))
    with pytest.raises(ProviderError) as info:
        provider.generate(Answer, "q")
    assert info.value.kind == "invalid_output" and info.value.retryable
    assert 0 < len(info.value.detail) <= 600


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
