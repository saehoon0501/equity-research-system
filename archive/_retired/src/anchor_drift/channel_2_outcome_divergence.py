"""Channel 2 — Outcome divergence (quantitative, no LLM).

Per spec ``docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md``
Section 4.5 Q5 line 533::

    2. Outcome divergence (quantitative): scenario_A_base_projections
       immutable; quarterly earnings -> if any of {revenue, gross margin, FCF}
       deviates > 25% -> trigger

The original ``scenario_A_base_projections`` is HMAC-signed at P5 lock
(``007_v3_watchlist_positions.sql``). Actuals come via ``mcp__fundamentals``;
the comparison is purely numeric — no LLM judgment.
"""

from __future__ import annotations

import datetime as _dt
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from . import OUTCOME_DEVIATION_THRESHOLD
from .hmac_verify import verify_scenario_hmac

_LOG = logging.getLogger(__name__)

_METRICS = ("revenue", "gross_margin", "fcf")


@dataclass
class OutcomeDivergenceResult:
    """One name's Channel 2 result.

    ``payload`` matches the JSONB shape documented in
    ``010_v3_drift_detection.sql`` for ``channel_2_outcome_divergence``.
    """

    triggered: bool
    last_earnings: Optional[str] = None
    revenue_actual: Optional[float] = None
    revenue_projected: Optional[float] = None
    margin_actual: Optional[float] = None
    margin_projected: Optional[float] = None
    fcf_actual: Optional[float] = None
    fcf_projected: Optional[float] = None
    deviations: dict[str, float] = field(default_factory=dict)
    breached_metrics: list[str] = field(default_factory=list)
    hmac_verified: bool = True
    error: Optional[str] = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "last_earnings": self.last_earnings,
            "revenue_actual": self.revenue_actual,
            "revenue_projected": self.revenue_projected,
            "margin_actual": self.margin_actual,
            "margin_projected": self.margin_projected,
            "fcf_actual": self.fcf_actual,
            "fcf_projected": self.fcf_projected,
            "deviations": dict(self.deviations),
            "breached_metrics": list(self.breached_metrics),
            "hmac_verified": bool(self.hmac_verified),
            "triggered": bool(self.triggered),
            "error": self.error,
        }


def _abs_pct_dev(actual: Optional[float], projected: Optional[float]) -> Optional[float]:
    """|actual - projected| / |projected|; returns None if not computable."""
    if actual is None or projected is None:
        return None
    try:
        denom = abs(float(projected))
        if denom == 0.0:
            return None
        return abs(float(actual) - float(projected)) / denom
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# Default fundamentals adapter — wraps mcp__fundamentals when available.      #
# Tests inject a stub via the ``fundamentals_fn`` parameter.                  #
# --------------------------------------------------------------------------- #


def _default_fundamentals_fn(ticker: str) -> dict[str, Any]:
    """Pull latest TTM actuals for the ticker from the ``latest_actuals``
    Postgres cache (migration 026).

    The cache is populated by ``/refresh-actuals`` which calls
    ``mcp__fundamentals`` at the Claude tool layer (Sharadar PIT) or
    falls back to ``mcp__edgar`` XBRL company facts. Returns the dict
    shape expected by Channel 2: ``{revenue, gross_margin, fcf,
    last_earnings_date}``. Empty dict ⇒ Channel 2 records no_actuals.
    """
    try:
        import os
        import psycopg
    except ImportError:
        _LOG.debug("psycopg not installed; latest_actuals cache unreachable")
        return {}
    dsn = os.environ.get(
        "EQUITY_RESEARCH_DSN",
        "postgresql://postgres@127.0.0.1:5432/equity_research",
    )
    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT period_end, revenue, gross_margin, fcf "
                    "FROM latest_actuals WHERE ticker = %s",
                    (ticker.upper(),),
                )
                row = cur.fetchone()
    except Exception as exc:  # noqa: BLE001 - defensive; never raise from default adapter
        _LOG.exception("latest_actuals fetch failed for %s: %s", ticker, exc)
        return {}
    if row is None:
        return {}
    period_end, revenue, gross_margin, fcf = row
    return {
        "last_earnings_date": (
            period_end.isoformat() if hasattr(period_end, "isoformat") else period_end
        ),
        "revenue": _coerce_float(revenue),
        "gross_margin": _coerce_float(gross_margin),
        "fcf": _coerce_float(fcf),
    }


