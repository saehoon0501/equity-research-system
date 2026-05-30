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

from src.reactive.features import FeatureSet
from src.reactive.params import DEFAULTS
from src.reactive.replay import simulator
from src.reactive.replay.simulator import (
    DEFAULT_STOP_LOSS_ATR_MULT,
    DailyDecision,
    apply_admit_gating,
    build_order,
    detect_stop_hit,
    index_champion_decisions,
    run_daily_layer,
    select_direction,
    simulate_fill,
)
from src.reactive.replay.types import Candidate, Fill, ReplayWindow
from src.survival.params import DEFAULTS as SURVIVAL_DEFAULTS
from src.survival.types import (
    AccountState,
    AdmitDecision,
    ClockState,
    OperationalState,
    OrderEvaluation,
    Position,
    ProposedOrder,
)

from tests.unit.reactive.replay._fixtures import (
    make_correlation_keys,
    make_fixture_dataport,
    stub_decide,
)


# --- local FeatureSet builder (carries the verbatim tactical bin) -------------
# The real `compute_daily_features` over the 3 canned fixture bars degrades to a
# `FeatureFailure(insufficient_history)` — so the daily layer would (correctly)
# go flat on every fixture day. To exercise the DIRECTIONAL paths (the candidate
# DRIVING `decide`), tests inject a local `features_fn` returning a real
# `FeatureSet` carrying a chosen `raw["tactical_bin"]`. Defined HERE (not in
# `_fixtures.py`, which is out of this task's boundary and whose
# `stub_compute_features` does not surface `tactical_bin`).


def _feature_set(*, tactical_bin: str, trend_vote: float | None = None) -> FeatureSet:
    """A `FeatureSet` carrying a chosen verbatim `raw["tactical_bin"]`.

    `trend_vote` defaults to the landed `_TACTICAL_VOTE` mapping of the bin, but
    is overridable so a test can make `tactical_bin` and `trend_vote` DISAGREE —
    the NB-1 read-source guard (`select_direction` must read the verbatim bin,
    never the vote that folds `unavailable`→`0.0`==`neutral`).
    """
    _bin_to_vote = {"positive": 1.0, "negative": -1.0, "neutral": 0.0, "unavailable": 0.0}
    tv = trend_vote if trend_vote is not None else _bin_to_vote.get(tactical_bin, 0.0)
    return FeatureSet(
        trend_vote=tv,
        flow_vote=0.5,
        meanrev_vote=0.0,
        trend_strength=0.5,
        raw={"rsi_14": 55.0, "tactical_bin": tactical_bin, "atr": 1.2},
    )


def _features_fn(*, tactical_bin: str, trend_vote: float | None = None):
    """An injectable `features_fn` returning the chosen `FeatureSet` for any day."""

    def _fn(symbol: str, day: str, data_port) -> FeatureSet:  # noqa: ANN001
        return _feature_set(tactical_bin=tactical_bin, trend_vote=trend_vote)

    return _fn

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
        features_fn=_features_fn(tactical_bin="positive"),
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
        features_fn=_features_fn(tactical_bin="positive"),
    )

    assert spy_decide.call_count >= 1
    # decide called with the candidate's snapshot (positional arg 3 / kw).
    call = spy_decide.call_args_list[0]
    passed_snapshot = call.args[2] if len(call.args) > 2 else call.kwargs["snapshot"]
    assert passed_snapshot is DEFAULTS
    assert all(isinstance(r, DailyDecision) for r in results)
    # Every per-day record carries the candidate's OWN ReactiveDecision + the day.
    assert results[0].decision is not None
    assert results[0].decision.decision in ("LONG", "SHORT", "HOLD")
    assert results[0].as_of_day == "2024-01-01"


# ============================================================================ #
# Direction selection from the tactical-overlay bin (Req 12.5, §12.3 / amend 2.3)
#
# Direction = the tactical relative-strength bin via the explicit map
#   positive→LONG, negative→SHORT, neutral/unavailable→None (no new exposure).
# Read from `FeatureSet.raw["tactical_bin"]`, NEVER `trend_vote` (NB-1: the vote
# folds `unavailable`→0.0==`neutral`, so the bin alone is authoritative).
# ============================================================================ #


def test_select_direction_positive_bin_is_long() -> None:
    """A `positive` tactical bin maps to `Direction.LONG`."""
    assert select_direction(_feature_set(tactical_bin="positive")) == "LONG"


def test_select_direction_negative_bin_is_short() -> None:
    """A `negative` tactical bin maps to `Direction.SHORT` — SHORT is now
    reconstructable (the defect this amendment fixes)."""
    assert select_direction(_feature_set(tactical_bin="negative")) == "SHORT"


def test_select_direction_neutral_bin_is_none() -> None:
    """A `neutral` tactical bin is non-directional → `None` (no new exposure)."""
    assert select_direction(_feature_set(tactical_bin="neutral")) is None


def test_select_direction_unavailable_bin_is_none() -> None:
    """An `unavailable` tactical bin is non-directional → `None` (no new
    exposure) — distinct *cause* from `neutral` but the same no-trade outcome."""
    assert select_direction(_feature_set(tactical_bin="unavailable")) is None


def test_select_direction_reads_bin_not_trend_vote() -> None:
    """The decisive NB-1 guard: when the bin and `trend_vote` DISAGREE, the
    direction follows the VERBATIM `raw["tactical_bin"]`, not the vote. A
    `negative` bin carrying a (contradictory) `trend_vote=+1.0` ⇒ SHORT, not
    LONG — proves the read-source is `raw["tactical_bin"]`."""
    fs = _feature_set(tactical_bin="negative", trend_vote=1.0)
    assert fs.trend_vote == 1.0  # the vote would (wrongly) say LONG
    assert select_direction(fs) == "SHORT"  # the bin says SHORT — bin wins


def test_select_direction_feature_failure_is_none() -> None:
    """A degraded feature object with no `raw` (e.g. a `FeatureFailure`) →
    `None` — fail toward no-new-exposure (Req 12.4)."""

    class _NoRaw:  # a FeatureFailure-like object: no `.raw`
        reason = "insufficient_history"

    assert select_direction(_NoRaw()) is None


