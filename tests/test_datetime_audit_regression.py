"""Regression tests for the datetime-handling audit (Phase 4 follow-up).

Pre-existing audits caught HMAC type-coercion + transaction boundary +
idempotency + error-swallowing bugs. This audit applies the same lens to
naive-vs-aware datetime confusion, UTC-vs-local-time, and time-window
arithmetic. Each test below reproduces a real bug class found in the
audit and locks in the fix.

Bug classes covered:
    - HIGH: alert_channels queue_processor — `created_at` returned as
            tz-less string crashes `now >= eligible_at` comparison.
    - HIGH: counterfactual_veto cli — naive ISO ``--trigger-at`` arg
            crashes inside cooling-off Layer 1.
    - HIGH: l4 daily-monitor _to_dt — naive datetime leak via tz-less
            ISO string.
    - CRITICAL: audit_trail _isoformat — sign-time naive datetime
            produced ``...Z`` form, but DB roundtrip returns aware UTC
            serialized as ``...+00:00``; canonical bytes mismatched.
"""

from __future__ import annotations

import datetime as _dt
import json
from datetime import timezone

import pytest

from src.alert_channels.queue_processor import _is_eligible_now
from src.audit_trail.hmac_verify import (
    _isoformat,
    canonical_payload_dict,
)


# ---------------------------------------------------------------------------
# Bug 1: alert_channels.queue_processor — backoff math with tz-less strings
# ---------------------------------------------------------------------------


def test_email_retry_backoff_eligibility_aware_clock() -> None:
    """1m / 5m / 15m schedule (Phase 4 Q9) using aware UTC clocks."""
    created_at = _dt.datetime(2026, 4, 29, 12, 0, tzinfo=timezone.utc)

    # attempts=0 → eligible immediately
    assert _is_eligible_now(
        attempts=0,
        created_at=created_at,
        now=created_at,
    )

    # attempts=1 → eligible at created_at + 60s (the 1m wait)
    assert not _is_eligible_now(
        attempts=1,
        created_at=created_at,
        now=created_at + _dt.timedelta(seconds=59),
    )
    assert _is_eligible_now(
        attempts=1,
        created_at=created_at,
        now=created_at + _dt.timedelta(seconds=60),
    )

    # attempts=2 → eligible at created_at + 60 + 300 = 360s
    assert not _is_eligible_now(
        attempts=2,
        created_at=created_at,
        now=created_at + _dt.timedelta(seconds=359),
    )
    assert _is_eligible_now(
        attempts=2,
        created_at=created_at,
        now=created_at + _dt.timedelta(seconds=360),
    )

    # attempts=3 → eligible at created_at + 60 + 300 + 900 = 1260s
    assert _is_eligible_now(
        attempts=3,
        created_at=created_at,
        now=created_at + _dt.timedelta(seconds=1260),
    )


def test_alert_channels_pending_rows_coerce_naive_to_utc() -> None:
    """`_select_pending_email_rows` must coerce naive timestamps to aware UTC.

    Regression: pre-fix, a row with `created_at` returned as a tz-less
    ISO string would yield a naive datetime, then `_is_eligible_now`
    raised `TypeError: can't subtract offset-naive and offset-aware
    datetimes` on aware-UTC `now`.
    """
    from src.alert_channels.queue_processor import _select_pending_email_rows

    class _FakeCursor:
        def __init__(self, rows):
            self._rows = rows

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, *a, **k):
            return None

        def fetchall(self):
            return self._rows

    class _FakeConn:
        def __init__(self, rows):
            self._rows = rows

        def cursor(self):
            return _FakeCursor(self._rows)

    import uuid as _uuid

    naive_str = "2026-04-29T12:00:00"  # no tz suffix
    fake_row = (
        str(_uuid.uuid4()),  # alert_id
        3,                    # severity
        "kill_criterion",     # alert_type
        "AAPL",               # ticker
        "summary text",       # summary
        None,                 # payload
        None,                 # drill_link_recommendation_id
        0,                    # email_send_attempts
        naive_str,            # created_at — naive
    )
    pending = _select_pending_email_rows(_FakeConn([fake_row]))
    assert len(pending) == 1
    _alert, created_at = pending[0]
    assert created_at.tzinfo is not None
    assert created_at.utcoffset() == _dt.timedelta(0)


# ---------------------------------------------------------------------------
# Bug 2 (counterfactual_veto cooling-off): tests removed 2026-05-23 with
# src/counterfactual_veto/ deletion (mig 041) per docs/superpowers/specs/
# 2026-05-23-eval-loop-deletion-design.md.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Bug 3: l4 daily-monitor _to_dt — naive datetime leak
# ---------------------------------------------------------------------------


