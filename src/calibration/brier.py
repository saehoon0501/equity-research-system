"""Brier-haircut on conviction (v3 spec §6.4 + §8.1).

The Brier score for a binary outcome is

    BS = mean( (p_i - y_i)^2 )

with p_i = the system's predicted probability of the favorable outcome and
y_i = the realized outcome (1 if the favorable outcome occurred, 0 otherwise).

For the equity-research system:
    * "favorable outcome" = the recommendation outperformed its benchmark at
      T+90d (delta_vs_benchmark_90d > 0). We use 90d because that's the
      trigger horizon for v0.5-active per phase_detector.
    * predicted probability comes from the conviction tier:
          HIGH   → 0.70
          MEDIUM → 0.50
          LOW    → 0.30
      The mapping is a starting prior; once a per-cell history of resolved
      predictions accumulates v0.5 will recalibrate it empirically (Section
      6.4 "calibration ladder").

Cells:
    Per-cell aggregation matches §6.0 calibration-circularity defense and
    §8.1 v0.5+ activation: (mode, materiality, recommendation_type). For
    BUY/TRIM the favorable outcome is positive alpha; for SELL/HOLD the
    favorable outcome is non-positive alpha (i.e., we recommended exit and
    it underperformed). The y_i mapping is centralized below.

Haircut policy at v0.5-active:
    Per spec §6.4, the haircut converts a calibration penalty into a
    conviction demote. Concretely:

        excess = max(0, brier - 0.25)        # 0.25 = random-baseline
        demote_steps = int(round(excess / 0.05))

    excess ≤ 0.05 → no demote, ≤ 0.10 → 1 step, ≤ 0.15 → 2 steps, …
    The conviction tier slides one band per step (HIGH→MEDIUM→LOW). LOW
    cannot demote further; the function returns LOW.

    At v0.1 the haircut is computed in shadow mode and stored alongside the
    recommendation; phase_detector flips the actual application live at
    v0.5-active (§8.1 trigger).
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Optional

# Conviction → probability prior. Recalibrated at v0.5+ once N≥50 outcomes
# accrue per cell.
CONVICTION_PRIOR: dict[str, float] = {
    "HIGH": 0.70,
    "MEDIUM": 0.50,
    "LOW": 0.30,
}

# Random-prediction baseline. Brier above this → calibration is degrading.
BRIER_RANDOM_BASELINE = 0.25

# Demote-step granularity per spec §6.4. 0.05 excess = 1 conviction band.
HAIRCUT_STEP_BRIER = 0.05

# Tier ladder for demotion.
_DEMOTE_LADDER = ["HIGH", "MEDIUM", "LOW"]

# Cap on rows pulled per `score_brier` call to keep the calculation O(N) and
# bounded in memory. v0.5 N is in the low hundreds; this cap is generous.
_MAX_ROWS_PER_CALL = 50_000


class BrierScope(str, Enum):
    """Aggregation grain for `score_brier`."""

    GLOBAL = "global"            # one cell across the whole corpus
    BY_MODE = "by_mode"          # B / B_prime / C
    BY_RECOMMENDATION = "by_rec" # BUY / HOLD / TRIM / SELL
    BY_CELL = "by_cell"          # (mode, materiality, recommendation) — full §6.0


@dataclass(frozen=True)
class BrierCell:
    """One aggregation cell's Brier score + sample size."""

    scope_key: tuple                 # ('global',) | ('B', 'M-2', 'BUY') | etc.
    n: int
    brier: float
    mean_predicted: float            # mean p_i across the cell
    mean_realized: float             # base rate y_i
    horizon: str                     # '30d' | '90d' | '1y'


# --------------------------------------------------------------------------- #
# Outcome → favorable mapping                                                 #
# --------------------------------------------------------------------------- #


def _favorable(rec_type: str, delta_vs_benchmark: Optional[float]) -> Optional[int]:
    """Map (recommendation_type, delta_vs_benchmark) → 1 (favorable) / 0 / None.

    BUY / TRIM are bullish-bias signals: favorable if delta > 0.
    SELL is a bearish-bias signal: favorable if delta < 0 (we said exit and
    it underperformed). HOLD is "do nothing"; treat as favorable iff |delta|
    is small (< 0.02 = 2pp). NULL delta → None.

    Returning None signals "skip this row from the Brier calculation".
    """
    if delta_vs_benchmark is None:
        return None
    if rec_type == "BUY" or rec_type == "TRIM":
        return 1 if delta_vs_benchmark > 0 else 0
    if rec_type == "SELL":
        return 1 if delta_vs_benchmark < 0 else 0
    if rec_type == "HOLD":
        return 1 if abs(delta_vs_benchmark) < 0.02 else 0
    return None