def test_positive_bin_drives_decide_with_long() -> None:
    """A `positive` bin ⇒ the SELECTED direction LONG is passed to `decide`."""
    spy_decide = Mock(side_effect=stub_decide)
    window = ReplayWindow(start="2024-01-02", end="2024-01-02", tickers=["AAPL"])

    run_daily_layer(
        _candidate(),
        window,
        make_fixture_dataport(),
        champion_decisions={},
        decide_fn=spy_decide,
        features_fn=_features_fn(tactical_bin="positive"),
    )

    call = spy_decide.call_args_list[0]
    passed_direction = call.args[1] if len(call.args) > 1 else call.kwargs["direction"]
    assert passed_direction == "LONG"


def test_negative_bin_drives_decide_with_short() -> None:
    """A `negative` bin ⇒ the SELECTED direction SHORT is passed to `decide`
    (SHORT is now reconstructable — the amendment's core fix)."""
    spy_decide = Mock(side_effect=lambda *a, **k: stub_decide(*a, decision="SHORT", **k))
    window = ReplayWindow(start="2024-01-02", end="2024-01-02", tickers=["AAPL"])

    results = run_daily_layer(
        _candidate(),
        window,
        make_fixture_dataport(),
        champion_decisions={},
        decide_fn=spy_decide,
        features_fn=_features_fn(tactical_bin="negative"),
    )

    call = spy_decide.call_args_list[0]
    passed_direction = call.args[1] if len(call.args) > 1 else call.kwargs["direction"]
    assert passed_direction == "SHORT"
    (rec,) = results
    assert rec.decision is not None
    assert rec.decision.decision == "SHORT"


def test_neutral_bin_is_flat_no_decide_call() -> None:
    """A `neutral` bin ⇒ a flat/no-trade day: `decide` is NEVER called, the
    record carries no `ReactiveDecision` (`decision is None`), and it does NOT
    count as divergent+actionable (a flat day needs no intraday re-fetch)."""
    spy_decide = Mock(side_effect=stub_decide)
    window = ReplayWindow(start="2024-01-02", end="2024-01-02", tickers=["AAPL"])
    pre_indexed = {("2024-01-02", "AAPL"): "LONG"}  # champion traded

    results = run_daily_layer(
        _candidate(),
        window,
        make_fixture_dataport(),
        champion_decisions=pre_indexed,
        decide_fn=spy_decide,
        features_fn=_features_fn(tactical_bin="neutral"),
    )

    spy_decide.assert_not_called()
    (rec,) = results
    assert rec.decision is None  # no decide call ⇒ no ReactiveDecision
    assert rec.tactical_bin == "neutral"  # the skip is attributable (12.5)
    assert rec.needs_intraday_refetch is False  # flat ⇒ no intraday path


def test_unavailable_bin_is_flat_distinguishable_from_neutral() -> None:
    """An `unavailable` bin is ALSO a flat day (no `decide`), but the record
    records WHICH bin it saw — so `unavailable` (12.4 bad data) is distinguishable
    from `neutral` (12.5 no edge), even though both halt new exposure. This is
    the literal `unavailable ≠ neutral` observability the bin read enables."""
    spy_decide = Mock(side_effect=stub_decide)
    window = ReplayWindow(start="2024-01-02", end="2024-01-02", tickers=["AAPL"])

    results = run_daily_layer(
        _candidate(),
        window,
        make_fixture_dataport(),
        champion_decisions={},
        decide_fn=spy_decide,
        features_fn=_features_fn(tactical_bin="unavailable"),
    )

    spy_decide.assert_not_called()
    (rec,) = results
    assert rec.decision is None
    assert rec.tactical_bin == "unavailable"
    assert rec.needs_intraday_refetch is False


def test_flat_day_distinguishable_from_hold_from_decide() -> None:
    """A flat day (`decision is None`) is distinguishable from a HOLD that the
    model RETURNED from `decide` (`decision is not None and
    decision.decision == "HOLD"`): a `positive` bin reaches `decide`, which
    returns HOLD — so the record carries a real `ReactiveDecision`, unlike the
    non-directional flat day."""
    candidate_hold = lambda *a, **k: stub_decide(*a, decision="HOLD", **k)  # noqa: E731
    window = ReplayWindow(start="2024-01-02", end="2024-01-02", tickers=["AAPL"])

    results = run_daily_layer(
        _candidate(),
        window,
        make_fixture_dataport(),
        champion_decisions={},
        decide_fn=candidate_hold,
        features_fn=_features_fn(tactical_bin="positive"),
    )

    (rec,) = results
    assert rec.decision is not None  # decide WAS called
    assert rec.decision.decision == "HOLD"  # ...and returned a HOLD
    assert rec.tactical_bin == "positive"  # a directional bin reached decide


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
        features_fn=_features_fn(tactical_bin="positive"),
    )

    (rec,) = results
    assert rec.decision is not None
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
        features_fn=_features_fn(tactical_bin="positive"),
    )

    (rec,) = results
    assert rec.decision is not None
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
        features_fn=_features_fn(tactical_bin="positive"),
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
        # A DIRECTIONAL bin so decide IS called and RETURNS a HOLD — a genuine
        # HOLD-from-decide (distinct from a non-directional flat day).
        features_fn=_features_fn(tactical_bin="positive"),
    )

    (rec,) = results
    assert rec.decision is not None
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
            features_fn=_features_fn(tactical_bin="positive"),
        )

    first = _run()
    second = _run()

    assert len(first) == len(second)
    for a, b in zip(first, second):
        assert a.as_of_day == b.as_of_day
        assert a.symbol == b.symbol
        assert (a.decision is None) == (b.decision is None)
        if a.decision is not None and b.decision is not None:
            assert a.decision.decision == b.decision.decision
            assert a.decision.probability == b.decision.probability
        assert a.tactical_bin == b.tactical_bin
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


