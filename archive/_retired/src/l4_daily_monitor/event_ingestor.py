"""Event ingestor — pulls events per ticker per day for L4 materiality classification.

Per v3 spec Section 4.5 Q1 (lines 460-483) the daily refresh log captures
all events the LLM judge considered for a (ticker, date) tuple. This module
sweeps all source classes the playbook calls for and emits a uniform
``Event`` stream for the classifier.

Source classes (Section 4.5 + Section 4.6 catalysts):

1. Earnings call remarks       (mcp__market_data + earnings calendar)
2. Macro prints                (mcp__fred + mcp__market_data news)
3. Filings                     (mcp__edgar)
4. Smart-money signals         (mcp__edgar 13F/13G/13D)
5. Sector rotation / peer moves(mcp__market_data)
6. Regulatory / litigation     (mcp__market_data news)
7. Product / capex / M&A       (mcp__market_data news)
8. Credit-event / spread blowouts (FRED EBP series; e.g., BAMLH0A0HYM2)

The ingestor is **adapter-driven** (mirroring src/mode_classifier/adapters.py
pattern). Production code wires up :class:`DefaultEventAdapter` which calls
the underlying MCP servers; tests inject a :class:`StubEventAdapter`.

Each ingested event carries a verbatim quote — the LLM judge cannot fire
M-2/M-3 without one (Section 6 Q1 audit-trail lock).

Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
    Section 4.5 Q1 (daily_refresh_log schema)
    Section 6 Q1 (verbatim-quote enforcement)
"""

from __future__ import annotations

import datetime as _dt
import logging
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

_LOG = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Event types — closed set for v0.1; matches EVENT_TYPE_AGENT_LOOKUP keys     #
# --------------------------------------------------------------------------- #


EVENT_TYPE_EARNINGS_CALL: str = "earnings_call_remark"
EVENT_TYPE_EARNINGS_MISS: str = "earnings_miss"
EVENT_TYPE_GUIDANCE_CUT: str = "guidance_cut"
EVENT_TYPE_EPS_SURPRISE: str = "eps_surprise"
EVENT_TYPE_MACRO_PRINT: str = "macro_print"
EVENT_TYPE_FILING_8K: str = "filing_8k"
EVENT_TYPE_FILING_10Q: str = "filing_10q"
EVENT_TYPE_FILING_10K: str = "filing_10k"
EVENT_TYPE_13F: str = "13f_filing"
EVENT_TYPE_13D: str = "13d_filing"
EVENT_TYPE_13G: str = "13g_filing"
EVENT_TYPE_SMART_MONEY: str = "smart_money_signal"
EVENT_TYPE_SECTOR_ROTATION: str = "sector_rotation"
EVENT_TYPE_PEER_MOVE: str = "peer_move"
EVENT_TYPE_REGULATORY: str = "regulatory"
EVENT_TYPE_LITIGATION: str = "litigation"
EVENT_TYPE_PRODUCT: str = "product_announcement"
EVENT_TYPE_CAPEX: str = "capex_announcement"
EVENT_TYPE_MA: str = "ma_announcement"
EVENT_TYPE_CREDIT_EVENT: str = "credit_event"
EVENT_TYPE_SPREAD_BLOWOUT: str = "spread_blowout"


