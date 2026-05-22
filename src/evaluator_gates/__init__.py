"""Evaluator gates — deterministic Tier-1 validators for pm-supervisor envelopes.

This package contains the cheap, fast, code-level checks that run as a
post-step hook after each subagent dispatch in /research-company. Tier-2
LLM evaluator (contamination, narrative coherence, evidence sufficiency)
runs only after the Tier-1 gates pass.

Each gate module exports a CLI for standalone invocation by the
orchestrator's Bash tool, plus a programmatic API used by the
``validate_all`` dispatcher below.

Module map (HG = hard-gate identifier):

    envelope_shape         — HG-23 — §8 top-level + sub-key presence, forbidden fields, summary_code enum
    sentiment_degradation  — HG-24 — re-compute sentiment_data_degraded from §4 indicators
    evidence_uuid_check    — HG-26 — evidence_index_refs UUID syntax + DB resolution
    outside_view_blend     — HG-27 — Bayesian-blend math consistency (catches AMZN raw==corrected bug)
    sizing_math            — HG-25 — conviction × mode → expected band; speculative-tier headroom clip
    counterfactual_catalog — HG-28 — top-3 bucket-schema + case_id catalog membership

Aggregate result:

    validate_all(envelope_path, ...) → AggregateValidationResult with
    per-gate pass/fail + a single overall valid bool.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.evaluator_gates.envelope_shape import (
    EnvelopeShapeResult,
    validate_envelope_shape,
)
from src.evaluator_gates.evidence_uuid_check import (
    EvidenceUUIDResult,
    validate_evidence_refs_syntactic,
    validate_evidence_refs_with_db,
)
from src.evaluator_gates.outside_view_blend import (
    OutsideViewBlendResult,
    validate_outside_view_blend,
)
from src.evaluator_gates.sizing_math import (
    SizingMathResult,
    validate_sizing_math,
)
from src.evaluator_gates.counterfactual_catalog import (
    CounterfactualCatalogResult,
    validate_counterfactual_top3,
)
from src.evaluator_gates.sentiment_degradation import (
    compute_sentiment_data_degraded,
)
from src.evaluator_gates.quant_memo_shape import (
    QuantMemoShapeResult,
    validate_quant_memo_shape,
)
from src.evaluator_gates.strategic_memo_shape import (
    StrategicMemoShapeResult,
    validate_strategic_memo_shape,
)
from src.evaluator_gates.catalyst_memo_shape import (
    CatalystMemoShapeResult,
    validate_catalyst_memo_shape,
)
from src.evaluator_gates.cdd_memo_shape import (
    CDDMemoShapeResult,
    validate_cdd_memo_shape,
)
from src.evaluator_gates.tactical_envelope_shape import (
    TacticalEnvelopeShapeResult,
    validate_tactical_envelope_shape,
)
from src.evaluator_gates.intangibles_adjustment_shape import (
    IntangiblesAdjustmentResult,
    validate_intangibles_adjustment,
)


# Stable rule IDs used in audit rows + delta-prompts. The convention
# matches the existing HG-NN identifiers from the evaluator rubric.
GATE_IDS: dict[str, str] = {
    "envelope_shape":        "HG-23",
    "sentiment_degradation": "HG-24",
    "sizing_math":           "HG-25",
    "evidence_uuid_check":   "HG-26",
    "outside_view_blend":    "HG-27",
    "counterfactual_catalog": "HG-28",
    "quant_memo_shape":      "HG-29",
    "strategic_memo_shape":  "HG-30",
    "catalyst_memo_shape":   "HG-31",
    "cdd_memo_shape":        "HG-32",
    "tactical_envelope_shape": "HG-33",
    "intangibles_adjustment_shape": "HG-38",
}


# Canonical artifact types accepted by validate_all. Each maps to its
# own gate set; pm_envelope is the default for backward compatibility.
VALID_ARTIFACT_TYPES = (
    "pm_envelope",
    "quant_memo",
    "strategic_memo",
    "catalyst_memo",
    "cdd_memo",
    "tactical_envelope",
)


@dataclass
class GateOutcome:
    """One gate's outcome inside an aggregate result."""

    gate_id: str
    gate_name: str
    valid: bool
    result_dict: dict[str, Any]
    # ``error_fingerprint`` is the (gate_id, sorted-key-tuple-of-failures)
    # used by the agent_harness retry loop for stuck-loop detection.
    error_fingerprint: str | None = None


