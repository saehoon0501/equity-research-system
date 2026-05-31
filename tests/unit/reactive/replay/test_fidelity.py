"""Inner-ring unit tests for the champion-reproduction fidelity comparator (Task 2.2).

NON-BEHAVIORAL. Exercises the PURE comparator `fidelity.compare` in isolation
(no I/O, no simulator, no DataPort, no live DB / feed) — the R9.2 inner-ring
seam. Source of truth: requirements.md Requirement 7 AC **7.1, 7.2, 7.3**;
design.md the `fidelity` component block (lines 210-213) + the simulator
**Core-algorithms #5** (FIFO fill-pairing, line 205) under the §16.1
one-position-per-symbol-per-day invariant.

The four pinned cases:
  * within-tolerance recorded-vs-simulated  -> status == "pass"        (7.1)
  * injected mismatch beyond tolerance      -> status == "fail"        (7.2)
  * empty / too-sparse recorded baseline    -> status == "not_evaluable" (7.3)
  * an ambiguous (non-round-trip) day       -> PairingAmbiguityError raised
    (design Core-algo #5: "aborts with a pairing-ambiguity signal ... never a
    silent undercount"). `FidelityResult.status` is a frozen 3-valued Literal
    in `types.py` (OUTSIDE this task's boundary), so the abort is a TYPED
    EXCEPTION, not a 4th status.

------------------------------------------------------------------------------
The `recorded_fills` joined-dict contract (harness-synthesized)
------------------------------------------------------------------------------
`compare`'s signature is exactly `(simulated_records, recorded_fills, tolerance)`
(design line 213) — there is NO separate `decisions` parameter. The harness
performs the decision->fill join (`parent_trace_id` linkage,
`decision-trace-telemetry`) BEFORE calling `compare`, so each `recorded_fills`
entry is a plain dict carrying both the fill payload AND the joined decision's
symbol + direction + the entry/exit leg side:

    {
      "day": "2024-01-31",          # §16.1 grouping key (one position / symbol / day)
      "symbol": "AAPL",             # from the linked decision (telemetry JSONB trace)
      "direction": "LONG"|"SHORT",  # the position direction (decision trace)
      "side": "BUY"|"SELL",         # the venue action of THIS leg (entry vs exit)
      "actual_fill_price": float,   # fill `trace.actual_fill_price`
      "fill_volume": float,         # fill `trace.fill_volume`
    }

FINDING (stated in the contract above): the telemetry schema (`schema.py`) and
the fixture builders carry NEITHER `symbol` NOR a buy/sell `side` as typed
fields — they live in the JSONB `trace` payload and are decision-linked. These
tests therefore build the joined dicts FROM the fixture builders' trace payloads
(reusing `actual_fill_price` / `fill_volume` / `parent_trace_id` linkage) and
enrich them with symbol/direction/side exactly as the harness join would. We do
NOT edit `_fixtures.py` (boundary) and do NOT edit `types.py` (boundary).

Requirements: 7.1, 7.2, 7.3.
"""

from __future__ import annotations

import pytest

from src.calibration.scorer import Label
from src.reactive.replay.fidelity import PairingAmbiguityError, compare
from src.reactive.replay.types import Fill, OutcomeRecord
from tests.unit.reactive.replay._fixtures import (
    make_champion_fill_row,
)


# --------------------------------------------------------------------------- #
# Builders: turn the fixture trace payloads into the harness-joined `recorded_
# fills` dicts (entry + flatten legs) and the simulated-champion OutcomeRecords.
# --------------------------------------------------------------------------- #


def _recorded_leg(
    *,
    day: str,
    symbol: str,
    direction: str,
    side: str,
    actual_fill_price: float,
    fill_volume: float,
) -> dict:
    """One harness-joined recorded-fill dict (a `kind=fill` row + linked decision).

    We pull the fill payload field names (`actual_fill_price`, `fill_volume`)
    from the landed fixture row's `trace` to keep this test pinned to the real
    schema, then enrich with the decision-linked symbol/direction/side.
    """
    fill_row = make_champion_fill_row()
    # Sanity: the fixture row really does carry these payload keys (schema pin).
    assert "actual_fill_price" in fill_row.trace
    assert "fill_volume" in fill_row.trace
    return {
        "day": day,
        "symbol": symbol,
        "direction": direction,
        "side": side,
        "actual_fill_price": actual_fill_price,
        "fill_volume": fill_volume,
    }