# --------------------------------------------------------------------------- #
# Event dataclass                                                             #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Event:
    """One event for the LLM judge to classify.

    Per Section 4.5 Q1 daily_refresh_log.events JSONB schema:
        {type, source_id, timestamp, raw_text, verbatim_quote, ...}

    Attributes:
        type: One of the EVENT_TYPE_* constants. Drives the
            EVENT_TYPE_AGENT_LOOKUP fallback table when judge
            confidence < 0.6 (Section 4.5 Q2).
        source_id: Provenance pointer into evidence_index or external doc
            store (e.g., "edgar:0001234567-25-000001").
        timestamp: When the event was published / occurred (UTC).
        raw_text: Full raw text supplied to the LLM judge as evidence.
        verbatim_quote: A pinpoint substring of raw_text that the
            classifier MUST cite to fire M-2/M-3 (Section 6 Q1).
            Empty string is allowed at ingest; classifier will reject
            and re-default to M-1 if no quote is materialized.
        metadata: Free-form JSONB-bound source-specific extras (filing
            type, FRED series id, ticker pair, etc.).
    """

    type: str
    source_id: str
    timestamp: _dt.datetime
    raw_text: str
    verbatim_quote: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_jsonb(self) -> dict[str, Any]:
        """Serialize for daily_refresh_log.events JSONB array."""
        return {
            "type": self.type,
            "source_id": self.source_id,
            "timestamp": self.timestamp.isoformat(),
            "raw_text": self.raw_text,
            "verbatim_quote": self.verbatim_quote,
            "metadata": dict(self.metadata),
        }


# --------------------------------------------------------------------------- #
# Adapter Protocol                                                            #
# --------------------------------------------------------------------------- #


@runtime_checkable
class EventAdapter(Protocol):
    """Decouples the ingestor from direct MCP-tool invocation.

    Production: :class:`DefaultEventAdapter` (calls mcp__market_data,
    mcp__edgar, mcp__fred via Claude Code's MCP surface).
    Tests: :class:`StubEventAdapter` returns canned events.
    """

    def fetch_news(self, ticker: str, date: _dt.date) -> list[Event]: ...
    def fetch_filings(self, ticker: str, date: _dt.date) -> list[Event]: ...
    def fetch_smart_money(self, ticker: str, date: _dt.date) -> list[Event]: ...
    def fetch_macro(self, date: _dt.date) -> list[Event]: ...
    def fetch_credit(self, date: _dt.date) -> list[Event]: ...
    def fetch_sector_peers(self, ticker: str, date: _dt.date) -> list[Event]: ...
    def fetch_earnings(self, ticker: str, date: _dt.date) -> list[Event]: ...


# --------------------------------------------------------------------------- #
# Default adapter — production wiring (best-effort, degrades gracefully)      #
# --------------------------------------------------------------------------- #


