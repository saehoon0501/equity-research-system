"""Smoke tests for the alert_channels package.

No live SMTP. No live Postgres. Both are stubbed via small in-memory fakes
mirroring the parts of the PEP-249 / smtplib API the module touches.

Coverage layer-by-layer:
  - email_sender.SmtpConfig.from_env       env-var resolution + missing-var error
  - email_sender._render_email_body        subject + plain + HTML invariants
  - email_sender.send_email_for_alert      idempotency, severity gate, success,
                                           transient + final failure
  - queue_processor._is_eligible_now       Phase 4 Q9 backoff math
  - queue_processor.process_email_queue    end-to-end drain stats
  - session_push.list_unread_alerts        ordering + filters
  - session_push.acknowledge*              idempotent ack flow
  - session_push.surface_unread_at_session_start  markdown header + stamp side-effect
  - system_health.render_system_health     all five sections present in markdown

Per v3 spec Section 5.3 + 5.4 + Section 7 PB#4 + Phase 4 Q9.
"""

from __future__ import annotations

import datetime as _dt
import sys
import uuid
from pathlib import Path
from typing import Any, Optional

import pytest

# Mirror sys.path trick used by other test modules.
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from alert_channels import (  # noqa: E402
    MAX_EMAIL_ATTEMPTS,
    RETRY_BACKOFFS_SECONDS,
    SEVERITY_M2,
    SEVERITY_M3,
)
from alert_channels.email_sender import (  # noqa: E402
    AlertRow,
    SendResult,
    SmtpConfig,
    _render_email_body,
    send_email_for_alert,
)
from alert_channels.queue_processor import (  # noqa: E402
    _is_eligible_now,
    process_email_queue,
)
from alert_channels.session_push import (  # noqa: E402
    UnreadAlertSummary,
    acknowledge,
    acknowledge_all,
    list_unread_alerts,
    render_alerts_list,
    surface_unread_at_session_start,
)
from alert_channels.system_health import render_system_health  # noqa: E402


# --------------------------------------------------------------------------- #
# In-memory PEP-249 stub                                                       #
# --------------------------------------------------------------------------- #


class _FakeCursor:
    def __init__(self, store: "_FakeStore") -> None:
        self._store = store
        self._result: list[tuple[Any, ...]] = []
        self.rowcount = 0

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def close(self) -> None:
        return None

    def execute(self, sql: str, params: Optional[tuple[Any, ...]] = None) -> None:
        self._result, self.rowcount = self._store.execute(sql, params or ())

    def fetchone(self) -> Optional[tuple[Any, ...]]:
        return self._result[0] if self._result else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._result)


