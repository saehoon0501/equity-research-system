"""Inner-ring E2E cycle for the Replay Harness (Task 4.3).

The full end-to-end cycle through the SINGLE public entry `replay_candidate`:
one seeded candidate config over one seeded window drives the whole landed chain
(`prefetch champion decisions → daily layer → intraday fills + §16.1 flatten →
total-return P&L → per-period OutcomeRecords`), then the champion re-sim feeds
`fidelity.compare` → a `FidelityResult`. It is the "critical path that proves the
engine reproduces known reality before any candidate is scored" (design §E2E).

How 4.3 differs from the 3.1 integration test (`test_harness.py`) — 4.3 is NOT a
re-run of 3.1's wiring checks; it earns its keep on three E2E-specific surfaces:

  * **Conservative champion-reproduction (R7.1).** 3.1's pass test uses
    `tolerance=1.0`, which cannot tell a faithful reproduction from a sloppy one.
    Here the recorded-champion fills are seeded at the fixture's OWN counterparty
    quote (entry @ ask, flatten @ bid) and the deterministic sizing volume, so the
    recorded-P&L reconstruction reproduces the simulated-champion path by
    construction — asserted PASS under a TIGHT tolerance (`1e-6`) far below 1.0.
    A tolerance that wide would mask a divergence; a tight one proves the engine
    actually reproduces reality. The seeded prices are the FIXTURE's bid/ask, not
    a hardcoded P&L float, so the assertion stays robust to the sizing math.

  * **R8.1 full 9-field outcome contract.** 3.1 only `isinstance`/`len`-checks the
    records. Here the seeded actionable record is asserted across all six R8.1
    categories (decision / predicted_probability / fills-with-prices /
    total_return_pnl / survival_events / realized_outcome + realized_label).

  * **Determinism on the E2E path INCLUDING fidelity (R9.1).** 3.1 compares
    `records` only. Here the seeded-CHAMPION path is run twice and the WHOLE
    `ReplayResult` (records AND the `FidelityResult`) is asserted equal — the
    champion-branch determinism 3.1's records-only test does not cover.

not_evaluable is the second load-bearing branch (R7.3): asserted `== "not_evaluable"`
AND `!= "fail"` (the spec stresses "distinct from a fidelity failure") for BOTH an
absent (empty) baseline AND a sparse lone-leg baseline (a decision + a single
entry fill, no exit). The sparse case proves an INSUFFICIENT baseline routes to
not_evaluable rather than a `PairingAmbiguityError` abort — a genuine R7.3
distinction (sparse-cold-start vs engine defect) 3.1 does not exercise.

Exercised in ISOLATION (R9.2 / P14 inner ring): a `FixtureDataPort`, stub cores
injected through the harness's `decide_fn`/`features_fn`/`admit_fn` seams, a fake
`query_trace` returning raw champion trace-row dicts, and a fake champion-config
reader — NO live market feed, NO LLM, NO live DB.

The seeded prices are NOT magic numbers: they are the `FixtureDataPort`'s own
counterparty quote (`fetch_quotes` → bid 101.50 / ask 101.54), which the
simulator fills the entry at the ask and the §16.1 flatten at the bid (R6.1
never-mid). Seeding the recorded baseline at those same prices + the deterministic
sizing volume reproduces the simulated-champion round trip exactly.

Why raw dict trace rows (not the typed `_fixtures` `make_champion_*_row`): the
harness does dict access on trace rows (`row.get("parent_trace_id")`,
`row["event_ts"]`, `row.get("trace")`); the typed `FillOutcomeRow` /
`DecisionTraceRow` dataclasses have no `.get`. So this file reuses 3.1's raw-dict
builder pattern (the query_trace wire shape) — the fixture's typed rows are the
SCHEMA reference, the dict builders here are the reader's actual return shape.

RED phase (src/ is LANDED + immutable, so a correct test goes green on first run):
captured a MEANINGFUL red by first seeding the flatten leg at a deliberately wrong
exit price (105.00 vs the fixture bid 101.50) — verified through the real
`replay_candidate` path that the divergence (~0.24) breaches the tight `1e-6`
tolerance ⇒ `status == "fail"`, proving the tight-tolerance assertion BITES (the
pass is not vacuous) — then corrected the flatten seed to the fixture bid 101.50
⇒ `status == "pass"`. The committed test holds the corrected (GREEN) seed; the
mis-seed transition is the red evidence that the conservative pass is real.

Source of truth: requirements.md R1.1, R7.1, R7.3, R8.1, R9.1; design.md §E2E
("seeded short window … champion-version fidelity pass — the critical path");
tasks.md 4.3 (Observable: "asserts both the champion-reproduction pass and the
not-evaluable branch") + 2.2 (the dividend-basis asymmetry → tight tolerance
requires `dividend_cash=0.0`).

Requirements: 1.1, 7.1, 7.3, 8.1, 9.1.
"""

