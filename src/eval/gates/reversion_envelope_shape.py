"""Mean-reversion-overlay JSON envelope shape validator (HG-36, v0.4.0).

Mirrors src/eval/gates/flow_envelope_shape.py at structural level.
Exposes a ReversionEnvelopeShapeResult dataclass with named field-lists so
the evaluator_gates aggregate dispatch can fingerprint stuck-loops correctly.

Validates the structured envelope emitted by the mean-reversion-overlay agent
(.claude/agents/overlays/mean-reversion-overlay.md). Catches:
- Missing top-level keys.
- Invalid reversion_signal_bin enum value
  (must be MR_OVERSOLD/MR_NEUTRAL/MR_OVERBOUGHT/MR_UNAVAILABLE).
- Missing unavailable_reason when bin == 'MR_UNAVAILABLE'.
- Invalid audit_mode enum (must be 'standalone' | 'snapshot').
- audit_mode='snapshot' missing parameters_version_max or effective_parameters_hash.
- audit_mode='standalone' presenting parameters_version_max or effective_parameters_hash
  (those fields MUST be absent in standalone mode).
- reversion_cell != null (v0.4.0 NEVER populates this field; it's a forward-compat
  placeholder for v0.4.2's pm-supervisor wiring).
- INV-3.6-A: unavailable_reason != None IFF bin == 'MR_UNAVAILABLE'.
- INV-3.6-B: MR_OVERSOLD requires drawdown+rsi+bollinger_lower all True;
             MR_OVERBOUGHT requires rsi_overbought+bollinger_upper all True
             (ma_distance fire is checked at components level, not in sub_signal_fires).

DETERMINISM: pure stdlib. No I/O beyond CLI stdin/stdout.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field

REVERSION_BIN_VALUES: frozenset[str] = frozenset(
    {"MR_OVERSOLD", "MR_NEUTRAL", "MR_OVERBOUGHT", "MR_UNAVAILABLE"}
)

AUDIT_MODE_VALUES: frozenset[str] = frozenset({"standalone", "snapshot"})

UNAVAILABLE_REASON_VALUES: frozenset[str] = frozenset(
    {
        "insufficient_price_history",
        "corrupt_price_data",
    }
)

REQUIRED_TOP_LEVEL: tuple[str, ...] = (
    "ticker",
    "as_of_date",
    "run_id",
    "reversion_signal_bin",
    "audit_mode",
    "reversion_cell",
    "frameworks_cited",
)

REQUIRED_COMPONENTS_KEYS: tuple[str, ...] = (
    "drawdown_from_252d_high_pct",
    "rsi_14",
    "bollinger_band_position",
    "ma_distance_200d_pct",
    "252d_high",
    "prior_close",
)

REQUIRED_SUB_SIGNAL_FIRES: tuple[str, ...] = (
    "drawdown_threshold",
    "rsi_oversold",
    "rsi_overbought",
    "bollinger_lower_extreme",
    "bollinger_upper_extreme",
)

UUID_REGEX = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
SHA256_REGEX = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)


@dataclass
class ReversionEnvelopeShapeResult:
    """Result envelope mirroring FlowEnvelopeShapeResult shape.

    Named field-lists let _fingerprint produce a deterministic
    stuck-loop signature for the evaluator_gates aggregate dispatch.
    """

    valid: bool
    missing_top_level: list[str] = field(default_factory=list)
    invalid_enum_values: list[str] = field(default_factory=list)
    invalid_audit_mode: str | None = None
    audit_mode_field_violations: list[str] = field(default_factory=list)
    reversion_cell_non_null: bool = False  # v0.4.0 NEVER populates
    missing_unavailable_reason: bool = False
    invalid_unavailable_reason: str | None = None
    missing_components_keys: list[str] = field(default_factory=list)
    missing_sub_signal_fires: list[str] = field(default_factory=list)
    inv_3_6_a_violation: bool = False  # bin==UNAVAILABLE iff reason!=None
    inv_3_6_b_violation: list[str] = field(default_factory=list)  # bin=OVERSOLD/OVERBOUGHT need fires
    notes: list[str] = field(default_factory=list)


def validate_reversion_envelope_shape(env: object) -> ReversionEnvelopeShapeResult:
    """Validate mean-reversion-overlay envelope against v0.4.0 schema.

    Accepts a dict (typical) or any object (returns invalid + note for wrong type).
    """
    if not isinstance(env, dict):
        return ReversionEnvelopeShapeResult(
            valid=False,
            notes=[f"envelope must be dict; got {type(env).__name__}"],
        )

    result = ReversionEnvelopeShapeResult(valid=True)

    # 1. Top-level presence
    for key in REQUIRED_TOP_LEVEL:
        if key not in env:
            result.missing_top_level.append(key)

    # 2. reversion_signal_bin enum
    bin_value = env.get("reversion_signal_bin")
    if bin_value is not None and bin_value not in REVERSION_BIN_VALUES:
        result.invalid_enum_values.append(f"reversion_signal_bin={bin_value!r}")

    # 3. audit_mode enum
    audit_mode = env.get("audit_mode")
    if audit_mode is not None and audit_mode not in AUDIT_MODE_VALUES:
        result.invalid_audit_mode = str(audit_mode)

    # 4. audit_mode field-presence contracts
    pvm = env.get("parameters_version_max")
    eph = env.get("effective_parameters_hash")
    if audit_mode == "snapshot":
        if pvm is None:
            result.audit_mode_field_violations.append(
                "audit_mode=snapshot requires parameters_version_max"
            )
        elif not UUID_REGEX.match(str(pvm)):
            result.audit_mode_field_violations.append(
                f"parameters_version_max not a UUID: {pvm!r}"
            )
        if eph is None:
            result.audit_mode_field_violations.append(
                "audit_mode=snapshot requires effective_parameters_hash"
            )
        elif not SHA256_REGEX.match(str(eph)):
            result.audit_mode_field_violations.append(
                f"effective_parameters_hash not 64-char hex: {eph!r}"
            )
    elif audit_mode == "standalone":
        if pvm is not None:
            result.audit_mode_field_violations.append(
                "audit_mode=standalone requires parameters_version_max ABSENT; "
                f"got {pvm!r}"
            )
        if eph is not None:
            result.audit_mode_field_violations.append(
                "audit_mode=standalone requires effective_parameters_hash ABSENT; "
                f"got {eph!r}"
            )

    # 5. reversion_cell MUST be null in v0.4.0 (forward-compat placeholder only)
    if "reversion_cell" in env and env["reversion_cell"] is not None:
        result.reversion_cell_non_null = True
        result.notes.append(
            "reversion_cell must be null in v0.4.0; populated by v0.4.2+ pm-supervisor wiring"
        )

    # 6. unavailable_reason / bin coupling (INV-3.6-A)
    unavailable_reason = env.get("unavailable_reason")
    if bin_value == "MR_UNAVAILABLE" and unavailable_reason is None:
        result.missing_unavailable_reason = True
        result.inv_3_6_a_violation = True
    if bin_value != "MR_UNAVAILABLE" and unavailable_reason is not None:
        result.inv_3_6_a_violation = True
        result.notes.append(
            "INV-3.6-A: unavailable_reason set but bin != MR_UNAVAILABLE"
        )
    if unavailable_reason is not None and unavailable_reason not in UNAVAILABLE_REASON_VALUES:
        result.invalid_unavailable_reason = str(unavailable_reason)

    # 7. components + sub_signal_fires (skip when unavailable)
    if bin_value != "MR_UNAVAILABLE":
        components = env.get("components")
        if not isinstance(components, dict):
            result.notes.append(
                f"components must be dict when bin!=MR_UNAVAILABLE; got {type(components).__name__}"
            )
        else:
            for key in REQUIRED_COMPONENTS_KEYS:
                if key not in components:
                    result.missing_components_keys.append(key)

        fires = env.get("sub_signal_fires")
        if not isinstance(fires, dict):
            result.notes.append(
                f"sub_signal_fires must be dict when bin!=MR_UNAVAILABLE; got {type(fires).__name__}"
            )
        else:
            for key in REQUIRED_SUB_SIGNAL_FIRES:
                if key not in fires:
                    result.missing_sub_signal_fires.append(key)

            # INV-3.6-B: oversold/overbought bin require all relevant fires True
            if bin_value == "MR_OVERSOLD":
                required = ("drawdown_threshold", "rsi_oversold", "bollinger_lower_extreme")
                for k in required:
                    if not fires.get(k):
                        result.inv_3_6_b_violation.append(
                            f"MR_OVERSOLD requires {k}=True"
                        )
            elif bin_value == "MR_OVERBOUGHT":
                required = ("rsi_overbought", "bollinger_upper_extreme")
                for k in required:
                    if not fires.get(k):
                        result.inv_3_6_b_violation.append(
                            f"MR_OVERBOUGHT requires {k}=True"
                        )

    # 8. Overall validity
    result.valid = (
        not result.missing_top_level
        and not result.invalid_enum_values
        and result.invalid_audit_mode is None
        and not result.audit_mode_field_violations
        and not result.reversion_cell_non_null
        and not result.missing_unavailable_reason
        and result.invalid_unavailable_reason is None
        and not result.missing_components_keys
        and not result.missing_sub_signal_fires
        and not result.inv_3_6_a_violation
        and not result.inv_3_6_b_violation
        and not any("must be dict" in n for n in result.notes)
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(prog="reversion_envelope_shape")
    parser.add_argument("--envelope", type=str, default="-", help="path to JSON envelope, or - for stdin")
    args = parser.parse_args()

    if args.envelope == "-":
        env = json.load(sys.stdin)
    else:
        with open(args.envelope) as f:
            env = json.load(f)

    result = validate_reversion_envelope_shape(env)
    print(json.dumps({
        "valid": result.valid,
        "missing_top_level": result.missing_top_level,
        "invalid_enum_values": result.invalid_enum_values,
        "invalid_audit_mode": result.invalid_audit_mode,
        "audit_mode_field_violations": result.audit_mode_field_violations,
        "reversion_cell_non_null": result.reversion_cell_non_null,
        "missing_unavailable_reason": result.missing_unavailable_reason,
        "invalid_unavailable_reason": result.invalid_unavailable_reason,
        "missing_components_keys": result.missing_components_keys,
        "missing_sub_signal_fires": result.missing_sub_signal_fires,
        "inv_3_6_a_violation": result.inv_3_6_a_violation,
        "inv_3_6_b_violation": result.inv_3_6_b_violation,
        "notes": result.notes,
    }, indent=2))
    return 0 if result.valid else 1


__all__ = [
    "ReversionEnvelopeShapeResult",
    "validate_reversion_envelope_shape",
    "REVERSION_BIN_VALUES",
    "AUDIT_MODE_VALUES",
    "UNAVAILABLE_REASON_VALUES",
    "REQUIRED_TOP_LEVEL",
    "REQUIRED_COMPONENTS_KEYS",
    "REQUIRED_SUB_SIGNAL_FIRES",
]


if __name__ == "__main__":
    sys.exit(main())
