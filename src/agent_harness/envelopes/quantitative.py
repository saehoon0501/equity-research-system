"""quantitative-analyst envelope contract — single source of truth.

Per harness-v4-final Phase 4 (2026-05-22). Mirrors HG-29 surface
(``src/evaluator_gates/quant_memo_shape.py``).

This is the highest-blast-radius non-pm-supervisor cutover because the
quant memo carries Overlay 1–5 (outside_view, reinvestment_moat,
bull/bear narratives with helmer_power_anchor, intangibles_adjustment).
HG-ENV enforces the SKELETON; HG-29 owns the deep semantic checks
(falsifier-date sub-rule, dual-DCF inherited+austere mandate, sentinel
conformance for speculative-tier skip strings).
"""
from __future__ import annotations

from typing import Any

from src.agent_harness.envelopes._base import (
    EnvelopeValidationResult,
    Predicate,
    insight_quality_properties,
    validate_envelope,
)
from src.evaluator_gates.quant_memo_shape import (
    CANONICAL_HELMER_POWERS,
    PENDING_STRATEGIC_SENTINEL,
    REQUIRED_FRAMEWORKS_CORE_THEMATIC,
    REQUIRED_OUTSIDE_VIEW_KEYS,
    REQUIRED_QUALITY_GATE_KEYS,
    REQUIRED_REINVESTMENT_MOAT_KEYS,
    SPECULATIVE_SKIP_SENTINEL,
    VALID_TIERS,
)


REASONING_STEPS: tuple[str, ...] = (
    "load_company_facts",
    "load_peer_comps",
    "compute_piotroski_f_score",
    "compute_altman_z_double_prime",
    "evaluate_quality_gate",
    "load_outside_view_reference_class",
    "compute_outside_view_prior",
    "blend_intuitive_with_reference",
    "compute_dcf_inherited_case",
    "compute_dcf_austere_case",
    "compute_dcf_bull_case",
    "compute_dcf_bear_case",
    "run_mauboussin_reverse_dcf",
    "evaluate_buffett_inevitables",
    "classify_reinvestment_moat",
    "anchor_helmer_power_to_strategic",
    "compute_intangibles_adjustment",
    "compose_bull_case_narrative",
    "compose_bear_case_narrative",
    "emit_envelope",
)


_QUALITY_GATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": list(REQUIRED_QUALITY_GATE_KEYS),
    "additionalProperties": True,
    "properties": {
        "piotroski_f_score": {
            "type": "integer",
            "minimum": 0,
            "maximum": 9,
        },
        "altman_z_double_prime": {"type": "number"},
        "passes_quality_gate": {"type": "boolean"},
    },
}


SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "analyst",
        "ticker",
        "tier",
        "quality_gate",
        "frameworks_cited",
        "evidence_index_refs",
        "banned_outputs_check",
        "reasoning_path_taken",
    ],
    # frameworks_cited body is deeply nested; HG-29 owns the semantic
    # detail (Overlay 1-5 sub-validators). HG-ENV pins the skeleton.
    "additionalProperties": True,
    "properties": {
        "analyst": {"type": "string"},
        "ticker": {"type": "string"},
        "tier": {"type": "string", "enum": sorted(VALID_TIERS)},
        "quality_gate": _QUALITY_GATE_SCHEMA,
        "frameworks_cited": {},  # list OR dict; CAF-2 dual-read
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


def _is_skip_sentinel(v: object) -> bool:
    return isinstance(v, str) and v.strip().upper().startswith(
        SPECULATIVE_SKIP_SENTINEL.split(" ")[0].upper()
    )


# P0-1 (additive, backward-compatible): document the five OPTIONAL
# insight-quality fields in ``properties``. Top-level schema is
# ``additionalProperties: True`` so they would already pass; listing them
# makes the dispatch-rendered schema show them to the LLM. None required.
SCHEMA["properties"].update(insight_quality_properties())


# ---------- Cross-field predicates -----------------------------------


def _required_frameworks_cited_when_non_speculative(env: dict[str, Any]) -> bool:
    """Core/thematic tiers must cite all 4 frameworks. Speculative may
    SKIP frameworks with the canonical skip sentinel — but the cited
    list itself must still be present."""
    if env.get("tier") == "speculative_optionality":
        return True
    for fk in REQUIRED_FRAMEWORKS_CORE_THEMATIC:
        if _find_framework(env, fk) is None:
            return False
    return True


def _outside_view_complete_when_non_speculative(env: dict[str, Any]) -> bool:
    """outside_view block must have all sub-keys present for core/thematic.
    Speculative may emit the canonical SPECULATIVE_SKIP_SENTINEL."""
    fw = _find_framework(env, "damodaran_narrative_dcf")
    if fw is None:
        # caught by required_frameworks_cited_when_non_speculative
        return env.get("tier") == "speculative_optionality"
    ov = (fw.get("output") or {}).get("outside_view")
    tier = env.get("tier")
    if tier == "speculative_optionality":
        return ov is None or _is_skip_sentinel(ov)
    if not isinstance(ov, dict):
        return False
    for k in REQUIRED_OUTSIDE_VIEW_KEYS:
        v = ov.get(k)
        if v is None:
            return False
        if isinstance(v, str) and v.strip() == "":
            return False
    return True


def _reinvestment_moat_complete_when_non_speculative(env: dict[str, Any]) -> bool:
    """reinvestment_moat block (inside buffett_2007_inevitables) must have
    all sub-keys for core/thematic. Speculative may skip."""
    if env.get("tier") == "speculative_optionality":
        return True
    fw = _find_framework(env, "buffett_2007_inevitables")
    if fw is None:
        return False
    rm = (fw.get("output") or {}).get("reinvestment_moat")
    if not isinstance(rm, dict):
        return False
    for k in REQUIRED_REINVESTMENT_MOAT_KEYS:
        if rm.get(k) is None:
            return False
    return True


def _helmer_anchor_canonical_or_pending(env: dict[str, Any]) -> bool:
    """Bull and bear case narratives must carry a helmer_power_anchor
    that is either a canonical snake_case Power name OR the
    PENDING_STRATEGIC_SENTINEL (Overlay 1 cross-agent reference)."""
    fw = _find_framework(env, "damodaran_narrative_dcf")
    if fw is None:
        return env.get("tier") == "speculative_optionality"
    out = fw.get("output") or {}
    for case in ("bull_case_narrative", "bear_case_narrative"):
        narr = out.get(case)
        if isinstance(narr, str) and _is_skip_sentinel(narr):
            continue
        if not isinstance(narr, dict):
            return False
        anchor = narr.get("helmer_power_anchor")
        if anchor == PENDING_STRATEGIC_SENTINEL:
            continue
        if anchor not in CANONICAL_HELMER_POWERS:
            return False
    return True


PREDICATES: dict[str, Predicate] = {
    "required_frameworks_cited_when_non_speculative":
        _required_frameworks_cited_when_non_speculative,
    "outside_view_complete_when_non_speculative":
        _outside_view_complete_when_non_speculative,
    "reinvestment_moat_complete_when_non_speculative":
        _reinvestment_moat_complete_when_non_speculative,
    "helmer_anchor_canonical_or_pending":
        _helmer_anchor_canonical_or_pending,
}


def validate(data: Any) -> EnvelopeValidationResult:
    return validate_envelope(
        data,
        schema=SCHEMA,
        reasoning_steps=REASONING_STEPS,
        predicates=PREDICATES,
    )


__all__ = ["PREDICATES", "REASONING_STEPS", "SCHEMA", "validate"]
