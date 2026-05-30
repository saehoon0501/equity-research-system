"""Pure-unit tests for the In-Session Monitor envelope judge (leaf).

Task 2.2 (in-session-monitor). Asserts the design's "Leaf — judge" contract
(`classify(diag: DriftDiagnostic, params: MonitorParams) -> EnvelopeVerdict`) and
its three structural rules (design §Leaf — judge):

  * Drift-decision rule — a metric is DRIFTED when its block-bootstrap CI
    EXCLUDES the pinned in-sample baseline by at least margin `M`. Brier/ECE are
    lower-is-better, so "excludes by M on the WORSE side" = `ci_low - baseline >=
    M` (the whole CI lies ABOVE — worse than — baseline by at least M). A model
    performing BETTER than baseline (whole CI BELOW baseline) is IN_ENVELOPE, not
    DRIFTED (it would otherwise route intervene→HALT on a "too-good" model). The
    PRIMARY (binding) metric is `"brier"` (reliability/Brier); `"ece"` is
    corroborating/informational, NOT an independent trigger.
  * Severity band — the bootstrap-distance from baseline (`d = ci_low - baseline`)
    banded by the P2-pinned `severity_cutoffs` {mild, severe}: SEVERE when
    `d >= severity_cutoffs["severe"]`, else MILD. The `[margin_M, mild)` zone
    clamps UP to MILD so a DRIFTED verdict NEVER carries severity NONE (which
    would route intervene→NONE and contradict DRIFTED).
  * Survival-band gate — an actionable (DRIFTED) verdict only when
    `diag.in_survival_band` is False. When inside the band, the deterministic
    reflex already owns it (R5.3 reflex-first / P7) → IN_ENVELOPE.
  * INSUFFICIENT — `diag.sufficient is False` (R2.4) wins over everything: no
    verdict, no intervention (state INSUFFICIENT / severity NONE / binding None).

margin_M vs severity_cutoffs convention (no `monitor.*` param seed exists yet —
checked db/migrations/): face-value per design §Leaf—judge — `margin_M` is the
DRIFTED gate, `severity_cutoffs` bands an ALREADY-drifted metric; the `[M, mild)`
zone clamps up to MILD. Documented, not a silent workaround.

All figures are DERIVED from the diagnostic only — the judge asserts no
probability (R2.3 / R7.2 / P15). No DB, no MCP, no LLM: a pure map over landed
dataclasses. The `MetricObservation` CIs are constructed directly (the judge does
not recompute calibration — that is the diagnostic leaf's job).

Requirements: 2.2 (classify sub-survival drift), 2.3 (derived-only, falsifiers),
2.4 (insufficient -> no verdict), 5.3 (reflex-first survival-band gate via the
diagnostic's derived flag), 7.2 (falsifiable + derived).
"""

from __future__ import annotations

import dataclasses as d

import pytest

from src.reactive.monitor import (
    DriftDiagnostic,
    EnvelopeState,
    EnvelopeVerdict,
    MetricObservation,
    MonitorParams,
    Severity,
)
from src.reactive.monitor.judge import classify
from src.reactive.telemetry import CorrelationKeys

_KEYS = CorrelationKeys(
    run_id="11111111-1111-1111-1111-111111111111",
    code_version="c2",
    param_version="p2",
    walk_forward_window="2026Q1",
)


def _params(
    *,
    margin_M: float = 0.02,
    mild: float = 0.05,
    severe: float = 0.15,
    min_observations: int = 5,
) -> MonitorParams:
    """A P2-shaped `MonitorParams` carrying the drift-rule knobs the judge binds
    on — `margin_M` (the DRIFTED gate) + `severity_cutoffs` {mild, severe} (the
    band). The baseline lives on each `MetricObservation`, not here (it is
    populated by the diagnostic leaf), so `in_sample_baseline` is irrelevant to
    the judge and left empty."""
    return MonitorParams(
        min_observations=min_observations,
        window_W=50,
        margin_M=margin_M,
        severity_cutoffs={"mild": mild, "severe": severe},
        in_sample_baseline={},
        cadence_seconds=300,
    )


def _obs(observed: float, ci_low: float, ci_high: float, baseline: float) -> MetricObservation:
    return MetricObservation(
        observed=observed, ci_low=ci_low, ci_high=ci_high, baseline=baseline
    )


def _diag(
    *,
    metrics: dict[str, MetricObservation] | None = None,
    window_n: int = 8,
    in_survival_band: bool = False,
    sufficient: bool = True,
) -> DriftDiagnostic:
    return DriftDiagnostic(
        metrics=metrics if metrics is not None else {},
        window_n=window_n,
        in_survival_band=in_survival_band,
        sufficient=sufficient,
        keys=_KEYS,
    )


# --- INSUFFICIENT wins over everything (R2.4) ------------------------------


