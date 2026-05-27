"""Thin opt-in cache wrappers for the existing LLM call-sites (P0-5).

These are *additive* helpers. The existing call-sites
(``src/p4_debate/_llm.py::call_messages`` and
``src/p3_mechanical_scorer/stage2_llm_rubric.py::_call_llm_once``) opt in by
constructing a cache via :func:`cache_from_env` and routing through these
wrappers. When the cache is ``None`` (the default — env flag OFF) the
wrappers call straight through, so runtime behaviour and existing tests are
unchanged.

Each wrapper takes the same arguments the call-site already has, plus an
explicit ``sample_index`` so self-consistency's N samples cache distinctly.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from .cache import LLMCache, make_cache_key
from .model_pin import pin_resolved_model


def cached_call_messages(
    *,
    cache: Optional[LLMCache],
    model: str,
    system: str,
    user: str,
    temperature: float,
    max_tokens: int,
    sample_index: int = 0,
    compute: Callable[[], str],
) -> str:
    """Wrap a ``call_messages``-style call (returns assistant text).

    ``compute`` is the zero-arg thunk that performs the real round-trip
    (e.g. ``lambda: call_messages(client, model, system, user, ...)``). When
    ``cache`` is ``None`` we simply call it; otherwise we route through the
    cache keyed on the resolved model id + the 5-tuple.
    """
    if cache is None:
        return compute()
    key = make_cache_key(
        model_version=pin_resolved_model(model),
        system=system,
        user=user,
        temperature=temperature,
        max_tokens=max_tokens,
        sample_index=sample_index,
    )
    return cache.get_or_compute(key, compute)


def cached_call_once(
    *,
    cache: Optional[LLMCache],
    model: str,
    system: str,
    user: str,
    temperature: float,
    max_tokens: int,
    sample_index: int = 0,
    compute: Callable[[], Any],
    dumps: Callable[[Any], str],
    loads: Callable[[str], Any],
) -> Any:
    """Wrap a ``_call_llm_once``-style call (returns a parsed object).

    The p3 scorer's ``_call_llm_once`` returns a parsed ``dict``. The cache
    stores *text*, so the caller supplies ``dumps``/``loads`` (typically
    ``json.dumps``/``json.loads``) to round-trip the object through the
    string store. When ``cache`` is ``None`` we just return ``compute()``.
    """
    if cache is None:
        return compute()
    key = make_cache_key(
        model_version=pin_resolved_model(model),
        system=system,
        user=user,
        temperature=temperature,
        max_tokens=max_tokens,
        sample_index=sample_index,
    )

    def _compute_text() -> str:
        return dumps(compute())

    text = cache.get_or_compute(key, _compute_text)
    return loads(text)