@dataclass
class AggregateValidationResult:
    """Aggregate of all gate outcomes for one envelope."""

    valid: bool
    artifact_path: str | None
    gates: list[GateOutcome] = field(default_factory=list)
    summary: dict[str, str] = field(default_factory=dict)
    # summary["envelope_shape"] = "pass" / "fail" / "skipped"

    def failed_gates(self) -> list[GateOutcome]:
        return [g for g in self.gates if not g.valid]

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "artifact_path": self.artifact_path,
            "summary": self.summary,
            "gates": [
                {
                    "gate_id": g.gate_id,
                    "gate_name": g.gate_name,
                    "valid": g.valid,
                    "error_fingerprint": g.error_fingerprint,
                    "result": g.result_dict,
                }
                for g in self.gates
            ],
        }


def _fingerprint_envelope_shape(r: EnvelopeShapeResult) -> str:
    parts = sorted(r.missing_top_level)
    parts += [f"subkey:{k}" for k in sorted(r.missing_subkeys)]
    parts += [f"forbidden:{f}" for f in sorted(r.forbidden_fields_present)]
    if r.invalid_summary_code is not None:
        parts.append(f"summary_code:{r.invalid_summary_code}")
    return "|".join(parts) if parts else "ok"


def _fingerprint_evidence(r: EvidenceUUIDResult) -> str:
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


def _fingerprint_outside_view(r: OutsideViewBlendResult) -> str:
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


def _fingerprint_sizing(r: SizingMathResult) -> str:
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


def _fingerprint_quant_memo(r: QuantMemoShapeResult) -> str:
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


def _fingerprint_strategic_memo(r: StrategicMemoShapeResult) -> str:
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


def _fingerprint_catalyst_memo(r: CatalystMemoShapeResult) -> str:
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


def _fingerprint_cdd_memo(r: CDDMemoShapeResult) -> str:
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


def _fingerprint_tactical_envelope(r: TacticalEnvelopeShapeResult) -> str:
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


def _fingerprint_intangibles(r: IntangiblesAdjustmentResult) -> str:
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


def _fingerprint_counterfactual(r: CounterfactualCatalogResult) -> str:
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


def _outcome(
    gate_name: str,
    valid: bool,
    result_dict: dict[str, Any],
    fingerprint: str,
) -> GateOutcome:
    # When the gate failed but the helper didn't populate any specific
    # fingerprint parts (e.g. missing-block + short-circuit return), use
    # a sentinel so stuck-loop detection still works. "ok" must never
    # appear on a failed outcome.
    fp = fingerprint
    if not valid and fp == "ok":
        fp = "generic_fail"
    return GateOutcome(
        gate_id=GATE_IDS[gate_name],
        gate_name=gate_name,
        valid=valid,
        result_dict=result_dict,
        error_fingerprint=fp if not valid else "ok",
    )


def _to_dict_safe(obj: Any) -> dict[str, Any]:
    """Convert a dataclass-result to dict for serialization."""
    if hasattr(obj, "__dict__"):
        out: dict[str, Any] = {}
        for k, v in obj.__dict__.items():
            if isinstance(v, (str, int, float, bool, type(None))):
                out[k] = v
            elif isinstance(v, (list, tuple)):
                out[k] = list(v)
            elif isinstance(v, dict):
                out[k] = v
            else:
                out[k] = str(v)
        return out
    return {"result": str(obj)}


