"""Resolved-model pinning (P0-5).

Envelopes must stamp the *resolved* model id (a concrete, versioned id),
not a moving alias like ``opus`` / ``sonnet``. This module maps the aliases
used in agent ``.md`` headers and the ``p3``/``p4`` constants onto their
resolved ids so CI can assert ``effective model == pinned``.

The resolved ids mirror the constants already locked in the codebase:
``src/p4_debate/__init__.py`` (``MODEL_SONNET = "claude-sonnet-4-5"``,
``MODEL_OPUS = "claude-opus-4-5"``) and ``src/p3_mechanical_scorer/__init__``
(``DEFAULT_MODEL``/``HIGH_STAKES_MODEL``). Keeping the table here (rather than
importing those modules) avoids a heavy import for a pure-data lookup; the
unit test cross-checks the two stay in sync.
"""

from __future__ import annotations

# Alias → resolved (versioned) model id. Already-resolved ids pass through.
MODEL_ALIASES: dict[str, str] = {
    "opus": "claude-opus-4-5",
    "sonnet": "claude-sonnet-4-5",
    "haiku": "claude-haiku-4-5",
}


def pin_resolved_model(model: str) -> str:
    """Resolve an alias to its concrete versioned id.

    * A bare alias (``"opus"``) resolves to its versioned id.
    * An already-resolved id (``"claude-opus-4-5"``) passes through
      unchanged.
    * An unknown string passes through unchanged (callers that need
      strictness should validate separately) — this keeps the helper from
      throwing on a future model the alias table hasn't learned yet.
    """
    if not model:
        raise ValueError("model must be a non-empty string")
    key = model.strip().lower()
    return MODEL_ALIASES.get(key, model.strip())


# Back-compat / readability alias used by call-sites.
resolved_model_id = pin_resolved_model
