"""Symbol metadata cache + ticker mapping (Task 3.1).

Source of truth: ``.kiro/specs/broker-cfd-adapter/design.md`` — the ``symbol_cache``
Components row (Domain layer), the Architecture map (``symbol_cache <- gate_client
+ mappers``), the "symbol_cache & mappers (summary)" section, and "Performance &
Scalability" (<=10/call detail batching, ~45 calls for 441 names, freshness +
refresh-on-validation-miss). Requirements: 3.3, 4.1, 4.2, 5.1.

Layer position (``models -> config -> gate_client -> {mappers, symbol_cache} ->
validation -> ...``): the cache sits in the Domain layer alongside ``mappers``. It
turns the venue's two symbol feeds into one authoritative, ticker-keyed metadata
map for the validation layer (Task 3.2) to interpret.

What this owns
--------------
1. **Build the tradable-symbol set** from the PUBLIC ``GET /tradfi/symbols``
   (``symbol``, ``category_id``, ``status`` open/closed, ``trade_mode``,
   ``next_open_time``, ``price_precision``), restricted to the US-stock CFD
   category (``config.US_STOCK_CATEGORY_ID`` = 2). Anything outside that category
   is EXCLUDED from the set; a ``resolve`` of an out-of-category ticker returns a
   structured ``OUT_OF_CATEGORY`` rejection (Req 4.2).

2. **Ticker-only identity** (Req 4.1). The cache key is the US ticker
   (``symbol``); the venue free-text ``symbol_desc`` is NEVER read for identity
   (the reference warns ``AAPL`` -> "American Airlines"). ``parse_symbols_detail``
   (mappers) already declines to read ``symbol_desc``; the cache never indexes by
   it either.

3. **Per-symbol enforcement metadata** from the AUTHENTICATED
   ``GET /tradfi/symbols/detail?symbols=`` (leverage, min/max order volume, swap
   rates, price precision), fetched in batches of <=10 tickers (the venue caps the
   ``symbols`` query at 10 — design Performance & Scalability). The public session
   status (open/closed + ``next_open_time``) is MERGED with the authenticated
   detail into ONE :class:`models.SymbolInfo` per ticker — detail rows carry no
   session-status field, so the merge backfills it from the universe feed.

4. **Swap/financing rates** (Req 3.3) and **leverage + trade_mode** (Req 5.1) are
   held on each ``SymbolInfo`` so the validation layer can reject disabled /
   sub-floor-leverage / disallowed-trade_mode names. This module only SURFACES the
   data — it performs NO rejection of tradability/leverage itself (5.1 is 3.2's
   job); the only rejections it emits are identity-level: unknown ticker
   (``UNKNOWN_SYMBOL``) and out-of-category (``OUT_OF_CATEGORY``).

Freshness / refresh policy (design Performance & Scalability)
-------------------------------------------------------------
The cache is built lazily on first use and then served from memory (a freshness
window: a cached, present ticker is returned without a venue round-trip, so an
order does not re-fetch the whole universe per call). On a validation MISS — a
ticker not in the cache — the cache REFRESHES once from the venue and retries,
so a newly-listed (or newly-relevant) name resolves and ``trade_mode`` / session
status stay current. A still-absent ticker after the refresh is a structured
``UNKNOWN_SYMBOL`` rejection. (Consistency note: a now-disabled symbol can be
stale within the freshness window; the refresh-on-miss bounds it and validation
re-reads ``trade_mode``/status from the merged record.)

Dependency injection (testability)
----------------------------------
``SymbolCache`` is constructed with a ``gate_client`` (the transport module — see
Task 2.1; exposes ``request(method, path, *, params=, transport=, ...)`` returning
a structured ``TransportResult`` / ``TransportError``) and an optional
``transport`` passed through on every call. Production passes ``transport=None``
(real httpx transport); tests inject the Task 1.4 ``make_mock_transport(...)`` so
the cache is unit-testable with NO live venue and NO direct httpx import. The cache
reuses ``mappers.parse_symbols_detail`` to turn raw detail JSON into typed
``SymbolInfo`` — it never re-parses the venue strings itself.
"""