class _FakeStore:
    """Minimal in-memory store backing tests of unread_alerts + system_errors.

    SQL parser is intentionally trivial — pattern-matches the SQL strings the
    module actually emits. When you change a query, update this stub.
    """

    def __init__(self) -> None:
        self.alerts: list[dict[str, Any]] = []
        self.system_errors: list[dict[str, Any]] = []

    # ---- helpers ---- #
    def add_alert(self, **kwargs: Any) -> dict[str, Any]:
        row: dict[str, Any] = {
            "alert_id": uuid.uuid4(),
            "severity": SEVERITY_M3,
            "alert_type": "materiality_m3",
            "ticker": "AAPL",
            "summary": "test summary",
            "payload": {},
            "drill_link_recommendation_id": None,
            "created_at": _dt.datetime(2026, 4, 29, 12, 0, tzinfo=_dt.timezone.utc),
            "acknowledged_at": None,
            "acknowledged_by": "operator",
            "email_sent_at": None,
            "email_send_attempts": 0,
            "claude_session_pushed_at": None,
        }
        row.update(kwargs)
        self.alerts.append(row)
        return row

    # ---- dispatch ---- #
    def execute(
        self,
        sql: str,
        params: tuple[Any, ...],
    ) -> tuple[list[tuple[Any, ...]], int]:
        s = " ".join(sql.split())  # collapse whitespace

        # ----- email_sender: idempotency probe (TOCTOU-safe FOR UPDATE) -----
        if s.startswith(
            "SELECT email_sent_at, email_send_attempts FROM unread_alerts "
            "WHERE alert_id ="
        ):
            (alert_id_str,) = params
            for row in self.alerts:
                if str(row["alert_id"]) == alert_id_str:
                    return [(row["email_sent_at"], row["email_send_attempts"])], 1
            return [], 0

        # Legacy single-column probe — kept so any callers that didn't
        # migrate to FOR UPDATE still work. Currently unused in tree.
        if s.startswith("SELECT email_sent_at FROM unread_alerts WHERE alert_id ="):
            (alert_id_str,) = params
            for row in self.alerts:
                if str(row["alert_id"]) == alert_id_str:
                    return [(row["email_sent_at"],)], 1
            return [], 0

        # ----- email_sender: pre-SMTP attempts bump (TOCTOU-safe) -----
        if s.startswith(
            "UPDATE unread_alerts SET email_send_attempts = %s WHERE alert_id ="
        ):
            attempts, alert_id_str = params
            for row in self.alerts:
                if str(row["alert_id"]) == alert_id_str:
                    row["email_send_attempts"] = attempts
                    return [], 1
            return [], 0

        # ----- email_sender: post-SMTP sent_at stamp -----
        if s.startswith(
            "UPDATE unread_alerts SET email_sent_at = COALESCE(email_sent_at, %s)"
        ):
            sent_at, alert_id_str = params
            for row in self.alerts:
                if str(row["alert_id"]) == alert_id_str:
                    if row["email_sent_at"] is None:
                        row["email_sent_at"] = sent_at
                    return [], 1
            return [], 0

        # Legacy combined update — retained for backwards-compat.
        if s.startswith("UPDATE unread_alerts SET email_send_attempts ="):
            attempts, sent_at, alert_id_str = params
            for row in self.alerts:
                if str(row["alert_id"]) == alert_id_str:
                    row["email_send_attempts"] = attempts
                    if sent_at is not None and row["email_sent_at"] is None:
                        row["email_sent_at"] = sent_at
                    return [], 1
            return [], 0

        # ----- email_sender: system_errors INSERT -----
        if s.startswith("INSERT INTO system_errors"):
            (
                ts,
                source,
                err_type,
                err_detail,
                retry_count,
                escalated,
                blocked_decision,
            ) = params
            self.system_errors.append(
                {
                    "timestamp_at": ts,
                    "source": source,
                    "error_type": err_type,
                    "error_detail": err_detail,
                    "retry_count": retry_count,
                    "escalated_to_alert": escalated,
                    "blocked_decision": blocked_decision,
                    "resolved_at": None,
                    "resolution": None,
                }
            )
            return [], 1

        # ----- queue_processor: SELECT pending rows -----
        if s.startswith("SELECT alert_id, severity, alert_type, ticker, summary, payload"):
            severity, max_attempts = params
            rows = [
                (
                    str(r["alert_id"]),
                    r["severity"],
                    r["alert_type"],
                    r["ticker"],
                    r["summary"],
                    r["payload"],
                    str(r["drill_link_recommendation_id"]) if r["drill_link_recommendation_id"] else None,
                    r["email_send_attempts"],
                    r["created_at"],
                )
                for r in self.alerts
                if r["severity"] == severity
                and r["email_sent_at"] is None
                and r["email_send_attempts"] < max_attempts
            ]
            rows.sort(key=lambda x: x[8])
            return rows, len(rows)

        # ----- session_push: list_unread_alerts (with optional filters) -----
        if s.startswith("SELECT alert_id, severity, alert_type, ticker, summary, drill_link_recommendation_id, created_at FROM unread_alerts WHERE acknowledged_at IS NULL"):
            filtered = [r for r in self.alerts if r["acknowledged_at"] is None]
            # Basic param consumption (severity/ticker/type/since)
            param_iter = iter(params)
            if "AND severity = %s" in s:
                sev = next(param_iter)
                filtered = [r for r in filtered if r["severity"] == sev]
            if "AND ticker = %s" in s:
                tkr = next(param_iter)
                filtered = [r for r in filtered if r["ticker"] == tkr]
            if "AND alert_type = %s" in s:
                at = next(param_iter)
                filtered = [r for r in filtered if r["alert_type"] == at]
            if "AND created_at >= %s" in s:
                since = next(param_iter)
                filtered = [r for r in filtered if r["created_at"] >= since]
            filtered.sort(key=lambda r: (-r["severity"], r["created_at"]), reverse=False)
            # severity DESC, created_at DESC: emulate sort
            filtered.sort(key=lambda r: r["created_at"], reverse=True)
            filtered.sort(key=lambda r: r["severity"], reverse=True)
            rows = [
                (
                    str(r["alert_id"]),
                    r["severity"],
                    r["alert_type"],
                    r["ticker"],
                    r["summary"],
                    str(r["drill_link_recommendation_id"]) if r["drill_link_recommendation_id"] else None,
                    r["created_at"],
                )
                for r in filtered
            ]
            return rows, len(rows)

        # ----- session_push: acknowledge single -----
        if s.startswith("UPDATE unread_alerts SET acknowledged_at = %s, acknowledged_by = %s WHERE alert_id ="):
            ack_at, ack_by, alert_id_str = params
            count = 0
            for row in self.alerts:
                if str(row["alert_id"]) == alert_id_str and row["acknowledged_at"] is None:
                    row["acknowledged_at"] = ack_at
                    row["acknowledged_by"] = ack_by
                    count += 1
            return [], count

        # ----- session_push: acknowledge_all -----
        if s.startswith("UPDATE unread_alerts SET acknowledged_at = %s, acknowledged_by = %s WHERE acknowledged_at IS NULL"):
            ack_at, ack_by = params
            count = 0
            for row in self.alerts:
                if row["acknowledged_at"] is None:
                    row["acknowledged_at"] = ack_at
                    row["acknowledged_by"] = ack_by
                    count += 1
            return [], count

        # ----- session_push: stamp pushed_at -----
        if s.startswith("UPDATE unread_alerts SET claude_session_pushed_at ="):
            now, alert_id_strs = params
            target = {str(a) for a in alert_id_strs}
            for row in self.alerts:
                if str(row["alert_id"]) in target and row["claude_session_pushed_at"] is None:
                    row["claude_session_pushed_at"] = now
            return [], len(target)

        # ----- system_health: degraded MCPs -----
        if s.startswith("SELECT e.source, MAX(CASE WHEN e.resolved_at IS NOT NULL"):
            sources = sorted({e["source"] for e in self.system_errors if e["resolved_at"] is None})
            rows = []
            for src in sources:
                last_ok = None
                for e in self.system_errors:
                    if e["source"] == src and e["resolved_at"] is not None:
                        if last_ok is None or e["timestamp_at"] > last_ok:
                            last_ok = e["timestamp_at"]
                rows.append((src, last_ok))
            return rows, len(rows)

        # ----- system_health: email queue depth -----
        if s.startswith("SELECT COUNT(*) FROM unread_alerts WHERE severity = %s AND email_sent_at IS NULL AND email_send_attempts < %s"):
            sev, max_a = params
            n = sum(
                1
                for r in self.alerts
                if r["severity"] == sev
                and r["email_sent_at"] is None
                and r["email_send_attempts"] < max_a
            )
            return [(n,)], 1

        # ----- system_health: queued for session push -----
        if s.startswith("SELECT COUNT(*) FROM unread_alerts WHERE severity = %s AND email_sent_at IS NULL AND email_send_attempts >= %s AND acknowledged_at IS NULL"):
            sev, max_a = params
            n = sum(
                1
                for r in self.alerts
                if r["severity"] == sev
                and r["email_sent_at"] is None
                and r["email_send_attempts"] >= max_a
                and r["acknowledged_at"] is None
            )
            return [(n,)], 1

        # ----- system_health: unread count by severity -----
        if s.startswith("SELECT COUNT(*) FROM unread_alerts WHERE severity = %s AND acknowledged_at IS NULL"):
            (sev,) = params
            n = sum(1 for r in self.alerts if r["severity"] == sev and r["acknowledged_at"] is None)
            return [(n,)], 1

        # ----- system_health: peak_pain_catalog probe -----
        if s.startswith("SELECT to_regclass"):
            return [(None,)], 1  # table absent in tests

        # ----- system_health: 7-day error count -----
        if s.startswith("SELECT source, COUNT(*) FROM system_errors WHERE timestamp_at >= %s"):
            (cutoff,) = params
            from collections import Counter

            counts = Counter(
                e["source"] for e in self.system_errors if e["timestamp_at"] >= cutoff
            )
            rows = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
            return rows, len(rows)

        raise NotImplementedError(f"unsupported SQL in stub: {s[:120]}")


