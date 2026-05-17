"""Operator-facing briefing assembled on every ``/run`` invocation.

Per v3 spec Section 5.4, ``/run`` is the single entry point. The briefing
aggregates:

  - Current phase + reason (phase_detector)
  - For v0.1-launch-readiness: launch-gate status grid (v01_launch_status)
  - For v0.1-active+: today's recommended actions per cadence
    (v01_active_routing)
  - Pending operator decisions (anchor-drift forced_review pending,
    counterfactual-veto override required, mode reclassification proposed)
  - Unread alert summary (links to /alerts for detail)
  - System health summary (links to /system-health for detail)

Render-only. The briefing surfaces work; the operator initiates each
sub-command manually.

Reference:
  Section 5.4 (slash command catalog + master orchestrator)
  Section 5.3 (push alerts)
  Section 6.2 (drift monitoring)
  Phase 4 Q9 (system_health unified visibility)
"""

from __future__ import annotations

import datetime as _dt
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

_LOG = logging.getLogger(__name__)

from src.orchestrator.phase_detector import Phase, PhaseSnapshot, detect_phase
from src.orchestrator.v01_active_routing import (
    ScheduledAction,
    collect_scheduled_actions,
    render_scheduled_actions,
)
from src.orchestrator.v01_launch_status import (
    LaunchGateGrid,
    collect_launch_gates,
    render_launch_gate_grid,
)


@dataclass(frozen=True)
class PendingOperatorDecision:
    """One pending decision blocking a downstream pipeline."""

    decision_type: str  # 'anchor_drift_forced_review' | 'counterfactual_veto_override' | 'mode_reclassification'
    ticker: str
    surfaced_at: Optional[_dt.datetime]
    detail: str
    drill_command: str  # the slash command the operator runs to act


@dataclass(frozen=True)
class AlertSummary:
    """Compact unread-alert summary; full detail via /alerts."""

    unread_m2: int
    unread_m3: int

    @property
    def total(self) -> int:
        return self.unread_m2 + self.unread_m3


@dataclass(frozen=True)
class SystemHealthSummaryRow:
    """Compact system-health summary; full detail via /system-health."""

    degraded_mcps: int
    queued_email_alerts: int
    disputed_catalog_count: int
    system_errors_last_7d: int


@dataclass(frozen=True)
class OperatorBriefing:
    """Top-level briefing for ``/run``."""

    generated_at: _dt.datetime
    phase: PhaseSnapshot
    launch_gates: Optional[LaunchGateGrid]  # populated only in launch-readiness
    scheduled_actions: list[ScheduledAction]  # populated for v0.1-active+
    pending_decisions: list[PendingOperatorDecision]
    alerts: AlertSummary
    system_health: SystemHealthSummaryRow


# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #


def collect_operator_briefing(
    conn: Any,
    *,
    now: Optional[_dt.datetime] = None,
) -> OperatorBriefing:
    """Assemble the full briefing in one Postgres pass.

    Args:
        conn: PEP-249 Postgres connection.
        now: Clock override for tests.

    Returns:
        OperatorBriefing ready for rendering.
    """
    now = now or _dt.datetime.now(_dt.timezone.utc)
    phase = detect_phase(conn, now=now)

    if phase.phase == Phase.V01_LAUNCH_READINESS:
        gates: Optional[LaunchGateGrid] = collect_launch_gates(conn)
        actions: list[ScheduledAction] = []
    else:
        gates = None
        actions = collect_scheduled_actions(conn, now=now)

    pending = _collect_pending_decisions(conn)
    alerts = _collect_alert_summary(conn)
    health = _collect_system_health_summary(conn, now=now)

    return OperatorBriefing(
        generated_at=now,
        phase=phase,
        launch_gates=gates,
        scheduled_actions=actions,
        pending_decisions=pending,
        alerts=alerts,
        system_health=health,
    )


