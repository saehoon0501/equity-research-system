"""Section 7.2 calibration harness for the counterfactual VETO retrieval.

Per v3 spec Section 7.2 launch gates:

    * archetype-coverage agreement ≥80% across the 15-case test set
    * canonical SURVIVOR retrieval correctness ≥90%
    * canonical NON-SURVIVOR retrieval correctness ≥90%

This module provides:

    - ``CalibrationCase`` — one operator-pre-annotated test case (candidate
      features + expected archetype distribution + optional expected top-3
      case_ids).
    - ``CalibrationReport`` — aggregate output with PASS/FAIL gate status and
      per-case failure detail (which features didn't align).
    - ``run_calibration`` — runs each case through the retrieval, scores it
      against the operator annotation, and returns the report.

Methodology (Phase 4 Q3 lock):

    archetype-coverage agreement: per-case, the predicted top-3 archetype
    distribution must match the operator-pre-annotated distribution within
    ±1 in each bucket (SURVIVOR, DILUTED-SURVIVOR, NON-SURVIVOR). The 80%
    gate is computed as (cases passing within ±1) / (total cases).

    canonical correctness: for cases pre-annotated as canonical SURVIVOR
    (resp. canonical NON-SURVIVOR), the predicted dominant bucket must be
    SURVIVOR-leaning (resp. NON-SURVIVOR). The 90% gates are split across
    the two canonical pools.

Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
           Section 7.2 (calibration launch gates),
           Phase 4 Q3 (15-case calibration test set).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Optional

from .layer3_veto import is_survivor_dominant
from .retrieval import (
    CatalogCase,
    archetype_distribution,
    retrieve_top_3,
)


GateStatus = Literal["PASS", "FAIL"]
CanonicalCategory = Literal["SURVIVOR", "NON-SURVIVOR", "TBD"]


# Section 7.2 launch-gate thresholds.
ARCHETYPE_COVERAGE_GATE_PCT: float = 80.0
CANONICAL_CORRECTNESS_GATE_PCT: float = 90.0


@dataclass(frozen=True)
class CalibrationCase:
    """One operator-pre-annotated calibration row.

    Attributes:
        case_id:                            Stable identifier (e.g., 'PLTR-2022').
        candidate_sector:                   Canonical sector key for retrieval.
        candidate_universal_core:           6-feature universal-core dict.
        candidate_sector_extensions:        Sector-specific feature dict.
        canonical_category:                 'SURVIVOR' / 'NON-SURVIVOR' / 'TBD'
                                            — used by canonical-correctness gate.
        expected_archetype_distribution:    Operator-annotated count per bucket.
        expected_top_3_case_ids:            Optional expected top-3 case_ids
                                            (None when not deterministic).
        notes:                              Human-readable annotation context.
    """

    case_id: str
    candidate_sector: str
    candidate_universal_core: dict[str, str]
    candidate_sector_extensions: dict[str, str]
    canonical_category: CanonicalCategory
    expected_archetype_distribution: dict[str, int]
    expected_top_3_case_ids: Optional[list[str]] = None
    notes: str = ""


@dataclass(frozen=True)
class CalibrationCaseResult:
    """Per-case outcome of one calibration run."""

    case_id: str
    canonical_category: CanonicalCategory
    expected_distribution: dict[str, int]
    actual_distribution: dict[str, int]
    expected_top_3: Optional[list[str]]
    actual_top_3: list[str]
    archetype_coverage_match: bool       # within ±1 in each bucket
    canonical_correctness_match: Optional[bool]  # None for TBD canonical
    failures: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CalibrationReport:
    """Aggregate calibration outcome — pass/fail vs Section 7.2 gates."""

    per_case_results: list[CalibrationCaseResult]
    archetype_coverage_agreement_pct: float
    canonical_survivor_correctness_pct: float
    canonical_non_survivor_correctness_pct: float
    gate_status: GateStatus
    failures: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Fixture loader
# ---------------------------------------------------------------------------


def load_calibration_cases_from_json(path: str | Path) -> list[CalibrationCase]:
    """Load 15-case fixture from a JSON file.

    Schema::

        [
            {
                "case_id": "PLTR-2022",
                "candidate_sector": "tech_saas",
                "candidate_universal_core": {...},
                "candidate_sector_extensions": {...},
                "canonical_category": "TBD",
                "expected_archetype_distribution": {"SURVIVOR": 2, ...},
                "expected_top_3_case_ids": ["NVDA-2008", ...] | null,
                "notes": "..."
            },
            ...
        ]
    """
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    return [
        CalibrationCase(
            case_id=row["case_id"],
            candidate_sector=row["candidate_sector"],
            candidate_universal_core=dict(row["candidate_universal_core"]),
            candidate_sector_extensions=dict(row.get("candidate_sector_extensions") or {}),
            canonical_category=row["canonical_category"],
            expected_archetype_distribution=dict(row["expected_archetype_distribution"]),
            expected_top_3_case_ids=(
                list(row["expected_top_3_case_ids"])
                if row.get("expected_top_3_case_ids") is not None
                else None
            ),
            notes=row.get("notes", ""),
        )
        for row in raw
    ]


# ---------------------------------------------------------------------------
# Comparison helpers
# ---------------------------------------------------------------------------


def _distributions_within_one(
    expected: dict[str, int], actual: dict[str, int]
) -> bool:
    """True iff every bucket count differs by at most 1 (Phase 4 Q3 rule)."""
    keys = set(expected) | set(actual)
    for k in keys:
        if abs(expected.get(k, 0) - actual.get(k, 0)) > 1:
            return False
    return True


def _canonical_correctness(
    canonical: CanonicalCategory, actual: dict[str, int]
) -> Optional[bool]:
    """For canonical SURVIVOR/NON-SURVIVOR, did the dominant bucket match?

    Returns None for TBD canonical (no canonical answer to score against).
    """
    if canonical == "TBD":
        return None
    if canonical == "SURVIVOR":
        return is_survivor_dominant(actual)
    if canonical == "NON-SURVIVOR":
        return actual.get("NON-SURVIVOR", 0) >= 2
    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


# Type for the retrieve callable — allows tests to inject a stub retrieval
# function. Default is the live ``retrieve_top_3`` from retrieval.py.
RetrieveFn = Callable[..., list[Any]]


def _default_retrieve(
    *,
    candidate_sector: str,
    candidate_universal_core: dict[str, str],
    candidate_sector_extensions: dict[str, str],
    catalog: list[CatalogCase],
    k: int = 3,
) -> list[Any]:
    return retrieve_top_3(
        candidate_sector=candidate_sector,
        candidate_universal_core=candidate_universal_core,
        candidate_sector_extensions=candidate_sector_extensions,
        catalog=catalog,
        k=k,
    )


def run_calibration(
    test_cases: list[CalibrationCase],
    catalog: list[CatalogCase],
    *,
    retrieve_fn: Optional[RetrieveFn] = None,
) -> CalibrationReport:
    """Run the calibration harness against the supplied catalog + cases.

    Args:
        test_cases:   The 15-case calibration fixture (Phase 4 Q3).
        catalog:      Active retrieval pool (already HMAC-verified).
        retrieve_fn:  Optional retrieval callable (DI for tests). Defaults to
                      the live ``retrieve_top_3`` from retrieval.py.

    Returns:
        CalibrationReport with per-case results + aggregate gate status.
    """
    fn = retrieve_fn or _default_retrieve
    results: list[CalibrationCaseResult] = []

    for tc in test_cases:
        top = fn(
            candidate_sector=tc.candidate_sector,
            candidate_universal_core=tc.candidate_universal_core,
            candidate_sector_extensions=tc.candidate_sector_extensions,
            catalog=catalog,
            k=3,
        )
        actual_dist = archetype_distribution(top)
        actual_ids = [m.case.case_id for m in top]
        coverage_match = _distributions_within_one(
            tc.expected_archetype_distribution, actual_dist
        )
        canonical_match = _canonical_correctness(tc.canonical_category, actual_dist)

        per_failures: list[str] = []
        if not coverage_match:
            per_failures.append(
                f"archetype-coverage diverged: expected={dict(tc.expected_archetype_distribution)} "
                f"actual={dict(actual_dist)}"
            )
        if canonical_match is False:
            per_failures.append(
                f"canonical-correctness failed: canonical={tc.canonical_category} "
                f"actual_distribution={dict(actual_dist)}"
            )
        if tc.expected_top_3_case_ids is not None:
            missing = [c for c in tc.expected_top_3_case_ids if c not in actual_ids]
            if missing:
                per_failures.append(
                    f"expected top-3 case_ids {tc.expected_top_3_case_ids} "
                    f"not all retrieved (actual={actual_ids}); "
                    f"missing={missing}"
                )

        results.append(
            CalibrationCaseResult(
                case_id=tc.case_id,
                canonical_category=tc.canonical_category,
                expected_distribution=dict(tc.expected_archetype_distribution),
                actual_distribution=dict(actual_dist),
                expected_top_3=(
                    list(tc.expected_top_3_case_ids)
                    if tc.expected_top_3_case_ids is not None
                    else None
                ),
                actual_top_3=actual_ids,
                archetype_coverage_match=coverage_match,
                canonical_correctness_match=canonical_match,
                failures=per_failures,
            )
        )

    # Aggregates
    n_total = len(results) or 1
    n_coverage_pass = sum(1 for r in results if r.archetype_coverage_match)
    coverage_pct = 100.0 * n_coverage_pass / n_total

    surv_results = [r for r in results if r.canonical_category == "SURVIVOR"]
    nsurv_results = [r for r in results if r.canonical_category == "NON-SURVIVOR"]
    surv_pct = (
        100.0 * sum(1 for r in surv_results if r.canonical_correctness_match)
        / len(surv_results)
        if surv_results
        else 100.0
    )
    nsurv_pct = (
        100.0 * sum(1 for r in nsurv_results if r.canonical_correctness_match)
        / len(nsurv_results)
        if nsurv_results
        else 100.0
    )

    gate_failures: list[str] = []
    if coverage_pct < ARCHETYPE_COVERAGE_GATE_PCT:
        gate_failures.append(
            f"archetype-coverage {coverage_pct:.1f}% < gate "
            f"{ARCHETYPE_COVERAGE_GATE_PCT:.0f}%"
        )
    if surv_pct < CANONICAL_CORRECTNESS_GATE_PCT:
        gate_failures.append(
            f"canonical SURVIVOR {surv_pct:.1f}% < gate "
            f"{CANONICAL_CORRECTNESS_GATE_PCT:.0f}%"
        )
    if nsurv_pct < CANONICAL_CORRECTNESS_GATE_PCT:
        gate_failures.append(
            f"canonical NON-SURVIVOR {nsurv_pct:.1f}% < gate "
            f"{CANONICAL_CORRECTNESS_GATE_PCT:.0f}%"
        )

    status: GateStatus = "PASS" if not gate_failures else "FAIL"

    return CalibrationReport(
        per_case_results=results,
        archetype_coverage_agreement_pct=round(coverage_pct, 2),
        canonical_survivor_correctness_pct=round(surv_pct, 2),
        canonical_non_survivor_correctness_pct=round(nsurv_pct, 2),
        gate_status=status,
        failures=gate_failures,
    )


__all__ = [
    "ARCHETYPE_COVERAGE_GATE_PCT",
    "CANONICAL_CORRECTNESS_GATE_PCT",
    "CalibrationCase",
    "CalibrationCaseResult",
    "CalibrationReport",
    "load_calibration_cases_from_json",
    "run_calibration",
]
