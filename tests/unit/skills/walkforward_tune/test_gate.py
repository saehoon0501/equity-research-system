"""Pure-unit tests for the deterministic promotion gate (task 2.3) — THE CRUX.

The gate's statistics (PSR / MinTRL / DSR / PBO) are Bailey & Lopez de Prado
formulas with NO repo precedent, so a self-written test only proves
self-consistency, not correctness. Per the task acceptance criteria these tests
therefore anchor to values **external to the implementer's own derivation**:

  * AT LEAST ONE hand-computed reference value per statistic — derived from the
    published formula evaluated against the *standard-normal table* (a published
    constant, the only true external truth here), with the arithmetic shown in
    the docstring so the reviewer can re-derive it by hand;
  * an INDEPENDENT cross-anchor: MinTRL is *defined* as the n at which PSR
    reaches confidence alpha, so plugging ``n = MinTRL`` back into ``psr`` must
    return alpha (ties MinTRL to PSR and to the external constant alpha at once);
  * the invariant PROPERTIES the task pins (DSR FALLS with trial count — the
    deflation; PSR FALLS / MinTRL RISES with negative skew & fat tails;
    N=1 => no-promote; IS-Sharpe never moves the verdict; insufficient =>
    no-promote; the §13 guard rejects an Edge gain that lowers Survive).

SOURCES (cited again at each statistic in gate.py):
  - Bailey & Lopez de Prado (2012), "The Sharpe Ratio Efficient Frontier",
    Journal of Risk — PSR, MinTRL, and the Mertens/Lo SR-estimator variance.
  - Bailey & Lopez de Prado (2014), "The Deflated Sharpe Ratio: Correcting for
    Selection Bias, Backtest Overfitting and Non-Normality", JPM — DSR + SR0
    expected-maximum-Sharpe.
  - Bailey, Borwein, Lopez de Prado & Zhu (2014), "The Probability of Backtest
    Overfitting" — CSCV / PBO via logit of the IS-best config's OOS rank.

IMPORTANT spec-vs-source note (verified against the source before writing these
tests; see gate.py for the inline citations): two prose invariants in the
walkforward spec are INVERTED relative to the published formulas and are NOT
encoded here as written —
  - the spec says "DSR rises with trial count"; the published DSR *falls* with N
    (that downward adjustment IS the deflation — SR0 rises with N);
  - the spec lumps "PSR/MinTRL grows with negative skew"; PSR *falls* with
    negative skew (PSR is designed to penalise it), while MinTRL *rises*.
The source wins (the task says the reviewer checks formula-vs-source); the
direction tests below assert the source-correct directions.

No LLM, MCP, or live DB — pure leaf (P1, P14 inner-ring).

Requirements: 4.5 (never IS-Sharpe), 5.1 (DSR+PSR/MinTRL+PBO), 5.2 (effective_N),
5.3 (MinBTL caps breadth), 5.4 (insufficient => no-promote), 5.5 (margin /
consecutive / hysteresis decision-rule; never IS-Sharpe), 6.2 (param-track gate),
6.3 (§13 lexicographic guard).
"""

from __future__ import annotations

import math

import pytest

from src.skills.walkforward_tune import gate as G
from src.skills.walkforward_tune.types import (
    GateParams,
    GateVerdict,
    OOSMatrix,
    OOSSample,
)

# --- External constant: the Euler-Mascheroni constant used in SR0 ----------
EULER_GAMMA = 0.5772156649015329


# ===========================================================================
# Section A — the small in-module math primitives, anchored to the
# standard-normal table (the external truth).
# ===========================================================================


def test_normal_cdf_matches_the_standard_normal_table() -> None:
    # External anchors: published standard-normal CDF values.
    assert G.norm_cdf(0.0) == pytest.approx(0.5, abs=1e-12)
    assert G.norm_cdf(1.0) == pytest.approx(0.8413447461, abs=1e-9)
    assert G.norm_cdf(1.959963985) == pytest.approx(0.975, abs=1e-7)
    assert G.norm_cdf(-1.0) == pytest.approx(1.0 - 0.8413447461, abs=1e-9)


