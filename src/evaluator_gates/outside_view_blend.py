"""Outside-view Bayesian-blend consistency check (Group F, AMZN math bug).

The pm-supervisor §2.6 adversarial_stress_test block carries an
``outside_view_*`` substructure (Overlay 3+4 per quantitative-analyst.md)
with these load-bearing fields:

- ``intuitive_growth_pct``                  — agent's bottom-up growth estimate
- ``reference_class_growth_mean_pct``        — cohort base rate
- ``r_coefficient_used``                     — Bayesian-blend weight (0.20 default)
- ``corrected_growth_pct``                   — blended result
- ``outside_view_divergence_pp_raw``         — intuitive − reference (pre-blend)
- ``corrected_divergence_pp``                — corrected − reference (post-blend)

The Bayesian blend formula per Mauboussin/Lovallo-Kahneman 2003 and
canonical-frameworks.md §3 is:

    corrected = intuitive * (1 - r) + reference * r

AMZN 2026-05-14 emitted ``raw = corrected = -0.80`` with ``r = 0.20``
which is mathematically inconsistent unless r = 0. The agent appears to
have skipped the blend step and copied the raw value into the corrected
field. This module re-computes the corrected value deterministically
and asserts the agent's emitted value matches within an epsilon.

DETERMINISM: pure Python, no I/O beyond CLI.
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass, field

# Match tolerance for the blend computation. 0.05pp absolute is well
# inside any reasonable agent-emitted precision; tighter than the value
# itself is meaningful.
DEFAULT_EPSILON_PP = 0.05

# Default r per Mauboussin base-rates 2016 (consistent across the codebase).
DEFAULT_R_COEFFICIENT = 0.20


@dataclass
class OutsideViewBlendResult:
    """Result envelope for the blend-consistency check."""

    valid: bool
    # Inputs (echoed for audit clarity).
    intuitive: float | None
    reference: float | None
    r: float | None
    corrected_emitted: float | None
    raw_divergence_emitted: float | None
    corrected_divergence_emitted: float | None
    # Re-computed deterministic ground truth.
    corrected_recomputed: float | None = None
    raw_divergence_recomputed: float | None = None
    corrected_divergence_recomputed: float | None = None
    # Deltas (emitted − recomputed). When valid, all |delta| <= epsilon.
    corrected_delta: float | None = None
    raw_divergence_delta: float | None = None
    corrected_divergence_delta: float | None = None
    epsilon: float = DEFAULT_EPSILON_PP
    notes: list[str] = field(default_factory=list)


def _coerce_float(value: object) -> float | None:
    """Coerce numeric or numeric-string to float; return None on failure."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None  # bool is a subclass of int — reject explicitly
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace("+", "").strip())
        except (ValueError, AttributeError):
            return None
    return None