class _FakeConn:
    def __init__(self, store: _FakeStore) -> None:
        self._store = store

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._store)

    def commit(self) -> None:
        return None

    def close(self) -> None:
        return None


@pytest.fixture
def store() -> _FakeStore:
    return _FakeStore()


@pytest.fixture
def conn(store: _FakeStore) -> _FakeConn:
    return _FakeConn(store)


@pytest.fixture
def smtp_config() -> SmtpConfig:
    return SmtpConfig(
        host="smtp.test",
        port=587,
        username="u",
        password="p",
        sender="from@test",
        recipient="to@test",
        use_tls=False,
    )


# --------------------------------------------------------------------------- #
# Fake SMTP client                                                            #
# --------------------------------------------------------------------------- #


class _FakeSMTP:
    def __init__(self, *, fail_with: Optional[Exception] = None) -> None:
        self.fail_with = fail_with
        self.sent_messages: list[str] = []
        self.login_called = False
        self.starttls_called = False
        self.quit_called = False

    def starttls(self, context: Any = None) -> None:
        self.starttls_called = True

    def login(self, u: str, p: str) -> None:
        self.login_called = True
        if self.fail_with is not None:
            raise self.fail_with

    def sendmail(self, sender: str, rcpts: list[str], body: str) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.sent_messages.append(body)

    def quit(self) -> None:
        self.quit_called = True


