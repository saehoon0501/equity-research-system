"""Smoke test for the shared Replay-Harness test scaffolding (Task 1.4).

Non-behavioral infra. This proves the inner-ring isolation seam (R9.2) that
every later replay unit test (`test_simulator.py`, `test_outcomes.py`,
`test_fidelity.py`) rides on, WITHOUT exercising any harness behavior (the
two-layer loop, P&L, stop-hit, dividend crediting — those are tasks 2.x/3.x):

  * the **fixture DataPort** structurally satisfies the landed `types.DataPort`
    `runtime_checkable` Protocol AND every named fetch method returns a
    raw-Massive-wire-shaped value with NO network (R9.2 — no live feed/DB);
  * the **stub cores** (`decide` / `compute_features` / survival `admit`/`assess`
    / `paper.simulate`) import and return the right-SHAPED landed/mirrored
    values, so the future `simulator`'s calls line up against them;
  * the **champion fixture rows** are real landed `decision_process_trace` row
    shapes (`DecisionTraceRow` / `FillOutcomeRow`);

…all with NO LLM, NO MCP, NO live DB (P14 inner ring, R9.2).

The scaffolding lives in `_fixtures` (a plain helper module, NOT `conftest.py`,
so the canned constructors are import-reusable by name across the replay unit
tests rather than only injectable as pytest fixtures).

Source of truth (cited per the task):
  - requirements.md Requirement 9 AC 9.2 — "the Replay Harness shall be
    exercisable in isolation — with stubbed cores and fixture data, without a
    live market feed, an LLM, or a live database."
  - design.md "File Structure Plan" `tests/unit/reactive/replay/` entry
    ("stub cores + fixture data; no network/DB") and the Allowed Dependencies
    block ("Drive (DESIGNED — stub in tests, revalidate on landing)" for the
    survival cores; the LANDED reactive `decide`/`compute_features`, survival
    `admit`/`assess`, and `broker.paper.simulate`).

Requirements: 9.2.
"""

from __future__ import annotations

import inspect
from typing import get_type_hints

from src.calibration.scorer import Label
from src.mcp.broker.models import OrderResult
from src.reactive.features import FeatureSet
from src.reactive.replay.types import DataPort
from src.reactive.telemetry.schema import (
    CorrelationKeys,
    DecisionTraceRow,
    FillOutcomeRow,
)
from src.reactive.types import ReactiveDecision

from tests.unit.reactive.replay import _fixtures as fx


# --- fixture DataPort: structurally satisfies the Protocol, no network -------


def test_fixture_dataport_satisfies_protocol() -> None:
    """The fixture DataPort is a structural `DataPort` (R9.2 injection seam).

    `runtime_checkable` only proves the five named methods exist (a weak
    structural check — it does NOT verify signatures), but that is exactly the
    isolation seam R9.2 asks for: the future `simulator` accepts any object that
    quacks like a `DataPort`.
    """
    port = fx.make_fixture_dataport()
    assert isinstance(port, DataPort)


