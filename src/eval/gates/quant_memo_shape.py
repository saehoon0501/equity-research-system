"""Quantitative-analyst memo shape validator (HG-29).

Validates the schema emitted by quantitative-analyst per
`.claude/agents/analysts/quantitative-analyst.md`. Catches the structural
failure modes observed across the 11-PM-report audit + the MSFT bugs:

- Missing Overlay 1-5 fields (helmer_power_anchor, reinvestment_moat,
  outside_view, bull/bear_case_narrative).
- Missing dual-DCF emission (inherited + austere required for
  core_fundamental / thematic_growth tiers).
- Speculative-tier skip-string non-conformance (fields must be SKIPPED
  with the canonical sentinel string, not silently omitted).
- Quality-gate fields missing (Piotroski F-score, Altman Z'').
- Falsifier-date semantics (quarterly-observable references must use
  filing-date, not fiscal-quarter-end — HG-15.5a sub-rule).

DETERMINISM: pure stdlib + the existing falsifier_date helper. No I/O
beyond CLI.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from typing import Any

from src.eval.gates._frameworks_cited_shim import (
    find_framework as _shim_find_framework,
)

# Tier enum from quant-analyst.md.
VALID_TIERS: frozenset[str] = frozenset({
    "core_fundamental",
    "thematic_growth",
    "speculative_optionality",
})

# Frameworks every quant memo must cite. The audit found inconsistent
# omission of damodaran_narrative_dcf + austere_dcf for core/thematic
# tiers — both are load-bearing per HG-20 Bug-8/10.
REQUIRED_FRAMEWORKS_CORE_THEMATIC: frozenset[str] = frozenset({
    "damodaran_narrative_dcf",
    "austere_dcf",
    "mauboussin_reverse_dcf",
    "buffett_2007_inevitables",
})

# Required top-level keys for ALL tiers.
REQUIRED_TOP_LEVEL: tuple[str, ...] = (
    "analyst",
    "ticker",
    "tier",
    "quality_gate",
    "frameworks_cited",
    "evidence_index_refs",
    "banned_outputs_check",
)

# Required quality_gate sub-keys.
REQUIRED_QUALITY_GATE_KEYS: tuple[str, ...] = (
    "piotroski_f_score",
    "altman_z_double_prime",
    "passes_quality_gate",
)

# Required outside_view sub-keys (core/thematic only; speculative skips
# the entire block with the canonical sentinel).
REQUIRED_OUTSIDE_VIEW_KEYS: tuple[str, ...] = (
    "intuitive_growth_pct",
    "reference_class_growth_mean_pct",
    "reference_source",
    "cohort_values_placeholder",
    "r_coefficient_used",
    "corrected_growth_pct",
    "corrected_divergence_pp",
)

# Required reinvestment_moat sub-keys (inside buffett_2007_inevitables
# framework block; core/thematic only).
REQUIRED_REINVESTMENT_MOAT_KEYS: tuple[str, ...] = (
    "quality_label",
    "incremental_roic_3y_trailing_pct",
    "deployable_runway_years_est",
)

# Canonical Helmer Power enum (snake_case). Must match strategic-analyst
# memo for cross-agent consistency (Overlay 1).
CANONICAL_HELMER_POWERS: frozenset[str] = frozenset({
    "scale_economies",
    "network_economies",
    "counter_positioning",
    "switching_costs",
    "branding",
    "cornered_resource",
    "process_power",
})

# Sentinel emitted by quant when strategic brief hasn't yet resolved.
PENDING_STRATEGIC_SENTINEL = "PENDING_STRATEGIC_RESOLUTION"

# Canonical speculative-tier skip sentinel.
SPECULATIVE_SKIP_SENTINEL = "SKIPPED — speculative"

# Falsifier-date regex: quarter-end-style YYYY-(MM-end) dates that are
# semantically wrong for "FY{N} Q{M} print" references — should be the
# filing date (~28 days after quarter-end for most issuers), not the
# quarter-end. HG-15.5a per the audit.
QUARTERLY_OBSERVABLE_KEYWORDS = (
    "print", "10-q", "10-k", "earnings", "quarterly", "quarter", "report",
)
QUARTER_END_DATE_REGEX = re.compile(
    r"^\d{4}-(?:01-31|02-28|02-29|03-31|04-30|05-31|06-30|07-31|"
    r"08-31|09-30|10-31|11-30|12-31)$"
)


@dataclass
class QuantMemoShapeResult:
    """Result envelope for quant memo shape validation."""

    valid: bool
    tier: str | None = None
    missing_top_level: list[str] = field(default_factory=list)
    missing_quality_gate_keys: list[str] = field(default_factory=list)
    missing_outside_view_keys: list[str] = field(default_factory=list)
    missing_reinvestment_moat_keys: list[str] = field(default_factory=list)
    missing_frameworks: list[str] = field(default_factory=list)
    invalid_helmer_anchor: str | None = None
    falsifier_date_issues: list[str] = field(default_factory=list)
    speculative_skip_non_conformance: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _is_present_non_empty(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, (str, list, dict, tuple)) and len(value) == 0:
        return False
    return True


def _is_skip_sentinel(value: object) -> bool:
    """True iff value matches the canonical speculative-tier skip pattern."""
    if not isinstance(value, str):
        return False
    return SPECULATIVE_SKIP_SENTINEL.lower() in value.lower()


def _find_framework(memo: dict, framework_key: str) -> dict | None:
    """Thin wrapper preserving the historical signature; delegates to the
    shared dual-read shim so this module supports BOTH the legacy list form
    and the v3.1+ keyed-object form transparently per CAF-2."""
    return _shim_find_framework(memo, framework_key)


def _validate_outside_view(memo: dict, result: QuantMemoShapeResult) -> None:
    """Outside-view block presence + sub-key check (core/thematic only)."""
    ov = memo.get("outside_view")
    if result.tier == "speculative_optionality":
        # Must be skip-sentinel (string OR dict with skip note).
        if ov is None:
            result.notes.append(
                "tier=speculative_optionality: outside_view must be emitted "
                "as skip sentinel, not omitted"
            )
            result.speculative_skip_non_conformance.append("outside_view")
        return

    if not isinstance(ov, dict):
        result.missing_outside_view_keys = list(REQUIRED_OUTSIDE_VIEW_KEYS)
        return
    missing = [k for k in REQUIRED_OUTSIDE_VIEW_KEYS if not _is_present_non_empty(ov.get(k))]
    if missing:
        result.missing_outside_view_keys = missing


def _validate_reinvestment_moat(memo: dict, result: QuantMemoShapeResult) -> None:
    """Reinvestment_moat sub-block inside buffett_2007_inevitables framework.

    Core/thematic must have populated quality_label + roic + runway.
    Speculative may emit quality_label = "SKIPPED — speculative" but the
    block must still be PRESENT (not silently omitted).
    """
    buf = _find_framework(memo, "buffett_2007_inevitables")
    if buf is None or not isinstance(buf.get("output"), dict):
        if result.tier in ("core_fundamental", "thematic_growth"):
            result.missing_reinvestment_moat_keys = list(REQUIRED_REINVESTMENT_MOAT_KEYS)
            result.notes.append(
                "frameworks_cited missing buffett_2007_inevitables for "
                f"tier={result.tier}"
            )
        return

    rim = buf["output"].get("reinvestment_moat")
    if not isinstance(rim, dict):
        if result.tier in ("core_fundamental", "thematic_growth"):
            result.missing_reinvestment_moat_keys = list(REQUIRED_REINVESTMENT_MOAT_KEYS)
        return

    # quality_label is the load-bearing field — must be present always.
    if not _is_present_non_empty(rim.get("quality_label")):
        result.missing_reinvestment_moat_keys.append("quality_label")

    # For core/thematic, roic + runway must be numeric (not skip).
    if result.tier in ("core_fundamental", "thematic_growth"):
        ql = rim.get("quality_label")
        if not _is_skip_sentinel(ql):
            for k in ("incremental_roic_3y_trailing_pct", "deployable_runway_years_est"):
                v = rim.get(k)
                if v is None or _is_skip_sentinel(v):
                    result.missing_reinvestment_moat_keys.append(k)


def _validate_dual_dcf(memo: dict, result: QuantMemoShapeResult) -> None:
    """For core/thematic tiers: BOTH damodaran_narrative_dcf AND
    austere_dcf MUST be present and populated (not SKIPPED).
    HG-20 Bug 8/10."""
    if result.tier not in ("core_fundamental", "thematic_growth"):
        return
    for fk in ("damodaran_narrative_dcf", "austere_dcf"):
        fw = _find_framework(memo, fk)
        if fw is None:
            result.missing_frameworks.append(fk)
            continue
        out = fw.get("output")
        if not isinstance(out, dict):
            result.missing_frameworks.append(f"{fk}.output")
            continue
        # Check base case value is numeric.
        base = out.get("base_case_value")
        if base is None or _is_skip_sentinel(base):
            result.notes.append(
                f"{fk}.output.base_case_value missing or SKIPPED for "
                f"tier={result.tier}; both DCFs are load-bearing per HG-20"
            )


def _validate_helmer_anchor(memo: dict, result: QuantMemoShapeResult) -> None:
    """Bull-case helmer_power_anchor must be canonical snake_case OR the
    PENDING sentinel; not a free-form string."""
    if result.tier == "speculative_optionality":
        return
    dcf = _find_framework(memo, "damodaran_narrative_dcf")
    if dcf is None:
        return
    out = dcf.get("output") or {}
    bull = out.get("bull_case_narrative") or {}
    anchor = bull.get("helmer_power_anchor")
    if anchor is None:
        return  # presence captured elsewhere
    if not isinstance(anchor, str):
        result.invalid_helmer_anchor = str(anchor)
        return
    if anchor == PENDING_STRATEGIC_SENTINEL:
        return  # pending resolution is allowed
    if anchor not in CANONICAL_HELMER_POWERS:
        result.invalid_helmer_anchor = anchor


def _validate_falsifier_dates(memo: dict, result: QuantMemoShapeResult) -> None:
    """HG-15.5a: any falsifier referencing a quarterly print must NOT use
    fiscal-quarter-end date — the observable is the filing date."""
    if result.tier == "speculative_optionality":
        return
    dcf = _find_framework(memo, "damodaran_narrative_dcf")
    if dcf is None:
        return
    out = dcf.get("output") or {}
    for arm_name in ("bull_case_narrative", "bear_case_narrative"):
        arm = out.get(arm_name) or {}
        observable = arm.get("falsifying_observable")
        date_str = arm.get("falsifier_resolution_date")
        if not isinstance(date_str, str) or not isinstance(observable, str):
            continue
        observable_lower = observable.lower()
        is_quarterly = any(kw in observable_lower for kw in QUARTERLY_OBSERVABLE_KEYWORDS)
        if is_quarterly and QUARTER_END_DATE_REGEX.match(date_str):
            result.falsifier_date_issues.append(
                f"{arm_name}.falsifier_resolution_date={date_str} is a "
                "fiscal-quarter-end but observable references a print/"
                "filing — use the actual 10-Q/10-K filing date "
                "(~28 days after quarter-end)"
            )


def validate_quant_memo_shape(memo: object) -> QuantMemoShapeResult:
    """Validate a quant memo dict against the v0.2 schema.

    Returns:
        QuantMemoShapeResult with valid=True iff:
        (a) all REQUIRED_TOP_LEVEL keys present,
        (b) quality_gate has all required keys,
        (c) tier-appropriate Overlay 2 + 3+4 + dual-DCF emissions,
        (d) helmer_power_anchor canonical (or PENDING sentinel),
        (e) falsifier dates respect HG-15.5a.
    """
    if not isinstance(memo, dict):
        return QuantMemoShapeResult(
            valid=False,
            notes=[f"memo must be a dict; got {type(memo).__name__}"],
        )

    result = QuantMemoShapeResult(valid=True)
    tier = memo.get("tier")
    result.tier = tier if isinstance(tier, str) else None

    # Top-level presence.
    for k in REQUIRED_TOP_LEVEL:
        if not _is_present_non_empty(memo.get(k)):
            result.missing_top_level.append(k)

    if result.tier is not None and result.tier not in VALID_TIERS:
        result.notes.append(
            f"tier={result.tier!r} not in canonical enum {sorted(VALID_TIERS)}"
        )

    # Quality gate sub-keys.
    qg = memo.get("quality_gate")
    if isinstance(qg, dict):
        for k in REQUIRED_QUALITY_GATE_KEYS:
            if not _is_present_non_empty(qg.get(k)):
                result.missing_quality_gate_keys.append(k)

    _validate_outside_view(memo, result)
    _validate_reinvestment_moat(memo, result)
    _validate_dual_dcf(memo, result)
    _validate_helmer_anchor(memo, result)
    _validate_falsifier_dates(memo, result)

    if (
        result.missing_top_level
        or result.missing_quality_gate_keys
        or result.missing_outside_view_keys
        or result.missing_reinvestment_moat_keys
        or result.missing_frameworks
        or result.invalid_helmer_anchor is not None
        or result.falsifier_date_issues
        or result.speculative_skip_non_conformance
    ):
        result.valid = False

    return result


def _result_to_dict(r: QuantMemoShapeResult) -> dict[str, Any]:
    return {
        "valid": r.valid,
        "tier": r.tier,
        "missing_top_level": r.missing_top_level,
        "missing_quality_gate_keys": r.missing_quality_gate_keys,
        "missing_outside_view_keys": r.missing_outside_view_keys,
        "missing_reinvestment_moat_keys": r.missing_reinvestment_moat_keys,
        "missing_frameworks": r.missing_frameworks,
        "invalid_helmer_anchor": r.invalid_helmer_anchor,
        "falsifier_date_issues": r.falsifier_date_issues,
        "speculative_skip_non_conformance": r.speculative_skip_non_conformance,
        "notes": r.notes,
    }


def _cli(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="quant_memo_shape",
        description=(
            "Validate a quantitative-analyst memo shape against the v0.2 "
            "schema. Exit 0 valid, 1 invalid, 2 unparseable."
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

    result = validate_quant_memo_shape(memo)
    sys.stdout.write(json.dumps(_result_to_dict(result), indent=2) + "\n")
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(_cli())


__all__ = [
    "QuantMemoShapeResult",
    "validate_quant_memo_shape",
    "VALID_TIERS",
    "REQUIRED_TOP_LEVEL",
    "REQUIRED_QUALITY_GATE_KEYS",
    "REQUIRED_OUTSIDE_VIEW_KEYS",
    "REQUIRED_REINVESTMENT_MOAT_KEYS",
    "REQUIRED_FRAMEWORKS_CORE_THEMATIC",
    "CANONICAL_HELMER_POWERS",
    "PENDING_STRATEGIC_SENTINEL",
    "SPECULATIVE_SKIP_SENTINEL",
]