# --------------------------------------------------------------------------- #
# SmtpConfig.from_env                                                         #
# --------------------------------------------------------------------------- #


class TestSmtpConfigFromEnv:
    REQUIRED = {
        "ALERT_SMTP_HOST": "smtp.example.com",
        "ALERT_SMTP_PORT": "587",
        "ALERT_SMTP_USERNAME": "u",
        "ALERT_SMTP_PASSWORD": "p",
        "ALERT_SMTP_SENDER": "from@example.com",
        "ALERT_SMTP_RECIPIENT": "to@example.com",
    }

    def test_loads_all_required(self) -> None:
        cfg = SmtpConfig.from_env(self.REQUIRED.copy())
        assert cfg.host == "smtp.example.com"
        assert cfg.port == 587
        assert cfg.use_tls is True

    def test_use_tls_zero_disables(self) -> None:
        env = self.REQUIRED.copy()
        env["ALERT_SMTP_USE_TLS"] = "0"
        cfg = SmtpConfig.from_env(env)
        assert cfg.use_tls is False

    def test_missing_var_raises(self) -> None:
        env = self.REQUIRED.copy()
        del env["ALERT_SMTP_PASSWORD"]
        with pytest.raises(RuntimeError, match="ALERT_SMTP_PASSWORD"):
            SmtpConfig.from_env(env)


# --------------------------------------------------------------------------- #
# Email body rendering                                                        #
# --------------------------------------------------------------------------- #


class TestRenderEmailBody:
    def _make(self, **overrides: Any) -> AlertRow:
        rec_id = uuid.uuid4()
        defaults: dict[str, Any] = {
            "alert_id": uuid.uuid4(),
            "severity": SEVERITY_M3,
            "alert_type": "materiality_m3",
            "ticker": "AAPL",
            "summary": "Earnings miss; guidance cut",
            "payload": {},
            "drill_link_recommendation_id": rec_id,
            "email_send_attempts": 0,
        }
        defaults.update(overrides)
        return AlertRow(**defaults)

    def test_subject_uses_m3_tag(self) -> None:
        alert = self._make()
        subject, _, _ = _render_email_body(alert)
        assert subject == f"[M-3] AAPL — materiality_m3"

    def test_subject_falls_back_to_portfolio_when_no_ticker(self) -> None:
        alert = self._make(ticker=None)
        subject, _, _ = _render_email_body(alert)
        assert "PORTFOLIO" in subject

    def test_plain_includes_drill_instruction(self) -> None:
        alert = self._make()
        _, plain, _ = _render_email_body(alert)
        assert "Run /audit-trail" in plain
        assert str(alert.drill_link_recommendation_id) in plain
        assert f"/ack {alert.alert_id}" in plain

    def test_html_well_formed_minimal(self) -> None:
        alert = self._make()
        _, _, html = _render_email_body(alert)
        assert html.startswith("<!DOCTYPE html>")
        assert "<body>" in html and "</body>" in html
        assert "M-3 ALERT" in html

    def test_no_drill_link_omits_drill_section(self) -> None:
        alert = self._make(drill_link_recommendation_id=None)
        _, plain, html = _render_email_body(alert)
        assert "Run /audit-trail" not in plain
        assert "/audit-trail" not in html


