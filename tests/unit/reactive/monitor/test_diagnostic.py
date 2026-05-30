"""Pure-unit tests for the In-Session Monitor calibration-drift diagnostic.

Task 2.1 (in-session-monitor). Asserts the design's "Leaf — diagnostic" contract
(`compute_drift(filters, params, label_source, conn=None) -> DriftDiagnostic`) and
the "Baseline-ownership decision (corrected 2026-05-30)" calibration-substrate
seam:

  (a) version-scoping — a window that crosses a hot-swap is restricted to the
      CURRENT (latest) `(code_version, param_version)` rows only; the diagnostic's
      `keys` + `window_n` come from that scoped set;
  (b) below `params.min_observations` (incl. the post-hot-swap refill window) ->
      `sufficient=False`, no metrics;
  (c) an injected SYNTHETIC `RealizedLabelSource` (with labeled pairs) drives the
      calibration-compute path: brier/ece observed + block-bootstrap CI from the
      LANDED `src/calibration/metrics.py`, baseline from the per-version
      `MonitorParams.in_sample_baseline`;
  (d) the v0.1 reality — an EMPTY label source (the reactive realized-directional-
      label surface is unlanded, owned by walkforward-tuning-loop) -> the
      diagnostic is correctly blind: `sufficient=False` / INSUFFICIENT.

No DB, no MCP, no LLM: `query_trace` is monkeypatched at the diagnostic module
seam so `compute_drift` never opens a connection (the synthetic rows ARE the
substrate). The landed metrics (`brier_score`, `expected_calibration_error`,
`block_bootstrap_ci`) are reused verbatim — re-computed independently in the
assertions, never hardcoded.

Requirements: 1.2 (read trace + calibration), 2.1 (derived diagnostic), 2.4
(insufficient -> no verdict), 9.1 (read via the landed surface + 4 keys), 9.5
(revalidate on upstream contract change — exercised by importing the landed types).
"""

from __future__ import annotations

import dataclasses as d

import pytest

from src.calibration.metrics import (
    block_bootstrap_ci,
    brier_score,
    expected_calibration_error,
)
from src.reactive.monitor import DriftDiagnostic, MetricObservation, MonitorParams
from src.reactive.monitor import diagnostic as diag_mod
from src.reactive.monitor.diagnostic import RealizedLabelSource, compute_drift
from src.reactive.telemetry import CorrelationKeys


# --- Synthetic substrate (no DB) ------------------------------------------


def _decision_row(
    *,
    code_version: str,
    param_version: str,
    walk_forward_window: str | None = "2026Q1",
    run_id: str = "11111111-1111-1111-1111-111111111111",
    event_ts: str = "2026-05-29T00:00:00Z",
    trace_id: str = "dec",
    probability: float = 0.6,
    liq_proximity: float = 0.1,
    stop_out: bool = False,
    gate_link: str | None = "Edge",
) -> dict:
    """A `decision`-kind row shaped exactly as `query_trace` returns it
    (all mig-048 columns; the version keys live on the row, the softmax
    `probability` + survival-proximity fields live on the JSONB `trace`).

    `gate_link` defaults to `"Edge"` — the normal (non-survival) Edge-link
    decision — so the survival-band derivation is OFF by default and a test
    must opt INTO the band (via `gate_link="Survive"/"safe-mode"` or
    `stop_out=True`). Defaulting to `"Survive"` would mask the band logic by
    forcing every row in-band (the prior-round test-masking defect)."""
    return {
        "trace_id": trace_id,
        "kind": "decision",
        "parent_trace_id": None,
        "event_ts": event_ts,
        "run_id": run_id,
        "code_version": code_version,
        "param_version": param_version,
        "walk_forward_window": walk_forward_window,
        "trace": {
            "gate_link": gate_link,
            "signal_values": {},
            "probability": probability,
            "decision": "long",
            "liq_proximity": liq_proximity,
            "stop_out": stop_out,
            "declined": False,
        },
        "created_at": event_ts,
    }