def render_operator_briefing(briefing: OperatorBriefing) -> str:
    """Render the briefing as terminal markdown."""
    lines: list[str] = []
    ts = briefing.generated_at.strftime("%Y-%m-%d %H:%M:%S UTC")
    lines.append("# /run — Operator Briefing")
    lines.append("")
    lines.append(f"_Generated at {ts}_")
    lines.append("")

    # Phase block.
    p = briefing.phase
    lines.append("## Phase")
    lines.append("")
    lines.append(f"- **Current phase:** `{p.phase.value}`")
    lines.append(f"- **Reason:** {p.reason}")
    if p.launch_date is not None:
        lines.append(f"- **Launch date:** {p.launch_date.isoformat()}")
    lines.append(f"- **Resolved predictions:** {p.resolved_predictions}")
    lines.append(f"- **Real-money execution active:** {p.real_money_active}")
    if p.days_since_launch is not None:
        lines.append(f"- **Days since launch:** {p.days_since_launch}")
    lines.append("")

    # Phase-specific block.
    if briefing.launch_gates is not None:
        lines.append(render_launch_gate_grid(briefing.launch_gates))
    if briefing.scheduled_actions:
        lines.append(render_scheduled_actions(briefing.scheduled_actions))
    elif briefing.launch_gates is None:
        # v0.1-active+ but no actions due today (rare)
        lines.append("## Scheduled Actions Today")
        lines.append("")
        lines.append("_No cadence actions due today._")
        lines.append("")

    # Pending decisions.
    lines.append("## Pending Operator Decisions")
    lines.append("")
    if not briefing.pending_decisions:
        lines.append("_None pending._")
    else:
        for d in briefing.pending_decisions:
            t = d.surfaced_at.strftime("%Y-%m-%d") if d.surfaced_at else "unknown"
            lines.append(
                f"- **{d.ticker}** ({d.decision_type}) — surfaced {t}: "
                f"{d.detail} → run `{d.drill_command}`"
            )
    lines.append("")

    # Alerts.
    a = briefing.alerts
    lines.append("## Alerts")
    lines.append("")
    if a.total == 0:
        lines.append("_No unread alerts._")
    else:
        lines.append(
            f"- **{a.total}** unread alerts "
            f"({a.unread_m3} M-3, {a.unread_m2} M-2). "
            f"See `/alerts` for detail; `/ack <alert_id>` to acknowledge."
        )
    lines.append("")

    # System health.
    h = briefing.system_health
    lines.append("## System Health")
    lines.append("")
    if (
        h.degraded_mcps == 0
        and h.queued_email_alerts == 0
        and h.disputed_catalog_count == 0
        and h.system_errors_last_7d == 0
    ):
        lines.append("All systems green. See `/system-health` for full detail.")
    else:
        lines.append(
            f"- Degraded MCPs: **{h.degraded_mcps}**"
        )
        lines.append(
            f"- Queued email alerts: **{h.queued_email_alerts}**"
        )
        lines.append(
            f"- Disputed catalog entries: **{h.disputed_catalog_count}**"
        )
        lines.append(
            f"- System errors (last 7d): **{h.system_errors_last_7d}**"
        )
        lines.append("")
        lines.append("See `/system-health` for full detail.")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------------- #
# Postgres queries — defensive on missing tables                              #
# --------------------------------------------------------------------------- #


def _collect_pending_decisions(conn: Any) -> list[PendingOperatorDecision]:
    """Surface anchor-drift / counterfactual-veto / mode-reclass pending."""
    out: list[PendingOperatorDecision] = []
    out.extend(_query_anchor_drift_pending(conn))
    out.extend(_query_counterfactual_veto_pending(conn))
    out.extend(_query_mode_reclassification_pending(conn))
    return out


def _query_anchor_drift_pending(
    conn: Any,
) -> list[PendingOperatorDecision]:
    """Anchor-drift forced_review with no anchor_drift_review_decisions row.

    Per v3 Section 6.2 — when a forced review is open, the operator must
    decide reaffirm / revise_with_rationale / cut.
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT adc.check_id, adc.ticker, adc.check_date
                FROM anchor_drift_checks adc
                WHERE adc.forced_review = TRUE
                  AND NOT EXISTS (
                      SELECT 1 FROM anchor_drift_review_decisions adrd
                      WHERE adrd.check_id = adc.check_id
                  )
                ORDER BY adc.check_date DESC
                LIMIT 20
                """
            )
            rows = cur.fetchall()
    except Exception as exc:  # noqa: BLE001 — defensive, but logged
        _LOG.warning(
            "operator_briefing._query_anchor_drift_pending failed: %s: %s",
            type(exc).__name__, exc,
        )
        return []
    out: list[PendingOperatorDecision] = []
    for check_id, ticker, check_date in rows:
        out.append(
            PendingOperatorDecision(
                decision_type="anchor_drift_forced_review",
                ticker=ticker,
                surfaced_at=_to_datetime(check_date),
                detail="anchor-drift forced review pending operator decision",
                drill_command=f"/audit-trail {ticker} --latest",
            )
        )
    return out