# --------------------------------------------------------------------------- #
# send_email_for_alert                                                        #
# --------------------------------------------------------------------------- #


class TestSendEmailForAlert:
    def _alert(self, store: _FakeStore, **overrides: Any) -> AlertRow:
        row = store.add_alert(**overrides)
        return AlertRow(
            alert_id=row["alert_id"],
            severity=row["severity"],
            alert_type=row["alert_type"],
            ticker=row["ticker"],
            summary=row["summary"],
            payload=row["payload"],
            drill_link_recommendation_id=row["drill_link_recommendation_id"],
            email_send_attempts=row["email_send_attempts"],
        )

    def test_skips_m2(
        self, store: _FakeStore, conn: _FakeConn, smtp_config: SmtpConfig
    ) -> None:
        alert = self._alert(store, severity=SEVERITY_M2)
        result = send_email_for_alert(
            conn=conn,
            alert=alert,
            smtp_config=smtp_config,
            smtp_client_factory=lambda: _FakeSMTP(),
        )
        assert result.sent is False
        assert result.error_detail == "severity_below_threshold"

    def test_success_marks_sent(
        self, store: _FakeStore, conn: _FakeConn, smtp_config: SmtpConfig
    ) -> None:
        alert = self._alert(store)
        smtp = _FakeSMTP()
        result = send_email_for_alert(
            conn=conn,
            alert=alert,
            smtp_config=smtp_config,
            smtp_client_factory=lambda: smtp,
        )
        assert result.sent is True
        assert result.attempt_number == 1
        assert smtp.sent_messages, "SMTP did not receive a message"
        # State updated.
        row = next(r for r in store.alerts if r["alert_id"] == alert.alert_id)
        assert row["email_sent_at"] is not None
        assert row["email_send_attempts"] == 1

    def test_idempotent_on_already_sent(
        self, store: _FakeStore, conn: _FakeConn, smtp_config: SmtpConfig
    ) -> None:
        sent_ts = _dt.datetime(2026, 4, 29, 14, tzinfo=_dt.timezone.utc)
        alert = self._alert(store, email_sent_at=sent_ts)
        smtp = _FakeSMTP()
        result = send_email_for_alert(
            conn=conn,
            alert=alert,
            smtp_config=smtp_config,
            smtp_client_factory=lambda: smtp,
        )
        assert result.sent is True
        assert result.error_detail == "already_sent"
        assert smtp.sent_messages == []  # not re-sent

    def test_transient_failure_increments_attempts(
        self, store: _FakeStore, conn: _FakeConn, smtp_config: SmtpConfig
    ) -> None:
        alert = self._alert(store)
        result = send_email_for_alert(
            conn=conn,
            alert=alert,
            smtp_config=smtp_config,
            smtp_client_factory=lambda: _FakeSMTP(fail_with=ConnectionError("nope")),
        )
        assert result.sent is False
        assert result.queued_for_session_push is False
        assert "ConnectionError" in (result.error_detail or "")
        row = next(r for r in store.alerts if r["alert_id"] == alert.alert_id)
        assert row["email_send_attempts"] == 1
        assert row["email_sent_at"] is None

    def test_final_failure_logs_system_error(
        self, store: _FakeStore, conn: _FakeConn, smtp_config: SmtpConfig
    ) -> None:
        # Pretend MAX-1 prior attempts already failed; this is the final.
        alert = self._alert(store, email_send_attempts=MAX_EMAIL_ATTEMPTS - 1)
        result = send_email_for_alert(
            conn=conn,
            alert=alert,
            smtp_config=smtp_config,
            smtp_client_factory=lambda: _FakeSMTP(fail_with=TimeoutError("timeout")),
        )
        assert result.sent is False
        assert result.queued_for_session_push is True
        assert result.attempt_number == MAX_EMAIL_ATTEMPTS
        assert len(store.system_errors) == 1
        err = store.system_errors[0]
        assert err["source"] == "alert_channels.email_sender"
        assert err["error_type"] == "smtp_send_failed"
        assert err["escalated_to_alert"] is True

    def test_concurrent_processors_do_not_double_send(
        self, store: _FakeStore, smtp_config: SmtpConfig
    ) -> None:
        """TOCTOU lock: two concurrent processors must not both send.

        Simulates two queue processors racing on the same alert. The
        TOCTOU-safe path uses ``SELECT ... FOR UPDATE`` + pre-bump of
        ``email_send_attempts`` BEFORE SMTP. We model the row lock
        explicitly with a ``threading.Lock`` so the second processor
        sees the bumped attempts counter when it acquires the lock and
        bails out (because we also stamp ``email_sent_at`` post-send).

        Per v3 spec Section 5.3 + Phase 4 Q9.
        """
        import threading

        # Fresh store + alert
        alert_row = store.add_alert()
        alert = AlertRow(
            alert_id=alert_row["alert_id"],
            severity=alert_row["severity"],
            alert_type=alert_row["alert_type"],
            ticker=alert_row["ticker"],
            summary=alert_row["summary"],
            payload=alert_row["payload"],
            drill_link_recommendation_id=alert_row["drill_link_recommendation_id"],
            email_send_attempts=alert_row["email_send_attempts"],
        )

        # Lock-aware connection: serializes execute() across cursors,
        # mimicking the postgres FOR UPDATE row lock semantics for the
        # critical SELECT/UPDATE pair. (The real implementation relies
        # on the DB; here we coarse-grain at the per-conn level.)
        per_conn_lock = threading.Lock()

        class _LockedConn(_FakeConn):
            def __init__(self, store: _FakeStore) -> None:
                super().__init__(store)
                self._held = False

            def cursor(self) -> _FakeCursor:
                return _LockedCursor(self._store, per_conn_lock)

            def commit(self) -> None:
                # Releasing the lock is modeled at the cursor level.
                return None

        class _LockedCursor(_FakeCursor):
            def __init__(self, store: _FakeStore, lock: threading.Lock) -> None:
                super().__init__(store)
                self._lock = lock
                self._holding = False

            def execute(self, sql: str, params: Optional[tuple[Any, ...]] = None) -> None:
                s = " ".join(sql.split())
                if "FOR UPDATE" in s and not self._holding:
                    self._lock.acquire()
                    self._holding = True
                super().execute(sql, params)

            def __exit__(self, *exc: Any) -> None:
                if self._holding:
                    self._lock.release()
                    self._holding = False
                return None

            def close(self) -> None:
                if self._holding:
                    self._lock.release()
                    self._holding = False

        results: list[SendResult] = []
        results_lock = threading.Lock()
        smtp_clients: list[_FakeSMTP] = []

        def _factory() -> _FakeSMTP:
            c = _FakeSMTP()
            smtp_clients.append(c)
            return c

        def _worker() -> None:
            conn_local = _LockedConn(store)
            r = send_email_for_alert(
                conn=conn_local,
                alert=alert,
                smtp_config=smtp_config,
                smtp_client_factory=_factory,
            )
            with results_lock:
                results.append(r)

        t1 = threading.Thread(target=_worker)
        t2 = threading.Thread(target=_worker)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        # Exactly one true-send (sent=True with no 'already_sent' marker).
        true_sends = [
            r for r in results
            if r.sent and r.error_detail not in ("already_sent", "already_sent_or_unknown")
        ]
        assert len(true_sends) == 1, (
            f"expected exactly one real send; got {len(true_sends)}: {results}"
        )
        # The other peer either saw already_sent or got severity_below_threshold-style bail.
        idempotent_results = [
            r for r in results
            if r.error_detail in ("already_sent", "already_sent_or_unknown")
        ]
        assert len(idempotent_results) == 1, (
            f"expected one idempotent bail; got: {results}"
        )

        # Only one SMTP client actually ``sendmail``-ed.
        senders_with_msg = [c for c in smtp_clients if c.sent_messages]
        assert len(senders_with_msg) == 1