from __future__ import annotations

from typing import Any, Optional, Union

# Layers above symbol_cache in the dependency direction
# (config -> gate_client -> {mappers, symbol_cache}). Imported BY NAME (production
# posture: broker dir on sys.path[0]). NOTE: httpx is NOT imported here — the
# transport seam belongs to gate_client; the cache only forwards an injected
# ``transport`` through it.
import config as _config
import mappers as _mappers
from models import RejectionCode, RejectionReason, SymbolInfo

# Venue caps the /tradfi/symbols/detail ``symbols`` query at 10 tickers
# (design Performance & Scalability: <=10/call). Keep the batch bound here.
_DETAIL_BATCH_SIZE = 10

# Venue endpoints (the cache's two reads). The signed-transport layer prefixes
# /api/v4 and adds auth; the cache names only the /tradfi paths.
_SYMBOLS_PATH = "/tradfi/symbols"
_SYMBOLS_DETAIL_PATH = "/tradfi/symbols/detail"


# Resolution result: a typed SymbolInfo on success, else a structured rejection.
ResolveResult = Union[SymbolInfo, RejectionReason]


class SymbolCache:
    """Ticker-keyed, US-stock-category-restricted symbol metadata cache.

    Construct with an injected ``gate_client`` (transport module) and an optional
    ``transport`` forwarded on every venue call (tests pass the Task 1.4 mock;
    production passes ``None``). The ``us_stock_category_id`` defaults to the venue
    constant in ``config`` (= 2) and is comparable as the venue reports it
    (``category_id`` is an int in the feed; ``SymbolInfo.category`` is its string).
    """

    def __init__(
        self,
        *,
        gate_client: Any,
        transport: Any = None,
        us_stock_category_id: int = _config.US_STOCK_CATEGORY_ID,
    ) -> None:
        self._gate_client = gate_client
        self._transport = transport
        self._category_id = us_stock_category_id
        # Ticker (US symbol) -> merged SymbolInfo. None until first build.
        self._by_ticker: Optional[dict[str, SymbolInfo]] = None

    # ------------------------------------------------------------------ #
    # Public API.
    # ------------------------------------------------------------------ #

    def resolve(self, ticker: str) -> ResolveResult:
        """Resolve a US ticker to its merged :class:`SymbolInfo`, or a structured
        rejection.

        Identity is the US TICKER only (Req 4.1) — the free-text description is
        never an identity key, so a description string never resolves. Flow:

        1. Ensure the cache is built (lazy first build).
        2. Hit on a CACHED ticker -> return it (freshness window: no refetch).
        3. MISS -> refresh once from the venue and retry (refresh-on-miss).
        4. Still absent after refresh -> ``UNKNOWN_SYMBOL`` rejection.

        An out-of-category ticker that exists at the venue but in another category
        is reported as ``OUT_OF_CATEGORY`` (it never enters the in-category set).
        A transport failure during a (re)build surfaces as a structured rejection
        rather than raising (conservative posture).
        """
        # 1) Lazy build (or surface a build failure structurally).
        if self._by_ticker is None:
            err = self._build()
            if err is not None:
                return err

        assert self._by_ticker is not None  # built above (or returned)

        # 2) Cache hit on a present, in-category ticker.
        hit = self._by_ticker.get(ticker)
        if hit is not None:
            return hit

        # 3) Refresh-on-miss: rebuild once and retry (the venue may now list it,
        #    or a stale set may have dropped it).
        err = self._build()
        if err is not None:
            return err
        hit = self._by_ticker.get(ticker)
        if hit is not None:
            return hit

        # 4) Still absent. Distinguish out-of-category (exists, wrong category)
        #    from genuinely unknown so the caller gets the precise reason (Req 4.2
        #    vs an unknown ticker). The category check needs the raw universe.
        return self._absent_reason(ticker)

    def tradable_symbols(self) -> list[SymbolInfo]:
        """Return every in-category tradable symbol (the validated set).

        Builds the cache on first use. On a build failure returns an empty list
        (the conservative posture — never a partially-authenticated set); callers
        that need the failure detail use :meth:`resolve`.
        """
        if self._by_ticker is None:
            err = self._build()
            if err is not None:
                return []
        assert self._by_ticker is not None
        return list(self._by_ticker.values())

    def refresh(self) -> Optional[RejectionReason]:
        """Force a rebuild from the venue. Returns ``None`` on success, else a
        structured rejection describing the transport/build failure."""
        return self._build()

    # ------------------------------------------------------------------ #
    # Internals.
    # ------------------------------------------------------------------ #

    def _build(self) -> Optional[RejectionReason]:
        """Rebuild the ticker->SymbolInfo map from the venue's two feeds.

        Public ``/tradfi/symbols`` -> session status + category filter; then the
        authenticated ``/tradfi/symbols/detail`` (batched <=10) for the in-category
        tickers -> enforcement metadata; merge into one SymbolInfo per ticker.
        Returns ``None`` on success, else a structured rejection (the cache is left
        unbuilt / unchanged so the next call retries).
        """
        universe = self._fetch_universe()
        if isinstance(universe, RejectionReason):
            return universe

        # Restrict to the US-stock CFD category (Req 4.2) by the venue category_id.
        in_category = [
            row for row in universe if self._is_in_category(row.get("category_id"))
        ]

        # Public session status keyed by ticker (open/closed + next_open_time),
        # for the merge. Identity is the ticker (Req 4.1) — symbol_desc untouched.
        session_by_ticker: dict[str, dict[str, Any]] = {
            str(row["symbol"]): row for row in in_category
        }
        tickers = list(session_by_ticker.keys())

        # Authenticated detail, batched <=10 (design Performance & Scalability).
        detail_rows = self._fetch_detail_batched(tickers)
        if isinstance(detail_rows, RejectionReason):
            return detail_rows

        # Parse detail rows into typed SymbolInfo via mappers (no re-parsing here).
        # mappers.parse_symbols_detail defaults status="unknown"/next_open_time=None
        # for detail rows; we overwrite both from the public session feed.
        parsed = _mappers.parse_symbols_detail(detail_rows)

        merged: dict[str, SymbolInfo] = {}
        for info in parsed:
            session = session_by_ticker.get(info.ticker)
            if session is None:
                # A detail row for a ticker not in the in-category universe —
                # exclude it (defensive; the request only asked for in-category).
                continue
            merged[info.ticker] = self._merge_session(info, session)

        self._by_ticker = merged
        return None

    def _fetch_universe(self) -> Union[list[dict[str, Any]], RejectionReason]:
        """GET the public ``/tradfi/symbols`` universe (raw venue rows)."""
        outcome = self._gate_client.request(
            "GET", _SYMBOLS_PATH, transport=self._transport
        )
        if not getattr(outcome, "ok", False):
            return self._transport_rejection(outcome, what="symbols universe")
        data = outcome.data
        if not isinstance(data, list):
            return RejectionReason(
                code=RejectionCode.UNKNOWN_SYMBOL,
                message="venue /tradfi/symbols returned a non-list payload",
            )
        return data

    def _fetch_detail_batched(
        self, tickers: list[str]
    ) -> Union[list[dict[str, Any]], RejectionReason]:
        """GET ``/tradfi/symbols/detail`` for ``tickers`` in batches of <=10.

        Returns the concatenated raw detail rows, or a structured rejection if any
        batch fails (the cache must not be built from a partially-authenticated
        set).
        """
        rows: list[dict[str, Any]] = []
        for start in range(0, len(tickers), _DETAIL_BATCH_SIZE):
            batch = tickers[start : start + _DETAIL_BATCH_SIZE]
            if not batch:
                continue
            outcome = self._gate_client.request(
                "GET",
                _SYMBOLS_DETAIL_PATH,
                params={"symbols": ",".join(batch)},
                transport=self._transport,
            )
            if not getattr(outcome, "ok", False):
                return self._transport_rejection(outcome, what="symbols detail")
            data = outcome.data
            if not isinstance(data, list):
                return RejectionReason(
                    code=RejectionCode.UNKNOWN_SYMBOL,
                    message="venue /tradfi/symbols/detail returned a non-list payload",
                )
            rows.extend(data)
        return rows

    def _absent_reason(self, ticker: str) -> RejectionReason:
        """Classify a ticker absent from the in-category cache after a refresh.

        If the venue universe lists it under a DIFFERENT category, it is
        ``OUT_OF_CATEGORY`` (Req 4.2); otherwise it is genuinely ``UNKNOWN_SYMBOL``.
        A transient transport failure here degrades to ``UNKNOWN_SYMBOL`` (the
        conservative outcome — we do not assert a category we could not read).
        """
        universe = self._fetch_universe()
        if isinstance(universe, RejectionReason):
            return RejectionReason(
                code=RejectionCode.UNKNOWN_SYMBOL,
                message=f"symbol {ticker!r} is not in the validated tradable set",
            )
        for row in universe:
            if str(row.get("symbol")) == ticker:
                # Exists at the venue but not in our in-category set -> wrong
                # category (Req 4.2). Identity matched on the TICKER, not the desc.
                return RejectionReason(
                    code=RejectionCode.OUT_OF_CATEGORY,
                    message=(
                        f"symbol {ticker!r} is category "
                        f"{row.get('category_id')!r}, outside the US-stock CFD "
                        f"category ({self._category_id})"
                    ),
                )
        return RejectionReason(
            code=RejectionCode.UNKNOWN_SYMBOL,
            message=f"symbol {ticker!r} is not in the venue tradable universe",
        )

    def _is_in_category(self, category_id: Any) -> bool:
        """True iff the venue ``category_id`` is the in-scope US-stock category.

        The venue reports ``category_id`` as an int (fixtures) — compare as int,
        tolerating a string form defensively.
        """
        try:
            return int(category_id) == int(self._category_id)
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _merge_session(info: SymbolInfo, session: dict[str, Any]) -> SymbolInfo:
        """Merge the public session status/next_open_time onto a detail-derived
        SymbolInfo. The detail parser cannot know the session (detail rows carry
        no status), so the authoritative open/closed + next_open_time come from the
        public ``/tradfi/symbols`` feed (design merge note)."""
        status = session.get("status")
        next_open = session.get("next_open_time")
        return SymbolInfo(
            ticker=info.ticker,
            category=info.category,
            leverage=info.leverage,
            trade_mode=info.trade_mode,
            min_order_volume=info.min_order_volume,
            max_order_volume=info.max_order_volume,
            price_precision=info.price_precision,
            buy_swap_rate=info.buy_swap_rate,
            sell_swap_rate=info.sell_swap_rate,
            status=str(status) if status is not None else info.status,
            next_open_time=(
                int(next_open) if next_open is not None else info.next_open_time
            ),
        )

    @staticmethod
    def _transport_rejection(outcome: Any, *, what: str) -> RejectionReason:
        """Turn a structured transport error into a conservative rejection (the
        cache never raises; it refuses to build an unauthenticated/partial set)."""
        error_class = getattr(outcome, "error_class", "transport_error")
        detail = getattr(outcome, "error", "") or ""
        return RejectionReason(
            code=RejectionCode.UNKNOWN_SYMBOL,
            message=f"could not load {what} ({error_class}): {detail}".rstrip(),
        )


__all__ = ["SymbolCache", "ResolveResult"]
