"""In-session-monitor intervention-audit envelope shape validator (HG-39).

The in-session-monitor (`.kiro/specs/in-session-monitor/`) emits its own
intervention-audit envelope on every cadence tick — the falsifiable *why* of an
intervention (or a declined-to-intervene), correlated to the model trace via the
four shared keys (R7.4). This module is its presence-only HG validator, mirroring
``src/eval/gates/envelope_shape.py`` (the HG-23 pm-supervisor validator).

Presence-only by design (P13 / matches HG-23): the gate checks KEY PRESENCE, not
value type-correctness. ``"string | null"`` annotations in the design doc are
narrative convention; nullable keys (``operator_action_required``, ``command_ref``)
need only the KEY present (``None`` is an accepted value). Type-correctness of the
audit is enforced by the audit dataclass + a richer per-agent contract test
(P14 inner-ring), NOT by this gate.

Required keys (design §Gate — intervention_audit_shape, §Data Models —
InterventionAudit):

  * the 4 correlation keys: ``run_id``, ``code_version``, ``param_version``,
    ``walk_forward_window`` (CorrelationKeys — the daemon-epoch keys of the single
    analyzed ``(code_version, param_version)``);
  * ``trigger_diagnostic`` — the derived triggering figure (P15, no asserted prob);
  * ``verdict`` — IN_ENVELOPE | DRIFTED | INSUFFICIENT;
  * ``intervention_intent`` — NONE | HALT_NEW_ENTRIES | TIGHTEN_SAFE_MODE |
    SELECT_SAFER_CONFIG;
  * ``rationale`` — a dict carrying a ``falsifiers`` sub-key (P15);
  * ``event_ts`` — ISO-8601 timestamp.

DETERMINISM: pure Python; no I/O beyond CLI stdin/stdout. No HTTP.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field

# The four correlation keys (CorrelationKeys) every audit must carry so it joins
# to the model trace + outcome ledger (R7.3). Named separately so the result can
# report the missing-correlation-key case distinctly if a consumer needs it.
CORRELATION_KEYS: tuple[str, ...] = (
    "run_id",
    "code_version",
    "param_version",
    "walk_forward_window",
)

# Top-level keys per the InterventionAudit data model (design §Data Models).
# Presence-only (P13): each must be present and non-empty EXCEPT the nullable
# keys below, for which only KEY presence is required.
REQUIRED_TOP_LEVEL: tuple[str, ...] = CORRELATION_KEYS + (
    "trigger_diagnostic",
    "verdict",
    "intervention_intent",
    "rationale",
    "event_ts",
)

# Keys where ``null`` / ``None`` is a legitimate value (design §Data Models:
# ``operator_action_required: str | null``, ``command_ref: str | null``). For
# these the validator requires the KEY present, but accepts ``None``. They are
# NOT in REQUIRED_TOP_LEVEL — they are optional-but-nullable; included here so a
# present-with-null value is never flagged when a consumer does require them.
NULLABLE_TOP_LEVEL: frozenset[str] = frozenset(
    {
        "operator_action_required",
        "command_ref",
    }
)

# Required sub-keys per top-level block. The rationale block must carry observable
# ``falsifiers`` (P15) — a hypothesis alone is not a falsifiable rationale.
REQUIRED_SUBKEYS: dict[str, tuple[str, ...]] = {
    "rationale": ("falsifiers",),
}


@dataclass
class InterventionAuditShapeResult:
    """Result envelope for intervention-audit shape validation.

    Named field-lists let ``_fingerprints.fingerprint_intervention_audit``
    produce a deterministic stuck-loop signature for the agent_harness retry
    loop (mirrors the other gate result dataclasses).
    """

    valid: bool
    missing_top_level: list[str] = field(default_factory=list)
    missing_subkeys: dict[str, list[str]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _is_present_non_empty(value: object) -> bool:
    """Presence check identical to ``envelope_shape._is_present_non_empty``.

    A value counts as present iff it is not None, not a missing key, and not an
    empty container/string.
    """
    if value is None:
        return False
    if isinstance(value, (str, list, dict, tuple)) and len(value) == 0:
        return False
    return True


def validate_intervention_audit_shape(
    audit: dict, run_id: str | None = None
) -> InterventionAuditShapeResult:
    """Validate an intervention-audit envelope against the InterventionAudit shape.

    Presence-only (P13): checks KEY PRESENCE + non-emptiness of required keys and
    the rationale ``falsifiers`` sub-key; does NOT type-check values.

    Args:
        audit: parsed audit envelope dict.
        run_id: optional caller-context passthrough (the monitor's own
            orchestration run_id used to name the envelope file). It does NOT
            participate in the shape verdict — the four correlation keys carried
            INSIDE the envelope are what the gate validates. Present in the
            signature per the design contract
            (``validate_intervention_audit_shape(audit, run_id=None)``).

    Returns:
        InterventionAuditShapeResult with ``valid=True`` iff every required
        top-level key is present-and-non-empty AND the rationale block carries
        its required sub-keys.
    """
    if not isinstance(audit, dict):
        return InterventionAuditShapeResult(
            valid=False,
            missing_top_level=list(REQUIRED_TOP_LEVEL),
            notes=[
                f"audit must be a JSON object (dict); got {type(audit).__name__}"
            ],
        )

    result = InterventionAuditShapeResult(valid=True)

    # Top-level presence. Nullable keys (not in REQUIRED_TOP_LEVEL) need only the
    # KEY present; required keys need a present-and-non-empty value.
    for key in REQUIRED_TOP_LEVEL:
        if key in NULLABLE_TOP_LEVEL:
            if key not in audit:
                result.missing_top_level.append(key)
        else:
            if not _is_present_non_empty(audit.get(key)):
                result.missing_top_level.append(key)

    # Sub-key presence for the validated blocks (rationale.falsifiers, P15).
    for top_key, subkeys in REQUIRED_SUBKEYS.items():
        block = audit.get(top_key)
        if not isinstance(block, dict):
            # The block itself is missing/non-dict — already reported at the
            # top level; don't double-report its sub-keys.
            continue
        missing_here = [
            sk for sk in subkeys if not _is_present_non_empty(block.get(sk))
        ]
        if missing_here:
            result.missing_subkeys[top_key] = missing_here

    if result.missing_top_level or result.missing_subkeys:
        result.valid = False

    return result


def _result_to_dict(r: InterventionAuditShapeResult) -> dict:
    return {
        "valid": r.valid,
        "missing_top_level": r.missing_top_level,
        "missing_subkeys": r.missing_subkeys,
        "notes": r.notes,
    }


def _cli(argv: list[str] | None = None) -> int:
    """CLI wrapper. Reads the audit JSON from ``--audit <path>`` or stdin
    (``--audit -``) and prints the validation result as JSON.

    Exit codes:
      0  audit valid
      1  audit invalid (one or more checks failed)
      2  audit unparseable or arguments invalid
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="intervention_audit_shape",
        description=(
            "Validate an in-session-monitor intervention-audit envelope against "
            "the InterventionAudit shape (presence-only, HG-39). "
            "Exit 0 valid, 1 invalid, 2 unparseable."
        ),
    )
    parser.add_argument(
        "--audit",
        required=True,
        help='path to audit JSON file, or "-" to read from stdin',
    )
    args = parser.parse_args(argv)

    try:
        if args.audit == "-":
            raw = sys.stdin.read()
        else:
            with open(args.audit, "r", encoding="utf-8") as f:
                raw = f.read()
        audit = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"unable to read/parse audit: {exc}\n")
        return 2

    result = validate_intervention_audit_shape(audit)
    sys.stdout.write(json.dumps(_result_to_dict(result), indent=2) + "\n")
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(_cli())


__all__ = [
    "InterventionAuditShapeResult",
    "validate_intervention_audit_shape",
    "CORRELATION_KEYS",
    "REQUIRED_TOP_LEVEL",
    "REQUIRED_SUBKEYS",
    "NULLABLE_TOP_LEVEL",
]
