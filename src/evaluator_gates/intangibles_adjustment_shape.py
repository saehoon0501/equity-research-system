"""Intangibles-adjustment block strict validator (HG-38).

Validates the ``intangibles_adjustment`` block + ``roic_methodology_regime``
flag added to the quantitative-analyst memo per Overlay 7 (Mauboussin
April 2025 / Ewens-Peters-Wang 2024 industry rates; §3.10 of
``.claude/agents/quantitative-analyst.md``).

Caught failure modes (from Step 3 sweep 2026-05-22):

- ``intangibles_adjusted_roic_pct: "SHADOW_MODE_NOT_COMPUTED_THIS_RUN"``
  — agent interpreted "SHADOW MODE" as "don't compute these values."
  The intent is: compute always for non-speculative tiers; the regime
  flag controls whether production label calculus uses adjusted_roic,
  not whether the value gets computed. A string sentinel where a float
  is required is a hard fail.
- Missing ``epw_industry_rates`` block under intangibles_adjustment.
- ``fama_french_industry_class`` not in canonical 5-class enum.
- Speculative-tier skip-flag inconsistent with the numeric-field
  sentinels (block claims tier=speculative but numeric fields populated,
  or vice versa).

The validator is deliberately strict on the numeric fields — the agent
gets another turn via the delta_prompt retry loop to compute and emit
proper values rather than punt on computation.

DETERMINISM: pure stdlib; no I/O beyond CLI.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any

# Canonical Fama-French 5-class industry enum used by EPW 2024.
CANONICAL_FF5_CLASSES: frozenset[str] = frozenset({
    "HiTec",
    "Hlth",
    "Cnsmr",
    "Manuf",
    "Other",
})

# Speculative-tier canonical skip sentinel (matches the §3.10 spec).
# Note: case- and dash-tolerant match per quant_memo_shape pattern.
SKIP_SENTINEL_LOWER = "skipped — speculative_optionality"

# These numeric fields MUST be present + numeric for non-speculative
# tiers. The "SHADOW_MODE_NOT_COMPUTED_THIS_RUN" sentinel observed
# in 2 of 3 Step-3 envelopes is a hard fail under this rule.
REQUIRED_NUMERIC_FIELDS: tuple[str, ...] = (
    "capitalized_intangibles_balance_usd",
    "intangibles_adjusted_earnings_usd",
    "intangibles_adjusted_invested_capital_usd",
    "intangibles_adjusted_roic_pct",
    "reverse_dcf_implied_growth_delta_pp",
)

# Required sub-keys of epw_industry_rates.
REQUIRED_EPW_RATE_KEYS: tuple[str, ...] = (
    "delta_rd",
    "delta_organ",
    "gamma_sga",
)

# Tiers where the intangibles adjustment applies (per §3.10 tier-gate).
NON_SPECULATIVE_TIERS: frozenset[str] = frozenset({
    "core_fundamental",
    "thematic_growth",
})

# Sentinel patterns the agent has been observed to emit incorrectly.
# Surfaced explicitly in the delta_prompt so the agent doesn't reuse them.
FORBIDDEN_SENTINELS: tuple[str, ...] = (
    "SHADOW_MODE_NOT_COMPUTED_THIS_RUN",
    "SHADOW_MODE_NOT_COMPUTED",
    "PENDING_COMPUTATION",
    "TBD",
)

# Recognized keys for the intangibles_adjustment block. Anything outside
# this set is surfaced as an unrecognized agent-invented key (soft warn,
# non-blocking — see CRWD 2026-05-22 case where the agent invented
# `shadow_mode_for_warm_start_label_calculus_note` to justify a regime
# fallback the spec did not authorize).
RECOGNIZED_BLOCK_KEYS: frozenset[str] = frozenset({
    *REQUIRED_NUMERIC_FIELDS,
    "epw_industry_rates",
    "fama_french_industry_class",
    "hall_steady_state_seed_used",
    "intangibles_adjustment_skipped_tier_speculative_optionality",
})


@dataclass
class IntangiblesAdjustmentResult:
    """Result envelope for HG-38 strict validation."""

    valid: bool
    tier: str | None = None
    block_present: bool = False
    block_type: str | None = None  # "dict", "string-sentinel", or "missing"
    missing_numeric_fields: list[str] = field(default_factory=list)
    forbidden_sentinels_in_numeric_fields: dict[str, str] = field(default_factory=dict)
    missing_epw_rate_keys: list[str] = field(default_factory=list)
    invalid_fama_french_class: str | None = None
    invalid_regime: str | None = None
    tier_regime_mismatch: str | None = None  # Patch A — hard fail for non-spec tier + regime='gaap'
    skip_flag_inconsistency: str | None = None
    unrecognized_block_keys: list[str] = field(default_factory=list)  # Patch C — soft warn
    notes: list[str] = field(default_factory=list)


def _is_numeric(value: object) -> bool:
    """Strict numeric check — True only for int or float (not bool, not numeric string)."""
    if isinstance(value, bool):
        return False
    return isinstance(value, (int, float))


def _is_skip_sentinel(value: object) -> bool:
    """Canonical speculative-tier skip sentinel match (case/dash-tolerant)."""
    if not isinstance(value, str):
        return False
    return SKIP_SENTINEL_LOWER in value.lower()


def validate_intangibles_adjustment(memo: object) -> IntangiblesAdjustmentResult:
    """Validate the intangibles_adjustment block + roic_methodology_regime flag.

    Schema rules:

    For tier in {core_fundamental, thematic_growth}:
        - intangibles_adjustment MUST be a dict (not a string sentinel).
        - Each numeric field in REQUIRED_NUMERIC_FIELDS MUST be int or float.
          "SHADOW_MODE_NOT_COMPUTED_THIS_RUN" and similar sentinels are HARD FAIL.
        - epw_industry_rates MUST be a dict with delta_rd, delta_organ, gamma_sga
          (all numeric).
        - fama_french_industry_class MUST be in canonical 5-class enum.
        - intangibles_adjustment_skipped_tier_speculative_optionality MUST be false.
        - roic_methodology_regime MUST be 'gaap' or 'intangibles_adjusted'.

    For tier == speculative_optionality:
        - intangibles_adjustment may be a skip-sentinel string OR a dict where
          all 5 numeric fields are the canonical skip sentinel, AND
          intangibles_adjustment_skipped_tier_speculative_optionality is true.

    For other tiers / missing tier: the block is optional; absent → pass.

    Returns:
        IntangiblesAdjustmentResult with valid=False if any rule failed.
    """
    if not isinstance(memo, dict):
        return IntangiblesAdjustmentResult(
            valid=False,
            notes=[f"memo must be a dict; got {type(memo).__name__}"],
        )

    result = IntangiblesAdjustmentResult(valid=True)
    tier = memo.get("tier")
    result.tier = tier if isinstance(tier, str) else None

    block = memo.get("intangibles_adjustment")
    regime = memo.get("roic_methodology_regime")

    # Tiers outside the gate are optional — pass if both fields absent.
    if result.tier not in NON_SPECULATIVE_TIERS and result.tier != "speculative_optionality":
        if block is None and regime is None:
            return result
        # If present, still validate the regime flag.

    # Validate roic_methodology_regime flag.
    if regime is not None:
        if regime not in ("gaap", "intangibles_adjusted"):
            result.invalid_regime = str(regime)

    # Patch A — tier-conditional regime enforcement (Step 4 PROVISIONAL
    # PROMOTED default, post-commit 3b5b027). For tier ∈ {core_fundamental,
    # thematic_growth}, regime MUST be 'intangibles_adjusted' per §3.10
    # line 115 HARD RULE. Warm-start inheritance from pre-promotion briefs
    # does NOT override this — the regime flag is recomputed on every
    # dispatch, never inherited.
    if result.tier in NON_SPECULATIVE_TIERS and regime == "gaap":
        result.tier_regime_mismatch = (
            f"tier={result.tier} requires roic_methodology_regime="
            "'intangibles_adjusted' per §3.10 Step 4 PROVISIONAL PROMOTED "
            "default (post-commit 3b5b027). Warm-start inheritance from "
            "pre-promotion briefs is NOT a valid override."
        )

    # Block-presence handling per tier.
    if block is None:
        if result.tier in NON_SPECULATIVE_TIERS:
            result.block_present = False
            result.block_type = "missing"
            result.notes.append(
                f"tier={result.tier} requires intangibles_adjustment block "
                "per §3.10; block is absent"
            )
        # speculative without the block is acceptable (auto-skipped).
        if result.invalid_regime is not None:
            result.valid = False
        else:
            result.valid = (result.tier == "speculative_optionality") and (
                block is None or _is_skip_sentinel(block)
            )
            if not result.valid and result.tier in NON_SPECULATIVE_TIERS:
                pass  # already noted above
        return result

    result.block_present = True

    # Speculative tier — string sentinel form is allowed.
    if isinstance(block, str):
        result.block_type = "string-sentinel"
        if not _is_skip_sentinel(block):
            result.notes.append(
                f"intangibles_adjustment is a string but does not match "
                f"canonical skip sentinel: {block!r}"
            )
            result.valid = False
        elif result.tier != "speculative_optionality":
            result.notes.append(
                f"tier={result.tier} cannot use intangibles_adjustment "
                "string sentinel; only speculative_optionality may skip"
            )
            result.valid = False
        return result

    if not isinstance(block, dict):
        result.block_type = type(block).__name__
        result.notes.append(
            f"intangibles_adjustment must be a dict (or skip-sentinel string "
            f"for speculative tier); got {type(block).__name__}"
        )
        result.valid = False
        return result

    result.block_type = "dict"

    # Speculative tier with dict form — must have skip flag true + all
    # numeric fields as skip sentinels.
    if result.tier == "speculative_optionality":
        skip_flag = block.get("intangibles_adjustment_skipped_tier_speculative_optionality")
        if skip_flag is not True:
            result.skip_flag_inconsistency = (
                f"tier=speculative_optionality but skip flag = {skip_flag!r}; expected True"
            )
            result.valid = False
        for fname in REQUIRED_NUMERIC_FIELDS:
            v = block.get(fname)
            if v is None:
                continue  # acceptable for skip case
            if _is_numeric(v):
                result.notes.append(
                    f"tier=speculative_optionality: field `{fname}` populated "
                    f"with numeric value {v}; expected skip-sentinel string"
                )
                result.valid = False
            elif isinstance(v, str) and not _is_skip_sentinel(v):
                # Allow only canonical skip sentinel.
                result.forbidden_sentinels_in_numeric_fields[fname] = v
                result.valid = False
        return result

    # Non-speculative tier (core_fundamental, thematic_growth):
    # all 5 numeric fields MUST be numeric.
    for fname in REQUIRED_NUMERIC_FIELDS:
        v = block.get(fname)
        if v is None:
            result.missing_numeric_fields.append(fname)
            continue
        if _is_numeric(v):
            continue
        # Anything not numeric is a fail — but distinguish forbidden
        # sentinel patterns for the delta_prompt to call out specifically.
        if isinstance(v, str):
            value_upper = v.upper()
            for forbidden in FORBIDDEN_SENTINELS:
                if forbidden in value_upper:
                    result.forbidden_sentinels_in_numeric_fields[fname] = v
                    break
            else:
                result.forbidden_sentinels_in_numeric_fields[fname] = v
        else:
            result.forbidden_sentinels_in_numeric_fields[fname] = repr(v)

    # epw_industry_rates sub-block.
    rates = block.get("epw_industry_rates")
    if rates is None or not isinstance(rates, dict):
        result.missing_epw_rate_keys = list(REQUIRED_EPW_RATE_KEYS)
    else:
        for k in REQUIRED_EPW_RATE_KEYS:
            v = rates.get(k)
            if not _is_numeric(v):
                result.missing_epw_rate_keys.append(k)

    # fama_french_industry_class.
    ff = block.get("fama_french_industry_class")
    if ff is not None and ff not in CANONICAL_FF5_CLASSES:
        result.invalid_fama_french_class = str(ff)

    # Skip flag must be false for non-speculative tiers.
    skip_flag = block.get("intangibles_adjustment_skipped_tier_speculative_optionality")
    if skip_flag is True:
        result.skip_flag_inconsistency = (
            f"tier={result.tier} but skip flag = True; "
            "intangibles_adjustment_skipped_tier_speculative_optionality must be False"
        )

    # Patch C — surface unrecognized block keys (soft warn, non-blocking).
    # The §3.10 schema is a closed set; agent-invented keys like
    # `shadow_mode_for_warm_start_label_calculus_note` (CRWD 2026-05-22)
    # indicate the agent fabricated a rationale for a violation.
    for k in block.keys():
        if k not in RECOGNIZED_BLOCK_KEYS:
            result.unrecognized_block_keys.append(k)

    # Aggregate validity. tier_regime_mismatch is HARD (Patch A);
    # unrecognized_block_keys is SOFT (Patch C — surfaces in result for
    # audit but does NOT trip result.valid).
    if (
        result.missing_numeric_fields
        or result.forbidden_sentinels_in_numeric_fields
        or result.missing_epw_rate_keys
        or result.invalid_fama_french_class is not None
        or result.invalid_regime is not None
        or result.tier_regime_mismatch is not None
        or result.skip_flag_inconsistency is not None
    ):
        result.valid = False

    return result


def _result_to_dict(r: IntangiblesAdjustmentResult) -> dict[str, Any]:
    return {
        "valid": r.valid,
        "tier": r.tier,
        "block_present": r.block_present,
        "block_type": r.block_type,
        "missing_numeric_fields": r.missing_numeric_fields,
        "forbidden_sentinels_in_numeric_fields": r.forbidden_sentinels_in_numeric_fields,
        "missing_epw_rate_keys": r.missing_epw_rate_keys,
        "invalid_fama_french_class": r.invalid_fama_french_class,
        "invalid_regime": r.invalid_regime,
        "tier_regime_mismatch": r.tier_regime_mismatch,
        "skip_flag_inconsistency": r.skip_flag_inconsistency,
        "unrecognized_block_keys": r.unrecognized_block_keys,
        "notes": r.notes,
    }


def _cli(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="intangibles_adjustment_shape",
        description=(
            "Validate a quantitative-analyst memo's intangibles_adjustment "
            "block (HG-38, Overlay 7). Exit 0 valid, 1 invalid, 2 unparseable."
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

    result = validate_intangibles_adjustment(memo)
    sys.stdout.write(json.dumps(_result_to_dict(result), indent=2) + "\n")
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(_cli())


__all__ = [
    "IntangiblesAdjustmentResult",
    "validate_intangibles_adjustment",
    "CANONICAL_FF5_CLASSES",
    "REQUIRED_NUMERIC_FIELDS",
    "REQUIRED_EPW_RATE_KEYS",
    "FORBIDDEN_SENTINELS",
    "NON_SPECULATIVE_TIERS",
    "RECOGNIZED_BLOCK_KEYS",
]
