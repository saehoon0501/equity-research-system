"""Deterministic stuck-loop fingerprints per gate (P0-4 extraction).

Each ``fingerprint_*`` collapses a gate's result dataclass into a stable
string signature used by the agent_harness retry loop for stuck-loop
detection. Extracted verbatim from ``__init__.py`` (the old ``_fingerprint_*``
functions) so the registry runners can import them without a circular
dependency. Logic is unchanged.
"""

from __future__ import annotations

from src.eval.gates.envelope_shape import EnvelopeShapeResult
from src.eval.gates.evidence_uuid_check import EvidenceUUIDResult
from src.eval.gates.outside_view_blend import OutsideViewBlendResult
from src.eval.gates.sizing_math import SizingMathResult
from src.eval.gates.counterfactual_catalog import CounterfactualCatalogResult
from src.eval.gates.quant_memo_shape import QuantMemoShapeResult
from src.eval.gates.strategic_memo_shape import StrategicMemoShapeResult
from src.eval.gates.catalyst_memo_shape import CatalystMemoShapeResult
from src.eval.gates.cdd_memo_shape import CDDMemoShapeResult
from src.eval.gates.tactical_envelope_shape import TacticalEnvelopeShapeResult
from src.eval.gates.reversion_envelope_shape import ReversionEnvelopeShapeResult
from src.eval.gates.intangibles_adjustment_shape import IntangiblesAdjustmentResult
from src.eval.gates.intervention_audit_shape import InterventionAuditShapeResult
from src.eval.gates.catalyst_modifier_composition_check import (
    CatalystModifierCompositionResult,
)
from src.eval.gates.crowding_composition_check import CrowdingCompositionResult


def fingerprint_envelope_shape(r: EnvelopeShapeResult) -> str:
    parts = sorted(r.missing_top_level)
    parts += [f"subkey:{k}" for k in sorted(r.missing_subkeys)]
    parts += [f"forbidden:{f}" for f in sorted(r.forbidden_fields_present)]
    if r.invalid_summary_code is not None:
        parts.append(f"summary_code:{r.invalid_summary_code}")
    return "|".join(parts) if parts else "ok"


def fingerprint_evidence(r: EvidenceUUIDResult) -> str:
    parts: list[str] = []
    if r.n_refs == 0:
        parts.append("empty_refs")
    if r.n_invalid_uuid:
        parts.append(f"invalid_uuid:{r.n_invalid_uuid}")
    if r.n_placeholders:
        parts.append(f"placeholder:{r.n_placeholders}")
    if r.n_duplicates:
        parts.append(f"duplicate:{r.n_duplicates}")
    if r.unresolved_uuids:
        parts.append(f"unresolved:{len(r.unresolved_uuids)}")
    return "|".join(parts) if parts else "ok"


def fingerprint_outside_view(r: OutsideViewBlendResult) -> str:
    parts: list[str] = []
    if r.corrected_delta is not None and abs(r.corrected_delta) > r.epsilon:
        parts.append("corrected_mismatch")
    if (
        r.raw_divergence_delta is not None
        and abs(r.raw_divergence_delta) > r.epsilon
    ):
        parts.append("raw_div_mismatch")
    if (
        r.corrected_divergence_delta is not None
        and abs(r.corrected_divergence_delta) > r.epsilon
    ):
        parts.append("corrected_div_mismatch")
    return "|".join(parts) if parts else "ok"


def fingerprint_sizing(r: SizingMathResult) -> str:
    parts: list[str] = []
    if r.conviction not in (None, "HIGH", "MEDIUM", "LOW"):
        parts.append(f"conviction:{r.conviction}")
    if r.mode not in (None, "B", "B'", "B_prime", "C"):
        parts.append(f"mode:{r.mode}")
    if r.min_delta is not None and abs(r.min_delta) > r.epsilon:
        parts.append("min_mismatch")
    if r.max_delta is not None and abs(r.max_delta) > r.epsilon:
        parts.append("max_mismatch")
    if r.midpoint_delta is not None and abs(r.midpoint_delta) > r.epsilon:
        parts.append("midpoint_mismatch")
    if r.tier_clip_required and r.clipped_max_expected is not None:
        parts.append("speculative_clip_missing")
    return "|".join(parts) if parts else "ok"