class DefaultEventAdapter:
    """Production adapter that calls the MCP-wrapped data sources.

    Per BUILD_LOG.md decision 1 (Path A, Claude Code is the runtime), the
    Python module cannot directly invoke MCP servers — those are spawned
    by Claude Code per ``.mcp.json``. The Python entry point therefore
    expects to be called from a subagent that already has the MCP tools
    exposed; the adapter receives pre-fetched JSON via the ``data_layer``
    helpers (or, in v0.1, falls back to the direct yfinance/EDGAR/FRED
    libraries the MCP servers wrap).

    For modules outside Claude Code (e.g., backtest harness, drift
    detector), the adapter degrades to empty lists and logs a warning;
    the caller is responsible for hydrating events from a snapshot.
    """

    def __init__(self, data_layer: Optional[Any] = None) -> None:
        self._data_layer = data_layer

    def fetch_news(self, ticker: str, date: _dt.date) -> list[Event]:
        if self._data_layer is None:
            _LOG.debug("DefaultEventAdapter.fetch_news: no data_layer; returning [].")
            return []
        try:
            news = self._data_layer.get_news(ticker=ticker, date=date)
        except Exception as exc:  # pragma: no cover - defensive
            _LOG.warning("fetch_news failed for %s on %s: %s", ticker, date, exc)
            return []
        return [_news_to_event(n) for n in (news or [])]

    def fetch_filings(self, ticker: str, date: _dt.date) -> list[Event]:
        if self._data_layer is None:
            return []
        try:
            filings = self._data_layer.get_filings(ticker=ticker, date=date)
        except Exception as exc:  # pragma: no cover - defensive
            _LOG.warning("fetch_filings failed for %s on %s: %s", ticker, date, exc)
            return []
        return [_filing_to_event(f) for f in (filings or [])]

    def fetch_smart_money(self, ticker: str, date: _dt.date) -> list[Event]:
        if self._data_layer is None:
            return []
        try:
            sm = self._data_layer.get_smart_money(ticker=ticker, date=date)
        except Exception as exc:  # pragma: no cover - defensive
            _LOG.warning("fetch_smart_money failed for %s on %s: %s", ticker, date, exc)
            return []
        return [_smart_money_to_event(s) for s in (sm or [])]

    def fetch_macro(self, date: _dt.date) -> list[Event]:
        if self._data_layer is None:
            return []
        try:
            prints = self._data_layer.get_macro_prints(date=date)
        except Exception as exc:  # pragma: no cover - defensive
            _LOG.warning("fetch_macro failed on %s: %s", date, exc)
            return []
        return [_macro_to_event(p) for p in (prints or [])]

    def fetch_credit(self, date: _dt.date) -> list[Event]:
        if self._data_layer is None:
            return []
        try:
            # FRED EBP series + spread blowout detection.
            credit_events = self._data_layer.get_credit_events(date=date)
        except Exception as exc:  # pragma: no cover - defensive
            _LOG.warning("fetch_credit failed on %s: %s", date, exc)
            return []
        return [_credit_to_event(c) for c in (credit_events or [])]

    def fetch_sector_peers(self, ticker: str, date: _dt.date) -> list[Event]:
        if self._data_layer is None:
            return []
        try:
            sec = self._data_layer.get_sector_signals(ticker=ticker, date=date)
        except Exception as exc:  # pragma: no cover - defensive
            _LOG.warning("fetch_sector_peers failed for %s on %s: %s", ticker, date, exc)
            return []
        return [_sector_to_event(s) for s in (sec or [])]

    def fetch_earnings(self, ticker: str, date: _dt.date) -> list[Event]:
        if self._data_layer is None:
            return []
        try:
            calls = self._data_layer.get_earnings_calls(ticker=ticker, date=date)
        except Exception as exc:  # pragma: no cover - defensive
            _LOG.warning("fetch_earnings failed for %s on %s: %s", ticker, date, exc)
            return []
        return [_earnings_to_event(e) for e in (calls or [])]


# --------------------------------------------------------------------------- #
# Source-specific normalizers                                                 #
# --------------------------------------------------------------------------- #


def _news_to_event(n: dict[str, Any]) -> Event:
    """Map a market_data news payload to an Event.

    Heuristic event_type assignment based on news category tags. Falls
    back to ``regulatory`` (defensive) when no category matches — the
    LLM judge does the final routing call regardless.
    """
    category = (n.get("category") or "").lower()
    if "earnings" in category:
        etype = EVENT_TYPE_EARNINGS_CALL
    elif "litigat" in category or "lawsuit" in category:
        etype = EVENT_TYPE_LITIGATION
    elif "regulat" in category or "antitrust" in category:
        etype = EVENT_TYPE_REGULATORY
    elif "product" in category or "launch" in category:
        etype = EVENT_TYPE_PRODUCT
    elif "capex" in category or "investment" in category:
        etype = EVENT_TYPE_CAPEX
    elif "merger" in category or "acquisition" in category or "m&a" in category:
        etype = EVENT_TYPE_MA
    elif "sector" in category:
        etype = EVENT_TYPE_SECTOR_ROTATION
    elif "credit" in category or "spread" in category:
        etype = EVENT_TYPE_CREDIT_EVENT
    else:
        etype = EVENT_TYPE_REGULATORY
    return Event(
        type=etype,
        source_id=str(n.get("id", n.get("url", "news:unknown"))),
        timestamp=_to_dt(n.get("timestamp") or n.get("published_at")),
        raw_text=str(n.get("body", n.get("headline", ""))),
        verbatim_quote=str(n.get("verbatim_quote", n.get("headline", ""))),
        metadata={"category": category, "source": "market_data.news"},
    )


