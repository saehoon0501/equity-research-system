"""Self-consistency aggregation helper for the LLM articulation sub-metrics.

Reference pattern: ``src/p3_mechanical_scorer/stage2_llm_rubric.py``
(``_aggregate_self_consistency`` — N=5 @ temp 0.7, median). That helper
aggregates ordinal LOW/MEDIUM/HIGH ratings; ours aggregates *numeric*
[0,1] scores (faithfulness / relevancy / factuality), so we take a plain
median over floats rather than ``median_low`` over ordinals. We pull the
N and temperature constants straight from ``src.p3_mechanical_scorer`` so
the two stay locked together (LOCKED DECISION: N=5 @ temp 0.7).

First-pass-only: callers draw exactly N samples once; there is no retry /
re-sample loop here.
"""

from __future__ import annotations

import statistics
from typing import Callable

# LOCKED constants reused by import (do NOT redefine).
from src.p3_mechanical_scorer import (
    SELF_CONSISTENCY_N,
    SELF_CONSISTENCY_TEMP,
)

__all__ = [
    "SELF_CONSISTENCY_N",
    "SELF_CONSISTENCY_TEMP",
    "median_self_consistency",
]


def median_self_consistency(
    sampler: Callable[[int], float],
    *,
    n: int = SELF_CONSISTENCY_N,
) -> tuple[float, list[float]]:
    """Draw ``n`` samples and return (median, raw_samples).

    Args:
        sampler: callable ``sample_index -> float in [0, 1]``. The
            ``sample_index`` is passed through so a cache keys each draw
            distinctly (see src/llm_cache: the 5-tuple includes
            ``sample_index`` so N samples never collapse to one entry).
        n: number of self-consistency samples (default LOCKED N=5).

    Returns:
        (median_score, [sample_0, ..., sample_{n-1}]).

    Median is ``statistics.median`` over floats (vs the p3 reference's
    ``median_low`` over LOW/MEDIUM/HIGH ordinals — different domain).
    """
    samples: list[float] = []
    for i in range(n):
        val = float(sampler(i))
        # Clamp into [0, 1] — a stray model value never poisons the median.
        samples.append(min(1.0, max(0.0, val)))
    median = statistics.median(samples)
    return median, samples
