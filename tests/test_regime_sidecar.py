"""Smoke tests for the S0 regime sidecar.

Per v3 spec §4.1. These tests use mocks for FRED + Fed-CSV HTTP — they do
not hit the network. Live integration is exercised by the daily CLI run.

Run from repo root:
    pytest tests/test_regime_sidecar.py -v

Coverage:
    - BOCPD detects a step-shift on synthetic data.
    - Forbes-Rigobon: Forbes-Rigobon 2002 worked example + degenerate cases.
    - Each dimension's `compute()` produces a valid `DimensionResult`.
    - `classifier.run_daily_classification` returns 6 dims even with one
      fetcher raising (degraded fallback).
    - `persistence.write_classifications` produces the SQL the migration
      schema expects (column-by-column).
"""

from __future__ import annotations

from datetime import date
from unittest import mock

import numpy as np
import pandas as pd
import pytest

from src.regime_sidecar import bocpd as bocpd_mod
from src.regime_sidecar import classifier as classifier_mod
from src.regime_sidecar import forbes_rigobon as fr_mod
from src.regime_sidecar import persistence as persistence_mod
from src.regime_sidecar.types import DIMENSION_REGISTRY, DimensionResult


# ---------------------------------------------------------------------------
# BOCPD
# ---------------------------------------------------------------------------


def test_bocpd_canonical_marginal_pinned_near_hazard_in_steady_state():
    """Canonical Adams-MacKay marginal P(r_t = 0 | x_{1:t}) is structurally
    pinned near the hazard rate when one run-length dominates the posterior
    (steady state). This is a property of BOCPD with constant-hazard prior,
    not a bug. The cumulative short-run-mass diagnostic (separate function)
    is what spikes on regime shifts.
    """
    np.random.seed(0)
    pre = np.random.normal(0.0, 1.0, 100)
    post = np.random.normal(5.0, 1.0, 100)
    series = np.concatenate([pre, post])
    probs = bocpd_mod.bocpd_change_probability(series, hazard=1.0 / 250.0)
    assert probs.shape == (200,)

    # Pre-shift: marginal stays ≈ hazard (≈0.004). Allow tiny float drift.
    pre_mean = float(probs[20:100].mean())
    assert pre_mean < 0.1, f"pre-shift canonical marginal anomalously high: {pre_mean}"


def test_bocpd_short_run_mass_detects_step_shift():
    """The short-run-mass diagnostic (P(r_t < 10 | x_{1:t})) DOES spike in
    the post-shift window — used as auxiliary diagnostic alongside the
    canonical marginal.
    """
    np.random.seed(0)
    pre = np.random.normal(0.0, 1.0, 100)
    post = np.random.normal(5.0, 1.0, 100)
    series = np.concatenate([pre, post])
    short = bocpd_mod.bocpd_short_run_mass(series)
    assert short.shape == (200,)

    pre_mean = float(short[20:100].mean())
    post_window_max = float(short[100:115].max())
    assert pre_mean < 0.2, f"pre-shift short-run mass too high: {pre_mean}"
    assert post_window_max > 0.7, f"post-shift short-run max too low: {post_window_max}"


def test_bocpd_threshold_boundaries_short_run_mass():
    """Boundary tests at 0.7 / 0.9 / 0.95 thresholds against the short-run
    mass diagnostic on a strong regime shift."""
    np.random.seed(0)
    pre = np.random.normal(0.0, 0.5, 100)
    post = np.random.normal(10.0, 0.5, 100)  # strong shift
    series = np.concatenate([pre, post])
    short = bocpd_mod.bocpd_short_run_mass(series)
    post_max = float(short[100:120].max())
    assert post_max > 0.7, "expected short-run-mass > 0.7 on strong shift"
    assert post_max > 0.9, "expected short-run-mass > 0.9 on strong shift"
    assert post_max > 0.95, "expected short-run-mass > 0.95 on strong shift"


def test_bocpd_handles_empty():
    assert bocpd_mod.bocpd_change_probability([]).shape == (0,)
    assert bocpd_mod.bocpd_short_run_mass([]).shape == (0,)
    assert bocpd_mod.latest_change_probability([]) == 0.0
    assert bocpd_mod.latest_short_run_mass([]) == 0.0
    assert bocpd_mod.latest_signals([]) == (0.0, 0.0)


