"""Regression tests for the broad-except audit (2026-04-29).

Each test triggers a previously-swallowed exception and asserts that the
new behaviour now LOGS the failure (instead of silently degrading), so an
operator drilling into system logs will see the underlying SQL / parse /
data-fetch error rather than just a False/0/None default.

Audit findings covered:
  - orchestrator.phase_detector — 3 broad excepts in DB-query helpers
    (the file's own docstring on _query_real_money_active calls out a
    real bug that was masked by the broad except).
  - orchestrator.operator_briefing — 5 broad excepts in DB-query helpers
    + the _count_query helper.
  - orchestrator.v01_launch_status._query_launch_readiness_log
  - orchestrator.v01_active_routing watchlist query
  - alert_channels.queue_processor JSON-payload parse
  - mode_classifier.adapters — DefaultDataAdapter / DefaultQualityAdapter
    methods that fall back to None on missing data.
  - l4_daily_monitor.refresh_emitter._TransactionalDbWriter.__exit__
    rollback failure.
  - l4_daily_monitor.drift_detector._TransactionalDbWriter.__exit__
    rollback failure.

Each test exercises the new logging path. Functional behaviour
(returns [] / 0 / False / None) is preserved — only the visibility
changed.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from unittest.mock import MagicMock

import pytest


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


class _RaisingCursor:
    """Cursor whose .execute() always raises; used to drive the except path."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def __enter__(self) -> "_RaisingCursor":
        return self

    def __exit__(self, *_a: Any) -> None:
        pass

    def execute(self, *_a: Any, **_kw: Any) -> None:
        raise self._exc

    def fetchone(self) -> Any:
        return None

    def fetchall(self) -> list:
        return []


class _RaisingConn:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def cursor(self) -> _RaisingCursor:
        return _RaisingCursor(self._exc)


# --------------------------------------------------------------------------- #
# orchestrator.phase_detector                                                 #
# --------------------------------------------------------------------------- #


def test_phase_detector_launch_signoff_logs_swallowed_db_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from src.orchestrator.phase_detector import _query_launch_signoff

    conn = _RaisingConn(RuntimeError("simulated SQL bug — no such column"))
    caplog.set_level(logging.WARNING, logger="src.orchestrator.phase_detector")
    signed, when = _query_launch_signoff(conn)
    assert (signed, when) == (False, None)
    assert any(
        "_query_launch_signoff failed" in r.message
        and "no such column" in r.message
        for r in caplog.records
    ), f"expected log of swallowed SQL error, got: {[r.message for r in caplog.records]}"


def test_phase_detector_resolved_predictions_logs_swallowed_db_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from src.orchestrator.phase_detector import _query_resolved_predictions

    conn = _RaisingConn(RuntimeError("connection reset"))
    caplog.set_level(logging.WARNING, logger="src.orchestrator.phase_detector")
    out = _query_resolved_predictions(conn)
    assert out == 0
    assert any(
        "_query_resolved_predictions failed" in r.message
        for r in caplog.records
    )


