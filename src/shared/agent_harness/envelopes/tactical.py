"""tactical-overlay envelope contract — single source of truth.

Per harness-v4-final Phase 1 (2026-05-22). Mirrors the schema enforced
by ``src/eval/gates/tactical_envelope_shape.py`` (HG-33) and
extends it with:

  - REASONING_STEPS — the Antonacci dual-momentum decision path the
    agent must cite by name in ``reasoning_path_taken``;
  - PREDICATES — cross-field invariants the JSON Schema can't express,
    namely (a) ``unavailable`` ⇒ ``unavailable_reason`` present, and
    (b) top-level ``tactical_signal_bin`` == ``tactical_cell.tactical_bin``.

The frozen-dataclass shape ``TacticalEnvelope`` is the in-process typed
view (parity with src/overlays/tactical/contracts.py::TacticalSignal).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from src.shared.agent_harness.envelopes._base import (
    EnvelopeValidationResult,
    Predicate,
    insight_quality_properties,
    validate_envelope,
)

# Allowed values — kept parallel to tactical_envelope_shape.py so HG-33
# and HG-ENV agree on the enum surface (single source-of-truth).
TACTICAL_BIN_VALUES: tuple[str, ...] = (
    "positive", "neutral", "negative", "unavailable",
)
TACTICAL_DISPOSITION_VALUES: tuple[str, ...] = (
    "HOLD", "BUY-HIGH", "BUY-MED", "AVOID",
)
CONVICTION_VALUES: tuple[str, ...] = ("HIGH", "MEDIUM", "LOW")
UNAVAILABLE_REASON_VALUES: tuple[str, ...] = (
    "insufficient_price_history", "rf_resolver_staleness",
)

# Reasoning-path enum — Antonacci 12-month dual-momentum decision path.
# Each step is a name the agent MUST cite in reasoning_path_taken iff it
# actually performed that step. Invented step names → HG-ENV hard fail.
REASONING_STEPS: tuple[str, ...] = (
    "load_ticker_prices",
    "load_spy_prices",
    "resolve_risk_free_at_helper",
    "compute_12m_excess_return",
    "compare_to_antonacci_thresholds",
    "classify_tactical_bin",
    "lookup_tactical_cell_disposition",
    "compute_tactical_cell_size_pct",
    "emit_envelope",
)


SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "ticker",
        "as_of_date",
        "run_id",
        "tactical_signal_bin",
        "rf_degenerate",
        "tactical_cell",
        "frameworks_cited",
        "reasoning_path_taken",
    ],
    "additionalProperties": False,
    "properties": {
        "ticker": {"type": "string"},
        "as_of_date": {"type": "string"},
        "run_id": {"type": "string"},
        "tactical_signal_bin": {
            "type": "string",
            "enum": list(TACTICAL_BIN_VALUES),
        },
        "rf_degenerate": {"type": "boolean"},
        "unavailable_reason": {
            # Optional: present iff tactical_signal_bin == 'unavailable'
            # (cross-field constraint enforced by predicate, not schema).
            "type": ["string", "null"],
            "enum": list(UNAVAILABLE_REASON_VALUES) + [None],
        },
        "tactical_cell": {
            "type": "object",
            "required": [
                "conviction",
                "tactical_bin",
                "cell_size_pct",
                "cell_disposition",
            ],
            "additionalProperties": False,
            "properties": {
                "conviction": {
                    "type": "string",
                    "enum": list(CONVICTION_VALUES),
                },
                "tactical_bin": {
                    "type": "string",
                    "enum": list(TACTICAL_BIN_VALUES),
                },
                "cell_size_pct": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 100,
                },
                "cell_disposition": {
                    "type": "string",
                    "enum": list(TACTICAL_DISPOSITION_VALUES),
                },
            },
        },
        "frameworks_cited": {
            "type": "array",
            "items": {"type": "string"},
        },
        "reasoning_path_taken": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
}

# P0-1 (additive, backward-compatible): splice the five OPTIONAL
# insight-quality fields into ``properties``. REQUIRED — the top-level
# schema is ``additionalProperties: False``, so without this the new keys
# would be rejected as unknown. None is added to ``required``.
SCHEMA["properties"].update(insight_quality_properties())


# ---------- Cross-field predicates ------------------------------------


def _unavailable_implies_reason(env: dict[str, Any]) -> bool:
    """If tactical_signal_bin == 'unavailable', unavailable_reason must
    be a non-null member of the reason enum. Otherwise unavailable_reason
    must be absent OR null (free choice).
    """
    is_unavail = env.get("tactical_signal_bin") == "unavailable"
    reason = env.get("unavailable_reason")
    if is_unavail:
        return reason in UNAVAILABLE_REASON_VALUES
    return reason in (None, *(()))


def _top_bin_equals_cell_bin(env: dict[str, Any]) -> bool:
    """Top-level tactical_signal_bin must agree with tactical_cell.tactical_bin.
    Catches state-shuffling between Plan B (classify) and Plan C (overlay).
    """
    cell = env.get("tactical_cell") or {}
    return env.get("tactical_signal_bin") == cell.get("tactical_bin")


PREDICATES: dict[str, Predicate] = {
    "unavailable_implies_reason": _unavailable_implies_reason,
    "top_bin_equals_cell_bin": _top_bin_equals_cell_bin,
}


# ---------- Typed view (frozen dataclass) -----------------------------


@dataclass(frozen=True)
class TacticalCell:
    conviction: str
    tactical_bin: str
    cell_size_pct: float
    cell_disposition: str


@dataclass(frozen=True)
class TacticalEnvelope:
    """In-process typed view of the tactical-overlay emit envelope.

    Parity with src/overlays/tactical/contracts.py::TacticalSignal —
    same Literal vocabulary, extended with the per-run audit fields the
    agent persists to disk.
    """

    ticker: str
    as_of_date: str
    run_id: str
    tactical_signal_bin: str
    rf_degenerate: bool
    tactical_cell: TacticalCell
    frameworks_cited: tuple[str, ...]
    reasoning_path_taken: tuple[str, ...]
    unavailable_reason: str | None = None


def validate(data: Any) -> EnvelopeValidationResult:
    """Validate a tactical-overlay envelope dict against the full
    contract: shape + reasoning enum + cross-field predicates.
    """
    return validate_envelope(
        data,
        schema=SCHEMA,
        reasoning_steps=REASONING_STEPS,
        predicates=PREDICATES,
    )


__all__ = [
    "CONVICTION_VALUES",
    "PREDICATES",
    "REASONING_STEPS",
    "SCHEMA",
    "TACTICAL_BIN_VALUES",
    "TACTICAL_DISPOSITION_VALUES",
    "TacticalCell",
    "TacticalEnvelope",
    "UNAVAILABLE_REASON_VALUES",
    "validate",
]
