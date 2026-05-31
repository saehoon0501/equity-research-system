"""Unit tests for the Replay-Harness `outcomes` leaf (Task 2.8 / R8.1, R8.2).

NON-BEHAVIORAL record-assembly tests for the FINAL simulator-side leaf — the
per-period `OutcomeRecord` assembler. The leaf takes the simulator's per-day
pieces (the 2.3 `DailyDecision`, the 2.6 `DayRoundTrip`, and the 2.7
`day_round_trip_pnl` float) and assembles ONE `OutcomeRecord` per trading day.
It computes NO survival-net metric, NO calibration, and NO gate (R8.2 — those
are the consumer `walkforward-tuning-loop`'s); it exposes ONLY record assembly.

Source of truth: requirements.md R8 AC 8.1/8.2; design.md `outcomes + harness`
("assemble the per-period `OutcomeRecord{...}` from simulator output; computes
**no** survival-net metric, calibration, or gate") + the `OutcomeRecord`
Data-Models block (the 9 pinned fields) + design line 202 (HOLD / admit=REJECT
⇒ a flat day) + the simulator's §16.1 exit-leg `survival_events` subset
(`stop_hit`/`flatten`/`flat_verify_failed`) vs 2.4's `admit_reject`.

These tests ride only the landed in-memory contracts (`DailyDecision`,
`DayRoundTrip`, `Fill`, `ReactiveDecision`, `OutcomeRecord`, `Label`) — no
network / DB / LLM / live feed (R9.2 isolation).

Requirements: 8.1, 8.2.
"""

from __future__ import annotations

from src.calibration.scorer import Label
from src.reactive.replay import outcomes
from src.reactive.replay.simulator import DailyDecision, DayRoundTrip
from src.reactive.replay.types import Fill, OutcomeRecord
from src.reactive.types import (
    CalibrationEvidence,
    DecisionSubstrate,
    Direction,
    ReactiveDecision,
)

DAY = "2024-03-07"
SYMBOL = "AAPL"


# --- Builders (the landed per-day shapes the assembler consumes) -----------


def _substrate(probability: float) -> DecisionSubstrate:
    return DecisionSubstrate(
        feature_values={"rsi_14": 55.0},
        probability=probability,
        effective_threshold=0.55,
        code_version="stub-code-v0",
        param_version="stub-param-v0",
        calibration=CalibrationEvidence(brier=None, reliability=None),
    )


def _reactive_decision(
    decision: str = "LONG",
    direction: Direction = "LONG",
    probability: float = 0.62,
) -> ReactiveDecision:
    actionable = decision != "HOLD"
    return ReactiveDecision(
        decision=decision,  # type: ignore[arg-type]
        direction_in=direction,
        probability=probability,
        sizing_hint=(probability - 0.55) if actionable else None,
        non_final=True,
        reason=None if actionable else "invalid_direction",
        substrate=_substrate(probability),
    )


def _daily(
    decision: ReactiveDecision | None,
    *,
    diverged: bool = False,
    needs_intraday_refetch: bool = False,
    champion_decision: str = "HOLD",
) -> DailyDecision:
    return DailyDecision(
        as_of_day=DAY,
        symbol=SYMBOL,
        decision=decision,
        tactical_bin="strong_uptrend" if decision is not None else "neutral",
        champion_decision=champion_decision,  # type: ignore[arg-type]
        diverged=diverged,
        needs_intraday_refetch=needs_intraday_refetch,
    )


def _entry_fill() -> Fill:
    return Fill(side="LONG", price=100.0, volume=10.0, ts=f"{DAY}T14:30:00Z")


def _exit_fill(reason_side: str = "SHORT", price: float = 101.0) -> Fill:
    return Fill(side=reason_side, price=price, volume=10.0, ts=f"{DAY}T19:55:00Z")


def _flat_round_trip() -> DayRoundTrip:
    """A no-trade day — trivially flat, no legs (mirrors flatten_before_close)."""
    return DayRoundTrip(
        symbol=SYMBOL,
        entry_fill=None,
        exit_fill=None,
        exit_reason=None,
        flat_verified=True,
        survival_events=[],
    )


def _flatten_round_trip() -> DayRoundTrip:
    """A §16.1 close-flattened round-trip (exit_reason='flatten')."""
    return DayRoundTrip(
        symbol=SYMBOL,
        entry_fill=_entry_fill(),
        exit_fill=_exit_fill(price=101.0),
        exit_reason="flatten",
        flat_verified=True,
        survival_events=["flatten"],
    )


def _stop_hit_round_trip() -> DayRoundTrip:
    """An intraday stop-hit round-trip (exit_reason='stop_hit')."""
    return DayRoundTrip(
        symbol=SYMBOL,
        entry_fill=_entry_fill(),
        exit_fill=_exit_fill(price=98.0),
        exit_reason="stop_hit",
        flat_verified=True,
        survival_events=["stop_hit"],
    )


# --- R8.1: a record carries all 9 fields, populated from the per-day pieces -


