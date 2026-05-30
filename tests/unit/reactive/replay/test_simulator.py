"""Unit tests for the Replay-Harness simulator DAILY layer (Task 2.3).

NON-BEHAVIORAL drive-not-reimplement tests for the FIRST piece of the
`simulator` module — the daily decision layer + divergence detection. The
intraday/fills/flatten/P&L pieces are tasks 2.4-2.7 (not exercised here).

The daily layer (design `simulator` "Core algorithms #1 — champion-decision
prefetch + divergence detection", System Flow daily leg):

  - **Champion-decision prefetch (once)**: at window start, call the injected
    `query_trace({...champion keys..., kind:"decision", until:<boundary>})`
    EXACTLY ONCE and index the champion decisions by `(day, symbol)` — no
    per-day DB round-trip (removes the ordering hazard).
  - **Per-day candidate decision (R3.1/R3.3)**: for each trading day D in the
    window, drive the LANDED `decide` (asserted via the `stub_decide` core, not
    recomputed) with the candidate `ParamSnapshot` → a `ReactiveDecision`. The
    candidate reconstructs its OWN decision (R2.1), never reading the champion's
    outcome as the candidate's decision.
  - **Divergence detection (R2.2)**: a `(day, symbol)` DIVERGES iff the
    candidate decision differs from the champion's indexed decision —
    INCLUDING champion-HOLD/absent vs candidate-actionable. A divergent +
    actionable day is flagged for the (later) intraday re-fetch; a
    non-divergent day is not.
  - **Determinism (R9.1)**: identical (candidate, window, port, champion index)
    ⇒ identical per-day decisions.

These tests ride the R9.2 `FixtureDataPort` isolation seam + `stub_decide` (no
network / DB / LLM). The champion side is injected two ways:

  - a FAKE `query_trace` (a `Mock`) to assert prefetch-once + the index
    extraction, and
  - PRE-INDEXED champion-decision dicts passed directly to the daily loop (the
    task explicitly permits this) so the divergence/determinism tests do NOT
    depend on the (daemon-undetermined) trace-payload symbol key.

Source of truth: requirements.md R2 AC 2.1/2.2, R3 AC 3.1/3.3; design.md
`simulator` "Core algorithms #1" + the System Flow daily leg + the test-plan
bullet (design line 268).

Requirements: 2.1, 2.2, 3.1, 3.3.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

from src.reactive.params import DEFAULTS
from src.reactive.replay import simulator
from src.reactive.replay.simulator import (
    DailyDecision,
    index_champion_decisions,
    run_daily_layer,
)
from src.reactive.replay.types import Candidate, ReplayWindow

from tests.unit.reactive.replay._fixtures import (
    make_correlation_keys,
    make_fixture_dataport,
    stub_decide,
)

# --- canned champion-decision trace rows (raw query_trace dicts) --------------
# `query_trace` returns RAW dicts keyed by `_COLUMNS` (NOT DecisionTraceRow
# objects); the symbol lives in the freeform `trace` JSONB payload under the
# module's `_CHAMPION_SYMBOL_KEY` (= "symbol"; daemon-undetermined — see the
# simulator module docstring + the task CONCERNS). The decision lives in
# `trace["decision"]` (pinned by the telemetry schema + fixture).


def _champion_row(*, symbol: str, day: str, decision: str) -> dict:
    """A raw `query_trace` champion decision-row dict (kind == 'decision')."""
    keys = make_correlation_keys()
    return {
        "trace_id": f"trace-{symbol}-{day}",
        "kind": "decision",
        "parent_trace_id": None,
        "event_ts": f"{day}T14:30:00Z",
        "run_id": keys.run_id,
        "code_version": keys.code_version,
        "param_version": keys.param_version,
        "walk_forward_window": keys.walk_forward_window,
        "trace": {"symbol": symbol, "decision": decision, "probability": 0.62},
        "created_at": f"{day}T14:30:00Z",
    }


def _candidate() -> Candidate:
    """A candidate config carrying the inner-ring DEFAULTS param snapshot (R1.3)."""
    return Candidate(param_snapshot=DEFAULTS, survival_parameters=None, code_version=None)


def _window(tickers: list[str]) -> ReplayWindow:
    return ReplayWindow(start="2024-01-01", end="2024-01-03", tickers=tickers)


# ============================================================================ #
# Champion-decision prefetch + indexing (algo #1, prefetch-once)
# ============================================================================ #


def test_champion_decisions_indexed_by_day_symbol() -> None:
    """`index_champion_decisions` keys champion rows by `(day, symbol)` — the
    `event_ts` date and the trace-payload symbol; the value is `trace["decision"]`.
    """
    fake_query = Mock(
        return_value=[
            _champion_row(symbol="AAPL", day="2024-01-02", decision="LONG"),
            _champion_row(symbol="MSFT", day="2024-01-02", decision="HOLD"),
        ]
    )
    champion_keys = {
        "code_version": "champ-code-v1",
        "param_version": "champ-param-v1",
        "walk_forward_window": "2024Q1",
    }

    index = index_champion_decisions(fake_query, champion_keys, until="2024-01-03")

    assert index[("2024-01-02", "AAPL")] == "LONG"
    assert index[("2024-01-02", "MSFT")] == "HOLD"


def test_champion_prefetch_calls_query_trace_exactly_once() -> None:
    """Champion decisions are pre-fetched ONCE (no per-day round-trip) — assert
    the injected `query_trace` is called exactly once over a multi-day,
    multi-ticker window (algo #1 "removing the ordering hazard").

    This is also the ONLY test that drives a fake `query_trace` end-to-end
    THROUGH `run_daily_layer`, so it additionally guards the two seams the
    isolated index test cannot: the `_CHAMPION_SYMBOL_KEY` extraction AND the
    `(day, symbol)` join between the champion `event_ts[:10]` and the
    epoch-ms-derived bar day. The candidate stub goes LONG every day; the
    champion went LONG on AAPL/2024-01-02 only.
    """
    fake_query = Mock(
        return_value=[
            _champion_row(symbol="AAPL", day="2024-01-02", decision="LONG"),
        ]
    )
    champion_keys = {
        "code_version": "champ-code-v1",
        "param_version": "champ-param-v1",
        "walk_forward_window": "2024Q1",
    }
    window = _window(["AAPL", "MSFT"])

    results = run_daily_layer(
        _candidate(),
        window,
        make_fixture_dataport(),
        query_trace=fake_query,
        champion_keys=champion_keys,
        is_boundary="2024-01-03",
        decide_fn=stub_decide,
    )

    assert fake_query.call_count == 1

    by_key = {(r.as_of_day, r.symbol): r for r in results}
    # The champion row MATCHED through the real index + join (LONG == LONG) ⇒
    # NOT divergent. Proves symbol extraction + the day-join actually line up.
    assert by_key[("2024-01-02", "AAPL")].diverged is False
    # A champion-absent (day, symbol) ⇒ HOLD substitution ⇒ candidate-LONG diverges.
    assert by_key[("2024-01-01", "AAPL")].diverged is True
    assert by_key[("2024-01-02", "MSFT")].diverged is True


def test_champion_prefetch_passes_kind_decision_and_boundary() -> None:
    """The single prefetch query filters `kind="decision"` + the champion keys +
    the boundary `until` (the consumer-supplied temporal firewall).
    """
    fake_query = Mock(return_value=[])
    champion_keys = {
        "code_version": "champ-code-v1",
        "param_version": "champ-param-v1",
        "walk_forward_window": "2024Q1",
    }

    index_champion_decisions(fake_query, champion_keys, until="2024-01-03")

    (filters,), _ = fake_query.call_args
    assert filters["kind"] == "decision"
    assert filters["until"] == "2024-01-03"
    assert filters["code_version"] == "champ-code-v1"
    assert filters["param_version"] == "champ-param-v1"
    assert filters["walk_forward_window"] == "2024Q1"


def test_index_raises_on_present_row_missing_symbol() -> None:
    """A PRESENT champion row with no recognized symbol key is a DEFECT (wrong
    daemon key), NOT a no-record — fail LOUD rather than collapse into the
    champion-absent path (which would make every actionable day spuriously
    diverge). Row-absence is tolerated only by the divergence predicate's
    `.get(..., "HOLD")`, never by the extractor.
    """
    bad_row = _champion_row(symbol="AAPL", day="2024-01-02", decision="LONG")
    del bad_row["trace"]["symbol"]
    fake_query = Mock(return_value=[bad_row])

    try:
        index_champion_decisions(fake_query, {}, until="2024-01-03")
    except (KeyError, ValueError):
        pass
    else:
        raise AssertionError("expected a loud failure on a present row missing symbol")


# ============================================================================ #
# Per-day candidate decision — DRIVE decide, never reimplement (R3.1/R3.3)
# ============================================================================ #


def test_candidate_decision_drives_decide_not_reimplemented() -> None:
    """The per-day decision is produced by DRIVING `decide` (asserted via the
    injected stub core), not recomputed — R3.1/R3.3. The stub is invoked with
    the candidate's `ParamSnapshot` and the per-day `FeatureSet`.
    """
    spy_decide = Mock(side_effect=stub_decide)
    window = _window(["AAPL"])
    pre_indexed: dict = {}

    results = run_daily_layer(
        _candidate(),
        window,
        make_fixture_dataport(),
        champion_decisions=pre_indexed,
        decide_fn=spy_decide,
    )

    assert spy_decide.call_count >= 1
    # decide called with the candidate's snapshot (positional arg 3 / kw).
    call = spy_decide.call_args_list[0]
    passed_snapshot = call.args[2] if len(call.args) > 2 else call.kwargs["snapshot"]
    assert passed_snapshot is DEFAULTS
    assert all(isinstance(r, DailyDecision) for r in results)
    # Every per-day record carries the candidate's OWN ReactiveDecision + the day.
    assert results[0].decision.decision in ("LONG", "SHORT", "HOLD")
    assert results[0].as_of_day == "2024-01-01"


# ============================================================================ #
# Divergence detection (R2.2)
# ============================================================================ #


def test_divergent_day_champion_hold_candidate_long_is_flagged() -> None:
    """A divergent-decision day (champion HOLD, candidate actionable LONG) is
    flagged for the (later) intraday re-fetch (R2.2 — INCLUDING the
    champion-HOLD vs candidate-actionable case).
    """
    champion_long = lambda *a, **k: stub_decide(*a, decision="LONG", **k)  # noqa: E731
    window = ReplayWindow(start="2024-01-02", end="2024-01-02", tickers=["AAPL"])
    pre_indexed = {("2024-01-02", "AAPL"): "HOLD"}  # champion HELD that day

    results = run_daily_layer(
        _candidate(),
        window,
        make_fixture_dataport(),
        champion_decisions=pre_indexed,
        decide_fn=champion_long,
    )

    (rec,) = results
    assert rec.decision.decision == "LONG"
    assert rec.diverged is True
    assert rec.needs_intraday_refetch is True


def test_non_divergent_day_is_not_flagged() -> None:
    """A non-divergent day (candidate decision == champion's indexed decision)
    is NOT flagged for re-fetch — the intraday layer may reuse the champion's
    recorded inputs (R2.2).
    """
    candidate_long = lambda *a, **k: stub_decide(*a, decision="LONG", **k)  # noqa: E731
    window = ReplayWindow(start="2024-01-02", end="2024-01-02", tickers=["AAPL"])
    pre_indexed = {("2024-01-02", "AAPL"): "LONG"}  # champion ALSO went LONG

    results = run_daily_layer(
        _candidate(),
        window,
        make_fixture_dataport(),
        champion_decisions=pre_indexed,
        decide_fn=candidate_long,
    )

    (rec,) = results
    assert rec.decision.decision == "LONG"
    assert rec.diverged is False
    assert rec.needs_intraday_refetch is False


def test_champion_absent_treated_as_hold() -> None:
    """A `(day, symbol)` with NO champion row → champion treated as HOLD →
    a candidate-actionable day diverges (R2.2 "no-record vs actionable"). This
    is the NORMAL champion-absent path, distinct from the extractor's defect path.
    """
    candidate_long = lambda *a, **k: stub_decide(*a, decision="LONG", **k)  # noqa: E731
    window = ReplayWindow(start="2024-01-02", end="2024-01-02", tickers=["AAPL"])
    pre_indexed: dict = {}  # champion never decided this (day, symbol)

    results = run_daily_layer(
        _candidate(),
        window,
        make_fixture_dataport(),
        champion_decisions=pre_indexed,
        decide_fn=candidate_long,
    )

    (rec,) = results
    assert rec.diverged is True
    assert rec.needs_intraday_refetch is True


def test_divergent_but_hold_candidate_not_flagged_for_refetch() -> None:
    """A divergent day where the CANDIDATE is HOLD (champion was LONG) needs NO
    intraday path — `needs_intraday_refetch` is False even though it diverged
    (the re-fetch flag is `diverged AND candidate actionable`, not bare diverged).
    """
    candidate_hold = lambda *a, **k: stub_decide(*a, decision="HOLD", **k)  # noqa: E731
    window = ReplayWindow(start="2024-01-02", end="2024-01-02", tickers=["AAPL"])
    pre_indexed = {("2024-01-02", "AAPL"): "LONG"}  # champion went LONG; candidate HOLDs

    results = run_daily_layer(
        _candidate(),
        window,
        make_fixture_dataport(),
        champion_decisions=pre_indexed,
        decide_fn=candidate_hold,
    )

    (rec,) = results
    assert rec.decision.decision == "HOLD"
    assert rec.diverged is True
    assert rec.needs_intraday_refetch is False


# ============================================================================ #
# Determinism (R9.1)
# ============================================================================ #


def test_identical_inputs_yield_identical_decisions() -> None:
    """Identical (candidate, window, port, champion index) ⇒ identical per-day
    records (R9.1 — determinism against a fixed fixture port + stub core).
    """
    window = _window(["AAPL", "MSFT"])
    pre_indexed = {("2024-01-02", "AAPL"): "HOLD"}

    def _run() -> list[DailyDecision]:
        return run_daily_layer(
            _candidate(),
            window,
            make_fixture_dataport(),
            champion_decisions=pre_indexed,
            decide_fn=stub_decide,
        )

    first = _run()
    second = _run()

    assert len(first) == len(second)
    for a, b in zip(first, second):
        assert a.as_of_day == b.as_of_day
        assert a.symbol == b.symbol
        assert a.decision.decision == b.decision.decision
        assert a.decision.probability == b.decision.probability
        assert a.diverged == b.diverged
        assert a.needs_intraday_refetch == b.needs_intraday_refetch


def test_one_record_per_trading_day_per_ticker() -> None:
    """The daily layer emits one `DailyDecision` per (trading day, ticker) over
    the window, days derived from `fetch_daily_bars` (the DataPort has no
    calendar method); ordering is deterministic (window-ticker order, sorted days).
    """
    window = _window(["AAPL", "MSFT"])

    results = run_daily_layer(
        _candidate(),
        window,
        make_fixture_dataport(),
        champion_decisions={},
        decide_fn=stub_decide,
    )

    # The fixture port serves 3 canned daily bars (2024-01-01/02/03); after the
    # window [start, end] bound that is 3 trading days × 2 tickers = 6 records.
    days = sorted({r.as_of_day for r in results})
    assert days == ["2024-01-01", "2024-01-02", "2024-01-03"]
    symbols = {r.symbol for r in results}
    assert symbols == {"AAPL", "MSFT"}
    assert len(results) == 6


def test_module_importable_and_pure() -> None:
    """The simulator module imports with no network/DB/LLM (pure leaf) and
    exposes the daily-layer seam 2.4 consumes."""
    assert hasattr(simulator, "run_daily_layer")
    assert hasattr(simulator, "index_champion_decisions")
    assert hasattr(simulator, "DailyDecision")