def fingerprint_quant_memo(r: QuantMemoShapeResult) -> str:
    parts: list[str] = []
    for k in r.missing_top_level:
        parts.append(f"top:{k}")
    for k in r.missing_quality_gate_keys:
        parts.append(f"qg:{k}")
    for k in r.missing_outside_view_keys:
        parts.append(f"ov:{k}")
    for k in r.missing_reinvestment_moat_keys:
        parts.append(f"rim:{k}")
    for fk in r.missing_frameworks:
        parts.append(f"fw:{fk}")
    if r.invalid_helmer_anchor is not None:
        parts.append(f"anchor:{r.invalid_helmer_anchor}")
    if r.falsifier_date_issues:
        parts.append("falsifier_date_quarter_end")
    if r.speculative_skip_non_conformance:
        parts.append("skip_non_conformance")
    return "|".join(sorted(parts)) if parts else "ok"


def fingerprint_strategic_memo(r: StrategicMemoShapeResult) -> str:
    parts: list[str] = []
    for k in r.missing_top_level:
        parts.append(f"top:{k}")
    for fk in r.missing_frameworks:
        parts.append(f"fw:{fk}")
    if r.invalid_power_names:
        parts.append(f"bad_power_names:{len(r.invalid_power_names)}")
    if r.held_powers_with_insufficient_citations:
        parts.append(
            f"underciter_powers:{len(r.held_powers_with_insufficient_citations)}"
        )
    if r.invalid_citation_uuids:
        parts.append(f"bad_uuid:{len(r.invalid_citation_uuids)}")
    for b in r.missing_capital_allocation_buckets:
        parts.append(f"capalloc:{b}")
    if r.invalid_letter_grades:
        parts.append(f"bad_grade:{len(r.invalid_letter_grades)}")
    if r.buyback_anchor_missing:
        parts.append("buyback_anchor_missing")
    return "|".join(sorted(parts)) if parts else "ok"


def fingerprint_catalyst_memo(r: CatalystMemoShapeResult) -> str:
    parts: list[str] = []
    for k in r.missing_top_level:
        parts.append(f"top:{k}")
    if r.invalid_catalyst_entries:
        parts.append(f"bad_catalyst:{len(r.invalid_catalyst_entries)}")
    for k in r.missing_positioning_keys:
        parts.append(f"pos:{k}")
    if r.tier_insufficient_inconsistency:
        parts.append("tier_insufficient_inconsistency")
    if r.invalid_sentiment_entries:
        parts.append(f"bad_sentiment:{len(r.invalid_sentiment_entries)}")
    if r.sentiment_indicators_missing:
        parts.append(
            f"missing_indicators:{len(r.sentiment_indicators_missing)}"
        )
    if r.sentiment_degraded_mismatch:
        parts.append("sentiment_degraded_mismatch")
    for k in r.missing_modifier_keys:
        parts.append(f"mod:{k}")
    if r.invalid_modifier_values:
        parts.append(f"bad_mod:{len(r.invalid_modifier_values)}")
    if r.invalid_active_manager_read is not None:
        parts.append(f"bad_amr:{r.invalid_active_manager_read}")
    return "|".join(sorted(parts)) if parts else "ok"