def _coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def detect_outcome_divergence(
    *,
    ticker: str,
    scenario_A_base_projections: Any,
    scenario_A_base_projections_hmac: str,
    fundamentals_fn: Any | None = None,
) -> OutcomeDivergenceResult:
    """Run Channel 2 outcome-divergence detection.

    Args:
        ticker: equity ticker.
        scenario_A_base_projections: P5 lock projections (JSONB dict
            with keys ``revenue``, ``gross_margin``, ``fcf``).
        scenario_A_base_projections_hmac: accompanying HMAC.
        fundamentals_fn: optional injected callable
            ``(ticker) -> dict`` (returns ``{revenue, gross_margin,
            fcf, last_earnings_date}``); defaults to
            mcp__fundamentals adapter.

    Returns:
        OutcomeDivergenceResult; triggered if any of {revenue,
        gross_margin, fcf} deviates > 25%.
    """
    ticker = ticker.upper().strip()
    fundamentals_fn = fundamentals_fn or _default_fundamentals_fn

    if not verify_scenario_hmac(
        scenario_A_base_projections, scenario_A_base_projections_hmac
    ):
        _LOG.error(
            "HMAC mismatch on scenario_A_base_projections for %s", ticker
        )
        return OutcomeDivergenceResult(
            triggered=True,
            hmac_verified=False,
            error="hmac_mismatch_or_tamper",
        )

    if not isinstance(scenario_A_base_projections, dict):
        return OutcomeDivergenceResult(
            triggered=False,
            error="no_projections",
        )

    actuals = fundamentals_fn(ticker) or {}
    if not actuals:
        return OutcomeDivergenceResult(
            triggered=False,
            error="no_actuals",
        )

    rev_proj = _coerce_float(scenario_A_base_projections.get("revenue"))
    mar_proj = _coerce_float(scenario_A_base_projections.get("gross_margin"))
    fcf_proj = _coerce_float(scenario_A_base_projections.get("fcf"))
    rev_act = _coerce_float(actuals.get("revenue"))
    mar_act = _coerce_float(actuals.get("gross_margin"))
    fcf_act = _coerce_float(actuals.get("fcf"))
    last_earnings = actuals.get("last_earnings_date")
    if isinstance(last_earnings, _dt.date):
        last_earnings = last_earnings.isoformat()

    deviations: dict[str, float] = {}
    rev_dev = _abs_pct_dev(rev_act, rev_proj)
    mar_dev = _abs_pct_dev(mar_act, mar_proj)
    fcf_dev = _abs_pct_dev(fcf_act, fcf_proj)
    if rev_dev is not None:
        deviations["revenue"] = rev_dev
    if mar_dev is not None:
        deviations["gross_margin"] = mar_dev
    if fcf_dev is not None:
        deviations["fcf"] = fcf_dev

    breached = [
        m for m in _METRICS
        if (deviations.get(m) is not None
            and deviations[m] > OUTCOME_DEVIATION_THRESHOLD)
    ]
    triggered = bool(breached)

    return OutcomeDivergenceResult(
        triggered=triggered,
        last_earnings=last_earnings if isinstance(last_earnings, str) else None,
        revenue_actual=rev_act,
        revenue_projected=rev_proj,
        margin_actual=mar_act,
        margin_projected=mar_proj,
        fcf_actual=fcf_act,
        fcf_projected=fcf_proj,
        deviations=deviations,
        breached_metrics=breached,
        hmac_verified=True,
    )


__all__ = ["OutcomeDivergenceResult", "detect_outcome_divergence"]