def _validate_pm_envelope(
    env: dict[str, Any],
    *,
    resolve_evidence_db: bool,
    case_ids_for_counterfactual: list[str] | None,
    db_dsn: str | None,
    catalyst_indicators: list[dict] | None,
    strict_envelope_shape: bool,
) -> tuple[list[GateOutcome], dict[str, str]]:
    """Gate set for pm-supervisor envelopes (the original 6 gates)."""
    outcomes: list[GateOutcome] = []
    summary: dict[str, str] = {}

    shape = validate_envelope_shape(env, strict=strict_envelope_shape)
    outcomes.append(_outcome("envelope_shape", shape.valid, _to_dict_safe(shape), _fingerprint_envelope_shape(shape)))
    summary["envelope_shape"] = "pass" if shape.valid else "fail"

    refs = env.get("evidence_index_refs")
    ev = (
        validate_evidence_refs_with_db(refs, db_dsn=db_dsn)
        if resolve_evidence_db
        else validate_evidence_refs_syntactic(refs)
    )
    outcomes.append(_outcome("evidence_uuid_check", ev.valid, _to_dict_safe(ev), _fingerprint_evidence(ev)))
    summary["evidence_uuid_check"] = "pass" if ev.valid else "fail"

    ast_block = env.get("adversarial_stress_test") or {}
    ov = validate_outside_view_blend(ast_block)
    outcomes.append(_outcome("outside_view_blend", ov.valid, _to_dict_safe(ov), _fingerprint_outside_view(ov)))
    summary["outside_view_blend"] = "pass" if ov.valid else "fail"

    sm = validate_sizing_math(env)
    outcomes.append(_outcome("sizing_math", sm.valid, _to_dict_safe(sm), _fingerprint_sizing(sm)))
    summary["sizing_math"] = "pass" if sm.valid else "fail"

    cf = validate_counterfactual_top3(env, case_ids=case_ids_for_counterfactual, db_dsn=db_dsn)
    outcomes.append(_outcome("counterfactual_catalog", cf.valid, _to_dict_safe(cf), _fingerprint_counterfactual(cf)))
    summary["counterfactual_catalog"] = "pass" if cf.valid else "fail"

    if catalyst_indicators is not None:
        sd = compute_sentiment_data_degraded(catalyst_indicators)
        emitted = env.get("sentiment_data_degraded")
        matches = emitted is None or bool(emitted) == bool(sd.degraded)
        sd_dict = {
            "recomputed_degraded": sd.degraded,
            "emitted_degraded": emitted,
            "matches": matches,
            "n_unavailable": sd.n_unavailable,
            "threshold": sd.threshold,
            "unavailable_names": sd.unavailable_names,
            "notes": sd.notes,
        }
        outcomes.append(_outcome("sentiment_degradation", matches, sd_dict, "mismatch" if not matches else "ok"))
        summary["sentiment_degradation"] = "pass" if matches else "fail"
    else:
        summary["sentiment_degradation"] = "skipped"

    return outcomes, summary


