"""US-equity trading-session classification for /micro bar series.

Classifies each bar by its Eastern-Time clock and filters a bar series to a
session scope. Default scope is REGULAR (09:30–16:00 ET): after-hours moves are
thin-volume and prone to revert at the next open, and silently blending them
into the indicator window can flip the directional read (observed on MU
2026-05-26: a bearish regular session + a +2% after-hours pop netted to a long
lean). After-hours is surfaced as a flagged annotation instead.

ET conversion is DST-aware via ``zoneinfo`` when available, with a month-based
EDT/EST fallback. Bars without a parseable ``ts`` classify as "unknown"; a series
with NO classifiable timestamps is returned unfiltered (we can't tell sessions,
so we don't drop anything).
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Sequence

try:  # stdlib 3.9+; needs system tzdata (present on macOS/Linux)
    from zoneinfo import ZoneInfo

    _ET: Any = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - fallback when tzdata is unavailable
    _ET = None

# ET clock boundaries, in minutes-since-midnight.
_PRE_OPEN = 4 * 60  # 04:00
_REGULAR_OPEN = 9 * 60 + 30  # 09:30
_REGULAR_CLOSE = 16 * 60  # 16:00
_AFTER_CLOSE = 20 * 60  # 20:00


def _et_minutes(ts: Any) -> int | None:
    if not ts:
        return None
    try:
        d = _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=_dt.timezone.utc)
    if _ET is not None:
        d = d.astimezone(_ET)
    else:
        # Rough US DST: EDT (UTC-4) Mar–Oct, EST (UTC-5) otherwise.
        offset = -4 if 3 <= d.astimezone(_dt.timezone.utc).month <= 10 else -5
        d = d.astimezone(_dt.timezone.utc) + _dt.timedelta(hours=offset)
    return d.hour * 60 + d.minute


def classify(ts: Any) -> str:
    """One of: 'pre', 'regular', 'after', 'closed', 'unknown'."""
    m = _et_minutes(ts)
    if m is None:
        return "unknown"
    if _PRE_OPEN <= m < _REGULAR_OPEN:
        return "pre"
    if _REGULAR_OPEN <= m < _REGULAR_CLOSE:
        return "regular"
    if _REGULAR_CLOSE <= m < _AFTER_CLOSE:
        return "after"
    return "closed"


def _et_date(ts: Any) -> str | None:
    """ET calendar date (YYYY-MM-DD) for a bar timestamp, or None."""
    if not ts:
        return None
    try:
        d = _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=_dt.timezone.utc)
    if _ET is not None:
        d = d.astimezone(_ET)
    else:
        offset = -4 if 3 <= d.astimezone(_dt.timezone.utc).month <= 10 else -5
        d = d.astimezone(_dt.timezone.utc) + _dt.timedelta(hours=offset)
    return d.date().isoformat()


def filter_session(bars: Sequence[dict], session: str = "regular") -> list[dict]:
    """Filter bars to a session scope: 'regular' | 'extended' | 'all'.

    'extended' keeps pre+regular+after (drops overnight). 'regular' keeps ONLY
    the LATEST regular session's bars — a multi-day fetch (lookback >1 session)
    must not be silently stitched across the overnight gap, which contaminates
    the session VWAP/opening-range and breaks cross-asset beta over the gap.
    If NO bar has a classifiable timestamp, the series is returned unchanged.
    """
    if session == "all":
        return list(bars)
    classified = [(b, classify(b.get("ts"))) for b in bars]
    if not any(c != "unknown" for _, c in classified):
        return list(bars)  # no timestamps -> cannot determine sessions
    keep = {"pre", "regular", "after"} if session == "extended" else {"regular"}
    in_scope = [b for b, c in classified if c in keep]
    if session == "regular":
        # Restrict to the LATEST regular session's date — a multi-day fetch
        # otherwise stitches two sessions across the overnight gap.
        latest = None
        for b in in_scope:
            d = _et_date(b.get("ts"))
            if d is not None and (latest is None or d > latest):
                latest = d
        if latest is not None:
            in_scope = [b for b in in_scope if _et_date(b.get("ts")) == latest]
    return in_scope


def after_hours_annotation(bars: Sequence[dict]) -> dict | None:
    """Summarize the after-hours move relative to the regular close, or None.

    Returns {regular_close, after_hours_last, change_pct, after_hours_bars}.
    None when there are no after-hours bars (or no timestamps).
    """
    aft_all = [b for b in bars if classify(b.get("ts")) == "after"]
    if not aft_all:
        return None
    # Latest after-hours session only (avoid stitching multiple days' AH bars).
    latest_aft_date = max((_et_date(b.get("ts")) for b in aft_all if _et_date(b.get("ts"))), default=None)
    aft = [b for b in aft_all if _et_date(b.get("ts")) == latest_aft_date] if latest_aft_date else aft_all
    # Regular close that PAIRS with that after-hours date (same calendar day).
    reg = [b for b in bars if classify(b.get("ts")) == "regular"
           and _et_date(b.get("ts")) == latest_aft_date]
    try:
        aft_last = float(aft[-1].get("close"))
    except (TypeError, ValueError):
        return None
    reg_close = None
    if reg:
        try:
            reg_close = float(reg[-1].get("close"))
        except (TypeError, ValueError):
            reg_close = None
    change_pct = None
    if reg_close:
        change_pct = round((aft_last - reg_close) / reg_close * 100.0, 3)
    return {
        "regular_close": reg_close,
        "after_hours_last": aft_last,
        "change_pct": change_pct,
        "after_hours_bars": len(aft),
        "note": "after-hours is thin-volume and may revert at the open; excluded "
        "from the signal by default (session='regular')",
    }
