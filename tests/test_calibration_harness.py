"""Section 7.2 calibration harness tests.

Per v3 spec Section 7.2 launch gates:
    * archetype-coverage agreement ≥80% across the 15-case test set
    * canonical SURVIVOR retrieval correctness ≥90%
    * canonical NON-SURVIVOR retrieval correctness ≥90%

These tests run the calibration harness against the realistic catalog fixture
and the 15-case calibration JSON. PASS gate is required before
launch-gate sign-off (Section 7.3a).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.counterfactual_veto.calibration import (
    ARCHETYPE_COVERAGE_GATE_PCT,
    CANONICAL_CORRECTNESS_GATE_PCT,
    CalibrationCase,
    CalibrationReport,
    load_calibration_cases_from_json,
    run_calibration,
)
from src.counterfactual_veto.retrieval import CatalogCase
from tests.fixtures.realistic_catalog import build_realistic_catalog


CALIBRATION_FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "calibration_15_cases.json"
)


@pytest.fixture
def calibration_cases() -> list[CalibrationCase]:
    return load_calibration_cases_from_json(CALIBRATION_FIXTURE_PATH)


@pytest.fixture
def calibration_catalog() -> list[CatalogCase]:
    return build_realistic_catalog()


def test_calibration_passes_section_7_2_gates(
    calibration_cases: list[CalibrationCase],
    calibration_catalog: list[CatalogCase],
) -> None:
    """Section 7.2 launch gate — must PASS on the 15-case test set.

    Asserts:
        - report.gate_status == 'PASS'
        - archetype-coverage agreement ≥ 80%
        - canonical SURVIVOR correctness ≥ 90%
        - canonical NON-SURVIVOR correctness ≥ 90%
    """
    report = run_calibration(calibration_cases, calibration_catalog)
    assert isinstance(report, CalibrationReport)
    assert report.gate_status == "PASS", (
        f"Calibration gate FAILED: {report.failures} | "
        f"coverage={report.archetype_coverage_agreement_pct}% "
        f"surv={report.canonical_survivor_correctness_pct}% "
        f"nsurv={report.canonical_non_survivor_correctness_pct}%"
    )
    assert report.archetype_coverage_agreement_pct >= ARCHETYPE_COVERAGE_GATE_PCT
    assert report.canonical_survivor_correctness_pct >= CANONICAL_CORRECTNESS_GATE_PCT
    assert (
        report.canonical_non_survivor_correctness_pct
        >= CANONICAL_CORRECTNESS_GATE_PCT
    )


def test_calibration_fixture_has_15_cases(
    calibration_cases: list[CalibrationCase],
) -> None:
    """Per Phase 4 Q3 — exactly 15 calibration cases across canonical buckets."""
    assert len(calibration_cases) == 15
    by_canon: dict[str, int] = {"SURVIVOR": 0, "NON-SURVIVOR": 0, "TBD": 0}
    for c in calibration_cases:
        by_canon[c.canonical_category] += 1
    assert by_canon["SURVIVOR"] == 5
    assert by_canon["NON-SURVIVOR"] == 5
    assert by_canon["TBD"] == 5


def test_per_case_failures_surface_actionably(
    calibration_catalog: list[CatalogCase],
) -> None:
    """A failing case should produce actionable failure-message diagnostics.

    Construct a deliberately impossible canonical SURVIVOR case (NON-SURVIVOR
    features against a catalog of NON-SURVIVOR cases) and verify the report
    surfaces the divergence in human-readable form.
    """
    bad_case = CalibrationCase(
        case_id="DELIBERATE-FAIL-CASE",
        candidate_sector="energy",
        candidate_universal_core={
            "founder_insider_stake_direction": "departed",
            "cash_runway": "distressed",
            "founder_in_place": "departed",
            "margin_trajectory": "deteriorating",
            "revenue_trajectory": "declining",
            "industry_tailwind": "structural-decline",
        },
        candidate_sector_extensions={},
        canonical_category="SURVIVOR",
        expected_archetype_distribution={"SURVIVOR": 3},
        expected_top_3_case_ids=None,
        notes="Adversarial: canonical SURVIVOR but features are NON-SURVIVOR-shaped",
    )
    report = run_calibration([bad_case], calibration_catalog)
    assert report.gate_status == "FAIL"
    assert report.canonical_survivor_correctness_pct < CANONICAL_CORRECTNESS_GATE_PCT
    failing = report.per_case_results[0]
    assert failing.failures, (
        "Expected per-case failures to be populated with actionable diagnostics"
    )
    # Diagnostic should mention which dimension diverged.
    joined = " ".join(failing.failures).lower()
    assert (
        "canonical-correctness" in joined or "archetype-coverage" in joined
    )
