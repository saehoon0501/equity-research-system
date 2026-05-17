"""Cadence-driven sub-command routing for v0.1-active phase.

Per v3 spec Section 5.4 + Section 4 (P5/P6/P7 emit cycle) + Section 6.3
(parameter-review cadence) + Section 6.2 (drift monitoring cadence), once
v0.1 is launched the orchestrator surfaces the daily/event/weekly/quarterly
cadences that should run on this date.

Cadence layers:

  Daily (post-market close + 30 min):
    - /daily-monitor sweep (Tier 1 + Tier 2 escalation)
    - L4 materiality classifier (M-1/M-2/M-3)
    - Push-alert dispatch (channels: email, session-push)

  Mode-tuned per ticker (P5+P6+P7 emit cycle):
    - Mode B   → weekly Mon open
    - Mode B'  → every 3 days
    - Mode C   → daily

  Quarterly (each Q-end):
    - /parameters-review (Section 6.3)
    - Pre-mortem cadence floor (Section 6.2 mode classifier)
    - Catalog hygiene 10% audit (Section 6.2 peak-pain catalog)

  Annual (Jan 1):
    - Full peak-pain catalog audit
    - Materiality drift gold-standard refresh

Render-only: returns a list of ScheduledAction objects (timestamp +
invocation command). The orchestrator does NOT execute any of these.
"""

from __future__ import annotations

import datetime as _dt
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScheduledAction:
    """One sub-command invocation the operator should consider running today."""

    cadence: str  # 'daily' | 'mode_tuned' | 'quarterly' | 'annual'
    when: str  # human-readable time/window
    invocation: str  # the slash command to invoke
    rationale: str
    ticker: Optional[str] = None


@dataclass(frozen=True)
class _ModeTuning:
    mode: str
    period_days: int
    weekday_anchor: Optional[int]  # ISO weekday (0=Mon) or None for any-day
    description: str


# Section 4.6 P5/P6/P7 emit cycle — mode-tuned cadence per ticker.
_MODE_TUNINGS: dict[str, _ModeTuning] = {
    "B": _ModeTuning(
        mode="B",
        period_days=7,
        weekday_anchor=0,  # Monday
        description="weekly emit cycle (Mode B steady compounders)",
    ),
    "B_prime": _ModeTuning(
        mode="B_prime",
        period_days=3,
        weekday_anchor=None,
        description="every-3-days emit cycle (Mode B' growth compounders)",
    ),
    "C": _ModeTuning(
        mode="C",
        period_days=1,
        weekday_anchor=None,
        description="daily emit cycle (Mode C catalyst-driven)",
    ),
}


# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #


def collect_scheduled_actions(
    conn: Any,
    *,
    now: Optional[_dt.datetime] = None,
) -> list[ScheduledAction]:
    """Compute the cadence-driven actions due today.

    Args:
        conn: PEP-249 Postgres connection.
        now: Clock override for tests.

    Returns:
        Ordered list of ScheduledAction (daily → mode-tuned → quarterly → annual).
    """
    now = now or _dt.datetime.now(_dt.timezone.utc)
    today = now.date()

    actions: list[ScheduledAction] = []
    actions.extend(_daily_actions(today))
    actions.extend(_mode_tuned_actions(conn, today))
    actions.extend(_quarterly_actions(today))
    actions.extend(_annual_actions(today))
    return actions