def fingerprint_cdd_memo(r: CDDMemoShapeResult) -> str:
    parts: list[str] = []
    for k in r.missing_top_level:
        parts.append(f"top:{k}")
    for k in r.missing_brief_metadata:
        parts.append(f"bm:{k}")
    for k in r.missing_quality_gate:
        parts.append(f"qg:{k}")
    for k in r.missing_outside_view_summary:
        parts.append(f"ovs:{k}")
    for k in r.missing_reinvestment_moat_summary:
        parts.append(f"rms:{k}")
    for k in r.missing_helmer_powers_summary:
        parts.append(f"hps:{k}")
    for k in r.missing_narrative_dcf_summary:
        parts.append(f"nds:{k}")
    for k in r.missing_thesis:
        parts.append(f"thesis:{k}")
    for k in r.missing_banned_outputs:
        parts.append(f"banned:{k}")
    if r.invalid_disposition is not None:
        parts.append(f"disp:{r.invalid_disposition}")
    return "|".join(sorted(parts)) if parts else "ok"


def fingerprint_tactical_envelope(r: TacticalEnvelopeShapeResult) -> str:
    """Deterministic stuck-loop signature for tactical envelope shape gate."""
    parts: list[str] = []
    for k in r.missing_top_level:
        parts.append(f"top:{k}")
    for v in r.invalid_enum_values:
        parts.append(f"enum:{v}")
    if r.missing_unavailable_reason:
        parts.append("missing_unavailable_reason")
    if r.invalid_unavailable_reason is not None:
        parts.append(f"bad_unavail_reason:{r.invalid_unavailable_reason}")
    if r.rf_degenerate_not_bool:
        parts.append("rf_degenerate_not_bool")
    if r.tactical_cell_not_dict:
        parts.append("tactical_cell_not_dict")
    for k in r.missing_cell_subkeys:
        parts.append(f"cell:{k}")
    if r.invalid_conviction is not None:
        parts.append(f"bad_conviction:{r.invalid_conviction}")
    if r.invalid_cell_disposition is not None:
        # INV-2.1-A violation surface — distinctive fingerprint to catch
        # canonical BUY/TRIM/SELL leakage at retry-loop boundaries.
        parts.append(f"bad_disposition:{r.invalid_cell_disposition}")
    if r.invalid_cell_size_type is not None:
        parts.append(f"bad_size_type:{r.invalid_cell_size_type}")
    return "|".join(sorted(parts)) if parts else "ok"


def fingerprint_intangibles(r: IntangiblesAdjustmentResult) -> str:
    parts: list[str] = []
    if not r.block_present:
        parts.append("block:missing")
    for k in r.missing_numeric_fields:
        parts.append(f"missing:{k}")
    for k in sorted(r.forbidden_sentinels_in_numeric_fields.keys()):
        parts.append(f"sentinel:{k}")
    for k in r.missing_epw_rate_keys:
        parts.append(f"epw:{k}")
    if r.invalid_fama_french_class is not None:
        parts.append(f"ff5:{r.invalid_fama_french_class}")
    if r.invalid_regime is not None:
        parts.append(f"regime:{r.invalid_regime}")
    if r.skip_flag_inconsistency is not None:
        parts.append("skip_flag_inconsistent")
    return "|".join(sorted(parts)) if parts else "ok"


def fingerprint_catalyst_modifier_composition(
    r: CatalystModifierCompositionResult,
) -> str:
    """Deterministic stuck-loop signature for HG-34 (catalyst+flow modifier composition).

    Distinguishes:
    - missing inputs (envelope or params absent) — caller fixes by providing the input
    - invalid inputs (envelope present but malformed)
    - drift_detected — pm-supervisor emitted a different audit_string than the
      deterministic helper produces; pm-supervisor needs to invoke the helper
      verbatim per its §6 contract.
    """
    parts: list[str] = []
    for k in r.missing_inputs:
        parts.append(f"missing:{k}")
    for k in r.invalid_inputs:
        parts.append(f"invalid:{k}")
    if r.drift_detected:
        parts.append("audit_string_drift")
    return "|".join(sorted(parts)) if parts else "ok"