def _round_trip_long(
    *,
    day: str = "2024-01-31",
    symbol: str = "AAPL",
    entry: float = 100.0,
    exit_: float = 103.0,
    volume: float = 10.0,
) -> list[dict]:
    """A clean LONG round trip: BUY entry then SELL flatten (§16.1)."""
    return [
        _recorded_leg(
            day=day, symbol=symbol, direction="LONG", side="BUY",
            actual_fill_price=entry, fill_volume=volume,
        ),
        _recorded_leg(
            day=day, symbol=symbol, direction="LONG", side="SELL",
            actual_fill_price=exit_, fill_volume=volume,
        ),
    ]


def _sim_record(*, pnl: float, day: str = "2024-01-31", symbol: str = "AAPL") -> OutcomeRecord:
    """A simulated-champion OutcomeRecord carrying a `total_return_pnl`."""
    return OutcomeRecord(
        period=day,
        symbol=symbol,
        decision="LONG",
        predicted_probability=0.62,
        fills=[Fill(side="BUY", price=100.0, volume=10.0, ts=f"{day}T14:30:00Z")],
        total_return_pnl=pnl,
        survival_events=[],
        realized_outcome=pnl,
        realized_label=Label.BUY,
    )


# --------------------------------------------------------------------------- #
# 7.1 — within tolerance => pass
# --------------------------------------------------------------------------- #


def test_within_tolerance_recorded_vs_simulated_is_pass():
    # Recorded LONG round trip: (103 - 100) * 10 * (+1) = +30.0
    recorded = _round_trip_long(entry=100.0, exit_=103.0, volume=10.0)
    # Simulated total reproduces it to within tolerance (off by 0.005).
    simulated = [_sim_record(pnl=30.005)]

    result = compare(simulated, recorded, tolerance=0.01)

    assert result.status == "pass"
    assert isinstance(result.detail, str) and result.detail


def test_exact_reproduction_is_pass():
    recorded = _round_trip_long(entry=100.0, exit_=103.0, volume=10.0)
    simulated = [_sim_record(pnl=30.0)]

    result = compare(simulated, recorded, tolerance=0.0)

    assert result.status == "pass"


def test_short_round_trip_pnl_sign_is_correct():
    # SHORT: SELL entry @105, BUY flatten @100 => (100 - 105) * 10 * (-1) = +50.0
    recorded = [
        _recorded_leg(day="2024-02-01", symbol="MSFT", direction="SHORT", side="SELL",
                      actual_fill_price=105.0, fill_volume=10.0),
        _recorded_leg(day="2024-02-01", symbol="MSFT", direction="SHORT", side="BUY",
                      actual_fill_price=100.0, fill_volume=10.0),
    ]
    simulated = [_sim_record(pnl=50.0, day="2024-02-01", symbol="MSFT")]

    result = compare(simulated, recorded, tolerance=0.01)

    assert result.status == "pass"


def test_aggregates_across_multiple_day_symbol_round_trips():
    # Two clean round trips: +30 (AAPL) and +50 (MSFT short) = +80 recorded total.
    recorded = _round_trip_long(day="2024-01-31", symbol="AAPL",
                                entry=100.0, exit_=103.0, volume=10.0)
    recorded += [
        _recorded_leg(day="2024-02-01", symbol="MSFT", direction="SHORT", side="SELL",
                      actual_fill_price=105.0, fill_volume=10.0),
        _recorded_leg(day="2024-02-01", symbol="MSFT", direction="SHORT", side="BUY",
                      actual_fill_price=100.0, fill_volume=10.0),
    ]
    simulated = [
        _sim_record(pnl=30.0, day="2024-01-31", symbol="AAPL"),
        _sim_record(pnl=50.0, day="2024-02-01", symbol="MSFT"),
    ]

    result = compare(simulated, recorded, tolerance=0.01)

    assert result.status == "pass"


def test_partial_multi_row_fills_paired_by_volume():
    # Entry split into two BUY legs (4 + 6 = 10), one SELL flatten of 10.
    # FIFO-pair by min volume: 4@100<->4@103 and 6@100<->6@103 => +30 total.
    recorded = [
        _recorded_leg(day="2024-01-31", symbol="AAPL", direction="LONG", side="BUY",
                      actual_fill_price=100.0, fill_volume=4.0),
        _recorded_leg(day="2024-01-31", symbol="AAPL", direction="LONG", side="BUY",
                      actual_fill_price=100.0, fill_volume=6.0),
        _recorded_leg(day="2024-01-31", symbol="AAPL", direction="LONG", side="SELL",
                      actual_fill_price=103.0, fill_volume=10.0),
    ]
    simulated = [_sim_record(pnl=30.0)]

    result = compare(simulated, recorded, tolerance=0.01)

    assert result.status == "pass"


