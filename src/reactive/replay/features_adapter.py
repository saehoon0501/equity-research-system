"""Replay Harness: the daily feature adapter (assemble inputs + drive the core).

Task 2.1. Given a symbol, an as-of day ``D``, and an injected ``DataPort``, this
leaf assembles the point-in-time daily feature inputs the LANDED
``src.reactive.features.compute_features`` consumes — the ticker daily OHLC bars
(also the ATR input), the SPY daily adjusted-close series, and the risk-free
yield — and **drives** ``compute_features`` to produce the ``FeatureSet``. It
owns NO feature math and NO overlay logic: it imports and calls the landed core,
which in turn reuses the landed overlay/indicator leaves (design §"Drive the
landed cores; never reimplement", R3.3).

The two point-in-time correctness rules this adapter DOES own (everything the
``compute_features`` core cannot know about as-of-instant semantics):

  - **Point-in-time (R3.1 / R4.1):** only data timestamped ≤ ``D`` feeds the
    features. The ``DataPort`` is the injection seam (R9.2); in production the
    landed ``data_client`` already bounds its fetch by ``end``, but a fixture
    port may return canned rows ignoring the window — so the adapter re-applies
    the ≤ ``D`` bound itself (defense-in-depth; no look-ahead can slip through).

  - **As-of split rule (R4.2 / design "Core algorithms #4"):** the ``DataPort``
    serves ``adjusted=false`` raw bars. The adapter split-adjusts the
    feature-window prices for splits with ex-date (Polygon ``execution_date``)
    ≤ ``D`` ONLY: an in-window pre-``D`` split is applied to the bars STRICTLY
    BEFORE its ex-date (so momentum stays continuous across the split); a split
    with ex-date > ``D`` is NEVER applied (it has not occurred as-of ``D`` —
    applying it would be look-ahead, distinct from blanket ``adjusted=true``
    which folds in post-``D`` splits = leakage). The FULL OHLC of a pre-ex-date
    bar is divided by the split factor (not just the close) so the ATR computed
    by ``compute_features`` over the same bars does not spike across the split.

Pure leaf (P1 / design §Dependency direction `types → data_client →
features_adapter → simulator`): imports the landed feature core + the owned
``DataPort`` protocol only — no httpx, no MCP, no DB, no consumer-spec import,
no per-day caching (the cross-candidate cache of design line 103 is a later
cost optimization the simulator owns; this adapter stays a stateless pure
function so the determinism contract R9.1 holds). It does NOT import
``data_client`` — it works against the injected ``DataPort`` protocol.

Source of truth: requirements.md R3 AC 3.1, R4 AC 4.2; design.md "Core
algorithms #4 (as-of split rule)", the `features_adapter` File-Structure /
Components-table (row 170) / Traceability (row 155) references.

Requirements: 3.1, 4.2.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from src.reactive.features import FeatureFailure, FeatureSet, compute_features
from src.reactive.replay.types import DataPort

# The longest reused feature lookback (252d) is owned by `compute_features`'s own
# `insufficient_history` gate — the adapter pulls a generous lookback window and
# lets the core enforce length. A year of trading days ≈ 252; pull ~400 calendar
# days back so 252 trading bars are present even across weekends/holidays.
_LOOKBACK_CALENDAR_DAYS = 400

# Polygon/Massive aggregate `t` is epoch MILLIseconds (mirrors data_client's
# `_MS_PER_S`); the adapter derives a bar's UTC date from it locally rather than
# importing data_client's private bounding helper (dependency stays on the
# DataPort protocol, not the concrete client).
_MS_PER_S = 1_000


def _bar_date(row: dict) -> date | None:
    """The UTC calendar date of a raw wire bar from its epoch-ms ``t``.

    Returns ``None`` when ``t`` is absent (the caller keeps such a row — it
    cannot be proven to be after ``D``; mirrors data_client's bounding policy).
    """
    t = row.get("t")
    if t is None:
        return None
    return datetime.fromtimestamp(t / _MS_PER_S, tz=timezone.utc).date()


def _bound_bars_as_of(rows: list[dict], as_of: date) -> list[dict]:
    """Drop raw wire bars dated strictly after ``as_of`` (R3.1/R4.1 — inclusive).

    Bars missing ``t`` are kept (cannot prove they are future), matching
    data_client's ``_bound_rows_by_ts`` policy. The boundary is INCLUSIVE: a bar
    dated exactly ``as_of`` feeds the features (the as-of instant's own row).
    """
    kept: list[dict] = []
    for row in rows:
        d = _bar_date(row)
        if d is None or d <= as_of:
            kept.append(row)
    return kept


def _split_factor(split: dict) -> float | None:
    """The price-division factor of a Polygon split row (``split_to/split_from``).

    A 1→4 forward split (``split_from=1, split_to=4``) has factor 4: pre-ex-date
    prices divide by 4 to align with the post-split level. Returns ``None`` for a
    malformed/zero split (skipped rather than raising — the adapter never raises).
    """
    try:
        sf = float(split["split_from"])
        st = float(split["split_to"])
    except (KeyError, TypeError, ValueError):
        return None
    if sf == 0.0 or st == 0.0:
        return None
    return st / sf


def _apply_as_of_splits(
    rows: list[dict], splits: list[dict], as_of: date
) -> list[dict]:
    """Split-adjust raw wire bars for ex-dates ≤ ``as_of`` only (R4.2, algo #4).

    For each split with ``execution_date`` ≤ ``as_of``, every bar dated STRICTLY
    BEFORE the ex-date has its full OHLC (open/high/low/close — NOT volume)
    divided by the split factor, so the series is continuous across the split
    and the ATR over the same bars does not spike. Splits with ex-date > ``as_of``
    are never applied (look-ahead). Cumulative across multiple in-window splits
    (each earlier bar is divided by every later in-window split's factor).
    """
    # Collect the applicable (ex-date ≤ as_of) split factors, keyed by ex-date.
    applicable: list[tuple[date, float]] = []
    for split in splits:
        ex_raw = split.get("execution_date")
        if ex_raw is None:
            continue
        ex_date = date.fromisoformat(str(ex_raw)[:10])
        if ex_date > as_of:
            continue  # post-D split: never applied (no look-ahead).
        factor = _split_factor(split)
        if factor is None or factor == 1.0:
            continue
        applicable.append((ex_date, factor))

    if not applicable:
        return [dict(r) for r in rows]

    adjusted: list[dict] = []
    for row in rows:
        new_row = dict(row)
        bar_d = _bar_date(row)
        if bar_d is not None:
            # Divide by every in-window split whose ex-date is strictly AFTER this
            # bar (i.e. this bar predates the split → it is on the old price scale).
            cum = 1.0
            for ex_date, factor in applicable:
                if bar_d < ex_date:
                    cum *= factor
            if cum != 1.0:
                for key in ("o", "h", "l", "c"):
                    if new_row.get(key) is not None:
                        new_row[key] = float(new_row[key]) / cum
        adjusted.append(new_row)
    return adjusted


def _to_bar(row: dict) -> dict:
    """Map a raw Massive-wire bar (``t/o/h/l/c/v``) to the landed `Bar` shape.

    `compute_features` (and the `_atr`/`closes` indicator leaves it drives)
    consumes the `src.reactive.types.Bar` TypedDict (``open/high/low/close/
    volume``). `Bar` is structurally a dict, so a plain dict with these keys
    satisfies it. Missing keys map to ``None`` — the core's Gate-0 bar-key
    validation owns the degenerate-features verdict (it never raises).
    """
    return {
        "open": row.get("o"),
        "high": row.get("h"),
        "low": row.get("l"),
        "close": row.get("c"),
        "volume": row.get("v"),
    }


def compute_daily_features(
    symbol: str,
    as_of_day: str,
    data_port: DataPort,
    *,
    atr_period: int = 14,
) -> FeatureSet | FeatureFailure:
    """Assemble the as-of-``D`` daily feature inputs and DRIVE `compute_features`.

    Pulls the ticker's raw (``adjusted=false``) daily bars + corporate-actions
    splits and SPY's raw daily closes via the injected ``DataPort``, enforces the
    point-in-time bound (≤ ``D``), applies the as-of split rule (ex-date ≤ ``D``
    only) to the ticker bars, maps the raw wire bars to the landed `Bar` shape,
    and drives the landed `compute_features`. Returns whatever the core returns
    (a `FeatureSet`, or a `FeatureFailure` for insufficient-history / degenerate
    features — passed through verbatim; the adapter never raises on a failure).

    Args:
        symbol: the ticker to compute features for.
        as_of_day: the as-of day ``D`` (ISO date) — the point-in-time instant.
        data_port: the injected `DataPort` (real `data_client` in prod, a fixture
            in tests — the R9.2 isolation seam).
        atr_period: ATR lookback forwarded to `compute_features` (default 14).

    Returns:
        `FeatureSet | FeatureFailure` — exactly the landed core's return.
    """
    as_of = date.fromisoformat(as_of_day[:10])
    start = (as_of - timedelta(days=_LOOKBACK_CALENDAR_DAYS)).isoformat()

    # --- Ticker leg: raw bars, point-in-time bound, as-of split-adjusted ----
    raw_ticker = data_port.fetch_daily_bars(symbol, start, as_of_day)
    raw_ticker = _bound_bars_as_of(list(raw_ticker), as_of)
    actions = data_port.fetch_corporate_actions(symbol, start, as_of_day)
    splits = list(actions.get("splits", [])) if actions else []
    raw_ticker = _apply_as_of_splits(raw_ticker, splits, as_of)
    ticker_bars = [_to_bar(r) for r in raw_ticker]

    # --- SPY leg: raw adjusted-close series, same point-in-time + split rule -
    raw_spy = data_port.fetch_daily_bars("SPY", start, as_of_day)
    raw_spy = _bound_bars_as_of(list(raw_spy), as_of)
    spy_actions = data_port.fetch_corporate_actions("SPY", start, as_of_day)
    spy_splits = list(spy_actions.get("splits", [])) if spy_actions else []
    raw_spy = _apply_as_of_splits(raw_spy, spy_splits, as_of)
    spy_close = [r["c"] for r in raw_spy if r.get("c") is not None]

    # --- Risk-free yield as-of D (a tactical-gate feature input) -------------
    rf_yield_pct = data_port.fetch_rf_yield(as_of_day)

    # --- DRIVE the landed core (never reimplement; R3.3) --------------------
    return compute_features(ticker_bars, spy_close, rf_yield_pct, atr_period)