def test_fixture_dataport_methods_return_wire_shapes_no_network() -> None:
    """Every named fetch returns a raw-Massive-wire-shaped value, no network.

    Shapes mirror `MassiveDataClient`'s returns (the fixture is a drop-in for the
    real client): bars are `list[dict]` with Polygon `t/o/h/l/c/v`; quotes are
    `{"results": [...]}` carrying `bp`/`ap`; corporate actions are
    `{"splits": [...], "dividends": [...]}`; rf-yield is a bare `float`. The
    feature-set mapping (Bar TypedDicts) is the future `features_adapter`'s job,
    NOT the port's.
    """
    port = fx.make_fixture_dataport()

    bars = port.fetch_daily_bars("AAPL", "2024-01-01", "2024-01-31")
    assert isinstance(bars, list) and bars
    assert {"t", "o", "h", "l", "c", "v"} <= set(bars[0])

    intraday = port.fetch_intraday("AAPL", "2024-01-31")
    assert isinstance(intraday, list) and intraday
    assert {"t", "o", "h", "l", "c", "v"} <= set(intraday[0])

    quotes = port.fetch_quotes("AAPL", "2024-01-31")
    assert isinstance(quotes, dict) and isinstance(quotes["results"], list)
    assert {"bp", "ap"} <= set(quotes["results"][0])

    trades = port.fetch_trades("AAPL", "2024-01-31")
    assert isinstance(trades, dict) and isinstance(trades["results"], list)

    grouped = port.fetch_grouped_daily("2024-01-31")
    assert isinstance(grouped, list) and grouped

    ca = port.fetch_corporate_actions("AAPL", "2024-01-01", "2024-01-31")
    assert set(ca) == {"splits", "dividends"}
    assert isinstance(ca["splits"], list) and isinstance(ca["dividends"], list)
    # The fixture carries at least one cash dividend so a later total-return P&L
    # test (task 5.1) has a dividend to credit.
    assert ca["dividends"], "fixture corp-actions must carry a dividend"

    rf = port.fetch_rf_yield("2024-01-31")
    assert isinstance(rf, float)


# --- stub reactive cores: right-shaped landed values -------------------------


def test_stub_decide_returns_reactive_decision_shape() -> None:
    """The stub `decide` returns a real landed `ReactiveDecision` (canned values)."""
    dec = fx.stub_decide(features=None, direction="LONG", snapshot=None)
    assert isinstance(dec, ReactiveDecision)
    assert dec.decision in ("LONG", "SHORT", "HOLD")
    assert dec.non_final is True  # every reactive decision is vetoable (R4.1)


def test_stub_decide_signature_matches_landed_decide() -> None:
    """The stub `decide` accepts the landed core's positional + keyword params.

    Pinned so the future `simulator`'s `decide(features, direction, snapshot,
    runtime_threshold=...)` call lines up against the stub.
    """
    params = list(inspect.signature(fx.stub_decide).parameters)
    assert params[:3] == ["features", "direction", "snapshot"]
    assert "runtime_threshold" in params


def test_stub_compute_features_returns_featureset_shape() -> None:
    """The stub `compute_features` returns a real landed `FeatureSet`."""
    fs = fx.stub_compute_features(ticker_bars=[], spy_close=[], rf_yield_pct=4.0)
    assert isinstance(fs, FeatureSet)
    assert isinstance(fs.raw, dict)


# --- stub survival cores: MIRRORED shapes (src.survival not landed here) ------


def test_stub_admit_returns_admit_decision_shape() -> None:
    """The stub `admit` returns a mirrored `AdmitDecision` (ALLOW/REJECT).

    `src.survival` is DESIGNED-not-landed in this worktree, so the survival
    contracts are MIRRORED locally in `_fixtures` (named to match) — the swap to
    real `src.survival` imports is the revalidation trigger when survival lands.
    """
    out = fx.stub_admit(
        order=None, state=None, op_state=None, params=None, clock=None,
        evaluation=None,
    )
    assert out.decision in ("ALLOW", "REJECT")


def _positional_params(fn) -> list[str]:  # noqa: ANN001
    """The POSITIONAL_OR_KEYWORD params of `fn` (the part a caller's call site
    pins). Keyword-only test-ergonomics knobs on the stubs are excluded — the
    simulator's call site supplies only the positional core args."""
    return [
        name
        for name, p in inspect.signature(fn).parameters.items()
        if p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    ]


def test_stub_admit_signature_includes_order_evaluation() -> None:
    """The stub `admit` matches the in-progress `survival-gate-impl` signature.

    The real `admit(order, state, op_state, params, clock, evaluation)` carries a
    SIXTH `OrderEvaluation` arg that the design's Allowed-Dependencies stub list
    omits — the stub follows the LANDED-in-progress signature (flagged in the
    status report CONCERNS). (Keyword-only test knobs on the stub are excluded
    via `_positional_params` — they are not part of the real core's call site.)
    """
    assert _positional_params(fx.stub_admit) == [
        "order", "state", "op_state", "params", "clock", "evaluation",
    ]


