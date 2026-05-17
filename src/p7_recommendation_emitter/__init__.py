"""p7_recommendation_emitter — Section 4.6 L5/L6 critical-path output module.

Per v3 spec Section 2.1 (P7 entry execution → recommendation output) +
Section 4.6 Q1 (full execution_recommendation schema) +
Section 5 Q1 (HMAC chain) +
Section 7 Q4 (layered drill-down).

Public surface:

  * ``emit_recommendation(inp, conn=, hmac_key=)`` — top-level emitter.
  * ``EmitInputs`` / ``EmitOutcome`` — typed bundles.
  * ``compute_sizing`` / ``SizingSuggestion`` — Section 4.6 PB#2 v0.1
    mode-static + 3 hard overlays.
  * ``roll_up_conviction`` / ``ConvictionRollup`` — Phase 4 Q2 deterministic
    rollup (HIGH/MEDIUM/LOW).
  * ``apply_hysteresis`` / ``HysteresisResult`` — Phase 4 Q7 2-cycle
    persistence + flip-frequency escalation.
  * ``compute_trigger_metadata`` / ``TriggerMetadata`` — Section 4.6 Q3
    cadence + materiality interrupts.
  * ``build_execution_context`` / ``ExecutionContext`` — Section 4.6 Q1
    execution_context envelope.
"""

from __future__ import annotations

from src.p7_recommendation_emitter.conviction_rollup import (
    CONVICTION_HIGH,
    CONVICTION_LOW,
    CONVICTION_MEDIUM,
    ConvictionInputs,
    ConvictionRollup,
    roll_up_conviction,
)
from src.p7_recommendation_emitter.emitter import (
    AUDIT_HMAC_ENV,
    EmitInputs,
    EmitOutcome,
    P7EmitError,
    emit_recommendation,
)
from src.p7_recommendation_emitter.execution_context import (
    ExecutionContext,
    FairValueEstimate,
    NearTermCatalyst,
    TechnicalSignals,
    aggregate_risk_flags,
    build_execution_context,
)
from src.p7_recommendation_emitter.hysteresis import (
    FLIP_FREQ_THRESHOLD,
    FLIP_WINDOW_DAYS,
    HysteresisInputs,
    HysteresisResult,
    apply_hysteresis,
)
from src.p7_recommendation_emitter.sizing import (
    AppliedOverlay,
    SizingContext,
    SizingSuggestion,
    compute_sizing,
)
from src.p7_recommendation_emitter.trigger_logic import (
    TRIGGER_M2,
    TRIGGER_M3,
    TRIGGER_MODE_CADENCE_FLOOR,
    TRIGGER_NEW_CANDIDATE,
    TriggerInputs,
    TriggerMetadata,
    cadence_floor_due_at,
    compute_trigger_metadata,
)

__all__ = [
    "AUDIT_HMAC_ENV",
    "AppliedOverlay",
    "CONVICTION_HIGH",
    "CONVICTION_LOW",
    "CONVICTION_MEDIUM",
    "ConvictionInputs",
    "ConvictionRollup",
    "EmitInputs",
    "EmitOutcome",
    "ExecutionContext",
    "FLIP_FREQ_THRESHOLD",
    "FLIP_WINDOW_DAYS",
    "FairValueEstimate",
    "HysteresisInputs",
    "HysteresisResult",
    "NearTermCatalyst",
    "P7EmitError",
    "SizingContext",
    "SizingSuggestion",
    "TRIGGER_M2",
    "TRIGGER_M3",
    "TRIGGER_MODE_CADENCE_FLOOR",
    "TRIGGER_NEW_CANDIDATE",
    "TechnicalSignals",
    "TriggerInputs",
    "TriggerMetadata",
    "aggregate_risk_flags",
    "apply_hysteresis",
    "build_execution_context",
    "cadence_floor_due_at",
    "compute_sizing",
    "compute_trigger_metadata",
    "emit_recommendation",
    "roll_up_conviction",
]