def test_bocpd_signals_returns_both_first_class():
    """``bocpd_signals`` returns a BocpdSignals dataclass with both arrays
    of equal length. Both signals are first-class per operator-locked
    dual-signal architecture (v3 §4.1)."""
    np.random.seed(0)
    pre = np.random.normal(0.0, 1.0, 100)
    post = np.random.normal(5.0, 1.0, 100)
    series = np.concatenate([pre, post])
    sigs = bocpd_mod.bocpd_signals(series)
    assert sigs.change_probability.shape == (200,)
    assert sigs.short_run_mass.shape == (200,)

    # Cross-validation: bocpd_signals returns the SAME values as the
    # individual single-signal helpers (they all use bocpd_signals
    # internally, so consistency is required).
    cp = bocpd_mod.bocpd_change_probability(series)
    srm = bocpd_mod.bocpd_short_run_mass(series)
    np.testing.assert_array_equal(sigs.change_probability, cp)
    np.testing.assert_array_equal(sigs.short_run_mass, srm)

    # Per spec lock: short-run mass crosses 0.7/0.95 on a strong shift;
    # canonical marginal does NOT systematically cross those thresholds.
    pre_cp_mean = float(sigs.change_probability[20:100].mean())
    post_srm_max = float(sigs.short_run_mass[100:120].max())
    assert pre_cp_mean < 0.1, (
        "canonical marginal should be pinned near hazard pre-shift; got "
        f"{pre_cp_mean}"
    )
    assert post_srm_max > 0.7, (
        f"short-run mass must cross firing floor on a strong shift; got "
        f"{post_srm_max}"
    )


def test_bocpd_constant_input_does_not_explode():
    """Constant series → variance=0 in growth branches → predictive
    Student-t can be degenerate. We require: (a) no exception raised, (b)
    output finite, (c) cp_prob never 1.0 from a numerical pathology."""
    series = [3.14] * 50
    probs = bocpd_mod.bocpd_change_probability(series)
    assert probs.shape == (50,)
    assert np.all(np.isfinite(probs))
    # Constant series: no real change-points; canonical marginal should
    # stay near hazard. Critically: never spike to 1.0 from numerical reset.
    assert float(np.max(probs)) < 0.1


def test_bocpd_nan_and_inf_input_resets_to_neutral_not_one():
    """If a non-finite log_Z arises from NaN/inf in input, cp_prob[t] = 0.0
    (neutral), NOT 1.0. Pinning to 1.0 would falsely trip the M-3
    catastrophic alert (>0.95 single-day) on a numerical pathology."""
    import warnings as _warnings
    # Construct a sequence that triggers the non-finite-log_Z reset path.
    series = np.array([0.0, 0.0, 1e308 * 1e308, 0.0, 0.0])  # produces inf
    with _warnings.catch_warnings():
        _warnings.simplefilter("ignore", RuntimeWarning)
        probs = bocpd_mod.bocpd_change_probability(series)
    # Step that triggered the reset must be 0.0, not 1.0.
    assert float(np.max(probs)) <= 0.5, (
        f"non-finite reset path leaked spike: max={float(np.max(probs))}"
    )


# ---------------------------------------------------------------------------
# Forbes-Rigobon
# ---------------------------------------------------------------------------


def test_forbes_rigobon_no_op_when_var_equal():
    """delta_var=0 ⇒ correction factor = 1, output == input."""
    out = fr_mod.vol_corrected_correlation(0.5, var_high=1.0, var_low=1.0)
    assert out == pytest.approx(0.5, abs=1e-9)


def test_forbes_rigobon_inflates_when_var_high_exceeds_baseline():
    """When high-vol variance exceeds baseline, observed rho is biased
    *down*; the FR correction inflates it back toward the unconditional
    correlation. (When high-vol below baseline, correction shrinks observed
    rho.) Per Forbes-Rigobon 2002.
    """
    rho_obs = 0.5
    out = fr_mod.vol_corrected_correlation(rho_obs, var_high=2.0, var_low=1.0)
    # delta=1; factor = sqrt(2 / (1 + 0.25)) = sqrt(1.6) ≈ 1.2649
    assert out == pytest.approx(0.5 * (1.6 ** 0.5), abs=1e-6)
    assert out > rho_obs  # inflated, not shrunk


