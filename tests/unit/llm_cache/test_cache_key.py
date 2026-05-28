"""Unit tests for the P0-5 LLM response-replay cache key + cache behaviour.

The load-bearing property under test (plan P0-5): the ``sample_index``
dimension is REQUIRED so that an N=5 self-consistency call produces 5
DISTINCT cache entries rather than collapsing to one.
"""

from __future__ import annotations

import json

import pytest

from src.llm_cache import (
    CacheMissError,
    LLMCache,
    cache_from_env,
    make_cache_key,
    prompt_sha,
)
from src.llm_cache.cache import CacheKey
from src.llm_cache.wrappers import cached_call_messages, cached_call_once


def _key(sample_index: int, **over) -> CacheKey:
    base = dict(
        model_version="claude-opus-4-5",
        system="sys",
        user="usr",
        temperature=0.7,
        max_tokens=1024,
        sample_index=sample_index,
    )
    base.update(over)
    return make_cache_key(**base)


# ---------------------------------------------------------------------------
# Key identity / distinctness
# ---------------------------------------------------------------------------


def test_sample_index_changes_digest():
    """Two keys differing ONLY in sample_index must NOT collide."""
    a = _key(0).digest()
    b = _key(1).digest()
    assert a != b


def test_five_sample_indices_produce_five_distinct_entries():
    """The headline P0-5 assertion: N=5 samples → 5 distinct cache entries."""
    digests = {_key(i).digest() for i in range(5)}
    assert len(digests) == 5


def test_identical_inputs_same_digest():
    """Same 5-tuple → identical digest (deterministic key)."""
    assert _key(2).digest() == _key(2).digest()


def test_temperature_normalised_but_distinct_values_differ():
    assert _key(0, temperature=0.7).digest() == _key(0, temperature=0.70).digest()
    assert _key(0, temperature=0.7).digest() != _key(0, temperature=0.0).digest()


def test_each_dimension_participates_in_key():
    base = _key(0).digest()
    assert _key(0, model_version="claude-sonnet-4-5").digest() != base
    assert _key(0, system="other").digest() != base
    assert _key(0, user="other").digest() != base
    assert _key(0, max_tokens=2048).digest() != base


def test_prompt_sha_is_field_order_sensitive():
    """Moving text between system/user must not collide (length-prefixed)."""
    assert prompt_sha("ab", "c") != prompt_sha("a", "bc")


# ---------------------------------------------------------------------------
# Record / replay behaviour
# ---------------------------------------------------------------------------


def test_record_then_replay_roundtrip(tmp_path):
    rec = LLMCache(cache_dir=tmp_path, mode="record")
    key = _key(0)
    calls = {"n": 0}

    def compute() -> str:
        calls["n"] += 1
        return "RESPONSE-0"

    assert rec.get_or_compute(key, compute) == "RESPONSE-0"
    assert rec.get_or_compute(key, compute) == "RESPONSE-0"
    assert calls["n"] == 1  # second call served from cache

    # New cache instance over the same dir, replay mode → hit served, no compute.
    rep = LLMCache(cache_dir=tmp_path, mode="replay")
    assert rep.get_or_compute(key, lambda: (_ for _ in ()).throw(AssertionError)) == "RESPONSE-0"


def test_replay_miss_raises(tmp_path):
    rep = LLMCache(cache_dir=tmp_path, mode="replay")
    with pytest.raises(CacheMissError):
        rep.get_or_compute(_key(99), lambda: "never")


def test_five_distinct_responses_recorded_and_replayed(tmp_path):
    """End-to-end: record 5 self-consistency samples → 5 stored entries that
    replay deterministically (so a recomputed median is reproducible)."""
    rec = LLMCache(cache_dir=tmp_path, mode="record")
    responses = ["HIGH", "HIGH", "MEDIUM", "HIGH", "LOW"]
    for i, r in enumerate(responses):
        rec.get_or_compute(_key(i), lambda r=r: r)
    assert len(rec) == 5

    rep = LLMCache(cache_dir=tmp_path, mode="replay")
    replayed = [rep.get_or_compute(_key(i), lambda: "MISS") for i in range(5)]
    assert replayed == responses


# ---------------------------------------------------------------------------
# Env-driven construction (default OFF)
# ---------------------------------------------------------------------------


def test_cache_from_env_default_off():
    assert cache_from_env(env={}) is None


def test_cache_from_env_enabled(tmp_path):
    cache = cache_from_env(
        env={"LLM_CACHE_ENABLED": "1", "LLM_CACHE_MODE": "record", "LLM_CACHE_DIR": str(tmp_path)}
    )
    assert isinstance(cache, LLMCache)
    assert cache.mode == "record"


def test_cache_from_env_replay_mode(tmp_path):
    cache = cache_from_env(
        env={"LLM_CACHE_ENABLED": "true", "LLM_CACHE_MODE": "replay", "LLM_CACHE_DIR": str(tmp_path)}
    )
    assert cache.mode == "replay"


# ---------------------------------------------------------------------------
# Wrappers (pass-through when cache is None; cache distinct samples otherwise)
# ---------------------------------------------------------------------------


def test_cached_call_messages_passthrough_when_disabled():
    out = cached_call_messages(
        cache=None,
        model="opus",
        system="s",
        user="u",
        temperature=0.3,
        max_tokens=10,
        sample_index=0,
        compute=lambda: "passthrough",
    )
    assert out == "passthrough"


def test_cached_call_messages_caches_per_sample_index(tmp_path):
    cache = LLMCache(cache_dir=tmp_path, mode="record")
    seen = []

    def make_compute(i):
        def _c():
            seen.append(i)
            return f"resp-{i}"
        return _c

    for i in range(5):
        out = cached_call_messages(
            cache=cache,
            model="opus",
            system="s",
            user="u",
            temperature=0.7,
            max_tokens=1024,
            sample_index=i,
            compute=make_compute(i),
        )
        assert out == f"resp-{i}"
    assert len(cache) == 5
    assert seen == [0, 1, 2, 3, 4]


def test_cached_call_once_roundtrips_objects(tmp_path):
    cache = LLMCache(cache_dir=tmp_path, mode="record")
    obj = {"rating": "HIGH", "confidence": 0.9}
    out = cached_call_once(
        cache=cache,
        model="sonnet",
        system="s",
        user="u",
        temperature=0.7,
        max_tokens=1024,
        sample_index=3,
        compute=lambda: obj,
        dumps=json.dumps,
        loads=json.loads,
    )
    assert out == obj
    # Replay returns the same object without recomputing.
    rep = LLMCache(cache_dir=tmp_path, mode="replay")
    again = cached_call_once(
        cache=rep,
        model="sonnet",
        system="s",
        user="u",
        temperature=0.7,
        max_tokens=1024,
        sample_index=3,
        compute=lambda: (_ for _ in ()).throw(AssertionError),
        dumps=json.dumps,
        loads=json.loads,
    )
    assert again == obj
