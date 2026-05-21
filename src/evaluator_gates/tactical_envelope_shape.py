"""Tactical-overlay JSON envelope shape validator.

Per Section 2 v3-final + Section 2.1 v5-final. Mirrors the HG-31
catalyst_memo_shape pattern at src/evaluator_gates/catalyst_memo_shape.py and
exposes a TacticalEnvelopeShapeResult dataclass with named field-lists so
the evaluator_gates aggregate dispatch can fingerprint stuck-loops correctly.

Validates the structured envelope emitted by the tactical-overlay agent
(.claude/agents/tactical-overlay.md). Catches:
- Missing top-level keys (ticker, as_of_date, run_id, tactical_signal_bin,
  rf_degenerate, tactical_cell, frameworks_cited).
- Invalid tactical_signal_bin enum value (must be positive/neutral/negative/unavailable).
- Missing unavailable_reason when bin == 'unavailable'.
- Missing tactical_cell sub-keys (conviction, tactical_bin, cell_size_pct,
  cell_disposition).
- Invalid conviction enum (HIGH/MEDIUM/LOW).
- Invalid cell_disposition enum — enforces INV-2.1-A disjointness with canonical
  summary_code enum (BUY-HIGH/BUY-MED/HOLD/AVOID; rejects canonical BUY/TRIM/SELL).
- Non-numeric cell_size_pct.

DETERMINISM: pure stdlib. No I/O beyond CLI stdin/stdout.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field

TACTICAL_BIN_VALUES: frozenset[str] = frozenset(
    {"positive", "neutral", "negative", "unavailable"}
)

# INV-2.1-A enforcement: tactical_disposition enum (NOT canonical summary_code).
TACTICAL_DISPOSITION_VALUES: frozenset[str] = frozenset(
    {"HOLD", "BUY-HIGH", "BUY-MED", "AVOID"}
)

CONVICTION_VALUES: frozenset[str] = frozenset({"HIGH", "MEDIUM", "LOW"})

UNAVAILABLE_REASON_VALUES: frozenset[str] = frozenset(
    {"insufficient_price_history", "rf_resolver_staleness"}
)

REQUIRED_TOP_LEVEL: tuple[str, ...] = (
    "ticker",
    "as_of_date",
    "run_id",
    "tactical_signal_bin",
    "rf_degenerate",
    "tactical_cell",
    "frameworks_cited",
)

REQUIRED_TACTICAL_CELL: tuple[str, ...] = (
    "conviction",
    "tactical_bin",
    "cell_size_pct",
    "cell_disposition",
)


@dataclass
class TacticalEnvelopeShapeResult:
    """Result envelope mirroring CatalystMemoShapeResult/CDDMemoShapeResult shape.

    Named field-lists let _fingerprint_tactical_envelope produce a deterministic
    stuck-loop signature for the evaluator_gates aggregate dispatch.
    """

    valid: bool
    missing_top_level: list[str] = field(default_factory=list)
    invalid_enum_values: list[str] = field(default_factory=list)
    missing_unavailable_reason: bool = False
    invalid_unavailable_reason: str | None = None
    rf_degenerate_not_bool: bool = False
    tactical_cell_not_dict: bool = False
    missing_cell_subkeys: list[str] = field(default_factory=list)
    invalid_conviction: str | None = None
    invalid_cell_disposition: str | None = None  # INV-2.1-A violation surface
    invalid_cell_size_type: str | None = None
    notes: list[str] = field(default_factory=list)


def validate_tactical_envelope_shape(env: object) -> TacticalEnvelopeShapeResult:
    """Validate tactical-overlay envelope against Section 2 v3-final schema.

    Accepts a dict (typical) or any object (returns invalid + note for wrong type).
    """
    if not isinstance(env, dict):
        return TacticalEnvelopeShapeResult(
            valid=False,
            notes=[f"envelope must be dict; got {type(env).__name__}"],
        )

    result = TacticalEnvelopeShapeResult(valid=True)

    # Top-level key presence
    for key in REQUIRED_TOP_LEVEL:
        if key not in env:
            result.missing_top_level.append(key)
    if result.missing_top_level:
        result.valid = False
        return result  # don't deep-validate when top-level missing

    # tactical_signal_bin enum
    bin_val = env["tactical_signal_bin"]
    if bin_val not in TACTICAL_BIN_VALUES:
        result.invalid_enum_values.append(f"tactical_signal_bin={bin_val!r}")
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

    # rf_degenerate must be boolean
    if not isinstance(env["rf_degenerate"], bool):
        result.rf_degenerate_not_bool = True
        result.valid = False

    # tactical_cell sub-keys
    cell = env["tactical_cell"]
    if not isinstance(cell, dict):
        result.tactical_cell_not_dict = True
        result.valid = False
        return result

    for key in REQUIRED_TACTICAL_CELL:
        if key not in cell:
            result.missing_cell_subkeys.append(key)
    if result.missing_cell_subkeys:
        result.valid = False
        return result

    # conviction enum
    if cell["conviction"] not in CONVICTION_VALUES:
        result.invalid_conviction = str(cell["conviction"])
        result.valid = False

    # tactical_bin enum (cell-level; mirrors top-level)
    if cell["tactical_bin"] not in TACTICAL_BIN_VALUES:
        result.invalid_enum_values.append(
            f"tactical_cell.tactical_bin={cell['tactical_bin']!r}"
        )
        result.valid = False

    # INV-2.1-A: cell_disposition must be in tactical_disposition enum,
    # NOT in canonical summary_code enum (BUY/TRIM/SELL forbidden here).
    disp = cell["cell_disposition"]
    if disp not in TACTICAL_DISPOSITION_VALUES:
        result.invalid_cell_disposition = str(disp)
        result.valid = False

    # cell_size_pct numeric (reject bools that pass isinstance(int))
    size = cell.get("cell_size_pct")
    if not isinstance(size, (int, float)) or isinstance(size, bool):
        result.invalid_cell_size_type = type(size).__name__
        result.valid = False

    return result


def _cli(argv: list[str] | None = None) -> int:
    """CLI: validates a tactical envelope. Exit 0 valid, 1 invalid, 2 unparseable.

    Mirrors the catalyst_memo_shape CLI signature (--memo path).
    """
    parser = argparse.ArgumentParser(
        description="Validate a tactical-overlay envelope against Section 2 v3-final schema.",
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

    result = validate_tactical_envelope_shape(env)
    sys.stdout.write(json.dumps(result.__dict__, indent=2, default=str) + "\n")
    return 0 if result.valid else 1


if __name__ == "__main__":
    sys.exit(_cli())


__all__ = [
    "CONVICTION_VALUES",
    "REQUIRED_TACTICAL_CELL",
    "REQUIRED_TOP_LEVEL",
    "TACTICAL_BIN_VALUES",
    "TACTICAL_DISPOSITION_VALUES",
    "TacticalEnvelopeShapeResult",
    "UNAVAILABLE_REASON_VALUES",
    "validate_tactical_envelope_shape",
]
