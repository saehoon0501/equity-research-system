"""catalyst-scout envelope contract — single source of truth.

Per harness-v4-final Phase 2 (2026-05-22). Mirrors the schema enforced
by ``src/eval/gates/catalyst_memo_shape.py`` (HG-31).

HG-ENV ↔ HG-31 division of labor:
  - HG-ENV (this module) enforces STRUCTURAL shape: required keys, enum
    membership, cross-field algebra the JSON Schema can't express via
    PREDICATES.
  - HG-31 continues to enforce SEMANTIC consistency post-hoc
    (sentiment_data_degraded recomputation cross-check). Both run; their
    delta-prompts are additive (iter-3 finding).

The PREDICATES are the SUBSET of cross-field invariants reducible to a
pure function of the emitted envelope (no recomputation against signal
arrays — that's HG-31's territory). Anything reducible to a JSON-Schema
constraint stays in SCHEMA (iter-3 contract).
"""
from __future__ import annotations

from typing import Any

from src.shared.agent_harness.envelopes._base import (
    EnvelopeValidationResult,
    Predicate,
    insight_quality_properties,
    validate_envelope,
)
from src.eval.gates.catalyst_memo_shape import (
    MAX_MODIFIER_REASON_LEN,
    VALID_ACTIVE_MANAGER_READS,
    VALID_CATALYST_TYPES,
    VALID_CONFIDENCE,
    VALID_KPI_IMPACTS,
    VALID_MODIFIER_DIRECTIONS,
    VALID_MODIFIER_MAGNITUDES,
)

# Reasoning-path enum — catalyst-scout's audit-traceable decision path.
# Invented steps → HG-ENV hard fail.
REASONING_STEPS: tuple[str, ...] = (
    "load_forward_catalyst_calendar",
    "rank_top_catalysts_90d",
    "load_options_positioning",
    "load_institutional_flow",
    "load_sentiment_indicators",
    "compute_sentiment_data_degraded",
    "derive_conviction_modifier",
    "handle_degraded_fallback",
    "emit_envelope",
)


_CATALYST_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["date", "type", "source", "kpi_impact", "confidence"],
    "additionalProperties": True,
    "properties": {
        "date": {"type": "string"},
        "type": {"type": "string", "enum": sorted(VALID_CATALYST_TYPES)},
        "source": {"type": "string"},
        "kpi_impact": {"type": "string", "enum": sorted(VALID_KPI_IMPACTS)},
        "confidence": {"type": "string", "enum": sorted(VALID_CONFIDENCE)},
    },
}


_SENTIMENT_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["indicator", "reading", "reading_date", "implication"],
    "additionalProperties": True,
    "properties": {
        "indicator": {"type": "string"},
        "reading": {"type": ["string", "number", "null"]},
        "reading_date": {"type": ["string", "null"]},
        "implication": {"type": "string"},
    },
}


_CONVICTION_MODIFIER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["direction", "magnitude", "reason"],
    "additionalProperties": True,
    "properties": {
        "direction": {
            "type": "integer",
            "enum": sorted(VALID_MODIFIER_DIRECTIONS),
        },
        "magnitude": {
            "type": "string",
            "enum": sorted(VALID_MODIFIER_MAGNITUDES),
        },
        "reason": {"type": "string"},
    },
}


_INSTITUTIONAL_FLOW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [],
    "additionalProperties": True,
    "properties": {
        "active_manager_conviction_read": {
            "type": ["string", "null"],
            "enum": sorted(VALID_ACTIVE_MANAGER_READS) + [None],
        },
    },
}


_POSITIONING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["tier_insufficient", "framework_keys"],
    "additionalProperties": True,
    "properties": {
        "tier_insufficient": {"type": "boolean"},
        "framework_keys": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
}


SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "ticker",
        "tier",
        "as_of",
        "catalysts",
        "positioning",
        "institutional_flow",
        "sentiment_signals",
        "sentiment_data_degraded",
        "conviction_modifier",
        "evidence_index_refs",
        "banned_outputs_check",
        "reasoning_path_taken",
    ],
    "additionalProperties": True,
    "properties": {
        "ticker": {"type": "string"},
        "tier": {
            "type": "string",
            "enum": [
                "core_fundamental",
                "thematic_growth",
                "speculative_optionality",
            ],
        },
        "as_of": {"type": "string"},
        "catalysts": {"type": "array", "items": _CATALYST_ITEM_SCHEMA},
        "positioning": _POSITIONING_SCHEMA,
        "institutional_flow": _INSTITUTIONAL_FLOW_SCHEMA,
        "sentiment_signals": {
            "type": "array",
            "items": _SENTIMENT_ITEM_SCHEMA,
        },
        "sentiment_data_degraded": {"type": "boolean"},
        "conviction_modifier": _CONVICTION_MODIFIER_SCHEMA,
        "evidence_index_refs": {
            "type": "array",
            "items": {"type": "string"},
        },
        "banned_outputs_check": {"type": "boolean"},
        "reasoning_path_taken": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
}


# P0-1 (additive, backward-compatible): document the five OPTIONAL
# insight-quality fields in ``properties``. Top-level schema is
# ``additionalProperties: True`` so they would already pass; listing them
# makes the dispatch-rendered schema show them to the LLM. None required.
SCHEMA["properties"].update(insight_quality_properties())


# ---------- Cross-field predicates -----------------------------------


def _tier_insufficient_consistency(env: dict[str, Any]) -> bool:
    """If positioning.tier_insufficient == True, iv_spread and p_c_ratio
    MUST be absent / null (the agent must not emit live positioning
    metrics when the tier doesn't support them).
    """
    pos = env.get("positioning") or {}
    if pos.get("tier_insufficient") is not True:
        return True
    for k in ("iv_spread", "p_c_ratio"):
        v = pos.get(k)
        if v not in (None, "", []):
            return False
    return True


def _conviction_modifier_reason_bounded(env: dict[str, Any]) -> bool:
    cm = env.get("conviction_modifier") or {}
    reason = cm.get("reason", "")
    if not isinstance(reason, str):
        return False
    return len(reason) <= MAX_MODIFIER_REASON_LEN


PREDICATES: dict[str, Predicate] = {
    "tier_insufficient_consistency": _tier_insufficient_consistency,
    "conviction_modifier_reason_bounded": _conviction_modifier_reason_bounded,
}


def validate(data: Any) -> EnvelopeValidationResult:
    return validate_envelope(
        data,
        schema=SCHEMA,
        reasoning_steps=REASONING_STEPS,
        predicates=PREDICATES,
    )


__all__ = ["PREDICATES", "REASONING_STEPS", "SCHEMA", "validate"]