def test_inverse_normal_cdf_matches_published_quantiles() -> None:
    # External anchors: the published normal quantiles. These pin the Acklam
    # rational approximation used by SR0 / MinTRL (no scipy in the inner ring).
    assert G.norm_ppf(0.975) == pytest.approx(1.959963985, abs=1e-6)
    assert G.norm_ppf(0.95) == pytest.approx(1.644853627, abs=1e-6)
    assert G.norm_ppf(0.5) == pytest.approx(0.0, abs=1e-9)
    # Symmetry of the quantile function.
    assert G.norm_ppf(0.025) == pytest.approx(-1.959963985, abs=1e-6)


def test_full_kurtosis_helper_adds_three_to_excess() -> None:
    # types.py pins OOSSample.kurtosis as EXCESS kurtosis; the B-LdP variance
    # term wants FULL kurtosis (gamma4 = 3 for a normal). The +3 conversion is
    # the single landmine that silently corrupts every statistic if forgotten.
    assert G.full_kurtosis(0.0) == pytest.approx(3.0)
    assert G.full_kurtosis(3.0) == pytest.approx(6.0)
    assert G.full_kurtosis(-1.2) == pytest.approx(1.8)


# ===========================================================================
# Section B — PSR. Hand-computed reference value + skew/kurtosis directions.
# ===========================================================================


def test_psr_hand_computed_reference_value() -> None:
    """PSR (Bailey & Lopez de Prado 2012).

    PSR(SR*) = Phi[ (SR_hat - SR*) * sqrt(n - 1) / D ],
        D^2 = 1 - gamma3*SR_hat + ((gamma4 - 1)/4)*SR_hat^2   (Mertens/Lo).

    Hand derivation (normal moments, gamma3 = 0, full gamma4 = 3):
      SR_hat = 0.2, benchmark SR* = 0, n = 26.
      D^2 = 1 - 0 + ((3-1)/4)*0.2^2 = 1 + 0.5*0.04 = 1.02 ; D = 1.0099504938.
      z   = (0.2 - 0) * sqrt(25) / 1.0099504938 = 1.0 / 1.0099504938 = 0.9901475.
      PSR = Phi(0.9901475) = 0.8389490   (from the standard-normal table).
    """
    psr = G.probabilistic_sharpe_ratio(
        sr_hat=0.2, sr_benchmark=0.0, n=26, skew=0.0, excess_kurt=0.0
    )
    assert psr == pytest.approx(0.8389490, abs=1e-6)


def test_psr_falls_as_skew_becomes_more_negative() -> None:
    # SOURCE-CORRECT direction (the spec prose is inverted). With SR_hat > 0,
    # gamma3 < 0 makes the -gamma3*SR_hat term POSITIVE => D^2 rises => z falls
    # => PSR falls. PSR is designed to penalise negative skew.
    common = dict(sr_hat=0.2, sr_benchmark=0.0, n=26, excess_kurt=0.0)
    psr_pos = G.probabilistic_sharpe_ratio(skew=+1.0, **common)
    psr_zero = G.probabilistic_sharpe_ratio(skew=0.0, **common)
    psr_neg = G.probabilistic_sharpe_ratio(skew=-1.0, **common)
    assert psr_pos > psr_zero > psr_neg


def test_psr_falls_as_tails_get_fatter() -> None:
    # Higher (excess) kurtosis => D^2 rises => PSR falls.
    common = dict(sr_hat=0.2, sr_benchmark=0.0, n=26, skew=0.0)
    psr_thin = G.probabilistic_sharpe_ratio(excess_kurt=0.0, **common)
    psr_fat = G.probabilistic_sharpe_ratio(excess_kurt=6.0, **common)
    assert psr_thin > psr_fat


# ===========================================================================
# Section C — MinTRL. Hand-computed value + the PSR-roundtrip cross-anchor +
# the negative-skew direction.
# ===========================================================================


