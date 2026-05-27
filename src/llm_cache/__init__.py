"""LLM response-replay cache + model pinning (Phase-0 deliverable P0-5).

This package provides a *default-OFF*, opt-in response cache for the
deterministic-replay needs of CI, plus a helper to pin the **resolved**
model id (not an alias) into envelopes.

Design contract (from plan P0-5):

* Cache key = ``(model_version, prompt_sha, temperature, max_tokens,
  sample_index)``. The ``sample_index`` dimension is **required** so that
  self-consistency's N=5 temp-0.7 samples each cache as a *distinct* entry
  rather than collapsing to a single entry (which would degenerate the
  median and trip spurious cache-miss failures).
* Default OFF: unless ``LLM_CACHE_ENABLED`` is truthy in the environment,
  the wrappers are pure pass-throughs and runtime behaviour is unchanged.
* In CI (``LLM_CACHE_ENABLED=1`` + ``LLM_CACHE_MODE=replay``) a cache miss
  raises :class:`CacheMissError` so a missing cassette fails the run.

Public surface:

* :class:`LLMCache`             — the on-disk JSON cache, keyed as above.
* :class:`CacheMissError`       — raised on replay-mode miss.
* :func:`cache_from_env`        — build a cache from env flags (or ``None``).
* :func:`cached_call_messages`  — thin wrapper around the p4_debate call-site.
* :func:`cached_call_once`      — thin wrapper around the p3 scorer call-site.
* :func:`pin_resolved_model`    — resolve an alias → concrete versioned id.
* :func:`resolved_model_id`     — alias for ``pin_resolved_model``.
"""

from __future__ import annotations

from .cache import (
    CacheMissError,
    LLMCache,
    cache_from_env,
    make_cache_key,
    prompt_sha,
)
from .model_pin import (
    MODEL_ALIASES,
    pin_resolved_model,
    resolved_model_id,
)
from .wrappers import cached_call_messages, cached_call_once

__all__ = [
    "CacheMissError",
    "LLMCache",
    "cache_from_env",
    "make_cache_key",
    "prompt_sha",
    "MODEL_ALIASES",
    "pin_resolved_model",
    "resolved_model_id",
    "cached_call_messages",
    "cached_call_once",
]
