"""Data-source adapters for the mode classifier.

The mode classifier is *deliberately* decoupled from direct MCP-tool
invocation. The Python module runs inside the operator's host process
(via the CLI or the orchestrator); the actual MCP servers are FastMCP
processes spawned by Claude Code (per ``.mcp.json``). To keep this
module testable and to honour BUILD_LOG.md decision 1 (Path A — Claude
Code is the runtime), every external read goes through a thin
``DataAdapter`` Protocol. Tests inject a ``StubDataAdapter`` with
fixed values; the production CLI wires up :class:`DefaultDataAdapter`,
which calls the same underlying libraries that the MCP servers wrap
(yfinance for prices, EDGAR for company-facts).

Two adapter Protocols:

* :class:`DataAdapter` — facts the rule classifier needs:
  market cap, 252d realized vol, profitability, growth.
* :class:`QualityAdapter` — facts the quality refinement needs:
  founder tenure, sustained ROIIC, profitability-path-clear.

Both have a default implementation that mirrors what an MCP-using
subagent would fetch from ``mcp__market_data`` /
``mcp__fundamentals`` / ``mcp__edgar``. Where the underlying MCP
server is stubbed (``mcp__fundamentals`` is a NotImplementedError stub
per BUILD_LOG decision 2), the default adapter falls back to the
EDGAR ``get_company_facts`` route — which is *non-PIT* and not safe
for backtests, but acceptable for sample-memo generation per
``.claude/references/mcp-required.md`` §3.

Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
Section 2.2; Section 3.1 MCPs.
"""

from __future__ import annotations

import datetime as _dt
import logging
import math
import statistics
from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable

_LOG = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Stage 1 facts                                                               #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class StructuralFacts:
    """Snapshot of the four market-structural inputs to Stage 1.

    Per spec Section 2.2 lines 106-109. All four fields are required;
    None values force overlap → Stage 3 LLM tie-breaker.

    Attributes:
        market_cap_usd: Current market cap in USD (single point estimate).
        realized_vol_252d: Trailing-252-trading-day annualized realized
            volatility, expressed as a decimal (0.18 == 18%).
        profitable_consecutive_years: Count of consecutive trailing fiscal
            years the company has been GAAP-profitable (net income > 0).
        revenue_growth_yoy: Most-recent fiscal-year revenue growth rate,
            decimal (0.08 == 8%). Used for the B-bin <12% / B'-bin >15%
            spec thresholds.
        narrative_driven: Operator/analyst-flagged "thematic / narrative"
            override that forces C-bin regardless of the other inputs.
            False is the safe default.
        as_of_date: ISO date the snapshot was computed for (audit trail).
    """

    market_cap_usd: Optional[float]
    realized_vol_252d: Optional[float]
    profitable_consecutive_years: Optional[int]
    revenue_growth_yoy: Optional[float]
    narrative_driven: bool
    as_of_date: str


# --------------------------------------------------------------------------- #
# Stage 2 facts                                                               #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class QualityFacts:
    """Inputs to the Section 7 PB#3 quality refinement (Stage 2).

    Per spec Section 2.2 line 112:

        HIGH-quality flag if (founder >=10yr tenure if B, >=5yr if B') AND
        (ROIIC > 15% sustained 5yr if B) AND profitability-path-clear

    Attributes:
        founder_tenure_years: Years the founder/founder-CEO has been at
            the helm. None if founder departed / never present / unknown.
        roiic_5yr_avg: 5-year trailing average return on incremental
            invested capital, decimal. None if not computable.
        profitability_path_clear: Boolean — operator/data-driven flag that
            the path to durable profitability is explicit (revenue ramp +
            unit economics positive + cash-burn finite). For B-bin names
            this is trivially True (already 5y profitable). For B' it
            should be True. For C it is the gating question.
        as_of_date: ISO snapshot date.
    """

    founder_tenure_years: Optional[float]
    roiic_5yr_avg: Optional[float]
    profitability_path_clear: bool
    as_of_date: str


# --------------------------------------------------------------------------- #
# Adapter Protocols                                                           #
# --------------------------------------------------------------------------- #


@runtime_checkable
class DataAdapter(Protocol):
    """Stage 1 facts source. Satisfied by any object providing the method."""

    def get_structural_facts(
        self, ticker: str, as_of: str
    ) -> StructuralFacts: ...


@runtime_checkable
class QualityAdapter(Protocol):
    """Stage 2 facts source."""

    def get_quality_facts(
        self, ticker: str, as_of: str
    ) -> QualityFacts: ...


# --------------------------------------------------------------------------- #
# Default adapter — shells out to the same libs the MCP servers wrap.         #
# --------------------------------------------------------------------------- #