# --------------------------------------------------------------------------- #
# queue_processor backoff math                                                #
# --------------------------------------------------------------------------- #


class TestEligibleNow:
    BASE = _dt.datetime(2026, 4, 29, 12, 0, tzinfo=_dt.timezone.utc)

    def test_attempt_zero_immediately_eligible(self) -> None:
        assert _is_eligible_now(attempts=0, created_at=self.BASE, now=self.BASE) is True

    def test_attempt_one_waits_60s(self) -> None:
        assert _is_eligible_now(attempts=1, created_at=self.BASE, now=self.BASE) is False
        assert (
            _is_eligible_now(
                attempts=1,
                created_at=self.BASE,
                now=self.BASE + _dt.timedelta(seconds=RETRY_BACKOFFS_SECONDS[0]),
            )
            is True
        )

    def test_attempt_two_waits_60s_plus_300s(self) -> None:
        cumulative = sum(RETRY_BACKOFFS_SECONDS[:2])
        assert (
            _is_eligible_now(
                attempts=2,
                created_at=self.BASE,
                now=self.BASE + _dt.timedelta(seconds=cumulative - 1),
            )
            is False
        )
        assert (
            _is_eligible_now(
                attempts=2,
                created_at=self.BASE,
                now=self.BASE + _dt.timedelta(seconds=cumulative),
            )
            is True
        )

    def test_max_attempts_never_eligible(self) -> None:
        assert (
            _is_eligible_now(
                attempts=MAX_EMAIL_ATTEMPTS,
                created_at=self.BASE,
                now=self.BASE + _dt.timedelta(days=365),
            )
            is False
        )

    def test_retry_attempt_4_uses_900s_wait(self) -> None:
        """Phase 4 Q9 lock: 1m / 5m / 15m schedule, MAX_EMAIL_ATTEMPTS=4.

        Cumulative wait before attempt 4 = 60 + 300 + 900 = 1260s.
        This exercises the 15m slot that previously was dead code.
        """
        assert MAX_EMAIL_ATTEMPTS == 4
        cumulative = sum(RETRY_BACKOFFS_SECONDS[:3])  # 1m + 5m + 15m
        assert cumulative == 60 + 300 + 900

        # Just before eligibility.
        assert (
            _is_eligible_now(
                attempts=3,
                created_at=self.BASE,
                now=self.BASE + _dt.timedelta(seconds=cumulative - 1),
            )
            is False
        )
        # At eligibility.
        assert (
            _is_eligible_now(
                attempts=3,
                created_at=self.BASE,
                now=self.BASE + _dt.timedelta(seconds=cumulative),
            )
            is True
        )