def test_min_trl_hand_computed_reference_value() -> None:
    """MinTRL (Bailey & Lopez de Prado 2012).

    MinTRL = 1 + D^2 * ( Phi^{-1}(alpha) / (SR_hat - SR*) )^2.

    Hand derivation (normal, gamma3 = 0, full gamma4 = 3, alpha = 0.95):
      SR_hat = 0.5, SR* = 0.  D^2 = 1 + 0.5*0.5^2 = 1.125.
      Phi^{-1}(0.95) = 1.6448536.
      MinTRL = 1 + 1.125 * (1.6448536 / 0.5)^2
             = 1 + 1.125 * (3.2897072)^2
             = 1 + 1.125 * 10.822173 = 1 + 12.174945 = 13.174945.
    """
    min_trl = G.min_track_record_length(
        sr_hat=0.5, sr_benchmark=0.0, skew=0.0, excess_kurt=0.0, alpha=0.95
    )
    assert min_trl == pytest.approx(13.174945, abs=1e-5)


def test_min_trl_roundtrips_into_psr_at_alpha() -> None:
    # INDEPENDENT cross-anchor (not self-consistency): MinTRL is DEFINED as the
    # n at which PSR reaches confidence alpha. So plugging n = MinTRL back into
    # PSR must return alpha. This ties MinTRL to PSR and to the external
    # constant alpha in one shot.
    alpha = 0.95
    min_trl = G.min_track_record_length(
        sr_hat=0.5, sr_benchmark=0.0, skew=0.0, excess_kurt=0.0, alpha=alpha
    )
    psr_at_min_trl = G.probabilistic_sharpe_ratio(
        sr_hat=0.5,
        sr_benchmark=0.0,
        n=min_trl,  # the continuous MinTRL, not rounded
        skew=0.0,
        excess_kurt=0.0,
    )
    assert psr_at_min_trl == pytest.approx(alpha, abs=1e-6)


def test_min_trl_rises_as_skew_becomes_more_negative() -> None:
    # SOURCE-CORRECT: MinTRL is proportional to D^2, which RISES with negative
    # skew => you need a LONGER track record. (This is the half of the spec's
    # "PSR/MinTRL grows with negative skew" prose that IS correct.)
    common = dict(sr_hat=0.5, sr_benchmark=0.0, excess_kurt=0.0, alpha=0.95)
    mt_pos = G.min_track_record_length(skew=+0.5, **common)
    mt_zero = G.min_track_record_length(skew=0.0, **common)
    mt_neg = G.min_track_record_length(skew=-0.5, **common)
    assert mt_pos < mt_zero < mt_neg


def test_min_trl_degenerate_when_sr_not_above_benchmark() -> None:
    # SR_hat <= SR* => (SR_hat - SR*) <= 0 => MinTRL undefined/degenerate.
    # The gate maps that to its no-promote fail-safe; the primitive signals it
    # by returning +inf (an infinitely long track record can never be met).
    mt = G.min_track_record_length(
        sr_hat=0.0, sr_benchmark=0.2, skew=0.0, excess_kurt=0.0, alpha=0.95
    )
    assert math.isinf(mt)


# ===========================================================================
# Section D — DSR. Hand-computed SR0 + DSR value + the deflation direction.
# ===========================================================================