def validate_outside_view_blend(
    outside_view_block: object,
    epsilon: float = DEFAULT_EPSILON_PP,
) -> OutsideViewBlendResult:
    """Validate the Bayesian blend math inside an outside_view block.

    Args:
        outside_view_block: dict with the §2.6 outside_view_* fields.
            Typically pulled from
            ``envelope["adversarial_stress_test"]`` since several names
            (e.g. ``outside_view_divergence_pp_raw``) live there per the
            existing emission convention.
        epsilon: percentage-point tolerance for the blend match
            (default 0.05pp).

    Returns:
        OutsideViewBlendResult with valid=True iff:
        (a) the corrected value matches the recomputed blend within epsilon,
        (b) the raw divergence matches intuitive - reference,
        (c) the corrected divergence matches corrected - reference.
        When any input field is missing/non-numeric, valid=False with a
        diagnostic note.
    """
    if not isinstance(outside_view_block, dict):
        return OutsideViewBlendResult(
            valid=False,
            intuitive=None,
            reference=None,
            r=None,
            corrected_emitted=None,
            raw_divergence_emitted=None,
            corrected_divergence_emitted=None,
            epsilon=epsilon,
            notes=[
                f"outside_view block must be a dict; got "
                f"{type(outside_view_block).__name__}"
            ],
        )

    intuitive = _coerce_float(
        outside_view_block.get("intuitive_growth_pct")
    )
    reference = _coerce_float(
        outside_view_block.get("reference_class_growth_mean_pct")
    )
    r_emitted = _coerce_float(outside_view_block.get("r_coefficient_used"))
    corrected = _coerce_float(outside_view_block.get("corrected_growth_pct"))
    raw_div_emitted = _coerce_float(
        outside_view_block.get("outside_view_divergence_pp_raw")
    )
    corrected_div_emitted = _coerce_float(
        outside_view_block.get("corrected_divergence_pp")
    )

    result = OutsideViewBlendResult(
        valid=True,
        intuitive=intuitive,
        reference=reference,
        r=r_emitted,
        corrected_emitted=corrected,
        raw_divergence_emitted=raw_div_emitted,
        corrected_divergence_emitted=corrected_div_emitted,
        epsilon=epsilon,
    )

    # Tier-conditional skip surface: speculative_optionality may emit
    # "N/A speculative skip" string sentinels. Coerce returns None for
    # those — interpret as "skip the check" rather than fail. The check
    # only runs when intuitive AND reference are numeric.
    if intuitive is None or reference is None:
        result.notes.append(
            "intuitive_growth_pct or reference_class_growth_mean_pct is "
            "non-numeric (speculative-tier skip OR missing field); "
            "blend-consistency check not applicable"
        )
        # When fields are skipped, we don't mark invalid — the
        # speculative tier legitimately skips this. But the envelope
        # shape check should still require the field to be PRESENT
        # (even if sentinel-valued); that's HG-23's job, not ours.
        return result

    if r_emitted is None:
        result.r = DEFAULT_R_COEFFICIENT
        result.notes.append(
            f"r_coefficient_used missing; using default {DEFAULT_R_COEFFICIENT}"
        )
        r_used = DEFAULT_R_COEFFICIENT
    else:
        r_used = r_emitted

    if not (0.0 <= r_used <= 1.0):
        result.valid = False
        result.notes.append(
            f"r_coefficient_used={r_used} is outside [0, 1]; blend "
            "formula assumes a convex combination weight"
        )
        return result

    # The Bayesian blend.
    corrected_recomputed = intuitive * (1.0 - r_used) + reference * r_used
    raw_div_recomputed = intuitive - reference
    corrected_div_recomputed = corrected_recomputed - reference

    result.corrected_recomputed = corrected_recomputed
    result.raw_divergence_recomputed = raw_div_recomputed
    result.corrected_divergence_recomputed = corrected_div_recomputed

    if corrected is not None:
        delta = corrected - corrected_recomputed
        result.corrected_delta = delta
        if not math.isclose(corrected, corrected_recomputed, abs_tol=epsilon):
            result.valid = False
            result.notes.append(
                f"corrected_growth_pct={corrected} does not match the "
                f"Bayesian blend intuitive*(1-r) + reference*r = "
                f"{corrected_recomputed:.4f} within {epsilon}pp "
                f"(delta {delta:+.4f}pp); r={r_used}"
            )

    if raw_div_emitted is not None:
        delta = raw_div_emitted - raw_div_recomputed
        result.raw_divergence_delta = delta
        if not math.isclose(
            raw_div_emitted, raw_div_recomputed, abs_tol=epsilon
        ):
            result.valid = False
            result.notes.append(
                f"outside_view_divergence_pp_raw={raw_div_emitted} does "
                f"not match intuitive - reference = "
                f"{raw_div_recomputed:.4f} within {epsilon}pp "
                f"(delta {delta:+.4f}pp)"
            )

    if corrected_div_emitted is not None:
        delta = corrected_div_emitted - corrected_div_recomputed
        result.corrected_divergence_delta = delta
        if not math.isclose(
            corrected_div_emitted, corrected_div_recomputed, abs_tol=epsilon
        ):
            result.valid = False
            result.notes.append(
                f"corrected_divergence_pp={corrected_div_emitted} does "
                f"not match corrected - reference = "
                f"{corrected_div_recomputed:.4f} within {epsilon}pp "
                f"(delta {delta:+.4f}pp)"
            )

    # AMZN-specific signature: raw == corrected with r > 0. This catches
    # the "skipped the blend step" failure mode even when the individual
    # delta checks would also fire — produces a clearer diagnostic.
    if (
        raw_div_emitted is not None
        and corrected_div_emitted is not None
        and r_used > 0.0
        and math.isclose(
            raw_div_emitted, corrected_div_emitted, abs_tol=1e-9
        )
        and not math.isclose(intuitive, reference, abs_tol=1e-9)
    ):
        result.valid = False
        result.notes.append(
            "AMZN-signature: raw_divergence == corrected_divergence with "
            f"r={r_used} > 0 — the blend step appears to have been "
            "skipped (corrected field copied from raw)"
        )

    return result