# ============================================================================ #
# Task 2.4 — decision→order construction + survival admit gating.
#
# NON-BEHAVIORAL: MIRROR the execution-daemon `order_builder` rule (design line
# 144/355) — DO NOT import the daemon (boundary-forbidden). Drive the LANDED
# `src.survival.gate.admit` (real, not stub) for at least one test to prove the
# integration.
#
# decision→order rule (design `simulator` "Core algorithms #2"; daemon
# `order_builder` Req 11.1-11.6):
#   - P9 intent BUY/TRIM/SELL; SHORT-open = intent="BUY" + direction="SHORT".
#   - volume from `sizing_hint` capped by `per_order_size_max`.
#   - protective stop-loss PRICE LEVEL = reference ∓ (atr × stop_loss_atr_mult)
#     (− for LONG, + for SHORT); satisfies survival's mandatory-stop check.
#   - reduce/close clamped ≤ held volume (no flatten-then-flip in v0.1);
#     position_id targets the held position.
#   - HOLD / None decision ⇒ no order.
#
# admit gating (R3.2 sequential account path; R3.3 drive the landed core):
#   - admit=REJECT ⇒ no order (a flat day).
#   - an advisory_max_volume ⇒ resize to it (re-build + re-admit once).
# ============================================================================ #


# --- decision→order fixtures --------------------------------------------------


def _reactive_decision(
    *, decision: str, direction_in: str, sizing_hint: float | None
):
    """A synthetic landed `ReactiveDecision` carrying a chosen `sizing_hint`.

    Reuses the fixture `stub_decide` (the landed shape) but overrides the
    sizing_hint by rebuilding from its substrate — keeping it a real
    `ReactiveDecision`. `direction_in` is the SELECTED side (LONG/SHORT) and
    `decision` the act-or-hold call; `sizing_hint` is the advisory volume scalar.
    """
    from dataclasses import replace

    base = stub_decide(
        _feature_set(tactical_bin="positive"),
        direction_in if direction_in in ("LONG", "SHORT") else "LONG",
        DEFAULTS,
        decision=decision,
    )
    return replace(base, decision=decision, direction_in=direction_in, sizing_hint=sizing_hint)


def _healthy_account(positions: list[Position] | None = None) -> AccountState:
    """A healthy `AccountState` that clears admit's margin gate (high level)."""
    return AccountState(
        activated=True,
        equity=100_000.0,
        used_margin=1_000.0,
        free_margin=99_000.0,
        margin_level=10_000.0,  # equity/used_margin*100 — well above the buffer
        balance=100_000.0,
        stop_out_level=50.0,
        positions=positions or [],
    )


def _clear_op_state() -> OperationalState:
    """Op-state with no kill switch and grade NONE — admit's gates 1/2 pass."""
    return OperationalState(
        kill_switch_engaged=False,
        safe_mode_grade="NONE",
        entered_at=None,
        triggered_by=None,
    )


def _allow_evaluation() -> OrderEvaluation:
    """An `OrderEvaluation` whose fields all clear admit's screen gates (the
    reject-leaning defaults must be explicitly overridden — in-universe,
    not-excluded, a finite margin delta)."""
    return OrderEvaluation(
        additional_used_margin=10.0,  # finite + small ⇒ no buffer breach
        in_universe=True,
        is_excluded=False,
    )


def _clock() -> ClockState:
    return ClockState(session_open=True, seconds_to_next_closure=None)


# --- build_order: intent + direction (Req 11.1; SHORT-open = BUY+SHORT) -------


def test_build_order_long_open_is_buy_long() -> None:
    """A LONG decision with no held position ⇒ an OPEN: intent BUY, direction
    LONG (Req 11.1)."""
    decision = _reactive_decision(decision="LONG", direction_in="LONG", sizing_hint=0.5)
    order = build_order(
        decision,
        position=None,
        params=SURVIVAL_DEFAULTS,
        reference_price=100.0,
        atr=2.0,
    )
    assert order is not None
    assert order.intent == "BUY"
    assert order.direction == "LONG"


def test_build_order_short_open_is_buy_plus_direction_short() -> None:
    """A SHORT decision (open short exposure) ⇒ intent BUY + direction SHORT —
    NOT a SELL (Req 11.1: SHORT-open = BUY + Direction.SHORT)."""
    decision = _reactive_decision(decision="SHORT", direction_in="SHORT", sizing_hint=0.5)
    order = build_order(
        decision,
        position=None,
        params=SURVIVAL_DEFAULTS,
        reference_price=100.0,
        atr=2.0,
    )
    assert order is not None
    assert order.intent == "BUY"
    assert order.direction == "SHORT"


def test_build_order_hold_returns_no_order() -> None:
    """A HOLD decision ⇒ no order (a flat day) — the builder returns None."""
    decision = _reactive_decision(decision="HOLD", direction_in="LONG", sizing_hint=None)
    order = build_order(
        decision,
        position=None,
        params=SURVIVAL_DEFAULTS,
        reference_price=100.0,
        atr=2.0,
    )
    assert order is None


def test_build_order_none_decision_returns_no_order() -> None:
    """A flat day (decision is None) ⇒ no order."""
    order = build_order(
        None,
        position=None,
        params=SURVIVAL_DEFAULTS,
        reference_price=100.0,
        atr=2.0,
    )
    assert order is None


# --- build_order: volume cap (Req 11.2) ---------------------------------------


def test_build_order_volume_capped_by_per_order_size_max() -> None:
    """Volume from `sizing_hint` is capped by `params.per_order_size_max` (Req
    11.2) — a sizing_hint above the cap clamps to the cap (DEFAULTS cap = 1.0)."""
    decision = _reactive_decision(decision="LONG", direction_in="LONG", sizing_hint=5.0)
    order = build_order(
        decision,
        position=None,
        params=SURVIVAL_DEFAULTS,  # per_order_size_max = 1.0
        reference_price=100.0,
        atr=2.0,
    )
    assert order is not None
    assert order.volume == SURVIVAL_DEFAULTS.per_order_size_max == 1.0


# --- build_order: ATR protective stop-loss (Req 11.3) -------------------------


def test_build_order_long_stop_loss_is_reference_minus_atr_mult() -> None:
    """The protective stop-loss for a LONG is the PRICE LEVEL `reference − atr ×
    mult` (Req 11.3) — below the reference for a long."""
    decision = _reactive_decision(decision="LONG", direction_in="LONG", sizing_hint=0.5)
    order = build_order(
        decision,
        position=None,
        params=SURVIVAL_DEFAULTS,
        reference_price=100.0,
        atr=2.0,
        stop_loss_atr_mult=3.0,
    )
    assert order is not None
    assert order.stop_loss == 100.0 - 2.0 * 3.0  # 94.0