# --------------------------------------------------------------------------- #
# process_email_queue end-to-end                                              #
# --------------------------------------------------------------------------- #


class TestProcessEmailQueue:
    def test_drains_eligible_rows(
        self, store: _FakeStore, conn: _FakeConn, smtp_config: SmtpConfig
    ) -> None:
        # Two eligible M-3 rows, one M-2 (skipped at SELECT level via severity gate).
        store.add_alert(severity=SEVERITY_M3)
        store.add_alert(severity=SEVERITY_M3)
        store.add_alert(severity=SEVERITY_M2)
        result = process_email_queue(
            conn=conn,
            smtp_config=smtp_config,
            smtp_client_factory=lambda: _FakeSMTP(),
            now=_dt.datetime(2026, 4, 29, 13, tzinfo=_dt.timezone.utc),
        )
        assert result.rows_examined == 2
        assert result.rows_sent == 2
        assert result.rows_failed_transient == 0
        assert result.rows_queued_for_session_push == 0

    def test_skips_rows_in_backoff_window(
        self, store: _FakeStore, conn: _FakeConn, smtp_config: SmtpConfig
    ) -> None:
        created = _dt.datetime(2026, 4, 29, 12, tzinfo=_dt.timezone.utc)
        store.add_alert(
            severity=SEVERITY_M3,
            email_send_attempts=1,
            created_at=created,
        )
        # 30 s after create — backoff is 60 s for attempt 1, so not eligible.
        result = process_email_queue(
            conn=conn,
            smtp_config=smtp_config,
            smtp_client_factory=lambda: _FakeSMTP(),
            now=created + _dt.timedelta(seconds=30),
        )
        assert result.rows_examined == 1
        assert result.rows_skipped_backoff == 1
        assert result.rows_sent == 0


# --------------------------------------------------------------------------- #
# session_push: list / acknowledge / surface                                  #
# --------------------------------------------------------------------------- #


