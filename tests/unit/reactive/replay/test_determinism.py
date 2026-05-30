"""Inner-ring determinism + isolation + revalidation-guard suite (Task 4.1).

The dedicated hardening suite for the highest-risk tuning component (P14: the
inner ring must be trustworthy before any promotion rests on it). Three ACs,
three sections:

  * **R9.1 — determinism.** Calling `replay_candidate` twice with the SAME
    injected fixture `DataPort` + same candidate + same window yields IDENTICAL
    `OutcomeRecords` (and an identical whole `ReplayResult`, fidelity included).
    Deeper than `test_harness.test_identical_inputs_yield_identical_records`,
    which builds a FRESH port per call and compares only `.records` with an
    empty champion: here the SAME port instance is reused (catching port
    statefulness) AND the champion-resim path is exercised (so the fill-synthesis
    `defaultdict`/`sorted` ordering is in scope).

  * **R9.2 — inner-ring isolation.** The WHOLE engine (candidate pass + champion
    re-sim) runs with the fixture `DataPort` + stub cores + fixture champion rows
    + an injected fake `query_trace` + a fake champion-config reader, touching NO
    network, NO DB, NO LLM. Asserted behaviorally: `psycopg` is never imported
    (the prod DB driver is genuinely absent from the inner-ring venv — the lazy
    import inside `_read_champion_config_p2` is never reached); a booby-trapped
    production `MassiveDataClient` is never constructed when a `data_port` is
    injected (the network seam short-circuits); no LLM SDK is imported.

  * **R10.3 — revalidation guard.** A test that FAILS if a DRIVEN core's
    interface changes shape. Two complementary halves:
      - a RECORDING stub captures the call-site arity the harness invokes the
        cores with (`decide` ← 3 positional, `admit` ← 6 positional) — catches
        call-site drift;
      - `inspect.signature(<landed core>).bind(...)` pins the REAL landed
        signatures (`decide`/`admit`/`assess`) — catches core-signature drift the
        injected stub would otherwise mask (a stub stands in for the core, so a
        new required core param would never surface through the stub alone).
    Together they bracket R10.3: "if a driven core's interface changes shape, the
    harness shall be revalidated against the new shape."

Source of truth: requirements.md R9 AC 9.1 + 9.2, R10 AC 10.3; design.md the
`harness` block + the dependency-direction note. P14 inner ring (no LLM, no MCP,
no live DB). TEST-ONLY: this file adds coverage; it modifies no `src/`.

Requirements: 9.1, 9.2, 10.3.
"""

from __future__ import annotations

import inspect
import sys
from typing import Any

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
    FixtureDataPort,
    make_correlation_keys,
    make_fixture_dataport,
    stub_admit,
    stub_decide,
)
from src.reactive.features import FeatureSet


# --------------------------------------------------------------------------- #
# Local seams (mirror test_harness.py: the real compute_daily_features over the
# 3 canned bars degrades to a FeatureFailure, so inject a directional FeatureSet
# carrying a verbatim `raw["tactical_bin"]` + `raw["atr"]` to drive the
# actionable path; champion rows are raw query_trace DICTS, not the dataclass
# fixture builders — the harness reads rows with `.get(...)` / `row[...]`).
# --------------------------------------------------------------------------- #


def _feature_set(*, tactical_bin: str = "positive") -> FeatureSet:
    """A directional `FeatureSet` (`raw["atr"]` is the build-order stop input)."""
    _bin_to_vote = {"positive": 1.0, "negative": -1.0, "neutral": 0.0, "unavailable": 0.0}
    return FeatureSet(
        trend_vote=_bin_to_vote.get(tactical_bin, 0.0),
        flow_vote=0.5,
        meanrev_vote=0.0,
        trend_strength=0.5,
        raw={"rsi_14": 55.0, "tactical_bin": tactical_bin, "atr": 1.2},
    )


def _features_fn(*, tactical_bin: str = "positive"):
    """An injectable `features_fn(symbol, day, data_port)` (the 3-arg call site)."""

    def _fn(symbol: str, day: str, data_port: Any) -> FeatureSet:
        return _feature_set(tactical_bin=tactical_bin)

    return _fn


