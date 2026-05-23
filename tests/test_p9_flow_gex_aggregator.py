"""Tests for the v0.2 gamma-regime aggregator (gex_aggregator.py)."""

import math
from datetime import date

import pytest

from src.p9_flow_overlay.gex_aggregator import (
    CONTRACT_MULTIPLIER,
    aggregate_gex_by_dte_bucket,
    classify_gamma_regime,
    compute_per_strike_gex,
    compute_zero_gamma_level,
    _bs_gamma_at_spot,
    _bucket_label,
    _dte_from_expiry,
)


# ---------- compute_per_strike_gex ----------


def test_per_strike_call_spotgamma_sign():
    """SpotGamma convention: dealers long calls → +1 sign on call gamma."""
    contract = {"type": "call", "gamma": 0.01, "open_interest": 100}
    # Formula: 0.01 × 100 × 100 × 400² × 0.01 × (+1) = 16000
    gex = compute_per_strike_gex(contract, spot=400.0, dealer_sign_calls=1, dealer_sign_puts=-1)
    assert gex == pytest.approx(0.01 * 100 * 100 * 400 * 400 * 0.01 * 1)


def test_per_strike_put_spotgamma_sign():
    """SpotGamma convention: dealers short puts → -1 sign on put gamma."""
    contract = {"type": "put", "gamma": 0.01, "open_interest": 100}
    gex = compute_per_strike_gex(contract, spot=400.0, dealer_sign_calls=1, dealer_sign_puts=-1)
    assert gex == pytest.approx(0.01 * 100 * 100 * 400 * 400 * 0.01 * -1)


def test_per_strike_squeezemetrics_sign_inverse():
    """SqueezeMetrics convention is opposite on calls."""
    contract = {"type": "call", "gamma": 0.01, "open_interest": 100}
    gex_sm = compute_per_strike_gex(contract, spot=400.0, dealer_sign_calls=-1, dealer_sign_puts=1)
    gex_sg = compute_per_strike_gex(contract, spot=400.0, dealer_sign_calls=1, dealer_sign_puts=-1)
    assert gex_sm == -gex_sg


def test_per_strike_none_gamma_returns_zero():
    """Illiquid contracts return gamma=None — treat as 0 contribution."""
    contract = {"type": "call", "gamma": None, "open_interest": 100}
    assert compute_per_strike_gex(contract, spot=400.0) == 0.0


def test_per_strike_none_oi_returns_zero():
    contract = {"type": "call", "gamma": 0.01, "open_interest": None}
    assert compute_per_strike_gex(contract, spot=400.0) == 0.0


def test_per_strike_unknown_type_returns_zero():
    contract = {"type": "future", "gamma": 0.01, "open_interest": 100}
    assert compute_per_strike_gex(contract, spot=400.0) == 0.0


# ---------- DTE bucketing ----------


def test_dte_from_expiry():
    assert _dte_from_expiry("2026-05-30", date(2026, 5, 23)) == 7
    assert _dte_from_expiry("2026-05-23", date(2026, 5, 23)) == 0
    # Past expiry clamped to 0 (defensive)
    assert _dte_from_expiry("2026-05-20", date(2026, 5, 23)) == 0


def test_bucket_label_boundaries():
    """Default boundaries (0, 7, 30, 90) → buckets 0DTE / 1-7d / 8-30d / 31-90d / 90d+."""
    b = (0, 7, 30, 90)
    assert _bucket_label(0, b) == "0DTE"
    assert _bucket_label(1, b) == "1-7d"
    assert _bucket_label(7, b) == "1-7d"
    assert _bucket_label(8, b) == "8-30d"
    assert _bucket_label(30, b) == "8-30d"
    assert _bucket_label(31, b) == "31-90d"
    assert _bucket_label(90, b) == "31-90d"
    assert _bucket_label(91, b) == "91d+"


