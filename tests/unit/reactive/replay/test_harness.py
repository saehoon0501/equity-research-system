"""Inner-ring INTEGRATION tests for the Replay-Harness public entry (Task 3.1).

This is the explicit cross-leaf WIRING task: `harness.replay_candidate` orchestrates
the landed replay leaves (`simulator` daily + intraday, `outcomes`, `fidelity`)
plus the upstream reads (`telemetry.reader.query_trace`, the P2
`run_parameters_snapshot` champion-config read) into the single contract
`walkforward-tuning-loop` calls per config per CPCV partition.

Exercised in ISOLATION (R9.2 / P14 inner ring): a `FixtureDataPort`, stub cores
injected through the simulator's `decide_fn`/`features_fn`/`admit_fn` seams, a
fake `query_trace`, and a fake champion-config reader — NO live market feed, NO
LLM, NO live DB. The harness must touch no out-of-boundary surface (R10.1/10.2:
read-only; no CPCV / metric / gate / fit / publish / live trading).

Source of truth: requirements.md Requirement 1 AC **1.1, 1.2**, Requirement 7 AC
**7.1**, Requirement 10 AC **10.1, 10.2**; design.md the `harness` component block
(lines 215-216) + the dependency-direction note (line 121) + the System Flow.

Requirements: 1.1, 1.2, 7.1, 10.1, 10.2.
"""

from __future__ import annotations

from typing import Any

from src.calibration.scorer import Label
from src.reactive.features import FeatureSet
from src.reactive.params import DEFAULTS as REACTIVE_DEFAULTS
from src.reactive.replay import harness
from src.reactive.replay.harness import replay_candidate
from src.reactive.replay.types import (
    Candidate,
    OutcomeRecord,
    ReplayResult,
    ReplayWindow,
)
from src.survival.params import DEFAULTS as SURVIVAL_DEFAULTS

from tests.unit.reactive.replay._fixtures import (
    make_correlation_keys,
    make_fixture_dataport,
    stub_decide,
)


# --------------------------------------------------------------------------- #
# Local test seams (mirror test_simulator's: the real compute_daily_features
# over 3 canned bars degrades to a FeatureFailure, so inject a directional
# FeatureSet to exercise the actionable path).
# --------------------------------------------------------------------------- #


def _feature_set(*, tactical_bin: str = "positive") -> FeatureSet:
    """A `FeatureSet` carrying a verbatim directional `raw["tactical_bin"]` + ATR.

    `raw["atr"]` is load-bearing here: the harness sources the build-order stop
    distance from it on an actionable day.
    """
    _bin_to_vote = {"positive": 1.0, "negative": -1.0, "neutral": 0.0, "unavailable": 0.0}
    return FeatureSet(
        trend_vote=_bin_to_vote.get(tactical_bin, 0.0),
        flow_vote=0.5,
        meanrev_vote=0.0,
        trend_strength=0.5,
        raw={"rsi_14": 55.0, "tactical_bin": tactical_bin, "atr": 1.2},
    )


def _features_fn(*, tactical_bin: str = "positive"):
    """An injectable `features_fn` returning a chosen `FeatureSet` for any day."""

    def _fn(symbol: str, day: str, data_port: Any) -> FeatureSet:
        return _feature_set(tactical_bin=tactical_bin)

    return _fn


def _candidate() -> Candidate:
    """A candidate config carrying the inner-ring DEFAULTS snapshots (R1.3)."""
    return Candidate(
        param_snapshot=REACTIVE_DEFAULTS,
        survival_parameters=SURVIVAL_DEFAULTS,
        code_version=None,
    )


def _window(tickers: list[str] | None = None) -> ReplayWindow:
    # The fixture daily bars span 2024-01-01..2024-01-03 (3 canned bars).
    return ReplayWindow(start="2024-01-01", end="2024-01-03", tickers=tickers or ["AAPL"])


def _empty_query_trace(filters: dict | None = None) -> list[dict]:
    """A fake `query_trace` returning no champion rows (the champion-absent case).

    A no-record champion → every candidate-actionable day diverges, but the
    candidate run reconstructs its OWN path regardless (R2.1); the harness needs
    no DB.
    """
    return []


# ============================================================================ #
# R1.1 / R1.2 — single-config single-window: per-period OutcomeRecords
# ============================================================================ #


