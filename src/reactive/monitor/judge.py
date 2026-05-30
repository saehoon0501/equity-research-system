"""In-Session Monitor: the envelope judge (leaf).

The pure-map behavioral-judgment leaf — `classify(diag, params) -> EnvelopeVerdict`
— that turns the diagnostic leaf's per-metric drift figures into an envelope
verdict + anomaly classification (design §Leaf — judge). It owns the
drift-DECISION (the diagnostic only POPULATES observed/CI/baseline; this leaf
decides whether the CI excludes the baseline, by how much, and whether the model
is inside its calibrated envelope). Satisfies requirements 2.2 (classify
sub-survival drift), 2.3 (derived-only, falsifiers), 2.4 (insufficient -> no
verdict), 5.3 (reflex-first survival-band gate), 7.2 (falsifiable + derived).

THREE structural rules (design §Leaf — judge; all NUMERIC values are P2-pinned
`MonitorParams`, never asserted here — P15):

  1. Drift-decision rule. A metric is DRIFTED when its block-bootstrap CI EXCLUDES
     the pinned in-sample baseline by at least margin `M`. Brier/ECE are
     LOWER-IS-BETTER, so "excludes by M" is ONE-SIDED on the WORSE side:
     `ci_low - baseline >= margin_M` (the whole CI lies ABOVE — worse than — the
     baseline by at least M). A model performing BETTER than baseline (CI entirely
     BELOW baseline) is IN_ENVELOPE, NOT drifted — a two-sided |distance| rule
     would wrongly route a "too-good" model to HALT/TIGHTEN (a conservative-only
     contradiction). The PRIMARY (binding) metric is `"brier"` (reliability/Brier);
     `"ece"` is corroborating/informational, NOT an independent trigger.

  2. Severity band. `severity` is the bootstrap-distance from baseline
     (`d = ci_low - baseline`) banded by the P2-pinned `severity_cutoffs`
     {mild, severe}: SEVERE when `d >= severity_cutoffs["severe"]` (calibration
     collapse), else MILD. The `[margin_M, severe)` zone is MILD — so a DRIFTED
     verdict NEVER carries `Severity.NONE` (which would route intervene→NONE and
     contradict the drift). Both gates are inclusive (`>=`).

  3. Survival-band gate. An actionable (DRIFTED) verdict is produced ONLY when
     `diag.in_survival_band` is False. Inside the band the deterministic reflex
     already owns it (R5.3 reflex-first / P7), so the verdict is IN_ENVELOPE — the
     band is the diagnostic's DERIVED flag (`stop_out` / survival `gate_link`),
     NEVER `survival_gate_state` (out of boundary).

  Precedence: INSUFFICIENT (`diag.sufficient is False`, R2.4) wins over everything
  (no verdict, no intervention). Then the survival-band gate. Then the drift rule.

margin_M vs severity_cutoffs convention: no `monitor.*` parameter seed exists yet
(checked db/migrations/), so the design's structural prose is read at face value —
`margin_M` is the DRIFTED gate; `severity_cutoffs` bands an ALREADY-drifted metric.
A future `monitor.*` seed (a Revalidation Trigger) may pin a different relationship;
this is the documented v0.1 convention, not a silent workaround.

Derived-only (P15): every figure on the returned verdict comes from the diagnostic;
the judge asserts no probability. Pure leaf (P1): stdlib + own-layer `types` only —
no DB, no MCP, no metrics recompute (that is the diagnostic leaf's job). Dependency
direction (design §Allowed Dependencies): `types → diagnostic → judge → ...` — this
module imports only `types`, nothing downward, nothing from execution-daemon /
walkforward-tuning-loop.
"""

from __future__ import annotations

import math

from src.reactive.monitor.types import (
    DriftDiagnostic,
    EnvelopeState,
    EnvelopeVerdict,
    MetricObservation,
    MonitorParams,
    Severity,
)

# The PRIMARY binding metric (design §Leaf — judge: "the primary metric is
# reliability/Brier, with ECE corroborating"). Brier alone decides DRIFTED and
# sets `binding_metric`; ECE is informational, not an independent gate.
_PRIMARY_METRIC = "brier"

# A verdict for the no-actionable-drift case — IN_ENVELOPE with no severity and no
# binding metric. Reused by the survival-band gate and every not-drifted branch so
# the "nothing actionable" shape is identical everywhere.
_IN_ENVELOPE = EnvelopeVerdict(
    state=EnvelopeState.IN_ENVELOPE,
    severity=Severity.NONE,
    binding_metric=None,
)


