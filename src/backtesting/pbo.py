"""Probability of Backtest Overfitting (PBO).

Reference:
    Bailey, D. H., Borwein, J., Lopez de Prado, M., and Zhu, Q. J. (2014).
    "The Probability of Backtest Overfitting."
    Journal of Computational Finance, 20(4), 39-69.

Implements Combinatorially-Symmetric Cross-Validation (CSCV). Pure stats; no
PIT fundamentals required. Operates on a T×N matrix of period-by-strategy
returns: T time-rows, N candidate-strategy columns.

The intuition: if the strategy that wins in-sample reliably wins out-of-sample,
PBO is low. If the in-sample winner places randomly out-of-sample, PBO ≈ 0.5
(no information). PBO > 0.5 means the in-sample winner systematically
underperforms out-of-sample — overfitting worse than random.

Algorithm (Bailey et al. 2014 §3):

    1. Split the T rows into S equal partitions (default S=16 per the paper).
    2. For each combination of S/2 partitions taken as "in-sample":
         a. Concatenate the S/2 IS partitions; remaining S/2 form OOS.
         b. Compute a performance metric (default: Sharpe) per strategy on IS.
         c. The IS winner is the column with max IS-Sharpe.
         d. Find that column's OOS rank; convert to a relative rank
            r in (0, 1) = (OOS_rank - 1) / (N - 1) for the winner.
         e. Compute logit: λ = log(r / (1 - r)). Negative λ means the IS
            winner placed in the bottom half OOS.
    3. PBO = fraction of combinations with λ < 0.
"""

from __future__ import annotations

import math
from itertools import combinations

import numpy as np


def _sharpe(returns: np.ndarray, axis: int = 0) -> np.ndarray:
    """Per-column Sharpe along `axis`. Returns NaN-safe; zero std → 0 Sharpe."""
    mean = np.nanmean(returns, axis=axis)
    std = np.nanstd(returns, axis=axis, ddof=1)
    # Avoid divide-by-zero — a column with no variance is treated as 0 Sharpe
    # rather than crashing the partition.
    out = np.zeros_like(mean, dtype=float)
    nz = std > 0
    out[nz] = mean[nz] / std[nz]
    return out


def probability_of_backtest_overfitting(
    returns_matrix: np.ndarray,
    n_partitions: int = 16,
    metric: str = "sharpe",
) -> float:
    """Compute PBO via Combinatorially-Symmetric Cross-Validation.

    Args:
        returns_matrix:     T×N numpy array. T period rows, N strategy columns.
        n_partitions:       S in Bailey et al. — must be even and ≥ 4. Default
                            16 matches the paper's recommendation.
        metric:             which per-strategy metric to rank IS/OOS by. Only
                            "sharpe" is implemented. Other metrics (Sortino,
                            Calmar) are mechanically identical — replace the
                            ranker if needed.

    Returns:
        PBO ∈ [0, 1]. Gate per docs/phasing-plan.md §2.5.3: PBO < 0.5.

    Raises:
        ValueError on a malformed matrix or odd `n_partitions`.
    """
    if metric != "sharpe":
        raise ValueError(f"metric={metric!r} not implemented; only 'sharpe'")
    arr = np.asarray(returns_matrix, dtype=float)
    if arr.ndim != 2:
        raise ValueError(f"returns_matrix must be 2-D, got shape {arr.shape}")
    n_periods, n_strategies = arr.shape
    if n_strategies < 2:
        raise ValueError(
            f"PBO requires at least 2 strategy columns, got {n_strategies}"
        )
    if n_partitions < 4 or n_partitions % 2 != 0:
        raise ValueError(
            f"n_partitions must be even and >= 4, got {n_partitions}"
        )
    if n_periods < n_partitions:
        raise ValueError(
            f"n_periods={n_periods} must be >= n_partitions={n_partitions}"
        )

    # Trim to a clean multiple so each partition has equal length. Per Bailey
    # et al. §3.1 — equal partitions preserve the symmetry of the CSCV.
    rows_per_partition = n_periods // n_partitions
    usable = rows_per_partition * n_partitions
    arr = arr[:usable]

    # partition_indices[s] = indices of rows belonging to partition s.
    partition_indices = [
        np.arange(s * rows_per_partition, (s + 1) * rows_per_partition)
        for s in range(n_partitions)
    ]

    half = n_partitions // 2
    n_overfit = 0
    n_total = 0

    for is_partitions in combinations(range(n_partitions), half):
        is_idx = np.concatenate(
            [partition_indices[s] for s in is_partitions]
        )
        oos_partitions = [s for s in range(n_partitions) if s not in is_partitions]
        oos_idx = np.concatenate(
            [partition_indices[s] for s in oos_partitions]
        )

        is_perf = _sharpe(arr[is_idx], axis=0)
        oos_perf = _sharpe(arr[oos_idx], axis=0)

        is_winner = int(np.argmax(is_perf))
        # OOS rank of the IS winner — 1-indexed, ascending (1 = worst).
        # Use rankdata-style with average tie handling.
        oos_winner_value = oos_perf[is_winner]
        oos_rank = 1 + np.sum(oos_perf < oos_winner_value) + 0.5 * (
            np.sum(oos_perf == oos_winner_value) - 1
        )
        # Relative rank in (0, 1).
        relative_rank = oos_rank / (n_strategies + 1)
        # Clip to keep the logit finite.
        relative_rank = float(np.clip(relative_rank, 1e-9, 1 - 1e-9))
        logit = math.log(relative_rank / (1.0 - relative_rank))

        if logit < 0:
            n_overfit += 1
        n_total += 1

    return float(n_overfit) / float(n_total) if n_total > 0 else 0.0
