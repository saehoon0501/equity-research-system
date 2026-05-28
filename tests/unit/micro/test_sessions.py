"""Tests for trading-session classification, filtering, and after-hours annotation."""

from __future__ import annotations

from src.micro import sessions
from src.micro.signal_model import compute_signal


def _bar(ts, c, h=None, l=None, v=1000):
    h = c if h is None else h
    l = c if l is None else l
    return {"ts": ts, "open": c, "high": h, "low": l, "close": c, "volume": v}


def test_classify_et_sessions_edt():
    # 2026-05-26 is EDT (UTC-4): ET = UTC-4.
    assert sessions.classify("2026-05-26T13:00:00Z") == "pre"      # 09:00 ET
    assert sessions.classify("2026-05-26T13:30:00Z") == "regular"  # 09:30 ET open
    assert sessions.classify("2026-05-26T19:59:00Z") == "regular"  # 15:59 ET
    assert sessions.classify("2026-05-26T20:00:00Z") == "after"    # 16:00 ET
    assert sessions.classify("2026-05-26T23:59:00Z") == "after"    # 19:59 ET
    assert sessions.classify("2026-05-26T03:00:00Z") == "closed"   # 23:00 ET prev
    assert sessions.classify(None) == "unknown"


def test_filter_session_regular_drops_pre_and_after():
    bars = [
        _bar("2026-05-26T13:00:00Z", 100),  # pre
        _bar("2026-05-26T14:00:00Z", 101),  # regular
        _bar("2026-05-26T19:59:00Z", 102),  # regular
        _bar("2026-05-26T21:00:00Z", 110),  # after
    ]
    reg = sessions.filter_session(bars, "regular")
    assert [b["close"] for b in reg] == [101, 102]
    ext = sessions.filter_session(bars, "extended")
    assert len(ext) == 4  # pre+regular+after all kept
    assert len(sessions.filter_session(bars, "all")) == 4


def test_filter_session_regular_keeps_only_latest_day():
    # Two days of bars; "regular" must keep ONLY the latest day's regular session
    # — a multi-day fetch must never be stitched across the overnight gap.
    day1 = [_bar("2026-05-26T14:00:00Z", 100), _bar("2026-05-26T19:59:00Z", 102)]  # regular
    day1_after = [_bar("2026-05-26T21:00:00Z", 105)]                                # after
    day2 = [_bar("2026-05-27T14:00:00Z", 110), _bar("2026-05-27T19:59:00Z", 115)]  # regular
    bars = day1 + day1_after + day2
    reg = sessions.filter_session(bars, "regular")
    # Only the May 27 regular bars; day1 regular and day1 after-hours are dropped.
    assert [b["close"] for b in reg] == [110, 115]


def test_filter_session_no_timestamps_returns_all():
    # ts-less bars can't be classified -> not filtered (keeps existing callers working).
    bars = [{"close": 100, "high": 100, "low": 100, "volume": 1}, {"close": 101, "high": 101, "low": 101, "volume": 1}]
    assert len(sessions.filter_session(bars, "regular")) == 2


def test_after_hours_annotation():
    bars = [
        _bar("2026-05-26T19:59:00Z", 100.0),  # regular close
        _bar("2026-05-26T21:00:00Z", 102.0),  # after
        _bar("2026-05-26T23:59:00Z", 102.0),  # after last
    ]
    ann = sessions.after_hours_annotation(bars)
    assert ann["regular_close"] == 100.0
    assert ann["after_hours_last"] == 102.0
    assert ann["change_pct"] == 2.0
    assert ann["after_hours_bars"] == 2
    # No after-hours bars -> None.
    assert sessions.after_hours_annotation([_bar("2026-05-26T14:00:00Z", 100)]) is None


def _ts_utc(minute_of_day: int) -> str:
    return f"2026-05-26T{minute_of_day // 60:02d}:{minute_of_day % 60:02d}:00Z"


def test_compute_signal_default_excludes_after_hours_and_flags_it():
    # Regular session (13:30->19:59 UTC = 09:30->15:59 ET) trends DOWN to a
    # close, then a big UP after-hours spike (20:00 UTC = 16:00 ET).
    reg = [_bar(_ts_utc(13 * 60 + 30 + i), 200.0 - i * 0.1) for i in range(390)]
    aft = [_bar(_ts_utc(20 * 60 + i), 175.0 + i * 0.05) for i in range(60)]
    out = compute_signal(reg + aft, prior=None, daily_atr=10.0)  # default session='regular'
    assert out["session"]["scope"] == "regular"
    assert out["session"]["after_hours"] is not None      # flagged, not silently used
    assert out["session"]["bars_used"] == 390             # only regular bars
    # Reference is the regular close (161.1), not the after-hours spike level.
    assert out["reference_price"] < 170
    # Including after-hours ('all') uses more bars and a higher reference.
    out_all = compute_signal(reg + aft, prior=None, daily_atr=10.0, session="all")
    assert out_all["session"]["bars_used"] == 450
    assert out_all["reference_price"] > out["reference_price"]