def test_aggregate_gex_groups_by_dte():
    """Two contracts in different buckets should aggregate separately."""
    as_of = date(2026, 5, 23)
    contracts = [
        {"type": "call", "gamma": 0.01, "open_interest": 100, "expiry": "2026-05-23"},  # 0DTE
        {"type": "call", "gamma": 0.02, "open_interest": 50, "expiry": "2026-08-01"},   # 31-90d
    ]
    result = aggregate_gex_by_dte_bucket(contracts, spot=400.0, as_of=as_of)
    assert "0DTE" in result
    assert "31-90d" in result
    assert result["0DTE"] > 0
    assert result["31-90d"] > 0
    # total_net_gex must be sum of buckets
    bucket_sum = sum(v for k, v in result.items() if k != "total_net_gex")
    assert result["total_net_gex"] == pytest.approx(bucket_sum)


def test_aggregate_skips_invalid_expiry():
    """Contracts with missing / malformed expiry don't crash; just skipped."""
    contracts = [
        {"type": "call", "gamma": 0.01, "open_interest": 100, "expiry": None},
        {"type": "call", "gamma": 0.01, "open_interest": 100, "expiry": "not-a-date"},
        {"type": "call", "gamma": 0.01, "open_interest": 100, "expiry": "2026-06-01"},  # valid
    ]
    result = aggregate_gex_by_dte_bucket(contracts, spot=400.0, as_of=date(2026, 5, 23))
    # Only the valid contract contributes; total_net_gex matches that single contract
    assert result["total_net_gex"] > 0
    # Valid expiry is 9 days out → 8-30d bucket
    assert "8-30d" in result


# ---------- Black-Scholes gamma ----------


def test_bs_gamma_at_atm_ref_value():
    """BS gamma at S=K=100, T=1y, σ=30%, r=0:
       d1 = (0 + 0.5×0.09×1) / (0.3×1) = 0.15
       N'(d1) = exp(-0.5×0.0225)/√(2π) ≈ 0.3945
       gamma = 0.3945 / (100 × 0.3 × 1) ≈ 0.01315
    """
    gamma = _bs_gamma_at_spot(spot=100.0, strike=100.0, ttm_years=1.0, iv=0.3, rf=0.0)
    assert gamma == pytest.approx(0.01315, rel=0.01)


def test_bs_gamma_zero_for_degenerate_inputs():
    assert _bs_gamma_at_spot(spot=0, strike=100, ttm_years=1, iv=0.3) == 0.0
    assert _bs_gamma_at_spot(spot=100, strike=0, ttm_years=1, iv=0.3) == 0.0
    assert _bs_gamma_at_spot(spot=100, strike=100, ttm_years=0, iv=0.3) == 0.0
    assert _bs_gamma_at_spot(spot=100, strike=100, ttm_years=1, iv=0) == 0.0
    assert _bs_gamma_at_spot(spot=100, strike=100, ttm_years=1, iv=-0.1) == 0.0


def test_bs_gamma_otm_lower_than_atm():
    """Gamma peaks ATM; far OTM is lower."""
    gamma_atm = _bs_gamma_at_spot(spot=100, strike=100, ttm_years=0.25, iv=0.3)
    gamma_otm = _bs_gamma_at_spot(spot=100, strike=130, ttm_years=0.25, iv=0.3)
    assert gamma_otm < gamma_atm


# ---------- Zero-gamma level construction ----------


def test_zero_gamma_returns_none_when_no_usable_contracts():
    """No contracts with iv → no BS re-pricing → None."""
    contracts = [{"type": "call", "gamma": 0.01, "open_interest": 100, "expiry": "2026-06-01", "iv": None, "strike": 400}]
    result = compute_zero_gamma_level(contracts, spot=400.0, as_of=date(2026, 5, 23))
    assert result is None


def test_zero_gamma_returns_none_when_no_crossing_in_grid():
    """A single ATM call with positive gamma — net GEX is positive across the
    grid (no sign flip) → returns None."""
    contracts = [
        {"type": "call", "gamma": 0.01, "open_interest": 100, "expiry": "2026-08-01",
         "iv": 0.3, "strike": 400},
    ]
    result = compute_zero_gamma_level(contracts, spot=400.0, as_of=date(2026, 5, 23))
    # Net GEX stays positive (single long-call position); no flip in ±10% grid
    assert result is None


# ---------- classify_gamma_regime ----------