def test_build_order_short_stop_loss_is_reference_plus_atr_mult() -> None:
    """The protective stop-loss for a SHORT is `reference + atr × mult` (Req 11.3)
    — ABOVE the reference for a short (the symmetric side)."""
    decision = _reactive_decision(decision="SHORT", direction_in="SHORT", sizing_hint=0.5)
    order = build_order(
        decision,
        position=None,
        params=SURVIVAL_DEFAULTS,
        reference_price=100.0,
        atr=2.0,
        stop_loss_atr_mult=3.0,
    )
    assert order is not None
    assert order.stop_loss == 100.0 + 2.0 * 3.0  # 106.0


def test_build_order_default_mult_constant_used_when_unset() -> None:
    """The module default `DEFAULT_STOP_LOSS_ATR_MULT` is used when no mult is
    passed (the mult's authoritative home is daemon config, NOT survival params —
    a 2.5 revalidation seam)."""
    decision = _reactive_decision(decision="LONG", direction_in="LONG", sizing_hint=0.5)
    order = build_order(
        decision,
        position=None,
        params=SURVIVAL_DEFAULTS,
        reference_price=100.0,
        atr=2.0,
    )
    assert order is not None
    assert order.stop_loss == 100.0 - 2.0 * DEFAULT_STOP_LOSS_ATR_MULT


# --- build_order: reduce clamped ≤ held, no flip (Req 11.4/11.6) --------------


def test_build_order_reduce_clamped_to_held_no_flip() -> None:
    """An opposite-side decision against a held position is a REDUCE clamped ≤
    the held volume — NO flatten-then-flip in v0.1 (Req 11.6). A LONG decision
    sized 5.0 against a SHORT position of 0.4 ⇒ volume clamped to 0.4 (full
    close); the reduce is on the DECIDED side (LONG — opposite the held SHORT) so
    admit reads it as a true net-reducing exit (gate.py:457). Survival's
    `ProposedOrder` carries no `position_id` (the daemon→survival adaptation
    seam) — the reduce targets by SYMBOL."""
    held = Position(
        position_id="pos-1",
        symbol="AAPL",
        direction="SHORT",
        volume=0.4,
        avg_open_price=100.0,
        used_margin=40.0,
        unrealized_pnl=0.0,
    )
    decision = _reactive_decision(decision="LONG", direction_in="LONG", sizing_hint=5.0)
    order = build_order(
        decision,
        position=held,
        params=SURVIVAL_DEFAULTS,
        reference_price=100.0,
        atr=2.0,
        symbol="AAPL",
    )
    assert order is not None
    # Clamped to the held volume — never exceeds it (no flip past flat).
    assert order.volume <= held.volume == 0.4
    assert order.volume == 0.4
    # Reduce is on the DECIDED side (opposite the held SHORT) → admit-legal exit.
    assert order.direction == "LONG"
    assert order.intent == "SELL"  # full close (clamped == held)
    assert order.symbol == "AAPL"


def test_build_order_reduce_under_kill_switch_still_admit_allows() -> None:
    """A reduce against a held position is an admit TRUE-EXIT: even under an
    engaged kill switch the REAL `admit` short-circuits to ALLOW (fail-toward-flat,
    gate.py:549). This pins that the reduce direction is the DECIDED (opposite)
    side — a held-side direction would read as an add and REJECT under the kill
    switch."""
    held = Position(
        position_id="pos-1",
        symbol="AAPL",
        direction="SHORT",
        volume=0.4,
        avg_open_price=100.0,
        used_margin=40.0,
        unrealized_pnl=0.0,
    )
    decision = _reactive_decision(decision="LONG", direction_in="LONG", sizing_hint=0.3)
    killed = OperationalState(
        kill_switch_engaged=True,
        safe_mode_grade="NONE",
        entered_at=None,
        triggered_by="test-kill",
    )
    order = apply_admit_gating(
        decision,
        position=held,
        params=SURVIVAL_DEFAULTS,
        reference_price=100.0,
        atr=2.0,
        account=_healthy_account([held]),
        op_state=killed,
        evaluation=_allow_evaluation(),
        clock=_clock(),
        symbol="AAPL",
        admit_fn=None,  # REAL admit
    )
    assert order is not None  # the true-exit short-circuit ALLOWed it
    assert order.direction == "LONG"


# --- apply_admit_gating: drive the REAL landed admit (the integration proof) --


def test_actionable_long_drives_real_admit_to_allow_order() -> None:
    """An actionable LONG ⇒ apply_admit_gating drives the REAL landed
    `src.survival.gate.admit` and (account healthy, op-state clear, evaluation
    clearing) ⇒ an ALLOWED BUY+LONG order at the admit-cleared volume (R3.2/R3.3).
    Uses the REAL admit — the integration proof."""
    decision = _reactive_decision(decision="LONG", direction_in="LONG", sizing_hint=0.5)
    order = apply_admit_gating(
        decision,
        position=None,
        params=SURVIVAL_DEFAULTS,
        reference_price=100.0,
        atr=2.0,
        account=_healthy_account(),
        op_state=_clear_op_state(),
        evaluation=_allow_evaluation(),
        clock=_clock(),
        admit_fn=None,  # None ⇒ the REAL landed admit
    )
    assert order is not None
    assert order.intent == "BUY"
    assert order.direction == "LONG"
    assert order.volume == 0.5  # builder volume cleared admit (≤ per_order_size_max)
    assert order.stop_loss is not None


def test_actionable_short_drives_real_admit_to_allow_buy_short() -> None:
    """A SHORT decision ⇒ the REAL admit ALLOWs a BUY + direction SHORT order
    (SHORT-open = BUY+Direction.SHORT through the gate)."""
    decision = _reactive_decision(decision="SHORT", direction_in="SHORT", sizing_hint=0.5)
    order = apply_admit_gating(
        decision,
        position=None,
        params=SURVIVAL_DEFAULTS,
        reference_price=100.0,
        atr=2.0,
        account=_healthy_account(),
        op_state=_clear_op_state(),
        evaluation=_allow_evaluation(),
        clock=_clock(),
        admit_fn=None,
    )
    assert order is not None
    assert order.intent == "BUY"
    assert order.direction == "SHORT"