def _params(*, min_observations: int = 5) -> MonitorParams:
    """A P2-shaped `MonitorParams` with a per-metric `in_sample_baseline`
    (the per-version reference the diagnostic populates onto each
    `MetricObservation.baseline`)."""
    return MonitorParams(
        min_observations=min_observations,
        window_W=50,
        margin_M=0.02,
        severity_cutoffs={"mild": 0.05, "severe": 0.15},
        in_sample_baseline={"brier": 0.21, "ece": 0.03},
        cadence_seconds=300,
    )


class _StubLabelSource:
    """Synthetic `RealizedLabelSource`: yields a fixed `(probability, label)`
    pair list regardless of the rows (the calibration-compute driver for test c).
    `calls` records the rows it was handed so version-scoping can be asserted."""

    def __init__(self, pairs: list[tuple[float, bool]]) -> None:
        self._pairs = pairs
        self.calls: list[list[dict]] = []

    def labels_for(self, rows: list[dict]) -> list[tuple[float, bool]]:
        self.calls.append(list(rows))
        return list(self._pairs)


class _EmptyLabelSource:
    """The v0.1 reality: the reactive realized-directional-label surface is
    unlanded, so this source yields NO labels -> the diagnostic is blind."""

    def labels_for(self, rows: list[dict]) -> list[tuple[float, bool]]:
        return []


def _patch_query_trace(monkeypatch, rows: list[dict]) -> dict:
    """Monkeypatch the diagnostic's `query_trace` seam to return `rows` without a
    DB. Returns a dict the test can inspect: `captured["filters"]` is the filter
    dict `compute_drift` passed (so we can assert it requested `kind='decision'`),
    `captured["conn"]` the conn it forwarded."""
    captured: dict = {}

    def _fake_query_trace(filters=None, conn=None):
        captured["filters"] = filters
        captured["conn"] = conn
        return list(rows)

    monkeypatch.setattr(diag_mod, "query_trace", _fake_query_trace)
    return captured


# --- (a) version-scoping: hot-swap window keeps only the CURRENT version ----


def test_window_crossing_hotswap_scopes_to_current_version_only(monkeypatch) -> None:
    # 3 rows on the OLD version, then 6 on the CURRENT (latest) version.
    old = [
        _decision_row(code_version="c1", param_version="p1", trace_id=f"old-{i}",
                      event_ts=f"2026-05-29T00:0{i}:00Z", probability=0.9, stop_out=False)
        for i in range(3)
    ]
    cur = [
        _decision_row(code_version="c2", param_version="p2", trace_id=f"cur-{i}",
                      event_ts=f"2026-05-29T01:0{i}:00Z", probability=0.5, stop_out=False)
        for i in range(6)
    ]
    captured = _patch_query_trace(monkeypatch, old + cur)
    src = _StubLabelSource([(0.5, True)] * 6)

    out = compute_drift({"since": "2026-05-29T00:00:00Z"}, _params(min_observations=5), src)

    # Only the 6 current-version rows count (the prior version is dropped, not mixed).
    assert out.window_n == 6
    # The diagnostic's 4 keys are the CURRENT analyzed version's (Issue 1).
    assert out.keys == CorrelationKeys(
        run_id="11111111-1111-1111-1111-111111111111",
        code_version="c2",
        param_version="p2",
        walk_forward_window="2026Q1",
    )
    # The label source was handed ONLY the scoped (current-version) rows.
    assert len(src.calls) == 1
    assert {(r["code_version"], r["param_version"]) for r in src.calls[0]} == {("c2", "p2")}
    # And the read asked the landed surface for decision rows specifically.
    assert captured["filters"]["kind"] == "decision"
    assert captured["filters"]["since"] == "2026-05-29T00:00:00Z"


# --- (b) below the floor (incl. post-hot-swap refill) -> insufficient --------


