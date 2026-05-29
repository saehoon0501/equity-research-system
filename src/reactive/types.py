"""Reactive Signal Model: decision contracts and fixed vocabularies.

The single source of the Reactive Signal Model's data contracts — the daily-bar
input shape, the fixed decision/failure vocabularies, the per-decision output,
and the cross-spec decision substrate. Per the design's "Types — `types`" and
"Data Models": pure types, no logic — this module satisfies requirements
2 (derived probability + carried calibration evidence), 3 (LONG/SHORT/HOLD vocab
+ caller-supplied direction echo), 4 (non-final flag), 5 (advisory sizing-hint
field), 7 (calibration evidence + decision substrate exposure), and 8 (the
deterministic, typed, isolatable leaf contract).

Pure leaf (P1): stdlib + typing only — no numpy, no MCP, no DB, no overlay
imports. Dependency direction is strict (design §Allowed Dependencies):
`types -> params -> features -> signal_model`; nothing here imports upward.

`Bar` is a `TypedDict` (structurally a `dict`), so a `Sequence[Bar]` passes
straight to `src/micro/indicators.py::atr(Sequence[dict])` / `closes(...)` with
no adapter — its keys are validated once at the `compute_features` boundary
(task 2.1), not here. Frozen dataclasses where the design mandates frozen
(`Weights`, `CalibrationEvidence`); the remaining record types are frozen too so
the determinism contract (R8.1) holds and nothing mutates a returned decision.
`DecisionSubstrate.code_version` / `.param_version` are byte-identical to the
landed telemetry `CorrelationKeys` typed columns (design line 223 revalidation
trigger — `src/reactive/telemetry/schema.py`, mig 048); do not drift the spelling.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

# --- Daily-bar input shape (OHLCV; structurally a dict) -------------------

Bar = TypedDict(
    "Bar",
    {
        "open": float,
        "high": float,
        "low": float,
        "close": float,
        "volume": float,
    },
)


# --- Fixed vocabularies (design §Types; P9 decision vocabulary) -----------

# The single, machine-readable HOLD-reason vocabulary. `insufficient_history`
# and `degenerate_features` are owned by `features`; `invalid_direction` is
# owned by `decide` (design §Feature adapter "Failure ownership").
Reason = Literal[
    "insufficient_history",
    "invalid_direction",
    "degenerate_features",
]

# The caller-supplied directional side — this model never selects it (R3.1/3.2).
Direction = Literal["LONG", "SHORT"]

# The only decision vocabulary the model emits (P9, R3.5).
Decision = Literal["LONG", "SHORT", "HOLD"]


# --- Parameter data contracts (shapes only; DEFAULTS + resolver = task 1.2) ---


@dataclass(frozen=True)
class Weights:
    """Near-equal base feature weights (R1.5).

    Normalized to `w_trend + w_flow + w_meanrev == 1` so the aggregate score
    stays in `[-1, +1]`; normalization itself is enforced by `params` (task
    1.2), not by this shape.
    """

    w_trend: float
    w_flow: float
    w_meanrev: float


@dataclass(frozen=True)
class CalibrationEvidence:
    """Calibration evidence carried in the active snapshot (R7.1).

    `brier` is the Brier score, `reliability` a reliability measure. Both are
    `None` until the `walkforward-tuning-loop` computes them over realized
    outcomes — this model only *exposes* them, it never computes them (R7.4).
    """

    brier: float | None
    reliability: float | None


# --- Feature-adapter failure discriminator --------------------------------


@dataclass(frozen=True)
class FeatureFailure:
    """A computed-feature failure that degrades to HOLD (design §Error Strategy).

    `reason` is drawn from the shared `Reason` vocabulary. `features` only ever
    emits `insufficient_history` / `degenerate_features` (the line-175 runtime
    domain); the type stays the full `Reason` per the design §Types contract.
    """

    reason: Reason


# --- Decision output contracts --------------------------------------------


@dataclass(frozen=True)
class DecisionSubstrate:
    """The per-decision substrate (R7.2/7.3) — the cross-spec telemetry payload.

    `decision-trace-telemetry` persists this into `decision_process_trace`:
    `code_version` + `param_version` promote to the row's typed correlation
    columns (must stay byte-identical to `CorrelationKeys` — design line 223);
    `feature_values` / `probability` / `effective_threshold` / `calibration`
    become the JSONB `trace` payload. `feature_values` carries the reused
    continuous components so a fire is reconstructable.
    """

    feature_values: dict
    probability: float
    effective_threshold: float
    code_version: str
    param_version: str
    calibration: CalibrationEvidence


@dataclass(frozen=True)
class ReactiveDecision:
    """The model's output data contract (one per `decide` call).

    `decision` is the thresholded act-or-hold call; `direction_in` echoes the
    caller-supplied side (never flipped, R4.3); `probability` is the derived
    `P(direction correct)` (R2); `sizing_hint` is the advisory, above-threshold
    sizing scalar (None on HOLD, R5); `non_final` is always True (vetoable
    downstream, R4.1); `reason` is the machine-readable HOLD cause (None when
    actionable); `substrate` is the inspectable per-decision evidence (R7).
    """

    decision: Decision
    direction_in: Direction
    probability: float
    sizing_hint: float | None
    non_final: bool
    reason: Reason | None
    substrate: DecisionSubstrate