def test_admit_reject_yields_flat_real_admit() -> None:
    """admit=REJECT ⇒ no order (a flat day). Driven by the REAL admit: an engaged
    kill switch rejects the open ⇒ apply_admit_gating returns None (R3.2)."""
    decision = _reactive_decision(decision="LONG", direction_in="LONG", sizing_hint=0.5)
    killed = OperationalState(
        kill_switch_engaged=True,
        safe_mode_grade="NONE",
        entered_at=None,
        triggered_by="test-kill",
    )
    order = apply_admit_gating(
        decision,
        position=None,
        params=SURVIVAL_DEFAULTS,
        reference_price=100.0,
        atr=2.0,
        account=_healthy_account(),
        op_state=killed,
        evaluation=_allow_evaluation(),
        clock=_clock(),
        admit_fn=None,
    )
    assert order is None


def test_hold_yields_no_order_through_gating() -> None:
    """HOLD ⇒ no order even before admit runs (the builder returns None, so admit
    is never consulted)."""
    decision = _reactive_decision(decision="HOLD", direction_in="LONG", sizing_hint=None)
    order = apply_admit_gating(
        decision,
        position=None,
        params=SURVIVAL_DEFAULTS,
        reference_price=100.0,
        atr=2.0,
        account=_healthy_account(),
        op_state=_clear_op_state(),
        evaluation=_allow_evaluation(),
        clock=_clock(),
        admit_fn=None,
    )
    assert order is None


def test_none_decision_yields_no_order_through_gating() -> None:
    """A flat day (decision None) ⇒ no order, admit never consulted."""
    order = apply_admit_gating(
        None,
        position=None,
        params=SURVIVAL_DEFAULTS,
        reference_price=100.0,
        atr=2.0,
        account=_healthy_account(),
        op_state=_clear_op_state(),
        evaluation=_allow_evaluation(),
        clock=_clock(),
        admit_fn=None,
    )
    assert order is None


def test_admit_advisory_resizes_order(monkeypatch) -> None:
    """An admit `advisory_max_volume` ⇒ the order is RESIZED to it (re-build +
    re-admit once). Driven by an INJECTED stub admit (the 1.4-style isolation
    stub) — the builder-capped volume never trips the REAL admit's strictly-above
    size gate, so the advisory branch is exercised deterministically via a stub
    that REJECTs once with an advisory, then ALLOWs the resized order."""
    decision = _reactive_decision(decision="LONG", direction_in="LONG", sizing_hint=1.0)

    calls: list[float] = []

    def _stub_admit(order, state, op_state, params, clock, evaluation):  # noqa: ANN001
        calls.append(order.volume)
        if order.volume > 0.3:
            return AdmitDecision(
                decision="REJECT",
                binding_constraint="size_limit",
                advisory_max_volume=0.3,
                reason="over advisory cap",
            )
        return AdmitDecision(
            decision="ALLOW", binding_constraint=None, advisory_max_volume=None, reason=None
        )

    order = apply_admit_gating(
        decision,
        position=None,
        params=SURVIVAL_DEFAULTS,
        reference_price=100.0,
        atr=2.0,
        account=_healthy_account(),
        op_state=_clear_op_state(),
        evaluation=_allow_evaluation(),
        clock=_clock(),
        admit_fn=_stub_admit,
    )
    assert order is not None
    assert order.volume == 0.3  # resized to the advisory cap
    # Re-built + re-admitted once: the first call saw the capped volume (1.0), the
    # second the resized (0.3).
    assert calls == [1.0, 0.3]


def test_admit_gating_returns_proposed_order_type() -> None:
    """The gating step returns a survival `ProposedOrder` (the type `admit`
    consumes) on ALLOW — not a daemon-owned shape (boundary)."""
    decision = _reactive_decision(decision="LONG", direction_in="LONG", sizing_hint=0.5)
    order = apply_admit_gating(
        decision,
        position=None,
        params=SURVIVAL_DEFAULTS,
        reference_price=100.0,
        atr=2.0,
        account=_healthy_account(),
        op_state=_clear_op_state(),
        evaluation=_allow_evaluation(),
        clock=_clock(),
        admit_fn=None,
    )
    assert isinstance(order, ProposedOrder)


# ============================================================================ #
# Task 2.5 — fill realism (counterparty bid/ask, never mid) + intraday stop-hit.
#
# NON-BEHAVIORAL: MIRRORS the broker `paper.py` side-aware fill-pricing rule
# (its `_fill_price_from_action` block) rather than calling the real
# `paper.simulate` — the broker package uses bare `from models import ...`
# imports that ImportError under `src.mcp.broker.paper` from repo root (the 1.4
# agent + `_fixtures.stub_paper_simulate` documented this). The rule MIRRORED:
#
#   - paper.py prices the MARKETABLE side conservatively: a buy lifts the ASK, a
#     sell hits the BID. For an OPEN, the marketable side is the position
#     direction (open LONG → ask, open SHORT → bid). For a CLOSE, the marketable
#     side is the OPPOSITE of the held direction (close a LONG = sell → bid;
#     close a SHORT = buy → ask).
#   - In the REPLAY's `ProposedOrder` representation the `direction` field
#     ALREADY encodes the marketable side for both opens AND reduces (a reduce's
#     `direction` is the DECIDED side, opposite the held position — see
#     `_reduce_order`). So the mirror collapses to ONE uniform rule:
#       direction == "LONG"  → ASK ;  direction == "SHORT" → BID.
#     (Copying paper.py's two-branch close logic LITERALLY onto a `ProposedOrder`
#     would INVERT closes — paper.py keys its close branch on the *position*
#     direction, the replay order's `direction` is already the opposite. The
#     direction-convention difference is the broker-packaging revalidation seam
#     for 2.6.)
#   - Counterparty price comes from `fetch_quotes` `bp`/`ap` (the NBBO), NEVER
#     the mid (and never the `fetch_trades` price, which in the fixture == mid).
#
# Intraday stop-hit (6.2): a protective stop level (from 2.4's `ProposedOrder`)
# registers a hit iff it lies INSIDE the day's intraday low/high range —
# LONG stop hit if intraday low ≤ stop; SHORT stop hit if intraday high ≥ stop;
# a stop OUTSIDE the range does not. A stopped exit fills AT the stop level.
#
# Source of truth: requirements.md R6 AC 6.1/6.2; design.md `simulator`
# "Intraday layer" + test-plan line 268 ("fills price at the historical bid/ask
# side"; "a stop level inside the intraday range registers a stop-hit").
# ============================================================================ #