def test_window_below_min_observations_is_insufficient(monkeypatch) -> None:
    # Only 2 current-version rows, floor is 5 -> the monitor is correctly blind.
    cur = [
        _decision_row(code_version="c2", param_version="p2", trace_id=f"cur-{i}",
                      event_ts=f"2026-05-29T01:0{i}:00Z")
        for i in range(2)
    ]
    _patch_query_trace(monkeypatch, cur)
    # A non-empty source proves the floor (not the label gate) drives insufficiency.
    src = _StubLabelSource([(0.5, True), (0.5, False)])

    out = compute_drift({}, _params(min_observations=5), src)

    assert out.sufficient is False
    assert out.metrics == {}
    assert out.window_n == 2


def test_empty_trace_is_insufficient_and_falls_back_to_filter_keys(monkeypatch) -> None:
    _patch_query_trace(monkeypatch, [])
    src = _StubLabelSource([(0.5, True)])

    out = compute_drift(
        {"code_version": "cX", "param_version": "pX", "run_id": "r9", "walk_forward_window": "2026Q2"},
        _params(min_observations=5),
        src,
    )

    assert out.sufficient is False
    assert out.window_n == 0
    assert out.metrics == {}
    # No rows[-1] to read -> keys fall back to the filter, no IndexError.
    assert out.keys.code_version == "cX"
    assert out.keys.param_version == "pX"
    # The unlanded source is never even asked when there are no rows.
    assert src.calls == []


# --- (c) injected synthetic source drives the calibration-compute path -------


def test_sufficient_window_computes_brier_ece_ci_and_baseline(monkeypatch) -> None:
    cur = [
        _decision_row(code_version="c2", param_version="p2", trace_id=f"cur-{i}",
                      event_ts=f"2026-05-29T01:{i:02d}:00Z", probability=0.5 + 0.01 * i,
                      stop_out=False)
        for i in range(8)
    ]
    _patch_query_trace(monkeypatch, cur)
    # The realized (probability, directional-label) pairs the seam yields.
    pairs = [(0.6, True), (0.55, False), (0.7, True), (0.65, True),
             (0.4, False), (0.45, True), (0.8, True), (0.5, False)]
    src = _StubLabelSource(pairs)
    params = _params(min_observations=5)

    out = compute_drift({}, params, src)

    assert out.sufficient is True
    assert out.window_n == 8
    assert set(out.metrics) == {"brier", "ece"}

    scores = [p for p, _ in pairs]
    labels = [y for _, y in pairs]

    # Brier: observed is the landed brier_score recomputed; CI from the landed
    # seeded block_bootstrap_ci; baseline is the per-version pinned value.
    brier = out.metrics["brier"]
    assert isinstance(brier, MetricObservation)
    assert brier.observed == pytest.approx(brier_score(scores, labels))
    exp_brier_ci = block_bootstrap_ci(brier_score, scores, labels)
    assert brier.ci_low == pytest.approx(exp_brier_ci.lower)
    assert brier.ci_high == pytest.approx(exp_brier_ci.upper)
    assert brier.ci_low <= brier.observed <= brier.ci_high
    assert brier.baseline == params.in_sample_baseline["brier"]

    # ECE: same recompute-and-compare against the landed metric.
    ece = out.metrics["ece"]
    assert ece.observed == pytest.approx(expected_calibration_error(scores, labels))
    assert ece.baseline == params.in_sample_baseline["ece"]

    # in_survival_band derives categorically from the latest scoped row's stop_out.
    assert out.in_survival_band is False


def test_in_survival_band_true_when_latest_decision_stopped_out(monkeypatch) -> None:
    cur = [
        _decision_row(code_version="c2", param_version="p2", trace_id=f"cur-{i}",
                      event_ts=f"2026-05-29T01:{i:02d}:00Z", stop_out=(i == 5))
        for i in range(6)
    ]
    _patch_query_trace(monkeypatch, cur)
    src = _StubLabelSource([(0.5, True)] * 6)

    out = compute_drift({}, _params(min_observations=5), src)

    # Latest scoped row (i==5) carries stop_out=True -> inside the survival band.
    assert out.in_survival_band is True