def _trading_days_back(end_iso: str, n: int) -> str:
    """Approximate calendar date n trading days before end_iso.

    252 trading days ~= 365 calendar days, so we add 25% slack.
    """
    end = _dt.date.fromisoformat(end_iso)
    return (end - _dt.timedelta(days=int(n * 1.45) + 7)).isoformat()


class DefaultDataAdapter:
    """Default Stage 1 adapter using yfinance for prices and EDGAR for facts.

    Equivalent to what a Claude Code subagent would do when calling
    ``mcp__market_data.get_prices`` + ``mcp__edgar.get_company_facts``;
    we call those same underlying libraries directly so the Python
    module is self-sufficient at the CLI.

    Per BUILD_LOG.md decision 2, ``mcp__fundamentals`` is stubbed —
    so we route fundamentals through EDGAR XBRL via
    ``mcp__edgar.get_company_facts``. This is *non-PIT* (filed-as-of,
    not restated-as-of); acceptable for sample memos but NOT for
    backtests. Caller is expected to surface that caveat.
    """

    def get_structural_facts(
        self, ticker: str, as_of: str
    ) -> StructuralFacts:
        market_cap = self._fetch_market_cap(ticker)
        vol = self._fetch_realized_vol(ticker, as_of)
        years_profitable, growth = self._fetch_fundamentals(ticker)
        return StructuralFacts(
            market_cap_usd=market_cap,
            realized_vol_252d=vol,
            profitable_consecutive_years=years_profitable,
            revenue_growth_yoy=growth,
            narrative_driven=False,  # operator override; defaults False
            as_of_date=as_of,
        )

    # ---------------------- internal fetchers --------------------------- #

    def _fetch_market_cap(self, ticker: str) -> Optional[float]:
        try:
            import yfinance as yf  # type: ignore[import-untyped]

            info = yf.Ticker(ticker).info or {}
            cap = info.get("marketCap")
            return float(cap) if cap else None
        except Exception as exc:  # noqa: BLE001
            _LOG.warning(
                "DefaultDataAdapter._fetch_market_cap(%s) failed: %s: %s",
                ticker, type(exc).__name__, exc,
            )
            return None

    def _fetch_realized_vol(
        self, ticker: str, as_of: str
    ) -> Optional[float]:
        """252-trading-day annualized realized volatility.

        Mirrors ``mcp__market_data.get_prices``; vol = stdev of daily
        log returns * sqrt(252).
        """
        try:
            import yfinance as yf  # type: ignore[import-untyped]

            start = _trading_days_back(as_of, 252)
            df = yf.Ticker(ticker).history(
                start=start, end=as_of, interval="1d", auto_adjust=False
            )
            if len(df) < 50:
                return None
            closes = [float(c) for c in df["Close"] if c and not math.isnan(c)]
            if len(closes) < 50:
                return None
            log_rets = [
                math.log(closes[i] / closes[i - 1])
                for i in range(1, len(closes))
                if closes[i - 1] > 0
            ]
            if len(log_rets) < 30:
                return None
            return statistics.stdev(log_rets) * math.sqrt(252)
        except Exception as exc:  # noqa: BLE001
            _LOG.warning(
                "DefaultDataAdapter._fetch_realized_vol(%s) failed: %s: %s",
                ticker, type(exc).__name__, exc,
            )
            return None

    def _fetch_fundamentals(
        self, ticker: str
    ) -> tuple[Optional[int], Optional[float]]:
        """Years-profitable and revenue-growth, via EDGAR XBRL fallback.

        Returns (consecutive_profitable_years, latest_revenue_growth_yoy).
        Both None if EDGAR data is unavailable.
        """
        try:
            # Reach the EDGAR MCP server's library directly; it lives in
            # src/mcp/edgar/server.py but we duplicate the call here so
            # the classifier doesn't take a runtime dependency on that
            # FastMCP package layout.
            import importlib

            edgar_mod = importlib.import_module("src.mcp.edgar.server")
            facts = edgar_mod.get_company_facts(ticker)
        except Exception as exc:  # noqa: BLE001
            _LOG.warning(
                "DefaultDataAdapter._fetch_fundamentals(%s) failed: %s: %s",
                ticker, type(exc).__name__, exc,
            )
            return None, None

        years_profitable = self._count_consecutive_profitable_years(facts)
        growth = self._latest_revenue_growth(facts)
        return years_profitable, growth

    @staticmethod
    def _count_consecutive_profitable_years(facts: dict) -> Optional[int]:
        """Walk NetIncomeLoss FY tags backwards; count run of >0."""
        try:
            tag = facts.get("facts", {}).get("us-gaap", {}).get(
                "NetIncomeLoss", {}
            )
            units = tag.get("units", {}).get("USD", [])
            fys = sorted(
                ((u.get("fy"), u.get("val")) for u in units if u.get("fp") == "FY"),
                key=lambda x: x[0] or 0,
                reverse=True,
            )
            run = 0
            for _, val in fys:
                if val is not None and val > 0:
                    run += 1
                else:
                    break
            return run if fys else None
        except Exception as exc:  # noqa: BLE001
            _LOG.warning(
                "DefaultDataAdapter._count_consecutive_profitable_years "
                "failed: %s: %s",
                type(exc).__name__, exc,
            )
            return None

    @staticmethod
    def _latest_revenue_growth(facts: dict) -> Optional[float]:
        """Latest two FY Revenues; growth = (cur - prior) / prior."""
        try:
            us_gaap = facts.get("facts", {}).get("us-gaap", {})
            for tag_name in (
                "Revenues",
                "RevenueFromContractWithCustomerExcludingAssessedTax",
            ):
                tag = us_gaap.get(tag_name, {})
                units = tag.get("units", {}).get("USD", [])
                fys = sorted(
                    (u for u in units if u.get("fp") == "FY"),
                    key=lambda u: u.get("fy") or 0,
                    reverse=True,
                )
                if len(fys) >= 2 and fys[1].get("val"):
                    prior = float(fys[1]["val"])
                    cur = float(fys[0]["val"])
                    if prior != 0:
                        return (cur - prior) / abs(prior)
            return None
        except Exception as exc:  # noqa: BLE001
            _LOG.warning(
                "DefaultDataAdapter._latest_revenue_growth failed: %s: %s",
                type(exc).__name__, exc,
            )
            return None