# --- fill-realism fixtures ----------------------------------------------------
# A quote whose bid/ask straddle a DISTINCT mid so "not mid" is discriminating:
# bid=101.50, ask=101.54 → mid=101.52 (the fixture `fetch_trades` price). An
# assertion on ask (101.54) or bid (101.50) is then provably ≠ mid.
_QUOTE_BID = 101.50
_QUOTE_ASK = 101.54
_QUOTE_MID = (_QUOTE_BID + _QUOTE_ASK) / 2.0  # 101.52 — what a mid-fill WOULD be


def _open_order(*, direction: str, volume: float = 0.5, stop_loss: float | None = None):
    """A directional OPEN `ProposedOrder` (intent BUY) on the decided side."""
    return ProposedOrder(
        symbol="AAPL",
        intent="BUY",
        direction=direction,
        volume=volume,
        stop_loss=stop_loss,
    )


def _quote_port():
    """A `FixtureDataPort` whose `fetch_quotes` returns the straddling NBBO."""
    return make_fixture_dataport()


# --- 6.1: fill at counterparty price, never mid -------------------------------


def test_buy_open_fills_at_ask_not_mid() -> None:
    """A BUY-open of a LONG fills at the historical ASK (the marketable buy side
    lifts the offer), NOT the mid (R6.1)."""
    order = _open_order(direction="LONG")
    fill = simulate_fill(order, port=_quote_port(), symbol="AAPL", ts="2024-01-31")
    assert isinstance(fill, Fill)
    assert fill.price == _QUOTE_ASK
    assert fill.price != _QUOTE_MID  # never the mid (R6.1)


def test_open_short_fills_at_bid() -> None:
    """An open-SHORT (sell-to-open) fills at the historical BID (the marketable
    sell side hits the bid), NOT the mid (R6.1)."""
    order = _open_order(direction="SHORT")
    fill = simulate_fill(order, port=_quote_port(), symbol="AAPL", ts="2024-01-31")
    assert fill.price == _QUOTE_BID
    assert fill.price != _QUOTE_MID


def test_close_long_fills_at_opposite_side_bid() -> None:
    """A CLOSE of a held LONG fills at the OPPOSITE side to the open — the close
    sells, so it hits the BID (R6.1). The reduce order's `direction` is the
    DECIDED side (SHORT, opposite the held LONG), so the uniform rule
    (SHORT→BID) correctly prices the close at bid — closing a long that OPENED at
    ask now fills at bid. A literal copy of paper.py's close branch (keyed on the
    *position* direction) would invert this to ask."""
    held = Position(
        position_id="p1",
        symbol="AAPL",
        direction="LONG",
        volume=0.5,
        avg_open_price=101.54,
        used_margin=10.0,
        unrealized_pnl=0.0,
    )
    close = build_order(
        _reactive_decision(decision="SHORT", direction_in="SHORT", sizing_hint=0.5),
        position=held,
        params=SURVIVAL_DEFAULTS,
        reference_price=100.0,
        atr=2.0,
        symbol="AAPL",
    )
    assert close is not None
    assert close.direction == "SHORT"  # decided side, opposite the held LONG
    fill = simulate_fill(close, port=_quote_port(), symbol="AAPL", ts="2024-01-31")
    assert fill.price == _QUOTE_BID  # sell-to-close hits the bid (opposite the ask open)


def test_close_short_fills_at_opposite_side_ask() -> None:
    """A CLOSE of a held SHORT fills at the OPPOSITE side — the close buys, so it
    lifts the ASK (R6.1). The reduce order's `direction` is LONG (opposite the
    held SHORT) → ASK."""
    held = Position(
        position_id="p2",
        symbol="AAPL",
        direction="SHORT",
        volume=0.5,
        avg_open_price=101.50,
        used_margin=10.0,
        unrealized_pnl=0.0,
    )
    close = build_order(
        _reactive_decision(decision="LONG", direction_in="LONG", sizing_hint=0.5),
        position=held,
        params=SURVIVAL_DEFAULTS,
        reference_price=100.0,
        atr=2.0,
        symbol="AAPL",
    )
    assert close is not None
    assert close.direction == "LONG"  # decided side, opposite the held SHORT
    fill = simulate_fill(close, port=_quote_port(), symbol="AAPL", ts="2024-01-31")
    assert fill.price == _QUOTE_ASK  # buy-to-close lifts the ask


def test_fill_carries_side_volume_and_iso_ts() -> None:
    """The `Fill` carries the order side, the requested volume, and an ISO ts —
    the quote `sip_timestamp` (nanoseconds) is normalized to ISO, never passed
    raw (the `OutcomeRecord.fills` contract, types.py)."""
    order = _open_order(direction="LONG", volume=0.7)
    fill = simulate_fill(order, port=_quote_port(), symbol="AAPL", ts="2024-01-31")
    assert fill.volume == 0.7
    assert fill.side == "LONG"
    # ISO, not a bare nanosecond integer.
    assert isinstance(fill.ts, str)
    assert "T" in fill.ts or fill.ts.count("-") >= 2
    assert "1706" not in fill.ts[:4]  # not the raw ns epoch leading digits


# --- 6.2: intraday stop-hit determination -------------------------------------
# The canned intraday path (fixtures `_CANNED_INTRADAY_BARS`) spans
# low=100.8 (bar 3 `l`) … high=102.1 (bar 2 `h`).
_INTRADAY_LOW = 100.8
_INTRADAY_HIGH = 102.1