def _candidate() -> Candidate:
    """A candidate carrying the inner-ring DEFAULTS snapshots (R1.3)."""
    return Candidate(
        param_snapshot=REACTIVE_DEFAULTS,
        survival_parameters=SURVIVAL_DEFAULTS,
        code_version=None,
    )


def _window(tickers: list[str] | None = None) -> ReplayWindow:
    return ReplayWindow(start="2024-01-01", end="2024-01-03", tickers=tickers or ["AAPL"])


def _allow_admit(order, account, op_state, params, clock, evaluation):
    """A 6-positional admit stub that ALLOWs every order (the harness call site)."""
    return stub_admit(order, account, op_state, params, clock, evaluation, decision="ALLOW")


# --- raw query_trace champion rows (DICTS — the shape the harness reads) ------


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
    """A raw `query_trace` champion FILL-row dict (kind == 'fill')."""
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


def _champion_rows() -> tuple[list[dict], list[dict]]:
    """A one-day LONG champion round trip (decision + entry/exit fills) so the
    fidelity re-sim path is fully exercised (not just the candidate pass)."""
    day = "2024-01-01"
    dec_id = "dec-AAPL-2024-01-01"
    decision_rows = [
        _champion_decision_row(symbol="AAPL", day=day, decision="LONG", trace_id=dec_id),
    ]
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
    return decision_rows, fill_rows


def _fake_query_trace_with_champion(decision_rows: list[dict], fill_rows: list[dict]):
    """A fake `query_trace` routing by the `kind=` filter (no DB; R9.2/R10.1)."""

    def _fn(filters: dict | None = None) -> list[dict]:
        kind = (filters or {}).get("kind")
        if kind == "decision":
            return list(decision_rows)
        if kind == "fill":
            return list(fill_rows)
        return list(decision_rows) + list(fill_rows)

    return _fn


def _fake_champion_config_reader(param_version: str, *, conn: Any = None) -> Candidate:
    """A fake P2 champion-config reader → the champion's pinned Candidate (no DB)."""
    return Candidate(
        param_snapshot=REACTIVE_DEFAULTS,
        survival_parameters=SURVIVAL_DEFAULTS,
        code_version=None,
    )


def _run_full_engine(port: FixtureDataPort, *, tolerance: float = 1.0) -> ReplayResult:
    """Drive the WHOLE engine — candidate pass + champion re-sim — on `port`.

    Exercises both halves of the harness (the candidate's own path AND the
    champion-reproduction fidelity precondition) with stub cores, fixture champion
    rows, and the fake DB-facing readers — the R9.2 isolation surface.
    """
    decision_rows, fill_rows = _champion_rows()
    return replay_candidate(
        _candidate(),
        ReplayWindow(start="2024-01-01", end="2024-01-01", tickers=["AAPL"]),
        data_port=port,
        query_trace_fn=_fake_query_trace_with_champion(decision_rows, fill_rows),
        champion_keys=make_correlation_keys(),
        champion_config_reader=_fake_champion_config_reader,
        decide_fn=stub_decide,
        features_fn=_features_fn(tactical_bin="positive"),
        admit_fn=_allow_admit,
        tolerance=tolerance,
    )


# ============================================================================ #
# R9.1 — determinism: SAME port + same config + same window ⇒ IDENTICAL result
# ============================================================================ #


def test_same_port_twice_yields_identical_outcome_records() -> None:
    """R9.1: two `replay_candidate` calls over the SAME fixture `DataPort` instance,
    same candidate, same window ⇒ IDENTICAL `OutcomeRecords`.

    Reusing the SAME port instance (not a fresh one per call) is the stronger
    contract: it catches any hidden port statefulness that a fresh-port test
    cannot. Frozen dataclasses give value equality, so list `==` is element-wise.
    """
    port = make_fixture_dataport()

    first = _run_full_engine(port)
    second = _run_full_engine(port)

    assert first.records == second.records
    # The records are genuinely populated (not a vacuous empty-list equality).
    assert first.records
    assert all(isinstance(r, OutcomeRecord) for r in first.records)


def test_same_port_twice_yields_identical_full_result_incl_fidelity() -> None:
    """R9.1: identity extends to the WHOLE `ReplayResult` — the champion-resim
    `FidelityResult` is identical too (the fill-synthesis ordering is stable),
    yet the two results are DISTINCT objects (a is not b — no shared mutable
    state leaked across the calls)."""
    port = make_fixture_dataport()

    first = _run_full_engine(port)
    second = _run_full_engine(port)

    assert first == second  # whole frozen ReplayResult, fidelity included
    assert first is not second
    assert first.fidelity == second.fidelity
    # The fidelity precondition was actually evaluated against the champion rows.
    assert first.fidelity.status in ("pass", "fail")