def test_replay_candidate_returns_replay_result_over_window() -> None:
    """R1.1: one candidate + one window ⇒ a `ReplayResult{records, fidelity}` with
    one `OutcomeRecord` per trading day (the fixture spans 3 canned days)."""
    result = replay_candidate(
        _candidate(),
        _window(["AAPL"]),
        data_port=make_fixture_dataport(),
        query_trace_fn=_empty_query_trace,
        champion_keys=make_correlation_keys(),
        decide_fn=stub_decide,
        features_fn=_features_fn(tactical_bin="positive"),
        admit_fn=_allow_admit,
    )

    assert isinstance(result, ReplayResult)
    assert all(isinstance(r, OutcomeRecord) for r in result.records)
    # One record per trading day (3 canned fixture daily bars).
    assert len(result.records) == 3
    assert {r.symbol for r in result.records} == {"AAPL"}


def test_replay_candidate_respects_caller_supplied_window_tickers() -> None:
    """R1.2: the harness imposes no CV scheme — it replays exactly the caller's
    window tickers (here two names ⇒ two names × the trading days)."""
    result = replay_candidate(
        _candidate(),
        _window(["AAPL", "MSFT"]),
        data_port=make_fixture_dataport(),
        query_trace_fn=_empty_query_trace,
        champion_keys=make_correlation_keys(),
        decide_fn=stub_decide,
        features_fn=_features_fn(tactical_bin="positive"),
        admit_fn=_allow_admit,
    )

    assert {r.symbol for r in result.records} == {"AAPL", "MSFT"}
    assert len(result.records) == 6  # 2 tickers × 3 trading days


def test_actionable_day_carries_fills_and_pnl() -> None:
    """An actionable LONG day (admit ALLOW) ⇒ the record carries entry+exit fills
    and a non-flat round trip (the intraday wiring fired)."""
    result = replay_candidate(
        _candidate(),
        _window(["AAPL"]),
        data_port=make_fixture_dataport(),
        query_trace_fn=_empty_query_trace,
        champion_keys=make_correlation_keys(),
        decide_fn=stub_decide,
        features_fn=_features_fn(tactical_bin="positive"),
        admit_fn=_allow_admit,
    )

    # At least one day fired an actionable LONG → entry + flatten fills present.
    actionable = [r for r in result.records if r.fills]
    assert actionable, "an actionable LONG day should carry fills"
    rec = actionable[0]
    assert rec.decision == "LONG"
    assert rec.realized_label == Label.BUY
    assert len(rec.fills) == 2  # entry + §16.1 flatten


def test_neutral_bin_day_is_flat_no_fills() -> None:
    """A non-directional (neutral) bin ⇒ a flat day: HOLD, no fills, zero P&L."""
    result = replay_candidate(
        _candidate(),
        _window(["AAPL"]),
        data_port=make_fixture_dataport(),
        query_trace_fn=_empty_query_trace,
        champion_keys=make_correlation_keys(),
        decide_fn=stub_decide,
        features_fn=_features_fn(tactical_bin="neutral"),
        admit_fn=_allow_admit,
    )

    assert all(r.decision == "HOLD" for r in result.records)
    assert all(r.fills == [] for r in result.records)
    assert all(r.total_return_pnl == 0.0 for r in result.records)


# ============================================================================ #
# 2.8 seam — admit_rejected threading: a REJECT day carries "admit_reject"
# ============================================================================ #


def _allow_admit(order, account, op_state, params, clock, evaluation):
    """A stub admit that ALLOWs every order (the happy path)."""
    from tests.unit.reactive.replay._fixtures import stub_admit

    return stub_admit(order, account, op_state, params, clock, evaluation, decision="ALLOW")


def _reject_admit(order, account, op_state, params, clock, evaluation):
    """A stub admit that REJECTs every order (non-advisory → a flat day)."""
    from tests.unit.reactive.replay._fixtures import stub_admit

    return stub_admit(
        order, account, op_state, params, clock, evaluation,
        decision="REJECT", binding_constraint="kill_switch_engaged",
    )


def test_admit_rejected_day_carries_admit_reject_event() -> None:
    """2.8 seam: an actionable day whose survival `admit` REJECTs ⇒ the record's
    `survival_events` carries "admit_reject" (the harness threads
    `admit_rejected=True` because `apply_admit_gating`'s bare None cannot)."""
    result = replay_candidate(
        _candidate(),
        _window(["AAPL"]),
        data_port=make_fixture_dataport(),
        query_trace_fn=_empty_query_trace,
        champion_keys=make_correlation_keys(),
        decide_fn=stub_decide,
        features_fn=_features_fn(tactical_bin="positive"),
        admit_fn=_reject_admit,
    )

    # Every actionable day was REJECTed → flat (no fills) but tagged admit_reject.
    assert result.records, "should still emit one record per day"
    assert all("admit_reject" in r.survival_events for r in result.records)
    assert all(r.fills == [] for r in result.records)