def fingerprint_crowding_composition(r: CrowdingCompositionResult) -> str:
    """Deterministic stuck-loop signature for HG-35 (crowding composition).

    Distinguishes:
    - missing inputs (flow envelope's components.crowding.warning absent or params absent)
    - invalid inputs (parameter coercion failed; logic_operator unrecognized)
    - invariant_violations (INV-CRD-1/2/3 surfaced — fail-safe contract breached)
    - drift_detected — re-derived warning bit-different from emitted; agent
      must invoke classify_crowding() verbatim per its emission contract.
    """
    parts: list[str] = []
    for k in r.missing_inputs:
        parts.append(f"missing:{k}")
    for k in r.invalid_inputs:
        parts.append(f"invalid:{k}")
    for v in r.invariant_violations:
        # Take the invariant identifier (INV-CRD-X) as the stable signature
        head = v.split(":", 1)[0]
        parts.append(f"invariant:{head}")
    if r.drift_detected:
        parts.append("warning_drift")
    return "|".join(sorted(parts)) if parts else "ok"


def fingerprint_reversion_envelope(r: ReversionEnvelopeShapeResult) -> str:
    """Deterministic stuck-loop signature for reversion envelope shape gate (HG-36)."""
    parts: list[str] = []
    for k in r.missing_top_level:
        parts.append(f"top:{k}")
    for v in r.invalid_enum_values:
        parts.append(f"enum:{v}")
    if r.invalid_audit_mode is not None:
        parts.append(f"audit_mode:{r.invalid_audit_mode}")
    for v in r.audit_mode_field_violations:
        parts.append(f"audit_field:{v[:40]}")  # truncate long messages
    if r.reversion_cell_non_null:
        parts.append("reversion_cell_non_null")
    if r.missing_unavailable_reason:
        parts.append("missing_unavailable_reason")
    if r.invalid_unavailable_reason is not None:
        parts.append(f"bad_unavail_reason:{r.invalid_unavailable_reason}")
    for k in r.missing_components_keys:
        parts.append(f"comp:{k}")
    for k in r.missing_sub_signal_fires:
        parts.append(f"fires:{k}")
    if r.inv_3_6_a_violation:
        parts.append("inv_3_6_a")
    for v in r.inv_3_6_b_violation:
        parts.append(f"inv_3_6_b:{v[:40]}")
    return "|".join(sorted(parts)) if parts else "ok"


def fingerprint_intervention_audit(r: InterventionAuditShapeResult) -> str:
    """Deterministic stuck-loop signature for the intervention-audit shape gate (HG-39)."""
    parts: list[str] = []
    for k in r.missing_top_level:
        parts.append(f"top:{k}")
    for top_key in sorted(r.missing_subkeys):
        for sk in r.missing_subkeys[top_key]:
            parts.append(f"subkey:{top_key}.{sk}")
    return "|".join(sorted(parts)) if parts else "ok"


def fingerprint_counterfactual(r: CounterfactualCatalogResult) -> str:
    parts: list[str] = []
    if r.missing_buckets:
        parts.append(f"missing:{','.join(sorted(r.missing_buckets))}")
    if r.invented_buckets:
        parts.append(f"invented_bucket:{','.join(sorted(r.invented_buckets))}")
    if r.invented_fields:
        parts.append(f"invented_field:{','.join(sorted(r.invented_fields))}")
    if r.case_ids_not_in_catalog:
        parts.append(f"unresolved:{len(r.case_ids_not_in_catalog)}")
    return "|".join(parts) if parts else "ok"


__all__ = [
    "fingerprint_envelope_shape",
    "fingerprint_evidence",
    "fingerprint_outside_view",
    "fingerprint_sizing",
    "fingerprint_quant_memo",
    "fingerprint_strategic_memo",
    "fingerprint_catalyst_memo",
    "fingerprint_cdd_memo",
    "fingerprint_tactical_envelope",
    "fingerprint_reversion_envelope",
    "fingerprint_intangibles",
    "fingerprint_intervention_audit",
    "fingerprint_catalyst_modifier_composition",
    "fingerprint_crowding_composition",
    "fingerprint_counterfactual",
]