def _validate_quant_memo(env: dict[str, Any], *, resolve_evidence_db: bool, db_dsn: str | None) -> tuple[list[GateOutcome], dict[str, str]]:
    """Gate set for quant memos: shape (HG-29) + evidence_index_refs UUIDs
    + intangibles_adjustment block (HG-38, Overlay 7)."""
    outcomes: list[GateOutcome] = []
    summary: dict[str, str] = {}

    shape = validate_quant_memo_shape(env)
    outcomes.append(_outcome("quant_memo_shape", shape.valid, _to_dict_safe(shape), _fingerprint_quant_memo(shape)))
    summary["quant_memo_shape"] = "pass" if shape.valid else "fail"

    refs = env.get("evidence_index_refs")
    ev = (
        validate_evidence_refs_with_db(refs, db_dsn=db_dsn)
        if resolve_evidence_db
        else validate_evidence_refs_syntactic(refs)
    )
    outcomes.append(_outcome("evidence_uuid_check", ev.valid, _to_dict_safe(ev), _fingerprint_evidence(ev)))
    summary["evidence_uuid_check"] = "pass" if ev.valid else "fail"

    # Outside-view blend math is also load-bearing in the quant memo
    # (the field lives directly on the memo, not nested under
    # adversarial_stress_test as it is for pm-envelopes).
    ov = validate_outside_view_blend(env.get("outside_view") or {})
    outcomes.append(_outcome("outside_view_blend", ov.valid, _to_dict_safe(ov), _fingerprint_outside_view(ov)))
    summary["outside_view_blend"] = "pass" if ov.valid else "fail"

    # HG-38: intangibles_adjustment block strict-schema validator
    # (Overlay 7, Mauboussin April 2025 / EPW 2024 industry rates).
    # Catches "SHADOW_MODE_NOT_COMPUTED_THIS_RUN" sentinel pattern and
    # other punted-computation cases observed in 2026-05-22 Step-3 sweep.
    ia = validate_intangibles_adjustment(env)
    outcomes.append(_outcome("intangibles_adjustment_shape", ia.valid, _to_dict_safe(ia), _fingerprint_intangibles(ia)))
    summary["intangibles_adjustment_shape"] = "pass" if ia.valid else "fail"

    return outcomes, summary


def _validate_strategic_memo(env: dict[str, Any], *, resolve_evidence_db: bool, db_dsn: str | None) -> tuple[list[GateOutcome], dict[str, str]]:
    """Gate set for strategic memos: shape (HG-30) + evidence_index_refs UUIDs."""
    outcomes: list[GateOutcome] = []
    summary: dict[str, str] = {}

    shape = validate_strategic_memo_shape(env)
    outcomes.append(_outcome("strategic_memo_shape", shape.valid, _to_dict_safe(shape), _fingerprint_strategic_memo(shape)))
    summary["strategic_memo_shape"] = "pass" if shape.valid else "fail"

    refs = env.get("evidence_index_refs")
    ev = (
        validate_evidence_refs_with_db(refs, db_dsn=db_dsn)
        if resolve_evidence_db
        else validate_evidence_refs_syntactic(refs)
    )
    outcomes.append(_outcome("evidence_uuid_check", ev.valid, _to_dict_safe(ev), _fingerprint_evidence(ev)))
    summary["evidence_uuid_check"] = "pass" if ev.valid else "fail"

    return outcomes, summary


def _validate_catalyst_memo(env: dict[str, Any], *, resolve_evidence_db: bool, db_dsn: str | None) -> tuple[list[GateOutcome], dict[str, str]]:
    """Gate set for catalyst-scout memos: shape (HG-31) + evidence UUIDs.

    sentiment_data_degraded cross-check is performed inside the shape
    validator itself since the sentiment_signals list is right there.
    """
    outcomes: list[GateOutcome] = []
    summary: dict[str, str] = {}

    shape = validate_catalyst_memo_shape(env)
    outcomes.append(_outcome("catalyst_memo_shape", shape.valid, _to_dict_safe(shape), _fingerprint_catalyst_memo(shape)))
    summary["catalyst_memo_shape"] = "pass" if shape.valid else "fail"

    refs = env.get("evidence_index_refs")
    ev = (
        validate_evidence_refs_with_db(refs, db_dsn=db_dsn)
        if resolve_evidence_db
        else validate_evidence_refs_syntactic(refs)
    )
    outcomes.append(_outcome("evidence_uuid_check", ev.valid, _to_dict_safe(ev), _fingerprint_evidence(ev)))
    summary["evidence_uuid_check"] = "pass" if ev.valid else "fail"

    return outcomes, summary