def test_expected_max_sharpe_sr0_hand_computed_reference_value() -> None:
    """SR0 expected-maximum-Sharpe (Bailey & Lopez de Prado 2014).

    SR0 = sqrt(V) * ( (1 - g)*Phi^{-1}(1 - 1/N) + g*Phi^{-1}(1 - 1/(N*e)) ),
        g = Euler-Mascheroni = 0.5772156649, e = 2.7182818.

    Hand derivation (V = 0.04 => sqrt(V) = 0.2, N = 5); the two quantiles are
    verified by bisection on the exact erf-based normal CDF (external):
      Phi^{-1}(1 - 1/5)   = Phi^{-1}(0.8)        = 0.84162123.
      Phi^{-1}(1 - 1/(5e)) = Phi^{-1}(0.92642411) = 1.44966566.
      SR0 = 0.2 * ((1-0.57721566)*0.84162123 + 0.57721566*1.44966566)
          = 0.2 * (0.42278434*0.84162123 + 0.57721566*1.44966566)
          = 0.2 * (0.35582558 + 0.83677842) = 0.2 * 1.19260400 = 0.23852080.
    (== 0.2385188 to 6 dp once the products are kept full-precision.)
    """
    sr0 = G.expected_max_sharpe(sr_variance=0.04, n_trials=5)
    assert sr0 == pytest.approx(0.2385188, abs=1e-6)


def test_dsr_hand_computed_reference_value() -> None:
    """DSR = PSR(SR0) (Bailey & Lopez de Prado 2014).

    DSR plugs SR0 in as the benchmark threshold; the variance term keeps the
    OBSERVED SR_hat (the 2012 PSR convention; sigma is the sampling variance of
    the estimator, a function of the observed Sharpe, not of the threshold).

    Hand derivation: SR_hat = 0.5, n = 50, normal moments, SR0 = 0.2385188
    (from the SR0 anchor above, V=0.04, N=5).
      D^2 = 1 + 0.5*0.5^2 = 1.125 ; D = 1.0606602.
      z   = (0.5 - 0.2385188)*sqrt(49)/1.0606602 = 0.2614812*7/1.0606602
          = 1.8303684/1.0606602 = 1.7256879.
      DSR = Phi(1.7256879) = 0.9577982 (standard-normal table).
    """
    dsr = G.deflated_sharpe_ratio(
        sr_hat=0.5,
        n=50,
        skew=0.0,
        excess_kurt=0.0,
        sr_variance=0.04,
        n_trials=5,
    )
    assert dsr == pytest.approx(0.95780, abs=1e-4)


def test_dsr_falls_as_trial_count_rises_the_deflation() -> None:
    # THE defining property of the Deflated Sharpe Ratio (and the place the spec
    # prose is inverted): more trials => SR0 rises => the threshold rises =>
    # DSR FALLS. This downward adjustment IS the multiple-testing deflation.
    common = dict(sr_hat=0.5, n=50, skew=0.0, excess_kurt=0.0, sr_variance=0.04)
    dsr_few = G.deflated_sharpe_ratio(n_trials=5, **common)
    dsr_many = G.deflated_sharpe_ratio(n_trials=50, **common)
    assert dsr_few > dsr_many


# ===========================================================================
# Section E — PBO via CSCV. Hand-computed reference + the rank-reversal anchor.
# ===========================================================================


def test_pbo_consistent_winner_is_zero() -> None:
    """PBO via CSCV (Bailey, Borwein, Lopez de Prado & Zhu 2014).

    Matrix rows = partitions, cols = configs. Split the S=4 partition-subsets
    into all C(4,2)=6 IS/OOS train/test combinations. For each: pick the IS-best
    config, find its OOS relative rank omega = rank/(N+1), logit lambda =
    ln(omega/(1-omega)). PBO = fraction of combinations with lambda <= 0.

    Hand derivation — a config that wins on EVERY partition is IS-best AND
    OOS-best in every split: OOS rank = 4 of 4, omega = 4/5 = 0.8,
    lambda = ln(0.8/0.2) = ln(4) = +1.3863 > 0 for all 6 combos => PBO = 0/6 = 0.
    """
    # config "c0" strictly dominates on every partition.
    matrix = _matrix_from_returns(
        per_config={
            "c0": [0.30, 0.32, 0.31, 0.33],
            "c1": [0.10, 0.09, 0.11, 0.08],
            "c2": [0.05, 0.06, 0.04, 0.07],
            "c3": [0.01, 0.02, 0.00, 0.03],
        },
        incumbent=[0.0, 0.0, 0.0, 0.0],
    )
    pbo = G.probability_of_backtest_overfitting(matrix, n_subsets=4)
    assert pbo == pytest.approx(0.0, abs=1e-12)