from __future__ import annotations

from typing import Any

from src.calibration.scorer import Label
from src.reactive.features import FeatureSet
from src.reactive.params import DEFAULTS as REACTIVE_DEFAULTS
from src.reactive.replay.harness import replay_candidate
from src.reactive.replay.types import (
    Candidate,
    Fill,
    OutcomeRecord,
    ReplayResult,
    ReplayWindow,
)
from src.survival.params import DEFAULTS as SURVIVAL_DEFAULTS

from tests.unit.reactive.replay._fixtures import (
    make_correlation_keys,
    make_fixture_dataport,
    stub_admit,
    stub_decide,
)

# The FixtureDataPort's OWN counterparty quote (`fetch_quotes` → bp/ap). The
# simulator fills the entry at the ASK (101.54) and the §16.1 flatten at the BID
# (101.50) — R6.1 never-mid. Seeding the recorded champion baseline at these same
# prices reproduces the simulated round trip, so the pass holds under a TIGHT
# tolerance (these are the fixture's prices, not a hardcoded P&L float).
_FIXTURE_ASK = 101.54
_FIXTURE_BID = 101.50

# A tolerance FAR below 3.1's `tolerance=1.0`: it is the conservative-reproduction
# gate. The seeded baseline reproduces the simulated path to float noise, so this
# passes; a sloppy reproduction (the RED-phase mis-seed) breaches it ⇒ fail.
_TIGHT_TOLERANCE = 1e-6

_DAY = "2024-01-01"  # the fixture daily bars span 2024-01-01..2024-01-03.


# --------------------------------------------------------------------------- #
# Seeded directional features (mirrors test_harness: the real
# compute_daily_features over the 3 canned bars degrades to a FeatureFailure, so
# inject a directional FeatureSet carrying the tactical_bin + ATR to drive the
# actionable LONG path deterministically).
# --------------------------------------------------------------------------- #


def _feature_set(*, tactical_bin: str = "positive") -> FeatureSet:
    """A directional `FeatureSet` with a verbatim `raw["tactical_bin"]` + ATR.

    `raw["atr"]` is load-bearing: the harness sources the build-order stop
    distance from it on an actionable day.
    """
    _bin_to_vote = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}
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


def _allow_admit(order, account, op_state, params, clock, evaluation):
    """A stub admit that ALLOWs every order (the happy E2E path)."""
    return stub_admit(
        order, account, op_state, params, clock, evaluation, decision="ALLOW"
    )


def _candidate() -> Candidate:
    """A candidate config carrying the inner-ring DEFAULTS snapshots (R1.3)."""
    return Candidate(
        param_snapshot=REACTIVE_DEFAULTS,
        survival_parameters=SURVIVAL_DEFAULTS,
        code_version=None,
    )


def _fake_champion_config_reader(param_version: str, *, conn: Any = None) -> Candidate:
    """A fake P2 champion-config reader → the champion's pinned Candidate.

    The real reader resolves `effective_parameters_jsonb` from
    `run_parameters_snapshot` by `param_version`; the test injects a canned
    Candidate so the JSONB→dataclass mapping stays prod-path only (no DB).
    """
    return _candidate()


# --------------------------------------------------------------------------- #
# Raw champion trace-row dict builders (the query_trace WIRE shape).
#
# The harness does dict access on trace rows (`.get`/`[...]`); the typed
# `_fixtures` rows have no `.get`. These mirror the landed reader's return shape
# and the `kind=` filter (reused from the 3.1 pattern).
# --------------------------------------------------------------------------- #