def test_long_stop_inside_range_registers_hit() -> None:
    """A LONG protective stop INSIDE the day's intraday low/high range registers
    a hit (intraday low ≤ stop), and the exit fills AT the stop level (R6.2)."""
    stop = 101.0  # between low 100.8 and high 102.1 → hit (low 100.8 ≤ 101.0)
    order = _open_order(direction="LONG", stop_loss=stop)
    hit = detect_stop_hit(order, port=_quote_port(), symbol="AAPL", day="2024-01-31")
    assert hit is not None
    assert hit.price == stop  # fills at/through the stop level


def test_long_stop_outside_range_no_hit() -> None:
    """A LONG stop BELOW the day's intraday low (outside the range) does NOT
    register a hit (R6.2)."""
    stop = 100.0  # below intraday low 100.8 → never touched
    order = _open_order(direction="LONG", stop_loss=stop)
    hit = detect_stop_hit(order, port=_quote_port(), symbol="AAPL", day="2024-01-31")
    assert hit is None


def test_short_stop_inside_range_registers_hit() -> None:
    """A SHORT protective stop INSIDE the range registers a hit (intraday high ≥
    stop), exit fills at the stop level (R6.2)."""
    stop = 101.5  # between low 100.8 and high 102.1 → hit (high 102.1 ≥ 101.5)
    order = _open_order(direction="SHORT", stop_loss=stop)
    hit = detect_stop_hit(order, port=_quote_port(), symbol="AAPL", day="2024-01-31")
    assert hit is not None
    assert hit.price == stop


def test_short_stop_outside_range_no_hit() -> None:
    """A SHORT stop ABOVE the day's intraday high (outside the range) does NOT
    register a hit (R6.2)."""
    stop = 103.0  # above intraday high 102.1 → never touched
    order = _open_order(direction="SHORT", stop_loss=stop)
    hit = detect_stop_hit(order, port=_quote_port(), symbol="AAPL", day="2024-01-31")
    assert hit is None


def test_stop_hit_fill_side_is_exit_side() -> None:
    """A stopped LONG exits by SELLING — the stop-hit `Fill` carries the exit
    (opposite-to-position) side and the order's volume (R6.2)."""
    order = _open_order(direction="LONG", volume=0.4, stop_loss=101.0)
    hit = detect_stop_hit(order, port=_quote_port(), symbol="AAPL", day="2024-01-31")
    assert hit is not None
    assert hit.volume == 0.4
    # The exit of a LONG is a sell — recorded as the SHORT (opposite) side.
    assert hit.side == "SHORT"


def test_no_stop_level_never_hits() -> None:
    """An order carrying no `stop_loss` (None) can never register a stop-hit."""
    order = _open_order(direction="LONG", stop_loss=None)
    hit = detect_stop_hit(order, port=_quote_port(), symbol="AAPL", day="2024-01-31")
    assert hit is None


# ============================================================================ #
# Task 2.6 — §16.1 force-flatten before close + verify-flat post-condition.
#
# NON-BEHAVIORAL. The simulator plays BOTH the survival-gate's role (owns the
# flat-before-closure invariant + verify-flat + escalate — survival-gate R6) AND
# the daemon's role (executes the timed flatten) over historical data. At the
# day's close, any open position from the day MUST be flattened — emit the
# opposite-side close, fill it via `simulate_fill` (2.5) at the closing intraday
# quote — and then VERIFY the account is actually flat (net signed position ==
# 0), NOT merely that a close order was emitted (survival-gate R6.2). A verify-
# flat failure (no closing quote ⇒ `simulate_fill` raises) surfaces a distinct
# `flat_verify_failed` signal (survival-gate R6.3 escalate), never a silent
# carry-over.
#
# The four-scenario collapse (the correctness tell): the day's flatten target is
# whatever NET residual remains after the intraday path. A stop-hit already
# closed the position ⇒ net 0 ⇒ flatten is a no-op, still flat. A no-trade day ⇒
# net 0 ⇒ trivially flat. An open residual ⇒ emit the opposite-side close for
# |net|, fill, re-verify net 0.
#
# This produces the day's CLOSED round-trip (entry fill from 2.4/2.5 + exit fill
# from stop-hit OR flatten) the 2.7 P&L step consumes. 2.6 computes NO P&L (the
# §16.1 `(exit−entry)×vol×dir` formula is 2.7's).
#
# Source of truth: requirements.md R2 AC 2.3 (sequential account path honoring
# the §16.1 intraday-flat invariant); design.md `simulator` "Intraday layer"
# (force-flatten before close + verifiable flat post-condition) + Core-algorithms
# #3 (§16.1 flatten); survival-gate R6 (the gate owns the invariant + verify-flat
# + escalate; the daemon executes — the simulator plays both in replay).
# Requirements: 2.3.
# ============================================================================ #


from src.reactive.replay.simulator import (  # noqa: E402
    DayRoundTrip,
    flatten_before_close,
)
from tests.unit.reactive.replay._fixtures import FixtureDataPort  # noqa: E402


# --- 2.6 fixtures: a port whose closing quote is present / absent -------------


class _NoQuoteDataPort(FixtureDataPort):
    """A `FixtureDataPort` whose `fetch_quotes` carries NO NBBO row — so a close
    cannot be filled (`simulate_fill` raises `ValueError`). Defined LOCALLY in
    the test (the `_fixtures.py` provider is out of this task's boundary)."""

    def fetch_quotes(self, symbol: str, ts: str) -> dict:  # noqa: ANN001
        return {"results": []}


def _entry_fill(*, side: str, volume: float, price: float = 101.54) -> Fill:
    """The day's entry `Fill` (from 2.4/2.5) — `side` is the position direction."""
    return Fill(side=side, price=price, volume=volume, ts="2024-01-31")


# --- 2.3 / §16.1: an open position force-flattens before close ----------------


