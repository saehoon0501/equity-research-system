"""Shared inner-ring test scaffolding for the Replay Harness (Task 1.4).

NON-BEHAVIORAL infra. This is the R9.2 isolation seam every later replay unit
test rides on: a **fixture `DataPort`** (deterministic, in-memory, no network),
**stub cores** (reactive `decide`/`compute_features`, survival `admit`/`assess`,
broker `paper.simulate`), and **champion fixture rows** (`decision_process_trace`
shapes). Importing this module touches NO live market feed, NO LLM, and NO live
database (R9.2; P14 inner ring).

Why a plain `_fixtures` module (not `conftest.py`): the canned constructors are
reused BY NAME across the replay unit tests (`test_simulator.py` builds a port +
stub cores, `test_fidelity.py` builds champion rows), so name-import beats
fixture-injection here. A `conftest.py` can later wrap these as `@pytest.fixture`
if a test prefers injection — this module is the single source of the shapes.

--------------------------------------------------------------------------------
The import boundary (the load-bearing rule of this file)
--------------------------------------------------------------------------------
Two camps, treated differently:

  * **LANDED in this worktree → import the real contract.** The reactive cores
    (`ReactiveDecision`, `FeatureSet`, `DecisionSubstrate`, `CalibrationEvidence`),
    the broker `OrderResult`, the telemetry rows (`DecisionTraceRow` /
    `FillOutcomeRow` / `CorrelationKeys`), and the calibration `Label`. The stubs
    RETURN these real types so the future `simulator` reads them natively.

  * **DESIGNED-not-landed → MIRROR the shape locally.** `src.survival` does NOT
    exist in this worktree (that is precisely why `replay.types.Candidate.
    survival_parameters` is typed `Any`). Importing `from src.survival ...` would
    make this whole module fail to collect. So the survival contracts the stubs
    return (`AdmitDecision`, `AssessDirective`, `OperationalState`,
    `ReduceDirective`) are mirrored here as local frozen dataclasses, named +
    shaped to match the in-progress `survival-gate-impl/src/survival/types.py`
    EXACTLY. **Swapping these mirrors for `from src.survival.types import ...`
    (and the stub-signature pins for `from src.survival.gate import ...`) is the
    revalidation trigger when survival lands** (design "revalidate on landing").

Why the stubs are stubs, not the real cores:
  * survival `admit`/`assess` are not landed here → must be stubbed.
  * `broker.paper.simulate` IS landed, but `paper.py` uses sys.path-bootstrap
    bare imports (`from models import ...`) that do not resolve under the `src.*`
    package path — so the stub returns a freshly-built landed `OrderResult`
    rather than calling the real `simulate`. The OUTPUT type is the real contract.
  * the reactive `decide`/`compute_features` ARE importable + landed, but the
    scaffolding's job is canned, controllable values for path tests, so they are
    stubbed too (the design's test-plan: "stub decide/survival/paper"). The
    stub SIGNATURES match the landed cores so the simulator's calls line up.

Source of truth: requirements.md R9 AC 9.2; design.md "File Structure Plan"
(`tests/unit/reactive/replay/`) + the Allowed Dependencies block.

Requirements: 9.2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

# --- LANDED contracts: import the real types (the stubs return these) ---------
from src.calibration.scorer import Label
from src.mcp.broker.models import OrderResult
from src.reactive.features import FeatureSet
from src.reactive.telemetry.schema import (
    CorrelationKeys,
    DecisionTraceRow,
    FillOutcomeRow,
)
from src.reactive.types import (
    CalibrationEvidence,
    Decision,
    DecisionSubstrate,
    Direction,
    ReactiveDecision,
)


# ============================================================================ #
# MIRRORED survival contracts (src.survival is DESIGNED-not-landed here).
#
# These mirror `survival-gate-impl/src/survival/types.py` field-for-field. When
# survival lands in this worktree, DELETE these mirrors and the stub signatures
# below switch to `from src.survival.types import ...` / `from src.survival.gate
# import admit, assess` — the revalidation trigger.
# ============================================================================ #


@dataclass(frozen=True)
class OperationalState:
    """MIRROR of `survival.types.OperationalState` (read fresh per admit/assess)."""

    kill_switch_engaged: bool
    safe_mode_grade: str  # SafeModeGrade Literal in the real type
    entered_at: Optional[datetime]
    triggered_by: Optional[str]


@dataclass(frozen=True)
class ReduceDirective:
    """MIRROR of `survival.types.ReduceDirective`."""

    kind: str  # Literal["FLATTEN","REDUCE","FREEZE_ENTRIES"] in the real type
    symbol: Optional[str]
    target_volume: Optional[float]
    reason: str


@dataclass(frozen=True)
class SurvivalEvent:
    """MIRROR of `survival.types.SurvivalEvent`."""

    event_type: str
    ticker: Optional[str]
    detail: str
    account_snapshot: dict


@dataclass(frozen=True)
class AdmitDecision:
    """MIRROR of `survival.types.AdmitDecision` (the per-order veto result)."""

    decision: str  # Literal["ALLOW","REJECT"] in the real type
    binding_constraint: Optional[str]
    advisory_max_volume: Optional[float]
    reason: Optional[str]


@dataclass(frozen=True)
class AssessDirective:
    """MIRROR of `survival.types.AssessDirective` (the standing-monitor result)."""

    next_op_state: OperationalState
    reduce_directives: list[ReduceDirective] = field(default_factory=list)
    events: list[SurvivalEvent] = field(default_factory=list)


# ============================================================================ #
# Fixture DataPort — deterministic, in-memory, NO network (R9.2).
#
# Returns raw-Massive-wire shapes matching `MassiveDataClient`'s returns (it is a
# drop-in for the real client by injection). The Bar-TypedDict mapping is the
# future `features_adapter`'s job, NOT the port's.
# ============================================================================ #

# A canned multi-day OHLCV path (Polygon wire keys: t/o/h/l/c/v; `t` is epoch ms).
# A few bars with a non-flat range so a later intraday stop-hit / ATR test (2.x)
# has something to bite on. NOT realistic market data — just deterministic.
_CANNED_DAILY_BARS: list[dict] = [
    {"t": 1_704_067_200_000, "o": 100.0, "h": 102.0, "l": 99.0, "c": 101.0, "v": 1_000_000.0},
    {"t": 1_704_153_600_000, "o": 101.0, "h": 103.5, "l": 100.5, "c": 103.0, "v": 1_200_000.0},
    {"t": 1_704_240_000_000, "o": 103.0, "h": 104.0, "l": 101.0, "c": 101.5, "v": 900_000.0},
]

# A canned 1-minute intraday path for a single day (same wire shape).
_CANNED_INTRADAY_BARS: list[dict] = [
    {"t": 1_706_702_400_000, "o": 101.5, "h": 101.8, "l": 101.2, "c": 101.6, "v": 50_000.0},
    {"t": 1_706_702_460_000, "o": 101.6, "h": 102.1, "l": 101.5, "c": 101.9, "v": 42_000.0},
    {"t": 1_706_702_520_000, "o": 101.9, "h": 102.0, "l": 100.8, "c": 100.9, "v": 61_000.0},
]


class FixtureDataPort:
    """In-memory `types.DataPort` implementation — canned responses, no network.

    Satisfies the `runtime_checkable` `DataPort` Protocol structurally (the five
    pinned methods) AND carries the extra fetches `MassiveDataClient` adds
    (`fetch_trades` / `fetch_grouped_daily`) so the fixture is a full drop-in.
    Every return is a deep copy of a module-level canned constant so a consumer
    that mutates a result cannot poison a later call (determinism, R9.1-adjacent).
    """

    def __init__(
        self,
        *,
        daily_bars: Optional[list[dict]] = None,
        intraday_bars: Optional[list[dict]] = None,
        rf_yield: float = 4.25,
        dividend_cash: float = 0.24,
    ) -> None:
        self._daily_bars = list(daily_bars if daily_bars is not None else _CANNED_DAILY_BARS)
        self._intraday_bars = list(
            intraday_bars if intraday_bars is not None else _CANNED_INTRADAY_BARS
        )
        self._rf_yield = float(rf_yield)
        self._dividend_cash = float(dividend_cash)

    # -- DataPort: the five pinned point-in-time methods -------------------- #

    def fetch_daily_bars(self, symbol: str, start: str, end: str) -> list[dict]:
        return [dict(b) for b in self._daily_bars]

    def fetch_intraday(self, symbol: str, day: str) -> list[dict]:
        return [dict(b) for b in self._intraday_bars]

    def fetch_quotes(self, symbol: str, ts: str) -> dict:
        # NBBO wire shape: each row carries `bp`/`ap` (bid/ask) + a SIP ns ts.
        return {
            "results": [
                {"sip_timestamp": 1_706_702_400_000_000_000, "bp": 101.50, "ap": 101.54},
            ]
        }

    def fetch_corporate_actions(self, symbol: str, start: str, end: str) -> dict:
        # Splits kept distinct from dividends (the port's wire shape); at least
        # one cash dividend so a later total-return P&L test (5.1) has one to credit.
        return {
            "splits": [],
            "dividends": [
                {"ex_dividend_date": "2024-01-15", "cash_amount": self._dividend_cash},
            ],
        }

    def fetch_rf_yield(self, day: str) -> float:
        return self._rf_yield

    # -- extra fetches MassiveDataClient adds (not Protocol-pinned) --------- #

    def fetch_trades(self, symbol: str, ts: str) -> dict:
        return {
            "results": [
                {"participant_timestamp": 1_706_702_400_000_000_000, "price": 101.52, "size": 100},
            ]
        }

    def fetch_grouped_daily(self, day: str) -> list[dict]:
        return [
            {"T": symbol, "o": 100.0, "h": 101.0, "l": 99.5, "c": 100.5, "v": 500_000.0}
            for symbol in ("AAPL", "MSFT")
        ]


def make_fixture_dataport(**kwargs: Any) -> FixtureDataPort:
    """Build a :class:`FixtureDataPort` (the R9.2 injection seam) with defaults."""
    return FixtureDataPort(**kwargs)


# ============================================================================ #
# Stub reactive cores — landed return shapes, canned values.
# Signatures match the landed `signal_model.decide` / `features.compute_features`
# so the future `simulator`'s calls line up.
# ============================================================================ #


def _canned_substrate(probability: float, effective_threshold: float) -> DecisionSubstrate:
    """A canned `DecisionSubstrate` (the inspectable per-decision evidence, R7)."""
    return DecisionSubstrate(
        feature_values={"rsi_14": 55.0},
        probability=probability,
        effective_threshold=effective_threshold,
        code_version="stub-code-v0",
        param_version="stub-param-v0",
        calibration=CalibrationEvidence(brier=None, reliability=None),
    )


def stub_decide(
    features: Any,
    direction: Direction,
    snapshot: Any,
    runtime_threshold: float | None = None,
    *,
    decision: Decision = "LONG",
    probability: float = 0.62,
    effective_threshold: float = 0.55,
) -> ReactiveDecision:
    """Stub of `signal_model.decide` → a canned landed `ReactiveDecision`.

    Positional params (`features, direction, snapshot, runtime_threshold`) mirror
    the landed core EXACTLY so the simulator's call site lines up. The canned
    outcome is overridable via keyword-only knobs so a path test can drive a HOLD
    vs an actionable LONG/SHORT without recomputing the model. `non_final=True`
    on every decision (R4.1 — vetoable downstream). `sizing_hint` is the advisory
    above-threshold scalar when actionable, `None` on HOLD (R5).
    """
    actionable = decision != "HOLD"
    return ReactiveDecision(
        decision=decision,
        direction_in=direction if direction in ("LONG", "SHORT") else "LONG",
        probability=probability,
        sizing_hint=(probability - effective_threshold) if actionable else None,
        non_final=True,
        reason=None if actionable else "invalid_direction",
        substrate=_canned_substrate(probability, effective_threshold),
    )


def stub_compute_features(
    ticker_bars: Any,
    spy_close: Any,
    rf_yield_pct: float | None,
    atr_period: int = 14,
    *,
    trend_vote: float = 1.0,
    flow_vote: float = 0.5,
    meanrev_vote: float = 0.0,
) -> FeatureSet:
    """Stub of `features.compute_features` → a canned landed `FeatureSet`.

    Signature mirrors the landed core (`ticker_bars, spy_close, rf_yield_pct,
    atr_period`). Returns a `FeatureSet` (never a `FeatureFailure`) with canned
    signed votes; `trend_strength = abs(flow_vote)` per the landed adapter rule.
    """
    return FeatureSet(
        trend_vote=trend_vote,
        flow_vote=flow_vote,
        meanrev_vote=meanrev_vote,
        trend_strength=abs(flow_vote),
        raw={"rsi_14": 55.0, "drawdown_atr": 1.2, "ma_distance_atr": 0.8},
    )


# ============================================================================ #
# Stub survival cores — MIRRORED return shapes, signatures match survival-gate.
# admit(order, state, op_state, params, clock, evaluation) -> AdmitDecision
# assess(state, op_state, params, clock)                   -> AssessDirective
# ============================================================================ #


def stub_admit(
    order: Any,
    state: Any,
    op_state: Any,
    params: Any,
    clock: Any,
    evaluation: Any,
    *,
    decision: str = "ALLOW",
    binding_constraint: str | None = None,
    advisory_max_volume: float | None = None,
) -> AdmitDecision:
    """Stub of `survival.gate.admit` → a mirrored `AdmitDecision`.

    The signature matches the in-progress `survival-gate-impl` EXACTLY, including
    the SIXTH positional `evaluation` (`OrderEvaluation`) arg — which the design's
    Allowed-Dependencies stub list omits (flagged in CONCERNS). Default ALLOW;
    override via keyword-only knobs to drive a REJECT path. `binding_constraint` /
    `advisory_max_volume` / `reason` are `None` on ALLOW (mirrors the real type).
    """
    if decision == "ALLOW":
        return AdmitDecision(
            decision="ALLOW",
            binding_constraint=None,
            advisory_max_volume=None,
            reason=None,
        )
    return AdmitDecision(
        decision="REJECT",
        binding_constraint=binding_constraint or "missing_sl",
        advisory_max_volume=advisory_max_volume,
        reason=f"stub reject: {binding_constraint or 'missing_sl'}",
    )


def stub_assess(
    state: Any,
    op_state: Any,
    params: Any,
    clock: Any,
    *,
    next_grade: str = "NONE",
    reduce_directives: Optional[list[ReduceDirective]] = None,
    events: Optional[list[SurvivalEvent]] = None,
) -> AssessDirective:
    """Stub of `survival.gate.assess` → a mirrored `AssessDirective`.

    The signature matches the in-progress `survival-gate-impl` EXACTLY (`state,
    op_state, params, clock`). Default a clean tick (grade NONE, no directives);
    override via keyword-only knobs to drive a FLATTEN/REDUCE path. The
    `next_op_state` is a mirrored `OperationalState` carrying `next_grade`.
    """
    return AssessDirective(
        next_op_state=OperationalState(
            kill_switch_engaged=False,
            safe_mode_grade=next_grade,
            entered_at=None,
            triggered_by=None,
        ),
        reduce_directives=list(reduce_directives or []),
        events=list(events or []),
    )


# ============================================================================ #
# Stub broker paper.simulate — landed OrderResult, landed keyword-only signature.
# ============================================================================ #


def stub_paper_simulate(
    intent: Any,
    *,
    bid: Optional[float] = None,
    ask: Optional[float] = None,
    position_volume: Optional[float] = None,
    transport: Any = None,
    fill_volume: float = 1.0,
) -> OrderResult:
    """Stub of `broker.paper.simulate` → a real landed `OrderResult`.

    The signature mirrors the landed `simulate` (keyword-only `bid`/`ask`/
    `position_volume`/`transport`) so the simulator's call site lines up. Prices
    at the canonical side rule (BUY/open lifts the ask, SELL hits the bid) when a
    bid/ask pair is supplied — defaults to the ask so a counterparty (never-mid)
    fill price is present (R6.1). The real `simulate` is NOT called (its bare
    `from models import ...` imports do not resolve under the `src.*` path); only
    the OUTPUT contract is the landed type.
    """
    if bid is not None and ask is not None:
        fill_price: Optional[float] = ask
        priced_side = "ask"
    else:
        fill_price = None
        priced_side = None
    return OrderResult(
        status="simulated",
        order_id=None,
        position_id=None,
        fill_price=fill_price,
        fill_volume=fill_volume,
        reason=None,
        raw={"simulated": True, "bid": bid, "ask": ask, "priced_side": priced_side},
    )


# ============================================================================ #
# Champion fixture rows — real landed decision_process_trace shapes.
# The harness↔fidelity reproduction (R7) FIFO-pairs simulated-champion records
# against these recorded fills; the fixtures supply that baseline.
# ============================================================================ #


def make_correlation_keys(
    *,
    run_id: str = "00000000-0000-0000-0000-0000000c4a3b",
    code_version: str = "champ-code-v1",
    param_version: str = "champ-param-v1",
    walk_forward_window: str | None = "2024Q1",
) -> CorrelationKeys:
    """A canned `CorrelationKeys` (the P3 four-key set every row joins on)."""
    return CorrelationKeys(
        run_id=run_id,
        code_version=code_version,
        param_version=param_version,
        walk_forward_window=walk_forward_window,
    )


def make_champion_decision_row(
    *,
    trace_id: str = "11111111-1111-1111-1111-111111111111",
    event_ts: str = "2024-01-31T14:30:00Z",
) -> DecisionTraceRow:
    """A canned champion `DecisionTraceRow` (kind == 'decision').

    Carries the JSONB `trace` payload a champion fire records (probability,
    decision, signal values) so a fidelity-baseline test can reconstruct the fire.
    """
    return DecisionTraceRow(
        trace_id=trace_id,
        keys=make_correlation_keys(),
        event_ts=event_ts,
        trace={
            "decision": "LONG",
            "probability": 0.62,
            "signal_values": {"trend_vote": 1.0, "flow_vote": 0.5, "meanrev_vote": 0.0},
            "liq_proximity": None,
            "stop_out": False,
            "declined": False,
        },
    )


def make_champion_fill_row(
    *,
    parent_trace_id: str = "11111111-1111-1111-1111-111111111111",
    trace_id: str = "22222222-2222-2222-2222-222222222222",
    event_ts: str = "2024-01-31T14:30:01Z",
) -> FillOutcomeRow:
    """A canned champion `FillOutcomeRow` (kind == 'fill') linked to a decision.

    The recorded fill the fidelity comparator pairs the simulated-champion fill
    against (expected_price / actual_fill_price / slippage / counterparty_price).
    """
    return FillOutcomeRow(
        trace_id=trace_id,
        parent_trace_id=parent_trace_id,
        keys=make_correlation_keys(),
        event_ts=event_ts,
        trace={
            "expected_price": 101.54,
            "actual_fill_price": 101.55,
            "slippage": 0.01,
            "fill_volume": 1.0,
            "counterparty_price": 101.54,
        },
    )


def make_champion_realized_label() -> Label:
    """The champion fixture's realized 4-bin calibration label (P9 `Label`)."""
    return Label.BUY


__all__ = [
    # mirrored survival contracts (swap to src.survival on landing)
    "OperationalState",
    "ReduceDirective",
    "SurvivalEvent",
    "AdmitDecision",
    "AssessDirective",
    # fixture data port
    "FixtureDataPort",
    "make_fixture_dataport",
    # stub cores
    "stub_decide",
    "stub_compute_features",
    "stub_admit",
    "stub_assess",
    "stub_paper_simulate",
    # champion rows
    "make_correlation_keys",
    "make_champion_decision_row",
    "make_champion_fill_row",
    "make_champion_realized_label",
]