def _worse_side_distance(obs: MetricObservation) -> float:
    """The bootstrap-distance by which the CI excludes the baseline on the WORSE
    (lower-is-better → higher-value) side.

    `ci_low - baseline`: positive when the whole CI lies ABOVE (worse than) the
    baseline (the drift case); <= 0 when the CI overlaps or lies BELOW (better
    than) the baseline. A NaN baseline (an unpinned metric — the diagnostic sets
    `float('nan')`) yields NaN, which is < every cutoff under the `>=` gates, so
    an unpinned metric cannot bind (intentional — no baseline, no drift judgement).
    """
    return obs.ci_low - obs.baseline


def _band_severity(distance: float, cutoffs: dict) -> Severity:
    """Band an ALREADY-drifted metric's distance into MILD / SEVERE.

    SEVERE when `distance >= cutoffs["severe"]` (calibration collapse), else MILD.
    The `[margin_M, severe)` zone is MILD — a drifted metric is never `NONE`. The
    cutoff is inclusive on the lower bound (`>=`)."""
    if distance >= float(cutoffs["severe"]):
        return Severity.SEVERE
    return Severity.MILD


def classify(diag: DriftDiagnostic, params: MonitorParams) -> EnvelopeVerdict:
    """Map a `DriftDiagnostic` + P2-pinned `MonitorParams` to an `EnvelopeVerdict`.

    Pure: reads `diag` and `params`, mutates neither, returns a frozen verdict.
    Precedence (design §Leaf — judge): INSUFFICIENT first (R2.4), then the
    survival-band gate (R5.3), then the worse-side drift rule on the primary
    `"brier"` metric. ECE is not consulted as a trigger (corroborating only).

    Args:
        diag: the diagnostic leaf's output (per-metric observed/CI/baseline,
            `window_n`, `in_survival_band`, `sufficient`, version keys).
        params: the pinned drift-rule knobs — `margin_M` (the DRIFTED gate) and
            `severity_cutoffs` {mild, severe} (the band). Consumed by value (P2);
            `window_W` / `min_observations` are already encoded in
            `diag.sufficient` (the diagnostic windowed + floored), so the judge
            does not re-window.

    Returns:
        An `EnvelopeVerdict` — `state` ∈ {IN_ENVELOPE, DRIFTED, INSUFFICIENT};
        `severity` the banded grade (NONE unless DRIFTED); `binding_metric` the
        metric that drove a DRIFTED verdict (`"brier"`), else None. All figures
        derived from `diag` only — no asserted probability (R2.3 / R7.2 / P15).
    """
    # Precedence 1 — INSUFFICIENT (R2.4): below the floor / no realized labels.
    # No verdict, no intervention, regardless of any populated metric.
    if not diag.sufficient:
        return EnvelopeVerdict(
            state=EnvelopeState.INSUFFICIENT,
            severity=Severity.NONE,
            binding_metric=None,
        )

    # Precedence 2 — survival-band gate (R5.3 / P7): inside hard-survival limits
    # the deterministic reflex already owns it; the monitor produces no actionable
    # verdict. The band is the diagnostic's DERIVED flag, never survival_gate_state.
    if diag.in_survival_band:
        return _IN_ENVELOPE

    # Precedence 3 — the drift-decision rule on the PRIMARY metric only.
    primary = diag.metrics.get(_PRIMARY_METRIC)
    if primary is None:
        # No primary metric populated -> nothing binds -> in-envelope.
        return _IN_ENVELOPE

    distance = _worse_side_distance(primary)
    # NaN-safe: `math.isnan` guards the unpinned-baseline case explicitly (a NaN
    # would already fail the `>=` gate, but the guard makes the intent unmistakable
    # and short-circuits before banding).
    if math.isnan(distance) or distance < float(params.margin_M):
        # Within margin, better-than-baseline, or unpinned -> NOT drifted.
        return _IN_ENVELOPE

    # DRIFTED on the worse side by >= margin_M: band the distance. A DRIFTED
    # verdict always carries MILD or SEVERE (never NONE).
    severity = _band_severity(distance, params.severity_cutoffs)
    return EnvelopeVerdict(
        state=EnvelopeState.DRIFTED,
        severity=severity,
        binding_metric=_PRIMARY_METRIC,
    )


__all__ = ["classify"]