def test_pbo_rank_reversal_matches_hand_count() -> None:
    """Rank-reversal anchor: configs that win IS lose OOS on the splits that
    isolate their winning half.

    With c0 winning partitions {0,1} and c3 winning partitions {2,3} (and ties
    broken by index), the 6 IS/OOS combos yield lambdas
    [-1.3863, +0.4055, +0.4055, +0.4055, +0.4055, -1.3863] (hand-traced):
    the two combos whose IS is exactly one config's winning half put the IS-best
    at the OOS bottom (omega = 1/5, lambda = ln(0.25) = -1.3863 <= 0).
    => PBO = 2/6 = 0.33333.
    """
    matrix = _matrix_from_returns(
        per_config={
            "c0": [0.40, 0.40, 0.01, 0.01],
            "c1": [0.10, 0.10, 0.05, 0.05],
            "c2": [0.05, 0.05, 0.10, 0.10],
            "c3": [0.01, 0.01, 0.40, 0.40],
        },
        incumbent=[0.0, 0.0, 0.0, 0.0],
    )
    pbo = G.probability_of_backtest_overfitting(matrix, n_subsets=4)
    assert pbo == pytest.approx(1.0 / 3.0, abs=1e-9)


# ===========================================================================
# Section F — evaluate_gate: end-to-end verdict behaviour (the observables).
# ===========================================================================


def _sample(ret: float, skew: float = 0.0, kurt: float = 0.0, n_obs: int = 40) -> OOSSample:
    return OOSSample(survival_net_return=ret, skew=skew, kurtosis=kurt, n_obs=n_obs)


def _matrix_from_returns(
    per_config: dict[str, list[float]],
    incumbent: list[float],
    trial_metadata: dict | None = None,
    n_obs: int = 40,
) -> OOSMatrix:
    return OOSMatrix(
        per_config={
            cid: [_sample(r, n_obs=n_obs) for r in series]
            for cid, series in per_config.items()
        },
        incumbent=[_sample(r, n_obs=n_obs) for r in incumbent],
        trial_metadata=trial_metadata or {},
    )


def _permissive_params(**overrides) -> GateParams:
    base = dict(
        dsr_threshold=0.90,
        psr_threshold=0.90,
        min_trl=50,
        pbo_threshold=0.20,
        min_btl=2,
        benchmark_sharpe=0.0,
        oos_margin=0.0,
        consecutive_required=1,
        hysteresis=0.0,
    )
    base.update(overrides)
    return GateParams(**base)


def _strong_promotable_matrix() -> OOSMatrix:
    # A trial set whose best config is a strong, consistent OOS winner that
    # beats the incumbent by a comfortable margin on every partition, with a
    # benign §13 decomposition (best dominates the incumbent on Survive too).
    per = {
        "winner": [0.18, 0.20, 0.19, 0.21, 0.20, 0.19, 0.22, 0.20],
        "mid": [0.06, 0.07, 0.05, 0.08, 0.06, 0.07, 0.05, 0.06],
        "weak": [0.01, 0.02, 0.00, 0.03, 0.01, 0.02, 0.00, 0.01],
    }
    incumbent = [0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05]
    meta = {
        "effective_n": 3,
        "lexicographic": {
            "winner": {"survive": 1.0, "preserve": 1.0, "edge": 0.9, "return": 0.9},
            "mid": {"survive": 1.0, "preserve": 1.0, "edge": 0.5, "return": 0.5},
            "weak": {"survive": 1.0, "preserve": 1.0, "edge": 0.1, "return": 0.1},
            "__incumbent__": {"survive": 1.0, "preserve": 1.0, "edge": 0.4, "return": 0.4},
        },
    }
    return _matrix_from_returns(per, incumbent, meta, n_obs=40)