# --------------------------------------------------------------------------- #
# Score                                                                       #
# --------------------------------------------------------------------------- #


def score_brier(
    conn: Any,
    *,
    scope: BrierScope = BrierScope.GLOBAL,
    horizon: str = "90d",
    as_of: Optional[_dt.date] = None,
) -> list[BrierCell]:
    """Compute Brier scores per scope cell against resolved outcomes.

    Args:
        scope: aggregation grain (see BrierScope).
        horizon: '30d' | '90d' | '1y'. Selects the matching delta column.
        as_of: only consider outcomes resolved at-or-before this date
            (i.e., t_plus_<horizon>_close_date ≤ as_of). Default: no cutoff.

    Returns:
        List of BrierCell, one per non-empty cell in the requested scope.
        Empty list if no resolved outcomes exist for the horizon.
    """
    if horizon not in {"30d", "90d", "1y"}:
        raise ValueError(f"horizon must be 30d|90d|1y, got {horizon!r}")

    delta_col = f"delta_vs_benchmark_{horizon}"
    close_col = f"t_plus_{horizon}_close_date"

    where_as_of = ""
    params: list[Any] = []
    if as_of is not None:
        where_as_of = f"AND ro.{close_col} <= %s"
        params.append(as_of)

    sql = f"""
        SELECT
            er.mode,
            COALESCE(er.trigger_metadata->>'triggered_by', 'cadence') AS materiality_proxy,
            er.recommendation,
            er.conviction,
            ro.{delta_col} AS delta
        FROM execution_recommendations er
        JOIN recommendation_outcomes ro
            ON ro.recommendation_id = er.recommendation_id
        WHERE ro.{delta_col} IS NOT NULL
          {where_as_of}
        LIMIT {_MAX_ROWS_PER_CALL}
    """
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        rows = cur.fetchall()
    finally:
        cur.close()

    return _aggregate(rows, scope=scope, horizon=horizon)


def _aggregate(
    rows: Iterable[tuple],
    *,
    scope: BrierScope,
    horizon: str,
) -> list[BrierCell]:
    """Bucket rows per scope, then compute Brier per bucket."""
    buckets: dict[tuple, list[tuple[float, int]]] = {}

    for r in rows:
        mode, materiality, rec_type, conviction, delta = r
        delta_f = float(delta) if delta is not None else None
        y = _favorable(rec_type, delta_f)
        if y is None:
            continue
        p = CONVICTION_PRIOR.get(conviction)
        if p is None:
            continue

        if scope is BrierScope.GLOBAL:
            key = ("global",)
        elif scope is BrierScope.BY_MODE:
            key = (mode,)
        elif scope is BrierScope.BY_RECOMMENDATION:
            key = (rec_type,)
        else:  # BY_CELL
            key = (mode, materiality, rec_type)

        buckets.setdefault(key, []).append((p, y))

    out: list[BrierCell] = []
    for key, samples in buckets.items():
        n = len(samples)
        if n == 0:
            continue
        brier = sum((p - y) ** 2 for p, y in samples) / n
        mean_p = sum(p for p, _ in samples) / n
        mean_y = sum(y for _, y in samples) / n
        out.append(
            BrierCell(
                scope_key=key,
                n=n,
                brier=brier,
                mean_predicted=mean_p,
                mean_realized=mean_y,
                horizon=horizon,
            )
        )
    out.sort(key=lambda c: (c.n * -1, c.scope_key))
    return out


# --------------------------------------------------------------------------- #
# Haircut                                                                     #
# --------------------------------------------------------------------------- #


def apply_haircut(conviction: str, brier: float) -> str:
    """Demote conviction by N steps based on Brier excess vs random baseline.

    >>> apply_haircut('HIGH', 0.20)
    'HIGH'
    >>> apply_haircut('HIGH', 0.30)   # excess 0.05 → 1 step
    'MEDIUM'
    >>> apply_haircut('HIGH', 0.40)   # excess 0.15 → 3 steps; clamps to LOW
    'LOW'
    >>> apply_haircut('LOW', 0.99)
    'LOW'
    """
    if conviction not in _DEMOTE_LADDER:
        raise ValueError(f"conviction must be HIGH|MEDIUM|LOW, got {conviction!r}")
    if brier <= BRIER_RANDOM_BASELINE:
        return conviction
    excess = brier - BRIER_RANDOM_BASELINE
    steps = int(round(excess / HAIRCUT_STEP_BRIER))
    idx = _DEMOTE_LADDER.index(conviction) + steps
    idx = min(idx, len(_DEMOTE_LADDER) - 1)
    return _DEMOTE_LADDER[idx]
