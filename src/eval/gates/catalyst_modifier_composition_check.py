"""Catalyst+flow modifier composition determinism gate (HG-34 — v0.2).

The v0.1 pm-supervisor §6 catalyst_modifier_applied audit string is
DETERMINISTIC by spec: pm-supervisor must invoke
``src.supervisor.catalyst_flow_modifier.compose_catalyst_flow_modifier()``
and emit its returned ``audit_string`` verbatim. No LLM judgment in the
composition arithmetic — that was the v0.1 /review-me iter 2 BLOCKER fix
(unit confusion + LLM-arithmetic drift were architecturally eliminated by
the pure-function helper).

THIS GATE catches drift: re-derives the expected ``audit_string`` from the
upstream envelopes + parameters snapshot + the same helper function, and
rejects pm-supervisor emissions where the observed string diverges from
expected. Bit-identical comparison — drift in any character flags as fail.

DETERMINISM: pure Python; no I/O beyond CLI stdin/stdout/files; no LLM.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Any, Optional

# Import the v0.1 helper — single source of truth for the composition formula.
from src.supervisor.catalyst_flow_modifier import (
    compose_catalyst_flow_modifier,
)


@dataclass
class CatalystModifierCompositionResult:
    """Result envelope for the composition-determinism check.

    Named field-lists let the evaluator_gates aggregate dispatch produce a
    deterministic stuck-loop signature (mirrors SentimentDegradationResult
    + TacticalEnvelopeShapeResult patterns).
    """

    valid: bool
    audit_string_expected: Optional[str] = None
    audit_string_observed: Optional[str] = None
    missing_inputs: list[str] = field(default_factory=list)
    invalid_inputs: list[str] = field(default_factory=list)
    drift_detected: bool = False
    drift_summary: Optional[str] = None
    notes: list[str] = field(default_factory=list)


def _extract_catalyst_inputs(catalyst_env: dict) -> tuple[int, Optional[str], bool, bool, str]:
    """Pull the load-bearing fields from catalyst-scout envelope.

    Returns: (direction, magnitude, tier_insufficient, sentiment_data_degraded, reason).
    Raises KeyError on missing required structure.
    """
    cm = catalyst_env.get("conviction_modifier") or {}
    direction = cm.get("direction")
    if not isinstance(direction, int):
        # Some agents emit "+1" / "-1" as strings; coerce.
        try:
            direction = int(direction)
        except (TypeError, ValueError):
            raise KeyError("catalyst_env.conviction_modifier.direction missing or non-int")
    magnitude = cm.get("magnitude")  # may be None when direction == 0
    reason = cm.get("reason") or ""

    positioning = catalyst_env.get("positioning") or {}
    tier_insufficient = bool(positioning.get("tier_insufficient", False))
    sentiment_data_degraded = bool(catalyst_env.get("sentiment_data_degraded", False))

    return direction, magnitude, tier_insufficient, sentiment_data_degraded, reason


def _extract_flow_signal_bin(flow_env: Optional[dict]) -> str:
    """Pull flow_signal_bin from flow-overlay envelope; default 'offline' if None."""
    if flow_env is None:
        return "offline"
    bin_ = flow_env.get("flow_signal_bin")
    if bin_ is None:
        return "offline"
    return str(bin_)


def _extract_pm_audit_string(pm_env: dict) -> Optional[str]:
    """Pull the emitted catalyst_modifier_applied from pm-supervisor envelope."""
    val = pm_env.get("catalyst_modifier_applied")
    if val is None:
        return None
    return str(val)


def _extract_pm_base_midpoint(pm_env: dict) -> Optional[float]:
    """Pull the base midpoint from pm-supervisor envelope (size_band before modifier).

    The composition helper requires base_midpoint_pp as input. pm-supervisor
    emits the final size_band (after modifier); we need to retrieve the
    pre-modifier midpoint. Per pm-supervisor.md §6 contract, this is preserved
    in the audit trail — look for it in `size_band_pre_modifier_midpoint_pp`
    or fall back to deriving from size_band midpoint + emitted modifier value.
    """
    val = pm_env.get("size_band_pre_modifier_midpoint_pp")
    if val is not None:
        try:
            return float(val)
        except (TypeError, ValueError):
            return None
    # Fallback: try sizing.base_midpoint_pp (alternative emission field)
    sizing = pm_env.get("sizing") or {}
    val = sizing.get("base_midpoint_pp")
    if val is not None:
        try:
            return float(val)
        except (TypeError, ValueError):
            return None
    return None


def validate_catalyst_modifier_composition(
    catalyst_env: Optional[dict],
    flow_env: Optional[dict],
    pm_env: dict,
    parameters_active_snapshot: dict[str, Any],
) -> CatalystModifierCompositionResult:
    """Re-derive expected audit_string, compare to pm-supervisor's emission.

    Args:
        catalyst_env: catalyst-scout envelope dict (read from
            memos/envelopes/catalyst-scout__<run_id>.json). May be None if
            catalyst-scout was offline — then modifier MUST be "0 (catalyst-scout offline)".
        flow_env: flow-overlay envelope dict (read from
            memos/envelopes/flow-overlay__<run_id>.json). May be None — then
            flow_signal_bin treated as "offline".
        pm_env: pm-supervisor envelope dict (required).
        parameters_active_snapshot: dict from run_parameters_snapshot — must
            contain the load-bearing sizing.* keys with INTEGER-PERCENT values.

    Returns:
        CatalystModifierCompositionResult with valid + diagnostic fields.
    """
    result = CatalystModifierCompositionResult(valid=True)

    # --- Validate inputs presence ---
    observed_audit = _extract_pm_audit_string(pm_env)
    if observed_audit is None:
        result.missing_inputs.append("pm_env.catalyst_modifier_applied")
        result.valid = False
        return result
    result.audit_string_observed = observed_audit

    base_midpoint_pp = _extract_pm_base_midpoint(pm_env)
    if base_midpoint_pp is None:
        result.missing_inputs.append("pm_env.size_band_pre_modifier_midpoint_pp")
        result.notes.append(
            "Cannot re-derive without pre-modifier base midpoint. "
            "pm-supervisor must surface size_band_pre_modifier_midpoint_pp in its emission "
            "for HG-34 to verify composition determinism."
        )
        result.valid = False
        return result

    # --- Special case: catalyst-scout offline → modifier MUST be "0 (catalyst-scout offline)" ---
    if catalyst_env is None:
        expected = "0 (catalyst-scout offline)"
        result.audit_string_expected = expected
        if observed_audit.strip() != expected:
            result.valid = False
            result.drift_detected = True
            result.drift_summary = (
                f"catalyst-scout offline: expected exactly {expected!r}; "
                f"observed {observed_audit!r}"
            )
        return result

    # --- Extract inputs from upstream envelopes ---
    try:
        (
            catalyst_direction,
            catalyst_magnitude,
            tier_insufficient,
            sentiment_data_degraded,
            catalyst_reason,
        ) = _extract_catalyst_inputs(catalyst_env)
    except KeyError as exc:
        result.invalid_inputs.append(f"catalyst_env: {exc}")
        result.valid = False
        return result

    flow_signal_bin = _extract_flow_signal_bin(flow_env)

    # --- Pull parameters with /100 conversion (per v0.1 INV-CFM-UNIT) ---
    try:
        raw_low = float(parameters_active_snapshot["sizing.catalyst_modifier_magnitude_scaler.low"])
        raw_med = float(parameters_active_snapshot["sizing.catalyst_modifier_magnitude_scaler.medium"])
        raw_high = float(parameters_active_snapshot["sizing.catalyst_modifier_magnitude_scaler.high"])
        raw_flow_pp = float(parameters_active_snapshot["sizing.flow_modifier_pp_per_unit"])
        raw_bound_full = float(parameters_active_snapshot["sizing.catalyst_modifier_bound.full_pct"])
        raw_bound_shrunk = float(parameters_active_snapshot["sizing.catalyst_modifier_bound.shrunk_pct"])
    except (KeyError, TypeError, ValueError) as exc:
        result.invalid_inputs.append(f"parameters_active_snapshot: {exc}")
        result.valid = False
        return result

    # Bound shrinks if EITHER data-quality flag is true (OR logic per pm-supervisor.md §6)
    if tier_insufficient or sentiment_data_degraded:
        bound_pct = raw_bound_shrunk / 100.0
    else:
        bound_pct = raw_bound_full / 100.0

    # --- Re-compute via the v0.1 helper ---
    try:
        recomputed = compose_catalyst_flow_modifier(
            base_midpoint_pp=base_midpoint_pp,
            catalyst_direction=catalyst_direction,
            catalyst_magnitude=catalyst_magnitude,
            catalyst_magnitude_scaler={
                "low": raw_low / 100.0,
                "medium": raw_med / 100.0,
                "high": raw_high / 100.0,
            },
            flow_signal_bin=flow_signal_bin,
            flow_per_unit_pct=raw_flow_pp / 100.0,
            bound_pct=bound_pct,
            catalyst_reason=catalyst_reason,
        )
    except ValueError as exc:
        result.invalid_inputs.append(f"compose_catalyst_flow_modifier raised: {exc}")
        result.valid = False
        return result

    expected_audit = recomputed.audit_string
    result.audit_string_expected = expected_audit

    # --- Bit-identical comparison ---
    if observed_audit != expected_audit:
        result.valid = False
        result.drift_detected = True
        result.drift_summary = (
            "audit_string drift between pm-supervisor emission and "
            "deterministic re-derivation via compose_catalyst_flow_modifier"
        )

    return result


def _result_to_dict(r: CatalystModifierCompositionResult) -> dict:
    return {
        "valid": r.valid,
        "audit_string_expected": r.audit_string_expected,
        "audit_string_observed": r.audit_string_observed,
        "missing_inputs": r.missing_inputs,
        "invalid_inputs": r.invalid_inputs,
        "drift_detected": r.drift_detected,
        "drift_summary": r.drift_summary,
        "notes": r.notes,
    }


def _load_json_or_none(path: Optional[str]) -> Optional[dict]:
    """Read a JSON file; return None if path is None/empty/"none"/"null"."""
    if not path or path.lower() in ("none", "null", ""):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _cli(argv: list[str] | None = None) -> int:
    """CLI wrapper. Exit 0 valid, 1 invalid, 2 unparseable.

    Args:
      --catalyst-env: path to catalyst-scout envelope JSON (or "none" if offline)
      --flow-env: path to flow-overlay envelope JSON (or "none" if absent)
      --pm-env: path to pm-supervisor envelope JSON (REQUIRED)
      --params-snapshot: path to parameters_active snapshot JSON (REQUIRED)
        Expected shape: flat dict {parameter_key: value} for the load-bearing
        sizing.catalyst_modifier_magnitude_scaler.{low,medium,high},
        sizing.flow_modifier_pp_per_unit, sizing.catalyst_modifier_bound.{full,shrunk}_pct keys.
    """
    parser = argparse.ArgumentParser(
        prog="catalyst_modifier_composition_check",
        description=(
            "Re-derive pm-supervisor.catalyst_modifier_applied from upstream "
            "envelopes via compose_catalyst_flow_modifier() and reject on drift. "
            "Exit 0 on valid (no drift), 1 on drift detected, 2 on unparseable input."
        ),
    )
    parser.add_argument("--catalyst-env", default=None, help='path to catalyst-scout envelope JSON, "none" if offline')
    parser.add_argument("--flow-env", default=None, help='path to flow-overlay envelope JSON, "none" if offline')
    parser.add_argument("--pm-env", required=True, help="path to pm-supervisor envelope JSON")
    parser.add_argument("--params-snapshot", required=True, help="path to parameters_active snapshot JSON")
    args = parser.parse_args(argv)

    try:
        catalyst_env = _load_json_or_none(args.catalyst_env)
        flow_env = _load_json_or_none(args.flow_env)
        pm_env = _load_json_or_none(args.pm_env)
        if pm_env is None:
            sys.stderr.write("--pm-env is required and must be a valid path\n")
            return 2
        params_snapshot = _load_json_or_none(args.params_snapshot)
        if params_snapshot is None:
            sys.stderr.write("--params-snapshot is required and must be a valid path\n")
            return 2
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"unable to read/parse input: {exc}\n")
        return 2

    result = validate_catalyst_modifier_composition(
        catalyst_env=catalyst_env,
        flow_env=flow_env,
        pm_env=pm_env,
        parameters_active_snapshot=params_snapshot,
    )
    sys.stdout.write(json.dumps(_result_to_dict(result), indent=2) + "\n")
    return 0 if result.valid else 1


if __name__ == "__main__":
    sys.exit(_cli())


__all__ = [
    "CatalystModifierCompositionResult",
    "validate_catalyst_modifier_composition",
]