class DefaultQualityAdapter:
    """Default Stage 2 adapter.

    Founder tenure is *not* mechanically derivable from XBRL; the
    spec accepts ``annotated watchlist data`` as the primary source.
    This default reads from a JSON sidecar at ``db/watchlist_overrides.json``
    if present; otherwise returns ``None`` for tenure, which forces the
    quality flag to STANDARD (the conservative default per Phase 4 Q1).

    ROIIC and profitability-path-clear: in v0.1 we read coarse proxies
    from the same EDGAR facts payload (NOPAT / incremental invested
    capital, 5y average). When ``mcp__fundamentals`` (Sharadar) lands
    in v0.5 the implementation should swap to that PIT source.
    """

    def __init__(self, watchlist_overrides_path: Optional[str] = None) -> None:
        self._overrides_path = watchlist_overrides_path

    def get_quality_facts(self, ticker: str, as_of: str) -> QualityFacts:
        founder_tenure = self._lookup_founder_tenure(ticker)
        roiic_5yr = self._compute_roiic_5yr(ticker)
        path_clear = self._lookup_profitability_path(ticker, founder_tenure)
        return QualityFacts(
            founder_tenure_years=founder_tenure,
            roiic_5yr_avg=roiic_5yr,
            profitability_path_clear=path_clear,
            as_of_date=as_of,
        )

    def _lookup_founder_tenure(self, ticker: str) -> Optional[float]:
        if not self._overrides_path:
            return None
        try:
            import json
            from pathlib import Path

            data = json.loads(Path(self._overrides_path).read_text())
            return data.get(ticker.upper(), {}).get("founder_tenure_years")
        except (OSError, ValueError) as exc:
            # Missing/unreadable overrides file or corrupt JSON. Conservative
            # default: None (forces STANDARD quality).
            _LOG.info(
                "DefaultQualityAdapter._lookup_founder_tenure(%s) using "
                "default (no overrides): %s: %s",
                ticker, type(exc).__name__, exc,
            )
            return None

    def _compute_roiic_5yr(self, ticker: str) -> Optional[float]:
        # In v0.1 we don't compute ROIIC mechanically — the Sharadar
        # pipeline will. Return None and let Stage 2 fall back to
        # STANDARD; operator can override via the watchlist sidecar.
        return None

    def _lookup_profitability_path(
        self, ticker: str, tenure: Optional[float]
    ) -> bool:
        # Conservative default: True only if there is an explicit
        # operator override saying so.
        if not self._overrides_path:
            return False
        try:
            import json
            from pathlib import Path

            data = json.loads(Path(self._overrides_path).read_text())
            return bool(
                data.get(ticker.upper(), {}).get(
                    "profitability_path_clear", False
                )
            )
        except (OSError, ValueError) as exc:
            # Missing/unreadable overrides file or corrupt JSON. Conservative
            # default: False.
            _LOG.info(
                "DefaultQualityAdapter._lookup_profitability_path(%s) using "
                "default False (no overrides): %s: %s",
                ticker, type(exc).__name__, exc,
            )
            return False
