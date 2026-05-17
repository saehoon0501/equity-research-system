"""Believability-weighted Issue Log (v3 spec §6.4).

For each debate row in `debate_consensus_history`, every style emits a
verdict (ADD / WATCH / PASS). The recommendation that lands in
`execution_recommendations` is the Phase-D synthesis. A style's
"believability" is its historical Brier score against actual outcomes —
calibration of *that style's verdict* (not the system's final conviction).

Mapping verdict → predicted-favorable-probability (one prior per verdict;
recalibrated empirically once N≥50 outcomes per style accumulate):

    ADD   → 0.65  (style was bullish; favorable = positive alpha)
    WATCH → 0.50  (neutral signal)
    PASS  → 0.35  (style was bearish; favorable = positive alpha would
                   contradict the style; we still score the system's
                   ultimate alpha, so PASS predicting against alpha is
                   coherent)

At v0.5-active, the synthesis weights each style's claim by inverse-Brier:

    w_style = 1 / max(brier_style, eps)
    w_normalized = w_style / sum(w_style)

Higher believability → larger weight on that style's non-negotiables in
Phase-D synthesis. At v0.1 these weights are computed in shadow mode
(stored, not applied); phase_detector flips them live at v0.5-active.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from src.calibration.brier import _favorable
from src.p4_debate import ALL_STYLES

# Verdict → bullish probability prior. Same convention as the conviction
# prior in src/calibration/brier.py — recalibrated at v0.5+.
VERDICT_PRIOR: dict[str, float] = {
    "ADD": 0.65,
    "WATCH": 0.50,
    "PASS": 0.35,
}

# Tiny epsilon to avoid /0 when a style is perfectly calibrated.
_INV_EPS = 0.001

# Cap on rows pulled per call. v0.5 N is in the low hundreds.
_MAX_ROWS_PER_CALL = 50_000


@dataclass(frozen=True)
class StyleBrier:
    """Per-style Brier + sample count + the inverse-Brier weight."""

    style: str
    n: int
    brier: float
    weight_inverse_brier: float


def score_per_style_brier(
    conn: Any,
    *,
    horizon: str = "90d",
    as_of: Optional[_dt.date] = None,
    rec_type_filter: Optional[str] = None,
) -> list[StyleBrier]:
    """Compute Brier per debate style against resolved outcomes.

    Joins debate_consensus_history → execution_recommendations →
    recommendation_outcomes. Reads each style's verdict from the
    `per_style_outputs` JSONB field.

    Args:
        horizon: 30d|90d|1y; selects the matching delta column.
        as_of: only resolved outcomes whose close_date ≤ as_of.
        rec_type_filter: optionally restrict to BUY-only Brier (etc.) so
            different recommendation types don't pollute each other.

    Returns:
        List of StyleBrier — one per known style with at least one resolved
        outcome. Weights are normalized to sum to 1.0 across the returned
        list. Empty if no outcomes are resolved yet.
    """
    if horizon not in {"30d", "90d", "1y"}:
        raise ValueError(f"horizon must be 30d|90d|1y, got {horizon!r}")

    delta_col = f"delta_vs_benchmark_{horizon}"
    close_col = f"t_plus_{horizon}_close_date"

    where_clauses: list[str] = [f"ro.{delta_col} IS NOT NULL"]
    params: list[Any] = []
    if as_of is not None:
        where_clauses.append(f"ro.{close_col} <= %s")
        params.append(as_of)
    if rec_type_filter is not None:
        where_clauses.append("er.recommendation = %s")
        params.append(rec_type_filter)
    where_sql = " AND ".join(where_clauses)

    sql = f"""
        SELECT
            dch.per_style_outputs,
            er.recommendation,
            ro.{delta_col} AS delta
        FROM debate_consensus_history dch
        JOIN execution_recommendations er
            ON er.recommendation_id = dch.recommendation_id
        JOIN recommendation_outcomes ro
            ON ro.recommendation_id = er.recommendation_id
        WHERE {where_sql}
        LIMIT {_MAX_ROWS_PER_CALL}
    """
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        rows = cur.fetchall()
    finally:
        cur.close()

    return _aggregate_styles(rows)


def _extract_verdict(per_style_outputs: Any, style: str) -> Optional[str]:
    """Pull the verdict for one style from a JSONB blob.

    Resilient to both dict and JSON-string inputs (psycopg2 returns dict;
    raw drivers may return str).
    """
    if isinstance(per_style_outputs, str):
        import json as _json
        try:
            per_style_outputs = _json.loads(per_style_outputs)
        except _json.JSONDecodeError:
            return None
    if not isinstance(per_style_outputs, dict):
        return None
    style_block = per_style_outputs.get(style)
    if not isinstance(style_block, dict):
        return None
    verdict = style_block.get("verdict")
    if not isinstance(verdict, str):
        return None
    return verdict.upper()


def _aggregate_styles(rows: Iterable[tuple]) -> list[StyleBrier]:
    """Bucket per-style (predicted_p, realized_y) and compute Brier."""
    buckets: dict[str, list[tuple[float, int]]] = {s: [] for s in ALL_STYLES}

    for r in rows:
        per_style, rec_type, delta = r
        delta_f = float(delta) if delta is not None else None
        y = _favorable(rec_type, delta_f)
        if y is None:
            continue
        for style in ALL_STYLES:
            verdict = _extract_verdict(per_style, style)
            if verdict is None:
                continue
            p = VERDICT_PRIOR.get(verdict)
            if p is None:
                continue
            buckets[style].append((p, y))

    # Compute Brier and inverse-Brier weights.
    raw: list[tuple[str, int, float, float]] = []
    for style, samples in buckets.items():
        if not samples:
            continue
        n = len(samples)
        brier = sum((p - y) ** 2 for p, y in samples) / n
        inv = 1.0 / max(brier, _INV_EPS)
        raw.append((style, n, brier, inv))

    if not raw:
        return []

    inv_total = sum(item[3] for item in raw)
    out: list[StyleBrier] = []
    for style, n, brier, inv in raw:
        out.append(
            StyleBrier(
                style=style,
                n=n,
                brier=brier,
                weight_inverse_brier=inv / inv_total,
            )
        )
    out.sort(key=lambda s: -s.n)
    return out


def synthesize_with_believability(
    style_verdicts: dict[str, str],
    style_briers: list[StyleBrier],
) -> dict[str, Any]:
    """Roll up per-style verdicts into a single recommendation, weighted by
    inverse-Brier believability.

    At v0.5-active this replaces equal-weight Phase-D synthesis. v0.1
    callers can use it in shadow mode (compute, log, but ignore the result).

    Returns:
        {
            'verdict': 'ADD'|'WATCH'|'PASS',
            'weighted_score': float in [0,1],
            'weights_used': {style: weight, ...},
            'fallback_equal_weight': bool,  # True if no Brier data
        }
    """
    weight_lookup = {sb.style: sb.weight_inverse_brier for sb in style_briers}

    verdict_to_score = {"ADD": 1.0, "WATCH": 0.5, "PASS": 0.0}

    # Equal-weight fallback if no Brier history yet.
    weights: dict[str, float]
    if weight_lookup:
        # Re-normalize over the styles we actually have verdicts for.
        contributing = {
            s: weight_lookup.get(s, 0.0) for s in style_verdicts.keys()
        }
        contributing_total = sum(contributing.values())
        if contributing_total > 0:
            weights = {s: w / contributing_total for s, w in contributing.items()}
            fallback = False
        else:
            weights = {s: 1.0 / len(style_verdicts) for s in style_verdicts}
            fallback = True
    else:
        weights = {s: 1.0 / len(style_verdicts) for s in style_verdicts}
        fallback = True

    score = 0.0
    for style, verdict in style_verdicts.items():
        v_score = verdict_to_score.get(verdict.upper())
        if v_score is None:
            continue
        score += weights.get(style, 0.0) * v_score

    if score >= 0.66:
        final = "ADD"
    elif score >= 0.33:
        final = "WATCH"
    else:
        final = "PASS"

    return {
        "verdict": final,
        "weighted_score": score,
        "weights_used": weights,
        "fallback_equal_weight": fallback,
    }
