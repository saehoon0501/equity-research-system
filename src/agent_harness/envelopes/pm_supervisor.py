"""pm-supervisor envelope contract — single source of truth.

Per harness-v4-final Phase 5 (2026-05-22). Mirrors HG-23 surface
(``src/evaluator_gates/envelope_shape.py``) and ports the §2.6 stress
enum (pm-supervisor.md lines 53-61) into a typed Literal so an invented
stress sub_test_name fails at HG-ENV (closing the freeform-stress
loophole that produced Bug 3 / byte-identical-input divergence).

This is the highest-risk cutover because the §2.6 enum surgery is the
load-bearing piece. Per harness-v4-final v4-final (iter-3 reviewer
caution): the canonical 5 STRESS_* tokens MUST be ported VERBATIM. Any
drift here re-opens the loophole.
"""
from __future__ import annotations

from typing import Any

from src.agent_harness.envelopes._base import (
    EnvelopeValidationResult,
    Predicate,
    validate_envelope,
)
from src.evaluator_gates.envelope_shape import (
    FORBIDDEN_TOP_LEVEL,
    REPORT_ROW_SUBKEYS,
    REQUIRED_SUBKEYS,
    REQUIRED_TOP_LEVEL,
    VALID_SUMMARY_CODES,
)


# Canonical §2.6 stress enum — pm-supervisor.md §2.6 lines 53-61.
# Ported VERBATIM from prose to Literal per v4-final Phase 5. Drift here
# re-opens the freeform-stress loophole that produced Bug 3.
STRESS_SUB_TESTS: tuple[str, ...] = (
    "STRESS_HELMER_POWER_ABSENT",
    "STRESS_HELMER_POWER_UNDER_EVIDENCED",
    "STRESS_REINVESTMENT_QUALITY_D_CONTRADICTION",
    "STRESS_CAPITAL_LIGHT_CHAIN_BROKEN",
    "STRESS_GENERIC_CLAIM_INVERSION_FAILED",
)

CONVICTION_VALUES: tuple[str, ...] = ("HIGH", "MEDIUM", "LOW")


# Reasoning-path enum — pm-supervisor's audit-traceable decision path.
# §2.6 stress tests are part of this path; named individually so the
# agent emits them only when actually executed.
REASONING_STEPS: tuple[str, ...] = (
    "load_cdd_integrated_memo",
    "load_tactical_envelope",
    "load_catalyst_envelope",
    "classify_mode",
    "compose_tl_dr",
    "compose_report_sentiment_row",
    "compose_report_trend_row",
    "compose_report_structural_theory_row",
    "compose_report_technical_entry_row",
    "compose_report_technical_exit_row",
    "compose_report_reasoning_row",
    "run_stress_helmer_power_absent",
    "run_stress_helmer_power_under_evidenced",
    "run_stress_reinvestment_quality_d_contradiction",
    "run_stress_capital_light_chain_broken",
    "run_stress_generic_claim_inversion_failed",
    "compose_adversarial_stress_test",
    "evaluate_counterfactual_veto",
    "compute_sleeve_cap_check",
    "compute_conviction_from_rule",
    "compute_conviction_emitted",
    "derive_summary_code",
    "derive_size_band_if_long",
    "compose_counterfactual_top3_summary",
    "compose_audit_trail_hint",
    "emit_envelope",
)


_TL_DR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": list(REQUIRED_SUBKEYS["tl_dr"]),
    "additionalProperties": True,
    "properties": {k: {} for k in REQUIRED_SUBKEYS["tl_dr"]},
}


_REPORT_ROW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": list(REPORT_ROW_SUBKEYS),
    "additionalProperties": True,
    "properties": {k: {} for k in REPORT_ROW_SUBKEYS},
}


_REPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": list(REQUIRED_SUBKEYS["report"]),
    "additionalProperties": True,
    "properties": {k: _REPORT_ROW_SCHEMA for k in REQUIRED_SUBKEYS["report"]},
}


_AUDIT_HINT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": list(REQUIRED_SUBKEYS["audit_trail_hint"]),
    "additionalProperties": True,
    "properties": {k: {} for k in REQUIRED_SUBKEYS["audit_trail_hint"]},
}


SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": list(REQUIRED_TOP_LEVEL) + ["reasoning_path_taken"],
    # FORBIDDEN_TOP_LEVEL ({summary_code_operator_semantic}) is enforced
    # by predicate — additionalProperties=True so we don't reject other
    # legitimate forward-compat fields, but the predicate explicitly
    # rejects the deprecated names.
    "additionalProperties": True,
    "properties": {
        "ticker": {"type": "string"},
        "as_of": {"type": "string"},
        "tier": {
            "type": "string",
            "enum": [
                "core_fundamental",
                "thematic_growth",
                "speculative_optionality",
            ],
        },
        "mode": {"type": "string"},
        "tl_dr": _TL_DR_SCHEMA,
        "report": _REPORT_SCHEMA,
        "audit_trail_hint": _AUDIT_HINT_SCHEMA,
        "summary_code": {
            "type": "string",
            "enum": sorted(VALID_SUMMARY_CODES),
        },
        "conviction": {"type": "string", "enum": list(CONVICTION_VALUES)},
        "size_band_if_long": {},
        "size_band_pre_modifier_midpoint_pp": {},
        "sleeve_cap_check": {},
        "counterfactual_top3_summary": {},
        "adversarial_stress_test": {
            "type": "object",
            "additionalProperties": True,
        },
        "catalyst_modifier_applied": {},
        "veto_reason": {},  # null OR string
        "conviction_rationale": {"type": "string"},
        "evidence_index_refs": {
            "type": "array",
            "items": {"type": "string"},
        },
        "rule_engine_version": {"type": "string"},
        "conviction_from_rule": {"type": "string", "enum": list(CONVICTION_VALUES)},
        "conviction_emitted": {"type": "string", "enum": list(CONVICTION_VALUES)},
        "conviction_override": {},  # bool OR object
        "reasoning_path_taken": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
}


# ---------- Cross-field predicates -----------------------------------


def _no_forbidden_top_level_fields(env: dict[str, Any]) -> bool:
    """The HIGH-4 consensus (docs/high-4-enum-drift-consensus.md) banned
    ``summary_code_operator_semantic`` — must not appear in envelope."""
    for f in FORBIDDEN_TOP_LEVEL:
        if f in env:
            return False
    return True


def _stress_kills_fired_enum_only(env: dict[str, Any]) -> bool:
    """Every kills_fired_evidence[].sub_test_name MUST be in the
    canonical 5-element §2.6 STRESS_* enum. This is the load-bearing
    rule that closed the freeform-stress loophole (Bug 3 / Phase 5a A1
    vs A7 byte-identical-input divergence)."""
    ast = env.get("adversarial_stress_test")
    if not isinstance(ast, dict):
        return True  # absence caught by schema required-list
    kills = ast.get("kills_fired_evidence")
    if not isinstance(kills, list):
        return True
    for k in kills:
        if not isinstance(k, dict):
            return False
        name = k.get("sub_test_name")
        if name not in STRESS_SUB_TESTS:
            return False
    return True


def _summary_code_canonical_only(env: dict[str, Any]) -> bool:
    """summary_code must be one of {BUY, HOLD, TRIM, SELL} (canonical
    4-bin per HIGH-4 consensus Item #1; 5-bin variants forbidden)."""
    sc = env.get("summary_code")
    return sc in VALID_SUMMARY_CODES


def _veto_reason_string_or_null(env: dict[str, Any]) -> bool:
    """veto_reason must be either null (no veto fired) or a non-empty
    string. Empty string is a known regression surface."""
    v = env.get("veto_reason", None)
    if v is None:
        return True
    if isinstance(v, str) and len(v.strip()) > 0:
        return True
    return False


PREDICATES: dict[str, Predicate] = {
    "no_forbidden_top_level_fields": _no_forbidden_top_level_fields,
    "stress_kills_fired_enum_only": _stress_kills_fired_enum_only,
    "summary_code_canonical_only": _summary_code_canonical_only,
    "veto_reason_string_or_null": _veto_reason_string_or_null,
}


def validate(data: Any) -> EnvelopeValidationResult:
    return validate_envelope(
        data,
        schema=SCHEMA,
        reasoning_steps=REASONING_STEPS,
        predicates=PREDICATES,
    )


__all__ = [
    "CONVICTION_VALUES",
    "PREDICATES",
    "REASONING_STEPS",
    "SCHEMA",
    "STRESS_SUB_TESTS",
    "validate",
]