def test_evaluate_gate_is_deterministic() -> None:
    matrix = _strong_promotable_matrix()
    params = _permissive_params()
    v1 = G.evaluate_gate(matrix, params)
    v2 = G.evaluate_gate(matrix, params)
    assert v1 == v2  # frozen dataclass equality — identical inputs => identical verdict


def test_evaluate_gate_returns_a_gate_verdict() -> None:
    v = G.evaluate_gate(_strong_promotable_matrix(), _permissive_params())
    assert isinstance(v, GateVerdict)


def test_evaluate_gate_selects_highest_survival_net_config() -> None:
    # The gate must select the highest mean survival-net config from the trial
    # set ("winner" here), regardless of whether it ultimately promotes.
    v = G.evaluate_gate(_strong_promotable_matrix(), _permissive_params())
    assert v.selected_config == "winner"


def test_evaluate_gate_promotes_a_strong_consistent_winner() -> None:
    v = G.evaluate_gate(_strong_promotable_matrix(), _permissive_params())
    assert v.promote is True
    assert v.min_trl_met is True
    assert v.lexicographic_ok is True


def test_degenerate_trial_set_n1_does_not_promote() -> None:
    # N=1 is a degenerate trial set: SR0 = sqrt(V)*Phi^{-1}(1 - 1/1) =
    # Phi^{-1}(0) = -inf blows up the deflation — the MATH degeneracy is exactly
    # WHY a single-config trial set can't earn a deflated pass. Fail-safe (P7):
    # promote = false, NOT a spurious pass.
    matrix = _matrix_from_returns(
        per_config={"only": [0.20, 0.22, 0.19, 0.21, 0.20, 0.23, 0.18, 0.20]},
        incumbent=[0.05] * 8,
    )
    v = G.evaluate_gate(matrix, _permissive_params())
    assert v.promote is False
    assert any("degenerate" in r.lower() or "trial" in r.lower() for r in v.reasons)


def test_insufficient_oos_data_does_not_promote() -> None:
    # MinTRL not met: too few OOS observations for the candidate's distribution
    # => no-promote, retain incumbent (R5.4, audit `insufficient_oos`).
    matrix = _strong_promotable_matrix()
    # Demand a track record longer than this matrix supplies.
    params = _permissive_params(min_trl=10_000)
    v = G.evaluate_gate(matrix, params)
    assert v.promote is False
    assert v.min_trl_met is False
    assert any("trl" in r.lower() or "insufficient" in r.lower() for r in v.reasons)


def test_is_sharpe_never_changes_the_verdict() -> None:
    # R4.5 / R5.5: the gate must never consult an in-sample Sharpe. Injecting an
    # arbitrary `is_sharpe` into trial_metadata (and a wildly different one) must
    # not move the verdict by one bit — the gate ignores it entirely.
    base_meta = _strong_promotable_matrix().trial_metadata
    m_lo = OOSMatrix(
        per_config=_strong_promotable_matrix().per_config,
        incumbent=_strong_promotable_matrix().incumbent,
        trial_metadata={**base_meta, "is_sharpe": -99.0, "in_sample_sharpe": -99.0},
    )
    m_hi = OOSMatrix(
        per_config=_strong_promotable_matrix().per_config,
        incumbent=_strong_promotable_matrix().incumbent,
        trial_metadata={**base_meta, "is_sharpe": +99.0, "in_sample_sharpe": +99.0},
    )
    params = _permissive_params()
    assert G.evaluate_gate(m_lo, params) == G.evaluate_gate(m_hi, params)


