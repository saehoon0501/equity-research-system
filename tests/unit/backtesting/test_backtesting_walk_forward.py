"""Tests for the activated walk_forward + pre_post_cutoff_sharpe_split paths.

Per v0.5 activation 2026-05-04: PIT fundamentals come from EDGAR
(`mcp__fundamentals`); per-memo claim-by-claim contamination defense is
audit_memos()'s responsibility, so walk_forward's price-only mechanics
no longer block on Sharadar.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.backtesting import BacktestingFramework


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


class _FakeMarketData:
    """In-memory market-data stub honoring the get_prices contract."""

    def __init__(self, rows_by_ticker: dict[str, list[dict]]):
        self._rows = rows_by_ticker

    def get_prices(self, ticker, start, end, interval="1d"):
        return {"rows": self._rows.get(ticker.upper(), [])}


class _NoopEvidenceIndex:
    def verify_memo(self, memo_path):
        return {"verdict": "PASS", "claims": []}

    def verify(self, *a, **kw):
        return {"verdict": "PASS"}


def _write_memo(tmp_path: Path, ticker: str, surfaced: str, horizon: int = 1) -> Path:
    memo = {
        "agent_id": "company-deep-dive",
        "ticker": ticker,
        "as_of_date": surfaced,
        "section_7_confidence_distribution": {"horizon_years": horizon},
    }
    p = tmp_path / f"{ticker.lower()}_{surfaced}.json"
    with p.open("w") as fh:
        json.dump(memo, fh)
    return p


# --------------------------------------------------------------------------- #
# walk_forward                                                                #
# --------------------------------------------------------------------------- #


def test_walk_forward_empty_memo_set_returns_zero(tmp_path):
    fw = BacktestingFramework(
        memo_set_path=str(tmp_path),
        market_data_client=_FakeMarketData({}),
        evidence_index_client=_NoopEvidenceIndex(),
    )
    result = fw.walk_forward()
    assert result.n_memos == 0
    assert result.aggregate_sharpe == 0.0
    assert result.periods == ()


def test_walk_forward_single_memo_computes_realized_return(tmp_path):
    _write_memo(tmp_path, "AAPL", "2024-01-02", horizon=1)
    rows = [
        {"date": "2024-01-02", "close": 100.0, "adj_close": 100.0},
        {"date": "2024-06-03", "close": 105.0, "adj_close": 105.0},
        {"date": "2024-12-31", "close": 120.0, "adj_close": 120.0},
    ]
    fw = BacktestingFramework(
        memo_set_path=str(tmp_path),
        market_data_client=_FakeMarketData({"AAPL": rows}),
        evidence_index_client=_NoopEvidenceIndex(),
    )
    result = fw.walk_forward()
    assert result.n_memos == 1
    # 100 → 120 = +20%
    assert result.returns[0] == pytest.approx(0.20)
    # Drawdown over the window — closes only went up, so dd = 0
    assert result.drawdowns[0] == pytest.approx(0.0)


def test_walk_forward_handles_drawdown(tmp_path):
    _write_memo(tmp_path, "AAPL", "2024-01-02", horizon=1)
    rows = [
        {"date": "2024-01-02", "close": 100.0, "adj_close": 100.0},
        {"date": "2024-06-03", "close": 80.0, "adj_close": 80.0},   # -20% peak-to-trough
        {"date": "2024-12-31", "close": 110.0, "adj_close": 110.0},
    ]
    fw = BacktestingFramework(
        memo_set_path=str(tmp_path),
        market_data_client=_FakeMarketData({"AAPL": rows}),
        evidence_index_client=_NoopEvidenceIndex(),
    )
    result = fw.walk_forward()
    assert result.drawdowns[0] == pytest.approx(-0.20)


def test_walk_forward_skips_memo_with_too_few_bars(tmp_path):
    _write_memo(tmp_path, "AAPL", "2024-01-02", horizon=1)
    rows = [
        {"date": "2024-01-02", "close": 100.0, "adj_close": 100.0},
    ]
    fw = BacktestingFramework(
        memo_set_path=str(tmp_path),
        market_data_client=_FakeMarketData({"AAPL": rows}),
        evidence_index_client=_NoopEvidenceIndex(),
    )
    result = fw.walk_forward()
    # The memo has fewer than 2 bars, gets skipped → n_memos=0
    assert result.n_memos == 0
    assert "<2 price bars" in result.notes


def test_walk_forward_aggregates_across_memos(tmp_path):
    _write_memo(tmp_path, "AAPL", "2024-01-02", horizon=1)
    _write_memo(tmp_path, "MSFT", "2024-01-02", horizon=1)
    aapl_rows = [
        {"date": "2024-01-02", "close": 100.0, "adj_close": 100.0},
        {"date": "2024-12-31", "close": 110.0, "adj_close": 110.0},
    ]
    msft_rows = [
        {"date": "2024-01-02", "close": 200.0, "adj_close": 200.0},
        {"date": "2024-12-31", "close": 230.0, "adj_close": 230.0},
    ]
    fw = BacktestingFramework(
        memo_set_path=str(tmp_path),
        market_data_client=_FakeMarketData({"AAPL": aapl_rows, "MSFT": msft_rows}),
        evidence_index_client=_NoopEvidenceIndex(),
    )
    result = fw.walk_forward()
    assert result.n_memos == 2
    assert len(result.returns) == 2
    assert len(result.drawdowns) == 2


# --------------------------------------------------------------------------- #
# pre_post_cutoff_sharpe_split                                                #
# --------------------------------------------------------------------------- #


def test_pre_post_split_partitions_on_cutoff(tmp_path):
    _write_memo(tmp_path, "AAPL", "2023-01-02", horizon=1)  # PRE
    _write_memo(tmp_path, "MSFT", "2024-06-01", horizon=1)  # POST
    aapl_rows = [
        {"date": "2023-01-02", "close": 100.0, "adj_close": 100.0},
        {"date": "2023-12-29", "close": 130.0, "adj_close": 130.0},
    ]
    msft_rows = [
        {"date": "2024-06-03", "close": 400.0, "adj_close": 400.0},
        {"date": "2025-05-30", "close": 360.0, "adj_close": 360.0},
    ]
    fw = BacktestingFramework(
        memo_set_path=str(tmp_path),
        market_data_client=_FakeMarketData({"AAPL": aapl_rows, "MSFT": msft_rows}),
        evidence_index_client=_NoopEvidenceIndex(),
    )
    result = fw.pre_post_cutoff_sharpe_split(cutoff_date="2024-01-01")
    assert result["pre_cutoff"]["n_memos"] == 1
    assert result["post_cutoff"]["n_memos"] == 1
    # AAPL pre: +30% return → mean_return = 0.30
    assert result["pre_cutoff"]["mean_return"] == pytest.approx(0.30)
    # MSFT post: -10% return
    assert result["post_cutoff"]["mean_return"] == pytest.approx(-0.10)


def test_pre_post_invalid_cutoff_raises(tmp_path):
    fw = BacktestingFramework(
        memo_set_path=str(tmp_path),
        market_data_client=_FakeMarketData({}),
        evidence_index_client=_NoopEvidenceIndex(),
    )
    with pytest.raises(ValueError):
        fw.pre_post_cutoff_sharpe_split(cutoff_date="not-a-date")