def test_classify_returns_required_keys():
    """End-to-end check that result has all schema-required keys (v3-final expansion)."""
    as_of = date(2026, 5, 23)
    contracts = [
        {"type": "call", "gamma": 0.01, "open_interest": 100, "expiry": "2026-06-01",
         "iv": 0.3, "strike": 400},
        {"type": "put", "gamma": 0.005, "open_interest": 80, "expiry": "2026-06-01",
         "iv": 0.3, "strike": 400},
    ]
    result = classify_gamma_regime(
        contracts, spot=400.0, as_of=as_of,
        positive_threshold_normalized=0.25,
        negative_threshold_normalized=-0.25,
    )
    required = {
        "bin", "net_gex_at_spot", "normalized_gex", "zero_gamma_distance_pct",
        "dte_bucket_decomp", "dealer_sign_convention", "regime_flip_signal_method",
        # v3-final additions
        "normalized_gex_unbounded", "winsorization_fired", "normalization_formula",
    }
    assert required.issubset(result.keys())
    assert result["bin"] in ("positive", "neutral", "negative")
    assert result["dealer_sign_convention"] == "spotgamma"
    # Default formula (no ADV passed) = spot_squared back-compat
    assert result["normalization_formula"] == "spot_squared"
    assert result["winsorization_fired"] is False


# ---------- v3-final: ADV normalization ----------


def test_classify_adv_normalization_when_adv_provided():
    """When notional_adv_30d > 0, normalization formula = adv_30d."""
    contracts = [
        {"type": "call", "gamma": 0.01, "open_interest": 1000, "expiry": "2026-06-01"},
    ]
    result = classify_gamma_regime(
        contracts, spot=400.0, as_of=date(2026, 5, 23),
        positive_threshold_normalized=0.25,
        negative_threshold_normalized=-0.25,
        notional_adv_30d=1_000_000_000.0,  # $1B daily notional
    )
    assert result["normalization_formula"] == "adv_30d"
    # net_gex = 0.01 * 1000 * 100 * 400² * 0.01 * 1 = 1.6e6; normalized = 1.6e6 / 1e9 = 0.0016
    assert result["normalized_gex"] == pytest.approx(result["net_gex_at_spot"] / 1_000_000_000.0)


def test_classify_falls_back_to_spot_squared_when_adv_missing():
    """notional_adv_30d=None → back-compat formula (spot²×100)."""
    contracts = [
        {"type": "call", "gamma": 0.01, "open_interest": 1000, "expiry": "2026-06-01"},
    ]
    result = classify_gamma_regime(
        contracts, spot=400.0, as_of=date(2026, 5, 23),
        positive_threshold_normalized=0.05,
        negative_threshold_normalized=-0.05,
    )
    assert result["normalization_formula"] == "spot_squared"


def test_classify_adv_zero_falls_back_to_spot_squared():
    """Defensive: adv=0 (degenerate) falls back to spot²×100."""
    contracts = [
        {"type": "call", "gamma": 0.01, "open_interest": 1000, "expiry": "2026-06-01"},
    ]
    result = classify_gamma_regime(
        contracts, spot=400.0, as_of=date(2026, 5, 23),
        positive_threshold_normalized=0.05,
        negative_threshold_normalized=-0.05,
        notional_adv_30d=0.0,
    )
    assert result["normalization_formula"] == "spot_squared"


# ---------- v3-final: winsorization ----------


def test_classify_winsorization_fires_when_raw_exceeds_bound():
    """Raw normalized_gex > winsorize_at → bin uses capped value; raw retained."""
    contracts = [
        # Make GEX large enough to push normalized > 2.0 under tiny ADV
        {"type": "call", "gamma": 0.05, "open_interest": 10_000, "expiry": "2026-06-01"},
    ]
    result = classify_gamma_regime(
        contracts, spot=400.0, as_of=date(2026, 5, 23),
        positive_threshold_normalized=0.25,
        negative_threshold_normalized=-0.25,
        notional_adv_30d=1_000_000.0,  # $1M daily — tiny — forces ratio to blow up
        winsorize_at=2.0,
    )
    assert result["winsorization_fired"] is True
    assert result["normalized_gex"] == pytest.approx(2.0)  # capped for bin
    assert result["normalized_gex_unbounded"] > 2.0       # raw retained
    assert result["bin"] == "positive"  # capped value still over +0.25 threshold