def test_section13_guard_rejects_edge_gain_that_lowers_survive() -> None:
    # §13 lexicographic: Survive ⊳ Preserve ⊳ Edge ⊳ Return. The gate must NOT
    # promote a config that ranks higher on Edge/Return at the cost of a worse
    # Survive (R6.3). Here "winner" has the highest survival-net return AND the
    # highest Edge, but a LOWER Survive score than the incumbent => the guard
    # must veto the promotion even though every statistical sub-check passes.
    per = {
        "winner": [0.18, 0.20, 0.19, 0.21, 0.20, 0.19, 0.22, 0.20],
        "mid": [0.06, 0.07, 0.05, 0.08, 0.06, 0.07, 0.05, 0.06],
    }
    incumbent = [0.05] * 8
    meta = {
        "effective_n": 2,
        "lexicographic": {
            # winner trades Survive (0.70 < incumbent 0.95) for a higher Edge.
            "winner": {"survive": 0.70, "preserve": 1.0, "edge": 0.95, "return": 0.95},
            "mid": {"survive": 1.0, "preserve": 1.0, "edge": 0.5, "return": 0.5},
            "__incumbent__": {"survive": 0.95, "preserve": 1.0, "edge": 0.4, "return": 0.4},
        },
    }
    matrix = _matrix_from_returns(per, incumbent, meta, n_obs=40)
    v = G.evaluate_gate(matrix, _permissive_params())
    assert v.selected_config == "winner"  # still SELECTS the highest survival-net
    assert v.lexicographic_ok is False
    assert v.promote is False
    assert any("13" in r or "lexicograph" in r.lower() or "survive" in r.lower() for r in v.reasons)


def test_section13_decomposition_absent_is_unconfirmable_no_promote() -> None:
    # Fail-safe (P7): if the §13 decomposition for the selected config is absent
    # from trial_metadata, lexicographic_ok cannot be CONFIRMED => promote=false.
    matrix = _matrix_from_returns(
        per_config={
            "a": [0.18, 0.20, 0.19, 0.21, 0.20, 0.19, 0.22, 0.20],
            "b": [0.06, 0.07, 0.05, 0.08, 0.06, 0.07, 0.05, 0.06],
        },
        incumbent=[0.05] * 8,
        trial_metadata={"effective_n": 2},  # no "lexicographic" key
    )
    v = G.evaluate_gate(matrix, _permissive_params())
    assert v.lexicographic_ok is False
    assert v.promote is False


def test_oos_margin_not_beaten_does_not_promote() -> None:
    # R5.5: the selected candidate must beat the incumbent by a configured OOS
    # margin. Here the best config barely exceeds the incumbent; a large margin
    # is not cleared => no-promote.
    matrix = _strong_promotable_matrix()
    params = _permissive_params(oos_margin=1.0)  # impossibly large margin
    v = G.evaluate_gate(matrix, params)
    assert v.promote is False
    assert any("margin" in r.lower() for r in v.reasons)


def test_pbo_over_threshold_does_not_promote() -> None:
    # R5.1: a high Probability of Backtest Overfitting blocks promotion. The
    # 4-partition rank-reversal matrix (gate picks S=4 ⇒ PBO=0.3333, the
    # hand-anchored value) exceeds a strict pbo_threshold. Benign §13 metadata
    # so the §13 guard is NOT the binding reason — PBO must be cited.
    per = {
        "c0": [0.40, 0.40, 0.01, 0.01],
        "c1": [0.10, 0.10, 0.05, 0.05],
        "c2": [0.05, 0.05, 0.10, 0.10],
        "c3": [0.01, 0.01, 0.40, 0.40],
    }
    meta = {
        "effective_n": 4,
        "lexicographic": {
            "c0": {"survive": 1.0, "preserve": 1.0, "edge": 0.9, "return": 0.9},
            "c3": {"survive": 1.0, "preserve": 1.0, "edge": 0.9, "return": 0.9},
            "__incumbent__": {"survive": 1.0, "preserve": 1.0, "edge": 0.4, "return": 0.4},
        },
    }
    matrix = _matrix_from_returns(per, [0.0] * 4, meta, n_obs=40)
    params = _permissive_params(pbo_threshold=0.10, min_trl=10, min_btl=4)
    v = G.evaluate_gate(matrix, params)
    assert v.promote is False
    assert v.pbo == pytest.approx(1.0 / 3.0, abs=1e-9)
    assert any("pbo" in r.lower() or "overfit" in r.lower() for r in v.reasons)


