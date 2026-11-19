"""`skillforge models` and the provider check: what is configured, which keys are unused, and one tiny call per model."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from test_ai_service import Fake, boom, gen
from test_skill_build import run_cli

from skillforge import cli
from skillforge.ai import AIService, ProfileSet, Profile, load_profiles
from skillforge.ai.doctor import check_models, describe, keys_present
from skillforge.api import create_app
from skillforge.builder import Builder, JobRunner
from skillforge.builder.provider import provider_status
from skillforge.db import Database
from skillforge.library import Library
from skillforge.providers import CallOptions

GEMINI = {"LLM_PROVIDER": "gemini", "LLM_MODEL": "m-default", "GOOGLE_API_KEY": "key-gemini-12345678"}
ALL = {**GEMINI, "GROQ_API_KEY": "key-groq-12345678", "OPENAI_API_KEY": "key-openai-12345678"}


def test_keys_present_lists_provider_names_never_values():
    assert keys_present(ALL) == ["gemini", "groq", "openai"]
    assert keys_present({"GOOGLE_API_KEY": "  ", "GROQ_API_KEY": ""}) == []
    assert keys_present({"LLM_API_KEY": "k"}) == []  # a custom endpoint needs its address as well
    assert keys_present({"LLM_API_KEY": "k", "LLM_BASE_URL": "https://example.test/v1"}) == ["custom"]
    assert "key-groq" not in json.dumps(keys_present(ALL))


def test_describe_shows_the_routing_and_flags_a_key_that_nothing_uses():
    svc = AIService(load_profiles({**ALL, "LLM_FAST_PROVIDER": "groq", "LLM_FAST_MODEL": "g-fast", "LLM_FALLBACKS": "groq:g-back"}))
    info = describe(svc, ALL)
    assert info["default"] == {"provider": "gemini", "model": "m-default"}
    assert {t["tier"]: (t["provider"], t["model"]) for t in info["tiers"]}["fast"] == ("groq", "g-fast")
    assert info["fallbacks"] == [{"provider": "groq", "model": "g-back"}] and info["escalation"] is None
    assert info["keys_present"] == ["gemini", "groq", "openai"]
    assert [u["provider"] for u in info["unused"]] == ["openai"]
    assert "OPENAI_API_KEY" in info["unused"][0]["hint"] and "LLM_FALLBACKS=openai:" in info["unused"][0]["hint"]
    assert "key-" not in json.dumps(info)


def test_a_provider_used_only_as_a_fallback_is_not_called_unused():
    svc = AIService(load_profiles({**ALL, "LLM_FALLBACKS": "openai:o1"}))
    assert [u["provider"] for u in describe(svc, ALL)["unused"]] == ["groq"]


def test_check_models_asks_each_distinct_model_once_and_never_raises():
    default = Fake([gen(tokens=(7, 3))], "gemini", "m1", secrets=["key-gemini-12345678"])
    fast = Fake([boom("overloaded"), ], "groq", "g1")
    back = Fake([gen()], "groq", "g1")  # the same model again: asked once only
    other = Fake([boom("auth", False)], "openai", "o1")
    profiles = ProfileSet(
        Profile("default", default, CallOptions()), {}, None,
        (Profile("fallback", fast, CallOptions()), Profile("fallback", back, CallOptions()), Profile("fallback", other, CallOptions())),
    )
    rows = check_models(AIService(profiles))
    assert [(r["provider"], r["model"], r["ok"]) for r in rows] == [("gemini", "m1", True), ("groq", "g1", False), ("openai", "o1", False)]
    assert (rows[0]["input_tokens"], rows[0]["output_tokens"]) == (7, 3) and rows[0]["latency_ms"] >= 0
    assert (rows[1]["kind"], rows[2]["kind"]) == ("overloaded", "auth") and rows[0]["kind"] == ""
    assert len(default.calls) == len(fast.calls) == 1 and back.calls == []


def test_check_models_removes_keys_from_what_it_reports():
    key = "key-gemini-12345678"
    default = Fake([ProviderError_with(key)], "gemini", "m1", secrets=[key])
    rows = check_models(AIService(ProfileSet(Profile("default", default, CallOptions()))))
    assert key not in json.dumps(rows) and rows[0]["ok"] is False


def ProviderError_with(key):
    from skillforge.providers import ProviderError
    return ProviderError(f"401 rejected {key}", kind="auth")


def test_check_models_wraps_a_bare_provider():
    from skillforge.providers import MockProvider
    rows = check_models(MockProvider([{"reply": "ok"}]))
    assert len(rows) == 1 and rows[0]["provider"] == "mock"


def test_provider_status_lists_the_fallbacks():
    status = provider_status(lambda: AIService(load_profiles({**ALL, "LLM_FALLBACKS": "groq:g1"})))
    assert status["fallbacks"] == [{"provider": "groq", "model": "g1"}]
    assert "key-groq" not in json.dumps(status)
    from skillforge.providers import MockProvider
    assert provider_status(lambda: MockProvider([]))["fallbacks"] == []


def test_the_models_command_describes_without_calling_anything(monkeypatch, capsys):
    for k, v in ALL.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("LLM_FALLBACKS", "groq:g-back")
    code, out, _ = run_cli(capsys, "models")
    assert code == 0
    assert "gemini" in out and "m-default" in out and "g-back" in out and "OPENAI_API_KEY" in out and "LLM_FALLBACKS=openai:" in out
    assert all(v not in out for v in ALL.values() if v.startswith("key-"))


def test_the_models_command_with_test_makes_one_call_per_model_and_exits_1_if_one_fails(monkeypatch, capsys):
    good, bad = Fake([gen(tokens=(7, 3))], "gemini", "m1"), Fake([boom("quota", False)], "groq", "g1")
    svc = AIService(ProfileSet(Profile("default", good, CallOptions()), {}, None, (Profile("fallback", bad, CallOptions()),)))
    monkeypatch.setattr(cli, "provider_from_env", lambda: svc)
    code, out, _ = run_cli(capsys, "models", "--test")
    assert code == 1 and "gemini/m1" in out and "OK" in out and "groq/g1" in out and "FAILED" in out and "quota" in out
    assert len(good.calls) == 1 and len(bad.calls) == 1
    monkeypatch.setattr(cli, "provider_from_env", lambda: AIService(ProfileSet(Profile("default", Fake([gen()], "gemini", "m1"), CallOptions()))))
    code, out, _ = run_cli(capsys, "models", "--test", "--json")
    assert code == 0 and json.loads(out)["checks"][0]["ok"] is True


def test_the_api_checks_the_models_on_request(tmp_path):
    db = Database(f"sqlite:///{(tmp_path / 'c.db').as_posix()}")
    db.migrate()
    fake = Fake([gen(tokens=(5, 2))], "gemini", "m1")
    svc = AIService(ProfileSet(Profile("default", fake, CallOptions())))
    builder = Builder(db, Library(tmp_path / "lib"), tmp_path / "b", provider_factory=lambda: svc, runner=JobRunner(inline=True))
    client = TestClient(create_app(Library(tmp_path / "lib"), builder=builder), base_url="http://localhost")
    r = client.post("/api/provider/check")
    assert r.status_code == 200 and r.json()["checks"][0]["ok"] is True and r.json()["checks"][0]["model"] == "m1"
    assert len(fake.calls) == 1
    db.close()