def _result_to_dict(r: OutsideViewBlendResult) -> dict:
    return {
        "valid": r.valid,
        "epsilon": r.epsilon,
        "inputs": {
            "intuitive_growth_pct": r.intuitive,
            "reference_class_growth_mean_pct": r.reference,
            "r_coefficient_used": r.r,
            "corrected_growth_pct_emitted": r.corrected_emitted,
            "outside_view_divergence_pp_raw_emitted": r.raw_divergence_emitted,
            "corrected_divergence_pp_emitted": r.corrected_divergence_emitted,
        },
        "recomputed": {
            "corrected_growth_pct": r.corrected_recomputed,
            "outside_view_divergence_pp_raw": r.raw_divergence_recomputed,
            "corrected_divergence_pp": r.corrected_divergence_recomputed,
        },
        "deltas": {
            "corrected": r.corrected_delta,
            "raw_divergence": r.raw_divergence_delta,
            "corrected_divergence": r.corrected_divergence_delta,
        },
        "notes": r.notes,
    }


def _cli(argv: list[str] | None = None) -> int:
    """CLI wrapper.

    Exit codes:
      0 blend valid (or skip-applicable per tier)
      1 blend invalid
      2 input unparseable
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="outside_view_blend",
        description=(
            "Validate the Bayesian-blend math in a pm-supervisor "
            "envelope's adversarial_stress_test.outside_view_* fields. "
            "Exit 0 valid (or skip-applicable), 1 invalid, 2 unparseable."
        ),
    )
    parser.add_argument(
        "--envelope",
        required=True,
        help='path to envelope JSON file, or "-" to read from stdin',
    )
    parser.add_argument(
        "--epsilon",
        type=float,
        default=DEFAULT_EPSILON_PP,
        help=f"percentage-point match tolerance (default {DEFAULT_EPSILON_PP})",
    )
    args = parser.parse_args(argv)

    try:
        if args.envelope == "-":
            raw = sys.stdin.read()
        else:
            with open(args.envelope, "r", encoding="utf-8") as f:
                raw = f.read()
        envelope = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"unable to read/parse envelope: {exc}\n")
        return 2

    if not isinstance(envelope, dict):
        sys.stderr.write("envelope must be a JSON object\n")
        return 2

    # The outside_view_* fields live inside adversarial_stress_test per
    # the existing emission convention (see envelope_shape.py
    # REQUIRED_SUBKEYS).
    block = envelope.get("adversarial_stress_test") or {}
    result = validate_outside_view_blend(block, epsilon=args.epsilon)
    sys.stdout.write(json.dumps(_result_to_dict(result), indent=2) + "\n")
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(_cli())


__all__ = [
    "OutsideViewBlendResult",
    "validate_outside_view_blend",
    "DEFAULT_EPSILON_PP",
    "DEFAULT_R_COEFFICIENT",
]