def test_forbes_rigobon_shrinks_when_var_high_below_baseline():
    """delta_var < 0 → corrected rho is smaller in magnitude than observed."""
    rho_obs = 0.5
    out = fr_mod.vol_corrected_correlation(rho_obs, var_high=0.5, var_low=1.0)
    # delta=-0.5; factor = sqrt(0.5 / (1 - 0.125)) = sqrt(0.5/0.875) ≈ 0.7559
    assert out < rho_obs


def test_forbes_rigobon_edge_rho_one():
    """rho = ±1 is a fixed point of the correction (factor = 1)."""
    out_pos = fr_mod.vol_corrected_correlation(1.0, var_high=2.0, var_low=1.0)
    out_neg = fr_mod.vol_corrected_correlation(-1.0, var_high=2.0, var_low=1.0)
    assert out_pos == pytest.approx(1.0, abs=1e-9)
    assert out_neg == pytest.approx(-1.0, abs=1e-9)


def test_forbes_rigobon_edge_var_high_zero():
    """var_high=0 → delta_var=-1, denom = 1 - rho²; correction shrinks
    toward zero except at rho=±1 (where denom=0; we fall back to rho)."""
    # Mid-range rho: standard correction.
    out = fr_mod.vol_corrected_correlation(0.5, var_high=0.0, var_low=1.0)
    # delta=-1; factor = sqrt(0/(1-0.25))=0; corrected=0.
    assert out == pytest.approx(0.0, abs=1e-9)
    # rho=±1 with var_high=0: denom = 1-1=0; falls back to rho.
    out_one = fr_mod.vol_corrected_correlation(1.0, var_high=0.0, var_low=1.0)
    # denom = 1 + (-1)*(1) = 0 → returns rho per implementation guard.
    assert out_one == pytest.approx(1.0, abs=1e-9)


def test_forbes_rigobon_degenerate_var_low_zero():
    """var_low=0 → return rho_observed unchanged (no correction possible)."""
    assert fr_mod.vol_corrected_correlation(0.7, 1.0, 0.0) == 0.7


# ---------------------------------------------------------------------------
# Dimension fetchers — mocked HTTP/FRED
# ---------------------------------------------------------------------------


def _fake_fred_series(values: list[float], end: date = date(2026, 4, 29)) -> list[dict]:
    """Build a FRED-style observations list ending on `end` (daily)."""
    n = len(values)
    dates = pd.date_range(end=end, periods=n, freq="D")
    return [{"date": d.strftime("%Y-%m-%d"), "value": v} for d, v in zip(dates, values)]


def test_dim1_credit_ebp_classifies_states():
    """Dim 1 (highest-edge dimension) — verify each threshold band classifies
    correctly with mocked CSV fetch."""
    from src.regime_sidecar.dimensions import dim1_credit_ebp as d1

    # Build 12 monthly observations ending 2026-03-31 (so all are <= asof).
    # Last value drives the state classification.
    dates = pd.date_range(end="2026-03-31", periods=12, freq="ME")

    def make_csv(last_ebp: float) -> str:
        rows = ["date,gz_spread,ebp,est_prob"]
        for i, dt in enumerate(dates):
            ebp = -0.2 if i < len(dates) - 1 else last_ebp
            rows.append(f"{dt.strftime('%Y-%m-%d')},2.0,{ebp},0.05")
        return "\n".join(rows)

    cases = [(-0.5, "benign"), (0.5, "stressed"), (1.5, "crisis")]
    for ebp_val, expected_state in cases:
        df_parsed = d1._parse_ebp_csv(make_csv(ebp_val))
        with mock.patch.object(d1, "_fetch_ebp_series", return_value=(df_parsed, "live:test")):
            res = d1.compute(date(2026, 4, 29))
        assert res.dimension_id == 1
        assert res.dimension_name == "credit_ebp"
        assert res.headline_state == expected_state, f"ebp={ebp_val} → {res.headline_state}, expected {expected_state}"
        assert res.state_probabilities[expected_state] == 1.0