def test_l4_to_dt_coerces_naive_iso_to_utc() -> None:
    """`event_ingestor._to_dt` must always return aware UTC."""
    from src.l4_daily_monitor.event_ingestor import _to_dt

    # Naive ISO string
    out = _to_dt("2026-04-29T12:00:00")
    assert out.tzinfo is not None
    assert out.utcoffset() == _dt.timedelta(0)

    # Naive datetime instance
    out2 = _to_dt(_dt.datetime(2026, 4, 29, 12, 0))
    assert out2.tzinfo is not None
    assert out2.utcoffset() == _dt.timedelta(0)

    # Aware datetime passes through
    aware = _dt.datetime(2026, 4, 29, 12, 0, tzinfo=timezone.utc)
    out3 = _to_dt(aware)
    assert out3 == aware

    # Z-suffixed ISO
    out4 = _to_dt("2026-04-29T12:00:00Z")
    assert out4.tzinfo is not None
    assert out4.utcoffset() == _dt.timedelta(0)

    # date object — already produced aware UTC
    out5 = _to_dt(_dt.date(2026, 4, 29))
    assert out5.tzinfo is not None


# ---------------------------------------------------------------------------
# Bug 4: HMAC _isoformat — sign-time naive vs DB-roundtrip aware mismatch
# ---------------------------------------------------------------------------


def test_hmac_isoformat_naive_matches_aware_utc_roundtrip() -> None:
    """The CRITICAL bug: sign-time naive datetime must canonicalize to
    the same bytes as the aware-UTC datetime returned by Postgres after
    a `timestamptz` round-trip.

    Pre-fix: naive → "2026-04-29T12:00:00Z"
             aware → "2026-04-29T12:00:00+00:00"
             (canonical mismatch → HMAC verification fails)
    Post-fix: both → "2026-04-29T12:00:00+00:00"
    """
    naive = _dt.datetime(2026, 4, 29, 12, 0, 0)
    aware_roundtripped = _dt.datetime(2026, 4, 29, 12, 0, 0, tzinfo=timezone.utc)

    assert _isoformat(naive) == _isoformat(aware_roundtripped)


def test_hmac_canonical_payload_naive_vs_aware_match() -> None:
    """End-to-end: full canonical-payload bytes are byte-identical for
    a naive sign-time datetime and the aware-UTC version returned by
    Postgres after a `timestamptz` round-trip."""
    naive = _dt.datetime(2026, 4, 29, 12, 0, 0)
    aware = _dt.datetime(2026, 4, 29, 12, 0, 0, tzinfo=timezone.utc)

    payload_naive = {"created_at": naive, "k": 1}
    payload_aware = {"created_at": aware, "k": 1}

    assert canonical_payload_dict(payload_naive) == canonical_payload_dict(
        payload_aware
    )


def test_hmac_isoformat_non_utc_aware_normalized_to_utc() -> None:
    """Defense in depth: if a producer somehow signs an aware datetime
    in a non-UTC zone, the canonical form must still match the UTC
    roundtrip from the DB."""
    eastern = timezone(_dt.timedelta(hours=-4))
    aware_eastern = _dt.datetime(2026, 4, 29, 8, 0, 0, tzinfo=eastern)
    aware_utc = _dt.datetime(2026, 4, 29, 12, 0, 0, tzinfo=timezone.utc)
    # 08:00 ET == 12:00 UTC
    assert _isoformat(aware_eastern) == _isoformat(aware_utc)


# ---------------------------------------------------------------------------
# Bug 5: cadence floor — date subtraction (180/120/60 day boundaries)
# ---------------------------------------------------------------------------


def test_cadence_floor_180_120_60_day_boundary() -> None:
    """B 180d / B' 120d / C 60d boundaries computed with date math."""
    from src.premortem_scheduler.cadence import cadence_status

    # Mode B — 180d
    last = _dt.date(2025, 11, 1)
    today_179 = (last + _dt.timedelta(days=179)).isoformat()
    today_180 = (last + _dt.timedelta(days=180)).isoformat()
    s = cadence_status(
        "AAPL", "B", as_of=today_179, last_premortem_date=last
    )
    assert s.due is False
    s = cadence_status(
        "AAPL", "B", as_of=today_180, last_premortem_date=last
    )
    assert s.due is True

    # Mode B' — 120d
    s = cadence_status(
        "AAPL",
        "B_prime",
        as_of=(last + _dt.timedelta(days=119)).isoformat(),
        last_premortem_date=last,
    )
    assert s.due is False
    s = cadence_status(
        "AAPL",
        "B_prime",
        as_of=(last + _dt.timedelta(days=120)).isoformat(),
        last_premortem_date=last,
    )
    assert s.due is True

    # Mode C — 60d
    s = cadence_status(
        "AAPL",
        "C",
        as_of=(last + _dt.timedelta(days=59)).isoformat(),
        last_premortem_date=last,
    )
    assert s.due is False
    s = cadence_status(
        "AAPL",
        "C",
        as_of=(last + _dt.timedelta(days=60)).isoformat(),
        last_premortem_date=last,
    )
    assert s.due is True
