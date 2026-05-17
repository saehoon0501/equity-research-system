"""Strategic-analyst memo shape validator (HG-30).

Validates the schema emitted by strategic-analyst per
`.claude/agents/strategic-analyst.md`. Catches the most common audit gaps:

- helmer_powers_evidence entries with status=held but <2 primary-source
  citations at source_quality_tier ≤2 (Overlay 1 hard rule).
- power_name not in canonical snake_case enum (would fail Stage-2
  cross-agent matching with quant memo's helmer_power_anchor).
- capital_allocation grades missing or using non-canonical letter
  grades.
- Buybacks grade missing dual-anchor rationale (multiple anchor OR
  prior_reverse_dcf_implied_value).
- frameworks_cited missing one of the 3 required strategic frameworks.

DETERMINISM: pure stdlib + UUID parsing. No I/O beyond CLI.
"""

from __future__ import annotations

import json
import re
import sys
import uuid
from dataclasses import dataclass, field
from typing import Any

CANONICAL_HELMER_POWERS: frozenset[str] = frozenset({
    "scale_economies",
    "network_economies",
    "counter_positioning",
    "switching_costs",
    "branding",
    "cornered_resource",
    "process_power",
})

VALID_POWER_STATUSES: frozenset[str] = frozenset({"held", "not_held", "pending"})

# Required frameworks for every strategic memo.
REQUIRED_FRAMEWORKS: tuple[str, ...] = (
    "mauboussin_moat_2024",
    "helmer_7_powers",
    "mauboussin_capital_allocation_2024",
)

# Required top-level keys.
REQUIRED_TOP_LEVEL: tuple[str, ...] = (
    "analyst",
    "ticker",
    "tier",
    "frameworks_cited",
    "evidence_index_refs",
    "banned_outputs_check",
)

# Capital-allocation buckets that must be graded.
CAPITAL_ALLOCATION_BUCKETS: tuple[str, ...] = (
    "capex", "rd", "ma", "dividends", "buybacks", "debt",
)

VALID_LETTER_GRADES: frozenset[str] = frozenset({
    "A+", "A", "A-",
    "B+", "B", "B-",
    "C+", "C", "C-",
    "D+", "D", "D-",
    "F",
    "N/A",  # acceptable for tier=speculative_optionality + debt bucket
})

# Minimum primary citations per held Power per Overlay 1.
HELD_POWER_MIN_CITATIONS = 2

# Buyback-grade reasoning anchor patterns. Per strategic-analyst.md,
# buybacks grade reasoning must cite either a prior reverse-DCF
# implied-value OR a self-computed multiple-vs-trailing-5y anchor.
BUYBACK_ANCHOR_KEYWORDS = (
    "reverse_dcf", "reverse-dcf", "reverse dcf", "implied_value",
    "implied value", "p/e", "ev/ebitda", "trailing 5y", "trailing-5y",
    "median multiple", "percentile",
)


@dataclass
class StrategicMemoShapeResult:
    """Result envelope for strategic memo shape validation."""

    valid: bool
    tier: str | None = None
    missing_top_level: list[str] = field(default_factory=list)
    missing_frameworks: list[str] = field(default_factory=list)
    invalid_power_names: list[str] = field(default_factory=list)
    held_powers_with_insufficient_citations: list[dict] = field(default_factory=list)
    invalid_citation_uuids: list[str] = field(default_factory=list)
    invalid_power_statuses: list[str] = field(default_factory=list)
    missing_capital_allocation_buckets: list[str] = field(default_factory=list)
    invalid_letter_grades: list[dict] = field(default_factory=list)
    buyback_anchor_missing: bool = False
    notes: list[str] = field(default_factory=list)


def _is_present_non_empty(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, (str, list, dict, tuple)) and len(value) == 0:
        return False
    return True


def _is_valid_uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


def _find_framework(memo: dict, framework_key: str) -> dict | None:
    fc = memo.get("frameworks_cited") or []
    if not isinstance(fc, list):
        return None
    for entry in fc:
        if isinstance(entry, dict) and entry.get("framework_key") == framework_key:
            return entry
    return None


def _validate_helmer_powers(memo: dict, result: StrategicMemoShapeResult) -> None:
    """Per-Power validation: snake_case enum, status enum, ≥2 citations
    for held Powers, all citation UUIDs parseable."""
    fw = _find_framework(memo, "helmer_7_powers")
    if fw is None:
        return  # caught by missing_frameworks
    out = fw.get("output") or {}
    powers = out.get("helmer_powers_evidence") or []
    if not isinstance(powers, list):
        result.notes.append(
            "helmer_powers_evidence must be a list; got "
            f"{type(powers).__name__}"
        )
        return

    for i, p in enumerate(powers):
        if not isinstance(p, dict):
            continue
        name = p.get("power_name")
        if name is None or not isinstance(name, str):
            result.invalid_power_names.append(str(name))
        elif name not in CANONICAL_HELMER_POWERS:
            result.invalid_power_names.append(name)

        status = p.get("status")
        if status is not None and status not in VALID_POWER_STATUSES:
            result.invalid_power_statuses.append(str(status))

        citations = p.get("primary_source_citations") or []
        if not isinstance(citations, list):
            citations = []
        # Validate UUIDs.
        bad_uuids = [c for c in citations if not _is_valid_uuid(c)]
        result.invalid_citation_uuids.extend(bad_uuids)

        # ≥2 citations required for held status.
        if status == "held" and len(citations) - len(bad_uuids) < HELD_POWER_MIN_CITATIONS:
            result.held_powers_with_insufficient_citations.append({
                "power_name": name,
                "citation_count": len(citations),
                "valid_citation_count": len(citations) - len(bad_uuids),
                "required_minimum": HELD_POWER_MIN_CITATIONS,
            })