def test_determinism_holds_for_neutral_flat_window() -> None:
    """R9.1: determinism is not a fluke of the actionable path — a flat (neutral
    bin) window over the same port is identical run-to-run too."""
    port = make_fixture_dataport()

    def _run() -> ReplayResult:
        return replay_candidate(
            _candidate(),
            _window(["AAPL"]),
            data_port=port,
            query_trace_fn=_fake_query_trace_with_champion([], []),
            champion_keys=make_correlation_keys(),
            champion_config_reader=_fake_champion_config_reader,
            decide_fn=stub_decide,
            features_fn=_features_fn(tactical_bin="neutral"),
            admit_fn=_allow_admit,
        )

    assert _run() == _run()


# ============================================================================ #
# R9.2 — inner-ring isolation: NO network / NO DB / NO LLM
# ============================================================================ #


def test_full_engine_runs_with_no_db_driver_imported() -> None:
    """R9.2: the WHOLE engine (candidate pass + champion re-sim) runs through the
    fixture port + stubs + fake readers WITHOUT importing the prod DB driver.

    `psycopg` is the only DB seam (lazily imported inside
    `_read_champion_config_p2`, which the injected `champion_config_reader`
    bypasses). It is genuinely absent from the inner-ring venv, so its presence in
    `sys.modules` after a full run is a strong, behavioral proof that no DB path
    was taken — not merely that a connection was mocked.
    """
    result = _run_full_engine(make_fixture_dataport())

    assert isinstance(result, ReplayResult)
    assert result.records  # the engine actually produced per-day records
    assert "psycopg" not in sys.modules, (
        "the prod DB driver was imported — the engine reached a live-DB path; the "
        "injected query_trace / champion_config_reader must short-circuit it (R9.2)."
    )


def test_injected_port_short_circuits_prod_data_client_construction(monkeypatch) -> None:
    """R9.2: when a `data_port` is injected, the production `MassiveDataClient`
    (the network/httpx seam) is NEVER constructed.

    Booby-trap the harness's `MassiveDataClient` so any attempt to build it
    explodes; the engine must still return a `ReplayResult` because the injected
    fixture port short-circuits `port = data_port if data_port is not None else
    MassiveDataClient()`. This proves isolation at the network boundary
    behaviorally (httpx itself is transitively imported by `data_client` at module
    load — see CONCERNS — so the proof is "the prod client is never built", not
    "httpx is unimportable").
    """

    class _BoomClient:
        def __init__(self, *a: Any, **k: Any) -> None:
            raise AssertionError(
                "MassiveDataClient was constructed — the injected fixture port did "
                "NOT short-circuit the prod network client (R9.2)."
            )

    monkeypatch.setattr(harness, "MassiveDataClient", _BoomClient)

    result = _run_full_engine(make_fixture_dataport())

    assert isinstance(result, ReplayResult)
    assert result.records


def test_full_engine_imports_no_llm_sdk() -> None:
    """R9.2: the inner ring drives deterministic cores only — no LLM SDK is pulled
    in by importing or running the engine (P14: no LLM in the inner ring)."""
    _run_full_engine(make_fixture_dataport())

    for sdk in ("anthropic", "openai"):
        assert sdk not in sys.modules, f"an LLM SDK ({sdk}) leaked into the inner ring (R9.2)"


# ============================================================================ #
# R10.3 — revalidation guard: FAIL if a driven core's interface changes shape
# ============================================================================ #


class _RecordingDecide:
    """A recording `decide_fn`: records the positional arity the harness calls it
    with, then delegates to the canned `stub_decide` so the path still runs."""

    def __init__(self) -> None:
        self.arities: list[int] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.arities.append(len(args))
        return stub_decide(*args, **kwargs)


class _RecordingAdmit:
    """A recording `admit_fn`: records the positional arity the harness's
    `apply_admit_gating` invokes the survival admit core with."""

    def __init__(self) -> None:
        self.arities: list[int] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.arities.append(len(args))
        return stub_admit(*args, **kwargs, decision="ALLOW")