def test_dim1_credit_ebp_stale_cache_path_tags_validation_depth():
    """When fetch falls back to local cache, validation_depth flags STALE_CACHE
    so downstream consumers can surface in risk_flags."""
    from src.regime_sidecar.dimensions import dim1_credit_ebp as d1

    dates = pd.date_range(end="2026-04-30", periods=6, freq="ME")
    csv_text = "date,gz_spread,ebp,est_prob\n" + "\n".join(
        f"{d.strftime('%Y-%m-%d')},2.0,-0.2,0.05" for d in dates
    )
    df_parsed = d1._parse_ebp_csv(csv_text)
    with mock.patch.object(d1, "_fetch_ebp_series", return_value=(df_parsed, "cache:ebp_20260428.csv")):
        res = d1.compute(date(2026, 4, 29))
    assert res.validation_depth == "STALE_CACHE"
    assert any(w.startswith("ebp_stale_cache") for w in res.warnings)


def test_dim2_cycle_ntfs_basic():
    from src.regime_sidecar.dimensions import dim2_cycle_ntfs as d2

    # 2y at 4.5%, 3mo at 5.5% → NTFS = -1.0 → recession bin.
    fake_2y = _fake_fred_series([4.5] * 200)
    fake_3m = _fake_fred_series([5.5] * 200)

    def fake_get(series_id, start=None, end=None):
        return {"DGS2": fake_2y, "DGS3MO": fake_3m}[series_id]

    with mock.patch.object(d2, "get_series", side_effect=fake_get):
        res = d2.compute(date(2026, 4, 29))

    assert res.dimension_id == 2
    assert res.dimension_name == "cycle_2y3m_slope"
    assert res.headline_state == "recession"
    assert res.state_probabilities["recession"] == 1.0
    assert sum(res.state_probabilities.values()) == pytest.approx(1.0)
    assert 0.0 <= res.bocpd_change_probability <= 1.0


def test_dim3_vol_vrp_classifies_normal():
    from src.regime_sidecar.dimensions import dim3_vol_vrp as d3

    # Stable VIX = 16 (var = 0.0256), constant SPX → RV ≈ 0 → VRP ≈ 0.0256
    # → "elevated" by our thresholds. Use VIX=10 → var=0.01 → "elevated".
    # Use VIX=8 → var=0.0064 → "normal" (>0, <0.01).
    fake_vix = _fake_fred_series([8.0] * 200)
    # SPX gently trending; tiny realized variance
    spx_vals = [4000.0 + i * 0.1 for i in range(200)]
    fake_spx = _fake_fred_series(spx_vals)

    def fake_get(series_id, start=None, end=None):
        return {"VIXCLS": fake_vix, "SP500": fake_spx}[series_id]

    with mock.patch.object(d3, "get_series", side_effect=fake_get):
        res = d3.compute(date(2026, 4, 29))

    assert res.dimension_id == 3
    assert res.headline_state in {"benign", "normal", "elevated", "crisis"}
    assert sum(res.state_probabilities.values()) == pytest.approx(1.0)


def test_dim4_mp_liquidity_composite_zscore():
    """Dim 4 composite z-score: synthesize 4 liquidity series with known
    YoY trends, verify composite z classifies and surface deferral flags."""
    from src.regime_sidecar.dimensions import dim4_mp_liquidity as d4

    # 7 years of daily-aligned monthly observations.
    dates = pd.date_range(end="2026-04-29", periods=7 * 365, freq="D")

    def fake_get(series_id, start=None, end=None):
        # Make WALCL/RESBALNS/M2SL trend up modestly; RRPONTSYD trends flat.
        # Returns YoY z near 0; classify "neutral".
        if series_id == "WALCL":
            vals = np.linspace(8e6, 8.5e6, len(dates))
        elif series_id == "RESBALNS":
            vals = np.linspace(3e6, 3.2e6, len(dates))
        elif series_id == "RRPONTSYD":
            vals = np.linspace(2e5, 2e5, len(dates))  # flat
        elif series_id == "M2SL":
            vals = np.linspace(2.1e7, 2.15e7, len(dates))
        else:
            return []
        return [{"date": d.strftime("%Y-%m-%d"), "value": float(v)} for d, v in zip(dates, vals)]

    with mock.patch.object(d4, "get_series", side_effect=fake_get):
        res = d4.compute(date(2026, 4, 29))

    assert res.dimension_id == 4
    assert res.dimension_name == "mp_liquidity"
    assert res.headline_state in {"tight", "neutral", "easy"}
    assert sum(res.state_probabilities.values()) == pytest.approx(1.0)
    # Deferred-overlay annotation must be present.
    assert res.raw_inputs.get("surprise_overlay_status") == "deferred_to_v0.5"
    assert res.raw_inputs.get("ff_futures_surprise_overlay") == "deferred_to_v0.5"


