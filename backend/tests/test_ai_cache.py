"""The opt-in response cache: only validated answers, never for eval replies, expiring, bounded, and off by default."""

from __future__ import annotations

import json

from pydantic import BaseModel
from test_ai_service import OK, Answer, Fake, Recorder, boom, gen, service

from skillforge.ai import Task
from skillforge.ai.cache import FileCache, cache_key
from skillforge.ai.service import service_from_env
from skillforge.graph.store import data_dir

GEMINI = {"LLM_PROVIDER": "gemini", "LLM_MODEL": "m-default", "GOOGLE_API_KEY": "key-one-1234567890"}


def test_a_hit_returns_the_same_answer_without_a_call(tmp_path):
    p, rec = Fake([gen()]), Recorder()
    svc = service(p, cache=FileCache(tmp_path), recorder=rec)
    assert svc.generate(Task.DESIGN, Answer, "same prompt", "s") == (OK, 1)
    assert svc.generate(Task.DESIGN, Answer, "same prompt", "s") == (OK, 0)
    assert len(p.calls) == 1 and svc.usage.calls == 1  # a hit is not a call, and not against the budget
    assert [r.status for r in rec.rows] == ["ok", "cache"] and rec.rows[1].input_tokens is None


def test_off_by_default(tmp_path):
    p = Fake([gen(), gen()])
    svc = service(p)
    svc.generate(Task.DESIGN, Answer, "q")
    svc.generate(Task.DESIGN, Answer, "q")
    assert len(p.calls) == 2


def test_eval_replies_are_never_cached(tmp_path):
    p = Fake([gen(), gen()])
    svc = service(p, cache=FileCache(tmp_path))
    svc.generate(Task.ACT, Answer, "q")
    svc.generate(Task.ACT, Answer, "q")
    assert len(p.calls) == 2 and list(tmp_path.glob("*.json")) == []


def test_only_validated_answers_are_stored(tmp_path):
    svc = service(Fake([boom("auth", False)]), cache=FileCache(tmp_path))
    try:
        svc.generate(Task.DESIGN, Answer, "q")
    except Exception:  # noqa: BLE001
        pass
    assert list(tmp_path.glob("*.json")) == []


def test_a_cached_text_that_no_longer_fits_the_schema_is_ignored_and_replaced(tmp_path):
    cache = FileCache(tmp_path)
    p = Fake([gen()])
    svc = service(p, cache=cache)
    key = cache_key("fake", "fake-1", Answer, None, "q")
    cache.put(key, json.dumps({"word": "only-a-word"}))  # missing "count"
    assert svc.generate(Task.DESIGN, Answer, "q") == (OK, 1) and len(p.calls) == 1


def test_expired_and_corrupt_entries_are_ignored(tmp_path):
    now = {"t": 1000.0}
    cache = FileCache(tmp_path, ttl_s=100, clock=lambda: now["t"])
    key = "a" * 64
    cache.put(key, "text")
    assert cache.get(key) == "text"
    now["t"] += 101
    assert cache.get(key) is None and not (tmp_path / f"{key}.json").exists()  # expired entries are removed
    (tmp_path / f"{'b' * 64}.json").write_text("not json at all", encoding="utf-8")
    assert cache.get("b" * 64) is None
    assert cache.get("../escape") is None and cache.get("short") is None  # a key is 64 hex characters, never a path


def test_the_oldest_entries_are_pruned_beyond_the_limit(tmp_path):
    now = {"t": 1000.0}
    cache = FileCache(tmp_path, max_entries=3, clock=lambda: now["t"])
    keys = [f"{i:064x}" for i in range(5)]
    for k in keys:
        now["t"] += 1
        cache.put(k, f"text {k[-1]}")
    assert [cache.get(k) for k in keys] == [None, None, "text 2", "text 3", "text 4"]


def test_the_key_changes_with_model_provider_system_prompt_and_schema():
    class Other(BaseModel):
        word: str

    base = cache_key("gemini", "m1", Answer, "s", "p")
    assert len({base, cache_key("gemini", "m2", Answer, "s", "p"), cache_key("openai", "m1", Answer, "s", "p"),
                cache_key("gemini", "m1", Answer, "t", "p"), cache_key("gemini", "m1", Answer, "s", "q"),
                cache_key("gemini", "m1", Other, "s", "p")}) == 6
    assert base == cache_key("gemini", "m1", Answer, "s", "p") and len(base) == 64


def test_the_cache_is_per_model(tmp_path):
    cache = FileCache(tmp_path)
    first, second = Fake([gen()], model="m1"), Fake([gen()], model="m2")
    service(first, cache=cache).generate(Task.DESIGN, Answer, "q")
    service(second, cache=cache).generate(Task.DESIGN, Answer, "q")
    assert len(first.calls) == 1 and len(second.calls) == 1


def test_service_from_env_turns_the_cache_on_only_when_asked():
    assert service_from_env(GEMINI).cache is None
    assert service_from_env({**GEMINI, "SKILLFORGE_LLM_CACHE": "0"}).cache is None
    on = service_from_env({**GEMINI, "SKILLFORGE_LLM_CACHE": "1"})
    assert isinstance(on.cache, FileCache) and on.cache.root == data_dir() / "llm-cache"