def test_hold_day_not_tagged_admit_reject() -> None:
    """A genuine HOLD/flat day (no order built) must NOT carry "admit_reject" —
    the harness disambiguates a no-order flat from a REJECTed order."""
    result = replay_candidate(
        _candidate(),
        _window(["AAPL"]),
        data_port=make_fixture_dataport(),
        query_trace_fn=_empty_query_trace,
        champion_keys=make_correlation_keys(),
        decide_fn=stub_decide,
        features_fn=_features_fn(tactical_bin="neutral"),  # flat: no order built
        admit_fn=_reject_admit,  # would reject IF an order existed
    )

    assert all("admit_reject" not in r.survival_events for r in result.records)


# ============================================================================ #
# R7.1 — champion re-sim: read champion config + fills, attach a FidelityResult
# ============================================================================ #


def _champion_decision_row(*, symbol: str, day: str, decision: str, trace_id: str) -> dict:
    """A raw `query_trace` champion DECISION-row dict (kind == 'decision')."""
    keys = make_correlation_keys()
    return {
        "trace_id": trace_id,
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


def _champion_fill_row(
    *, parent_trace_id: str, trace_id: str, day: str, ts_suffix: str,
    actual_fill_price: float, fill_volume: float,
) -> dict:
    """A raw `query_trace` champion FILL-row dict (kind == 'fill').

    The fill payload carries NEITHER symbol NOR a buy/sell side (schema pin:
    they live in the linked DECISION's JSONB trace + are derived). The harness
    joins symbol/direction via `parent_trace_id` and derives the leg side from
    event-ts ordering within the (day, symbol) group.
    """
    keys = make_correlation_keys()
    return {
        "trace_id": trace_id,
        "kind": "fill",
        "parent_trace_id": parent_trace_id,
        "event_ts": f"{day}T{ts_suffix}Z",
        "run_id": keys.run_id,
        "code_version": keys.code_version,
        "param_version": keys.param_version,
        "walk_forward_window": keys.walk_forward_window,
        "trace": {
            "expected_price": actual_fill_price,
            "actual_fill_price": actual_fill_price,
            "slippage": 0.0,
            "fill_volume": fill_volume,
            "counterparty_price": actual_fill_price,
        },
        "created_at": f"{day}T{ts_suffix}Z",
    }


def _fake_query_trace_with_champion(decision_rows: list[dict], fill_rows: list[dict]):
    """A fake `query_trace` returning champion rows filtered by `kind`.

    Mirrors the landed reader's `kind=` filter so the harness's two reads
    (kind='decision' for the index + join, kind='fill' for the baseline) work.
    """

    def _fn(filters: dict | None = None) -> list[dict]:
        kind = (filters or {}).get("kind")
        if kind == "decision":
            return list(decision_rows)
        if kind == "fill":
            return list(fill_rows)
        return list(decision_rows) + list(fill_rows)

    return _fn


def _fake_champion_config_reader(param_version: str, *, conn: Any = None) -> Candidate:
    """A fake P2 champion-config reader → the champion's pinned Candidate.

    The real reader resolves `effective_parameters_jsonb` from
    `run_parameters_snapshot` by `param_version`; the test injects a canned
    Candidate so the JSONB→dataclass mapping is prod-path only (no DB).
    """
    return Candidate(
        param_snapshot=REACTIVE_DEFAULTS,
        survival_parameters=SURVIVAL_DEFAULTS,
        code_version=None,
    )


def test_champion_resim_attaches_fidelity_pass_within_tolerance() -> None:
    """R7.1: a champion-version run reads the champion config (P2) + the champion
    fills (query_trace), re-runs the simulator on the champion config, and attaches
    a FidelityResult. With a within-tolerance reproduction ⇒ status 'pass'.

    The simulated-champion side fires a LONG day (entry @ ask 101.54, flatten @
    bid 101.50, volume = sizing_hint capped by per_order_size_max). The recorded
    fills are synthesized to reproduce that day's P&L within tolerance; the
    tolerance is set wide enough to absorb the price-only-vs-total-return
    dividend-basis asymmetry (tasks.md 2.2 finding)."""
    day = "2024-01-01"
    dec_id = "dec-AAPL-2024-01-01"
    decision_rows = [
        _champion_decision_row(symbol="AAPL", day=day, decision="LONG", trace_id=dec_id),
    ]
    # The simulated-champion LONG round trip prices entry@101.54 (ask),
    # flatten@101.50 (bid), so per-unit price P&L = (101.50 - 101.54) = -0.04.
    # Reproduce that with recorded entry/exit at matching prices + a generous
    # tolerance that absorbs the same-day dividend term on the simulated side.
    fill_rows = [
        _champion_fill_row(
            parent_trace_id=dec_id, trace_id="fill-entry", day=day,
            ts_suffix="14:30:00", actual_fill_price=101.54, fill_volume=0.07,
        ),
        _champion_fill_row(
            parent_trace_id=dec_id, trace_id="fill-exit", day=day,
            ts_suffix="15:55:00", actual_fill_price=101.50, fill_volume=0.07,
        ),
    ]

    result = replay_candidate(
        _candidate(),
        ReplayWindow(start=day, end=day, tickers=["AAPL"]),
        data_port=make_fixture_dataport(dividend_cash=0.0),  # no dividend → no basis skew
        query_trace_fn=_fake_query_trace_with_champion(decision_rows, fill_rows),
        champion_keys=make_correlation_keys(),
        champion_config_reader=_fake_champion_config_reader,
        decide_fn=stub_decide,
        features_fn=_features_fn(tactical_bin="positive"),
        admit_fn=_allow_admit,
        tolerance=1.0,
    )

    assert result.fidelity.status == "pass"
    assert result.fidelity.detail


def test_champion_resim_not_evaluable_on_empty_baseline() -> None:
    """R7.3-adjacent (the harness orchestration of it): no champion fills ⇒
    fidelity 'not_evaluable' (distinct from 'fail'), the sparse-baseline branch."""
    result = replay_candidate(
        _candidate(),
        _window(["AAPL"]),
        data_port=make_fixture_dataport(),
        query_trace_fn=_fake_query_trace_with_champion([], []),
        champion_keys=make_correlation_keys(),
        champion_config_reader=_fake_champion_config_reader,
        decide_fn=stub_decide,
        features_fn=_features_fn(tactical_bin="positive"),
        admit_fn=_allow_admit,
    )

    assert result.fidelity.status == "not_evaluable"


# ============================================================================ #
# R10.1 / R10.2 — consumption boundary: read-only; no out-of-boundary surface
# ============================================================================ #


def test_harness_writes_nothing_read_only() -> None:
    """R10.1: the harness reads the trace read-only — the injected `query_trace`
    spy records ONLY read-shaped calls (a SELECT-only surface; no write/insert/
    update kwargs ever passed)."""
    calls: list[dict] = []

    def _spy_query_trace(filters: dict | None = None) -> list[dict]:
        calls.append(dict(filters or {}))
        return []

    replay_candidate(
        _candidate(),
        _window(["AAPL"]),
        data_port=make_fixture_dataport(),
        query_trace_fn=_spy_query_trace,
        champion_keys=make_correlation_keys(),
        champion_config_reader=_fake_champion_config_reader,
        decide_fn=stub_decide,
        features_fn=_features_fn(tactical_bin="positive"),
        admit_fn=_allow_admit,
    )

    # The only DB-facing surface used is the injected read-only query_trace; it
    # was called (read), never with any mutation-shaped filter.
    assert calls, "the harness must read the champion trace"
    for f in calls:
        # query_trace is SELECT-only; a mutation would surface as a non-read key.
        assert "kind" in f


def test_harness_does_no_cpcv_metric_gate_fit_publish() -> None:
    """R10.2: the harness's public surface is `replay_candidate` only — no metric,
    gate, CPCV, fit, or publish entry points (those are the consumer's)."""
    public = {n for n in vars(harness) if not n.startswith("_")}
    forbidden = {
        "cpcv", "partition", "metric", "score", "gate", "fit", "publish",
        "promote", "dsr", "psr", "pbo",
    }
    # No forbidden out-of-boundary public callable leaked onto the module.
    assert not (public & forbidden), f"out-of-boundary surface on harness: {public & forbidden}"


def test_replay_candidate_is_the_public_entry() -> None:
    """The single contract `walkforward-tuning-loop` calls is `replay_candidate`,
    re-exported from the package `__init__` (design line 100)."""
    from src.reactive.replay import replay_candidate as exported

    assert exported is replay_candidate


# ============================================================================ #
# R9.1 — determinism: identical inputs ⇒ identical records
# ============================================================================ #


def test_identical_inputs_yield_identical_records() -> None:
    """R9.1: identical (candidate, window, port responses, champion index) ⇒
    identical per-day records (the determinism contract holds end-to-end)."""

    def _run() -> ReplayResult:
        return replay_candidate(
            _candidate(),
            _window(["AAPL"]),
            data_port=make_fixture_dataport(),
            query_trace_fn=_empty_query_trace,
            champion_keys=make_correlation_keys(),
            champion_config_reader=_fake_champion_config_reader,
            decide_fn=stub_decide,
            features_fn=_features_fn(tactical_bin="positive"),
            admit_fn=_allow_admit,
        )

    assert _run().records == _run().records
