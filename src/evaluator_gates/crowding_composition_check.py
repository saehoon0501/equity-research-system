"""Crowding warning composition determinism gate (HG-35 — v0.3).

The v0.3 flow-overlay emits a `components.crowding.warning` boolean that is
DETERMINISTIC by spec: warning=True IFF (per logic_operator) two threshold
breaches hold simultaneously (AND) or independently (OR), and IFF the data
is not stale. No LLM judgment in the classification arithmetic — the
pure-function helper
``src.p9_flow_overlay.crowding_classifier.classify_crowding()`` is the
single source of truth.

THIS GATE catches drift: re-derives the expected ``warning`` boolean from
the emitted ``days_to_cover`` + ``short_pct_float`` + ``settlement_date`` +
parameters snapshot, and rejects flow-overlay emissions where the observed
boolean diverges. Bit-identical comparison.

Invariants enforced:
  - INV-CRD-1: warning=True IFF (per logic_operator) both thresholds breached
  - INV-CRD-2: warning=False whenever unavailable_reason is non-null (fail-safe)
  - INV-CRD-3: stale=True implies warning=False

DETERMINISM: pure Python; no I/O beyond CLI stdin/stdout/files; no LLM.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional


_REQUIRED_PARAM_KEYS = (
    "flow.crowding_days_to_cover_threshold",
    "flow.crowding_short_pct_float_threshold",
    "flow.crowding_logic_operator",
    "flow.crowding_stale_data_max_days",
)


@dataclass
class CrowdingCompositionResult:
    """Result envelope for the HG-35 composition-determinism check.

    Named field-lists let evaluator_gates aggregate dispatch produce a
    deterministic stuck-loop signature (mirrors CatalystModifierCompositionResult).
    """

    valid: bool
    warning_expected: Optional[bool] = None
    warning_observed: Optional[bool] = None
    missing_inputs: list[str] = field(default_factory=list)
    invalid_inputs: list[str] = field(default_factory=list)
    invariant_violations: list[str] = field(default_factory=list)
    drift_detected: bool = False
    drift_summary: Optional[str] = None
    notes: list[str] = field(default_factory=list)


def _get_crowding_block(flow_env: Optional[dict]) -> Optional[dict]:
    if flow_env is None:
        return None
    components = flow_env.get("components") or {}
    crowding = components.get("crowding")
    if not isinstance(crowding, dict):
        return None
    return crowding


def _coerce_logic_operator(raw: Any) -> Optional[str]:
    if not isinstance(raw, str):
        return None
    raw = raw.strip().upper()
    if raw not in ("AND", "OR"):
        return None
    return raw


def _parse_iso_date(raw: Any) -> Optional[date]:
    if raw is None:
        return None
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None


def validate_crowding_composition(
    flow_env: Optional[dict],
    parameters_active_snapshot: dict[str, Any],
    as_of: Optional[date] = None,
) -> CrowdingCompositionResult:
    """Re-derive expected `warning`, compare to flow-overlay's emission.

    Args:
        flow_env: flow-overlay envelope dict. If None or `components.crowding`
            is absent, the gate is NOT-APPLICABLE-FOR-OUTPUT-TYPE (valid=True,
            note explains why).
        parameters_active_snapshot: dict with the load-bearing
            `flow.crowding_*` keys (INTEGER-PERCENT not applicable — these
            are stored as their natural units: float threshold, float fraction,
            string operator, int days).
        as_of: anchor date for staleness check; if None, treats stale-check
            as informational only (warning still re-derived from emitted
            `stale` flag).

    Returns:
        CrowdingCompositionResult with valid + diagnostic fields.
    """
    result = CrowdingCompositionResult(valid=True)

    crowding = _get_crowding_block(flow_env)
    if crowding is None:
        result.notes.append(
            "components.crowding absent — gate NOT-APPLICABLE-FOR-OUTPUT-TYPE; "
            "v0.1/v0.2 envelopes without crowding sub-signal validate as PASS by skip."
        )
        return result

    # --- Pull emission ---
    warning_observed = crowding.get("warning")
    if not isinstance(warning_observed, bool):
        result.missing_inputs.append("flow_env.components.crowding.warning")
        result.valid = False
        return result
    result.warning_observed = warning_observed

    days_to_cover = crowding.get("days_to_cover")
    short_pct_float = crowding.get("short_pct_float")
    stale = bool(crowding.get("stale", False))
    unavailable_reason = crowding.get("unavailable_reason")

    # --- Pull parameters ---
    try:
        params = {k: parameters_active_snapshot[k] for k in _REQUIRED_PARAM_KEYS}
    except KeyError as exc:
        result.missing_inputs.append(f"parameters_active_snapshot: {exc}")
        result.valid = False
        return result

    try:
        dtc_threshold = float(params["flow.crowding_days_to_cover_threshold"])
        spf_threshold = float(params["flow.crowding_short_pct_float_threshold"])
        logic_op = _coerce_logic_operator(params["flow.crowding_logic_operator"])
        stale_max = int(params["flow.crowding_stale_data_max_days"])
    except (TypeError, ValueError) as exc:
        result.invalid_inputs.append(f"parameter coercion: {exc}")
        result.valid = False
        return result

    if logic_op is None:
        result.invalid_inputs.append(
            "flow.crowding_logic_operator must be 'AND' or 'OR'"
        )
        result.valid = False
        return result

    # --- INV-CRD-2: warning=False whenever unavailable_reason is non-null ---
    if unavailable_reason is not None and warning_observed is True:
        result.invariant_violations.append(
            f"INV-CRD-2: warning={warning_observed} but unavailable_reason={unavailable_reason!r} "
            "(fail-safe contract: any unavailable_reason must force warning=False)"
        )
        result.valid = False

    # --- INV-CRD-3: stale=True implies warning=False ---
    if stale and warning_observed is True:
        result.invariant_violations.append(
            "INV-CRD-3: stale=True but warning=True (fail-safe contract: "
            "stale data must force warning=False)"
        )
        result.valid = False

    # --- INV-CRD-1: re-derive warning from numeric inputs + thresholds ---
    if unavailable_reason is None and not stale:
        if days_to_cover is None or short_pct_float is None:
            result.invariant_violations.append(
                "INV-CRD-1: unavailable_reason=None and stale=False but "
                "days_to_cover or short_pct_float is None (incoherent emission)"
            )
            result.valid = False
            return result

        try:
            dtc_breach = float(days_to_cover) >= dtc_threshold
            spf_breach = float(short_pct_float) >= spf_threshold
        except (TypeError, ValueError) as exc:
            result.invalid_inputs.append(f"numeric coercion: {exc}")
            result.valid = False
            return result

        if logic_op == "AND":
            expected = dtc_breach and spf_breach
        else:
            expected = dtc_breach or spf_breach

        result.warning_expected = expected

        if expected != warning_observed:
            result.drift_detected = True
            result.valid = False
            result.drift_summary = (
                f"warning drift: re-derivation expected={expected} but observed={warning_observed} "
                f"(days_to_cover={days_to_cover} vs threshold={dtc_threshold}; "
                f"short_pct_float={short_pct_float} vs threshold={spf_threshold}; "
                f"logic_operator={logic_op})"
            )
    else:
        # unavailable or stale: expected is False per INV-CRD-2/3
        result.warning_expected = False

    # Optional staleness anchor check (informational; doesn't fail the gate
    # by itself — the emitter's `stale` flag is what the invariants enforce).
    if as_of is not None and not stale and crowding.get("settlement_date"):
        settle = _parse_iso_date(crowding.get("settlement_date"))
        if settle is not None:
            age = (as_of - settle).days
            if age > stale_max:
                result.notes.append(
                    f"settlement_date age={age}d exceeds stale_max={stale_max}d but "
                    "emitter did not flag stale=True; informational only (HG-35 trusts "
                    "the emitter's stale flag per INV-CRD-3)."
                )

    return result


def _result_to_dict(r: CrowdingCompositionResult) -> dict:
    return {
        "valid": r.valid,
        "warning_expected": r.warning_expected,
        "warning_observed": r.warning_observed,
        "missing_inputs": r.missing_inputs,
        "invalid_inputs": r.invalid_inputs,
        "invariant_violations": r.invariant_violations,
        "drift_detected": r.drift_detected,
        "drift_summary": r.drift_summary,
        "notes": r.notes,
    }


def _load_json_or_none(path: Optional[str]) -> Optional[dict]:
    if not path or path.lower() in ("none", "null", ""):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _cli(argv: list[str] | None = None) -> int:
    """CLI wrapper. Exit 0 valid, 1 invalid, 2 unparseable.

    Args:
      --flow-env: path to flow-overlay envelope JSON (or "none"). If the
        envelope lacks components.crowding, gate is NOT-APPLICABLE.
      --params-snapshot: path to parameters_active snapshot JSON (REQUIRED).
      --as-of: optional ISO date for staleness anchor check.
    """
    parser = argparse.ArgumentParser(
        prog="crowding_composition_check",
        description=(
            "Re-derive flow-overlay.components.crowding.warning from emitted "
            "numerics + parameters and reject on drift. Exit 0 on valid (no "
            "drift), 1 on drift / invariant violation, 2 on unparseable input."
        ),
    )
    parser.add_argument("--flow-env", required=True, help='path to flow-overlay envelope JSON, "none" if absent')
    parser.add_argument("--params-snapshot", required=True, help="path to parameters_active snapshot JSON")
    parser.add_argument("--as-of", default=None, help="optional ISO date for staleness anchor check")
    args = parser.parse_args(argv)

    try:
        flow_env = _load_json_or_none(args.flow_env)
        params_snapshot = _load_json_or_none(args.params_snapshot)
        if params_snapshot is None:
            sys.stderr.write("--params-snapshot is required and must be a valid path\n")
            return 2
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"unable to read/parse input: {exc}\n")
        return 2

    as_of = None
    if args.as_of:
        try:
            as_of = date.fromisoformat(args.as_of)
        except ValueError:
            sys.stderr.write(f"--as-of must be ISO date (YYYY-MM-DD); got {args.as_of!r}\n")
            return 2

    result = validate_crowding_composition(
        flow_env=flow_env,
        parameters_active_snapshot=params_snapshot,
        as_of=as_of,
    )
    sys.stdout.write(json.dumps(_result_to_dict(result), indent=2) + "\n")
    return 0 if result.valid else 1


if __name__ == "__main__":
    sys.exit(_cli())


__all__ = [
    "CrowdingCompositionResult",
    "validate_crowding_composition",
]
