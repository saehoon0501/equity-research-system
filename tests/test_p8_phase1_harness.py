"""Tests for Phase 1 backtest harness (Section 2.1 v5-final acceptance gate)."""

import json
import tempfile
from pathlib import Path

import pytest

from src.p8_tactical_overlay.phase1_harness import (
    VALID_DISPOSITION_VALUES,
    Phase1Report,
    format_report,
    run_phase1,
)


def _make_envelope(tmpdir: str, run_id: str, ticker: str, conviction: str) -> str:
    """Write a minimal pm-supervisor envelope fixture."""
    env = {
        "ticker": ticker,
        "run_id": run_id,
        "conviction": conviction,
        "summary_code": "HOLD",
    }
    path = Path(tmpdir) / f"pm-supervisor__{run_id}.json"
    path.write_text(json.dumps(env))
    return str(path)


def test_empty_cohort_returns_empty_report():
    with tempfile.TemporaryDirectory() as tmpdir:
        report = run_phase1(tmpdir)
    assert report.cohort_size == 0
    assert report.all_dispositions_valid is True  # vacuously true


def test_single_envelope_high_conviction_positive_bin_emits_buy_high():
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_envelope(tmpdir, "run-1", "GOOGL", "HIGH")
        report = run_phase1(tmpdir, tactical_bin_injector=lambda env: "positive")
    assert report.cohort_size == 1
    assert report.results[0].cell_disposition == "BUY-HIGH"
    assert report.results[0].cell_size_pct == 6.0
    assert report.all_dispositions_valid is True


def test_medium_conviction_positive_emits_buy_med_load_bearing_case():
    """Section 2.1 v5: empirical 83% MEDIUM base rate → BUY-MED is load-bearing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_envelope(tmpdir, "run-1", "GOOGL", "MEDIUM")
        report = run_phase1(tmpdir, tactical_bin_injector=lambda env: "positive")
    assert report.results[0].cell_disposition == "BUY-MED"
    assert report.results[0].cell_size_pct == 3.0


def test_inv_2_1_a_all_dispositions_valid_across_cohort():
    """Phase 1 hard gate: all emitted dispositions must be in valid enum."""
    convictions = ["HIGH", "MEDIUM", "LOW", "HIGH", "MEDIUM"]
    bins = ["positive", "neutral", "negative", "unavailable", "positive"]
    with tempfile.TemporaryDirectory() as tmpdir:
        for i, conv in enumerate(convictions):
            _make_envelope(tmpdir, f"run-{i}", "GOOGL", conv)
        report = run_phase1(
            tmpdir,
            tactical_bin_injector=lambda env, _idx=[0]: bins[_idx[0]] if _idx[0] < len(bins) else "positive",
        )
    # Each disposition must be in the disjoint tactical_disposition enum
    for r in report.results:
        assert r.cell_disposition in VALID_DISPOSITION_VALUES
    assert report.all_dispositions_valid is True
    assert report.invalid_dispositions == []


def test_envelope_with_missing_conviction_skipped():
    with tempfile.TemporaryDirectory() as tmpdir:
        env = {"ticker": "GOOGL", "run_id": "broken"}
        Path(tmpdir, "pm-supervisor__broken.json").write_text(json.dumps(env))
        report = run_phase1(tmpdir)
    assert report.cohort_size == 0
    assert any("no valid conviction" in n for n in report.notes)


def test_corrupt_envelope_skipped_with_note():
    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "pm-supervisor__bad.json").write_text("not json{")
        report = run_phase1(tmpdir)
    assert report.cohort_size == 0
    assert any("parse failure" in n for n in report.notes)


def test_context_sidecar_ignored():
    """*.context.json files should NOT be loaded as envelopes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "pm-supervisor__run-1.context.json").write_text('{"context": "data"}')
        _make_envelope(tmpdir, "run-1", "GOOGL", "HIGH")
        report = run_phase1(tmpdir, tactical_bin_injector=lambda env: "positive")
    assert report.cohort_size == 1
    assert report.results[0].cell_disposition == "BUY-HIGH"


def test_ticker_filter_applied():
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_envelope(tmpdir, "run-1", "GOOGL", "HIGH")
        _make_envelope(tmpdir, "run-2", "MSFT", "MEDIUM")
        _make_envelope(tmpdir, "run-3", "GOOGL", "MEDIUM")
        report = run_phase1(
            tmpdir, ticker="GOOGL",
            tactical_bin_injector=lambda env: "positive",
        )
    assert report.cohort_size == 2
    assert all(r.ticker == "GOOGL" for r in report.results)


def test_low_conviction_with_unavailable_bin_is_hold_not_avoid():
    """Section 2.1 v4 fix: LOW × Unavailable → HOLD (data-insufficiency defers)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_envelope(tmpdir, "run-1", "RDDT", "LOW")
        report = run_phase1(tmpdir, tactical_bin_injector=lambda env: "unavailable")
    assert report.results[0].cell_disposition == "HOLD"
    assert report.results[0].cell_size_pct == 0.0  # LOW row hard-zeroed regardless


def test_disposition_counts_aggregated():
    with tempfile.TemporaryDirectory() as tmpdir:
        for i in range(3):
            _make_envelope(tmpdir, f"run-{i}", "GOOGL", "MEDIUM")
        report = run_phase1(tmpdir, tactical_bin_injector=lambda env: "positive")
    assert report.disposition_counts == {"BUY-MED": 3}
    assert report.cohort_size == 3


def test_format_report_human_readable():
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_envelope(tmpdir, "run-1", "GOOGL", "HIGH")
        _make_envelope(tmpdir, "run-2", "GOOGL", "MEDIUM")
        report = run_phase1(tmpdir, tactical_bin_injector=lambda env: "positive")
    text = format_report(report)
    assert "Phase 1 cohort size: 2" in text
    assert "INV-2.1-A" in text
    assert "BUY-HIGH" in text or "BUY-MED" in text