def test_phase_detector_real_money_active_logs_swallowed_db_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Regression for the bug documented at phase_detector.py:210 —
    a column-name typo previously fell through silently and routed the
    system into the wrong phase."""
    from src.orchestrator.phase_detector import _query_real_money_active

    conn = _RaisingConn(RuntimeError('column "parameter_value" does not exist'))
    caplog.set_level(logging.WARNING, logger="src.orchestrator.phase_detector")
    out = _query_real_money_active(conn)
    assert out is False
    assert any(
        "_query_real_money_active failed" in r.message
        and "parameter_value" in r.message
        for r in caplog.records
    )


# --------------------------------------------------------------------------- #
# orchestrator.operator_briefing                                              #
# --------------------------------------------------------------------------- #


def test_operator_briefing_count_query_logs_swallowed_db_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from src.orchestrator.operator_briefing import _count_query

    conn = _RaisingConn(RuntimeError("simulated DB outage"))
    caplog.set_level(logging.WARNING, logger="src.orchestrator.operator_briefing")
    out = _count_query(conn, "SELECT COUNT(*) FROM whatever")
    assert out == 0
    assert any(
        "_count_query failed" in r.message and "DB outage" in r.message
        for r in caplog.records
    )


def test_operator_briefing_anchor_drift_logs_swallowed_db_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from src.orchestrator.operator_briefing import _query_anchor_drift_pending

    conn = _RaisingConn(RuntimeError("relation does not exist"))
    caplog.set_level(logging.WARNING, logger="src.orchestrator.operator_briefing")
    out = _query_anchor_drift_pending(conn)
    assert out == []
    assert any(
        "_query_anchor_drift_pending failed" in r.message
        for r in caplog.records
    )


def test_operator_briefing_alert_summary_logs_swallowed_db_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from src.orchestrator.operator_briefing import (
        AlertSummary,
        _collect_alert_summary,
    )

    conn = _RaisingConn(RuntimeError("connection refused"))
    caplog.set_level(logging.WARNING, logger="src.orchestrator.operator_briefing")
    out = _collect_alert_summary(conn)
    assert out == AlertSummary(unread_m2=0, unread_m3=0)
    assert any(
        "_collect_alert_summary failed" in r.message
        for r in caplog.records
    )


# --------------------------------------------------------------------------- #
# orchestrator.v01_launch_status                                              #
# --------------------------------------------------------------------------- #


def test_v01_launch_status_logs_swallowed_db_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from src.orchestrator.v01_launch_status import _query_launch_readiness_log

    conn = _RaisingConn(RuntimeError("schema drift"))
    caplog.set_level(logging.WARNING, logger="src.orchestrator.v01_launch_status")
    out = _query_launch_readiness_log(conn)
    assert out == {}
    assert any(
        "_query_launch_readiness_log failed" in r.message
        for r in caplog.records
    )


# --------------------------------------------------------------------------- #
# orchestrator.v01_active_routing                                             #
# --------------------------------------------------------------------------- #


def test_v01_active_routing_logs_swallowed_db_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from src.orchestrator import v01_active_routing

    # The watchlist fetcher is a private name; query module attributes.
    fetcher = None
    for name in dir(v01_active_routing):
        if name.startswith("_") and "watchlist" in name.lower():
            fetcher = getattr(v01_active_routing, name)
            break
    if fetcher is None:
        # Fall back to scanning module source for the function name.
        import inspect

        for name, obj in inspect.getmembers(v01_active_routing, inspect.isfunction):
            try:
                src = inspect.getsource(obj)
            except OSError:
                continue
            if (
                "FROM watchlist" in src
                and "v01_active_routing watchlist" in src
            ):
                fetcher = obj
                break
    assert fetcher is not None, "could not locate the watchlist fetcher"

    conn = _RaisingConn(RuntimeError("table missing"))
    caplog.set_level(logging.WARNING, logger="src.orchestrator.v01_active_routing")
    out = fetcher(conn)
    assert out == []
    assert any(
        "v01_active_routing watchlist query failed" in r.message
        for r in caplog.records
    )


# --------------------------------------------------------------------------- #
# alert_channels.queue_processor — JSON parse failure                         #
# --------------------------------------------------------------------------- #


def test_queue_processor_logs_corrupt_payload(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If unread_alerts.payload contains corrupted JSON, the processor must
    log + degrade to {} (not silently swallow)."""
    import datetime as _dt
    from uuid import uuid4

    from src.alert_channels.queue_processor import _select_pending_email_rows

    alert_id = uuid4()
    row = (
        str(alert_id),  # alert_id
        3,  # severity
        "test_alert",  # alert_type
        "AAPL",  # ticker
        "test summary",  # summary
        "{this is: not json,",  # payload (corrupt)
        None,  # drill_link_recommendation_id
        0,  # email_send_attempts
        _dt.datetime.now(_dt.timezone.utc),  # created_at
    )

    class _StubConn:
        def cursor(self_inner):
            class _C:
                def __enter__(self_c):
                    return self_c

                def __exit__(self_c, *a):
                    pass

                def execute(self_c, *a, **kw):
                    pass

                def fetchall(self_c):
                    return [row]

            return _C()

    caplog.set_level(logging.WARNING, logger="src.alert_channels.queue_processor")
    out = _select_pending_email_rows(_StubConn())
    assert len(out) == 1
    alert, _created = out[0]
    assert alert.payload == {}, "corrupt payload must degrade to empty dict"
    assert any(
        "failed to parse payload" in r.message for r in caplog.records
    ), f"expected parse-failure log, got: {[r.message for r in caplog.records]}"


