"""Shared Anthropic-SDK glue for all phase modules.

Per the same Path-A convention as ``src/mode_classifier/stage3_overlap_tiebreaker.py``:
the SDK is imported lazily; tests inject a fake client via ``client=``;
absent ``ANTHROPIC_API_KEY`` we raise ``LLMUnavailableError`` rather
than silently default.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

_LOG = logging.getLogger(__name__)


class LLMUnavailableError(RuntimeError):
    """Raised when the SDK is missing or no credentials are available."""


def build_default_client() -> Any:
    """Build an Anthropic client from the environment, or raise."""
    try:
        import anthropic  # type: ignore[import-not-found]
    except ImportError as exc:
        raise LLMUnavailableError(
            "anthropic SDK not installed; pip install anthropic OR pass a "
            "test double via the `client=` argument."
        ) from exc
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise LLMUnavailableError(
            "ANTHROPIC_API_KEY not set in environment. Per BUILD_LOG.md "
            "decision 1 (Path A), the v0.1 runtime is Claude Code; the "
            "P4 debate orchestrator is therefore expected to be invoked "
            "under Claude Code's MCP tool surface or with a pre-built "
            "client supplied via the `client=` kwarg."
        )
    return anthropic.Anthropic()


def call_messages(
    client: Any,
    model: str,
    system: str,
    user: str,
    *,
    max_tokens: int = 2048,
    temperature: float = 0.3,
    sample_index: int = 0,
) -> str:
    """One ``messages.create`` round-trip; returns the assistant text.

    Mirrors the helper in ``mode_classifier/stage3_overlap_tiebreaker.py``
    so the test-double surface is identical.

    Opt-in response-replay cache (P0-5): when ``LLM_CACHE_ENABLED`` is set in
    the environment, the call is routed through ``src.llm_cache`` keyed on the
    resolved model id + ``(prompt_sha, temperature, max_tokens, sample_index)``.
    Default OFF — absent the env flag this is a pure pass-through and runtime
    behaviour is identical to before. ``sample_index`` lets a self-consistency
    caller (N samples at one temperature) cache each sample distinctly.
    """
    cache = None
    try:
        from src.llm_cache import cache_from_env, cached_call_messages  # noqa: WPS433

        cache = cache_from_env()
    except Exception:  # pragma: no cover - cache import must never break runtime
        cache = None

    if cache is not None:
        return cached_call_messages(
            cache=cache,
            model=model,
            system=system,
            user=user,
            temperature=temperature,
            max_tokens=max_tokens,
            sample_index=sample_index,
            compute=lambda: _raw_call_messages(
                client, model, system, user, max_tokens, temperature
            ),
        )
    return _raw_call_messages(client, model, system, user, max_tokens, temperature)


def _raw_call_messages(
    client: Any,
    model: str,
    system: str,
    user: str,
    max_tokens: int,
    temperature: float,
) -> str:
    """The actual ``messages.create`` round-trip (cache-agnostic)."""
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    # Stash the raw response on the client so cost-aware callers (WS-5 BoN-MAV
    # cost rollup) can read token usage without changing call_messages' text
    # return contract. Best-effort: never fails the call if the client is a
    # restricted object.
    try:
        client.last_response = resp
    except Exception:  # pragma: no cover - read-only client object
        pass
    blocks = getattr(resp, "content", None) or []
    for b in blocks:
        text = getattr(b, "text", None)
        if text:
            return text
    if isinstance(resp, dict):
        for b in resp.get("content", []) or []:
            if isinstance(b, dict) and b.get("text"):
                return str(b["text"])
    raise RuntimeError("LLM response had no extractable text block")


def extract_json(text: str) -> Optional[dict]:
    """Best-effort JSON extraction (matches ``mode_classifier`` convention).

    Models occasionally emit code fences or leading prose despite the
    system prompt; we strip the first/last brace span before parse.
    """
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