_KEYS = make_correlation_keys()


def _champion_decision_row(*, symbol: str, day: str, decision: str, trace_id: str) -> dict:
    """A raw `query_trace` champion DECISION-row dict (kind == 'decision')."""
    return {
        "trace_id": trace_id,
        "kind": "decision",
        "parent_trace_id": None,
        "event_ts": f"{day}T14:30:00Z",
        "run_id": _KEYS.run_id,
        "code_version": _KEYS.code_version,
        "param_version": _KEYS.param_version,
        "walk_forward_window": _KEYS.walk_forward_window,
        "trace": {"symbol": symbol, "decision": decision, "probability": 0.62},
        "created_at": f"{day}T14:30:00Z",
    }


def _champion_fill_row(
    *,
    parent_trace_id: str,
    trace_id: str,
    day: str,
    ts_suffix: str,
    actual_fill_price: float,
    fill_volume: float,
) -> dict:
    """A raw `query_trace` champion FILL-row dict (kind == 'fill').

    The fill payload carries NEITHER symbol NOR a buy/sell side (schema pin: they
    live in the linked DECISION's JSONB trace + are derived). The harness joins
    symbol/direction via `parent_trace_id` and derives the leg side from event-ts
    ordering within the (day, symbol) group.
    """
    return {
        "trace_id": trace_id,
        "kind": "fill",
        "parent_trace_id": parent_trace_id,
        "event_ts": f"{day}T{ts_suffix}Z",
        "run_id": _KEYS.run_id,
        "code_version": _KEYS.code_version,
        "param_version": _KEYS.param_version,
        "walk_forward_window": _KEYS.walk_forward_window,
        "trace": {
            "expected_price": actual_fill_price,
            "actual_fill_price": actual_fill_price,
            "slippage": 0.0,
            "fill_volume": fill_volume,
            "counterparty_price": actual_fill_price,
        },
        "created_at": f"{day}T{ts_suffix}Z",
    }


def _fake_query_trace(decision_rows: list[dict], fill_rows: list[dict]):
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


def _empty_query_trace(filters: dict | None = None) -> list[dict]:
    """A fake `query_trace` returning no champion rows (the champion-absent case)."""
    return []


# --------------------------------------------------------------------------- #
# Seeded champion baselines — reproduce the simulated round trip exactly.
# --------------------------------------------------------------------------- #


_CHAMPION_DEC_ID = "dec-AAPL-2024-01-01"
# The deterministic sizing volume the simulator fills the LONG round trip at
# (sizing_hint capped by per-order size). Seed the recorded baseline at the SAME
# volume so the recorded reconstruction matches the simulated P&L by construction.
_CHAMPION_VOLUME = 0.07


def _reproducing_champion_rows() -> tuple[list[dict], list[dict]]:
    """Champion decision + fill rows whose reconstruction reproduces the sim path.

    Entry @ the fixture ASK (101.54), flatten @ the fixture BID (101.50), volume
    = the deterministic sizing volume — so the recorded-P&L reconstruction
    (`(exit − entry) × vol`) reproduces the simulated-champion round trip to float
    noise, holding the PASS under the TIGHT tolerance (the conservative R7.1
    proof). Prices are the fixture's quote, not a hardcoded P&L float.
    """
    decision_rows = [
        _champion_decision_row(
            symbol="AAPL", day=_DAY, decision="LONG", trace_id=_CHAMPION_DEC_ID
        ),
    ]
    fill_rows = [
        _champion_fill_row(
            parent_trace_id=_CHAMPION_DEC_ID,
            trace_id="fill-entry",
            day=_DAY,
            ts_suffix="14:30:00",  # earliest → the OPEN leg (BUY for LONG)
            actual_fill_price=_FIXTURE_ASK,
            fill_volume=_CHAMPION_VOLUME,
        ),
        _champion_fill_row(
            parent_trace_id=_CHAMPION_DEC_ID,
            trace_id="fill-exit",
            day=_DAY,
            ts_suffix="15:55:00",  # later → the §16.1 flatten leg (SELL for LONG)
            actual_fill_price=_FIXTURE_BID,
            fill_volume=_CHAMPION_VOLUME,
        ),
    ]
    return decision_rows, fill_rows