def _filing_to_event(f: dict[str, Any]) -> Event:
    """Map an EDGAR filing payload to an Event."""
    form = (f.get("form_type") or "").lower()
    if form.startswith("8-k"):
        etype = EVENT_TYPE_FILING_8K
    elif form.startswith("10-q"):
        etype = EVENT_TYPE_FILING_10Q
    elif form.startswith("10-k"):
        etype = EVENT_TYPE_FILING_10K
    elif form.startswith("13f"):
        etype = EVENT_TYPE_13F
    elif form.startswith("13d"):
        etype = EVENT_TYPE_13D
    elif form.startswith("13g"):
        etype = EVENT_TYPE_13G
    else:
        etype = EVENT_TYPE_FILING_8K  # conservative default
    return Event(
        type=etype,
        source_id=str(f.get("accession_number", "edgar:unknown")),
        timestamp=_to_dt(f.get("filed_at")),
        raw_text=str(f.get("text", "")),
        verbatim_quote=str(f.get("verbatim_quote", "")),
        metadata={"form_type": form, "source": "edgar"},
    )


def _smart_money_to_event(s: dict[str, Any]) -> Event:
    """Map a 13F/13G/13D smart-money signal to an Event."""
    form = (s.get("form_type") or "").lower()
    if form.startswith("13f"):
        etype = EVENT_TYPE_13F
    elif form.startswith("13d"):
        etype = EVENT_TYPE_13D
    elif form.startswith("13g"):
        etype = EVENT_TYPE_13G
    else:
        etype = EVENT_TYPE_SMART_MONEY
    return Event(
        type=etype,
        source_id=str(s.get("accession_number", "edgar:smart-money")),
        timestamp=_to_dt(s.get("filed_at")),
        raw_text=str(s.get("text", "")),
        verbatim_quote=str(s.get("verbatim_quote", "")),
        metadata={
            "form_type": form,
            "filer": s.get("filer"),
            "delta_shares": s.get("delta_shares"),
            "source": "edgar.smart_money",
        },
    )


def _macro_to_event(p: dict[str, Any]) -> Event:
    """Map a FRED macro print to an Event."""
    return Event(
        type=EVENT_TYPE_MACRO_PRINT,
        source_id=str(p.get("series_id", "fred:unknown")),
        timestamp=_to_dt(p.get("release_date")),
        raw_text=str(p.get("text", "")),
        verbatim_quote=str(p.get("verbatim_quote", "")),
        metadata={
            "series_id": p.get("series_id"),
            "value": p.get("value"),
            "source": "fred",
        },
    )


def _credit_to_event(c: dict[str, Any]) -> Event:
    """Map a credit-event / spread-blowout payload to an Event.

    Heuristic: any payload tagged ``spread_blowout=True`` becomes the
    blowout type; everything else maps to a generic credit event.
    """
    if c.get("spread_blowout") is True:
        etype = EVENT_TYPE_SPREAD_BLOWOUT
    else:
        etype = EVENT_TYPE_CREDIT_EVENT
    return Event(
        type=etype,
        source_id=str(c.get("series_id", "fred:credit")),
        timestamp=_to_dt(c.get("release_date")),
        raw_text=str(c.get("text", "")),
        verbatim_quote=str(c.get("verbatim_quote", "")),
        metadata={
            "series_id": c.get("series_id"),
            "spread_bps": c.get("spread_bps"),
            "source": "fred.ebp",
        },
    )


def _sector_to_event(s: dict[str, Any]) -> Event:
    """Map a sector-rotation / peer-move payload to an Event."""
    if s.get("kind") == "peer_move":
        etype = EVENT_TYPE_PEER_MOVE
    else:
        etype = EVENT_TYPE_SECTOR_ROTATION
    return Event(
        type=etype,
        source_id=str(s.get("id", "sector:unknown")),
        timestamp=_to_dt(s.get("timestamp")),
        raw_text=str(s.get("text", "")),
        verbatim_quote=str(s.get("verbatim_quote", "")),
        metadata={"source": "market_data.sector"},
    )


