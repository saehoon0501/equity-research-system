"""WS-7.2 portfolio-fit risk → correlation sizing multiplier tests.

Pure/offline. No network. Covers:
  * offline beta/correlation math from fixture return arrays (deterministic),
  * the multiplier mapping (diversifier => 1.0; concentrator => < 1.0; monotone;
    always in (0, 1.0]),
  * the injectable seams (precomputed scalars / return arrays / fetcher),
  * integration: feeding the multiplier into composable_size reduces size.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from src.risk_overlay import (
    PortfolioFitInputs,
    PortfolioFitResult,
    beta_from_returns,
    correlation_to_book,
    portfolio_fit_multiplier,
    resolve_portfolio_fit,
)
from src.sizing.composable import composable_size


# --------------------------------------------------------------------------- #
# Fixtures: deterministic aligned return series.                              #
# --------------------------------------------------------------------------- #

# A reproducible benchmark return stream.
_RNG = np.random.default_rng(7)
_BENCH = _RNG.normal(0.0, 0.01, size=250)
_BOOK_INDEP = _RNG.normal(0.0, 0.01, size=250)  # book stream unrelated to bench
_NOISE = _RNG.normal(0.0, 0.002, size=250)


def _diversifier_returns():
    """Low-beta, low-corr-to-book candidate: mostly its own idiosyncratic noise,
    a small benchmark component, and ~no relation to the book."""
    candidate = 0.1 * _BENCH + _RNG.normal(0.0, 0.01, size=250)
    book = _BOOK_INDEP
    return candidate, _BENCH, book


def _concentrator_returns():
    """High-beta, high-corr-to-book candidate: it is ~the book plus a levered
    benchmark tilt — exactly the name that concentrates existing exposure."""
    book = 1.0 * _BENCH + _NOISE  # book is essentially the benchmark
    candidate = 1.8 * _BENCH + _NOISE  # high beta AND tracks the book closely
    return candidate, _BENCH, book


# --------------------------------------------------------------------------- #
# Offline math                                                                #
# --------------------------------------------------------------------------- #


def test_beta_from_returns_recovers_known_beta():
    bench = np.array([0.01, -0.02, 0.03, -0.01, 0.02, 0.0, -0.015, 0.025])
    cand = 1.5 * bench  # exact linear relation => beta 1.5
    assert beta_from_returns(cand, bench) == pytest.approx(1.5, abs=1e-9)


def test_beta_negative_when_inverse():
    bench = np.array([0.01, -0.02, 0.03, -0.01, 0.02])
    cand = -0.8 * bench
    assert beta_from_returns(cand, bench) == pytest.approx(-0.8, abs=1e-9)


def test_correlation_perfect_and_zero():
    a = np.array([0.01, -0.02, 0.03, -0.01, 0.02])
    assert correlation_to_book(a, 2 * a) == pytest.approx(1.0, abs=1e-9)
    assert correlation_to_book(a, -a) == pytest.approx(-1.0, abs=1e-9)


def test_beta_raises_on_misaligned():
    with pytest.raises(ValueError):
        beta_from_returns([0.1, 0.2, 0.3], [0.1, 0.2])


def test_beta_raises_on_zero_variance_benchmark():
    with pytest.raises(ValueError):
        beta_from_returns([0.1, 0.2, 0.3], [0.0, 0.0, 0.0])


def test_math_inputs_validated():
    with pytest.raises(ValueError):
        correlation_to_book([0.1], [0.2])  # < 2 obs
    with pytest.raises(ValueError):
        beta_from_returns([0.1, np.nan, 0.3], [0.1, 0.2, 0.3])  # non-finite


# --------------------------------------------------------------------------- #
# Mapping                                                                     #
# --------------------------------------------------------------------------- #


def test_low_beta_low_corr_diversifier_is_unity():
    # Below both floors => exactly 1.0, no haircut.
    assert portfolio_fit_multiplier(beta=0.5, corr_to_book=0.1) == 1.0
    assert portfolio_fit_multiplier(beta=1.0, corr_to_book=0.3) == 1.0


def test_high_beta_high_corr_concentrator_is_below_one():
    m = portfolio_fit_multiplier(beta=1.8, corr_to_book=0.9)
    assert m < 1.0
    assert 0.0 < m <= 1.0


def test_negative_corr_is_not_penalised():
    # A hedge (negative corr to book) keeps full size on the corr axis.
    base = portfolio_fit_multiplier(beta=0.5, corr_to_book=-0.9)
    assert base == 1.0


def test_negative_beta_magnitude_is_penalised():
    # Large |beta| with high corr still concentrates risk.
    pos = portfolio_fit_multiplier(beta=1.8, corr_to_book=0.9)
    neg = portfolio_fit_multiplier(beta=-1.8, corr_to_book=0.9)
    assert neg == pytest.approx(pos)
    assert neg < 1.0


def test_monotone_decreasing_in_corr():
    betas = 1.6
    corrs = [0.3, 0.4, 0.6, 0.8, 1.0]
    vals = [portfolio_fit_multiplier(beta=betas, corr_to_book=c) for c in corrs]
    assert all(vals[i] >= vals[i + 1] for i in range(len(vals) - 1))
    assert vals[0] > vals[-1]  # strictly lower at the high-corr end


def test_monotone_decreasing_in_beta():
    corr = 0.8
    betas = [1.0, 1.2, 1.5, 1.8, 2.0, 2.5]
    vals = [portfolio_fit_multiplier(beta=b, corr_to_book=corr) for b in betas]
    assert all(vals[i] >= vals[i + 1] for i in range(len(vals) - 1))
    assert vals[0] > vals[-1]


def test_high_high_strictly_worse_than_either_alone():
    only_beta = portfolio_fit_multiplier(beta=2.0, corr_to_book=0.1)
    only_corr = portfolio_fit_multiplier(beta=0.5, corr_to_book=1.0)
    both = portfolio_fit_multiplier(beta=2.0, corr_to_book=1.0)
    assert both < only_beta
    assert both < only_corr


def test_multiplier_always_in_open_unit_interval():
    rng = np.random.default_rng(0)
    for _ in range(500):
        b = float(rng.uniform(-4.0, 4.0))
        c = float(rng.uniform(-1.0, 1.0))
        m = portfolio_fit_multiplier(beta=b, corr_to_book=c)
        assert 0.0 < m <= 1.0


def test_never_exceeds_one_even_with_extreme_inputs():
    # Far below both floors must still cap at 1.0 (never inflation).
    assert portfolio_fit_multiplier(beta=0.0, corr_to_book=-1.0) == 1.0


# --------------------------------------------------------------------------- #
# resolve_portfolio_fit seams                                                 #
# --------------------------------------------------------------------------- #


def test_resolve_from_precomputed_scalars():
    res = resolve_portfolio_fit(beta=1.8, corr_to_book=0.9)
    assert isinstance(res, PortfolioFitResult)
    assert res.beta == 1.8
    assert res.corr_to_book == 0.9
    assert res.multiplier < 1.0
    # The composite equals the product of the two reported penalties.
    assert res.multiplier == pytest.approx(res.beta_penalty * res.corr_penalty)


def test_resolve_from_return_arrays_diversifier_gives_unity():
    cand, bench, book = _diversifier_returns()
    res = resolve_portfolio_fit(
        candidate_returns=cand, benchmark_returns=bench, book_returns=book
    )
    # Construction guarantees beta ~0.1 (< floor) and |corr| small (< floor).
    assert abs(res.beta) < 1.0
    assert res.corr_to_book < 0.3
    assert res.multiplier == 1.0


def test_resolve_from_return_arrays_concentrator_haircut():
    cand, bench, book = _concentrator_returns()
    res = resolve_portfolio_fit(
        candidate_returns=cand, benchmark_returns=bench, book_returns=book
    )
    assert res.beta > 1.0
    assert res.corr_to_book > 0.3
    assert res.multiplier < 1.0


def test_resolve_via_fetcher_seam():
    calls = {"n": 0}

    def fetcher() -> PortfolioFitInputs:
        calls["n"] += 1
        return PortfolioFitInputs(beta=1.9, corr_to_book=0.95)

    res = resolve_portfolio_fit(fetcher=fetcher)
    assert calls["n"] == 1  # fetcher actually used as the seam
    assert res.multiplier < 1.0


def test_explicit_scalar_takes_precedence_over_fetcher():
    def fetcher() -> PortfolioFitInputs:  # pragma: no cover - must not run
        raise AssertionError("fetcher must not be called when scalars present")

    res = resolve_portfolio_fit(beta=0.5, corr_to_book=0.1, fetcher=fetcher)
    assert res.multiplier == 1.0


def test_resolve_via_inputs_dataclass_with_arrays():
    cand, bench, book = _concentrator_returns()
    res = resolve_portfolio_fit(
        PortfolioFitInputs(
            candidate_returns=cand, benchmark_returns=bench, book_returns=book
        )
    )
    assert res.multiplier < 1.0


def test_resolve_raises_when_nothing_resolvable():
    with pytest.raises(ValueError):
        resolve_portfolio_fit()  # no scalars, no arrays, no fetcher


def test_resolve_payload_shape():
    p = resolve_portfolio_fit(beta=1.5, corr_to_book=0.7).to_payload()
    assert set(p) >= {
        "beta",
        "corr_to_book",
        "beta_penalty",
        "corr_penalty",
        "multiplier",
        "dimension",
        "axes_unavailable",
    }
    assert p["dimension"] == "correlation"
    # Finite, well-formed inputs => no axis flagged unavailable.
    assert p["axes_unavailable"] == []


# --------------------------------------------------------------------------- #
# Integration with composable_size                                            #
# --------------------------------------------------------------------------- #


def test_multiplier_reduces_composable_size():
    cand, bench, book = _concentrator_returns()
    m = resolve_portfolio_fit(
        candidate_returns=cand, benchmark_returns=bench, book_returns=book
    ).multiplier
    assert m < 1.0

    full = composable_size(mode="B", conviction="HIGH")
    cut = composable_size(mode="B", conviction="HIGH", correlation_multiplier=m)

    assert cut.initial_pct < full.initial_pct
    assert cut.max_pct < full.max_pct
    assert cut.net_multiplier == pytest.approx(full.net_multiplier * m)
    assert cut.multipliers["correlation"] == pytest.approx(m)


def test_diversifier_multiplier_leaves_size_unchanged():
    m = resolve_portfolio_fit(beta=0.6, corr_to_book=0.1).multiplier
    assert m == 1.0
    full = composable_size(mode="B", conviction="HIGH")
    same = composable_size(mode="B", conviction="HIGH", correlation_multiplier=m)
    assert same.net_multiplier == pytest.approx(full.net_multiplier)


# --------------------------------------------------------------------------- #
# Regression: non-finite scalar inputs must FAIL CLOSED, not open to 1.0.     #
#                                                                             #
# Confirmed bug: a NaN/inf scalar beta or corr flowed through the ramp        #
# (NaN comparisons all False), penalty became NaN, and min(1.0, NaN) returns  #
# 1.0 in CPython — so a garbage/unknown-risk name silently got its FULL       #
# target size (the risk overlay failing OPEN). Now a non-finite axis is a     #
# DATA ERROR: it applies the conservative ramp floor (never 1.0) so the       #
# result is finite, in (0, 1.0], and strictly below 1.0 — distinguishable     #
# from a genuine diversifier — and resolve_* flags the axis unavailable.      #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "beta, corr",
    [
        (float("nan"), 0.9),
        (2.0, float("nan")),
        (float("inf"), 0.9),
        (2.0, float("inf")),
        (float("-inf"), 0.9),
    ],
)
def test_multiplier_nonfinite_fails_closed_not_open(beta, corr):
    m = portfolio_fit_multiplier(beta, corr)
    assert math.isfinite(m)          # never NaN / inf
    assert 0.0 < m <= 1.0            # stays in the contract interval
    assert m < 1.0                   # NOT a silent clean 1.0 (no fail-open)


def test_multiplier_both_axes_nonfinite_still_finite_and_bounded():
    m = portfolio_fit_multiplier(float("nan"), float("nan"))
    assert math.isfinite(m)
    assert 0.0 < m < 1.0


def test_resolve_marks_nan_beta_axis_unavailable():
    res = resolve_portfolio_fit(beta=float("nan"), corr_to_book=0.9)
    assert math.isfinite(res.multiplier)
    assert 0.0 < res.multiplier <= 1.0
    assert res.axes_unavailable == ("beta",)
    assert res.to_payload()["axes_unavailable"] == ["beta"]


def test_resolve_marks_nan_corr_axis_unavailable():
    res = resolve_portfolio_fit(beta=2.0, corr_to_book=float("nan"))
    assert math.isfinite(res.multiplier)
    assert 0.0 < res.multiplier <= 1.0
    assert res.axes_unavailable == ("corr_to_book",)


def test_resolve_marks_inf_beta_axis_unavailable():
    res = resolve_portfolio_fit(beta=float("inf"), corr_to_book=0.9)
    assert math.isfinite(res.multiplier)
    assert 0.0 < res.multiplier <= 1.0
    assert res.axes_unavailable == ("beta",)


def test_resolve_via_fetcher_with_nan_scalar_fails_closed():
    def fetcher() -> PortfolioFitInputs:
        return PortfolioFitInputs(beta=float("nan"), corr_to_book=0.9)

    res = resolve_portfolio_fit(fetcher=fetcher)
    assert math.isfinite(res.multiplier)
    assert 0.0 < res.multiplier < 1.0
    assert res.axes_unavailable == ("beta",)


def test_genuine_diversifier_distinguishable_from_garbage():
    # The whole point of the fix: a real low-beta low-corr diversifier returns
    # EXACTLY 1.0 and flags NO axis unavailable, while a NaN-axis name returns
    # < 1.0 with the axis flagged. The two are not conflated.
    good = resolve_portfolio_fit(beta=0.5, corr_to_book=0.1)
    assert good.multiplier == 1.0
    assert good.axes_unavailable == ()

    garbage = resolve_portfolio_fit(beta=float("nan"), corr_to_book=0.1)
    assert garbage.multiplier < 1.0
    assert garbage.axes_unavailable == ("beta",)
    assert good.multiplier != garbage.multiplier
