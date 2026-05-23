"""Flow-overlay JSON envelope shape validator.

Mirrors src/evaluator_gates/tactical_envelope_shape.py (HG-33) at structural
level. Exposes a FlowEnvelopeShapeResult dataclass with named field-lists so
the evaluator_gates aggregate dispatch can fingerprint stuck-loops correctly.

Validates the structured envelope emitted by the flow-overlay agent
(.claude/agents/flow-overlay.md). Catches:
- Missing top-level keys.
- Invalid flow_signal_bin enum value (must be positive/neutral/negative/unavailable).
- Missing unavailable_reason when bin == 'unavailable'.
- Missing flow_cell sub-keys (conviction, flow_bin, cell_size_pct, cell_disposition).
- Invalid conviction enum (HIGH/MEDIUM/LOW).
- Invalid cell_disposition enum — enforces INV-FLOW-2.1-A disjointness with
  canonical summary_code enum (BUY-HIGH/BUY-MED/HOLD/AVOID; rejects canonical
  BUY/TRIM/SELL).
- Non-numeric cell_size_pct.

DETERMINISM: pure stdlib. No I/O beyond CLI stdin/stdout.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field

FLOW_BIN_VALUES: frozenset[str] = frozenset(
    {"positive", "neutral", "negative", "unavailable"}
)

# INV-FLOW-2.1-A enforcement: flow_disposition enum (NOT canonical summary_code).
FLOW_DISPOSITION_VALUES: frozenset[str] = frozenset(
    {"HOLD", "BUY-HIGH", "BUY-MED", "AVOID"}
)

CONVICTION_VALUES: frozenset[str] = frozenset({"HIGH", "MEDIUM", "LOW"})

UNAVAILABLE_REASON_VALUES: frozenset[str] = frozenset(
    {
        "insufficient_price_history",
        "spy_price_history_unavailable",
        # v0.2 additions (gamma_regime sub-signal)
        "options_chain_unavailable",
        "gex_data_stale",
        "bs_iv_unavailable",
        # v0.3 additions (crowding sub-signal)
        "short_interest_unavailable",
        "short_interest_stale",
        "shares_outstanding_unavailable",
    }
)

REQUIRED_TOP_LEVEL: tuple[str, ...] = (
    "ticker",
    "as_of_date",
    "run_id",
    "flow_signal_bin",
    "flow_cell",
    "frameworks_cited",
)

REQUIRED_FLOW_CELL: tuple[str, ...] = (
    "conviction",
    "flow_bin",
    "cell_size_pct",
    "cell_disposition",
)


@dataclass
class FlowEnvelopeShapeResult:
    """Result envelope mirroring TacticalEnvelopeShapeResult shape.

    Named field-lists let _fingerprint_flow_envelope produce a deterministic
    stuck-loop signature for the evaluator_gates aggregate dispatch.
    """

    valid: bool
    missing_top_level: list[str] = field(default_factory=list)
    invalid_enum_values: list[str] = field(default_factory=list)
    missing_unavailable_reason: bool = False
    invalid_unavailable_reason: str | None = None
    flow_cell_not_dict: bool = False
    missing_cell_subkeys: list[str] = field(default_factory=list)
    invalid_conviction: str | None = None
    invalid_cell_disposition: str | None = None  # INV-FLOW-2.1-A violation surface
    invalid_cell_size_type: str | None = None
    notes: list[str] = field(default_factory=list)


def validate_flow_envelope_shape(env: object) -> FlowEnvelopeShapeResult:
    """Validate flow-overlay envelope against v0.1 schema.

    Accepts a dict (typical) or any object (returns invalid + note for wrong type).
    """
    if not isinstance(env, dict):
        return FlowEnvelopeShapeResult(
            valid=False,
            notes=[f"envelope must be dict; got {type(env).__name__}"],
        )

    result = FlowEnvelopeShapeResult(valid=True)

    # Top-level key presence
    for key in REQUIRED_TOP_LEVEL:
        if key not in env:
            result.missing_top_level.append(key)
    if result.missing_top_level:
        result.valid = False
        return result  # don't deep-validate when top-level missing

    # flow_signal_bin enum
    bin_val = env["flow_signal_bin"]
    if bin_val not in FLOW_BIN_VALUES:
        result.invalid_enum_values.append(f"flow_signal_bin={bin_val!r}")
        result.valid = False

    # unavailable bin requires valid reason
    if bin_val == "unavailable":
        reason = env.get("unavailable_reason")
        if reason is None:
            result.missing_unavailable_reason = True
            result.valid = False
        elif reason not in UNAVAILABLE_REASON_VALUES:
            result.invalid_unavailable_reason = str(reason)
            result.valid = False

    # flow_cell sub-keys
    cell = env["flow_cell"]
    if not isinstance(cell, dict):
        result.flow_cell_not_dict = True
        result.valid = False
        return result

    for key in REQUIRED_FLOW_CELL:
        if key not in cell:
            result.missing_cell_subkeys.append(key)
    if result.missing_cell_subkeys:
        result.valid = False
        return result

    # conviction enum
    if cell["conviction"] not in CONVICTION_VALUES:
        result.invalid_conviction = str(cell["conviction"])
        result.valid = False

    # flow_bin enum (cell-level; mirrors top-level)
    if cell["flow_bin"] not in FLOW_BIN_VALUES:
        result.invalid_enum_values.append(
            f"flow_cell.flow_bin={cell['flow_bin']!r}"
        )
        result.valid = False

    # INV-FLOW-2.1-A: cell_disposition must be in flow_disposition enum,
    # NOT in canonical summary_code enum (BUY/TRIM/SELL forbidden here).
    disp = cell["cell_disposition"]
    if disp not in FLOW_DISPOSITION_VALUES:
        result.invalid_cell_disposition = str(disp)
        result.valid = False

    # cell_size_pct numeric (reject bools that pass isinstance(int))
    size = cell.get("cell_size_pct")
    if not isinstance(size, (int, float)) or isinstance(size, bool):
        result.invalid_cell_size_type = type(size).__name__
        result.valid = False

    return result


def _cli(argv: list[str] | None = None) -> int:
    """CLI: validates a flow envelope. Exit 0 valid, 1 invalid, 2 unparseable.

    Mirrors the tactical_envelope_shape CLI signature (--memo path).
    """
    parser = argparse.ArgumentParser(
        description="Validate a flow-overlay envelope against v0.1 schema.",
    )
    parser.add_argument(
        "--memo",
        required=False,
        help="path to envelope JSON file (omit to read from stdin)",
    )
    args = parser.parse_args(argv)

    try:
        if args.memo:
            with open(args.memo, "r", encoding="utf-8") as f:
                env = json.load(f)
        else:
            env = json.loads(sys.stdin.read())
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"unable to read/parse envelope: {exc}\n")
        return 2

    result = validate_flow_envelope_shape(env)
    sys.stdout.write(json.dumps(result.__dict__, indent=2, default=str) + "\n")
    return 0 if result.valid else 1


if __name__ == "__main__":
    sys.exit(_cli())


__all__ = [
    "CONVICTION_VALUES",
    "FLOW_BIN_VALUES",
    "FLOW_DISPOSITION_VALUES",
    "FlowEnvelopeShapeResult",
    "REQUIRED_FLOW_CELL",
    "REQUIRED_TOP_LEVEL",
    "UNAVAILABLE_REASON_VALUES",
    "validate_flow_envelope_shape",
]
