"""Calibration metrics — Brier, log-loss, reliability diagram, block-bootstrap CI.

WS-4. All metrics are computed on the *snapshotted* ``continuous_score`` (the
emission-time probability captured write-once in ``calibration_emission_snapshot``)
against the resolver-written ``label_binary`` outcome.

LOCKED DECISIONS:
  - Block bootstrap: block size = 5, reps = 1000, 95% CI (2.5 / 97.5 pct).
  - Bootstrap is SEEDED (mirrors the ``random.Random(sample_seed)`` precedent in
    src/backtesting/framework.py — here we use ``numpy.random.default_rng(seed)``
    so the resample is reproducible and the seed is recorded on the result).
  - ECE may be computed but MUST NOT appear in the headline. ``brier_report``
    returns a ``CalibrationReport`` whose ``headline`` dict contains ONLY
    brier / log_loss (+ their CIs) and n; ``ece`` lives off-headline.

No I/O, no clock, no DB — pure functions over (scores, labels).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

# LOCKED bootstrap parameters.
BLOCK_SIZE = 5
N_REPS = 1000
CI_LEVEL = 0.95
# Default seed — recorded on every report so a re-run is bit-reproducible.
# Mirrors framework.py's "production audits should pass a seed" guidance.
DEFAULT_BOOTSTRAP_SEED = 20260527

# Clip used for log-loss so a confident-wrong prediction yields a large-but-
# finite penalty instead of +inf. Standard sklearn-style eps.
_LOGLOSS_EPS = 1e-15


def _as_arrays(scores: Sequence[float], labels: Sequence[bool]) -> tuple[np.ndarray, np.ndarray]:
    p = np.asarray(scores, dtype=float)
    y = np.asarray([1.0 if bool(v) else 0.0 for v in labels], dtype=float)
    if p.shape != y.shape:
        raise ValueError(f"scores/labels length mismatch: {p.shape} vs {y.shape}")
    if p.size == 0:
        raise ValueError("cannot compute calibration metrics on an empty sample")
    if np.any((p < 0.0) | (p > 1.0)):
        raise ValueError("scores must lie in [0, 1]")
    return p, y


def brier_score(scores: Sequence[float], labels: Sequence[bool]) -> float:
    """Mean squared error between probability and binary outcome. Lower = better."""
    p, y = _as_arrays(scores, labels)
    return float(np.mean((p - y) ** 2))


def log_loss(scores: Sequence[float], labels: Sequence[bool]) -> float:
    """Mean binary cross-entropy with eps-clipping. Lower = better."""
    p, y = _as_arrays(scores, labels)
    pc = np.clip(p, _LOGLOSS_EPS, 1.0 - _LOGLOSS_EPS)
    return float(-np.mean(y * np.log(pc) + (1.0 - y) * np.log(1.0 - pc)))


@dataclass(frozen=True)
class ReliabilityBin:
    """One bin of a reliability diagram."""

    lower: float
    upper: float
    count: int
    mean_predicted: float  # mean score in the bin (NaN-as-None if empty)
    mean_observed: float  # empirical hit-rate in the bin


def reliability_diagram(
    scores: Sequence[float], labels: Sequence[bool], n_bins: int = 10
) -> list[ReliabilityBin]:
    """Equal-width reliability bins over [0,1].

    Bin i covers [i/n, (i+1)/n); the top bin is closed on the right so score==1.0
    lands in the last bin. Empty bins are returned with count 0 and mean_*=nan
    so the diagram has a fixed shape regardless of data density.
    """
    if n_bins < 1:
        raise ValueError("n_bins must be >= 1")
    p, y = _as_arrays(scores, labels)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    out: list[ReliabilityBin] = []
    for i in range(n_bins):
        lo, hi = float(edges[i]), float(edges[i + 1])
        if i == n_bins - 1:
            mask = (p >= lo) & (p <= hi)
        else:
            mask = (p >= lo) & (p < hi)
        cnt = int(mask.sum())
        if cnt == 0:
            out.append(ReliabilityBin(lo, hi, 0, float("nan"), float("nan")))
        else:
            out.append(
                ReliabilityBin(
                    lo,
                    hi,
                    cnt,
                    float(p[mask].mean()),
                    float(y[mask].mean()),
                )
            )
    return out


def expected_calibration_error(
    scores: Sequence[float], labels: Sequence[bool], n_bins: int = 10
) -> float:
    """ECE — count-weighted |mean_predicted - mean_observed| across bins.

    NOTE: WS-4 forbids ECE in the headline at small N. Provided for diagnostics /
    off-headline reporting only.
    """
    p, _ = _as_arrays(scores, labels)
    n = p.size
    bins = reliability_diagram(scores, labels, n_bins=n_bins)
    ece = 0.0
    for b in bins:
        if b.count == 0:
            continue
        ece += (b.count / n) * abs(b.mean_predicted - b.mean_observed)
    return float(ece)


def _block_bootstrap_indices(
    n: int, block_size: int, rng: np.random.Generator
) -> np.ndarray:
    """One block-bootstrap resample of indices for a length-n series.

    Moving-block bootstrap: draw ceil(n/block_size) blocks of consecutive
    indices, each block starting at a uniformly random position in
    [0, n-block_size] (clamped so a block never runs off the end), concatenate,
    and trim to exactly n. Preserves local (within-block) dependence — the right
    choice for time-ordered calibration where adjacent recs share regime/market
    state. Block size locked at 5.
    """
    if n <= 0:
        raise ValueError("n must be positive")
    bs = min(block_size, n)  # degrade gracefully when sample < one block
    n_blocks = int(np.ceil(n / bs))
    max_start = n - bs  # inclusive upper bound for a block start
    starts = rng.integers(0, max_start + 1, size=n_blocks)
    idx = np.concatenate([np.arange(s, s + bs) for s in starts])
    return idx[:n]


@dataclass(frozen=True)
class CI:
    point: float
    lower: float
    upper: float
    level: float = CI_LEVEL


def block_bootstrap_ci(
    metric_fn,
    scores: Sequence[float],
    labels: Sequence[bool],
    *,
    block_size: int = BLOCK_SIZE,
    n_reps: int = N_REPS,
    level: float = CI_LEVEL,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> CI:
    """Percentile block-bootstrap CI for a scalar metric on (scores, labels).

    ``metric_fn`` is e.g. ``brier_score`` / ``log_loss``. SEEDED via
    ``np.random.default_rng(seed)`` — the same seed reproduces the same CI.
    """
    p, y = _as_arrays(scores, labels)
    n = p.size
    point = float(metric_fn(p, y))
    rng = np.random.default_rng(seed)
    reps = np.empty(n_reps, dtype=float)
    for r in range(n_reps):
        idx = _block_bootstrap_indices(n, block_size, rng)
        reps[r] = float(metric_fn(p[idx], y[idx]))
    alpha = (1.0 - level) / 2.0
    lower = float(np.percentile(reps, 100.0 * alpha))
    upper = float(np.percentile(reps, 100.0 * (1.0 - alpha)))
    return CI(point=point, lower=lower, upper=upper, level=level)


@dataclass(frozen=True)
class CalibrationReport:
    """Full calibration report.

    ``headline`` contains ONLY Brier + log-loss (point + CI) and n — ECE is
    deliberately excluded per WS-4 (small-N ECE is unstable). ECE and the
    reliability diagram live as off-headline diagnostics.
    """

    n: int
    brier: CI
    log_loss: CI
    reliability: list[ReliabilityBin]
    ece: float  # off-headline diagnostic only
    seed: int
    block_size: int
    n_reps: int

    @property
    def headline(self) -> dict:
        """Headline metrics — Brier + log-loss + n. NO ECE (WS-4)."""
        return {
            "n": self.n,
            "brier": {
                "point": self.brier.point,
                "ci_lower": self.brier.lower,
                "ci_upper": self.brier.upper,
                "ci_level": self.brier.level,
            },
            "log_loss": {
                "point": self.log_loss.point,
                "ci_lower": self.log_loss.lower,
                "ci_upper": self.log_loss.upper,
                "ci_level": self.log_loss.level,
            },
        }


def calibration_report(
    scores: Sequence[float],
    labels: Sequence[bool],
    *,
    n_bins: int = 10,
    block_size: int = BLOCK_SIZE,
    n_reps: int = N_REPS,
    level: float = CI_LEVEL,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> CalibrationReport:
    """Compute the full WS-4 calibration report on snapshotted scores vs labels."""
    p, y = _as_arrays(scores, labels)
    brier_ci = block_bootstrap_ci(
        brier_score, p, y, block_size=block_size, n_reps=n_reps, level=level, seed=seed
    )
    ll_ci = block_bootstrap_ci(
        log_loss, p, y, block_size=block_size, n_reps=n_reps, level=level, seed=seed
    )
    rel = reliability_diagram(p, y, n_bins=n_bins)
    ece = expected_calibration_error(p, y, n_bins=n_bins)
    return CalibrationReport(
        n=int(p.size),
        brier=brier_ci,
        log_loss=ll_ci,
        reliability=rel,
        ece=ece,
        seed=seed,
        block_size=block_size,
        n_reps=n_reps,
    )