def test_stub_assess_returns_assess_directive_shape() -> None:
    """The stub `assess` returns a mirrored `AssessDirective` with an op-state."""
    out = fx.stub_assess(state=None, op_state=None, params=None, clock=None)
    assert hasattr(out, "next_op_state")
    assert isinstance(out.reduce_directives, list)
    assert isinstance(out.events, list)


def test_stub_assess_signature_matches_landed_assess() -> None:
    """The stub `assess` matches the in-progress `assess` positional signature."""
    assert _positional_params(fx.stub_assess) == ["state", "op_state", "params", "clock"]


# --- stub broker paper.simulate: real landed OrderResult ---------------------


def test_stub_paper_simulate_returns_order_result_shape() -> None:
    """The stub `paper.simulate` returns a real landed `OrderResult`.

    The real `paper.py` uses sys.path-bootstrap bare imports (`from models import
    ...`) that do not resolve under the `src.*` package path, so the stub returns
    a freshly-built `OrderResult` rather than calling the real `simulate`; the
    OUTPUT type is the landed contract so the future `simulator` reads it natively.
    """
    res = fx.stub_paper_simulate(intent=None, bid=10.0, ask=10.02)
    assert isinstance(res, OrderResult)
    assert res.status == "simulated"
    assert res.fill_price is not None


def test_stub_paper_simulate_signature_matches_landed_simulate() -> None:
    """The stub `paper.simulate` matches the landed keyword-only signature.

    Pinned so the future `simulator`'s `paper.simulate(intent, bid=, ask=, ...)`
    call lines up.
    """
    params = inspect.signature(fx.stub_paper_simulate).parameters
    assert "intent" in params
    for kw in ("bid", "ask", "position_volume"):
        assert params[kw].kind is inspect.Parameter.KEYWORD_ONLY


# --- champion fixture rows: real landed decision_process_trace shapes ---------


def test_champion_decision_row_is_landed_trace_shape() -> None:
    """The champion decision fixture is a real `DecisionTraceRow` with keys."""
    row = fx.make_champion_decision_row()
    assert isinstance(row, DecisionTraceRow)
    assert isinstance(row.keys, CorrelationKeys)
    assert isinstance(row.trace, dict)
    assert row.keys.run_id  # the P3 key threading the row


def test_champion_fill_row_links_to_decision() -> None:
    """The champion fill fixture is a `FillOutcomeRow` linked to a decision row.

    A linked fill (not a mutation) is the champion baseline the harness↔fidelity
    reproduction (R7) FIFO-pairs against; the fixture supplies that baseline.
    """
    decision = fx.make_champion_decision_row()
    fill = fx.make_champion_fill_row(parent_trace_id=decision.trace_id)
    assert isinstance(fill, FillOutcomeRow)
    assert fill.parent_trace_id == decision.trace_id
    assert isinstance(fill.keys, CorrelationKeys)


# --- canonical-vocabulary reuse (P9): the champion label is a real Label -----


def test_champion_realized_label_is_canonical_label() -> None:
    """The champion fixture's realized label is the canonical `Label` (P9)."""
    label = fx.make_champion_realized_label()
    assert isinstance(label, Label)


# --- determinism: the canned constructors are pure (R9.1-adjacent) -----------


def test_fixture_constructors_are_deterministic() -> None:
    """Identical calls return equal canned values (frozen dataclasses, no clock).

    Underpins R9.1 (identical inputs → identical record): the fixtures introduce
    no nondeterminism (no `now()`, no RNG) into a replay unit test.
    """
    assert fx.make_champion_decision_row() == fx.make_champion_decision_row()
    a = get_type_hints(DecisionTraceRow)  # importable + introspectable, no DB
    assert "keys" in a