def test_insufficient_diagnostic_yields_insufficient_verdict_no_severity() -> None:
    # sufficient=False -> no verdict, no intervention, regardless of any metric.
    diag = _diag(
        metrics={"brier": _obs(0.5, 0.45, 0.55, baseline=0.21)},  # would be DRIFTED if read
        sufficient=False,
    )
    out = classify(diag, _params())
    assert out.state is EnvelopeState.INSUFFICIENT
    assert out.severity is Severity.NONE
    assert out.binding_metric is None


def test_insufficient_takes_precedence_over_survival_band() -> None:
    # Even inside the survival band, INSUFFICIENT is the verdict (sufficiency first).
    diag = _diag(sufficient=False, in_survival_band=True)
    out = classify(diag, _params())
    assert out.state is EnvelopeState.INSUFFICIENT


# --- survival-band gate: reflex owns it -> IN_ENVELOPE (R5.3 / P7) ----------


def test_in_survival_band_is_in_envelope_even_when_brier_would_drift() -> None:
    # Inside the survival band the deterministic reflex already owns it; the
    # monitor must NOT produce an actionable verdict (5.3 reflex-first).
    drifted_brier = _obs(0.5, 0.45, 0.55, baseline=0.21)  # ci_low - baseline = 0.24 >> margin
    diag = _diag(metrics={"brier": drifted_brier}, in_survival_band=True)
    out = classify(diag, _params())
    assert out.state is EnvelopeState.IN_ENVELOPE
    assert out.severity is Severity.NONE
    assert out.binding_metric is None


# --- drift-decision rule: worse-side CI excludes baseline by >= margin_M -----


def test_brier_ci_excludes_baseline_by_margin_is_drifted_mild() -> None:
    # ci_low - baseline = 0.24 - 0.21 = 0.03; margin_M=0.02 -> DRIFTED.
    # distance 0.03 in [mild=0.05? no -> below mild] -> clamp up to MILD.
    brier = _obs(observed=0.25, ci_low=0.24, ci_high=0.26, baseline=0.21)
    diag = _diag(metrics={"brier": brier})
    out = classify(diag, _params(margin_M=0.02, mild=0.05, severe=0.15))
    assert out.state is EnvelopeState.DRIFTED
    assert out.binding_metric == "brier"
    # distance 0.03 < severe 0.15 -> MILD (and never NONE for a DRIFTED verdict).
    assert out.severity is Severity.MILD


def test_brier_drift_distance_at_or_above_severe_cutoff_is_severe() -> None:
    # ci_low - baseline = 0.40 - 0.21 = 0.19 >= severe 0.15 -> SEVERE (collapse).
    brier = _obs(observed=0.42, ci_low=0.40, ci_high=0.44, baseline=0.21)
    diag = _diag(metrics={"brier": brier})
    out = classify(diag, _params(margin_M=0.02, mild=0.05, severe=0.15))
    assert out.state is EnvelopeState.DRIFTED
    assert out.severity is Severity.SEVERE
    assert out.binding_metric == "brier"


def test_severe_cutoff_is_inclusive_lower_bound() -> None:
    # distance EXACTLY at severe cutoff -> SEVERE (>= is inclusive).
    brier = _obs(observed=0.37, ci_low=0.36, ci_high=0.38, baseline=0.21)  # d = 0.15
    out = classify(_diag(metrics={"brier": brier}), _params(severe=0.15))
    assert out.severity is Severity.SEVERE


def test_drift_gate_is_inclusive_at_margin_M() -> None:
    # distance EXACTLY at margin_M -> DRIFTED (>= is inclusive).
    brier = _obs(observed=0.24, ci_low=0.23, ci_high=0.25, baseline=0.21)  # d = 0.02
    out = classify(_diag(metrics={"brier": brier}), _params(margin_M=0.02, severe=0.15))
    assert out.state is EnvelopeState.DRIFTED
    assert out.severity is Severity.MILD


def test_brier_ci_within_margin_of_baseline_is_in_envelope() -> None:
    # ci_low - baseline = 0.22 - 0.21 = 0.01 < margin_M=0.02 -> NOT drifted.
    brier = _obs(observed=0.23, ci_low=0.22, ci_high=0.24, baseline=0.21)
    out = classify(_diag(metrics={"brier": brier}), _params(margin_M=0.02))
    assert out.state is EnvelopeState.IN_ENVELOPE
    assert out.severity is Severity.NONE
    assert out.binding_metric is None


# --- one-sided: a BETTER-than-baseline model is IN_ENVELOPE, never DRIFTED ----


