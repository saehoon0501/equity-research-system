"""Smoke tests for src/disposition_view/.

No live Postgres required — tests use a hand-rolled FakeConnection that
implements just enough of the loader's _Connection / _Cursor protocol to
drive get_disposition_rows.

Verifies:
  - Loader returns one DispositionRow per watchlist name.
  - mode_to_primary_horizon mapping (B → long, B' → mid, C → short).
  - Manual primary override.
  - Per-horizon signal derivation (BUY / HOLD / TRIM / SELL routing).
  - Mode-fit flag status precedence.
  - Renderer emits Section 4.6 Q2 schema markers.
  - Filter by mode + ticker.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

import pytest

from src.disposition_view import (
    DispositionRow,
    ModeFitRow,
    derive_flag_status,
    derive_horizon_signals,
    get_disposition_rows,
    mode_to_primary_horizon,
    render_disposition,
    render_mode_fit_dashboard,
    render_single_ticker,
)


# -----------------------------------------------------------------------------
# Fake Postgres connection
# -----------------------------------------------------------------------------


class FakeStore:
    """In-memory equivalent of the joined tables."""

    def __init__(self) -> None:
        self.watchlist: list[dict] = []
        self.recommendations: list[dict] = []
        self.refreshes: list[dict] = []
        self.classifications: list[dict] = []
        self.vol_checks: list[dict] = []
        self.positions: list[dict] = []


class FakeCursor:
    def __init__(self, store: FakeStore) -> None:
        self._store = store
        self._result: list[tuple[Any, ...]] = []

    def execute(self, sql: str, params: Optional[tuple[Any, ...]] = None) -> None:
        params = params or ()
        norm = " ".join(sql.split())

        if "FROM watchlist w" in norm:
            rows = list(self._store.watchlist)
            params_iter = list(params)
            if "AND w.ticker = %s" in norm:
                ticker = params_iter.pop(0)
                rows = [r for r in rows if r["ticker"] == ticker]
            if "AND w.mode = %s" in norm:
                mode = params_iter.pop(0)
                rows = [r for r in rows if r["mode"] == mode]
            rows.sort(key=lambda r: (r["mode"], r["ticker"]))
            self._result = [
                (
                    r["ticker"],
                    r["mode"],
                    r["company_quality_flag"],
                    r["conviction_threshold"],
                    r["regime_sensitivity"],
                )
                for r in rows
            ]
            return

        if "FROM execution_recommendations" in norm and "ORDER BY date DESC" in norm:
            ticker = params[0]
            rows = [r for r in self._store.recommendations if r["ticker"] == ticker]
            rows.sort(key=lambda r: (r["date"], r["created_at"]), reverse=True)
            if not rows:
                self._result = []
                return
            r = rows[0]
            self._result = [
                (
                    str(r["recommendation_id"]),
                    r["ticker"],
                    r["date"],
                    r["recommendation"],
                    r["conviction"],
                    r["conviction_breakdown"],
                    r["sizing_suggestion"],
                    r["execution_context"],
                    r["trigger_metadata"],
                )
            ]
            return

        if "FROM daily_refresh_log" in norm:
            ticker = params[0]
            rows = [r for r in self._store.refreshes if r["ticker"] == ticker]
            rows.sort(key=lambda r: (r["date"], r["created_at"]), reverse=True)
            if not rows:
                self._result = []
                return
            r = rows[0]
            self._result = [
                (r["date"], r["materiality"], r["recommended_action"], r["events"])
            ]
            return

        if "FROM positions" in norm:
            ticker = params[0]
            rows = [p for p in self._store.positions if p["ticker"] == ticker]
            if not rows:
                self._result = [(None, None, None)]
                return
            shares = sum(float(p["shares_held"]) for p in rows)
            if shares <= 0:
                self._result = [(None, None, None)]
                return
            avg = sum(
                float(p["shares_held"]) * float(p["cost_basis"]) for p in rows
            ) / shares
            first = min(p["first_acquired"] for p in rows)
            self._result = [(shares, avg, first)]
            return

        if "FROM mode_classifications" in norm and "recheck_status = 'confirmed'" in norm:
            ticker = params[0]
            rows = [
                r
                for r in self._store.classifications
                if r["ticker"] == ticker and r["recheck_status"] == "confirmed"
            ]
            rows.sort(key=lambda r: r["classified_at"], reverse=True)
            if not rows:
                self._result = []
                return
            self._result = [(rows[0]["classified_at"],)]
            return

        if "FROM mode_classifications" in norm:
            ticker = params[0]
            rows = [r for r in self._store.classifications if r["ticker"] == ticker]
            rows.sort(key=lambda r: r["classified_at"], reverse=True)
            if not rows:
                self._result = []
                return
            self._result = [(rows[0]["classified_at"], rows[0]["recheck_status"])]
            return

        if "FROM mode_vol_checks" in norm:
            ticker = params[0]
            rows = [v for v in self._store.vol_checks if v["ticker"] == ticker]
            rows.sort(key=lambda v: v["check_date"], reverse=True)
            if not rows:
                self._result = []
                return
            v = rows[0]
            self._result = [
                (
                    v["check_date"],
                    v["realized_vol_252d"],
                    v["mode_band_low"],
                    v["mode_band_high"],
                    v["within_band"],
                    v["consecutive_outside_count"],
                    v["flagged"],
                )
            ]
            return

        # Unknown SQL — return empty.
        self._result = []

    def fetchone(self) -> Optional[tuple[Any, ...]]:
        return self._result[0] if self._result else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._result)

    def close(self) -> None:
        pass


class FakeConnection:
    def __init__(self, store: FakeStore) -> None:
        self._store = store

    def cursor(self) -> FakeCursor:
        return FakeCursor(self._store)

    def close(self) -> None:
        pass


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def store() -> FakeStore:
    s = FakeStore()
    now = datetime.now(timezone.utc)

    # Three watchlist names — one per mode.
    s.watchlist = [
        dict(
            ticker="AAPL",
            mode="B",
            company_quality_flag="HIGH",
            conviction_threshold=0.7,
            regime_sensitivity="LOW",
        ),
        dict(
            ticker="NVDA",
            mode="B_prime",
            company_quality_flag="HIGH",
            conviction_threshold=0.6,
            regime_sensitivity="MEDIUM",
        ),
        dict(
            ticker="RKLB",
            mode="C",
            company_quality_flag="STANDARD",
            conviction_threshold=0.5,
            regime_sensitivity="HIGH",
        ),
    ]

    s.recommendations = [
        dict(
            recommendation_id=uuid4(),
            ticker="AAPL",
            date=date(2026, 4, 28),
            recommendation="HOLD",
            conviction="HIGH",
            conviction_breakdown={
                "debate_consensus": "5/5 unanimous",
                "kills_fired": "0 of 7",
                "counterfactual_top_3": "3 SURVIVOR archetype",
                "mode_certainty": "rule_clean",
                "drift_channels": "0 of 3 triggered",
            },
            sizing_suggestion={"initial_pct": 3.0, "max_pct": 8.0},
            execution_context={
                "current_price": 192.30,
                "fair_value_estimate": {"point": 200, "range_low": 180, "range_high": 220},
                "near_term_catalysts": [{"event": "earnings", "date": "2026-05-02"}],
                "technical_signals": {"ma_50d": 188.0},
            },
            trigger_metadata={"triggered_by": "mode_cadence_floor"},
            created_at=now,
        ),
        dict(
            recommendation_id=uuid4(),
            ticker="NVDA",
            date=date(2026, 4, 28),
            recommendation="BUY",
            conviction="HIGH",
            conviction_breakdown={
                "debate_consensus": "4/5 (Quant dissents HOLD)",
                "kills_fired": "0 of 7",
                "counterfactual_top_3": "3 SURVIVOR archetype",
                "mode_certainty": "rule_clean",
                "drift_channels": "0 of 3 triggered",
            },
            sizing_suggestion={"initial_pct": 1.4, "max_pct": 3.5},
            execution_context={
                "current_price": 158.32,
                "fair_value_estimate": {"point": 175, "range_low": 155, "range_high": 195},
                "near_term_catalysts": [{"event": "GTC keynote", "date": "2026-05-15"}],
            },
            trigger_metadata={"triggered_by": "new_candidate"},
            created_at=now,
        ),
        dict(
            recommendation_id=uuid4(),
            ticker="RKLB",
            date=date(2026, 4, 27),
            recommendation="TRIM",
            conviction="MEDIUM",
            conviction_breakdown={
                "debate_consensus": "3/5",
                "kills_fired": "1 of 5",
                "counterfactual_top_3": "1 SURVIVOR + 2 NON_SURVIVOR",
                "mode_certainty": "llm_tiebreaker",
                "drift_channels": "2 of 3 triggered",
            },
            sizing_suggestion={"initial_pct": 0.5, "max_pct": 2.0},
            execution_context={
                "current_price": 32.10,
                "near_term_catalysts": [],
            },
            trigger_metadata={"triggered_by": "m2_event"},
            created_at=now,
        ),
    ]

    s.refreshes = [
        dict(
            ticker="AAPL",
            date=date(2026, 4, 28),
            materiality=1,
            recommended_action="hold",
            events=[],
            created_at=now,
        ),
        dict(
            ticker="NVDA",
            date=date(2026, 4, 28),
            materiality=2,
            recommended_action="size_up",
            events=[{"type": "filing_8k"}],
            created_at=now,
        ),
        dict(
            ticker="RKLB",
            date=date(2026, 4, 28),
            materiality=3,
            recommended_action="reunderwrite",
            events=[{"type": "guidance_cut"}],
            created_at=now,
        ),
    ]

    s.classifications = [
        dict(
            ticker="AAPL",
            classified_at=datetime(2026, 1, 15, tzinfo=timezone.utc),
            recheck_status="confirmed",
        ),
        dict(
            ticker="NVDA",
            classified_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            recheck_status="confirmed",
        ),
        dict(
            ticker="RKLB",
            classified_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
            recheck_status="reclassification_proposed",
        ),
    ]

    s.vol_checks = [
        dict(
            ticker="AAPL",
            check_date=date(2026, 4, 1),
            realized_vol_252d=0.22,
            mode_band_low=0.0,
            mode_band_high=0.25,
            within_band=True,
            consecutive_outside_count=0,
            flagged=False,
        ),
        dict(
            ticker="NVDA",
            check_date=date(2026, 4, 1),
            realized_vol_252d=0.42,
            mode_band_low=0.25,
            mode_band_high=0.50,
            within_band=True,
            consecutive_outside_count=0,
            flagged=False,
        ),
        dict(
            ticker="RKLB",
            check_date=date(2026, 4, 1),
            realized_vol_252d=0.35,  # Below C band of >50%
            mode_band_low=0.50,
            mode_band_high=2.00,
            within_band=False,
            consecutive_outside_count=2,
            flagged=True,
        ),
    ]

    s.positions = [
        dict(
            ticker="AAPL",
            shares_held=100.0,
            cost_basis=150.0,
            first_acquired=date(2024, 6, 1),
        ),
    ]
    return s


@pytest.fixture
def conn(store: FakeStore) -> FakeConnection:
    return FakeConnection(store)


# -----------------------------------------------------------------------------
# Mode → primary horizon mapping (Section 4.6 Q2)
# -----------------------------------------------------------------------------


def test_mode_to_primary_horizon_mapping() -> None:
    assert mode_to_primary_horizon("B") == "long"
    assert mode_to_primary_horizon("B_prime") == "mid"
    assert mode_to_primary_horizon("C") == "short"


def test_mode_to_primary_horizon_unknown_raises() -> None:
    with pytest.raises(ValueError):
        mode_to_primary_horizon("X")


# -----------------------------------------------------------------------------
# Loader
# -----------------------------------------------------------------------------


def test_loader_returns_one_row_per_watchlist_name(conn: FakeConnection) -> None:
    rows = get_disposition_rows(conn)
    assert len(rows) == 3
    assert {r.ticker for r in rows} == {"AAPL", "NVDA", "RKLB"}
    aapl = next(r for r in rows if r.ticker == "AAPL")
    assert aapl.shares_held == 100.0
    assert aapl.cost_basis == 150.0
    assert aapl.recommendation == "HOLD"


def test_loader_filter_by_ticker(conn: FakeConnection) -> None:
    rows = get_disposition_rows(conn, ticker="NVDA")
    assert len(rows) == 1
    assert rows[0].ticker == "NVDA"
    assert rows[0].mode == "B_prime"


def test_loader_filter_by_mode(conn: FakeConnection) -> None:
    rows = get_disposition_rows(conn, mode="C")
    assert len(rows) == 1
    assert rows[0].ticker == "RKLB"


def test_loader_unheld_name_has_no_position(conn: FakeConnection) -> None:
    rows = get_disposition_rows(conn, ticker="NVDA")
    assert rows[0].shares_held is None


def test_loader_attaches_mode_fit(conn: FakeConnection) -> None:
    rows = get_disposition_rows(conn, ticker="RKLB")
    mf = rows[0].mode_fit
    assert mf.flagged is True
    assert mf.consecutive_outside_count == 2
    assert mf.recheck_status == "reclassification_proposed"


# -----------------------------------------------------------------------------
# Per-horizon signal derivation
# -----------------------------------------------------------------------------


def test_derive_horizon_signals_b_mode_long_primary(conn: FakeConnection) -> None:
    rows = get_disposition_rows(conn, ticker="AAPL")
    sigs = derive_horizon_signals(rows[0])
    assert sigs["long"].is_primary is True
    assert sigs["short"].is_primary is False
    assert sigs["mid"].is_primary is False


def test_derive_horizon_signals_bprime_mode_mid_primary(conn: FakeConnection) -> None:
    rows = get_disposition_rows(conn, ticker="NVDA")
    sigs = derive_horizon_signals(rows[0])
    assert sigs["mid"].is_primary is True


def test_derive_horizon_signals_c_mode_short_primary(conn: FakeConnection) -> None:
    rows = get_disposition_rows(conn, ticker="RKLB")
    sigs = derive_horizon_signals(rows[0])
    assert sigs["short"].is_primary is True


def test_derive_horizon_signals_override(conn: FakeConnection) -> None:
    rows = get_disposition_rows(conn, ticker="AAPL")
    sigs = derive_horizon_signals(rows[0], primary_override="short")
    assert sigs["short"].is_primary is True
    assert sigs["long"].is_primary is False


def test_derive_horizon_signal_routing_buy(conn: FakeConnection) -> None:
    rows = get_disposition_rows(conn, ticker="NVDA")
    sigs = derive_horizon_signals(rows[0])
    # Mid horizon mirrors latest recommendation (BUY/HIGH).
    assert sigs["mid"].signal == "BUY"


def test_derive_horizon_signal_routing_sell_on_m3(conn: FakeConnection) -> None:
    rows = get_disposition_rows(conn, ticker="RKLB")
    sigs = derive_horizon_signals(rows[0])
    # Short horizon: M-3 + reunderwrite escalation does NOT contain "exit",
    # but materiality 3 → SELL routing per derivation rules.
    assert sigs["short"].signal == "SELL"


def test_derive_horizon_signal_routing_long_drift(conn: FakeConnection) -> None:
    rows = get_disposition_rows(conn, ticker="RKLB")
    sigs = derive_horizon_signals(rows[0])
    # 2 of 3 drift channels triggered + NON_SURVIVOR → SELL.
    assert sigs["long"].signal == "SELL"


# -----------------------------------------------------------------------------
# Mode-fit flag-status precedence (Phase 4 Q5)
# -----------------------------------------------------------------------------


def _mk_mf(**kwargs: Any) -> ModeFitRow:
    defaults = dict(
        mode="B",
        realized_vol_252d=0.20,
        mode_band_low=0.0,
        mode_band_high=0.25,
        within_band=True,
        consecutive_outside_count=0,
        flagged=False,
        last_confirmed_date=date(2026, 1, 1),
        recheck_status="confirmed",
        last_check_date=date(2026, 4, 1),
    )
    defaults.update(kwargs)
    return ModeFitRow(**defaults)


def test_flag_status_pending_reclassification_wins() -> None:
    mf = _mk_mf(recheck_status="reclassification_proposed", flagged=True)
    assert derive_flag_status(mf) == "pending_reclassification"


def test_flag_status_rule_output_mismatch() -> None:
    mf = _mk_mf(recheck_status="pending_review", flagged=False)
    assert derive_flag_status(mf) == "rule_output_mismatch"


def test_flag_status_vol_band_inconsistency() -> None:
    mf = _mk_mf(recheck_status="confirmed", flagged=True)
    assert derive_flag_status(mf) == "vol_band_inconsistency"


def test_flag_status_none_when_clean() -> None:
    mf = _mk_mf()
    assert derive_flag_status(mf) == "none"


# -----------------------------------------------------------------------------
# Renderer
# -----------------------------------------------------------------------------


def test_render_disposition_emits_section_4_6_q2_markers(conn: FakeConnection) -> None:
    rows = get_disposition_rows(conn)
    md = render_disposition(rows)
    # Header
    assert "# Multi-Horizon Disposition View" in md
    # Per Section 4.6 Q2 schema markers
    assert "primary_horizon" not in md  # we don't include the YAML key globally
    assert "PRIMARY" in md
    assert "detail_expanded_by_default: true" in md
    assert "detail_collapsed_by_default: true" in md
    # Multi-horizon table headers
    assert "Short (≤3mo)" in md
    assert "Mid (3-12mo)" in md
    assert "Long (12+mo)" in md
    # Mode-fit dashboard
    assert "Mode-Fit Dashboard" in md
    assert "rule_output_mismatch" in md or "vol_band_inconsistency" in md or "OK" in md


def test_render_disposition_marks_primary_with_asterisk(conn: FakeConnection) -> None:
    rows = get_disposition_rows(conn)
    md = render_disposition(rows)
    # Primary-horizon cell prefix marker '*'
    assert "* " in md


def test_render_disposition_with_override(conn: FakeConnection) -> None:
    rows = get_disposition_rows(conn)
    md = render_disposition(rows, primary_overrides={"AAPL": "short"})
    # AAPL row's Short cell should have the asterisk (primary marker).
    aapl_lines = [ln for ln in md.splitlines() if ln.startswith("| AAPL")]
    assert aapl_lines, "expected an AAPL row in main table"
    aapl_row = aapl_lines[0]
    # Primary column should now show 'short'.
    assert "| short |" in aapl_row


def test_render_single_ticker(conn: FakeConnection) -> None:
    rows = get_disposition_rows(conn, ticker="NVDA")
    md = render_single_ticker(rows[0])
    assert "Disposition — NVDA" in md
    assert "Primary horizon (mode-anchored)" in md
    assert "mid" in md.lower()


def test_render_mode_fit_dashboard(conn: FakeConnection) -> None:
    rows = get_disposition_rows(conn)
    md = render_mode_fit_dashboard(rows)
    # All three flag types possible in fixture, plus realized vol cells.
    assert "realized_252d_vol" in md
    assert "last_confirmed_date" in md
    assert "flag_status" in md
    # RKLB has reclassification_proposed → pending_reclassification.
    assert "pending_reclassification" in md
    # AAPL within band → OK.
    assert "OK" in md


def test_render_empty_watchlist_handles_gracefully() -> None:
    md = render_disposition([])
    assert "No watchlist names" in md


# -----------------------------------------------------------------------------
# CLI smoke
# -----------------------------------------------------------------------------


def test_cli_argparse_smoke() -> None:
    from src.disposition_view.cli import _build_parser

    parser = _build_parser()
    ns = parser.parse_args(["render"])
    assert ns.cmd == "render"

    ns = parser.parse_args(["render", "--mode", "B_prime"])
    assert ns.mode == "B_prime"

    ns = parser.parse_args(["render", "--ticker", "NVDA"])
    assert ns.ticker == "NVDA"

    ns = parser.parse_args(
        ["render", "--toggle-primary", "AAPL", "short"]
    )
    assert ns.toggle_primary == [["AAPL", "short"]]


def test_parse_overrides_rejects_duplicate_ticker() -> None:
    """Per v3 Section 4.6 Q2 + 5.4: duplicate --toggle-primary ticker → exit 4.

    Persistent overrides are deferred to v0.5+; for v0.1 the override is
    session-only. Two flags for the same ticker in one invocation is an
    operator-confusion signal — last-write-wins is dangerous, so we exit
    rather than guess.
    """
    from src.disposition_view.cli import _parse_overrides

    # Single override → fine.
    assert _parse_overrides([["AAPL", "short"]]) == {"AAPL": "short"}

    # Two distinct tickers → fine.
    out = _parse_overrides([["AAPL", "short"], ["NVDA", "long"]])
    assert out == {"AAPL": "short", "NVDA": "long"}

    # Same ticker twice → SystemExit(4).
    with pytest.raises(SystemExit) as exc_info:
        _parse_overrides([["AAPL", "short"], ["AAPL", "long"]])
    assert exc_info.value.code == 4

    # Unknown horizon → SystemExit(4).
    with pytest.raises(SystemExit) as exc_info:
        _parse_overrides([["AAPL", "decade"]])
    assert exc_info.value.code == 4
