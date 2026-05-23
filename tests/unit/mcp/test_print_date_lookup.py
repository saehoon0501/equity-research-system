"""Unit tests for src.data_layer.print_date_lookup (Bug 12 fix).

Tests the pure-math layer only — the HTTP fetchers are smoke-tested
manually via the CLI (network-dependent, not in CI).
"""

from __future__ import annotations

import datetime as dt

import pytest

from src.data_layer.print_date_lookup import (
    PrintProjection,
    project_print_date,
)


# --------------------------------------------------------------------------
# MSFT historical Q2 (Dec-quarter) print dates from EDGAR (Bug 12 fixture).
# Lags: 28, 29, 30, 24 days. Median = 28.5 → rounded 28 days.
# Projecting from 2026-12-31 → 2027-01-28.
# --------------------------------------------------------------------------
MSFT_Q2_HISTORY = [
    (dt.date(2025, 12, 31), dt.date(2026, 1, 28)),
    (dt.date(2024, 12, 31), dt.date(2025, 1, 29)),
    (dt.date(2023, 12, 31), dt.date(2024, 1, 30)),
    (dt.date(2022, 12, 31), dt.date(2023, 1, 24)),
]


def test_msft_q2_projects_late_january_not_quarter_end():
    """The Bug 12 regression case: 2026-12-31 quarter-end must project to
    late-January 2027, not be reused as the falsifier_resolution_date."""
    target = dt.date(2026, 12, 31)
    proj = project_print_date(MSFT_Q2_HISTORY, target)

    assert proj.projected_print_date == dt.date(2027, 1, 28)
    assert proj.projected_print_date.month == 1
    assert proj.projected_print_date.year == 2027
    # Must be at least 3 weeks past the quarter-end (audit-trail guarantee).
    assert (proj.projected_print_date - target).days >= 21


def test_median_lag_and_distribution():
    proj = project_print_date(MSFT_Q2_HISTORY, dt.date(2026, 12, 31))
    assert proj.median_lag_days == 28  # median of [28, 29, 30, 24] = 28.5 → 28
    assert proj.lag_distribution_days == [24, 28, 29, 30]
    assert proj.n_historical_pairs == 4


def test_single_pair_returns_that_lag():
    pairs = [(dt.date(2025, 12, 31), dt.date(2026, 1, 28))]
    proj = project_print_date(pairs, dt.date(2026, 12, 31))
    assert proj.median_lag_days == 28
    assert proj.projected_print_date == dt.date(2027, 1, 28)


def test_empty_history_raises():
    with pytest.raises(ValueError, match="at least one"):
        project_print_date([], dt.date(2026, 12, 31))


def test_negative_lag_raises():
    bad_pairs = [(dt.date(2026, 1, 28), dt.date(2025, 12, 31))]  # filed BEFORE qe
    with pytest.raises(ValueError, match="lags must be positive"):
        project_print_date(bad_pairs, dt.date(2026, 12, 31))


def test_zero_lag_raises():
    bad_pairs = [(dt.date(2025, 12, 31), dt.date(2025, 12, 31))]  # same day
    with pytest.raises(ValueError, match="lags must be positive"):
        project_print_date(bad_pairs, dt.date(2026, 12, 31))


def test_projection_preserves_inputs():
    """Audit-trail: the returned PrintProjection echoes all inputs so an
    evaluator can verify the math from the envelope alone."""
    target = dt.date(2026, 12, 31)
    proj = project_print_date(MSFT_Q2_HISTORY, target)
    assert proj.target_quarter_end == target
    assert proj.historical_pairs == MSFT_Q2_HISTORY
    assert proj.source == "caller_supplied"


def test_projection_is_a_dataclass():
    """Confirms the return type is the documented PrintProjection."""
    proj = project_print_date(MSFT_Q2_HISTORY, dt.date(2026, 12, 31))
    assert isinstance(proj, PrintProjection)