class TestSessionPush:
    def test_list_orders_severity_then_recency(
        self, store: _FakeStore, conn: _FakeConn
    ) -> None:
        old = _dt.datetime(2026, 4, 28, tzinfo=_dt.timezone.utc)
        new = _dt.datetime(2026, 4, 29, tzinfo=_dt.timezone.utc)
        a_m2_new = store.add_alert(severity=SEVERITY_M2, created_at=new, alert_type="materiality_m2")
        a_m3_old = store.add_alert(severity=SEVERITY_M3, created_at=old)
        a_m3_new = store.add_alert(severity=SEVERITY_M3, created_at=new)
        rows = list_unread_alerts(conn)
        # Severity DESC then created_at DESC -> M-3 new, M-3 old, M-2 new
        ids = [r.alert_id for r in rows]
        assert ids == [a_m3_new["alert_id"], a_m3_old["alert_id"], a_m2_new["alert_id"]]

    def test_filters_by_severity_and_ticker(
        self, store: _FakeStore, conn: _FakeConn
    ) -> None:
        store.add_alert(severity=SEVERITY_M3, ticker="AAPL")
        store.add_alert(severity=SEVERITY_M3, ticker="MSFT")
        store.add_alert(severity=SEVERITY_M2, ticker="AAPL", alert_type="materiality_m2")
        rows = list_unread_alerts(conn, severity=SEVERITY_M3, ticker="AAPL")
        assert len(rows) == 1
        assert rows[0].ticker == "AAPL"
        assert rows[0].severity == SEVERITY_M3

    def test_acknowledge_idempotent(
        self, store: _FakeStore, conn: _FakeConn
    ) -> None:
        row = store.add_alert()
        assert acknowledge(conn, row["alert_id"]) is True
        assert acknowledge(conn, row["alert_id"]) is False  # already acked

    def test_acknowledge_all(
        self, store: _FakeStore, conn: _FakeConn
    ) -> None:
        store.add_alert()
        store.add_alert(severity=SEVERITY_M2, alert_type="materiality_m2")
        already = store.add_alert(acknowledged_at=_dt.datetime.now(_dt.timezone.utc))
        n = acknowledge_all(conn)
        assert n == 2
        # Pre-acked row stayed acked.
        assert next(r for r in store.alerts if r["alert_id"] == already["alert_id"])["acknowledged_at"] is not None

    def test_surface_session_renders_header_and_stamps(
        self, store: _FakeStore, conn: _FakeConn
    ) -> None:
        store.add_alert(severity=SEVERITY_M3, ticker="AAPL")
        store.add_alert(severity=SEVERITY_M2, ticker="MSFT", alert_type="materiality_m2")
        out = surface_unread_at_session_start(conn)
        assert "Unread alerts" in out
        assert "1 M-3 / 1 M-2" in out
        assert "AAPL" in out and "MSFT" in out
        # Both rows stamped.
        for r in store.alerts:
            assert r["claude_session_pushed_at"] is not None

    def test_surface_session_empty(
        self, store: _FakeStore, conn: _FakeConn
    ) -> None:
        assert "No unread alerts" in surface_unread_at_session_start(conn)

    def test_render_alerts_list_formatting(
        self, store: _FakeStore, conn: _FakeConn
    ) -> None:
        store.add_alert(severity=SEVERITY_M3, ticker="AAPL")
        rows = list_unread_alerts(conn)
        out = render_alerts_list(rows)
        assert "/alerts" in out and "M-3" in out and "/ack" in out


# --------------------------------------------------------------------------- #
# system_health markdown                                                      #
# --------------------------------------------------------------------------- #


class TestSystemHealth:
    def test_renders_all_sections(
        self, store: _FakeStore, conn: _FakeConn
    ) -> None:
        # Seed: one degraded MCP, one M-3 in queue, one M-2 unread.
        store.system_errors.append(
            {
                "timestamp_at": _dt.datetime(2026, 4, 28, tzinfo=_dt.timezone.utc),
                "source": "mcp__broker__get_positions",
                "error_type": "auth_failed",
                "error_detail": "token expired",
                "retry_count": 2,
                "escalated_to_alert": True,
                "blocked_decision": "daily_refresh_full_watchlist",
                "resolved_at": None,
                "resolution": None,
            }
        )
        store.add_alert(severity=SEVERITY_M3)
        store.add_alert(severity=SEVERITY_M2, alert_type="materiality_m2")
        out = render_system_health(conn)
        assert "Degraded MCPs" in out
        assert "mcp__broker__get_positions" in out
        assert "Queued recoveries" in out
        assert "Active push-alert backlog" in out
        assert "Disputed catalog" in out
        assert "system_errors" in out
        # Counts surfaced.
        assert "Unread M-3: **1**" in out
        assert "Unread M-2: **1**" in out

    def test_healthy_system_renders_clean(
        self, store: _FakeStore, conn: _FakeConn
    ) -> None:
        out = render_system_health(conn)
        assert "_None — all MCPs healthy._" in out
        assert "Unread M-3: **0**" in out
        assert "_No errors in the last 7 days._" in out
