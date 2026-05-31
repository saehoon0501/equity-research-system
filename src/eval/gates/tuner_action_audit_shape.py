"""Tuner-action-audit envelope shape validator (HG-41, walkforward-tuning-loop).

The walkforward-tuning-loop (`.kiro/specs/walkforward-tuning-loop/`) emits a
tuner-action audit on EVERY cycle — promote AND decline (R8.1) — recording the
falsifiable *why* of the promotion decision, correlated to the model trace +
outcome ledger via the four shared keys (R8.3). This module is its presence-only
HG validator, mirroring ``src/eval/gates/envelope_shape.py`` (HG-23) and
``src/eval/gates/intervention_audit_shape.py`` (HG-39).

It realizes R6's evaluator obligation for this loop: the existing ``/evaluate``
hard gates are output-type-specific (HG-4 every claim needs an Evidence-Index
reference) and do not fit a statistical audit; R6's "evaluator" is realized by
THIS validator's falsifiability gate (design §audit + tuner_action_audit_shape).

THE ENVELOPE SHAPE it validates is the FLAT dict the ``audit`` leaf (task 3.2)
serializes from the ``TunerActionAudit`` frozen dataclass via
``dataclasses.asdict`` — the four correlation keys at the TOP LEVEL (flattened,
NOT nested under a ``keys`` block — this is where the HG-39 analog would mislead;
HG-39 nests its keys, this one does not), the DERIVED ``gate_metrics`` dict, and
the STRUCTURED ``hypothesis`` ({statement, falsifiers}):

    {
      "audit_id":            str,
      "run_id":              str,         # correlation key 1 (P3) — required
      "code_version":        str,         # correlation key 2     — required
      "param_version":       str,         # correlation key 3     — required
      "walk_forward_window": str | null,  # correlation key 4     — NULLABLE
      "promoted":            bool,
      "track":               "param"|"code"|"both",
      "gate_metrics": {                    # DERIVED, not asserted (P15)
        "dsr", "psr", "min_trl_met", "pbo", "effective_n", "lexicographic_ok"
      },
      "hypothesis": {                      # FALSIFIABLE (P15)
        "statement":  str,
        "falsifiers": [str, ...]          # >=1 observable falsifier
      }
    }

P15 falsifiability/derived-metrics check (the gate's substance): ``gate_metrics``
must carry its six DERIVED figures (so the rationale's numbers are the gate's own
derived output, never asserted probabilities), and ``hypothesis`` must carry both
a falsifiable ``statement`` AND a NON-EMPTY ``falsifiers`` list (a hypothesis with
no observable falsifier is not falsifiable). ``statement`` and ``falsifiers`` are
checked SEPARATELY so a consumer can tell a missing hypothesis from an
unfalsifiable one (design observable: "rejects … the hypothesis / the
falsifiers" independently).

``walk_forward_window`` is NULLABLE — it is null on decline ("null until
promoted", design §Data Models; types.py ``str | None``). The audit is emitted on
BOTH promote and decline, so requiring it non-null would fail EVERY decline audit
(the conservative path, P7, the E2E 4.2 most wants to prove). Nullable here means:
the KEY must be present, but ``None`` is an accepted value.

Presence-only by design (P13 / matches HG-23, HG-39): the gate checks KEY
PRESENCE + non-emptiness, NOT value type-correctness. Type-correctness of the
audit is enforced by the ``TunerActionAudit`` frozen dataclass at assembly time
(task 3.2) + the per-leaf inner-ring tests (P14), NOT by this gate.

DETERMINISM: pure Python; no I/O beyond CLI stdin/stdout. No HTTP, no DB, no skill
import (dict-only — it never imports the walkforward_tune package).
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field

# The four correlation keys (R8.3) every audit carries at the TOP LEVEL
# (flattened — the audit leaf serializes ``asdict(TunerActionAudit)``), so the
# row joins to ``decision_process_trace`` (mig 048) + ``counterfactual_ledger``.
# Named separately so a consumer can report the missing-correlation-key case
# distinctly. ``walk_forward_window`` is NULLABLE (see NULLABLE_TOP_LEVEL).
CORRELATION_KEYS: tuple[str, ...] = (
    "run_id",
    "code_version",
    "param_version",
    "walk_forward_window",
)

# The six DERIVED gate figures (P15 — derived, not asserted). These mirror the
# audit leaf's pinned ``_GATE_METRIC_KEYS`` (``audit.gate_metrics_from_verdict``)
# and the mig-053 ``gate_metrics`` JSONB column exactly — kept as the single
# source of truth for the ``gate_metrics`` sub-shape this gate enforces.
GATE_METRIC_KEYS: tuple[str, ...] = (
    "dsr",
    "psr",
    "min_trl_met",
    "pbo",
    "effective_n",
    "lexicographic_ok",
)

# Required top-level keys per the TunerActionAudit data model (design §Data
# Models). The four correlation keys ride FLATTENED at the top level (NOT nested
# — unlike HG-39's ``keys`` block). Each must be present-and-non-empty EXCEPT the
# nullable keys below (KEY presence only).
REQUIRED_TOP_LEVEL: tuple[str, ...] = (
    "run_id",
    "code_version",
    "param_version",
    "walk_forward_window",
    "gate_metrics",
    "hypothesis",
)

# Keys where ``null`` / ``None`` is a legitimate value (design §Data Models:
# ``walk_forward_window`` is "null until promoted"). For these the validator
# requires the KEY present, but accepts ``None`` — required-but-nullable, so a
# decline audit (walk_forward_window=None) validates while a MISSING key does not.
NULLABLE_TOP_LEVEL: frozenset[str] = frozenset({"walk_forward_window"})

# Required sub-keys per top-level block — the P15 gate substance.
REQUIRED_SUBKEYS: dict[str, tuple[str, ...]] = {
    # The DERIVED gate figures (P15): the metrics are the gate's own derived
    # numbers, not asserted probabilities — so all six must be present.
    "gate_metrics": GATE_METRIC_KEYS,
    # The FALSIFIABLE rationale (P15): a statement AND a non-empty falsifiers
    # list. A statement alone is not falsifiable; an empty falsifiers list is not
    # falsifiable. Checked separately so a consumer distinguishes the two.
    "hypothesis": ("statement", "falsifiers"),
}


@dataclass
class TunerActionAuditResult:
    """Result envelope for tuner-action-audit shape validation.

    Named field-lists let a fingerprint helper produce a deterministic stuck-loop
    signature for the agent_harness retry loop (mirrors the other gate result
    dataclasses).
    """

    valid: bool
    missing_top_level: list[str] = field(default_factory=list)
    missing_subkeys: dict[str, list[str]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _is_present_non_empty(value: object) -> bool:
    """Presence check identical to ``envelope_shape._is_present_non_empty``.

    A value counts as present iff it is not None, not a missing key, and not an
    empty container/string. A derived metric of ``False`` / ``0`` / ``0.0`` is a
    real value (present) — only ``None`` and empty containers/strings fail.
    """
    if value is None:
        return False
    if isinstance(value, (str, list, dict, tuple)) and len(value) == 0:
        return False
    return True


def validate_tuner_action_audit(env: dict) -> TunerActionAuditResult:
    """Validate a tuner-action-audit envelope against the TunerActionAudit shape.

    Presence-only (P13): checks KEY PRESENCE + non-emptiness of the required
    top-level keys (the four flattened correlation keys + gate_metrics +
    hypothesis), the six DERIVED gate metrics, and the FALSIFIABLE hypothesis
    sub-keys (statement + a non-empty falsifiers list). Does NOT type-check
    values.

    Args:
        env: the parsed audit envelope dict (the on-disk
            ``memos/envelopes/walkforward-tune__<run_id>.json`` the audit leaf
            writes, or its in-memory equivalent).

    Returns:
        TunerActionAuditResult with ``valid=True`` iff every required top-level
        key is present-and-non-empty (``walk_forward_window`` may be ``None``, but
        the KEY must exist) AND both validated blocks carry their required
        sub-keys (the P15 derived-metrics + falsifiability check).
    """
    if not isinstance(env, dict):
        return TunerActionAuditResult(
            valid=False,
            missing_top_level=list(REQUIRED_TOP_LEVEL),
            notes=[
                f"envelope must be a JSON object (dict); got {type(env).__name__}"
            ],
        )

    result = TunerActionAuditResult(valid=True)

    # Top-level presence. Nullable keys (``walk_forward_window``) need only the
    # KEY present; the rest need a present-and-non-empty value.
    for key in REQUIRED_TOP_LEVEL:
        if key in NULLABLE_TOP_LEVEL:
            if key not in env:
                result.missing_top_level.append(key)
        else:
            if not _is_present_non_empty(env.get(key)):
                result.missing_top_level.append(key)

    # Sub-key presence for the validated blocks (the P15 gate substance):
    #   gate_metrics — all six DERIVED figures present (derived, not asserted);
    #   hypothesis   — a falsifiable statement + a non-empty falsifiers list.
    for top_key, subkeys in REQUIRED_SUBKEYS.items():
        block = env.get(top_key)
        if not isinstance(block, dict):
            # The block itself is missing/non-dict — already reported at the top
            # level; don't double-report its sub-keys for a block that is absent.
            continue
        missing_here = [
            sk for sk in subkeys if not _is_present_non_empty(block.get(sk))
        ]
        if missing_here:
            result.missing_subkeys[top_key] = missing_here

    if result.missing_top_level or result.missing_subkeys:
        result.valid = False

    return result


def _result_to_dict(r: TunerActionAuditResult) -> dict:
    return {
        "valid": r.valid,
        "missing_top_level": r.missing_top_level,
        "missing_subkeys": r.missing_subkeys,
        "notes": r.notes,
    }


def _cli(argv: list[str] | None = None) -> int:
    """CLI wrapper. Reads the envelope JSON from ``--envelope <path>`` or stdin
    (``--envelope -``) and prints the validation result as JSON.

    Exit codes:
      0  envelope valid
      1  envelope invalid (one or more checks failed)
      2  envelope unparseable or arguments invalid
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="tuner_action_audit_shape",
        description=(
            "Validate a walkforward-tuning-loop tuner-action-audit envelope "
            "against the TunerActionAudit shape (presence-only, HG-41). "
            "Exit 0 valid, 1 invalid, 2 unparseable."
        ),
    )
    parser.add_argument(
        "--envelope",
        required=True,
        help='path to envelope JSON file, or "-" to read from stdin',
    )
    args = parser.parse_args(argv)

    try:
        if args.envelope == "-":
            raw = sys.stdin.read()
        else:
            with open(args.envelope, "r", encoding="utf-8") as f:
                raw = f.read()
        env = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"unable to read/parse envelope: {exc}\n")
        return 2

    result = validate_tuner_action_audit(env)
    sys.stdout.write(json.dumps(_result_to_dict(result), indent=2) + "\n")
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(_cli())


__all__ = [
    "TunerActionAuditResult",
    "validate_tuner_action_audit",
    "CORRELATION_KEYS",
    "GATE_METRIC_KEYS",
    "REQUIRED_TOP_LEVEL",
    "REQUIRED_SUBKEYS",
    "NULLABLE_TOP_LEVEL",
]
