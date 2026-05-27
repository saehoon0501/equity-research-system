"""Deterministic composition of catalyst-scout + flow-overlay modifiers into
the final `catalyst_modifier_applied` audit string.

Per /review-me iteration 1 finding #2: the §6 catalyst_modifier_applied composition
under LLM judgment was prone to drift on identical inputs because the additive
math + clipping rule was prose-only. This module pins the EXACT formula so the
synthesizer can call a pure function and emit a deterministic audit string.

Pairs with the v0.2 HG (deferred): a deterministic re-derivation gate in
src/eval/gates/catalyst_modifier_composition_check.py that re-computes
the expected modifier from upstream envelopes + rejects pm-supervisor emissions
that drift. v0.1 ships the helper; v0.2 wires the gate.

Composition rule:
  combined_modifier_pp = clip(catalyst_pp + flow_pp, -bound_pp, +bound_pp)

  where:
    catalyst_pp = catalyst_direction × magnitude_scaler[magnitude] × base_midpoint_pp
    flow_pp     = flow_sign × flow_per_unit_pct × base_midpoint_pp
    bound_pp    = bound_pct × base_midpoint_pp

  flow_sign is +1 if flow_signal_bin == "positive",
              -1 if == "negative",
               0 if in {"neutral", "unavailable", "offline"}.

  catalyst_direction ∈ {-1, 0, +1} per catalyst-scout envelope.
  magnitude ∈ {"low", "medium", "high"}; magnitude_scaler is a parameters-table
  lookup (sizing.catalyst_modifier_magnitude_scaler.{low,medium,high}).
  bound_pct ∈ {full_pct, shrunk_pct} per pm-supervisor §6 data-quality rule.

INV-CFM-1: catalyst_pp + flow_pp is computed BEFORE clipping (the bound applies
           to the COMBINED contribution, not each separately).
INV-CFM-2: clip is symmetric — combined_modifier_pp ∈ [-bound_pp, +bound_pp].
INV-CFM-3: result is deterministic in its 6 inputs; no LLM, no I/O, no clock reads.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

FlowSignalBin = Literal["positive", "neutral", "negative", "unavailable", "offline"]
CatalystDirection = Literal[-1, 0, 1]
Magnitude = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class CatalystFlowModifierResult:
    """Pure-function output. Audit string is reconstructable from fields."""

    base_midpoint_pp: float
    catalyst_direction: int
    catalyst_magnitude: Optional[Magnitude]
    catalyst_pp_unclipped: float
    flow_signal_bin: FlowSignalBin
    flow_sign: int
    flow_pp_unclipped: float
    combined_pp_unclipped: float
    bound_pp: float
    combined_pp_clipped: float
    clip_engaged: bool
    audit_string: str


def _flow_sign(flow_signal_bin: str) -> int:
    if flow_signal_bin == "positive":
        return 1
    if flow_signal_bin == "negative":
        return -1
    return 0  # neutral / unavailable / offline


def compose_catalyst_flow_modifier(
    *,
    base_midpoint_pp: float,
    catalyst_direction: int,
    catalyst_magnitude: Optional[str],
    catalyst_magnitude_scaler: dict[str, float],
    flow_signal_bin: Optional[str],
    flow_per_unit_pct: float,
    bound_pct: float,
    catalyst_reason: str = "",
    flow_reason: str = "",
) -> CatalystFlowModifierResult:
    """Pure composition of catalyst + flow contributions per the §6 spec.

    UNIT CONVENTION (load-bearing — /review-me iter 2 Finding A):
        All `*_pct` parameters here are FRACTIONAL (0.25 means 25%, 0.05 means 5%).
        The migration table stores INTEGER PERCENT (25, 5). Callers MUST divide
        parameters_active values by 100 before passing to this function.
        The input-range guard below raises if any scaler exceeds 1.0 — catches
        the "forgot the /100" 100× error before it corrupts the audit string.

    Args:
        base_midpoint_pp: the size-band midpoint before modifier application
            (e.g. 4.5 for a HIGH-band MEDIUM-bin midpoint). Percentage-points.
        catalyst_direction: -1 | 0 | +1 per catalyst-scout envelope.
        catalyst_magnitude: 'low' | 'medium' | 'high' | None (None when
            direction == 0; ignored in that case).
        catalyst_magnitude_scaler: dict from PARAMETERS_USED block, post-/100
            conversion (e.g. {'low': 0.05, 'medium': 0.10, 'high': 0.20}).
        flow_signal_bin: per flow-overlay envelope. Accepts 'offline' for
            the .degraded sentinel case. Accepts None and treats it identically
            to 'offline' (no envelope on disk = zero contribution).
        flow_per_unit_pct: post-/100 fractional value (default 0.05 = 5%).
        bound_pct: post-/100 fractional value per §6 data-quality rule
            (e.g. 0.25 for full, 0.10 for shrunk).
        catalyst_reason, flow_reason: free-form audit prose appended to the
            output audit_string.

    Returns:
        CatalystFlowModifierResult — all intermediate values + final clipped
        value + reconstructable audit string.

    Raises:
        ValueError: invalid enum values, missing scaler key, OR any input
            outside expected fractional range (catches integer-percent unit
            confusion before it propagates).
    """
    if catalyst_direction not in (-1, 0, 1):
        raise ValueError(
            f"catalyst_direction must be in {{-1, 0, +1}}, got {catalyst_direction!r}"
        )
    if flow_signal_bin is None:
        # None envelope file on disk → treat identically to 'offline' sentinel.
        # Per pm-supervisor.md §6 contract; documented + tested.
        flow_signal_bin = "offline"
    if flow_signal_bin not in ("positive", "neutral", "negative", "unavailable", "offline"):
        raise ValueError(f"unknown flow_signal_bin {flow_signal_bin!r}")
    if bound_pct <= 0:
        raise ValueError(f"bound_pct must be > 0, got {bound_pct}")

    # INV-CFM-UNIT: input-range guard catches integer-percent unit confusion.
    # All fractional parameters here represent percentages < 100% in practice
    # (a modifier of 100%+ of the midpoint would be a redesign, not a tuning).
    # If a caller forgets the /100 conversion, the value will be 5/10/20/25/etc.,
    # and this guard catches it before the audit string gets a 100× error.
    if bound_pct > 1.0:
        raise ValueError(
            f"bound_pct must be FRACTIONAL (< 1.0), got {bound_pct}. "
            "Did you forget to divide the parameters_active value by 100? "
            "Storage convention is integer-percent; helper expects fractional."
        )
    if flow_per_unit_pct > 1.0 or flow_per_unit_pct < 0:
        raise ValueError(
            f"flow_per_unit_pct must be in [0, 1.0], got {flow_per_unit_pct}. "
            "Did you forget the /100 conversion?"
        )
    for mag_key, mag_val in catalyst_magnitude_scaler.items():
        if not isinstance(mag_val, (int, float)) or mag_val > 1.0 or mag_val < 0:
            raise ValueError(
                f"catalyst_magnitude_scaler[{mag_key!r}] must be FRACTIONAL "
                f"in [0, 1.0], got {mag_val}. Did you forget the /100 conversion?"
            )

    # Catalyst contribution
    if catalyst_direction == 0:
        catalyst_pp_unclipped = 0.0
    else:
        if catalyst_magnitude not in catalyst_magnitude_scaler:
            raise ValueError(
                f"catalyst_magnitude {catalyst_magnitude!r} not in scaler "
                f"keys {sorted(catalyst_magnitude_scaler.keys())}"
            )
        scaler = catalyst_magnitude_scaler[catalyst_magnitude]
        catalyst_pp_unclipped = catalyst_direction * scaler * base_midpoint_pp

    # Flow contribution
    flow_sign = _flow_sign(flow_signal_bin)
    flow_pp_unclipped = flow_sign * flow_per_unit_pct * base_midpoint_pp

    # Combined + clip
    bound_pp = bound_pct * base_midpoint_pp
    combined_unclipped = catalyst_pp_unclipped + flow_pp_unclipped
    combined_clipped = max(-bound_pp, min(bound_pp, combined_unclipped))
    clip_engaged = combined_unclipped != combined_clipped

    # Audit string (reconstructable, no LLM judgment)
    sign_char = "+" if combined_clipped >= 0 else "-"
    parts = [f"{sign_char}{abs(combined_clipped):.2f}pp"]
    if catalyst_pp_unclipped != 0.0 or catalyst_reason:
        cat_sign = "+" if catalyst_pp_unclipped >= 0 else "-"
        cat_segment = (
            f"catalyst {cat_sign}{abs(catalyst_pp_unclipped):.2f}pp"
            f" (dir={catalyst_direction}, mag={catalyst_magnitude})"
        )
        if catalyst_reason:
            cat_segment += f" — {catalyst_reason}"
        parts.append(cat_segment)
    flow_segment = (
        f"flow {('+' if flow_pp_unclipped >= 0 else '-')}{abs(flow_pp_unclipped):.2f}pp"
        f" (bin={flow_signal_bin})"
    )
    if flow_reason:
        flow_segment += f" — {flow_reason}"
    parts.append(flow_segment)
    parts.append(f"bound=±{bound_pp:.2f}pp")
    if clip_engaged:
        parts.append("CLIPPED")
    audit_string = " | ".join(parts)

    return CatalystFlowModifierResult(
        base_midpoint_pp=base_midpoint_pp,
        catalyst_direction=catalyst_direction,
        catalyst_magnitude=catalyst_magnitude,  # type: ignore[arg-type]
        catalyst_pp_unclipped=catalyst_pp_unclipped,
        flow_signal_bin=flow_signal_bin,  # type: ignore[arg-type]
        flow_sign=flow_sign,
        flow_pp_unclipped=flow_pp_unclipped,
        combined_pp_unclipped=combined_unclipped,
        bound_pp=bound_pp,
        combined_pp_clipped=combined_clipped,
        clip_engaged=clip_engaged,
        audit_string=audit_string,
    )


__all__ = [
    "CatalystFlowModifierResult",
    "compose_catalyst_flow_modifier",
]