def test_brier_ci_entirely_below_baseline_is_in_envelope_not_drifted() -> None:
    # The model is performing BETTER (lower Brier) than baseline by a wide margin.
    # Worse-side gate (ci_low - baseline) is negative -> NOT drifted. A two-sided
    # |distance| rule would wrongly route a "too-good" model to HALT/TIGHTEN.
    brier = _obs(observed=0.05, ci_low=0.02, ci_high=0.08, baseline=0.21)
    out = classify(_diag(metrics={"brier": brier}), _params(margin_M=0.02))
    assert out.state is EnvelopeState.IN_ENVELOPE
    assert out.severity is Severity.NONE
    assert out.binding_metric is None


# --- ECE is corroborating only, NOT an independent trigger -------------------


def test_ece_drift_alone_without_brier_drift_is_in_envelope() -> None:
    # ECE worse-side excludes baseline by margin, but BRIER does not -> the
    # primary metric does not bind, so the verdict is IN_ENVELOPE (ECE corroborates
    # the primary; it is not an independent gate).
    brier = _obs(observed=0.22, ci_low=0.21, ci_high=0.23, baseline=0.21)  # d_brier = 0.00 < M
    ece = _obs(observed=0.30, ci_low=0.25, ci_high=0.35, baseline=0.03)  # d_ece huge
    out = classify(
        _diag(metrics={"brier": brier, "ece": ece}), _params(margin_M=0.02)
    )
    assert out.state is EnvelopeState.IN_ENVELOPE
    assert out.binding_metric is None


def test_binding_metric_is_brier_when_brier_drifts_regardless_of_ece() -> None:
    brier = _obs(observed=0.30, ci_low=0.28, ci_high=0.32, baseline=0.21)  # d = 0.07 -> MILD
    ece = _obs(observed=0.02, ci_low=0.01, ci_high=0.03, baseline=0.03)  # ece fine
    out = classify(_diag(metrics={"brier": brier, "ece": ece}), _params(severe=0.15))
    assert out.state is EnvelopeState.DRIFTED
    assert out.binding_metric == "brier"
    assert out.severity is Severity.MILD


# --- NaN-baseline guard (an unpinned primary metric cannot bind) -------------


def test_nan_baseline_brier_cannot_bind_is_in_envelope() -> None:
    # The diagnostic sets baseline=nan when a metric is not pinned in
    # in_sample_baseline. nan comparisons are False, so the metric cannot trigger
    # DRIFTED -> IN_ENVELOPE (intentional: no baseline, no drift judgement).
    brier = _obs(observed=0.9, ci_low=0.85, ci_high=0.95, baseline=float("nan"))
    out = classify(_diag(metrics={"brier": brier}), _params())
    assert out.state is EnvelopeState.IN_ENVELOPE
    assert out.severity is Severity.NONE
    assert out.binding_metric is None


def test_no_brier_metric_present_is_in_envelope() -> None:
    # Sufficient but the primary metric is absent (e.g. only ece populated) ->
    # nothing binds -> IN_ENVELOPE.
    ece = _obs(observed=0.30, ci_low=0.25, ci_high=0.35, baseline=0.03)
    out = classify(_diag(metrics={"ece": ece}), _params())
    assert out.state is EnvelopeState.IN_ENVELOPE
    assert out.binding_metric is None


def test_sufficient_with_no_metrics_is_in_envelope() -> None:
    out = classify(_diag(metrics={}), _params())
    assert out.state is EnvelopeState.IN_ENVELOPE
    assert out.severity is Severity.NONE
    assert out.binding_metric is None


# --- contract / shape guards ------------------------------------------------


def test_returns_frozen_envelope_verdict() -> None:
    out = classify(_diag(metrics={}), _params())
    assert isinstance(out, EnvelopeVerdict)
    with pytest.raises(d.FrozenInstanceError):
        out.severity = Severity.SEVERE  # type: ignore[misc]


def test_classify_is_pure_does_not_mutate_inputs() -> None:
    brier = _obs(observed=0.30, ci_low=0.28, ci_high=0.32, baseline=0.21)
    diag = _diag(metrics={"brier": brier})
    params = _params()
    before_metrics = dict(diag.metrics)
    classify(diag, params)
    # The judge reads, never writes: the diagnostic's metrics dict is untouched.
    assert diag.metrics == before_metrics
    assert diag.metrics["brier"] is brier


def test_drifted_verdict_never_has_severity_none() -> None:
    # The structural invariant: a DRIFTED verdict always carries a real band
    # (MILD or SEVERE) so intervene never receives DRIFTED+NONE (which would
    # route to NONE and contradict the drift).
    for ci_low in (0.23, 0.24, 0.30, 0.40, 0.60):
        brier = _obs(observed=ci_low + 0.01, ci_low=ci_low, ci_high=ci_low + 0.02, baseline=0.21)
        out = classify(_diag(metrics={"brier": brier}), _params(margin_M=0.02, severe=0.15))
        if out.state is EnvelopeState.DRIFTED:
            assert out.severity in (Severity.MILD, Severity.SEVERE)
            assert out.severity is not Severity.NONE
