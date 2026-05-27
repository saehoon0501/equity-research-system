"""strategic-analyst envelope contract — single source of truth.

Per harness-v4-final Phase 3 (2026-05-22). Mirrors the schema enforced
by ``src/evaluator_gates/strategic_memo_shape.py`` (HG-30).

HG-ENV ↔ HG-30 division of labor:
  - HG-ENV (this module): top-level structural shape, frameworks_cited
    listing, Helmer power_name enum membership, capital_allocation
    grades letter-grade enum, reasoning-path enum, plus cross-field
    predicates (held-Power citation floor, buybacks anchor keyword
    presence).
  - HG-30 continues to enforce identical semantics. Their delta-prompts
    are additive (iter-3 finding).
"""
from __future__ import annotations

import uuid
from typing import Any

from src.agent_harness.envelopes._base import (
    EnvelopeValidationResult,
    Predicate,
    insight_quality_properties,
    validate_envelope,
)
from src.evaluator_gates.strategic_memo_shape import (
    BUYBACK_ANCHOR_KEYWORDS,
    CANONICAL_HELMER_POWERS,
    CAPITAL_ALLOCATION_BUCKETS,
    HELD_POWER_MIN_CITATIONS,
    REQUIRED_FRAMEWORKS,
    VALID_LETTER_GRADES,
    VALID_POWER_STATUSES,
)


# Reasoning-path enum — strategic-analyst's audit-traceable decision path.
REASONING_STEPS: tuple[str, ...] = (
    "load_company_facts",
    "load_peer_comps",
    "apply_mauboussin_moat_2024",
    "evaluate_helmer_power_scale_economies",
    "evaluate_helmer_power_network_economies",
    "evaluate_helmer_power_counter_positioning",
    "evaluate_helmer_power_switching_costs",
    "evaluate_helmer_power_branding",
    "evaluate_helmer_power_cornered_resource",
    "evaluate_helmer_power_process_power",
    "grade_capital_allocation_capex",
    "grade_capital_allocation_rd",
    "grade_capital_allocation_ma",
    "grade_capital_allocation_dividends",
    "grade_capital_allocation_buybacks",
    "grade_capital_allocation_debt",
    "compute_overall_capital_allocation_grade",
    "emit_envelope",
)


_HELMER_POWER_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["power_name", "status"],
    "additionalProperties": True,
    "properties": {
        "power_name": {
            "type": "string",
            "enum": sorted(CANONICAL_HELMER_POWERS),
        },
        "status": {
            "type": "string",
            "enum": sorted(VALID_POWER_STATUSES),
        },
        "primary_source_citations": {
            "type": "array",
            "items": {"type": "string"},
        },
        "benefit_cashflow_effect": {"type": "string"},
        "barrier_to_arbitrage": {"type": "string"},
    },
}


SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "analyst",
        "ticker",
        "tier",
        "frameworks_cited",
        "evidence_index_refs",
        "banned_outputs_check",
        "reasoning_path_taken",
    ],
    # Strategic memo nests deep structures (frameworks_cited body, etc.)
    # we don't want to fully type-out here — additionalProperties=True
    # lets HG-30 own the semantic detail while HG-ENV pins the spine.
    "additionalProperties": True,
    "properties": {
        "analyst": {"type": "string"},
        "ticker": {"type": "string"},
        "tier": {
            "type": "string",
            "enum": [
                "core_fundamental",
                "thematic_growth",
                "speculative_optionality",
            ],
        },
        "frameworks_cited": {},  # list OR dict; CAF-2 dual-read; checked in predicate
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


def _find_framework(env: dict[str, Any], key: str) -> dict[str, Any] | None:
    fwc = env.get("frameworks_cited")
    if isinstance(fwc, dict):
        v = fwc.get(key)
        return v if isinstance(v, dict) else None
    if isinstance(fwc, list):
        for item in fwc:
            if isinstance(item, dict) and item.get("key") == key:
                return item
    return None


# P0-1 (additive, backward-compatible): document the five OPTIONAL
# insight-quality fields in ``properties``. Top-level schema is
# ``additionalProperties: True`` so they would already pass; listing them
# makes the dispatch-rendered schema show them to the LLM. None required.
SCHEMA["properties"].update(insight_quality_properties())


# ---------- Cross-field predicates -----------------------------------


def _all_required_frameworks_cited(env: dict[str, Any]) -> bool:
    """Frameworks_cited must reference all 3 strategic frameworks."""
    for fk in REQUIRED_FRAMEWORKS:
        if _find_framework(env, fk) is None:
            return False
    return True


def _held_powers_have_min_citations(env: dict[str, Any]) -> bool:
    """Every Helmer power with status=='held' must have ≥2 primary-source
    citations with valid UUID format (Overlay 1 hard rule)."""
    fw = _find_framework(env, "helmer_7_powers")
    if fw is None:
        return True  # caught by all_required_frameworks_cited predicate
    powers = (fw.get("output") or {}).get("helmer_powers_evidence") or []
    if not isinstance(powers, list):
        return False
    for p in powers:
        if not isinstance(p, dict):
            return False
        if p.get("status") != "held":
            continue
        citations = p.get("primary_source_citations") or []
        if not isinstance(citations, list):
            return False
        valid_count = 0
        for c in citations:
            try:
                uuid.UUID(str(c))
                valid_count += 1
            except (ValueError, AttributeError):
                pass
        if valid_count < HELD_POWER_MIN_CITATIONS:
            return False
    return True


def _capital_allocation_grades_complete(env: dict[str, Any]) -> bool:
    """All 6 capital_allocation buckets must have a canonical letter grade."""
    fw = _find_framework(env, "mauboussin_capital_allocation_2024")
    if fw is None:
        return True
    grades = (fw.get("output") or {}).get("grades") or {}
    if not isinstance(grades, dict):
        return False
    for bucket in CAPITAL_ALLOCATION_BUCKETS:
        g = grades.get(bucket)
        if isinstance(g, dict):
            g = g.get("grade")
        if not isinstance(g, str) or g not in VALID_LETTER_GRADES:
            return False
    return True


def _buybacks_grade_has_anchor(env: dict[str, Any]) -> bool:
    """Buybacks bucket reasoning text must cite a dual-anchor keyword."""
    fw = _find_framework(env, "mauboussin_capital_allocation_2024")
    if fw is None:
        return True
    grades = (fw.get("output") or {}).get("grades") or {}
    buyback = grades.get("buybacks") if isinstance(grades, dict) else None
    if not isinstance(buyback, dict):
        return True  # caught by capital_allocation_grades_complete
    reasoning = str(buyback.get("reasoning", "")).lower()
    if not reasoning:
        return False
    return any(kw in reasoning for kw in BUYBACK_ANCHOR_KEYWORDS)


PREDICATES: dict[str, Predicate] = {
    "all_required_frameworks_cited": _all_required_frameworks_cited,
    "held_powers_have_min_citations": _held_powers_have_min_citations,
    "capital_allocation_grades_complete": _capital_allocation_grades_complete,
    "buybacks_grade_has_anchor": _buybacks_grade_has_anchor,
}


def validate(data: Any) -> EnvelopeValidationResult:
    return validate_envelope(
        data,
        schema=SCHEMA,
        reasoning_steps=REASONING_STEPS,
        predicates=PREDICATES,
    )


__all__ = ["PREDICATES", "REASONING_STEPS", "SCHEMA", "validate"]