def _earnings_to_event(e: dict[str, Any]) -> Event:
    """Map an earnings-call/EPS-surprise/guidance-cut payload to an Event."""
    kind = (e.get("kind") or "").lower()
    if "miss" in kind:
        etype = EVENT_TYPE_EARNINGS_MISS
    elif "guidance" in kind:
        etype = EVENT_TYPE_GUIDANCE_CUT
    elif "surprise" in kind:
        etype = EVENT_TYPE_EPS_SURPRISE
    else:
        etype = EVENT_TYPE_EARNINGS_CALL
    return Event(
        type=etype,
        source_id=str(e.get("id", "earnings:unknown")),
        timestamp=_to_dt(e.get("timestamp")),
        raw_text=str(e.get("text", "")),
        verbatim_quote=str(e.get("verbatim_quote", "")),
        metadata={
            "kind": kind,
            "fiscal_period": e.get("fiscal_period"),
            "source": "market_data.earnings",
        },
    )


def _to_dt(v: Any) -> _dt.datetime:
    """Best-effort ISO-string → datetime; defaults to UTC midnight today.

    Always returns an aware UTC datetime. Naive input (datetime without
    tzinfo, or ISO strings missing a tz suffix) is coerced to UTC — the
    L4 daily-monitor pipeline assumes timestamptz throughout, and a leak
    of naive datetimes here would crash downstream `now - ts` math.
    """
    if isinstance(v, _dt.datetime):
        if v.tzinfo is None:
            return v.replace(tzinfo=_dt.timezone.utc)
        return v
    if isinstance(v, _dt.date):
        return _dt.datetime.combine(v, _dt.time(0, 0), tzinfo=_dt.timezone.utc)
    if isinstance(v, str) and v:
        try:
            parsed = _dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
        if parsed is not None:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=_dt.timezone.utc)
            return parsed
    return _dt.datetime.now(_dt.timezone.utc)


# --------------------------------------------------------------------------- #
# Public entry                                                                #
# --------------------------------------------------------------------------- #


def ingest_events(
    ticker: str,
    date: _dt.date,
    adapter: Optional[EventAdapter] = None,
) -> list[Event]:
    """Pull all event classes for (ticker, date).

    Per Section 4.5 Q1: returns a flat list of Event objects covering
    earnings, macro, filings, smart-money, sector/peers, regulatory/
    litigation, product/capex/M&A, credit-event/spread-blowout. Order is
    not specified — downstream classifier will sort by timestamp.

    Args:
        ticker: Equity ticker (e.g., 'NVDA').
        date: Trading date to scan.
        adapter: Optional :class:`EventAdapter` (defaults to
            :class:`DefaultEventAdapter` with no data_layer — i.e.,
            empty results unless the caller wires one up).

    Returns:
        Flat list of :class:`Event` (possibly empty).
    """
    if adapter is None:
        adapter = DefaultEventAdapter()

    events: list[Event] = []
    events.extend(adapter.fetch_earnings(ticker, date))
    events.extend(adapter.fetch_macro(date))
    events.extend(adapter.fetch_filings(ticker, date))
    events.extend(adapter.fetch_smart_money(ticker, date))
    events.extend(adapter.fetch_sector_peers(ticker, date))
    events.extend(adapter.fetch_news(ticker, date))
    events.extend(adapter.fetch_credit(date))

    # Sort by timestamp for deterministic LLM input ordering.
    events.sort(key=lambda e: e.timestamp)
    _LOG.info(
        "ingest_events(%s, %s): %d events across %d types",
        ticker, date, len(events), len({e.type for e in events}),
    )
    return events