def render_scheduled_actions(actions: list[ScheduledAction]) -> str:
    """Render a markdown list grouped by cadence."""
    lines: list[str] = []
    lines.append("## Scheduled Actions Today")
    lines.append("")

    if not actions:
        lines.append("_No cadence actions due today._")
        lines.append("")
        return "\n".join(lines)

    by_cadence: dict[str, list[ScheduledAction]] = {}
    for a in actions:
        by_cadence.setdefault(a.cadence, []).append(a)

    order = ["daily", "mode_tuned", "quarterly", "annual"]
    for cad in order:
        items = by_cadence.get(cad, [])
        if not items:
            continue
        lines.append(f"### {_cadence_label(cad)} ({len(items)})")
        lines.append("")
        for a in items:
            tick = f" `{a.ticker}`" if a.ticker else ""
            lines.append(
                f"- **{a.when}** —{tick} `{a.invocation}` "
                f"— {a.rationale}"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------------- #
# Cadence builders                                                            #
# --------------------------------------------------------------------------- #


def _daily_actions(today: _dt.date) -> list[ScheduledAction]:
    """Section 5.4 daily layer — always runs in v0.1-active."""
    return [
        ScheduledAction(
            cadence="daily",
            when="post-market close + 30 min",
            invocation="/daily-monitor",
            rationale=(
                "Tier 1 Sonnet + Tier 2 Sonnet/Opus sweep across all watchlist "
                "names; L4 materiality classification on news/filings. Per v3 "
                "spec §4.5 Q1 model constraint (Sonnet/Opus only — NO Haiku)."
            ),
        ),
        ScheduledAction(
            cadence="daily",
            when="post-market close + 35 min",
            invocation="/alerts",
            rationale=(
                "Push unresolved M-2/M-3 alerts surfaced by daily-monitor; "
                "operator triages via /ack."
            ),
        ),
        ScheduledAction(
            cadence="daily",
            when="any-time",
            invocation="/system-health",
            rationale=(
                "Confirm degraded MCPs / queued recoveries / disputed catalog "
                "entries are clean before the day's emit cycles."
            ),
        ),
    ]


def _mode_tuned_actions(
    conn: Any, today: _dt.date
) -> list[ScheduledAction]:
    """Section 4.6 P5/P6/P7 emit cycle — mode-tuned per ticker."""
    rows = _query_watchlist_modes(conn)
    out: list[ScheduledAction] = []
    for ticker, mode, last_emit in rows:
        tuning = _MODE_TUNINGS.get(mode)
        if tuning is None:
            continue
        if not _is_emit_due(today, last_emit, tuning):
            continue
        out.append(
            ScheduledAction(
                cadence="mode_tuned",
                when="market open",
                invocation=f"/research-company {ticker}",
                rationale=tuning.description,
                ticker=ticker,
            )
        )
    return out


def _quarterly_actions(today: _dt.date) -> list[ScheduledAction]:
    """Section 6.3 + 6.2 — quarterly cadences on quarter-end dates."""
    if not _is_quarter_end(today):
        return []
    return [
        ScheduledAction(
            cadence="quarterly",
            when="quarter-end",
            invocation="/parameters-review",
            rationale=(
                "Pull last 90d counterfactual ledger; system proposes "
                "parameter updates; operator approves/modifies/rejects "
                "(Section 6.3)."
            ),
        ),
        ScheduledAction(
            cadence="quarterly",
            when="quarter-end",
            invocation="/premortem --cadence-floor",
            rationale=(
                "Mode classifier pre-mortem cadence floor — surface any "
                "ticker with a pending mode reclassification proposal "
                "(Section 6.2)."
            ),
        ),
        ScheduledAction(
            cadence="quarterly",
            when="quarter-end",
            invocation="/system-health --catalog-hygiene-audit 10pct",
            rationale=(
                "Peak-pain catalog 10% stratified sample audit "
                "(Section 6.2 hygiene)."
            ),
        ),
    ]


def _annual_actions(today: _dt.date) -> list[ScheduledAction]:
    """Section 6.2 — annual full audits (fire on Jan 1)."""
    if today.month != 1 or today.day != 1:
        return []
    return [
        ScheduledAction(
            cadence="annual",
            when="Jan 1",
            invocation="/system-health --catalog-hygiene-audit full",
            rationale=(
                "Annual full peak-pain catalog audit (Section 6.2 — "
                "stratified across all entries)."
            ),
        ),
        ScheduledAction(
            cadence="annual",
            when="Jan 1",
            invocation="/parameters-review --materiality-gold-refresh",
            rationale=(
                "Materiality drift gold-standard refresh — re-rate the "
                "rolling 30-event gold standard (Section 6.2 + Phase 4 Q8)."
            ),
        ),
    ]


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _is_emit_due(
    today: _dt.date, last_emit: Optional[_dt.date], tuning: _ModeTuning
) -> bool:
    """Mode-tuned emit-due predicate.

    For weekday-anchored modes (Mode B → Mon), only the anchor weekday ever
    emits — including the cold-start case (last_emit=None). Period-based
    modes (B', C) emit when elapsed days >= period_days, or unconditionally
    on cold start.
    """
    if tuning.weekday_anchor is not None:
        return today.weekday() == tuning.weekday_anchor
    if last_emit is None:
        return True
    elapsed = (today - last_emit).days
    if elapsed < 0:
        return False
    return elapsed >= tuning.period_days


def _is_quarter_end(d: _dt.date) -> bool:
    """True iff d is the last day of Mar / Jun / Sep / Dec."""
    if d.month not in (3, 6, 9, 12):
        return False
    next_day = d + _dt.timedelta(days=1)
    return next_day.month != d.month


def _query_watchlist_modes(
    conn: Any,
) -> list[tuple[str, str, Optional[_dt.date]]]:
    """Returns [(ticker, mode, last_emit_date)]. Defensive on missing tables."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    w.ticker,
                    w.mode,
                    (
                        SELECT MAX(er.recommendation_date)
                        FROM execution_recommendations er
                        WHERE er.ticker = w.ticker
                    ) AS last_emit
                FROM watchlist w
                WHERE w.status = 'active'
                ORDER BY w.ticker
                """
            )
            rows = cur.fetchall()
    except Exception as exc:  # noqa: BLE001 — defensive, but logged
        _LOG.warning(
            "v01_active_routing watchlist query failed: %s: %s",
            type(exc).__name__, exc,
        )
        return []
    out: list[tuple[str, str, Optional[_dt.date]]] = []
    for ticker, mode, last_emit in rows:
        out.append((ticker, mode, last_emit))
    return out


def _cadence_label(cadence: str) -> str:
    return {
        "daily": "Daily (post-market close + 30 min)",
        "mode_tuned": "Mode-tuned per ticker (P5+P6+P7 emit cycle)",
        "quarterly": "Quarterly (each Q-end)",
        "annual": "Annual (Jan 1)",
    }.get(cadence, cadence.title())