# --------------------------------------------------------------------------- #
# mode_classifier.adapters — fallback paths now log                           #
# --------------------------------------------------------------------------- #


def test_quality_adapter_missing_overrides_logs_info(
    caplog: pytest.LogCaptureFixture, tmp_path: Any,
) -> None:
    """DefaultQualityAdapter._lookup_founder_tenure formerly swallowed all
    Exceptions silently. Now narrowed to (OSError, ValueError) and logged."""
    from src.mode_classifier.adapters import DefaultQualityAdapter

    missing_path = str(tmp_path / "does_not_exist.json")
    adapter = DefaultQualityAdapter(watchlist_overrides_path=missing_path)

    caplog.set_level(logging.INFO, logger="src.mode_classifier.adapters")
    tenure = adapter._lookup_founder_tenure("AAPL")
    assert tenure is None
    assert any(
        "_lookup_founder_tenure" in r.message and "AAPL" in r.message
        for r in caplog.records
    )


def test_quality_adapter_corrupt_overrides_logs(
    caplog: pytest.LogCaptureFixture, tmp_path: Any,
) -> None:
    from src.mode_classifier.adapters import DefaultQualityAdapter

    p = tmp_path / "watchlist_overrides.json"
    p.write_text("{this is not valid json", encoding="utf-8")
    adapter = DefaultQualityAdapter(watchlist_overrides_path=str(p))

    caplog.set_level(logging.INFO, logger="src.mode_classifier.adapters")
    out = adapter._lookup_profitability_path("AAPL", tenure=10.0)
    assert out is False
    assert any(
        "_lookup_profitability_path" in r.message
        for r in caplog.records
    )


# --------------------------------------------------------------------------- #
# l4_daily_monitor — transactional rollback failure surfaces in logs          #
# --------------------------------------------------------------------------- #


def test_refresh_emitter_rollback_failure_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When a transaction rollback itself fails, the original exception
    must propagate AND the rollback failure must be logged so the
    operator can see the data-integrity signal."""
    from src.l4_daily_monitor.refresh_emitter import _TransactionalDbWriter

    writer = _TransactionalDbWriter(dsn="dummy://")
    fake_conn = MagicMock()
    fake_conn.rollback.side_effect = RuntimeError("rollback exploded")
    fake_conn.close.side_effect = None
    writer._conn = fake_conn

    caplog.set_level(logging.ERROR, logger="src.l4_daily_monitor.refresh_emitter")
    # Simulate exiting with an in-flight body exception.
    out = writer.__exit__(RuntimeError, RuntimeError("body bug"), None)
    assert out is False  # do not suppress original
    fake_conn.rollback.assert_called_once()
    assert any(
        "rollback FAILED" in r.message and "body bug" in r.message
        for r in caplog.records
    ), f"missing rollback-failure log; got: {[r.message for r in caplog.records]}"


def test_drift_detector_rollback_failure_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from src.l4_daily_monitor.drift_detector import _TransactionalDbWriter

    writer = _TransactionalDbWriter(dsn="dummy://")
    fake_conn = MagicMock()
    fake_conn.rollback.side_effect = RuntimeError("network gone")
    fake_conn.close.side_effect = None
    writer._conn = fake_conn

    caplog.set_level(logging.ERROR, logger="src.l4_daily_monitor.drift_detector")
    out = writer.__exit__(RuntimeError, RuntimeError("body bug"), None)
    assert out is False
    fake_conn.rollback.assert_called_once()
    assert any(
        "rollback FAILED" in r.message
        and "drift+alert atomicity" in r.message
        for r in caplog.records
    )


def test_refresh_emitter_close_failure_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """conn.close() failure during teardown is now logged (was: silently
    swallowed). Common signal for connection-pool exhaustion."""
    from src.l4_daily_monitor.refresh_emitter import _TransactionalDbWriter

    writer = _TransactionalDbWriter(dsn="dummy://")
    fake_conn = MagicMock()
    fake_conn.commit.side_effect = None
    fake_conn.close.side_effect = RuntimeError("close failed")
    writer._conn = fake_conn

    caplog.set_level(logging.WARNING, logger="src.l4_daily_monitor.refresh_emitter")
    writer.__exit__(None, None, None)
    fake_conn.commit.assert_called_once()
    assert any(
        "close failed" in r.message for r in caplog.records
    )