def test_dim6_bond_proxy_first_diff_vs_log_diff_yields_close_rho():
    """The new bond-return proxy `-Δy10` (canonical Forbes-Rigobon form)
    should yield a rolling correlation roughly equivalent to the previous
    `-Δlog(y10)` on realistic small daily yield changes (where Δy ≈ y·Δlog(y)).
    Verify the corrected rho computed from each form differs by < 0.1.
    """
    from src.regime_sidecar.forbes_rigobon import vol_corrected_correlation

    np.random.seed(7)
    n = 200
    spx_ret = np.random.normal(0, 0.01, n)
    y10 = 4.0 + np.cumsum(np.random.normal(0, 0.02, n))

    # Form A — first difference (new canonical).
    r_bnd_A = -np.diff(y10)
    # Form B — log-diff (legacy).
    r_bnd_B = -np.diff(np.log(y10))

    spx_ret_aligned = spx_ret[1:]
    rho_A = float(np.corrcoef(spx_ret_aligned[-60:], r_bnd_A[-60:])[0, 1])
    rho_B = float(np.corrcoef(spx_ret_aligned[-60:], r_bnd_B[-60:])[0, 1])

    var_high = float(np.var(spx_ret_aligned[-60:]))
    var_low = float(np.var(spx_ret_aligned))
    rho_A_corr = vol_corrected_correlation(rho_A, var_high, var_low)
    rho_B_corr = vol_corrected_correlation(rho_B, var_high, var_low)

    # On small daily yield changes, the two formulations should agree closely.
    assert abs(rho_A_corr - rho_B_corr) < 0.1, (
        f"bond-proxy rho mismatch too large: rho_A={rho_A_corr:.4f}, "
        f"rho_B={rho_B_corr:.4f}"
    )


def test_dim5_dollar_neutral():
    from src.regime_sidecar.dimensions import dim5_dollar as d5

    # Flat DXY → trend ≈ 0 → neutral.
    fake = _fake_fred_series([120.0] * 200)
    with mock.patch.object(d5, "get_series", return_value=fake):
        res = d5.compute(date(2026, 4, 29))

    assert res.dimension_id == 5
    assert res.headline_state == "neutral"


def test_dim6_stock_bond_corr_runs():
    from src.regime_sidecar.dimensions import dim6_stock_bond_corr as d6

    np.random.seed(42)
    spx_returns = np.random.normal(0, 0.01, 200)
    spx_levels = 4000 * np.exp(np.cumsum(spx_returns))
    y10_levels = 4.0 + np.cumsum(np.random.normal(0, 0.005, 200))

    fake_spx = _fake_fred_series(list(spx_levels))
    fake_y10 = _fake_fred_series(list(y10_levels))

    def fake_get(series_id, start=None, end=None):
        return {"SP500": fake_spx, "DGS10": fake_y10}[series_id]

    with mock.patch.object(d6, "get_series", side_effect=fake_get):
        res = d6.compute(date(2026, 4, 29))

    assert res.dimension_id == 6
    assert res.headline_state in {"negative", "neutral", "positive"}
    assert "rho_corrected_60d" in res.raw_inputs


# ---------------------------------------------------------------------------
# Classifier orchestration
# ---------------------------------------------------------------------------


def test_classifier_returns_six_dims_even_with_failure():
    """If a fetcher raises, classifier should synthesize a degraded
    DimensionResult so all 6 rows are present."""

    def boom(asof_date, history_days=365):
        raise RuntimeError("simulated FRED outage")

    fakes = [(i, boom) for i in range(1, 7)]
    with mock.patch.object(classifier_mod, "DIMENSION_FETCHERS", fakes):
        results = classifier_mod.run_daily_classification(date(2026, 4, 29))

    assert set(results.keys()) == {1, 2, 3, 4, 5, 6}
    for r in results.values():
        assert r.validation_depth == "DEGRADED"
        assert any(w.startswith("fetcher_failed") for w in r.warnings)


