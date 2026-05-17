"""BB-pseudo-BMA+ regime weights — v0.5 upgrade (v3 spec §4.1 + §6.4).

Per spec, the v0.1 regime sidecar uses pure 1/6 equal-weight across the
6 Tier-1 dimensions (Smith-Wallis 2009; Claeskens-Magnus-Vasnev-Wang
2016 — equal-weight beats optimization at small N). At v0.5+:

    N≈30 (months 12)  : pseudo-BMA+ shadow-running; equal-weight live
    N≈30 promote      : Bayes-factor > 20 vs equal-weight (Kass-Raftery)
    N≈50 (months 18+) : BB-pseudo-BMA+ with Diebold-Pauly shrinkage:

        w_final = (38/(38+N)) · w_equal_1/6 + (N/(38+N)) · w_pseudoBMA+

    Classical BMA REJECTED (M-closed assumption fails per Yao et al. 2018).

Implementation:
    * `compute_pseudo_bma_plus(lpd_matrix)` — Yao et al. 2018 weights from
      out-of-sample log-pointwise predictive density per dimension.
    * `bb_stabilize(lpd_matrix, n_bootstrap)` — Bayesian-Bootstrap stabilized
      version (resample observation weights from Dirichlet(1,...,1)).
    * `diebold_pauly_shrunk(bma_weights, n)` — final BB-pseudo-BMA+ weights
      after shrinkage toward equal-weight.

The lpd_matrix is K × N (K dimensions, N observations). Each entry is the
log-likelihood the dimension's prediction assigned to the realized outcome.
For the equity-research system: dimension d on date t predicts a regime-
shift probability that maps to an unfavorable-alpha probability for the
recommendation; lpd_{d,t} = log(p) if y=1 else log(1-p).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

# Diebold-Pauly shrinkage constant per spec §4.1: shrinks pseudo-BMA+
# weights toward equal-weight. 38 is the operator-locked anchor.
_SHRINKAGE_ANCHOR = 38

# Default BB resample count. Yao et al. 2018 uses 1000+; we default to 200
# for tractable v0.5 latency. Caller can raise it for offline calibration.
_DEFAULT_BB_RESAMPLES = 200

# Min lpd value to keep elpd finite when one dimension assigns probability ~0
# to a realized outcome. log(0.02) ≈ -3.91; we clamp pointwise lpd at this
# floor so a single near-impossible prediction doesn't single-handedly drive
# a dimension's BMA weight to zero. The dimension still gets a sharp penalty
# (it was 95%+ wrong on that observation) but the overall weight stays
# detectable rather than vanishing into floating-point dust.
_MIN_LPD = -3.91


@dataclass(frozen=True)
class BMAResult:
    """Per-dimension weights + diagnostic metadata."""

    weights: list[float]               # length K; sums to 1
    elpd: list[float]                  # per-dim expected log-predictive-density
    n_observations: int
    method: str                        # 'pseudo_bma_plus' | 'bb_pseudo_bma_plus'
                                       #  | 'shrunk_bb_pseudo_bma_plus'

    def as_dict(self, dimension_names: list[str]) -> dict[str, float]:
        if len(dimension_names) != len(self.weights):
            raise ValueError(
                "dimension_names length mismatch with weights"
            )
        return dict(zip(dimension_names, self.weights))


# --------------------------------------------------------------------------- #
# Pseudo-BMA+ (Yao et al. 2018)                                               #
# --------------------------------------------------------------------------- #


def _validate_lpd(lpd_matrix: list[list[float]]) -> tuple[int, int]:
    if not lpd_matrix:
        raise ValueError("lpd_matrix must have at least one dimension")
    K = len(lpd_matrix)
    N = len(lpd_matrix[0])
    if N == 0:
        raise ValueError("lpd_matrix must have at least one observation")
    for row in lpd_matrix:
        if len(row) != N:
            raise ValueError("lpd_matrix rows must be equal length")
    return K, N


def compute_pseudo_bma_plus(lpd_matrix: list[list[float]]) -> BMAResult:
    """Pseudo-BMA+ (Yao et al. 2018, eq. 5).

    elpd_d = sum_n lpd_{d,n}
    w_d   = exp(elpd_d - max) / sum_d exp(...)

    Subtracting max(elpd) keeps the exponential numerically stable.
    """
    K, N = _validate_lpd(lpd_matrix)

    # Sum lpd across observations per dimension; clamp pointwise lpd at floor
    # so a single near-impossible prediction can't drag a dim's weight to 0
    # via a single -inf.
    elpd = [
        sum(max(v, _MIN_LPD) for v in lpd_matrix[d])
        for d in range(K)
    ]
    max_e = max(elpd)
    raw = [math.exp(e - max_e) for e in elpd]
    total = sum(raw)
    if total <= 0:
        # All dimensions equally bad — fall back to uniform
        weights = [1.0 / K] * K
    else:
        weights = [w / total for w in raw]

    return BMAResult(
        weights=weights,
        elpd=elpd,
        n_observations=N,
        method="pseudo_bma_plus",
    )


# --------------------------------------------------------------------------- #
# BB stabilization (Bayesian Bootstrap)                                       #
# --------------------------------------------------------------------------- #


def _dirichlet_one_one(n: int, rng: random.Random) -> list[float]:
    """Sample a length-N vector from Dirichlet(1, 1, ..., 1).

    Standard trick: sample N independent Exp(1)s, normalize by the sum.
    """
    samples = [-math.log(max(rng.random(), 1e-12)) for _ in range(n)]
    s = sum(samples)
    return [x / s for x in samples] if s > 0 else [1.0 / n] * n


def bb_stabilize(
    lpd_matrix: list[list[float]],
    *,
    n_bootstrap: int = _DEFAULT_BB_RESAMPLES,
    seed: int | None = None,
) -> BMAResult:
    """Bayesian-Bootstrap-stabilized pseudo-BMA+.

    For each bootstrap replicate:
        1. Sample observation weights w ~ Dirichlet(1,...,1)
        2. Compute weighted elpd_d = Σ_n w_n × lpd_{d,n}
        3. Convert to pseudo-BMA+ weights via softmax.
    Average the per-replicate weight vectors → final BB-pseudo-BMA+ weights.

    Args:
        lpd_matrix: K × N lpd matrix.
        n_bootstrap: number of BB replicates.
        seed: deterministic seed for tests. None = system random.
    """
    K, N = _validate_lpd(lpd_matrix)
    rng = random.Random(seed)

    weight_sum = [0.0] * K
    last_elpd: list[float] = [0.0] * K

    for _ in range(n_bootstrap):
        w = _dirichlet_one_one(N, rng)
        elpd = [
            sum(max(lpd_matrix[d][n], _MIN_LPD) * w[n] for n in range(N)) * N
            for d in range(K)
        ]
        # Softmax with max-shift for stability
        max_e = max(elpd)
        raw = [math.exp(e - max_e) for e in elpd]
        s = sum(raw)
        if s > 0:
            for d in range(K):
                weight_sum[d] += raw[d] / s
        else:
            for d in range(K):
                weight_sum[d] += 1.0 / K
        last_elpd = elpd

    avg = [w / n_bootstrap for w in weight_sum]
    # Renormalize defensively (FP drift over many adds)
    s = sum(avg)
    if s > 0:
        avg = [w / s for w in avg]

    return BMAResult(
        weights=avg,
        elpd=last_elpd,
        n_observations=N,
        method="bb_pseudo_bma_plus",
    )


# --------------------------------------------------------------------------- #
# Diebold-Pauly shrinkage                                                     #
# --------------------------------------------------------------------------- #


def diebold_pauly_shrunk(
    bma_weights: list[float],
    n: int,
    *,
    equal_weight_anchor: float | None = None,
) -> list[float]:
    """Apply spec §4.1 shrinkage:

        w_final = (38/(38+N)) · w_equal + (N/(38+N)) · w_pseudoBMA+

    For small N, the equal-weight anchor dominates — robust to small-sample
    pseudo-BMA+ noise. As N grows, pseudo-BMA+ takes over.

    Args:
        bma_weights: length-K pseudo-BMA+ output (must sum to ~1).
        n: sample size used to compute bma_weights.
        equal_weight_anchor: w_equal scalar. Default = 1/K.

    Returns:
        Length-K shrunk weights. Sums to 1.0.
    """
    K = len(bma_weights)
    if K == 0:
        raise ValueError("bma_weights must be non-empty")
    if n < 0:
        raise ValueError("n must be non-negative")

    eq = equal_weight_anchor if equal_weight_anchor is not None else 1.0 / K
    eq_vec = [eq] * K

    weight_eq = _SHRINKAGE_ANCHOR / (_SHRINKAGE_ANCHOR + n)
    weight_bma = n / (_SHRINKAGE_ANCHOR + n)

    out = [
        weight_eq * eq_vec[d] + weight_bma * bma_weights[d]
        for d in range(K)
    ]
    s = sum(out)
    if s > 0:
        out = [w / s for w in out]
    return out


# --------------------------------------------------------------------------- #
# All-in-one helper                                                           #
# --------------------------------------------------------------------------- #


def shrunk_bb_pseudo_bma_plus(
    lpd_matrix: list[list[float]],
    *,
    n_bootstrap: int = _DEFAULT_BB_RESAMPLES,
    seed: int | None = None,
) -> BMAResult:
    """Compose BB-pseudo-BMA+ with Diebold-Pauly shrinkage in one call.

    This is the v0.5+ live computation. Expect it to default to a
    near-equal weighting until N ≥ ~30, then pseudo-BMA+ signal increases
    smoothly with sample size.
    """
    bb = bb_stabilize(lpd_matrix, n_bootstrap=n_bootstrap, seed=seed)
    shrunk = diebold_pauly_shrunk(bb.weights, n=bb.n_observations)
    return BMAResult(
        weights=shrunk,
        elpd=bb.elpd,
        n_observations=bb.n_observations,
        method="shrunk_bb_pseudo_bma_plus",
    )