def test_classify_winsorization_negative_side():
    """Raw normalized_gex < -winsorize_at → bin uses capped negative value."""
    contracts = [
        # Single PUT with large gamma — under spotgamma convention puts get -1 sign
        {"type": "put", "gamma": 0.05, "open_interest": 10_000, "expiry": "2026-06-01"},
    ]
    result = classify_gamma_regime(
        contracts, spot=400.0, as_of=date(2026, 5, 23),
        positive_threshold_normalized=0.25,
        negative_threshold_normalized=-0.25,
        notional_adv_30d=1_000_000.0,
        winsorize_at=2.0,
    )
    assert result["winsorization_fired"] is True
    assert result["normalized_gex"] == pytest.approx(-2.0)
    assert result["normalized_gex_unbounded"] < -2.0
    assert result["bin"] == "negative"


def test_classify_winsorization_inactive_when_raw_within_bounds():
    contracts = [
        {"type": "call", "gamma": 0.01, "open_interest": 100, "expiry": "2026-06-01"},
    ]
    result = classify_gamma_regime(
        contracts, spot=400.0, as_of=date(2026, 5, 23),
        positive_threshold_normalized=0.25,
        negative_threshold_normalized=-0.25,
        notional_adv_30d=1_000_000_000.0,
        winsorize_at=2.0,
    )
    assert result["winsorization_fired"] is False
    assert result["normalized_gex"] == result["normalized_gex_unbounded"]


def test_classify_no_winsorize_when_winsorize_at_none():
    """When winsorize_at=None, no capping; raw equals classified."""
    contracts = [
        {"type": "call", "gamma": 0.05, "open_interest": 10_000, "expiry": "2026-06-01"},
    ]
    result = classify_gamma_regime(
        contracts, spot=400.0, as_of=date(2026, 5, 23),
        positive_threshold_normalized=0.25,
        negative_threshold_normalized=-0.25,
        notional_adv_30d=1_000_000.0,
        # winsorize_at omitted → None default
    )
    assert result["winsorization_fired"] is False
    assert result["normalized_gex"] == result["normalized_gex_unbounded"]


def test_classify_unknown_dealer_sign_raises():
    with pytest.raises(ValueError, match="dealer_sign_convention"):
        classify_gamma_regime(
            contracts=[],
            spot=100.0,
            as_of=date(2026, 5, 23),
            positive_threshold_normalized=0.05,
            negative_threshold_normalized=-0.05,
            dealer_sign_convention="acme",
        )


def test_classify_empty_chain_neutral():
    """Empty contracts list → net_gex = 0 → neutral bin."""
    result = classify_gamma_regime(
        contracts=[],
        spot=400.0,
        as_of=date(2026, 5, 23),
        positive_threshold_normalized=0.05,
        negative_threshold_normalized=-0.05,
    )
    assert result["net_gex_at_spot"] == 0.0
    assert result["normalized_gex"] == 0.0
    assert result["bin"] == "neutral"
    assert result["zero_gamma_distance_pct"] is None


def test_classify_squeezemetrics_flips_sign():
    """Same chain, SpotGamma vs SqueezeMetrics → opposite net_gex."""
    contracts = [
        {"type": "call", "gamma": 0.01, "open_interest": 1000, "expiry": "2026-06-01"},
    ]
    sg = classify_gamma_regime(
        contracts, spot=400.0, as_of=date(2026, 5, 23),
        positive_threshold_normalized=0.05,
        negative_threshold_normalized=-0.05,
        dealer_sign_convention="spotgamma",
    )
    sm = classify_gamma_regime(
        contracts, spot=400.0, as_of=date(2026, 5, 23),
        positive_threshold_normalized=0.05,
        negative_threshold_normalized=-0.05,
        dealer_sign_convention="squeezemetrics",
    )
    assert sg["net_gex_at_spot"] == -sm["net_gex_at_spot"]