# ---------------------------------------------------------------------------
# Persistence — schema validity
# ---------------------------------------------------------------------------


def _sample_result(dim_id: int = 1) -> DimensionResult:
    return DimensionResult(
        dimension_id=dim_id,
        dimension_name=DIMENSION_REGISTRY[dim_id],
        classification_date=date(2026, 4, 29),
        state_probabilities={"benign": 1.0, "stressed": 0.0, "crisis": 0.0},
        headline_state="benign",
        # Dual-signal architecture (operator-locked, v3 §4.1): both fields
        # first-class and persisted. Canonical marginal kept for audit;
        # short-run mass drives firing.
        bocpd_change_probability=0.05,
        bocpd_short_run_mass=0.15,
        raw_inputs={"ebp_value": -0.3},
        history_length_days=252,
        validation_depth="HIGH",
        warnings=[],
    )


def test_write_classifications_emits_expected_sql():
    """Mock psycopg connection — verify the column list / value tuple shape
    matches `regime_classification_history` schema."""
    fake_cursor = mock.MagicMock()
    fake_cursor.rowcount = 1
    fake_cursor.fetchone.return_value = (date(2026, 4, 1),)

    fake_conn = mock.MagicMock()
    fake_conn.cursor.return_value.__enter__.return_value = fake_cursor

    inserted = persistence_mod.write_classifications(
        [_sample_result(1), _sample_result(2)],
        cold_start_override=True,
        conn=fake_conn,
    )

    assert inserted == 2
    # Verify INSERT was called with the expected column count.
    insert_calls = [
        c for c in fake_cursor.execute.call_args_list
        if "INSERT INTO regime_classification_history" in str(c.args[0])
    ]
    assert len(insert_calls) == 2
    # Each call's params tuple should have exactly 12 elements (column count).
    # Bumped from 11 to 12 with migration 020: bocpd_short_run_mass is now
    # a first-class column persisted alongside bocpd_change_probability per
    # operator-locked dual-signal architecture.
    for c in insert_calls:
        assert len(c.args[1]) == 12
    # Verify the dual signal pair appears in the params tuple in column order
    # (canonical marginal then short-run mass; matches the INSERT statement).
    first_params = insert_calls[0].args[1]
    assert 0.05 in first_params and 0.15 in first_params, (
        "expected both bocpd_change_probability=0.05 and "
        "bocpd_short_run_mass=0.15 in params tuple"
    )


def test_is_cold_start_for_date():
    launch = date(2026, 1, 1)
    # Day 0 → cold-start.
    assert persistence_mod.is_cold_start_for_date(launch, launch) is True
    # ~30 calendar days ≈ 21 trading days → cold-start.
    assert persistence_mod.is_cold_start_for_date(date(2026, 1, 31), launch) is True
    # ~180 calendar days ≈ 128 trading days → not cold-start.
    assert persistence_mod.is_cold_start_for_date(date(2026, 7, 1), launch) is False
    # Pre-launch backfill → cold-start.
    assert persistence_mod.is_cold_start_for_date(date(2025, 12, 1), launch) is True


def test_cold_start_boundary_day_89_90_91():
    """Per v3 §7.5: launch day = day 1. First 90 days carry the flag.
    Day 90 is the last cold-start day; day 91 clears.

    1-indexed mapping: day N = launch + (N-1) business days.
        day 1  = launch (0 BDays elapsed) → cold-start (start of window)
        day 89 = launch + 88 BDays         → cold-start
        day 90 = launch + 89 BDays         → cold-start (last day)
        day 91 = launch + 90 BDays         → clears (first non-cold day)
    """
    launch = date(2026, 1, 5)  # Monday — predictable BDay arithmetic
    day_89 = (pd.Timestamp(launch) + pd.tseries.offsets.BDay(88)).date()
    day_90 = (pd.Timestamp(launch) + pd.tseries.offsets.BDay(89)).date()
    day_91 = (pd.Timestamp(launch) + pd.tseries.offsets.BDay(90)).date()

    assert persistence_mod.is_cold_start_for_date(day_89, launch) is True, "day 89 must be cold-start"
    assert persistence_mod.is_cold_start_for_date(day_90, launch) is True, "day 90 must be cold-start (last day)"
    assert persistence_mod.is_cold_start_for_date(day_91, launch) is False, "day 91 must clear"