def test_open_long_force_flattens_before_close_and_verifies_flat() -> None:
    """A day with an open LONG position (no stop-hit) force-flattens before close:
    the opposite-side close is emitted + filled, and verify-flat confirms net 0
    (§16.1, survival-gate R6.1/R6.2)."""
    # A LONG entry whose stop (95.0) is BELOW the intraday low (100.8) → no
    # stop-hit during the day, so a residual remains to flatten at close.
    entry = _open_order(direction="LONG", volume=0.5, stop_loss=95.0)
    entry_fill = _entry_fill(side="LONG", volume=0.5)
    rt = flatten_before_close(
        entry,
        entry_fill=entry_fill,
        port=_quote_port(),
        symbol="AAPL",
        day="2024-01-31",
    )
    assert isinstance(rt, DayRoundTrip)
    assert rt.flat_verified is True
    # The exit is a flatten (not a stop-hit), recorded SHORT (opposite the LONG).
    assert rt.exit_reason == "flatten"
    assert rt.exit_fill is not None
    assert rt.exit_fill.side == "SHORT"
    assert rt.exit_fill.volume == 0.5
    # The close sells → hits the BID (the marketable sell side), never mid.
    assert rt.exit_fill.price == _QUOTE_BID
    assert "flatten" in rt.survival_events
    assert "flat_verify_failed" not in rt.survival_events


def test_open_short_force_flattens_before_close() -> None:
    """A day with an open SHORT position force-flattens before close — the close
    BUYS (recorded LONG), lifts the ASK, and verify-flat confirms net 0."""
    # A SHORT entry whose stop (110.0) is ABOVE the intraday high (102.1) → no hit.
    entry = _open_order(direction="SHORT", volume=0.3, stop_loss=110.0)
    entry_fill = _entry_fill(side="SHORT", volume=0.3, price=101.50)
    rt = flatten_before_close(
        entry,
        entry_fill=entry_fill,
        port=_quote_port(),
        symbol="AAPL",
        day="2024-01-31",
    )
    assert rt.flat_verified is True
    assert rt.exit_reason == "flatten"
    assert rt.exit_fill is not None
    assert rt.exit_fill.side == "LONG"  # buy-to-close, opposite the held SHORT
    assert rt.exit_fill.price == _QUOTE_ASK  # buy lifts the ask
    assert "flatten" in rt.survival_events


# --- 2.3 / §16.1: a stop-hit already exited → flatten is a no-op, still flat ---


def test_stop_hit_day_flatten_is_noop_still_flat() -> None:
    """A day already exited by a stop-hit (2.5): the close is a no-op — net is
    already 0 — and verify-flat still asserts flat. The exit is the STOP-HIT, not
    a flatten (survival-gate R6.2 — verify the post-condition, not the order)."""
    # A LONG stop (101.0) INSIDE the intraday range (low 100.8 ≤ 101.0) → the
    # position exits intraday; the close at day's end finds net 0.
    entry = _open_order(direction="LONG", volume=0.5, stop_loss=101.0)
    entry_fill = _entry_fill(side="LONG", volume=0.5)
    rt = flatten_before_close(
        entry,
        entry_fill=entry_fill,
        port=_quote_port(),
        symbol="AAPL",
        day="2024-01-31",
    )
    assert rt.flat_verified is True
    assert rt.exit_reason == "stop_hit"
    assert rt.exit_fill is not None
    assert rt.exit_fill.side == "SHORT"  # stopped LONG exits by selling
    assert rt.exit_fill.price == 101.0  # fills AT the stop level
    assert "stop_hit" in rt.survival_events
    # No flatten order was needed (the stop already flattened it).
    assert "flatten" not in rt.survival_events
    assert "flat_verify_failed" not in rt.survival_events


# --- 2.3 / §16.1: the closing fill can't be obtained → flatten-failure signal --


def test_unfillable_close_raises_flatten_failure_not_silent_carry() -> None:
    """A day where the closing fill CANNOT be obtained (no closing quote): the
    verify-flat post-condition FAILS — surfaced as a distinct `flat_verify_failed`
    signal (survival-gate R6.3 escalate), NOT a silent carry-over. The replay
    must not crash (no `ValueError` propagates) and must not pretend flat."""
    entry = _open_order(direction="LONG", volume=0.5, stop_loss=95.0)  # no stop-hit
    entry_fill = _entry_fill(side="LONG", volume=0.5)
    rt = flatten_before_close(
        entry,
        entry_fill=entry_fill,
        port=_NoQuoteDataPort(),  # closing quote absent → unfillable close
        symbol="AAPL",
        day="2024-01-31",
    )
    assert rt.flat_verified is False  # NOT flat — the close could not fill
    assert "flat_verify_failed" in rt.survival_events
    assert rt.exit_fill is None  # no exit fill obtained (not a fabricated one)


# --- 2.3 / §16.1: a flat (no-trade) day is trivially flat ----------------------


def test_no_trade_day_is_trivially_flat() -> None:
    """A flat (no-trade) day — no entry order/fill — is trivially flat: no exit,
    no flatten, no escalation (§16.1 holds vacuously)."""
    rt = flatten_before_close(
        None,
        entry_fill=None,
        port=_quote_port(),
        symbol="AAPL",
        day="2024-01-31",
    )
    assert rt.flat_verified is True
    assert rt.entry_fill is None
    assert rt.exit_fill is None
    assert rt.exit_reason is None
    assert rt.survival_events == []


# --- 2.6: the closed round-trip shape the 2.7 P&L step consumes ----------------


def test_round_trip_carries_entry_and_exit_for_pnl_seam() -> None:
    """The `DayRoundTrip` carries the entry fill + the exit fill (stop-hit OR
    flatten) — entry price, exit price, volume, and direction — everything the
    2.7 §16.1 `(exit−entry)×vol×dir` P&L step needs. 2.6 computes NO P&L."""
    entry = _open_order(direction="LONG", volume=0.5, stop_loss=95.0)
    entry_fill = _entry_fill(side="LONG", volume=0.5, price=101.54)
    rt = flatten_before_close(
        entry,
        entry_fill=entry_fill,
        port=_quote_port(),
        symbol="AAPL",
        day="2024-01-31",
    )
    assert rt.symbol == "AAPL"
    assert rt.entry_fill is entry_fill  # entry price + volume + direction
    assert rt.exit_fill is not None  # exit price (the flatten leg)
    # The shape carries no P&L field (2.7's concern) — only the legs.
    assert not hasattr(rt, "total_return_pnl")
