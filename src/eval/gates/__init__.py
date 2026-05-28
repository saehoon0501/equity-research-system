"""Evaluator gates — deterministic Tier-1 validators for pm-supervisor envelopes.

This package contains the cheap, fast, code-level checks that run as a
post-step hook after each subagent dispatch in /research-company. Tier-2
LLM evaluator (contamination, narrative coherence, evidence sufficiency)
runs only after the Tier-1 gates pass.

Each gate module exports a CLI for standalone invocation by the
orchestrator's Bash tool, plus a programmatic API used by the
``validate_all`` dispatcher below.

Module map (HG = hard-gate identifier):

    envelope_shape         — HG-23 — §8 top-level + sub-key presence, forbidden fields, summary_code enum
    sentiment_degradation  — HG-24 — re-compute sentiment_data_degraded from §4 indicators
    evidence_uuid_check    — HG-26 — evidence_index_refs UUID syntax + DB resolution
    outside_view_blend     — HG-27 — Bayesian-blend math consistency (catches AMZN raw==corrected bug)
    sizing_math            — HG-25 — conviction × mode → expected band; speculative-tier headroom clip
    counterfactual_catalog — HG-28 — top-3 bucket-schema + case_id catalog membership

Aggregate result:

    validate_all(envelope_path, ...) → AggregateValidationResult with
    per-gate pass/fail + a single overall valid bool.

Gate registry (P0-4)
--------------------
Which gates run for a given ``artifact_type`` — and the order they run in —
is defined entirely by the data structure ``REGISTRY`` in
:mod:`src.eval.gates._registry` (``{artifact_type: [GateRunner, ...]}``).
``validate_all`` simply builds a :class:`GateContext` from its kwargs, looks
up the artifact's runner list, and iterates it. Adding a gate to an artifact
is a pure data edit — append a runner to its registry entry — with **no edit
to ``validate_all`` and no per-artifact ``_validate_*`` body to touch** (those
bodies were folded into the registry runners).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Re-export the gate result dataclasses + validator entrypoints so that
# ``from src.eval.gates import EnvelopeShapeResult`` etc. keep working.
from src.eval.gates.envelope_shape import (
    EnvelopeShapeResult,
    validate_envelope_shape,
)
from src.eval.gates.evidence_uuid_check import (
    EvidenceUUIDResult,
    validate_evidence_refs_syntactic,
    validate_evidence_refs_with_db,
)
from src.eval.gates.outside_view_blend import (
    OutsideViewBlendResult,
    validate_outside_view_blend,
)
from src.eval.gates.sizing_math import (
    SizingMathResult,
    validate_sizing_math,
)
from src.eval.gates.counterfactual_catalog import (
    CounterfactualCatalogResult,
    validate_counterfactual_top3,
)
from src.eval.gates.sentiment_degradation import (
    compute_sentiment_data_degraded,
)
from src.eval.gates.quant_memo_shape import (
    QuantMemoShapeResult,
    validate_quant_memo_shape,
)
from src.eval.gates.strategic_memo_shape import (
    StrategicMemoShapeResult,
    validate_strategic_memo_shape,
)
from src.eval.gates.catalyst_memo_shape import (
    CatalystMemoShapeResult,
    validate_catalyst_memo_shape,
)
from src.eval.gates.cdd_memo_shape import (
    CDDMemoShapeResult,
    validate_cdd_memo_shape,
)
from src.eval.gates.tactical_envelope_shape import (
    TacticalEnvelopeShapeResult,
    validate_tactical_envelope_shape,
)
from src.eval.gates.reversion_envelope_shape import (
    ReversionEnvelopeShapeResult,
    validate_reversion_envelope_shape,
)
from src.eval.gates.intangibles_adjustment_shape import (
    IntangiblesAdjustmentResult,
    validate_intangibles_adjustment,
)
from src.eval.gates.catalyst_modifier_composition_check import (
    CatalystModifierCompositionResult,
    validate_catalyst_modifier_composition,
)
from src.eval.gates.crowding_composition_check import (
    CrowdingCompositionResult,
    validate_crowding_composition,
)

# Outcome primitives + the per-artifact gate registry (P0-4).
from src.eval.gates._outcome import (
    GATE_IDS,
    GateOutcome,
    make_outcome,
    to_dict_safe,
)
from src.eval.gates._registry import (
    REGISTRY,
    GateContext,
    GateRunner,
)


# Canonical artifact types accepted by validate_all. Each maps to its
# own gate set (see REGISTRY); pm_envelope is the default for backward
# compatibility. Kept as an explicit tuple (its membership/order is part
# of the public contract used by the CLI's ``choices=``) and asserted to
# stay in lock-step with the registry keys below.
VALID_ARTIFACT_TYPES = (
    "pm_envelope",
    "quant_memo",
    "strategic_memo",
    "catalyst_memo",
    "cdd_memo",
    "tactical_envelope",
    "reversion_envelope",
)

assert set(VALID_ARTIFACT_TYPES) == set(REGISTRY), (
    "VALID_ARTIFACT_TYPES and the gate REGISTRY have drifted; "
    f"tuple={set(VALID_ARTIFACT_TYPES)} registry={set(REGISTRY)}"
)


@dataclass
class AggregateValidationResult:
    """Aggregate of all gate outcomes for one envelope."""

    valid: bool
    artifact_path: str | None
    gates: list[GateOutcome] = field(default_factory=list)
    summary: dict[str, str] = field(default_factory=dict)
    # summary["envelope_shape"] = "pass" / "fail" / "skipped"

    def failed_gates(self) -> list[GateOutcome]:
        return [g for g in self.gates if not g.valid]

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "artifact_path": self.artifact_path,
            "summary": self.summary,
            "gates": [
                {
                    "gate_id": g.gate_id,
                    "gate_name": g.gate_name,
                    "valid": g.valid,
                    "error_fingerprint": g.error_fingerprint,
                    "result": g.result_dict,
                }
                for g in self.gates
            ],
        }


def validate_all(
    envelope: dict[str, Any] | str | Path,
    *,
    artifact_type: str = "pm_envelope",
    resolve_evidence_db: bool = False,
    case_ids_for_counterfactual: list[str] | None = None,
    db_dsn: str | None = None,
    catalyst_indicators: list[dict] | None = None,
    strict_envelope_shape: bool = False,
    catalyst_env: dict | None = None,
    flow_env: dict | None = None,
    params_snapshot: dict | None = None,
) -> AggregateValidationResult:
    """Run the gate set appropriate to ``artifact_type``.

    The set of gates (and their order) per ``artifact_type`` is defined by
    ``REGISTRY`` in :mod:`src.eval.gates._registry`. This function is a
    thin driver: it builds a :class:`GateContext` from the kwargs below,
    iterates the artifact's registered runners, and aggregates their
    outcomes. Conditional gates (e.g. ``sentiment_degradation``,
    ``catalyst_modifier_composition_check``, ``crowding_composition_check``)
    short-circuit to a ``"skipped"`` summary inside their own runner and
    contribute no outcome to the ``valid`` roll-up.

    Args:
        envelope: parsed dict, or path-like to a JSON file.
        artifact_type: one of {pm_envelope, quant_memo, strategic_memo,
            catalyst_memo, cdd_memo, tactical_envelope, reversion_envelope}.
            Defaults to pm_envelope for backward compatibility.
        resolve_evidence_db: HG-26 DB resolution check.
        case_ids_for_counterfactual: case_ids for HG-28 catalog check
            (pm_envelope only).
        db_dsn: Postgres DSN passthrough.
        catalyst_indicators: HG-24 cross-check (pm_envelope only).
        strict_envelope_shape: HG-23 strict mode (pm_envelope only).
        catalyst_env: HG-34 input — catalyst-scout envelope dict (pm_envelope only;
            v0.2; None when catalyst-scout offline).
        flow_env: HG-34 input — flow-overlay envelope dict (pm_envelope only;
            v0.2; None when flow-overlay offline).
        params_snapshot: HG-34 input — flat dict of parameters_active rows
            (pm_envelope only; v0.2). When None, HG-34/HG-35 are skipped.

    Returns:
        AggregateValidationResult with one GateOutcome per gate that ran.
        The ``valid`` field is True iff every gate that produced an outcome
        passed (skipped gates do not affect it).

    Raises:
        ValueError: if artifact_type is not in VALID_ARTIFACT_TYPES.
    """
    if artifact_type not in REGISTRY:
        raise ValueError(
            f"artifact_type={artifact_type!r} not in {VALID_ARTIFACT_TYPES}"
        )

    artifact_path: str | None = None
    env: dict[str, Any]
    if isinstance(envelope, (str, Path)):
        artifact_path = str(envelope)
        with open(envelope, "r", encoding="utf-8") as f:
            env = json.load(f)
    elif isinstance(envelope, dict):
        env = envelope
    else:
        raise TypeError(
            f"envelope must be dict or path; got {type(envelope).__name__}"
        )

    ctx = GateContext(
        resolve_evidence_db=resolve_evidence_db,
        case_ids_for_counterfactual=case_ids_for_counterfactual,
        db_dsn=db_dsn,
        catalyst_indicators=catalyst_indicators,
        strict_envelope_shape=strict_envelope_shape,
        catalyst_env=catalyst_env,
        flow_env=flow_env,
        params_snapshot=params_snapshot,
    )

    outcomes: list[GateOutcome] = []
    summary: dict[str, str] = {}
    for runner in REGISTRY[artifact_type]:
        outcome, summary_key, summary_value = runner(env, ctx)
        summary[summary_key] = summary_value
        if outcome is not None:
            outcomes.append(outcome)

    overall_valid = all(o.valid for o in outcomes)
    return AggregateValidationResult(
        valid=overall_valid,
        artifact_path=artifact_path,
        gates=outcomes,
        summary=summary,
    )


def _cli(argv: list[str] | None = None) -> int:
    """CLI wrapper for the aggregate validator.

    Exit codes:
      0 all gates passed
      1 one or more gates failed
      2 unparseable input
    """
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="validate_all",
        description=(
            "Run every Tier-1 gate (HG-23/24/25/26/27/28/29/30/31/32/33/34/35/38) "
            "against a pm-supervisor envelope. Exit 0 valid, 1 invalid, 2 unparseable."
        ),
    )
    parser.add_argument(
        "--envelope",
        required=True,
        help="path to envelope/memo JSON file",
    )
    parser.add_argument(
        "--artifact-type",
        default="pm_envelope",
        choices=VALID_ARTIFACT_TYPES,
        help="which gate set to run (default pm_envelope for backward compat)",
    )
    parser.add_argument(
        "--resolve-evidence-db",
        action="store_true",
        help="also check evidence_index_refs resolve in evidence_index table",
    )
    parser.add_argument(
        "--case-ids",
        default=None,
        help="comma-separated case_ids for counterfactual catalog check",
    )
    parser.add_argument(
        "--catalyst-indicators",
        default=None,
        help="path to JSON file with catalyst-scout §4 indicators",
    )
    parser.add_argument(
        "--db-dsn",
        default=None,
    )
    parser.add_argument(
        "--strict-shape",
        action="store_true",
        help="strict envelope-shape validation (report.* row subkeys)",
    )
    args = parser.parse_args(argv)

    try:
        with open(args.envelope, "r", encoding="utf-8") as f:
            env = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"unable to read/parse envelope: {exc}\n")
        return 2

    case_ids: list[str] | None = None
    if args.case_ids:
        case_ids = [c.strip() for c in args.case_ids.split(",") if c.strip()]

    indicators: list[dict] | None = None
    if args.catalyst_indicators:
        try:
            with open(args.catalyst_indicators, "r", encoding="utf-8") as f:
                parsed = json.load(f)
            if isinstance(parsed, list):
                indicators = parsed
            elif isinstance(parsed, dict) and isinstance(
                parsed.get("indicators"), list
            ):
                indicators = parsed["indicators"]
        except (OSError, json.JSONDecodeError) as exc:
            sys.stderr.write(
                f"unable to read catalyst indicators: {exc}\n"
            )
            return 2

    result = validate_all(
        env,
        artifact_type=args.artifact_type,
        resolve_evidence_db=args.resolve_evidence_db,
        case_ids_for_counterfactual=case_ids,
        db_dsn=args.db_dsn,
        catalyst_indicators=indicators,
        strict_envelope_shape=args.strict_shape,
    )
    sys.stdout.write(json.dumps(result.to_dict(), indent=2, default=str) + "\n")
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(_cli())


__all__ = [
    "AggregateValidationResult",
    "GateOutcome",
    "GATE_IDS",
    "GateContext",
    "GateRunner",
    "REGISTRY",
    "VALID_ARTIFACT_TYPES",
    "validate_all",
]