def _validate_cdd_memo(env: dict[str, Any]) -> tuple[list[GateOutcome], dict[str, str]]:
    """Gate set for CDD integrated memos: shape (HG-32). No UUID check —
    the CDD memo carries `evidence_index_rows_added` (a count), not a
    UUID array; UUIDs live on the contributing analyst memos."""
    outcomes: list[GateOutcome] = []
    summary: dict[str, str] = {}

    shape = validate_cdd_memo_shape(env)
    outcomes.append(_outcome("cdd_memo_shape", shape.valid, _to_dict_safe(shape), _fingerprint_cdd_memo(shape)))
    summary["cdd_memo_shape"] = "pass" if shape.valid else "fail"

    return outcomes, summary


def _validate_tactical_envelope(env: dict[str, Any]) -> tuple[list[GateOutcome], dict[str, str]]:
    """Gate set for tactical-overlay envelopes: shape only (HG-33).

    INV-2.1-A enforcement lives in the shape validator: canonical BUY/TRIM/SELL
    in cell_disposition is rejected (must be one of BUY-HIGH/BUY-MED/HOLD/AVOID).
    No UUID check (tactical-overlay does not own evidence_index rows; its
    frameworks_cited list is a static label, not a UUID array).
    """
    outcomes: list[GateOutcome] = []
    summary: dict[str, str] = {}

    shape = validate_tactical_envelope_shape(env)
    outcomes.append(_outcome(
        "tactical_envelope_shape",
        shape.valid,
        _to_dict_safe(shape),
        _fingerprint_tactical_envelope(shape),
    ))
    summary["tactical_envelope_shape"] = "pass" if shape.valid else "fail"

    return outcomes, summary


def validate_all(
    envelope: dict[str, Any] | str | Path,
    *,
    artifact_type: str = "pm_envelope",
    resolve_evidence_db: bool = False,
    case_ids_for_counterfactual: list[str] | None = None,
    db_dsn: str | None = None,
    catalyst_indicators: list[dict] | None = None,
    strict_envelope_shape: bool = False,
) -> AggregateValidationResult:
    """Run the gate set appropriate to ``artifact_type``.

    Args:
        envelope: parsed dict, or path-like to a JSON file.
        artifact_type: one of {pm_envelope, quant_memo, strategic_memo,
            catalyst_memo, cdd_memo}. Defaults to pm_envelope for
            backward compatibility.
        resolve_evidence_db: HG-26 DB resolution check.
        case_ids_for_counterfactual: case_ids for HG-28 catalog check
            (pm_envelope only).
        db_dsn: Postgres DSN passthrough.
        catalyst_indicators: HG-24 cross-check (pm_envelope only).
        strict_envelope_shape: HG-23 strict mode (pm_envelope only).

    Returns:
        AggregateValidationResult with one GateOutcome per gate. The
        ``valid`` field is True iff every gate passed.

    Raises:
        ValueError: if artifact_type is not in VALID_ARTIFACT_TYPES.
    """
    if artifact_type not in VALID_ARTIFACT_TYPES:
        raise ValueError(
            f"artifact_type={artifact_type!r} not in {VALID_ARTIFACT_TYPES}"
        )

    artifact_path: str | None = None
    env: dict[str, Any]
    if isinstance(envelope, (str, Path)):
        artifact_path = str(envelope)
        with open(envelope, "r", encoding="utf-8") as f:
            env = json.load(f)
    elif isinstance(envelope, dict):
        env = envelope
    else:
        raise TypeError(
            f"envelope must be dict or path; got {type(envelope).__name__}"
        )

    if artifact_type == "pm_envelope":
        outcomes, summary = _validate_pm_envelope(
            env,
            resolve_evidence_db=resolve_evidence_db,
            case_ids_for_counterfactual=case_ids_for_counterfactual,
            db_dsn=db_dsn,
            catalyst_indicators=catalyst_indicators,
            strict_envelope_shape=strict_envelope_shape,
        )
    elif artifact_type == "quant_memo":
        outcomes, summary = _validate_quant_memo(
            env, resolve_evidence_db=resolve_evidence_db, db_dsn=db_dsn
        )
    elif artifact_type == "strategic_memo":
        outcomes, summary = _validate_strategic_memo(
            env, resolve_evidence_db=resolve_evidence_db, db_dsn=db_dsn
        )
    elif artifact_type == "catalyst_memo":
        outcomes, summary = _validate_catalyst_memo(
            env, resolve_evidence_db=resolve_evidence_db, db_dsn=db_dsn
        )
    elif artifact_type == "cdd_memo":
        outcomes, summary = _validate_cdd_memo(env)
    elif artifact_type == "tactical_envelope":
        outcomes, summary = _validate_tactical_envelope(env)
    else:  # pragma: no cover — guarded above
        raise AssertionError("unreachable artifact_type branch")

    overall_valid = all(o.valid for o in outcomes)
    return AggregateValidationResult(
        valid=overall_valid,
        artifact_path=artifact_path,
        gates=outcomes,
        summary=summary,
    )