def _query_counterfactual_veto_pending(
    conn: Any,
) -> list[PendingOperatorDecision]:
    """Counterfactual-veto override required.

    Per v3 Section 4.6 + 5.2 — when veto fires, operator may override the
    PASS-default by explicit decision.
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT er.recommendation_id, er.ticker, er.recommendation_date
                FROM execution_recommendations er
                WHERE er.counterfactual_veto_status = 'override_required'
                  AND er.operator_override_decision IS NULL
                ORDER BY er.recommendation_date DESC
                LIMIT 20
                """
            )
            rows = cur.fetchall()
    except Exception as exc:  # noqa: BLE001 — defensive, but logged
        _LOG.warning(
            "operator_briefing._query_counterfactual_veto_pending failed: "
            "%s: %s",
            type(exc).__name__, exc,
        )
        return []
    out: list[PendingOperatorDecision] = []
    for rec_id, ticker, rec_date in rows:
        out.append(
            PendingOperatorDecision(
                decision_type="counterfactual_veto_override",
                ticker=ticker,
                surfaced_at=_to_datetime(rec_date),
                detail="counterfactual-veto override decision required",
                drill_command=(
                    f"/audit-trail {rec_id} --stage stage_4_counterfactual"
                ),
            )
        )
    return out


def _query_mode_reclassification_pending(
    conn: Any,
) -> list[PendingOperatorDecision]:
    """Mode reclassification proposed by quarterly classifier.

    Per v3 Phase 4 Q5 — quarterly rule classifier disagrees with stored mode;
    surfaced as `pending_reclassification` in the disposition view.
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT mc.ticker, mc.classification_date, mc.final_mode
                FROM mode_classifications mc
                WHERE mc.flag_status = 'pending_reclassification'
                ORDER BY mc.classification_date DESC
                LIMIT 20
                """
            )
            rows = cur.fetchall()
    except Exception as exc:  # noqa: BLE001 — defensive, but logged
        _LOG.warning(
            "operator_briefing._query_mode_reclassification_pending failed: "
            "%s: %s",
            type(exc).__name__, exc,
        )
        return []
    out: list[PendingOperatorDecision] = []
    for ticker, when, proposed_mode in rows:
        out.append(
            PendingOperatorDecision(
                decision_type="mode_reclassification",
                ticker=ticker,
                surfaced_at=_to_datetime(when),
                detail=f"reclassification to mode '{proposed_mode}' proposed",
                drill_command=f"/disposition --ticker {ticker}",
            )
        )
    return out


def _collect_alert_summary(conn: Any) -> AlertSummary:
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT severity, COUNT(*)
                FROM unread_alerts
                WHERE acknowledged_at IS NULL
                GROUP BY severity
                """
            )
            rows = cur.fetchall()
    except Exception as exc:  # noqa: BLE001 — defensive, but logged
        _LOG.warning(
            "operator_briefing._collect_alert_summary failed: %s: %s",
            type(exc).__name__, exc,
        )
        return AlertSummary(unread_m2=0, unread_m3=0)
    m2 = 0
    m3 = 0
    for sev, count in rows:
        if int(sev) == 2:
            m2 = int(count)
        elif int(sev) == 3:
            m3 = int(count)
    return AlertSummary(unread_m2=m2, unread_m3=m3)


def _collect_system_health_summary(
    conn: Any,
    *,
    now: _dt.datetime,
) -> SystemHealthSummaryRow:
    return SystemHealthSummaryRow(
        degraded_mcps=_count_query(
            conn,
            """
            SELECT COUNT(DISTINCT source)
            FROM system_errors
            WHERE resolved_at IS NULL
            """,
        ),
        queued_email_alerts=_count_query(
            conn,
            """
            SELECT COUNT(*)
            FROM unread_alerts
            WHERE acknowledged_at IS NULL
              AND email_sent_at IS NULL
            """,
        ),
        disputed_catalog_count=_count_query(
            conn,
            """
            SELECT COUNT(*)
            FROM peak_pain_catalog
            WHERE consensus_status = 'disputed'
            """,
        ),
        system_errors_last_7d=_count_query(
            conn,
            """
            SELECT COUNT(*)
            FROM system_errors
            WHERE created_at >= %s
            """,
            (now - _dt.timedelta(days=7),),
        ),
    )


# --------------------------------------------------------------------------- #
# Tiny helpers                                                                #
# --------------------------------------------------------------------------- #


def _count_query(conn: Any, sql: str, params: tuple = ()) -> int:
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
    except Exception as exc:  # noqa: BLE001 — defensive, but logged
        _LOG.warning(
            "operator_briefing._count_query failed (sql=%r): %s: %s",
            sql.strip().splitlines()[0] if sql.strip() else sql,
            type(exc).__name__,
            exc,
        )
        return 0
    return int(row[0]) if row else 0


def _to_datetime(d: Any) -> Optional[_dt.datetime]:
    if d is None:
        return None
    if isinstance(d, _dt.datetime):
        return d
    if isinstance(d, _dt.date):
        return _dt.datetime(d.year, d.month, d.day, tzinfo=_dt.timezone.utc)
    return None