# Pinned call-site arities (the shapes the harness/simulator drive the cores with).
# A drift in EITHER the harness call site OR these pins is the R10.3 trigger.
_DECIDE_CALL_ARITY = 3   # decide(features, direction, snapshot)
_ADMIT_CALL_ARITY = 6    # admit(order, state, op_state, params, clock, evaluation)


def test_harness_calls_decide_with_expected_call_site_arity() -> None:
    """R10.3 (call-site half): the harness drives the reactive decision core with
    exactly 3 positional args. A recording stub captures the arity; if the harness
    call site grows/shrinks an argument this assertion fails (revalidation due)."""
    rec = _RecordingDecide()

    replay_candidate(
        _candidate(),
        _window(["AAPL"]),
        data_port=make_fixture_dataport(),
        query_trace_fn=_fake_query_trace_with_champion([], []),
        champion_keys=make_correlation_keys(),
        champion_config_reader=_fake_champion_config_reader,
        decide_fn=rec,
        features_fn=_features_fn(tactical_bin="positive"),
        admit_fn=_allow_admit,
    )

    assert rec.arities, "the harness must drive the reactive decision core (R3.1)"
    assert all(n == _DECIDE_CALL_ARITY for n in rec.arities), (
        f"decide called with positional arities {rec.arities}, expected all "
        f"{_DECIDE_CALL_ARITY} — the driven-core call site changed shape (R10.3)."
    )


def test_harness_calls_admit_with_expected_call_site_arity() -> None:
    """R10.3 (call-site half): the harness's `apply_admit_gating` drives the
    survival admit core with exactly 6 positional args (the contested 6th
    `evaluation`). A recording stub captures it; a shape change fails here."""
    rec = _RecordingAdmit()

    replay_candidate(
        _candidate(),
        _window(["AAPL"]),
        data_port=make_fixture_dataport(),
        query_trace_fn=_fake_query_trace_with_champion([], []),
        champion_keys=make_correlation_keys(),
        champion_config_reader=_fake_champion_config_reader,
        decide_fn=stub_decide,
        features_fn=_features_fn(tactical_bin="positive"),
        admit_fn=rec,
    )

    assert rec.arities, "the harness must gate orders through the survival admit core (R3.1)"
    assert all(n == _ADMIT_CALL_ARITY for n in rec.arities), (
        f"admit called with positional arities {rec.arities}, expected all "
        f"{_ADMIT_CALL_ARITY} — the driven-core call site changed shape (R10.3)."
    )


def test_landed_decide_signature_still_binds_call_site_arity() -> None:
    """R10.3 (core-signature half): the REAL landed reactive `decide` still accepts
    the harness call-site arity.

    The recording stub stands in for the core at runtime, so a new REQUIRED
    parameter on the landed core would never surface through it — this `inspect`
    bind pins the actual landed signature so such drift goes RED. Pairs with the
    call-site test above to bracket R10.3."""
    from src.reactive.signal_model import decide as landed_decide

    sentinel = object()
    sig = inspect.signature(landed_decide)
    # Must accept the 3 positional args the harness drives it with.
    sig.bind(sentinel, sentinel, sentinel)  # raises TypeError on arity drift


def test_landed_admit_signature_still_binds_call_site_arity() -> None:
    """R10.3 (core-signature half): the REAL landed survival `admit` still accepts
    the harness call-site arity (6 positional, incl. the contested `evaluation`).
    A required-arg drift on the landed core raises here (revalidation due)."""
    from src.survival.gate import admit as landed_admit

    sentinel = object()
    sig = inspect.signature(landed_admit)
    sig.bind(sentinel, sentinel, sentinel, sentinel, sentinel, sentinel)


def test_landed_survival_assess_signature_pinned() -> None:
    """R10.3: the survival `assess` core (named alongside `admit` in R10.3) keeps
    its 4-positional shape (`state, op_state, params, clock`).

    The current harness path gates entries via `admit` only; `assess` is pinned
    here because R10.3 names it explicitly, so a shape change is flagged for
    revalidation even though the harness does not yet drive it (CONCERN)."""
    from src.survival.gate import assess as landed_assess

    sentinel = object()
    sig = inspect.signature(landed_assess)
    sig.bind(sentinel, sentinel, sentinel, sentinel)