def test_record_carries_all_nine_fields_from_per_day_pieces():
    daily = _daily(_reactive_decision(decision="LONG", probability=0.62))
    round_trip = _flatten_round_trip()
    pnl = 10.0  # the day_round_trip_pnl float

    rec = outcomes.assemble_outcome(daily, round_trip, pnl)

    assert isinstance(rec, OutcomeRecord)
    # 1 period, 2 symbol, 3 decision, 4 predicted_probability
    assert rec.period == DAY
    assert rec.symbol == SYMBOL
    assert rec.decision == "LONG"
    assert rec.predicted_probability == 0.62
    # 5 fills = entry + exit Fills of the day
    assert rec.fills == [round_trip.entry_fill, round_trip.exit_fill]
    # 6 total_return_pnl = the day_round_trip_pnl float (verbatim)
    assert rec.total_return_pnl == pnl
    # 7 survival_events: the day's exit-leg subset (no admit_reject here)
    assert rec.survival_events == ["flatten"]
    # 8 realized_outcome = the day's realized round-trip return (the P&L)
    assert rec.realized_outcome == pnl
    # 9 realized_label = the 4-bin Label mapped from the decision
    assert rec.realized_label == Label.BUY


def test_short_decision_maps_to_sell_label():
    daily = _daily(_reactive_decision(decision="SHORT", direction="SHORT"))
    rec = outcomes.assemble_outcome(daily, _flatten_round_trip(), -5.0)
    assert rec.decision == "SHORT"
    assert rec.realized_label == Label.SELL


# --- R8.1: a flat day → HOLD, no fills, 0 P&L, predicted_probability None ----


def test_flat_day_maps_to_hold_no_fills_zero_pnl_none_probability():
    # A non-directional flat day: DailyDecision.decision is None (design L188-194).
    daily = _daily(None)
    rec = outcomes.assemble_outcome(daily, _flat_round_trip(), 0.0)

    assert rec.decision == "HOLD"
    assert rec.fills == []
    assert rec.total_return_pnl == 0.0
    assert rec.realized_outcome == 0.0
    assert rec.predicted_probability is None
    assert rec.realized_label == Label.HOLD


def test_model_returned_hold_maps_to_hold_with_its_probability():
    # A HOLD the model RETURNED (not a None flat day) still carries its prob.
    daily = _daily(_reactive_decision(decision="HOLD", probability=0.51))
    rec = outcomes.assemble_outcome(daily, _flat_round_trip(), 0.0)
    assert rec.decision == "HOLD"
    assert rec.predicted_probability == 0.51
    assert rec.realized_label == Label.HOLD


# --- R8.1: an admit-rejected day → survival_events includes "admit_reject" ---


def test_admit_rejected_day_includes_admit_reject_event():
    # The candidate decided LONG but survival admit REJECTED it ⇒ a flat day,
    # but the survival_events must record the "admit_reject" tag (2.4's tag,
    # passed in explicitly — apply_admit_gating's bare None cannot carry it).
    daily = _daily(_reactive_decision(decision="LONG"), diverged=True)
    rec = outcomes.assemble_outcome(
        daily, _flat_round_trip(), 0.0, admit_rejected=True
    )
    assert "admit_reject" in rec.survival_events


def test_admit_reject_prepends_to_exit_leg_events():
    # admit_reject is 2.4's; it leads the day list, then the exit-leg subset.
    daily = _daily(_reactive_decision(decision="LONG"))
    rec = outcomes.assemble_outcome(
        daily, _stop_hit_round_trip(), -20.0, admit_rejected=True
    )
    assert rec.survival_events == ["admit_reject", "stop_hit"]


# --- R8.1: a stop-hit day → survival_events includes "stop_hit" --------------


def test_stop_hit_day_includes_stop_hit_event():
    daily = _daily(_reactive_decision(decision="LONG"))
    rec = outcomes.assemble_outcome(daily, _stop_hit_round_trip(), -20.0)
    assert "stop_hit" in rec.survival_events
    assert rec.fills == [
        _stop_hit_round_trip().entry_fill,
        _stop_hit_round_trip().exit_fill,
    ]


def test_survival_events_is_a_fresh_list_not_aliasing_round_trip():
    # Determinism / no-mutation hygiene (R9.1): the assembled list must not be
    # the same object as DayRoundTrip.survival_events (else a caller appending
    # admit_reject would mutate the frozen round-trip's list).
    round_trip = _flatten_round_trip()
    daily = _daily(_reactive_decision(decision="LONG"))
    rec = outcomes.assemble_outcome(daily, round_trip, 10.0, admit_rejected=True)
    assert rec.survival_events is not round_trip.survival_events
    assert round_trip.survival_events == ["flatten"]  # untouched


# --- R8.2: the module exposes ONLY record assembly — NO metric/calibration/gate


def test_public_surface_is_assembly_only_no_metric_calibration_gate():
    # The load-bearing R8.2 assertion: the module's public surface is the
    # assembler alone — no survival-net metric, no calibration, no gate.
    assert outcomes.__all__ == ["assemble_outcome"]
    public = {n for n in dir(outcomes) if not n.startswith("_")}
    forbidden_substrings = ("metric", "calibrat", "gate", "score", "promote")
    leaked = {
        name
        for name in public
        if callable(getattr(outcomes, name))
        and getattr(getattr(outcomes, name), "__module__", "") == outcomes.__name__
        and any(sub in name.lower() for sub in forbidden_substrings)
    }
    assert leaked == set(), f"outcomes leaked metric/calibration/gate surface: {leaked}"
