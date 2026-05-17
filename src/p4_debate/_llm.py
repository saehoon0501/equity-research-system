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
) -> str:
    """One ``messages.create`` round-trip; returns the assistant text.

    Mirrors the helper in ``mode_classifier/stage3_overlap_tiebreaker.py``
    so the test-double surface is identical.
    """
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
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
