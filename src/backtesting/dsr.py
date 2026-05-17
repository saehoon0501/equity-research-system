"""Deflated Sharpe Ratio (DSR).

Reference:
    Bailey, D. H., and Lopez de Prado, M. (2014). "The Deflated Sharpe Ratio:
    Correcting for Selection Bias, Backtest Overfitting, and Non-Normality."
    Journal of Portfolio Management, 40(5), 94–107.

Pure-stats implementation; no PIT fundamentals required. Inputs are a single
strategy's observed Sharpe ratio plus the trial count it was selected from.

The DSR adjusts an observed Sharpe ratio for two effects the headline number
ignores:
  1. Selection bias: when N strategies are tried and the best is reported, the
     reported Sharpe is an upper-order statistic, not a representative draw.
  2. Non-normal returns: skew and kurtosis change the standard error of the
     Sharpe estimator.

Formula (Bailey-Lopez de Prado 2014, eq. 9):

    DSR = Φ( (SR - E[max SR | N trials]) * sqrt(T - 1) /
              sqrt(1 - skew*SR + ((kurt - 1)/4)*SR^2) )

where Φ is the standard-normal CDF; SR is the *non-annualized* per-period
Sharpe; T is the number of return observations; skew/kurt are the third/fourth
moments of the strategy's return distribution. Defaults skew=0, kurt=3 reduce
the denominator to sqrt(1 + SR^2/2), matching the iid-normal special case.

E[max SR | N] is approximated via the expected-maximum of N iid standard-normal
draws (Bailey-Lopez de Prado 2014, eq. 6):

    E[max SR | N] ≈ (1 - γ) Φ⁻¹(1 - 1/N) + γ Φ⁻¹(1 - 1/(N*e))

where γ ≈ 0.5772 is the Euler-Mascheroni constant.

Note on units: callers commonly hold an annualized Sharpe (SR_ann = SR_per *
sqrt(periods_per_year)). We accept either via the `sharpe_periods_per_year`
parameter and convert internally to per-period for the math.
"""

from __future__ import annotations

import math

from scipy.stats import norm

# Euler-Mascheroni constant. The expected-max approximation in Bailey-Lopez
# de Prado 2014 derives from the asymptotic distribution of the maximum of N
# iid standard normals, where γ enters via the Gumbel-distribution mean shift.
_EULER_MASCHERONI = 0.5772156649015329


def expected_max_sharpe(n_trials: int) -> float:
    """Expected maximum Sharpe ratio over N independent backtest trials.

    Per Bailey-Lopez de Prado 2014 eq. 6, approximating the expected max of N
    iid standard normals. Returned in per-period units (caller scales).

    Args:
        n_trials: number of independent strategy trials. Must be >= 1; for
                  n_trials==1 the expectation collapses to 0 and selection bias
                  is nil (no choice was made).

    Returns:
        E[max_i SR_i] under the iid-standard-normal null.
    """
    if n_trials < 1:
        raise ValueError(f"n_trials must be >= 1, got {n_trials}")
    if n_trials == 1:
        return 0.0
    # ppf(1 - 1/N) is the inverse-CDF point at quantile 1 - 1/N.
    term_a = (1.0 - _EULER_MASCHERONI) * norm.ppf(1.0 - 1.0 / n_trials)
    term_b = _EULER_MASCHERONI * norm.ppf(1.0 - 1.0 / (n_trials * math.e))
    return float(term_a + term_b)


def deflated_sharpe_ratio(
    sharpe_ratio: float,
    n_observations: int,
    n_trials: int,
    skew: float = 0.0,
    kurtosis: float = 3.0,
    sharpe_periods_per_year: int | None = None,
) -> float:
    """Compute the Deflated Sharpe Ratio.

    Args:
        sharpe_ratio:               observed Sharpe ratio. By default treated
                                    as per-period; pass `sharpe_periods_per_year`
                                    to indicate the input is annualized and have
                                    it de-annualized internally.
        n_observations:             number of return observations T (e.g. 120
                                    monthly, 252 daily).
        n_trials:                   total number of trial strategies / parameter
                                    combinations evaluated. Each alternate
                                    parameter set MUST be counted as a trial,
                                    per `.claude/commands/backtest.md` §11.
        skew:                       third moment of returns (0 for normal).
        kurtosis:                   fourth moment of returns (3 for normal).
        sharpe_periods_per_year:    if provided, divide `sharpe_ratio` by
                                    sqrt(periods_per_year) before applying the
                                    formula. Common values: 252 (daily), 12
                                    (monthly). None means input is per-period.

    Returns:
        DSR ∈ [0, 1] — a probability that the true Sharpe exceeds zero given
        the trial count and distributional assumptions. Common gate per
        docs/phasing-plan.md §2.5.3: DSR > 0.5.
    """
    if n_observations < 2:
        raise ValueError(f"n_observations must be >= 2, got {n_observations}")
    if n_trials < 1:
        raise ValueError(f"n_trials must be >= 1, got {n_trials}")

    sr = sharpe_ratio
    if sharpe_periods_per_year is not None:
        if sharpe_periods_per_year < 1:
            raise ValueError(
                f"sharpe_periods_per_year must be >= 1, got {sharpe_periods_per_year}"
            )
        sr = sr / math.sqrt(sharpe_periods_per_year)

    expected_max = expected_max_sharpe(n_trials)

    # Variance of the Sharpe ratio estimator under non-normal returns
    # (Mertens 2002 / Bailey-Lopez de Prado 2014 eq. 9 denominator).
    variance_term = 1.0 - skew * sr + ((kurtosis - 1.0) / 4.0) * sr * sr
    if variance_term <= 0:
        # Degenerate distributional inputs; the formula's variance term must
        # be positive. Fall back to the iid-normal denominator.
        variance_term = 1.0 + (sr * sr) / 2.0

    z = (sr - expected_max) * math.sqrt(n_observations - 1) / math.sqrt(variance_term)
    return float(norm.cdf(z))