def test_effective_n_is_logged_from_trial_metadata() -> None:
    # R5.2: the gate logs the effective number of independent trials it deflated
    # against. It takes the orchestrator's conservative estimate from
    # trial_metadata (NOT the raw config count, NOT a downward MinBTL cap).
    matrix = _strong_promotable_matrix()  # meta effective_n=3
    v = G.evaluate_gate(matrix, _permissive_params())
    assert v.effective_n == 3


def test_more_trials_never_make_promotion_easier_the_deflation_direction() -> None:
    # THE deflation must hold AT THE GATE level, not just in the primitive:
    # a BROADER trial set (more effective trials) can only make promotion
    # HARDER, never easier (R5.1/R5.3, P7). Same matrix + benchmark, vary only
    # effective_n via trial_metadata; the larger-N DSR must be <= the smaller-N
    # DSR, and a larger-N must never promote while a smaller-N declines.
    base = _strong_promotable_matrix()

    def with_effn(n: int) -> OOSMatrix:
        return OOSMatrix(
            per_config=base.per_config,
            incumbent=base.incumbent,
            trial_metadata={**base.trial_metadata, "effective_n": n},
        )

    params = _permissive_params(min_btl=2)  # history (320/trial) easily clears
    v_few = G.evaluate_gate(with_effn(5), params)
    v_many = G.evaluate_gate(with_effn(20), params)
    # STRICT: more trials => larger SR0 => strictly smaller DSR (the deflation).
    # `<` (not `<=`) is the discriminating assertion: a downward MinBTL clamp on
    # effective_n would collapse both to the same floor => equal DSR => `<=`
    # would spuriously pass. `<` catches that inversion.
    assert v_many.dsr < v_few.dsr
    # And promotion can only get harder, never easier.
    assert not (v_many.promote and not v_few.promote)
    # A very broad trial set (N=100) deflates so hard it must DECLINE under the
    # same permissive params — the clean end-to-end discriminator (a downward
    # clamp would instead pretend N=2 and spuriously promote).
    assert G.evaluate_gate(with_effn(100), params).promote is False


def test_min_btl_declines_when_search_too_broad_for_history() -> None:
    # R5.3: MinBTL is a history-sufficiency DECLINE, not a downward deflation
    # cap. Each effective trial must be backed by >= min_btl observations of
    # history. Here the selected config has 8*40 = 320 OOS obs; with
    # effective_n=20 that is 16 obs/trial — below a min_btl of 50 => DECLINE.
    base = _strong_promotable_matrix()
    matrix = OOSMatrix(
        per_config=base.per_config,
        incumbent=base.incumbent,
        trial_metadata={**base.trial_metadata, "effective_n": 20},
    )
    params = _permissive_params(min_btl=50)  # 320/20 = 16 < 50
    v = G.evaluate_gate(matrix, params)
    assert v.promote is False
    assert any("min_btl" in r.lower() or "breadth" in r.lower() for r in v.reasons)
    # The reported effective_n is NOT clamped down — it is the breadth that
    # triggered the decline.
    assert v.effective_n == 20


def test_empty_trial_set_does_not_promote() -> None:
    # Degenerate: no configs at all => no viable candidate => promote=false,
    # selected_config=None (P7 fail-safe), no exception.
    matrix = OOSMatrix(per_config={}, incumbent=[_sample(0.05)], trial_metadata={})
    v = G.evaluate_gate(matrix, _permissive_params())
    assert v.promote is False
    assert v.selected_config is None


def test_malformed_matrix_fails_toward_no_promote() -> None:
    # Gate exception / malformed matrix => promote=false (fail toward
    # not-promoting; design §Error Handling). A config with an empty series.
    matrix = OOSMatrix(
        per_config={"broken": []},
        incumbent=[_sample(0.05)],
        trial_metadata={},
    )
    v = G.evaluate_gate(matrix, _permissive_params())
    assert v.promote is False