def _sparse_champion_rows() -> tuple[list[dict], list[dict]]:
    """A SPARSE lone-leg champion baseline: a decision + a single ENTRY fill.

    No exit/flatten leg ⇒ the (day, symbol) group never forms a round trip ⇒
    `fidelity._has_any_round_trip` is False ⇒ the comparator returns
    `not_evaluable` (NOT a `PairingAmbiguityError`). This is the R7.3
    insufficient-baseline (paper cold-start) case — distinct from an engine defect.
    """
    decision_rows = [
        _champion_decision_row(
            symbol="AAPL", day=_DAY, decision="LONG", trace_id=_CHAMPION_DEC_ID
        ),
    ]
    fill_rows = [
        _champion_fill_row(
            parent_trace_id=_CHAMPION_DEC_ID,
            trace_id="fill-entry-only",
            day=_DAY,
            ts_suffix="14:30:00",
            actual_fill_price=_FIXTURE_ASK,
            fill_volume=_CHAMPION_VOLUME,
        ),
    ]
    return decision_rows, fill_rows


def _one_day_window() -> ReplayWindow:
    """A seeded ONE-day window (the seeded E2E unit)."""
    return ReplayWindow(start=_DAY, end=_DAY, tickers=["AAPL"])


def _replay(query_trace_fn, *, tolerance: float = _TIGHT_TOLERANCE) -> ReplayResult:
    """The seeded ONE-config ONE-window E2E `replay_candidate` invocation.

    Fixture DataPort with `dividend_cash=0.0` (the tight tolerance REQUIRES it:
    a same-day cash dividend skews the simulated total-return side vs the
    price-only recorded side — tasks.md 2.2 — which would conservatively false-fail
    a tight tolerance). Stub cores injected through the harness seams (R9.2).
    """
    return replay_candidate(
        _candidate(),
        _one_day_window(),
        data_port=make_fixture_dataport(dividend_cash=0.0),
        query_trace_fn=query_trace_fn,
        champion_keys=_KEYS,
        champion_config_reader=_fake_champion_config_reader,
        decide_fn=stub_decide,
        features_fn=_features_fn(tactical_bin="positive"),
        admit_fn=_allow_admit,
        tolerance=tolerance,
    )


# ============================================================================ #
# R1.1 / R8.1 — the seeded E2E cycle produces a full-contract OutcomeRecord
# ============================================================================ #


def test_e2e_produces_outcome_records_over_window() -> None:
    """R1.1: the seeded one-config one-window cycle drives the whole landed chain
    end-to-end and produces a per-period `OutcomeRecord` (one trading day here)."""
    decision_rows, fill_rows = _reproducing_champion_rows()
    result = _replay(_fake_query_trace(decision_rows, fill_rows))

    assert isinstance(result, ReplayResult)
    assert result.records, "the E2E cycle must emit a per-period record"
    assert all(isinstance(r, OutcomeRecord) for r in result.records)
    # The seeded window is one day × one ticker ⇒ exactly one record.
    assert len(result.records) == 1
    assert result.records[0].symbol == "AAPL"
    assert result.records[0].period == _DAY


def test_e2e_actionable_record_carries_full_r8_1_contract() -> None:
    """R8.1: the seeded actionable LONG record carries ALL six R8.1 categories —
    decisions, predicted probability, fills WITH prices, total-return P&L,
    survival events, and the realized outcome + 4-bin label (the harness↔tuner
    seam the tuner scores; the harness computes no metric itself, R8.2)."""
    decision_rows, fill_rows = _reproducing_champion_rows()
    result = _replay(_fake_query_trace(decision_rows, fill_rows))

    rec = result.records[0]

    # 1. the candidate's decision (reactive vocab).
    assert rec.decision == "LONG"
    # 2. the model's predicted probability (calibration input; float on an
    #    actionable day — None on flat days per tasks.md 2.8, so assert here only).
    assert isinstance(rec.predicted_probability, float)
    assert rec.predicted_probability == 0.62
    # 3. fills WITH counterparty prices (entry + §16.1 flatten; never mid, R6.1).
    assert all(isinstance(f, Fill) for f in rec.fills)
    assert len(rec.fills) == 2  # entry + flatten
    assert all(f.price is not None for f in rec.fills)
    fill_prices = {f.price for f in rec.fills}
    assert _FIXTURE_ASK in fill_prices  # entry @ ask
    assert _FIXTURE_BID in fill_prices  # flatten @ bid
    # 4. total-return P&L (a real number; computed, not asserted).
    assert isinstance(rec.total_return_pnl, float)
    # 5. survival events — the §16.1 flatten fired on the actionable day.
    assert "flatten" in rec.survival_events
    # 6. the realized outcome + the 4-bin calibration label (P9 vocabulary).
    assert isinstance(rec.realized_outcome, float)
    assert rec.realized_label == Label.BUY


