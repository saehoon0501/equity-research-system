"""mean-reversion-overlay envelope contract — single source of truth.

Mirrors src/agent_harness/envelopes/tactical.py at structural level (the
simpler sibling). This module is the agent_harness dispatch-contract view
of the mean-reversion-overlay emit envelope; it was the one piece of the
reversion contract that did not yet exist as an ``envelopes/<agent>.py``
module (P0-1).

REUSE, do NOT recreate. The reversion contract already exists elsewhere
and this module references it rather than duplicating it:

  - ``src/p10_reversion_overlay/contracts.py::ReversionSignal`` — the
    frozen-dataclass cross-plan handoff (re-exported here as the typed
    view, parity with the other envelope modules);
  - ``src/evaluator_gates/reversion_envelope_shape.py`` (HG-36) — the
    deep semantic shape checker (enum surface, audit_mode field
    contracts, INV-3.6-A/B sub-signal coupling). This module imports its
    enum constants so HG-36 and HG-ENV agree on the vocabulary, and HG-36
    remains the authority for the deep cross-field rules;
  - ``src/evaluator_gates/__init__.py::_validate_reversion_envelope``
    (~line 716) — the gate-set dispatcher that runs HG-36.

HG-ENV (this module) enforces the STRUCTURAL dispatch contract: required
top-level keys, the reversion_signal_bin enum, the REASONING_STEPS enum,
and the cross-field predicate that couples ``unavailable_reason`` to the
``MR_UNAVAILABLE`` bin. The audit_mode field-presence contract and the
INV-3.6-B sub-signal coupling stay in HG-36 (their deep nature is beyond
the JSON-Schema subset _base.py implements).

v0.4.0 scope: standalone mode (no pm-supervisor cell completion). The
``reversion_cell`` field stays null in v0.4.0; HG-36 enforces that.

NOTE (P0-1 scope): the plan also calls for wiring mean-reversion-overlay
into pm-supervisor as a soft-modulator. That wiring is OUT OF SCOPE for
this deliverable (envelope module only) and is deferred.
"""
from __future__ import annotations

from typing import Any

from src.agent_harness.envelopes._base import (
    EnvelopeValidationResult,
    Predicate,
    insight_quality_properties,
    validate_envelope,
)

# REUSE the enum surface from the HG-36 shape gate so HG-36 and HG-ENV
# agree on the vocabulary (single source-of-truth). Do NOT redefine these.
from src.evaluator_gates.reversion_envelope_shape import (
    AUDIT_MODE_VALUES,
    REVERSION_BIN_VALUES,
    UNAVAILABLE_REASON_VALUES,
)

# REUSE the existing frozen-dataclass contract as the typed view (parity
# with tactical.py::TacticalEnvelope referencing p8 TacticalSignal).
from src.p10_reversion_overlay.contracts import (  # noqa: F401  (re-export)
    ReversionBin,
    ReversionSignal,
    UnavailableReason,
)

# Reasoning-path enum — mean-reversion decision path. Each step is a name
# the agent MUST cite in reasoning_path_taken iff it actually performed
# that step. Invented step names → HG-ENV hard fail.
REASONING_STEPS: tuple[str, ...] = (
    "load_ticker_prices",
    "compute_drawdown_from_252d_high",
    "compute_rsi_14",
    "compute_bollinger_band_position",
    "compute_ma_distance_200d",
    "evaluate_sub_signal_fires",
    "classify_reversion_bin",
    "emit_envelope",
)


SCHEMA: dict[str, Any] = {
    "type": "object",
    # Mirrors HG-36 REQUIRED_TOP_LEVEL so an envelope valid under HG-36 is
    # also valid here. (HG-36 owns the deep audit_mode/components/fires
    # rules; this schema owns top-level presence + enum + reasoning path.)
    "required": [
        "ticker",
        "as_of_date",
        "run_id",
        "reversion_signal_bin",
        "audit_mode",
        "reversion_cell",
        "frameworks_cited",
    ],
    "additionalProperties": False,
    "properties": {
        "ticker": {"type": "string"},
        "as_of_date": {"type": "string"},
        "run_id": {"type": "string"},
        "reversion_signal_bin": {
            "type": "string",
            "enum": sorted(REVERSION_BIN_VALUES),
        },
        "audit_mode": {
            "type": "string",
            "enum": sorted(AUDIT_MODE_VALUES),
        },
        "unavailable_reason": {
            # Optional: present iff reversion_signal_bin == 'MR_UNAVAILABLE'
            # (cross-field constraint enforced by predicate, not schema).
            "type": ["string", "null"],
            "enum": sorted(UNAVAILABLE_REASON_VALUES) + [None],
        },
        "reversion_cell": {
            # v0.4.0 NEVER populates this; HG-36 enforces it must be null.
            # Kept nullable here so a v0.4.0 envelope (reversion_cell=null)
            # validates; forward-compat placeholder for v0.4.2 wiring.
            "type": ["object", "null"],
            "additionalProperties": True,
        },
        "components": {
            # Present when bin != MR_UNAVAILABLE; deep key checks live in
            # HG-36. Permissive here for back-compat.
            "type": ["object", "null"],
            "additionalProperties": True,
        },
        "sub_signal_fires": {
            "type": ["object", "null"],
            "additionalProperties": True,
        },
        # snapshot-mode fields (HG-36 owns the presence/format contract).
        "parameters_version_max": {"type": ["string", "null"]},
        "effective_parameters_hash": {"type": ["string", "null"]},
        "frameworks_cited": {
            "type": "array",
            "items": {"type": "string"},
        },
        # Optional in HG-36; included here to mirror the sibling modules.
        "reasoning_path_taken": {
            "type": ["array", "null"],
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
    """If reversion_signal_bin == 'MR_UNAVAILABLE', unavailable_reason
    must be a non-null member of the reason enum. Otherwise
    unavailable_reason must be absent OR null (INV-3.6-A, mirrored from
    HG-36 at the structural layer).
    """
    is_unavail = env.get("reversion_signal_bin") == "MR_UNAVAILABLE"
    reason = env.get("unavailable_reason")
    if is_unavail:
        return reason in UNAVAILABLE_REASON_VALUES
    return reason is None


PREDICATES: dict[str, Predicate] = {
    "unavailable_implies_reason": _unavailable_implies_reason,
}


# ---------- Typed view -------------------------------------------------
#
# The in-process typed view is the existing frozen dataclass
# ``ReversionSignal`` (re-exported above). We do NOT define a parallel
# dataclass — the plan is explicit that the contract already exists and
# must be reused, not recreated.


def validate(data: Any) -> EnvelopeValidationResult:
    """Validate a mean-reversion-overlay envelope dict against the
    structural contract: shape + reasoning enum + cross-field predicate.

    HG-36 (``reversion_envelope_shape.validate_reversion_envelope_shape``)
    remains the authority for the deep audit_mode / components /
    sub_signal_fires / INV-3.6-B rules.
    """
    return validate_envelope(
        data,
        schema=SCHEMA,
        reasoning_steps=REASONING_STEPS,
        predicates=PREDICATES,
    )


__all__ = [
    "AUDIT_MODE_VALUES",
    "PREDICATES",
    "REASONING_STEPS",
    "REVERSION_BIN_VALUES",
    "ReversionBin",
    "ReversionSignal",
    "SCHEMA",
    "UNAVAILABLE_REASON_VALUES",
    "UnavailableReason",
    "validate",
]
