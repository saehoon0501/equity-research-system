"""Replay Harness: the `outcomes` leaf — per-period `OutcomeRecord` assembly.

NON-BEHAVIORAL. Assembles ONE `types.OutcomeRecord` per trading day from the
simulator's per-day pieces — the 2.3 `DailyDecision`, the 2.6 `DayRoundTrip`,
and the 2.7 `day_round_trip_pnl` float — wiring the 9 pinned `OutcomeRecord`
fields (design §Data Models "Owned" block; requirements R8.1). It computes
**no** survival-net metric, **no** calibration, and **no** gate — those are the
consumer `walkforward-tuning-loop`'s (R8.2); this module's public surface is
the assembler alone (asserted by the test).

Position in the strict left→right dependency chain (design §Dependency
direction): `types → data_client → features_adapter → simulator → outcomes →
harness`. This leaf imports the simulator's per-day output shapes
(`DailyDecision`, `DayRoundTrip`) + the owned in-memory contracts (`types`) +
the landed calibration `Label` vocabulary (P9 reuse) — all READ-ONLY. It never
imports a consumer spec and never imports upward.

Field-derivation notes (the load-bearing seam decisions):
  - `period`   ← `DailyDecision.as_of_day`; `symbol` ← `DailyDecision.symbol`.
  - `decision` ← the day's `ReactiveDecision.decision` (LONG/SHORT/HOLD), OR
    `"HOLD"` when the day is flat (`DailyDecision.decision is None`, design
    line 188-194/202 — a flat/no-trade day's effective decision is HOLD).
  - `predicted_probability` ← the softmax `ReactiveDecision.probability` at
    fire (calibration input), OR `None` on a flat day (no model fire). NOTE:
    the pinned `OutcomeRecord` annotation is `float`, but a flat day carries
    `None` per this task's contract — the tuner must filter flat days before
    calibrating (flagged as a seam concern, not enforced here).
  - `fills`    ← the day's entry + exit `Fill`s (`DayRoundTrip.entry_fill` and
    `.exit_fill`), `None` legs dropped. A flat / unfilled-close day → `[]`.
  - `total_return_pnl`  ← the `day_round_trip_pnl` float, verbatim (price P&L +
    same-day cash dividend, already computed by 2.7).
  - `survival_events`   ← 2.4's `"admit_reject"` (passed in explicitly when the
    day was admit-rejected — `apply_admit_gating`'s bare `None` cannot carry the
    tag, so the harness/2.4 caller supplies it) PREPENDED to the
    `DayRoundTrip.survival_events` exit-leg subset (`stop_hit`/`flatten`/
    `flat_verify_failed`). A fresh list (no aliasing the frozen round-trip's).
  - `realized_outcome`  ← the day's realized round-trip return — the same
    `day_round_trip_pnl` float (the calibration target; no normalization basis
    is pinned, so the raw return is assembled — the sign/normalization
    convention reconciliation is the tuner's, R8.2).
  - `realized_label`    ← the 4-bin calibration `Label` mapped from the decision
    (LONG→BUY, SHORT→SELL, HOLD/flat→HOLD). A pure decision→Label map — the
    harness does NOT margin-threshold the realized return into a label (that
    needs a margin = calibration, which is the consumer's per R8.2; the consumer
    applies its own margin via `scorer.score`).
"""

from __future__ import annotations

from src.calibration.scorer import Label
from src.reactive.replay.simulator import DailyDecision, DayRoundTrip
from src.reactive.replay.types import OutcomeRecord

# Decision-vocabulary (LONG/SHORT/HOLD, P9) → 4-bin calibration Label (P9). A
# pure, deterministic map — NOT a margin-thresholded realized-return classifier
# (that is the consumer's calibration concern, R8.2). LONG is a buy-side fire,
# SHORT a sell-side fire, HOLD the no-act bin.
_DECISION_TO_LABEL: dict[str, Label] = {
    "LONG": Label.BUY,
    "SHORT": Label.SELL,
    "HOLD": Label.HOLD,
}

# 2.4's survival tag — NOT in the `DayRoundTrip` exit-leg subset (that step owns
# only `stop_hit`/`flatten`/`flat_verify_failed`); the admit-REJECT signal is
# supplied by the caller because `apply_admit_gating` collapses it into a bare
# `None` (simulator.py SEAM note).
_EVENT_ADMIT_REJECT = "admit_reject"


def assemble_outcome(
    daily: DailyDecision,
    round_trip: DayRoundTrip,
    total_return_pnl: float,
    *,
    admit_rejected: bool = False,
) -> OutcomeRecord:
    """Assemble the per-day `OutcomeRecord` from the simulator's per-day pieces.

    NON-BEHAVIORAL record assembly only — NO metric, NO calibration, NO gate
    (R8.2). Wires the 9 pinned `OutcomeRecord` fields (R8.1) from the daily
    decision, the day's closed round-trip, and the day's total-return P&L.

    Args:
        daily: the 2.3 `DailyDecision` — supplies `period`/`symbol`/`decision`/
            `predicted_probability` (a `None` `daily.decision` ⇒ a flat day →
            decision HOLD, probability None).
        round_trip: the 2.6 `DayRoundTrip` — supplies the entry/exit `Fill`s and
            the exit-leg `survival_events` subset.
        total_return_pnl: the 2.7 `day_round_trip_pnl` float — the day's total-
            return P&L; also the `realized_outcome` (the day's realized round-
            trip return). 0.0 on a flat day.
        admit_rejected: True iff the day's candidate order was survival-admit
            REJECTED (the 2.4 `"admit_reject"` tag the bare-`None` gating return
            cannot carry). Defaults False; the caller (2.4/harness) supplies it.

    Returns:
        the per-period `OutcomeRecord`. NO metric / calibration / gate — those
        are the consumer's (R8.2).
    """
    rd = daily.decision
    decision = rd.decision if rd is not None else "HOLD"
    predicted_probability = rd.probability if rd is not None else None

    fills = [f for f in (round_trip.entry_fill, round_trip.exit_fill) if f is not None]

    # admit_reject (2.4's) PREPENDED to the exit-leg subset (2.6's); a fresh
    # list so we never alias / mutate the frozen round-trip's list (R9.1).
    survival_events: list[str] = []
    if admit_rejected:
        survival_events.append(_EVENT_ADMIT_REJECT)
    survival_events.extend(round_trip.survival_events)

    return OutcomeRecord(
        period=daily.as_of_day,
        symbol=daily.symbol,
        decision=decision,
        predicted_probability=predicted_probability,  # type: ignore[arg-type]
        fills=fills,
        total_return_pnl=total_return_pnl,
        survival_events=survival_events,
        realized_outcome=total_return_pnl,
        realized_label=_DECISION_TO_LABEL[decision],
    )


__all__ = ["assemble_outcome"]
