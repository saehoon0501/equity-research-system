"""In-Session Monitor: the calibration-drift diagnostic (leaf).

The behavioral-judgment *computation* leaf at the head of the live read path:
read the recent decision-trace via the landed `query_trace` surface, scope it to
a SINGLE `(code_version, param_version)` (calibration is meaningless across a
hot-swap — Issue 1), and compute the derived calibration figures over that
version-scoped window using the LANDED `src/calibration/metrics.py` (Brier / ECE
+ block-bootstrap CI). Emits a `DriftDiagnostic` (per-metric observed + CI +
per-version baseline, the survival-band flag, `window_n`, `sufficient`) or an
explicit insufficient result. Pure read; NO write; reuses landed metrics and the
landed reader (no reimplementation). Satisfies requirements 1.2, 2.1, 2.4, 9.1,
9.5 and the design's "Leaf — diagnostic".

CALIBRATION-SUBSTRATE SEAM (design "Baseline-ownership decision, corrected
2026-05-30"): the reactive per-decision realized *directional* label — *was
`P(caller direction)` the correct side?* — is NOT carried on
`decision_process_trace` (decision rows carry the softmax `probability` only;
fill rows carry fill-quality only) and is **owned by `walkforward-tuning-loop`/a
future reactive realized-outcome surface, not yet landed** (`signal_model.py`
R7.4). `counterfactual_ledger` is the slow-layer outer-ring eval ledger (wrong
grain + outcome vocabulary) and is **not** the substrate — this leaf NEVER reads
it and NEVER fabricates a label. Instead the realized labels arrive through an
INJECTED `RealizedLabelSource` Protocol: the orchestrator supplies the source,
and for v0.1 it yields NO reactive labels -> the diagnostic returns INSUFFICIENT
(correctly blind on calibration drift until that surface lands). The unit tests
inject a synthetic source to drive the calibration-compute path.

Dependency direction (design §Allowed Dependencies, strict left→right):
`types → diagnostic → judge → ...`. This module imports only `types` (own layer),
the landed telemetry reader, the landed calibration metrics, and stdlib/typing —
nothing downward, nothing from `execution-daemon` / `walkforward-tuning-loop`.

Resolution notes (the landed types/metrics narrow the design's prose):
  * `DriftDiagnostic.metrics` is `dict[str, MetricObservation]` where a
    `MetricObservation` is SCALAR (observed/ci_low/ci_high/baseline) and
    `block_bootstrap_ci` needs a SCALAR `metric_fn`. `reliability_diagram`
    returns a non-scalar list with no home on this contract, so the per-metric
    map carries the two scalar proper figures the design's drift rule binds on:
    `"brier"` (the reliability/Brier primary) and `"ece"` (corroborating). The
    reliability diagram itself is not surfaced here (the landed type has no slot);
    this is a conscious narrowing of the design's literal "compute
    reliability_diagram", not a silent omission.
  * `baseline` is the P2-pinned per-metric value `params.in_sample_baseline[m]`,
    not runtime-recomputed: the signature carries no in-sample-window argument, so
    the design's "baseline derived from the same seam" is provenance + a future
    Revalidation trigger (wire the real per-version baseline when the reactive
    realized-outcome surface lands), not a second computation inside this leaf.
  * This leaf does NOT decide drift — "CI excludes baseline by margin M" is the
    `judge` leaf's rule. `compute_drift` only POPULATES observed/CI/baseline.
  * `in_survival_band` is derived CATEGORICALLY from the latest scoped decision's
    survival-proximity fields (design §Leaf — diagnostic: `liq_proximity` /
    `stop_out` / `gate_link`). It is `stop_out` OR a survival/safe-mode `gate_link`
    (Survive / safe-mode — attested in decision-trace-telemetry design.md:130 /
    research.md:57), both CATEGORICAL so they mint no number. The numeric
    `liq_proximity` is DELIBERATELY DROPPED: no P2-pinned proximity cutoff exists,
    so binding on it would assert an unpinned threshold (a P15 violation). `gate_link
    = "Preserve"` is OUT of band: in the chain Survive ⊳ Preserve ⊳ Edge ⊳ Return,
    a binding Preserve means Survive is NOT binding — the account is inside
    hard-survival limits, exactly the R2.2 case the monitor must judge.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

# The `gate_link` tokens that name the deterministic SURVIVAL / safe-mode band
# (Issue 2 / design §Leaf — diagnostic, "liq_proximity / stop_out / gate_link").
# ATTESTED upstream: decision-trace-telemetry design.md:130 + research.md:57 —
# safe-mode/flatten exit rows carry `gate_link = "Survive" / "safe-mode"`. These
# are matched hyphen/underscore- and case-INSENSITIVELY (see `_gate_link_in_band`)
# because the literal runtime string is produced by the daemon `trace_assembler`'s
# `binding_constraint → gate_link` map, which is UNLANDED (lives only in
# `.kiro/specs/execution-daemon/`) and so not yet pinnable against code — tolerance
# guards against the repo's known hyphen/underscore drift (`safe_mode_grade` etc.).
# Tokens, not a numeric threshold: this is a categorical membership test, so it
# mints no unpinned cutoff (no P15 concern, unlike a `liq_proximity` band — below).
# `"Preserve"` is DELIBERATELY EXCLUDED: the chain is Survive ⊳ Preserve ⊳ Edge ⊳
# Return, so if only Preserve binds the *Survive* constraint is NOT binding — the
# account is INSIDE hard-survival limits, which is exactly the R2.2 condition the
# monitor MUST act on. Putting Preserve in-band would suppress the monitor in the
# one case the requirement says it must judge. R9.5 revalidation: re-pin this set
# when the daemon `trace_assembler` lands the real `gate_link` vocabulary.
_SURVIVAL_BAND_GATE_LINKS = frozenset({"survive", "safemode"})

from src.calibration.metrics import (
    block_bootstrap_ci,
    brier_score,
    expected_calibration_error,
)
from src.reactive.monitor.types import (
    DriftDiagnostic,
    MetricObservation,
    MonitorParams,
)
from src.reactive.telemetry import CorrelationKeys
from src.reactive.telemetry.reader import query_trace


@runtime_checkable
class RealizedLabelSource(Protocol):
    """The injected calibration-substrate seam (design "Leaf — diagnostic").

    For a version-scoped window of `decision`-kind rows, yield per-decision
    `(probability, realized_binary_label)` pairs — the softmax probability paired
    with the realized *directional* outcome (was the caller's direction the
    correct side?). That realized label is OWNED by `walkforward-tuning-loop`/a
    future reactive realized-outcome surface (not landed); the v0.1 source yields
    NONE, so the diagnostic is correctly INSUFFICIENT/blind until it lands. The
    monitor INJECTS this seam (it never reads `counterfactual_ledger` — wrong
    grain — and never fabricates a label).
    """

    def labels_for(self, rows: list[dict]) -> list[tuple[float, bool]]: ...


def _scope_to_current_version(rows: list[dict]) -> list[dict]:
    """Restrict a (possibly hot-swap-crossing) window to the CURRENT version only.

    `query_trace` returns rows ordered by `event_ts` ascending and may span a
    hot-swap; calibration across two `(code_version, param_version)` epochs is
    meaningless (Issue 1). The current version is the `(code_version,
    param_version)` of the LATEST decision row (`rows[-1]`); the prior version's
    rows are dropped, not mixed in. Empty input → empty output (the caller then
    falls back to the filter keys).
    """
    if not rows:
        return []
    latest = rows[-1]
    cur = (latest["code_version"], latest["param_version"])
    return [r for r in rows if (r["code_version"], r["param_version"]) == cur]


def _gate_link_in_band(gate_link: Any) -> bool:
    """True when a `gate_link` value names the survival / safe-mode band.

    Categorical membership against `_SURVIVAL_BAND_GATE_LINKS`, normalized so the
    attested `"Survive"` / `"safe-mode"` tokens match regardless of case or
    hyphen/underscore/space punctuation (the runtime string from the unlanded
    daemon `trace_assembler` is not yet pinnable — R9.5 revalidation). A `None`
    or non-string (older / unset trace rows) is OUT of band — never raises, so the
    `... or _gate_link_in_band(...)` derivation short-circuits cleanly.
    """
    if not isinstance(gate_link, str):
        return False
    normalized = gate_link.strip().lower().replace("-", "").replace("_", "").replace(" ", "")
    return normalized in _SURVIVAL_BAND_GATE_LINKS


def _keys_from_row(row: dict) -> CorrelationKeys:
    """The four analyzed-version correlation keys read off a trace row (R7.3 /
    R9.1). One version per diagnostic — the audit pulls its keys from here."""
    return CorrelationKeys(
        run_id=row["run_id"],
        code_version=row["code_version"],
        param_version=row["param_version"],
        walk_forward_window=row["walk_forward_window"],
    )


def _keys_from_filters(filters: dict[str, Any]) -> CorrelationKeys:
    """Fallback keys when the scoped window is empty (no `rows[-1]` to read):
    take whatever the orchestrator pinned in the filter, else None — so an empty
    window still returns a coherent (insufficient) diagnostic, never an
    IndexError."""
    return CorrelationKeys(
        run_id=filters.get("run_id"),
        code_version=filters.get("code_version"),
        param_version=filters.get("param_version"),
        walk_forward_window=filters.get("walk_forward_window"),
    )


def _insufficient(
    keys: CorrelationKeys, window_n: int, in_survival_band: bool
) -> DriftDiagnostic:
    """A no-metrics, `sufficient=False` diagnostic (R2.4): the window is below the
    floor, OR the (v0.1-unlanded) label source yielded no realized labels. No
    verdict, no intervention downstream."""
    return DriftDiagnostic(
        metrics={},
        window_n=window_n,
        in_survival_band=in_survival_band,
        sufficient=False,
        keys=keys,
    )


def compute_drift(
    filters: dict[str, Any],
    params: MonitorParams,
    label_source: RealizedLabelSource,
    conn: Any = None,
) -> DriftDiagnostic:
    """Derive the calibration-drift diagnostic over a version-scoped window.

    Reads `decision`-kind trace rows through the landed `query_trace` surface
    (R9.1 — never reimplemented), scopes them to the current
    `(code_version, param_version)` (a hot-swap-crossing window keeps only the
    current version's rows — Issue 1), obtains the per-decision
    `(probability, realized_binary_label)` pairs from the injected
    `label_source` seam, and computes the derived calibration figures (Brier +
    ECE, each with its block-bootstrap CI) over that window using the LANDED
    `src/calibration/metrics.py`. The per-metric `baseline` is the P2-pinned
    per-version `params.in_sample_baseline[metric]`. Pure read; no write.

    Sufficiency (R2.4) has TWO independent gates — `sufficient` is False when:
      (1) `window_n < params.min_observations` (incl. the expected post-hot-swap
          refill window, where the current-version window is below the floor); OR
      (2) `label_source` yields NO realized labels — the v0.1 reality, since the
          reactive realized-directional-outcome surface is unlanded -> the
          diagnostic is correctly blind (INSUFFICIENT).
    In either case the result carries empty `metrics` and `sufficient=False`.

    Args:
        filters: the `query_trace` filter dict (a time window and/or correlation
            keys). `compute_drift` adds `kind='decision'` so only decision rows
            (the softmax-probability substrate) are read; the value is propagated
            by value (P2) and never re-resolved mid-tick.
        params: the P2-pinned `MonitorParams` (the `min_observations` floor + the
            per-version `in_sample_baseline`), consumed by value.
        label_source: the injected `RealizedLabelSource` seam (v0.1 yields none).
        conn: a psycopg connection forwarded to `query_trace`; None ⟹ the reader
            opens/closes its own (the unit tests monkeypatch `query_trace`, so no
            DB is touched on the pure path).

    Returns:
        A `DriftDiagnostic` — per-metric (observed, CI, baseline) + `window_n` +
        `in_survival_band` + `sufficient`, tagged with the analyzed version's four
        correlation keys.
    """
    # Read only decision rows: the softmax `probability` substrate lives there
    # (fill rows are fill-quality only). `kind` is set by us, not the caller, so
    # the diagnostic always reads the right kind regardless of the filter.
    decision_filters = {**filters, "kind": "decision"}
    rows = query_trace(decision_filters, conn)

    # Restrict a hot-swap-crossing window to the current version's rows only.
    scoped = _scope_to_current_version(rows)
    window_n = len(scoped)

    if not scoped:
        # Empty window -> no row to read keys/stop_out from; fall back to the
        # filter keys, survival-band defaults False, insufficient.
        return _insufficient(_keys_from_filters(filters), window_n, in_survival_band=False)

    keys = _keys_from_row(scoped[-1])
    # `in_survival_band` is derived CATEGORICALLY from the latest scoped decision's
    # survival-proximity trace fields (design §Leaf — diagnostic: "liq_proximity /
    # stop_out / gate_link"). Two categorical signals are OR'd:
    #   * `stop_out` (bool trace key) — the reflex has stopped the position out;
    #   * `gate_link` ∈ {Survive, safe-mode} — the binding lexicographic link is the
    #     deterministic survival / safe-mode reflex (attested upstream:
    #     decision-trace-telemetry design.md:130 / research.md:57), matched
    #     tolerantly via `_gate_link_in_band`.
    # The numeric `liq_proximity` is DELIBERATELY LEFT OUT: there is no P2-pinned
    # proximity cutoff, so binding on it would MINT an unpinned threshold — a P15
    # violation. Categorical `stop_out`/`gate_link` mint no number, so they are
    # safe to include. Inside the band = the deterministic reflex already owns it;
    # the judge gates an actionable verdict on this being False (design §Leaf —
    # judge survival-band gate, R5.3 reflex-first / P7).
    latest_trace = scoped[-1]["trace"]
    in_survival_band = bool(latest_trace.get("stop_out", False)) or _gate_link_in_band(
        latest_trace.get("gate_link")
    )

    # Gate 1: window floor (R2.4) — incl. the expected post-hot-swap blind window.
    if window_n < params.min_observations:
        return _insufficient(keys, window_n, in_survival_band)

    # Gate 2: the realized-label substrate (the v0.1 unlanded-surface reality).
    pairs = label_source.labels_for(scoped)
    if not pairs:
        return _insufficient(keys, window_n, in_survival_band)

    scores = [float(p) for p, _ in pairs]
    labels = [bool(y) for _, y in pairs]

    metrics: dict[str, MetricObservation] = {
        "brier": _observe(brier_score, scores, labels, params.in_sample_baseline.get("brier")),
        "ece": _observe(
            expected_calibration_error, scores, labels, params.in_sample_baseline.get("ece")
        ),
    }

    return DriftDiagnostic(
        metrics=metrics,
        window_n=window_n,
        in_survival_band=in_survival_band,
        sufficient=True,
        keys=keys,
    )


def _observe(
    metric_fn,
    scores: list[float],
    labels: list[bool],
    baseline: float | None,
) -> MetricObservation:
    """Compute one scalar metric's observed value + its seeded block-bootstrap CI
    from the LANDED metrics, paired with the P2-pinned per-version baseline.

    `block_bootstrap_ci` uses the landed locked defaults (block_size=5,
    n_reps=1000, level=0.95, seed=20260527) so the CI is reproducible (P15: the
    figure is derived, never asserted). `baseline` is the pinned per-version
    reference; `None` (an unpinned metric) maps to NaN so the contract field is
    always present (the judge then has no comparison to bind on that metric).
    """
    ci = block_bootstrap_ci(metric_fn, scores, labels)
    return MetricObservation(
        observed=ci.point,
        ci_low=ci.lower,
        ci_high=ci.upper,
        baseline=float(baseline) if baseline is not None else float("nan"),
    )


__all__ = [
    "RealizedLabelSource",
    "compute_drift",
]
