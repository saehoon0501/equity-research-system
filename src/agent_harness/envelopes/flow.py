"""flow-overlay envelope contract — single source of truth.

Mirrors src/agent_harness/envelopes/tactical.py. Schema enforced by
``src/evaluator_gates/flow_envelope_shape.py`` (HG-FLOW) and extended with:

  - REASONING_STEPS — the CTA-proximity composite decision path the agent
    must cite in ``reasoning_path_taken``;
  - PREDICATES — cross-field invariants (a) ``unavailable`` ⇒
    ``unavailable_reason`` present; (b) top-level ``flow_signal_bin`` ==
    ``flow_cell.flow_bin``.

The frozen-dataclass shape ``FlowEnvelope`` is the in-process typed view
(parity with src/p9_flow_overlay/contracts.py::FlowSignal).

v0.1 scope: CTA-proximity sub-signal only. v0.2 will extend SCHEMA with
``components.gamma_regime`` block and REASONING_STEPS with gamma-related
steps. v0.3 adds ``components.crowding``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.agent_harness.envelopes._base import (
    EnvelopeValidationResult,
    Predicate,
    validate_envelope,
)

# Allowed values — kept parallel to flow_envelope_shape.py so HG-FLOW
# and HG-ENV agree on the enum surface (single source-of-truth).
FLOW_BIN_VALUES: tuple[str, ...] = (
    "positive", "neutral", "negative", "unavailable",
)
FLOW_DISPOSITION_VALUES: tuple[str, ...] = (
    "HOLD", "BUY-HIGH", "BUY-MED", "AVOID",
)
CONVICTION_VALUES: tuple[str, ...] = ("HIGH", "MEDIUM", "LOW")
UNAVAILABLE_REASON_VALUES: tuple[str, ...] = (
    "insufficient_price_history",
    "spy_price_history_unavailable",
)

# Reasoning-path enum — CTA-proximity composite decision path.
# Each step is a name the agent MUST cite in reasoning_path_taken iff it
# actually performed that step. Invented step names → HG-FLOW hard fail.
REASONING_STEPS: tuple[str, ...] = (
    "load_ticker_prices",
    "load_spy_prices",
    "compute_ticker_tsmom_12mo",
    "compute_ticker_ma_distance",
    "compute_ticker_donchian_state",
    "compute_market_tsmom_12mo",
    "compute_market_ma_distance",
    "compute_market_donchian_state",
    "aggregate_composite_score",
    "classify_flow_bin",
    "lookup_flow_cell_disposition",
    "compute_flow_cell_size_pct",
    "emit_envelope",
)


SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "ticker",
        "as_of_date",
        "run_id",
        "flow_signal_bin",
        "flow_cell",
        "frameworks_cited",
        "reasoning_path_taken",
    ],
    "additionalProperties": False,
    "properties": {
        "ticker": {"type": "string"},
        "as_of_date": {"type": "string"},
        "run_id": {"type": "string"},
        "flow_signal_bin": {
            "type": "string",
            "enum": list(FLOW_BIN_VALUES),
        },
        "unavailable_reason": {
            # Optional: present iff flow_signal_bin == 'unavailable'
            # (cross-field constraint enforced by predicate, not schema).
            "type": ["string", "null"],
            "enum": list(UNAVAILABLE_REASON_VALUES) + [None],
        },
        "components": {
            # Optional — present when bin != 'unavailable'. v0.1 carries
            # ticker_score / market_score / composite_score_normalized; v0.2
            # extends with gamma_regime sub-block; v0.3 extends with crowding.
            "type": ["object", "null"],
            "additionalProperties": True,
        },
        "flow_cell": {
            "type": "object",
            "required": [
                "conviction",
                "flow_bin",
                "cell_size_pct",
                "cell_disposition",
            ],
            "additionalProperties": False,
            "properties": {
                "conviction": {
                    "type": "string",
                    "enum": list(CONVICTION_VALUES),
                },
                "flow_bin": {
                    "type": "string",
                    "enum": list(FLOW_BIN_VALUES),
                },
                "cell_size_pct": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 100,
                },
                "cell_disposition": {
                    "type": "string",
                    "enum": list(FLOW_DISPOSITION_VALUES),
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


# ---------- Cross-field predicates ------------------------------------


def _unavailable_implies_reason(env: dict[str, Any]) -> bool:
    """If flow_signal_bin == 'unavailable', unavailable_reason must be a
    non-null member of the reason enum. Otherwise unavailable_reason must
    be absent OR null (free choice).
    """
    is_unavail = env.get("flow_signal_bin") == "unavailable"
    reason = env.get("unavailable_reason")
    if is_unavail:
        return reason in UNAVAILABLE_REASON_VALUES
    return reason is None


def _top_bin_equals_cell_bin(env: dict[str, Any]) -> bool:
    """Top-level flow_signal_bin must agree with flow_cell.flow_bin.
    Catches state-shuffling between classify_flow and overlay.
    """
    cell = env.get("flow_cell") or {}
    return env.get("flow_signal_bin") == cell.get("flow_bin")


PREDICATES: dict[str, Predicate] = {
    "unavailable_implies_reason": _unavailable_implies_reason,
    "top_bin_equals_cell_bin": _top_bin_equals_cell_bin,
}


# ---------- Typed view (frozen dataclass) -----------------------------


@dataclass(frozen=True)
class FlowCell:
    conviction: str
    flow_bin: str
    cell_size_pct: float
    cell_disposition: str


@dataclass(frozen=True)
class FlowEnvelope:
    """In-process typed view of the flow-overlay emit envelope.

    Parity with src/p9_flow_overlay/contracts.py::FlowSignal — same
    Literal vocabulary, extended with the per-run audit fields the
    agent persists to disk.
    """

    ticker: str
    as_of_date: str
    run_id: str
    flow_signal_bin: str
    flow_cell: FlowCell
    frameworks_cited: tuple[str, ...]
    reasoning_path_taken: tuple[str, ...]
    unavailable_reason: str | None = None
    components: dict[str, Any] | None = None


def validate(data: Any) -> EnvelopeValidationResult:
    """Validate a flow-overlay envelope dict against the full
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
    "FLOW_BIN_VALUES",
    "FLOW_DISPOSITION_VALUES",
    "FlowCell",
    "FlowEnvelope",
    "PREDICATES",
    "REASONING_STEPS",
    "SCHEMA",
    "UNAVAILABLE_REASON_VALUES",
    "validate",
]