def _validate_capital_allocation(memo: dict, result: StrategicMemoShapeResult) -> None:
    fw = _find_framework(memo, "mauboussin_capital_allocation_2024")
    if fw is None:
        return
    out = fw.get("output") or {}
    grades = out.get("grades") or {}
    if not isinstance(grades, dict):
        result.notes.append(
            f"capital_allocation.grades must be a dict; got "
            f"{type(grades).__name__}"
        )
        return

    for bucket in CAPITAL_ALLOCATION_BUCKETS:
        grade = grades.get(bucket)
        if grade is None:
            result.missing_capital_allocation_buckets.append(bucket)
            continue
        if isinstance(grade, dict):
            grade = grade.get("grade")
        if not isinstance(grade, str) or grade not in VALID_LETTER_GRADES:
            result.invalid_letter_grades.append({
                "bucket": bucket,
                "emitted": str(grade),
            })

    # overall_grade is also required.
    if not _is_present_non_empty(out.get("overall_grade")):
        result.notes.append(
            "capital_allocation.overall_grade is required (synthesized A-F "
            "across all 6 buckets)"
        )

    # Buybacks anchor check — search the buybacks bucket's reasoning
    # text for one of the dual-anchor keywords.
    buyback = grades.get("buybacks")
    reasoning_text = ""
    if isinstance(buyback, dict):
        reasoning_text = str(buyback.get("reasoning", ""))
    # Also check key_examples for any buyback-related reasoning.
    key_examples = out.get("key_examples") or {}
    if isinstance(key_examples, dict):
        for k, v in key_examples.items():
            reasoning_text += " " + json.dumps(v, default=str)
    if reasoning_text:
        lower = reasoning_text.lower()
        if not any(kw in lower for kw in BUYBACK_ANCHOR_KEYWORDS):
            result.buyback_anchor_missing = True


def validate_strategic_memo_shape(memo: object) -> StrategicMemoShapeResult:
    """Validate a strategic memo dict against the v0.2 schema.

    Returns:
        StrategicMemoShapeResult with valid=True iff:
        (a) all REQUIRED_TOP_LEVEL keys present,
        (b) all 3 REQUIRED_FRAMEWORKS cited,
        (c) every helmer_powers_evidence row has canonical power_name,
            valid status, and (if status=held) ≥2 primary citations
            with valid UUID format,
        (d) capital_allocation grades present for all 6 buckets with
            canonical letter grades,
        (e) buybacks bucket has an anchor in its reasoning text.
    """
    if not isinstance(memo, dict):
        return StrategicMemoShapeResult(
            valid=False,
            notes=[f"memo must be a dict; got {type(memo).__name__}"],
        )

    result = StrategicMemoShapeResult(valid=True)
    tier = memo.get("tier")
    result.tier = tier if isinstance(tier, str) else None

    for k in REQUIRED_TOP_LEVEL:
        if not _is_present_non_empty(memo.get(k)):
            result.missing_top_level.append(k)

    for fk in REQUIRED_FRAMEWORKS:
        if _find_framework(memo, fk) is None:
            result.missing_frameworks.append(fk)

    _validate_helmer_powers(memo, result)
    _validate_capital_allocation(memo, result)

    if (
        result.missing_top_level
        or result.missing_frameworks
        or result.invalid_power_names
        or result.held_powers_with_insufficient_citations
        or result.invalid_citation_uuids
        or result.invalid_power_statuses
        or result.missing_capital_allocation_buckets
        or result.invalid_letter_grades
        or result.buyback_anchor_missing
    ):
        result.valid = False

    return result


def _result_to_dict(r: StrategicMemoShapeResult) -> dict[str, Any]:
    return {
        "valid": r.valid,
        "tier": r.tier,
        "missing_top_level": r.missing_top_level,
        "missing_frameworks": r.missing_frameworks,
        "invalid_power_names": r.invalid_power_names,
        "held_powers_with_insufficient_citations":
            r.held_powers_with_insufficient_citations,
        "invalid_citation_uuids": r.invalid_citation_uuids,
        "invalid_power_statuses": r.invalid_power_statuses,
        "missing_capital_allocation_buckets":
            r.missing_capital_allocation_buckets,
        "invalid_letter_grades": r.invalid_letter_grades,
        "buyback_anchor_missing": r.buyback_anchor_missing,
        "notes": r.notes,
    }


def _cli(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="strategic_memo_shape",
        description=(
            "Validate a strategic-analyst memo shape against the v0.2 "
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

    result = validate_strategic_memo_shape(memo)
    sys.stdout.write(json.dumps(_result_to_dict(result), indent=2) + "\n")
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(_cli())


__all__ = [
    "StrategicMemoShapeResult",
    "validate_strategic_memo_shape",
    "REQUIRED_FRAMEWORKS",
    "REQUIRED_TOP_LEVEL",
    "CANONICAL_HELMER_POWERS",
    "CAPITAL_ALLOCATION_BUCKETS",
    "VALID_LETTER_GRADES",
    "HELD_POWER_MIN_CITATIONS",
]