@pytest.mark.parametrize("gate_link", ["Survive", "safe-mode", "SAFE_MODE", "survive"])
def test_in_survival_band_true_when_latest_gate_link_is_survival(
    monkeypatch, gate_link
) -> None:
    # The latest scoped decision binds on a survival/safe-mode gate_link WITHOUT
    # a stop_out — the band must be derived CATEGORICALLY from gate_link too, not
    # only from stop_out (decision-trace-telemetry design.md:130/research.md:57:
    # safe-mode/flatten exit rows carry gate_link = Survive/safe-mode). The token
    # match is hyphen/underscore- and case-tolerant (the runtime string from the
    # unlanded daemon trace_assembler is not yet pinnable — R9.5 revalidation).
    cur = [
        _decision_row(code_version="c2", param_version="p2", trace_id=f"cur-{i}",
                      event_ts=f"2026-05-29T01:{i:02d}:00Z", stop_out=False,
                      gate_link=(gate_link if i == 5 else "Edge"))
        for i in range(6)
    ]
    _patch_query_trace(monkeypatch, cur)
    src = _StubLabelSource([(0.5, True)] * 6)

    out = compute_drift({}, _params(min_observations=5), src)

    # Latest scoped row binds on a survival/safe-mode link -> inside the band,
    # even though stop_out is False (the branch the prior suite never exercised).
    assert out.in_survival_band is True


@pytest.mark.parametrize("gate_link", ["Edge", "Preserve", "Return", None])
def test_in_survival_band_false_for_non_survival_gate_link(monkeypatch, gate_link) -> None:
    # "Edge"/"Return" are normal non-survival links. "Preserve" is the next
    # lexicographic link BELOW Survive (Survive > Preserve > Edge > Return): if
    # only Preserve binds, the Survive constraint is NOT binding -> the account is
    # INSIDE hard-survival limits -> exactly the R2.2 condition the monitor MUST
    # act on. So "Preserve" is OUT of the band by requirement, not just unattested.
    # None (older/unset trace rows) is also out-of-band and must not error.
    cur = [
        _decision_row(code_version="c2", param_version="p2", trace_id=f"cur-{i}",
                      event_ts=f"2026-05-29T01:{i:02d}:00Z", stop_out=False,
                      gate_link=gate_link)
        for i in range(6)
    ]
    _patch_query_trace(monkeypatch, cur)
    src = _StubLabelSource([(0.5, True)] * 6)

    out = compute_drift({}, _params(min_observations=5), src)

    assert out.in_survival_band is False


# --- (d) v0.1 empty source -> sufficient=False (INSUFFICIENT, correctly blind) -


def test_empty_label_source_is_insufficient_even_with_full_window(monkeypatch) -> None:
    # ENOUGH rows (8 >= floor 5): the floor passes; the LABEL gate fails because
    # the reactive realized-directional-outcome surface is unlanded (v0.1).
    cur = [
        _decision_row(code_version="c2", param_version="p2", trace_id=f"cur-{i}",
                      event_ts=f"2026-05-29T01:{i:02d}:00Z")
        for i in range(8)
    ]
    _patch_query_trace(monkeypatch, cur)

    out = compute_drift({}, _params(min_observations=5), _EmptyLabelSource())

    assert out.window_n == 8  # the window itself was sufficient...
    assert out.sufficient is False  # ...but with no labels the diagnostic is blind.
    assert out.metrics == {}


# --- contract / shape guards ----------------------------------------------


def test_returns_frozen_drift_diagnostic(monkeypatch) -> None:
    _patch_query_trace(monkeypatch, [])
    out = compute_drift({}, _params(), _EmptyLabelSource())
    assert isinstance(out, DriftDiagnostic)
    with pytest.raises(d.FrozenInstanceError):
        out.window_n = 99  # type: ignore[misc]


def test_realized_label_source_is_a_runtime_checkable_protocol() -> None:
    # The synthetic stub satisfies the seam structurally (Protocol injection).
    assert isinstance(_StubLabelSource([]), RealizedLabelSource)
    assert isinstance(_EmptyLabelSource(), RealizedLabelSource)
