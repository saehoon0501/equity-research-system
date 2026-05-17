"""Smoke tests for src/orchestrator/.

No live Postgres required — uses a hand-rolled FakeConnection that
implements just enough of the PEP-249 protocol to drive each query in
phase_detector / v01_launch_status / v01_active_routing /
operator_briefing.

Verifies:
  - Phase detection: launch-readiness → v0.1-active → v0.5-active → v1.0-active.
  - Launch-gate grid renders all four Section 7 categories with the
    expected gate names; PENDING default when no row recorded.
  - Cadence routing: daily layer always; mode-tuned per ticker
    (B weekly Mon / B' every 3d / C daily); quarterly on quarter-end;
    annual on Jan 1.
  - Operator briefing renders both the v0.1-launch-readiness path
    (gate grid) and the v0.1-active path (scheduled actions).
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any, Optional

import pytest

from src.orchestrator import (
    Phase,
    collect_launch_gates,
    collect_operator_briefing,
    collect_scheduled_actions,
    detect_phase,
    render_launch_gate_grid,
    render_operator_briefing,
    render_scheduled_actions,
)


# -----------------------------------------------------------------------------
# Fake Postgres connection
# -----------------------------------------------------------------------------


@dataclass
class FakeStore:
    """In-memory equivalent of all tables the orchestrator queries."""

    launch_signed_off: bool = False
    launch_all_green: bool = False
    launch_date: Optional[_dt.date] = None
    resolved_predictions: int = 0
    real_money_active: bool = False
    launch_gate_rows: dict[str, dict] = field(default_factory=dict)
    watchlist: list[dict] = field(default_factory=list)
    last_emit_per_ticker: dict[str, Optional[_dt.date]] = field(default_factory=dict)
    anchor_drift_pending: list[dict] = field(default_factory=list)
    counterfactual_veto_pending: list[dict] = field(default_factory=list)
    mode_reclass_pending: list[dict] = field(default_factory=list)
    unread_alerts_by_severity: dict[int, int] = field(default_factory=dict)
    degraded_mcp_count: int = 0
    queued_email_count: int = 0
    disputed_catalog_count: int = 0
    system_errors_7d: int = 0


class FakeCursor:
    def __init__(self, store: FakeStore) -> None:
        self._store = store
        self._result: list[tuple[Any, ...]] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *_exc: Any) -> None:
        pass

    def execute(self, sql: str, params: Optional[tuple[Any, ...]] = None) -> None:
        norm = " ".join(sql.split())
        store = self._store

        if "FROM launch_readiness_log" in norm and "signed_off = TRUE" in norm:
            if store.launch_signed_off:
                self._result = [
                    (store.launch_all_green, True, store.launch_date)
                ]
            else:
                self._result = []
            return

        if "FROM launch_readiness_log" in norm:
            self._result = [
                (
                    name,
                    rec.get("status"),
                    rec.get("evidence_link"),
                    rec.get("detail"),
                )
                for name, rec in store.launch_gate_rows.items()
            ]
            return

        if "FROM recommendation_outcomes" in norm:
            self._result = [(store.resolved_predictions,)]
            return

        if "FROM parameters_active" in norm:
            self._result = [(1,)] if store.real_money_active else []
            return

        if "FROM watchlist w" in norm:
            self._result = [
                (
                    w["ticker"],
                    w["mode"],
                    store.last_emit_per_ticker.get(w["ticker"]),
                )
                for w in store.watchlist
                if w.get("status", "active") == "active"
            ]
            return

        if "FROM anchor_drift_checks" in norm:
            self._result = [
                (r["check_id"], r["ticker"], r["check_date"])
                for r in store.anchor_drift_pending
            ]
            return

        if "FROM execution_recommendations" in norm and "counterfactual_veto" in norm:
            self._result = [
                (r["recommendation_id"], r["ticker"], r["recommendation_date"])
                for r in store.counterfactual_veto_pending
            ]
            return

        if "FROM mode_classifications" in norm and "pending_reclassification" in norm:
            self._result = [
                (r["ticker"], r["classification_date"], r["final_mode"])
                for r in store.mode_reclass_pending
            ]
            return

        if "FROM unread_alerts" in norm and "GROUP BY severity" in norm:
            self._result = [
                (sev, count) for sev, count in store.unread_alerts_by_severity.items()
            ]
            return

        if "FROM system_errors" in norm and "resolved_at IS NULL" in norm:
            self._result = [(store.degraded_mcp_count,)]
            return

        if "FROM unread_alerts" in norm and "email_sent_at IS NULL" in norm:
            self._result = [(store.queued_email_count,)]
            return

        if "FROM peak_pain_catalog" in norm and "disputed" in norm:
            self._result = [(store.disputed_catalog_count,)]
            return

        if "FROM system_errors" in norm and "created_at" in norm:
            self._result = [(store.system_errors_7d,)]
            return

        # Unknown query — return empty.
        self._result = []

    def fetchone(self) -> Optional[tuple[Any, ...]]:
        return self._result[0] if self._result else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._result)

    def close(self) -> None:
        pass


class FakeConnection:
    def __init__(self, store: FakeStore) -> None:
        self.store = store

    def cursor(self) -> FakeCursor:
        return FakeCursor(self.store)

    def close(self) -> None:
        pass


# -----------------------------------------------------------------------------
# Phase detection
# -----------------------------------------------------------------------------


def test_phase_v01_launch_readiness_when_no_signoff() -> None:
    conn = FakeConnection(FakeStore(launch_signed_off=False))
    snap = detect_phase(conn)
    assert snap.phase == Phase.V01_LAUNCH_READINESS
    assert "launch gates not all green" in snap.reason


def test_phase_v01_active_when_launched_low_resolved() -> None:
    store = FakeStore(
        launch_signed_off=True,
        launch_all_green=True,
        launch_date=_dt.date(2026, 4, 1),
        resolved_predictions=10,
    )
    conn = FakeConnection(store)
    now = _dt.datetime(2026, 4, 29, tzinfo=_dt.timezone.utc)
    snap = detect_phase(conn, now=now)
    assert snap.phase == Phase.V01_ACTIVE
    assert snap.resolved_predictions == 10
    assert snap.days_since_launch == 28


def test_phase_v05_active_when_50_resolved() -> None:
    store = FakeStore(
        launch_signed_off=True,
        launch_all_green=True,
        launch_date=_dt.date(2026, 4, 1),
        resolved_predictions=55,
    )
    conn = FakeConnection(store)
    snap = detect_phase(
        conn, now=_dt.datetime(2026, 8, 1, tzinfo=_dt.timezone.utc)
    )
    assert snap.phase == Phase.V05_ACTIVE
    assert "≥ 50" in snap.reason


def test_phase_v05_active_when_540_days_elapsed() -> None:
    store = FakeStore(
        launch_signed_off=True,
        launch_all_green=True,
        launch_date=_dt.date(2024, 1, 1),  # > 540 days before 2026-04-29
        resolved_predictions=5,
    )
    conn = FakeConnection(store)
    snap = detect_phase(
        conn, now=_dt.datetime(2026, 4, 29, tzinfo=_dt.timezone.utc)
    )
    assert snap.phase == Phase.V05_ACTIVE


def test_phase_v10_active_when_real_money_live() -> None:
    store = FakeStore(
        launch_signed_off=True,
        launch_all_green=True,
        launch_date=_dt.date(2026, 4, 1),
        real_money_active=True,
    )
    conn = FakeConnection(store)
    snap = detect_phase(conn)
    assert snap.phase == Phase.V10_ACTIVE


# -----------------------------------------------------------------------------
# Launch-gate grid
# -----------------------------------------------------------------------------


def test_launch_gate_grid_all_pending_when_empty_log() -> None:
    """Gate counts after Appendix H alignment + broker_mcp_oauth removal
    (operator decision 2026-05-01): 32 total = 11 H.1 + 9 H.2 + 8 H.3+H.4 + 4 H.5."""
    conn = FakeConnection(FakeStore())
    grid = collect_launch_gates(conn)
    assert len(grid.hard_gates) == 11
    assert len(grid.calibration_gates) == 9
    assert len(grid.operator_signoff_gates) == 8
    assert len(grid.walkthrough_gates) == 4
    assert grid.green == 0
    assert not grid.all_green


def test_launch_gate_grid_marks_pass_from_log() -> None:
    store = FakeStore(
        launch_gate_rows={
            "calibration_harness_pass": {
                "status": "PASS",
                "evidence_link": "checkpoints/checkpoint_1.md",
                "detail": "harness passes 14/15",
            },
            "walkthrough_cold_start_day_1": {"status": "FAIL", "detail": "regression"},
        }
    )
    conn = FakeConnection(store)
    grid = collect_launch_gates(conn)
    cal_gate = next(
        g for g in grid.hard_gates if g.gate_name == "calibration_harness_pass"
    )
    assert cal_gate.status.value == "PASS"
    assert cal_gate.evidence_link == "checkpoints/checkpoint_1.md"

    cs = next(
        g for g in grid.hard_gates if g.gate_name == "walkthrough_cold_start_day_1"
    )
    assert cs.status.value == "FAIL"


def test_launch_gate_grid_renders_section_headers() -> None:
    grid = collect_launch_gates(FakeConnection(FakeStore()))
    out = render_launch_gate_grid(grid)
    assert "Section 7.1 — Hard gates" in out
    assert "Section 7.2 — Calibration gates" in out
    assert "Section 7.3 — Operator sign-off" in out
    assert "Section 7.3a — Walkthrough" in out
    assert "0 of 32 gates green" in out


# -----------------------------------------------------------------------------
# Cadence routing
# -----------------------------------------------------------------------------


def test_daily_actions_always_present() -> None:
    conn = FakeConnection(FakeStore())
    actions = collect_scheduled_actions(
        conn, now=_dt.datetime(2026, 4, 29, tzinfo=_dt.timezone.utc)
    )
    daily = [a for a in actions if a.cadence == "daily"]
    invocations = {a.invocation for a in daily}
    assert "/daily-monitor" in invocations
    assert "/alerts" in invocations
    assert "/system-health" in invocations


def test_mode_c_emits_daily() -> None:
    """Mode C: period_days=1 → emits every day regardless of last_emit."""
    store = FakeStore(
        watchlist=[{"ticker": "GME", "mode": "C", "status": "active"}],
        last_emit_per_ticker={"GME": _dt.date(2026, 4, 28)},
    )
    conn = FakeConnection(store)
    actions = collect_scheduled_actions(
        conn, now=_dt.datetime(2026, 4, 29, tzinfo=_dt.timezone.utc)
    )
    mode_tuned = [a for a in actions if a.cadence == "mode_tuned"]
    assert any(a.ticker == "GME" for a in mode_tuned)


def test_mode_b_emits_only_on_monday() -> None:
    """Mode B: weekday_anchor=Monday."""
    store = FakeStore(
        watchlist=[{"ticker": "KO", "mode": "B", "status": "active"}],
        last_emit_per_ticker={"KO": None},
    )
    conn = FakeConnection(store)

    # 2026-04-27 is a Monday.
    monday = _dt.datetime(2026, 4, 27, tzinfo=_dt.timezone.utc)
    actions_mon = collect_scheduled_actions(conn, now=monday)
    assert any(
        a.cadence == "mode_tuned" and a.ticker == "KO" for a in actions_mon
    )

    # 2026-04-29 is a Wednesday.
    wed = _dt.datetime(2026, 4, 29, tzinfo=_dt.timezone.utc)
    actions_wed = collect_scheduled_actions(conn, now=wed)
    assert not any(
        a.cadence == "mode_tuned" and a.ticker == "KO" for a in actions_wed
    )


def test_mode_b_prime_emits_every_3_days() -> None:
    store = FakeStore(
        watchlist=[{"ticker": "NVDA", "mode": "B_prime", "status": "active"}],
        last_emit_per_ticker={"NVDA": _dt.date(2026, 4, 26)},
    )
    conn = FakeConnection(store)

    # Day 2 — not yet due.
    actions_day2 = collect_scheduled_actions(
        conn, now=_dt.datetime(2026, 4, 28, tzinfo=_dt.timezone.utc)
    )
    assert not any(a.ticker == "NVDA" for a in actions_day2)

    # Day 3 — due.
    actions_day3 = collect_scheduled_actions(
        conn, now=_dt.datetime(2026, 4, 29, tzinfo=_dt.timezone.utc)
    )
    assert any(a.ticker == "NVDA" for a in actions_day3)


def test_quarterly_actions_only_on_quarter_end() -> None:
    conn = FakeConnection(FakeStore())

    # 2026-06-30 is end of Q2.
    q_end = _dt.datetime(2026, 6, 30, tzinfo=_dt.timezone.utc)
    actions = collect_scheduled_actions(conn, now=q_end)
    quarterly = [a for a in actions if a.cadence == "quarterly"]
    assert len(quarterly) == 3
    invs = {a.invocation for a in quarterly}
    assert "/parameters-review" in invs

    # 2026-04-29 is mid-Q2.
    mid_q = _dt.datetime(2026, 4, 29, tzinfo=_dt.timezone.utc)
    actions_mid = collect_scheduled_actions(conn, now=mid_q)
    assert not any(a.cadence == "quarterly" for a in actions_mid)


def test_annual_actions_only_on_jan_1() -> None:
    conn = FakeConnection(FakeStore())
    jan1 = _dt.datetime(2027, 1, 1, tzinfo=_dt.timezone.utc)
    actions = collect_scheduled_actions(conn, now=jan1)
    annual = [a for a in actions if a.cadence == "annual"]
    assert len(annual) == 2


# -----------------------------------------------------------------------------
# Operator briefing
# -----------------------------------------------------------------------------


def test_briefing_v01_launch_readiness_includes_gate_grid() -> None:
    conn = FakeConnection(FakeStore())
    briefing = collect_operator_briefing(conn)
    assert briefing.phase.phase == Phase.V01_LAUNCH_READINESS
    assert briefing.launch_gates is not None
    assert briefing.scheduled_actions == []

    out = render_operator_briefing(briefing)
    assert "/run — Operator Briefing" in out
    assert "v0.1-launch-readiness" in out
    assert "Launch Gate Status" in out
    assert "Scheduled Actions Today" not in out  # not rendered in launch-readiness


def test_briefing_v01_active_includes_scheduled_actions() -> None:
    store = FakeStore(
        launch_signed_off=True,
        launch_all_green=True,
        launch_date=_dt.date(2026, 4, 1),
        resolved_predictions=10,
        watchlist=[{"ticker": "GME", "mode": "C", "status": "active"}],
        last_emit_per_ticker={"GME": _dt.date(2026, 4, 28)},
        unread_alerts_by_severity={2: 1, 3: 0},
    )
    conn = FakeConnection(store)
    briefing = collect_operator_briefing(
        conn, now=_dt.datetime(2026, 4, 29, tzinfo=_dt.timezone.utc)
    )
    assert briefing.phase.phase == Phase.V01_ACTIVE
    assert briefing.launch_gates is None
    assert any(a.cadence == "daily" for a in briefing.scheduled_actions)
    assert briefing.alerts.unread_m2 == 1

    out = render_operator_briefing(briefing)
    assert "v0.1-active" in out
    assert "Scheduled Actions Today" in out
    assert "Launch Gate Status" not in out
    assert "Pending Operator Decisions" in out
    assert "Alerts" in out
    assert "System Health" in out


def test_briefing_pending_decisions_surface() -> None:
    store = FakeStore(
        launch_signed_off=True,
        launch_all_green=True,
        launch_date=_dt.date(2026, 4, 1),
        resolved_predictions=5,
        anchor_drift_pending=[
            {
                "check_id": "abc-1",
                "ticker": "PLTR",
                "check_date": _dt.date(2026, 4, 28),
            }
        ],
        mode_reclass_pending=[
            {
                "ticker": "NVDA",
                "classification_date": _dt.date(2026, 4, 27),
                "final_mode": "C",
            }
        ],
    )
    conn = FakeConnection(store)
    briefing = collect_operator_briefing(
        conn, now=_dt.datetime(2026, 4, 29, tzinfo=_dt.timezone.utc)
    )

    types = {d.decision_type for d in briefing.pending_decisions}
    assert "anchor_drift_forced_review" in types
    assert "mode_reclassification" in types

    out = render_operator_briefing(briefing)
    assert "PLTR" in out
    assert "NVDA" in out