# ============================================================================ #
# R7.1 — CONSERVATIVE champion-reproduction pass (the load-bearing assertion)
# ============================================================================ #


def test_e2e_champion_reproduction_passes_under_tight_tolerance() -> None:
    """R7.1 (load-bearing): a champion-version replay whose recorded fills are
    seeded at the fixture's OWN counterparty quote (entry @ ask, flatten @ bid) +
    the deterministic sizing volume reproduces the simulated-champion round trip
    by construction ⇒ `FidelityResult.status == "pass"` under a TIGHT tolerance.

    The tight tolerance (`1e-6`, far below 3.1's `1.0`) is what makes this a
    CONSERVATIVE proof: it would NOT mask a divergence. The RED-phase mis-seed
    (flatten @ 105.00) breached this same tolerance ⇒ `fail`, proving the pass is
    not vacuous. The pass is asserted on the verdict, not a hardcoded P&L float.
    """
    decision_rows, fill_rows = _reproducing_champion_rows()
    result = _replay(_fake_query_trace(decision_rows, fill_rows))

    assert result.fidelity.status == "pass"
    # A conservative pass, not a fail masked by a wide tolerance.
    assert result.fidelity.status != "fail"
    assert result.fidelity.detail  # the comparator surfaces the divergence magnitude


# ============================================================================ #
# R7.3 — not_evaluable (distinct from fail) — absent AND sparse baselines
# ============================================================================ #


def test_e2e_absent_champion_baseline_is_not_evaluable() -> None:
    """R7.3: an ABSENT (empty) champion fill baseline ⇒ `not_evaluable` — DISTINCT
    from `fail` (the spec: "distinct from a fidelity failure"), so the consumer
    treats a sparse cold-start differently from an engine defect."""
    result = _replay(_empty_query_trace)

    assert result.fidelity.status == "not_evaluable"
    assert result.fidelity.status != "fail"


def test_e2e_sparse_lone_leg_baseline_is_not_evaluable() -> None:
    """R7.3: a SPARSE lone-leg baseline (a champion decision + a single ENTRY fill,
    no exit) is INSUFFICIENT to form any round trip ⇒ `not_evaluable`, NOT a
    `PairingAmbiguityError` abort. This proves the cold-start sparse-baseline path
    routes to not_evaluable (distinct from `fail`) — the R7.3 distinction 3.1's
    empty-only test does not exercise."""
    decision_rows, fill_rows = _sparse_champion_rows()
    result = _replay(_fake_query_trace(decision_rows, fill_rows))

    assert result.fidelity.status == "not_evaluable"
    assert result.fidelity.status != "fail"


# ============================================================================ #
# R9.1 — determinism on the E2E path (records AND fidelity)
# ============================================================================ #


def test_e2e_determinism_records_and_fidelity() -> None:
    """R9.1: identical (candidate, window, fixture inputs, champion baseline) ⇒ an
    identical `ReplayResult` — records AND the `FidelityResult` — on the seeded
    CHAMPION path. 3.1's determinism test compares `records` only; this is the
    E2E-specific version covering the champion-reproduction branch too."""
    decision_rows, fill_rows = _reproducing_champion_rows()

    def _run() -> ReplayResult:
        return _replay(_fake_query_trace(decision_rows, fill_rows))

    first = _run()
    second = _run()

    # Frozen dataclasses throughout ⇒ structural equality covers the full tree.
    assert first.records == second.records
    assert first.fidelity == second.fidelity
    assert first == second  # the whole ReplayResult, end to end
