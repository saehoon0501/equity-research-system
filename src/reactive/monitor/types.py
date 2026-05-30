"""In-Session Monitor: domain types for the supervisory sense→judge→act→audit loop.

The single source of the monitor leaf modules' data contracts — the calibration-
drift diagnostic, the envelope verdict + anomaly classification, the bounded
intervention vocabulary, the writer-side command payload, the falsifiable
intervention audit, and the P2-pinned `MonitorParams`. Per the design's
"Components and Interfaces", every "Leaf —" contract block, and "Data Models"
(InterventionAudit, InterventionCommand, MonitorParams): pure types, no logic —
this module is the shared `types` at the head of the strict dependency chain
`types → diagnostic → judge → intervene → {audit, command_writer}` (design
§Allowed Dependencies). Satisfies requirements 2.2 (drift-classification verdict
types), 3.1 (bounded operational authority — the four intents + the three daemon
command seams), and 7.3 (the four correlation keys carried typed on the audit).

Pure leaf (P1): stdlib + the landed `CorrelationKeys` only — no psycopg, no MCP,
no DB, no calibration/metrics import at this layer (the diagnostic leaf imports
those; `types` stays at the head of the chain and imports nothing downward).
All record types are frozen so a returned verdict/diagnostic/audit cannot be
mutated after the fact (the determinism contract the inner-ring tests rely on).

Vocabulary discipline (two DISTINCT enums — do not conflate):
  * `InterventionIntent` is the monitor's decision vocabulary: EXACTLY four members
    (NONE + the three §15 reading-#2 actionable intents). A fifth would mint
    authority the operator did not grant.
  * `CommandType` is the daemon's intake-seam vocabulary: the THREE named seams
    (`engage-kill-switch` / `set-safe-mode-grade` / `select-validated-config`).
The `intervene` leaf maps an intent to a command type at the writer boundary;
they are not interchangeable.

`Severity` is an `IntEnum` shared by `EnvelopeVerdict.severity` and
`ActiveState.severity` so the `intervene` leaf can BOTH order them
(`result.severity <= active.severity` is the conservative-only guard, design
§Leaf — intervene) AND branch on the discrete mild/severe band — a single ordered
grade serves both. Severity is the *banded grade*; the raw bootstrap distance
lives on the per-metric `MetricObservation` (observed + CI), not here.

The audit's four correlation keys are the daemon `execution_daemon_epoch` keys of
the single analyzed `(code_version, param_version)`, read from the analyzed trace
(design §Leaf — audit / Issue 1) — carried as a typed `CorrelationKeys` (the
landed telemetry contract, `src/reactive/telemetry/schema.py`, mig 048), never a
loose dict, so the audit joins the model trace + ledger (R7.3). This is distinct
from the monitor's own orchestration `run_id` used only to name the envelope.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum

from src.reactive.telemetry import CorrelationKeys

# --- Fixed vocabularies (design §Leaf — judge / intervene; data models) ----


class EnvelopeState(str, Enum):
    """Whether the model is behaving inside its calibrated envelope (judge).

    `INSUFFICIENT` is the no-verdict state when the version-scoped window is
    below `min_observations` (R2.4) — it never produces an intervention.
    """

    IN_ENVELOPE = "IN_ENVELOPE"
    DRIFTED = "DRIFTED"
    INSUFFICIENT = "INSUFFICIENT"


class Severity(IntEnum):
    """The banded drift grade — ordered so the conservative-only guard compares.

    Shared by `EnvelopeVerdict.severity` (judge output) and `ActiveState.severity`
    (the live state intervene must not loosen). `IntEnum` gives the ordering for
    `result.severity <= active.severity` (design §Leaf — intervene invariant) and
    the discrete band for the `mild → SELECT/TIGHTEN`, `severe → HALT` mapping.
    The numeric values are the band ORDER only — never an asserted probability
    (P15); the calibrated mild/severe cutoffs are P2-pinned `MonitorParams`.
    """

    NONE = 0
    MILD = 1
    SEVERE = 2


class InterventionIntent(str, Enum):
    """The monitor's decision vocabulary — EXACTLY four members (design).

    `NONE` (in-envelope / insufficient / a guard-rejected non-conservative
    intent) plus the three §15 reading-#2 actionable intents the daemon can
    apply. The cardinality is load-bearing: a fifth member would grant authority
    beyond operational-recovery + select-pre-validated-config.
    """

    NONE = "NONE"
    HALT_NEW_ENTRIES = "HALT_NEW_ENTRIES"
    TIGHTEN_SAFE_MODE = "TIGHTEN_SAFE_MODE"
    SELECT_SAFER_CONFIG = "SELECT_SAFER_CONFIG"


class CommandType(str, Enum):
    """The daemon's THREE intake-seam names (design §Owned — InterventionCommand).

    Distinct vocabulary from `InterventionIntent`: `HALT_NEW_ENTRIES` /
    `TIGHTEN_SAFE_MODE` route to `engage-kill-switch` / `set-safe-mode-grade`,
    and `SELECT_SAFER_CONFIG` routes to `select-validated-config`. `NONE` maps to
    no command. The daemon owns the table and the apply; this is only the seam
    name the writer-side row carries.
    """

    ENGAGE_KILL_SWITCH = "engage-kill-switch"
    SET_SAFE_MODE_GRADE = "set-safe-mode-grade"
    SELECT_VALIDATED_CONFIG = "select-validated-config"


class CommandResultStatus(str, Enum):
    """The outcome of `command_writer.submit_command` (design §Leaf — command_writer).

    Phase 1 always returns `ADVISORY` (advisory no-op recording the would-be
    intent; mig 052 not yet implemented). Phase 2 adds the live outcomes: the
    intake row confirmed `applied` (`APPLIED`); `status=rejected` or non-member /
    survival-loosening selection (`REJECTED`); no-confirm or undeliverable →
    fail-safe escalate-to-halt + surface-to-operator (`ESCALATED`).
    """

    ADVISORY = "ADVISORY"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
    ESCALATED = "ESCALATED"


# --- Diagnostic data contracts (design §Leaf — diagnostic) -----------------


@dataclass(frozen=True)
class MetricObservation:
    """One calibration metric's observed value with its block-bootstrap CI.

    `observed` is the derived figure (e.g. Brier over the version-scoped window),
    `ci_low` / `ci_high` the block-bootstrap CI bounds, `baseline` that version's
    pinned `in_sample_baseline` for the same metric. The drift rule (judge)
    fires when the CI excludes `baseline` by at least `margin_M` — so the raw
    distance lives HERE (observed vs baseline + CI), not on the banded
    `Severity`. Derived-only (P15): no asserted probability rides this record.
    Field names deliberately diverge from `metrics.CI` (point/lower/upper) to
    match the design's `observed/ci_low/ci_high/baseline` contract.
    """

    observed: float
    ci_low: float
    ci_high: float
    baseline: float


@dataclass(frozen=True)
class DriftDiagnostic:
    """The diagnostic leaf's output: per-metric drift figures over a window.

    `metrics` maps a metric name (e.g. `"brier"`, `"reliability"`, `"ece"`) to
    its `MetricObservation`. `window_n` is the count of closed decisions analyzed;
    `sufficient` is False when `window_n < params.min_observations` (R2.4 — incl.
    the expected post-hot-swap blind window). `in_survival_band` is derived from
    the trace's `liq_proximity` / `stop_out` / `gate_link` (NEVER
    `survival_gate_state` — out of boundary): the judge produces an actionable
    verdict only when this is False (design §Leaf — judge survival-band gate).
    `keys` are the single analyzed version's correlation keys — one version per
    diagnostic (Issue 1: calibration is meaningless across a hot-swap); the audit
    pulls its four R7.3 keys from here.
    """

    metrics: dict[str, MetricObservation]
    window_n: int
    in_survival_band: bool
    sufficient: bool
    keys: CorrelationKeys


# --- Judge / verdict (design §Leaf — judge) --------------------------------


@dataclass(frozen=True)
class EnvelopeVerdict:
    """The judge's classification — `{state, severity, binding_metric}` (design).

    `state` is the `EnvelopeState`; `severity` is the banded grade (NONE for
    IN_ENVELOPE / INSUFFICIENT); `binding_metric` names the metric whose CI drove
    the verdict (the primary reliability/Brier, ECE corroborating) — `None` when
    no metric binds (in-envelope / insufficient). All figures derived from the
    diagnostic only; no asserted probability (R2.3 / R7.2 / P15).
    """

    state: EnvelopeState
    severity: Severity
    binding_metric: str | None


# --- Version menu + live state (design §Leaf — intervene) ------------------


@dataclass(frozen=True)
class VersionRef:
    """One validated-version menu entry the `SELECT_SAFER_CONFIG` intent picks from.

    The validated-version identity (the three telemetry version keys; the run_id
    is the live orchestration's, not a version coordinate). The menu is the P2
    `parameters` machinery published by `walkforward-tuning-loop` (design
    Revalidation — RESOLVED 2026-05-30); intervene selects only members of it,
    toward-safer, and never fits (R3.3 / R9.3). The daemon re-validates membership
    + non-loosening at apply-time.
    """

    code_version: str
    param_version: str
    walk_forward_window: str | None


@dataclass(frozen=True)
class ActiveState:
    """The live state intervene must not loosen (conservative-only, R5.1).

    `version` is the active `VersionRef`; `safe_mode_grade` the current safe-mode
    grade (higher = tighter); `kill_switch_engaged` whether the deterministic
    reflex is already engaged (intervene must not relax it, R5.2); `severity` the
    state's current banded grade so `result.severity <= active.severity` is the
    forbidden-loosening check (design §Leaf — intervene invariant). Sourced from
    the trace / daemon state by the orchestrator; intervene consumes it by value.
    """

    version: VersionRef
    safe_mode_grade: int
    kill_switch_engaged: bool
    severity: Severity


# --- Writer-side command + result (design §Owned — InterventionCommand) ----


@dataclass(frozen=True)
class InterventionCommand:
    """The row the monitor INSERTs into the daemon-owned `execution_daemon_command_intake`.

    Writer-side contract ONLY (mig 052 + the poll-validate-apply-mark wiring are
    daemon-owned, out of boundary). `command_id = uuid5(version-epoch-keys +
    intent_type)` — stable identity for idempotent re-issue, deliberately NOT the
    rolling-window edge (which moves every tick), so `ON CONFLICT (command_id) DO
    NOTHING` dedups a re-run of the same logical command. `command_type` is a
    `CommandType` (the three daemon seams). `args` carries the seam payload (e.g.
    the safe-mode grade, or the selected `VersionRef`). `issued_by` is the
    commander identity the daemon validates against its allowlist (Rev 2.1
    write-auth). `run_id` is the monitor's orchestration run; `requested_at` is
    ISO 8601.
    """

    command_id: str
    command_type: CommandType
    args: dict
    run_id: str
    issued_by: str
    requested_at: str


@dataclass(frozen=True)
class CommandResult:
    """The outcome `command_writer.submit_command` returns (design §Leaf).

    `status` is the `CommandResultStatus` (ADVISORY in Phase 1). `command_ref` is
    the confirmed intake `command_id` (None until confirmed / Phase 1).
    `reason` is the human-readable cause (e.g. the daemon's `reject_reason`, or
    the no-confirm escalation note); None on a clean apply.
    """

    status: CommandResultStatus
    command_ref: str | None
    reason: str | None


# --- Audit envelope (design §Owned — InterventionAudit) --------------------


@dataclass(frozen=True)
class InterventionAudit:
    """The falsifiable, key-correlated intervention audit (envelope-on-disk).

    Field set is byte-aligned with the design's "Owned — InterventionAudit" table
    AND the `intervention_audit_shape` HG validator AND `emit_audit`'s serialized
    dict — they must not diverge (the HG gate is presence-only, P13; type-
    correctness is this dataclass + the golden-envelope test, P14).

    `keys` are the four correlation keys of the analyzed version (R7.3), typed.
    `trigger_diagnostic` is the derived triggering figure (metric / observed /
    threshold / window_n — never an asserted probability, R7.2 / P15). `verdict`
    and `intervention_intent` are stored as `str` (the envelope is JSON; the
    enum *values* serialize, so the validator and consumers read strings — do not
    promote them to the rich enums here or `emit_audit` diverges). `rationale` is
    `{hypothesis, falsifiers: list[str]}` (P15). `operator_action_required` is the
    out-of-band action the daemon has no seam for (e.g. `restart_wedged_component`,
    R3.1), else None. `applied` is the unmistakable advisory-vs-live signal: False
    in Phase 1 ("NO ACTION TAKEN") and until confirmed; True only after the intake
    row reports `status=applied`. `command_ref` is the intake `command_id` (the
    *what*) in Phase 2, else None — the audit owns the *why* only (R7.4). The why
    and the daemon's command-event what join via the four keys. `event_ts` is
    ISO 8601.
    """

    keys: CorrelationKeys
    trigger_diagnostic: dict
    verdict: str
    intervention_intent: str
    operator_action_required: str | None
    rationale: dict
    applied: bool
    command_ref: str | None
    event_ts: str


# --- Run-level P2 pin (design §Owned — MonitorParams) ----------------------


@dataclass(frozen=True)
class MonitorParams:
    """The drift-rule knobs, P2-pinned by value at run start (design §Owned).

    Resolved from `parameters_active` (a new `monitor.*` namespace) under
    REPEATABLE READ and consumed by value, never re-resolved mid-tick (P2).
    Values are calibrated empirically, never asserted (P15) — this is the shape
    only; the numbers are pinned, not defaulted here.

    `min_observations` is the window floor for sufficiency (R2.4); `window_W` the
    rolling closed-decision count; `margin_M` the baseline-exclusion margin;
    `severity_cutoffs` the `{mild, severe}` bands; `in_sample_baseline` the
    PER-VERSION reference baseline keyed by metric (v0.1 the monitor computes it
    itself from that version's in-sample ledger rows — a Revalidation Trigger);
    `cadence_seconds` the supervisory tick interval (the cadence requirement; the
    scheduler host is out of boundary). It does NOT write a `run_parameters_snapshot`
    row (Rev 2.1 anti-contamination): the monitor pins `monitor.*` into its own
    context/envelope, never touching the `/research-company` LLM-run lifecycle.
    """

    min_observations: int
    window_W: int
    margin_M: float
    severity_cutoffs: dict
    in_sample_baseline: dict
    cadence_seconds: int
