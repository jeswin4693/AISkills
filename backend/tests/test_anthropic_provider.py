"""The native Anthropic adapter, against a mocked HTTP server. Never a real key, never the network."""

from __future__ import annotations

import json

import anthropic
import httpx2
import pytest
from pydantic import BaseModel

from skillforge.providers import AnthropicProvider, CallOptions, ProviderError


class Answer(BaseModel):
    word: str
    count: int


def message(text: str, stop_reason: str = "end_turn", usage=(11, 7)) -> dict:
    return {
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-served",
        "content": [{"type": "text", "text": text}], "stop_reason": stop_reason, "stop_sequence": None,
        "usage": {"input_tokens": usage[0], "output_tokens": usage[1]},
    }


GOOD = json.dumps({"word": "ok", "count": 3})


def adapter(handler) -> AnthropicProvider:
    client = anthropic.Anthropic(
        api_key="k", base_url="https://example.test", max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
    )
    return AnthropicProvider(name="anthropic", model="m", api_key="k", key_env="MY_KEY", client=client)


def error_body(kind: str, text: str) -> dict:
    return {"type": "error", "error": {"type": kind, "message": text}}


def test_sends_system_and_schema_and_parses_the_answer():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, json=message(GOOD))

    g = adapter(handler).generate(Answer, "question", system="rules")
    assert g.value == Answer(word="ok", count=3)
    assert seen["body"]["system"] == "rules" and seen["body"]["model"] == "m"
    assert seen["body"]["messages"] == [{"role": "user", "content": "question"}]
    assert seen["body"]["output_config"]["format"]["type"] == "json_schema"
    assert seen["body"]["max_tokens"] == 16000


def test_returns_usage_latency_and_served_model_and_generate_structured_is_the_value():
    p = adapter(lambda request: httpx2.Response(200, json=message(GOOD)))
    g = p.generate(Answer, "q")
    assert (g.usage.input_tokens, g.usage.output_tokens, g.model) == (11, 7, "claude-served") and g.latency_s >= 0
    assert p.generate_structured(Answer, "q") == Answer(word="ok", count=3)


def test_options_are_forwarded():
    seen = {}

    def handler(request):
        seen["body"], seen["request"] = json.loads(request.content), request
        return httpx2.Response(200, json=message(GOOD))

    adapter(handler).generate(Answer, "q", options=CallOptions(max_output_tokens=300, timeout_s=4.0))
    assert seen["body"]["max_tokens"] == 300 and seen["request"].extensions["timeout"]["read"] == 4.0


def test_declares_capabilities_and_secrets_and_has_no_hidden_retries():
    p = AnthropicProvider(name="anthropic", model="m", api_key="the-key-value", key_env="K")
    assert p.secrets == ("the-key-value",) and p.capabilities.structured_output == "json_schema"
    assert p._client.max_retries == 0 and p._client.timeout.read == 90.0


@pytest.mark.parametrize(
    "status, kind, retryable",
    [
        (401, "auth", False), (403, "auth", False), (404, "model_missing", False), (400, "bad_request", False),
        (408, "timeout", True), (429, "rate_limit", False), (500, "overloaded", True), (529, "overloaded", True),
    ],
)
def test_http_errors_get_kinds(status, kind, retryable):
    with pytest.raises(ProviderError) as info:
        adapter(lambda request: httpx2.Response(status, json=error_body("x_error", "nope"))).generate(Answer, "q")
    assert (info.value.kind, info.value.retryable) == (kind, retryable)


def test_the_429_wait_is_read_from_the_header():
    with pytest.raises(ProviderError) as info:
        adapter(lambda request: httpx2.Response(429, json=error_body("rate_limit_error", "x"), headers={"retry-after": "9"})).generate(Answer, "q")
    assert info.value.retry_after_s == 9.0


def test_network_failures_are_retryable():
    def timeout(request):
        raise httpx2.ReadTimeout("slow", request=request)

    def refused(request):
        raise httpx2.ConnectError("down", request=request)

    with pytest.raises(ProviderError) as t:
        adapter(timeout).generate(Answer, "q")
    with pytest.raises(ProviderError) as c:
        adapter(refused).generate(Answer, "q")
    assert (t.value.kind, t.value.retryable, c.value.kind, c.value.retryable) == ("timeout", True, "connection", True)


def test_a_413_is_input_too_large_and_is_not_retried():
    body = {"type": "error", "error": {"type": "request_too_large", "message": "Request exceeds the maximum allowed number of bytes."}}
    with pytest.raises(ProviderError) as info:
        adapter(lambda request: httpx2.Response(413, json=body)).generate(Answer, "q")
    assert info.value.kind == "input_too_large" and info.value.retryable is False


def test_a_refusal_and_a_cut_off_answer_are_reported_by_kind():
    with pytest.raises(ProviderError) as r:
        adapter(lambda request: httpx2.Response(200, json=message("", stop_reason="refusal"))).generate(Answer, "q")
    assert r.value.kind == "refused"
    with pytest.raises(ProviderError) as m:
        adapter(lambda request: httpx2.Response(200, json=message('{"word": "o', stop_reason="max_tokens"))).generate(Answer, "q")
    assert m.value.kind == "too_long" and m.value.retryable is False


def test_invalid_json_is_invalid_output_with_a_short_detail():
    with pytest.raises(ProviderError) as info:
        adapter(lambda request: httpx2.Response(200, json=message('{"word": "x"}'))).generate(Answer, "q")
    assert info.value.kind == "invalid_output" and info.value.retryable and 0 < len(info.value.detail) <= 600