def _cli(argv: list[str] | None = None) -> int:
    """CLI wrapper for the aggregate validator.

    Exit codes:
      0 all gates passed
      1 one or more gates failed
      2 unparseable input
    """
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="validate_all",
        description=(
            "Run every Tier-1 gate (HG-23/24/25/26/27/28) against a "
            "pm-supervisor envelope. Exit 0 valid, 1 invalid, 2 unparseable."
        ),
    )
    parser.add_argument(
        "--envelope",
        required=True,
        help="path to envelope/memo JSON file",
    )
    parser.add_argument(
        "--artifact-type",
        default="pm_envelope",
        choices=VALID_ARTIFACT_TYPES,
        help="which gate set to run (default pm_envelope for backward compat)",
    )
    parser.add_argument(
        "--resolve-evidence-db",
        action="store_true",
        help="also check evidence_index_refs resolve in evidence_index table",
    )
    parser.add_argument(
        "--case-ids",
        default=None,
        help="comma-separated case_ids for counterfactual catalog check",
    )
    parser.add_argument(
        "--catalyst-indicators",
        default=None,
        help="path to JSON file with catalyst-scout §4 indicators",
    )
    parser.add_argument(
        "--db-dsn",
        default=None,
    )
    parser.add_argument(
        "--strict-shape",
        action="store_true",
        help="strict envelope-shape validation (report.* row subkeys)",
    )
    args = parser.parse_args(argv)

    try:
        with open(args.envelope, "r", encoding="utf-8") as f:
            env = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"unable to read/parse envelope: {exc}\n")
        return 2

    case_ids: list[str] | None = None
    if args.case_ids:
        case_ids = [c.strip() for c in args.case_ids.split(",") if c.strip()]

    indicators: list[dict] | None = None
    if args.catalyst_indicators:
        try:
            with open(args.catalyst_indicators, "r", encoding="utf-8") as f:
                parsed = json.load(f)
            if isinstance(parsed, list):
                indicators = parsed
            elif isinstance(parsed, dict) and isinstance(
                parsed.get("indicators"), list
            ):
                indicators = parsed["indicators"]
        except (OSError, json.JSONDecodeError) as exc:
            sys.stderr.write(
                f"unable to read catalyst indicators: {exc}\n"
            )
            return 2

    result = validate_all(
        env,
        artifact_type=args.artifact_type,
        resolve_evidence_db=args.resolve_evidence_db,
        case_ids_for_counterfactual=case_ids,
        db_dsn=args.db_dsn,
        catalyst_indicators=indicators,
        strict_envelope_shape=args.strict_shape,
    )
    sys.stdout.write(json.dumps(result.to_dict(), indent=2, default=str) + "\n")
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(_cli())


__all__ = [
    "AggregateValidationResult",
    "GateOutcome",
    "GATE_IDS",
    "validate_all",
]
