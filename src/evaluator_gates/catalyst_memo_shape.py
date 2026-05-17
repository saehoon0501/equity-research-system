"""Catalyst-scout memo shape validator (HG-31).

Validates the schema emitted by catalyst-scout per
`.claude/agents/catalyst-scout.md`. Catches the audit gaps in Groups H
(catalyst-scout coverage) + I (sentiment_data_degraded boolean
universally missing) + degraded-fallback handling:

- top_catalysts_90d / catalysts array shape (date, type, source,
  kpi_impact, confidence).
- positioning block sub-keys (tier_insufficient + iv_spread + p_c_ratio
  + unusual_dte_distribution + strike_clustering, tier-conditional).
- sentiment_signals: 4 expected indicators present (each with
  reading + reading_date + implication) OR explicitly marked
  unavailable.
- sentiment_data_degraded boolean is present and matches the
  deterministic re-count from sentiment_degradation.py (cross-check
  hook).
- conviction_modifier schema (direction ∈ {-1,0,+1}, magnitude enum,
  reason string ≤500 chars).
- institutional_flow: top10_holders + active/passive % + 13G/A deltas +
  next_13f_deadline + active_manager_conviction_read enum.

DETERMINISM: pure stdlib. No I/O beyond CLI.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any

from src.evaluator_gates.sentiment_degradation import (
    EXPECTED_INDICATOR_NAMES,
    compute_sentiment_data_degraded,
)

VALID_TIERS: frozenset[str] = frozenset({
    "core_fundamental", "thematic_growth", "speculative_optionality",
})

VALID_CATALYST_TYPES: frozenset[str] = frozenset({
    "earnings", "guidance", "M&A", "regulatory", "product_launch",
    "investor_day", "dividend", "conference", "macro_event_company_referenced",
})

VALID_KPI_IMPACTS: frozenset[str] = frozenset({
    "EPS", "revenue", "margin", "guidance", "regulatory", "M&A",
})

VALID_CONFIDENCE: frozenset[str] = frozenset({"high", "medium", "low"})

VALID_HOLDER_CLASSIFICATIONS: frozenset[str] = frozenset({
    "ACTIVE", "PASSIVE", "AMBIGUOUS",
})

VALID_ACTIVE_MANAGER_READS: frozenset[str] = frozenset({
    "ADD_INTO_PARABOLIC",
    "HOLD_THROUGH_PARABOLIC",
    "TRIM_THROUGH_PARABOLIC",
    "NO_ACTIVE_ANCHOR",
    "INCONCLUSIVE",
})

VALID_MODIFIER_DIRECTIONS: frozenset[int] = frozenset({-1, 0, 1})
VALID_MODIFIER_MAGNITUDES: frozenset[str] = frozenset({"low", "medium", "high"})

# Top-level required fields per catalyst-scout.md §output schema.
REQUIRED_TOP_LEVEL: tuple[str, ...] = (
    "ticker",
    "tier",
    "as_of",
    "catalysts",
    "positioning",
    "institutional_flow",
    "sentiment_signals",
    "sentiment_data_degraded",
    "conviction_modifier",
    "evidence_index_refs",
    "banned_outputs_check",
)

# Each catalyst entry's required fields.
REQUIRED_CATALYST_KEYS: tuple[str, ...] = (
    "date", "type", "source", "kpi_impact", "confidence",
)

# Each sentiment_signals entry's required fields.
REQUIRED_SENTIMENT_KEYS: tuple[str, ...] = (
    "indicator", "reading", "reading_date", "implication",
)

# Each conviction_modifier required fields.
REQUIRED_CONVICTION_MODIFIER_KEYS: tuple[str, ...] = (
    "direction", "magnitude", "reason",
)

# Maximum length of conviction_modifier.reason text.
MAX_MODIFIER_REASON_LEN = 500


@dataclass
class CatalystMemoShapeResult:
    """Result envelope for catalyst-scout memo shape validation."""

    valid: bool
    tier: str | None = None
    missing_top_level: list[str] = field(default_factory=list)
    invalid_catalyst_entries: list[dict] = field(default_factory=list)
    missing_positioning_keys: list[str] = field(default_factory=list)
    tier_insufficient_inconsistency: list[str] = field(default_factory=list)
    invalid_sentiment_entries: list[dict] = field(default_factory=list)
    sentiment_indicators_missing: list[str] = field(default_factory=list)
    sentiment_degraded_emitted: bool | None = None
    sentiment_degraded_recomputed: bool | None = None
    sentiment_degraded_mismatch: bool = False
    missing_modifier_keys: list[str] = field(default_factory=list)
    invalid_modifier_values: list[str] = field(default_factory=list)
    invalid_active_manager_read: str | None = None
    notes: list[str] = field(default_factory=list)


def _is_present_non_empty(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, (str, list, dict, tuple)) and len(value) == 0:
        return False
    return True


def _validate_catalysts(memo: dict, result: CatalystMemoShapeResult) -> None:
    catalysts = memo.get("catalysts")
    # Accept either top-level "catalysts" or "top_catalysts_90d" (the
    # pm-supervisor envelope uses the latter name).
    if catalysts is None:
        catalysts = memo.get("top_catalysts_90d")
    if not isinstance(catalysts, list):
        return
    for i, c in enumerate(catalysts):
        if not isinstance(c, dict):
            result.invalid_catalyst_entries.append({
                "index": i, "error": f"not a dict; type={type(c).__name__}"
            })
            continue
        missing = [k for k in REQUIRED_CATALYST_KEYS if not _is_present_non_empty(c.get(k))]
        invalid_enums: list[str] = []
        if c.get("type") is not None and c.get("type") not in VALID_CATALYST_TYPES:
            invalid_enums.append(f"type={c.get('type')!r}")
        if c.get("kpi_impact") is not None and c.get("kpi_impact") not in VALID_KPI_IMPACTS:
            invalid_enums.append(f"kpi_impact={c.get('kpi_impact')!r}")
        if c.get("confidence") is not None and c.get("confidence") not in VALID_CONFIDENCE:
            invalid_enums.append(f"confidence={c.get('confidence')!r}")
        if missing or invalid_enums:
            result.invalid_catalyst_entries.append({
                "index": i,
                "missing": missing,
                "invalid_enums": invalid_enums,
            })


def _validate_positioning(memo: dict, result: CatalystMemoShapeResult) -> None:
    pos = memo.get("positioning")
    if not isinstance(pos, dict):
        return

    # tier_insufficient required.
    if "tier_insufficient" not in pos:
        result.missing_positioning_keys.append("tier_insufficient")
    elif not isinstance(pos["tier_insufficient"], bool):
        result.notes.append(
            f"positioning.tier_insufficient must be bool; got "
            f"{type(pos['tier_insufficient']).__name__}"
        )

    # tier_insufficient consistency: if True, iv_spread/p_c_ratio/etc
    # MUST be null OR empty arrays.
    if pos.get("tier_insufficient") is True:
        for k in ("iv_spread", "p_c_ratio"):
            v = pos.get(k)
            if v is not None and v != "" and v != []:
                result.tier_insufficient_inconsistency.append(
                    f"positioning.{k}={v!r} is non-null but "
                    "tier_insufficient=true (should be null)"
                )
        # Must have fallback_proxies populated.
        if not _is_present_non_empty(pos.get("fallback_proxies")):
            result.tier_insufficient_inconsistency.append(
                "positioning.fallback_proxies missing/empty but "
                "tier_insufficient=true (fallback should be populated)"
            )

    # framework_keys required.
    fwk = pos.get("framework_keys")
    if not isinstance(fwk, list) or len(fwk) == 0:
        result.missing_positioning_keys.append("framework_keys")


def _validate_sentiment(memo: dict, result: CatalystMemoShapeResult) -> None:
    signals = memo.get("sentiment_signals")
    if not isinstance(signals, list):
        return

    seen_indicators: set[str] = set()
    for i, s in enumerate(signals):
        if not isinstance(s, dict):
            result.invalid_sentiment_entries.append({
                "index": i, "error": f"not a dict; type={type(s).__name__}"
            })
            continue
        missing = [k for k in REQUIRED_SENTIMENT_KEYS if k not in s]
        # reading + reading_date may be null when data unavailable —
        # presence-of-key check, not non-empty.
        if missing:
            result.invalid_sentiment_entries.append({
                "index": i, "missing_keys": missing,
            })
        ind_name = s.get("indicator")
        if isinstance(ind_name, str):
            for expected in EXPECTED_INDICATOR_NAMES:
                if expected.lower() in ind_name.lower():
                    seen_indicators.add(expected)

    # Check all 4 expected indicators were emitted (even if marked unavailable).
    missing_indicators = [
        n for n in EXPECTED_INDICATOR_NAMES if n not in seen_indicators
    ]
    if missing_indicators:
        result.sentiment_indicators_missing = missing_indicators

    # sentiment_data_degraded cross-check.
    emitted_degraded = memo.get("sentiment_data_degraded")
    result.sentiment_degraded_emitted = (
        emitted_degraded if isinstance(emitted_degraded, bool) else None
    )
    if isinstance(signals, list):
        recomp = compute_sentiment_data_degraded(signals)
        result.sentiment_degraded_recomputed = recomp.degraded
        if (
            isinstance(emitted_degraded, bool)
            and emitted_degraded != recomp.degraded
        ):
            result.sentiment_degraded_mismatch = True
            result.notes.append(
                f"sentiment_data_degraded emitted={emitted_degraded} but "
                f"deterministic re-count gives {recomp.degraded} "
                f"(n_unavailable={recomp.n_unavailable}, "
                f"threshold={recomp.threshold})"
            )


def _validate_conviction_modifier(memo: dict, result: CatalystMemoShapeResult) -> None:
    cm = memo.get("conviction_modifier")
    if not isinstance(cm, dict):
        return
    for k in REQUIRED_CONVICTION_MODIFIER_KEYS:
        if not _is_present_non_empty(cm.get(k)):
            result.missing_modifier_keys.append(k)

    direction = cm.get("direction")
    if direction is not None and direction not in VALID_MODIFIER_DIRECTIONS:
        result.invalid_modifier_values.append(f"direction={direction!r}")

    magnitude = cm.get("magnitude")
    if magnitude is not None and magnitude not in VALID_MODIFIER_MAGNITUDES:
        result.invalid_modifier_values.append(f"magnitude={magnitude!r}")

    reason = cm.get("reason")
    if isinstance(reason, str) and len(reason) > MAX_MODIFIER_REASON_LEN:
        result.invalid_modifier_values.append(
            f"reason length {len(reason)} > {MAX_MODIFIER_REASON_LEN}"
        )


def _validate_institutional_flow(memo: dict, result: CatalystMemoShapeResult) -> None:
    inst = memo.get("institutional_flow")
    if not isinstance(inst, dict):
        return
    amr = inst.get("active_manager_conviction_read")
    if amr is not None and amr not in VALID_ACTIVE_MANAGER_READS:
        result.invalid_active_manager_read = str(amr)


def validate_catalyst_memo_shape(memo: object) -> CatalystMemoShapeResult:
    """Validate a catalyst-scout memo dict against the v0.2 schema."""
    if not isinstance(memo, dict):
        return CatalystMemoShapeResult(
            valid=False,
            notes=[f"memo must be a dict; got {type(memo).__name__}"],
        )

    result = CatalystMemoShapeResult(valid=True)
    tier = memo.get("tier")
    result.tier = tier if isinstance(tier, str) else None

    for k in REQUIRED_TOP_LEVEL:
        if k == "sentiment_data_degraded":
            # Presence-only — bool value can be either true or false.
            if k not in memo:
                result.missing_top_level.append(k)
        elif not _is_present_non_empty(memo.get(k)):
            result.missing_top_level.append(k)

    _validate_catalysts(memo, result)
    _validate_positioning(memo, result)
    _validate_sentiment(memo, result)
    _validate_conviction_modifier(memo, result)
    _validate_institutional_flow(memo, result)

    if (
        result.missing_top_level
        or result.invalid_catalyst_entries
        or result.missing_positioning_keys
        or result.tier_insufficient_inconsistency
        or result.invalid_sentiment_entries
        or result.sentiment_indicators_missing
        or result.sentiment_degraded_mismatch
        or result.missing_modifier_keys
        or result.invalid_modifier_values
        or result.invalid_active_manager_read is not None
    ):
        result.valid = False

    return result


def _result_to_dict(r: CatalystMemoShapeResult) -> dict[str, Any]:
    return {
        "valid": r.valid,
        "tier": r.tier,
        "missing_top_level": r.missing_top_level,
        "invalid_catalyst_entries": r.invalid_catalyst_entries,
        "missing_positioning_keys": r.missing_positioning_keys,
        "tier_insufficient_inconsistency": r.tier_insufficient_inconsistency,
        "invalid_sentiment_entries": r.invalid_sentiment_entries,
        "sentiment_indicators_missing": r.sentiment_indicators_missing,
        "sentiment_degraded_emitted": r.sentiment_degraded_emitted,
        "sentiment_degraded_recomputed": r.sentiment_degraded_recomputed,
        "sentiment_degraded_mismatch": r.sentiment_degraded_mismatch,
        "missing_modifier_keys": r.missing_modifier_keys,
        "invalid_modifier_values": r.invalid_modifier_values,
        "invalid_active_manager_read": r.invalid_active_manager_read,
        "notes": r.notes,
    }


def _cli(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="catalyst_memo_shape",
        description=(
            "Validate a catalyst-scout memo shape against the v0.2 schema. "
            "Exit 0 valid, 1 invalid, 2 unparseable."
        ),
    )
    parser.add_argument("--memo", required=True, help="path to memo JSON")
    args = parser.parse_args(argv)

    try:
        with open(args.memo, "r", encoding="utf-8") as f:
            memo = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"unable to read/parse memo: {exc}\n")
        return 2

    result = validate_catalyst_memo_shape(memo)
    sys.stdout.write(json.dumps(_result_to_dict(result), indent=2) + "\n")
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(_cli())


__all__ = [
    "CatalystMemoShapeResult",
    "validate_catalyst_memo_shape",
    "REQUIRED_TOP_LEVEL",
    "REQUIRED_CATALYST_KEYS",
    "REQUIRED_SENTIMENT_KEYS",
    "REQUIRED_CONVICTION_MODIFIER_KEYS",
    "VALID_CATALYST_TYPES",
    "VALID_KPI_IMPACTS",
    "VALID_CONFIDENCE",
    "VALID_MODIFIER_DIRECTIONS",
    "VALID_MODIFIER_MAGNITUDES",
    "VALID_ACTIVE_MANAGER_READS",
]