# --------------------------------------------------------------------------- #
# 7.2 — divergence beyond tolerance => fail (consumer withholds promotion)
# --------------------------------------------------------------------------- #


def test_injected_mismatch_beyond_tolerance_is_fail():
    # Recorded +30.0; simulated +25.0 — a 5.0 divergence, far beyond tolerance.
    recorded = _round_trip_long(entry=100.0, exit_=103.0, volume=10.0)
    simulated = [_sim_record(pnl=25.0)]

    result = compare(simulated, recorded, tolerance=0.01)

    assert result.status == "fail"
    # The detail must surface the divergence magnitude (not a silent verdict).
    assert isinstance(result.detail, str) and result.detail


def test_mismatch_just_outside_tolerance_is_fail():
    recorded = _round_trip_long(entry=100.0, exit_=103.0, volume=10.0)
    simulated = [_sim_record(pnl=30.02)]  # off by 0.02 > tolerance 0.01

    result = compare(simulated, recorded, tolerance=0.01)

    assert result.status == "fail"


# --------------------------------------------------------------------------- #
# 7.3 — absent / too-sparse recorded baseline => not_evaluable (distinct from fail)
# --------------------------------------------------------------------------- #


def test_empty_recorded_baseline_is_not_evaluable():
    result = compare([_sim_record(pnl=30.0)], [], tolerance=0.01)

    assert result.status == "not_evaluable"
    assert isinstance(result.detail, str) and result.detail


def test_sparse_baseline_single_leg_no_round_trip_is_not_evaluable():
    # A lone entry with no flatten anywhere — insufficient to form ANY round trip.
    sparse = [
        _recorded_leg(day="2024-01-31", symbol="AAPL", direction="LONG", side="BUY",
                      actual_fill_price=100.0, fill_volume=10.0),
    ]

    result = compare([_sim_record(pnl=0.0)], sparse, tolerance=0.01)

    assert result.status == "not_evaluable"


# --------------------------------------------------------------------------- #
# Pairing-ambiguity abort — a non-round-trip day (unmatched / surplus legs).
# Distinct from `not_evaluable` (populated-but-unbalanced, NOT empty/sparse).
# --------------------------------------------------------------------------- #


def test_ambiguous_day_two_entries_one_exit_aborts():
    # 2 BUY entries (10 + 10 = 20) but only 1 SELL flatten (10) on one (day,symbol):
    # 10 of entry volume is left unmatched after FIFO -> surplus leg -> ambiguous.
    ambiguous = [
        _recorded_leg(day="2024-01-31", symbol="AAPL", direction="LONG", side="BUY",
                      actual_fill_price=100.0, fill_volume=10.0),
        _recorded_leg(day="2024-01-31", symbol="AAPL", direction="LONG", side="BUY",
                      actual_fill_price=101.0, fill_volume=10.0),
        _recorded_leg(day="2024-01-31", symbol="AAPL", direction="LONG", side="SELL",
                      actual_fill_price=103.0, fill_volume=10.0),
    ]

    with pytest.raises(PairingAmbiguityError):
        compare([_sim_record(pnl=30.0)], ambiguous, tolerance=0.01)


def test_ambiguous_day_surplus_exit_aborts():
    # One BUY entry (10) but TWO SELL flattens (10 + 10) — surplus exit volume.
    ambiguous = [
        _recorded_leg(day="2024-01-31", symbol="AAPL", direction="LONG", side="BUY",
                      actual_fill_price=100.0, fill_volume=10.0),
        _recorded_leg(day="2024-01-31", symbol="AAPL", direction="LONG", side="SELL",
                      actual_fill_price=103.0, fill_volume=10.0),
        _recorded_leg(day="2024-01-31", symbol="AAPL", direction="LONG", side="SELL",
                      actual_fill_price=104.0, fill_volume=10.0),
    ]

    with pytest.raises(PairingAmbiguityError):
        compare([_sim_record(pnl=30.0)], ambiguous, tolerance=0.01)


def test_ambiguous_partial_volume_imbalance_aborts():
    # Entry volume (10) != exit volume (7) on a populated day: a non-round-trip.
    ambiguous = [
        _recorded_leg(day="2024-01-31", symbol="AAPL", direction="LONG", side="BUY",
                      actual_fill_price=100.0, fill_volume=10.0),
        _recorded_leg(day="2024-01-31", symbol="AAPL", direction="LONG", side="SELL",
                      actual_fill_price=103.0, fill_volume=7.0),
    ]

    with pytest.raises(PairingAmbiguityError):
        compare([_sim_record(pnl=30.0)], ambiguous, tolerance=0.01)
