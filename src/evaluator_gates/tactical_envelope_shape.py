"""Tactical-overlay JSON envelope shape validator.

Per Section 2 v3-final + Section 2.1 v5-final. Mirrors the HG-31
catalyst_memo_shape pattern at src/evaluator_gates/catalyst_memo_shape.py.

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
class ValidationResult:
    """Outcome of validate() — passed boolean + ordered error list."""

    passed: bool
    errors: list[str] = field(default_factory=list)


def validate(env: dict) -> ValidationResult:
    """Validate tactical-overlay envelope against Section 2 v3-final schema.

    Returns ValidationResult; check .passed and .errors.
    """
    errs: list[str] = []

    # Top-level key presence
    for key in REQUIRED_TOP_LEVEL:
        if key not in env:
            errs.append(f"missing top-level key: {key}")
    if errs:
        # Don't deep-validate when top-level missing; surface clearly.
        return ValidationResult(passed=False, errors=errs)

    # tactical_signal_bin enum
    bin_val = env["tactical_signal_bin"]
    if bin_val not in TACTICAL_BIN_VALUES:
        errs.append(
            f"tactical_signal_bin invalid: {bin_val!r} "
            f"(must be one of {sorted(TACTICAL_BIN_VALUES)})"
        )

    # unavailable bin requires valid reason
    if bin_val == "unavailable":
        reason = env.get("unavailable_reason")
        if reason not in UNAVAILABLE_REASON_VALUES:
            errs.append(
                f"unavailable bin requires unavailable_reason in "
                f"{sorted(UNAVAILABLE_REASON_VALUES)}, got {reason!r}"
            )

    # rf_degenerate must be boolean
    if not isinstance(env["rf_degenerate"], bool):
        errs.append(f"rf_degenerate must be bool, got {type(env['rf_degenerate']).__name__}")

    # tactical_cell sub-keys
    cell = env["tactical_cell"]
    if not isinstance(cell, dict):
        errs.append(f"tactical_cell must be dict, got {type(cell).__name__}")
        return ValidationResult(passed=False, errors=errs)

    missing_cell_subkey = False
    for key in REQUIRED_TACTICAL_CELL:
        if key not in cell:
            errs.append(f"missing tactical_cell.{key}")
            missing_cell_subkey = True
    if missing_cell_subkey:
        return ValidationResult(passed=False, errors=errs)

    # conviction enum
    if cell["conviction"] not in CONVICTION_VALUES:
        errs.append(
            f"tactical_cell.conviction invalid: {cell['conviction']!r} "
            f"(must be one of {sorted(CONVICTION_VALUES)})"
        )

    # tactical_bin enum (cell-level; mirrors top-level)
    if cell["tactical_bin"] not in TACTICAL_BIN_VALUES:
        errs.append(
            f"tactical_cell.tactical_bin invalid: {cell['tactical_bin']!r}"
        )

    # INV-2.1-A enforcement: cell_disposition must be in tactical_disposition enum,
    # NOT in canonical summary_code enum (BUY/TRIM/SELL forbidden here).
    disp = cell["cell_disposition"]
    if disp not in TACTICAL_DISPOSITION_VALUES:
        errs.append(
            f"tactical_cell.cell_disposition invalid: {disp!r} "
            f"(must be one of {sorted(TACTICAL_DISPOSITION_VALUES)}; "
            f"INV-2.1-A: canonical BUY/TRIM/SELL are summary_code values only)"
        )

    # cell_size_pct numeric
    size = cell.get("cell_size_pct")
    if not isinstance(size, (int, float)) or isinstance(size, bool):
        errs.append(
            f"tactical_cell.cell_size_pct must be numeric, got {type(size).__name__}"
        )

    return ValidationResult(passed=len(errs) == 0, errors=errs)


def main() -> int:
    """CLI: reads JSON envelope on stdin, exits 0 on PASS, 1 on FAIL."""
    try:
        env = json.loads(sys.stdin.read())
    except json.JSONDecodeError as e:
        print(f"invalid JSON: {e}", file=sys.stderr)
        return 1
    out = validate(env)
    if out.passed:
        return 0
    for e in out.errors:
        print(e, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
