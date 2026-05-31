"""Walkforward-tuning-loop owned in-memory contract types — the dependency-root
BARRIER (task 1.1).

This module pins every walkforward-OWNED cross-leaf shape before the parallel
leaf fan-out, so the leaves (`read`, `fit`, `cpcv`, `metric`, `gate`,
`publish`, `audit`) cannot diverge on shape (design §"File Structure Plan":
`types` is the dependency root; §Overview: `types.py` is the load-bearing
barrier). The single most load-bearing pin is the ``OOSSample`` ↔ ``OOSMatrix``
seam: ``metric`` PRODUCES ``OOSSample``s and ``gate`` CONSUMES them via
``OOSMatrix`` — these shapes must not diverge.

Consumed contract (IMPORTED, never re-declared — design §Allowed Dependencies,
R10.3): ``Candidate``, ``OutcomeRecord``, ``ReplayResult``, ``ReplayWindow``
from ``src.reactive.replay`` (the ``reactive-replay-harness`` spec), and
``Label`` from ``src.calibration.scorer`` (the canonical 4-bin vocabulary, P9).
Re-exported here so this barrier is the single import point for the leaves and
so object-identity (`wf.Candidate is replay.Candidate`) provably holds — there
is no parallel re-declaration of those shapes.

Pure leaf (P1): stdlib + typing only — no httpx, no MCP, no DB, no consumer-spec
imports, no other-leaf imports. Frozen dataclasses throughout so the
determinism contract holds (R9.1: identical inputs → identical gate verdict;
the gate's invariant is "identical inputs ⇒ identical verdict").

Requirements: 4.5 (the gate NEVER uses in-sample Sharpe — so ``GateVerdict``
carries no IS-Sharpe field), 8.1 (the tuner-action audit row), 10.3 (consume
the reactive ``ParamSnapshot`` / ``SurvivalParameters`` — carried inside the
consumed ``Candidate`` — as the versioned objects this loop tunes, never
re-implementing them).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# --- Consumed contract: IMPORT, never re-declare (R10.3, P9) --------------
# Re-exported below so the barrier is the single import point for the leaves
# and object identity (wf.Candidate is replay.Candidate) holds.
from src.calibration.scorer import Label
from src.reactive.replay import (
    Candidate,
    OutcomeRecord,
    ReplayResult,
    ReplayWindow,
)


# --- ReadSet: firewalled trace slice + drained events ---------------------


@dataclass(frozen=True)
class Event:
    """One drained ``execution_daemon_event_queue`` anomaly event (R10.5).

    Surfaced to the fit's behavioral analysis (e.g. a queued safe_mode /
    kill_switch / lifecycle event). The walkforward loop DRAINS this queue and
    sets ``drained_at`` — it does NOT own the emit side (design §Out of
    Boundary; the queue DDL is `execution-daemon`'s, mig 051).

    Fields:
      - ``event_id``: the queue row's identifier.
      - ``event_type``: e.g. "safe_mode" / "kill_switch" / "lifecycle".
      - ``event_ts``: ISO timestamp the event was queued (firewall-relevant:
        events after the IS boundary must not leak into the fit).
      - ``payload``: the event's structured detail (JSONB-backed).
    """

    event_id: str
    event_type: str
    event_ts: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class ReadSet:
    """The firewall-bounded read for the fit's behavioral analysis (R2.1).

    Produced by the ``read`` leaf's ``read_firewalled`` + ``drain_events``.
    Carries the model-trace slice read only up to the in-sample boundary (no
    OOS leak) and the drained anomaly events. Does NOT carry any
    ``counterfactual_ledger`` P&L (design §Allowed Dependencies — reactive P&L
    comes from the harness's ``OutcomeRecord``s, never the ledger).

    Fields:
      - ``is_boundary``: the in-sample boundary ISO timestamp the read was
        bounded by.
      - ``trace_rows``: the firewall-bounded ``decision_process_trace`` slice
        (raw rows for behavioral analysis).
      - ``drained_events``: the anomaly events drained from the event queue.
    """

    is_boundary: str
    trace_rows: list[dict[str, Any]]
    drained_events: list[Event]


# --- TrialSet: >=2 Candidates + trial metadata (for effective_N) ----------


@dataclass(frozen=True)
class TrialSet:
    """The assembled trial set — >=2 hashed candidate configs (R3.1/3.4).

    Produced by the ``fit`` leaf's ``assemble_trial_set``. The trial set must be
    non-trivial (>=2 configs) so the gate's DSR/PBO deflation is non-degenerate
    (R5.2/5.3) — that minimum is enforced by ``fit`` at assembly, not by this
    type. ``trial_metadata`` carries what the gate deflates ``effective_n``
    against (e.g. the search breadth, correlated-sweep structure).

    Fields:
      - ``candidates``: the consumed-``Candidate`` configs in the trial set.
      - ``trial_metadata``: search/optimizer metadata for effective_N
        estimation (P15 — derived, conservative, calibration-time concern).
    """

    candidates: list[Candidate]
    trial_metadata: dict[str, Any]


# --- Partition: a CPCV split carrying its OOS span as a ReplayWindow -------


@dataclass(frozen=True)
class Partition:
    """One combinatorial-purged-CV partition (R2.2/2.3, 4.1).

    Produced by the ``cpcv`` leaf's ``make_partitions``. Realizes the leakage
    firewall: purge of label-overlapping observations + embargo after each test
    block. The OOS span maps to the consumed harness ``ReplayWindow`` —
    the two specs share ONE window type (design seam note, line 205): this
    loop's ``Partition`` CARRIES the ``ReplayWindow`` it hands to
    ``replay_candidate`` per config.

    Fields:
      - ``partition_id``: stable identifier (CPCV combination index).
      - ``is_indices``: the in-sample observation indices (post-purge/embargo).
      - ``oos_indices``: the out-of-sample observation indices for this split.
      - ``oos_window``: the ``ReplayWindow`` the OOS span maps to (the shared
        harness window type handed to ``replay_candidate``).
    """

    partition_id: int
    is_indices: list[int]
    oos_indices: list[int]
    oos_window: ReplayWindow


# --- OOSSample: the BARRIER PIN — metric PRODUCES, gate CONSUMES -----------


@dataclass(frozen=True)
class OOSSample:
    """One config × one partition out-of-sample sample — the metric↔gate seam.

    THE load-bearing pin: ``metric.score(outcome_records) -> OOSSample``
    PRODUCES this; ``gate.evaluate_gate`` CONSUMES it via ``OOSMatrix``. Exactly
    four fields, no more — calibration (Brier/reliability) is folded INTO the
    survival-net scalar by ``metric`` (design §Evaluation Leaves), it is NOT a
    separate matrix field; adding a 5th field would diverge the seam.

    The four fields are the per-(config, partition) survival-net return summary
    plus the return-distribution shape stats the gate's PSR/MinTRL needs:
      - ``survival_net_return``: the survival-net risk-adjusted return for this
        config over this partition (reflects the §13 ordering — survival
        breaches / stop-outs dominate the ranking; R4.3). The gate selects the
        highest of these across the trial set.
      - ``skew``: the OOS return-distribution skewness (PSR/MinTRL is
        skew-aware; PSR rises with negative skew, R5.1).
      - ``kurtosis``: the OOS return-distribution (excess) kurtosis (PSR/MinTRL
        is kurtosis-aware).
      - ``n_obs``: the number of OOS observations in this partition (feeds
        MinTRL sufficiency — R5.4: too few ⇒ no-promote).
    """

    survival_net_return: float
    skew: float
    kurtosis: float
    n_obs: int


# --- OOSMatrix: the metric→gate container (per-config × per-partition) -----


@dataclass(frozen=True)
class OOSMatrix:
    """The CPCV OOS matrix the gate evaluates over (design §gate Contracts).

    Per-config per-partition survival-net samples for the trial set + the
    incumbent's series + trial metadata. Partition order MUST be consistent
    across configs and the incumbent (the gate pairs partitions positionally
    for PBO/CSCV and the OOS-margin comparison).

    Fields:
      - ``per_config``: ``{config_id: [OOSSample, ...]}`` — one partition-ordered
        series per trial-set config.
      - ``incumbent``: the incumbent champion's partition-ordered series (the
        OOS-margin baseline; R5.5 the selected candidate must beat it).
      - ``trial_metadata``: the trial set's metadata the gate deflates
        ``effective_n`` against (MinBTL caps breadth; correlated sweeps reduce
        to an effective count, R5.3).
    """

    per_config: dict[str, list[OOSSample]]
    incumbent: list[OOSSample]
    trial_metadata: dict[str, Any]


# --- GateParams: DSR / PSR / MinTRL / PBO / MinBTL / decision-rule knobs ----


@dataclass(frozen=True)
class GateParams:
    """The deterministic gate's pinned threshold + decision-rule knobs (R5.1-5.5).

    Consumed by ``gate.evaluate_gate``. Provisional numeric values are set by
    the orchestrator (P2 PARAMETERS_USED) and calibrated empirically (design
    §Open Questions — decision-rule knobs). This type pins the KNOB NAMES so the
    gate and the orchestrator agree.

    Knob families:
      - ``dsr_threshold``: Deflated Sharpe Ratio promote threshold (R5.1).
      - ``psr_threshold``: Probabilistic Sharpe Ratio significance threshold
        vs the benchmark (R5.1).
      - ``min_trl``: Minimum Track Record Length (observations) for sufficiency
        (R5.4: not met ⇒ no-promote).
      - ``pbo_threshold``: max acceptable Probability of Backtest Overfitting
        (R5.1, over the trial set).
      - ``min_btl``: Minimum Backtest Length — caps the trial-set breadth to the
        available history (R5.3).
      - ``benchmark_sharpe``: the non-trivial benchmark Sharpe PSR/MinTRL tests
        against (R5.1 — "vs a non-trivial benchmark Sharpe").
      - ``oos_margin``: the configured OOS margin the selected candidate must
        beat the incumbent by (R5.5).
      - ``consecutive_required``: consecutive-cycle count the margin must be
        sustained over (R5.5 anti-churn).
      - ``hysteresis``: anti-churn hysteresis (R5.5).
    """

    dsr_threshold: float
    psr_threshold: float
    min_trl: int
    pbo_threshold: float
    min_btl: int
    benchmark_sharpe: float
    oos_margin: float
    consecutive_required: int
    hysteresis: float


# --- GateVerdict: the 9 design-pinned fields; NEVER an IS-Sharpe field -----


@dataclass(frozen=True)
class GateVerdict:
    """The deterministic promotion verdict (design §gate Contracts, line 231-232).

    Exactly the nine pinned fields. ``promote=true`` only if EVERY sub-check
    passes for ``selected_config``; ``reasons`` cites the binding sub-check.
    Carries NO in-sample-Sharpe field by design (R4.5 / R5.5 — IS-Sharpe is
    never a promotion criterion, so it has no place on the verdict a downstream
    consumer reads). Gate figures are DERIVED metrics (P15), not asserted
    probabilities.

    Fields:
      - ``promote``: the promote/decline verdict.
      - ``selected_config``: the selected config id (None on decline / no
        viable candidate; P7 fail-safe).
      - ``reasons``: the cited binding sub-checks (audit rationale).
      - ``dsr``: the Deflated Sharpe Ratio of the selected config (deflated by
        ``effective_n``).
      - ``psr``: the Probabilistic Sharpe Ratio vs the benchmark.
      - ``min_trl_met``: whether MinTRL sufficiency held (R5.4).
      - ``pbo``: the Probability of Backtest Overfitting over the trial set.
      - ``effective_n``: the effective number of independent trials the gate
        deflated against (R5.2 — logged).
      - ``lexicographic_ok``: whether the §13 guard held (no Edge/Return gain at
        the cost of a worse Survive/Preserve, R6.3).
    """

    promote: bool
    selected_config: str | None
    reasons: list[str]
    dsr: float
    psr: float
    min_trl_met: bool
    pbo: float
    effective_n: int
    lexicographic_ok: bool


# --- TunerActionAudit: mirrors mig-053 columns minus DB-default created_at --


@dataclass(frozen=True)
class TunerActionAudit:
    """The tuner-action audit row — emitted on BOTH promote and decline (R8.1).

    Mirrors the ``walkforward_tuner_audit`` (mig 053) columns minus the
    DB-default ``created_at`` (design §Data Models). The four correlation keys
    (``run_id``, ``code_version``, ``param_version``, ``walk_forward_window``)
    make every row joinable to ``decision_process_trace`` and the ledger (R8.3).
    All columns are immutable after insert (append-only guard at the DB).

    Fields:
      - ``audit_id``: client-minted UUID PK.
      - ``run_id``: correlation key (P3, threads the cycle).
      - ``code_version``: correlation key.
      - ``param_version``: the candidate's version.
      - ``walk_forward_window``: the IS-boundary label advanced — None until
        promoted (design §Data Models "null until promoted").
      - ``promoted``: the verdict.
      - ``track``: "param" | "code" | "both".
      - ``gate_metrics``: DERIVED gate figures (dsr, psr, min_trl_met, pbo,
        effective_n, lexicographic_ok) — P15: derived, not asserted (R8.2).
      - ``hypothesis``: the FALSIFIABLE promotion statement + observable
        falsifiers (P15, R8.2).
    """

    audit_id: str
    run_id: str
    code_version: str
    param_version: str
    walk_forward_window: str | None
    promoted: bool
    track: str
    gate_metrics: dict[str, Any]
    hypothesis: dict[str, Any]


__all__ = [
    # Consumed contract — re-exported (IMPORTED, never re-declared).
    "Candidate",
    "OutcomeRecord",
    "ReplayResult",
    "ReplayWindow",
    "Label",
    # Walkforward-owned shapes (the barrier).
    "Event",
    "ReadSet",
    "TrialSet",
    "Partition",
    "OOSSample",
    "OOSMatrix",
    "GateParams",
    "GateVerdict",
    "TunerActionAudit",
]
