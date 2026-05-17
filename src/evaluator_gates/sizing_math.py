"""Sizing-math conformance validator (HG-25, Group C fix — 2026-05-16).

The pm-supervisor §6 sizing pipeline is:

    base_band     = lookup(conviction)        # HIGH=(3,6,4.5), MEDIUM=(1.5,3,2.25), LOW=(0,0,0)
    multiplier    = lookup(mode)              # B=1.0, B'=0.5, C=0.333
    final_band    = base_band × multiplier

§7 tier overlays:
- core_fundamental: no overlay
- thematic_growth: cap to MEDIUM iff implied_growth > 1.5× historical CAGR
- speculative_optionality: clip final_max_book_pct to headroom (sleeve_reference required)

Historical bugs caught by this gate:

- RGTI: emitted HIGH-conviction 3-6% band to a speculative_optionality
  tier name without sleeve_reference clipping (or sleeve_reference
  showed headroom < 3%, which would have required the clip).
- RKLB: Mode C multiplier ~0.5× instead of ~0.333× — 0.5-1.0% emitted
  vs spec 0.33-0.67% for HIGH×C or 0.165-0.33% for MEDIUM×C.

This module re-computes the band deterministically and asserts the
emitted ``size_band_if_long`` (or ``would_be_size_at_*`` audit trace when
gated to zero) matches within epsilon.

DETERMINISM: pure stdlib, no I/O beyond CLI.
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass, field
from typing import Mapping

# Absolute-pp match tolerance. 0.01pp (= 1 basis point) is meaningfully
# tighter than any band-midpoint precision we'd emit.
DEFAULT_EPSILON_PP = 0.01

# Base bands keyed by conviction. (min_pct, max_pct, midpoint_pct).
CONVICTION_BANDS: dict[str, tuple[float, float, float]] = {
    "HIGH":   (3.0, 6.0, 4.5),
    "MEDIUM": (1.5, 3.0, 2.25),
    "LOW":    (0.0, 0.0, 0.0),
}

# Mode multipliers per pm-supervisor.md §6. ``B_prime`` is the JSON enum
# value; ``B'`` is the markdown convention — accept both.
MODE_MULTIPLIERS: dict[str, float] = {
    "B":       1.0,
    "B'":      0.5,
    "B_prime": 0.5,
    "C":       1.0 / 3.0,  # ~0.333
}

VALID_TIERS: frozenset[str] = frozenset({
    "core_fundamental",
    "thematic_growth",
    "speculative_optionality",
})


@dataclass
class SizingMathResult:
    """Result envelope for sizing-math conformance."""

    valid: bool
    # Inputs (echoed for audit).
    conviction: str | None
    mode: str | None
    tier: str | None
    summary_code: str | None
    # Re-computed deterministic ground truth (post mode multiplier).
    expected_band: tuple[float, float, float] | None
    # Emitted values from envelope.
    emitted_band: tuple[float, float, float] | None
    # Tier-overlay applicability + result.
    tier_clip_required: bool = False
    headroom: float | None = None
    clipped_max_expected: float | None = None
    # Deltas
    min_delta: float | None = None
    max_delta: float | None = None
    midpoint_delta: float | None = None
    epsilon: float = DEFAULT_EPSILON_PP
    notes: list[str] = field(default_factory=list)


def _coerce_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace("+", "").strip())
        except (ValueError, AttributeError):
            return None
    return None


def _extract_emitted_band(
    block: Mapping[str, object] | None,
) -> tuple[float, float, float] | None:
    """Pull (min, max, midpoint) from a band dict in the envelope.

    Accepts both the canonical schema (``min_book_pct`` / ``max_book_pct``
    / ``midpoint``) and the ``would_be_size_at_*`` audit-trace form (same
    keys per pm-supervisor.md §6 line 271 paragraph).
    """
    if not isinstance(block, dict):
        return None
    mn = _coerce_float(block.get("min_book_pct"))
    mx = _coerce_float(block.get("max_book_pct"))
    md = _coerce_float(block.get("midpoint"))
    if mn is None or mx is None or md is None:
        return None
    return (mn, mx, md)


def _compute_expected_band(
    conviction: str,
    mode: str,
) -> tuple[float, float, float] | None:
    """Compute the (min, max, midpoint) band for a (conviction, mode)
    pair per pm-supervisor.md §6 base bands × mode multipliers.

    Returns None if either input is not in the canonical table.
    """
    base = CONVICTION_BANDS.get(conviction)
    mult = MODE_MULTIPLIERS.get(mode)
    if base is None or mult is None:
        return None
    mn = round(base[0] * mult, 4)
    mx = round(base[1] * mult, 4)
    md = round(base[2] * mult, 2)  # spec line 290: "round midpoint to 2 decimals"
    return (mn, mx, md)


def validate_sizing_math(
    envelope: object,
    epsilon: float = DEFAULT_EPSILON_PP,
) -> SizingMathResult:
    """Validate the sizing math in a pm-supervisor envelope.

    Validates:
      1. Conviction + mode are recognized enum values.
      2. The emitted band (or would_be_size_at_* trace) matches the
         deterministically recomputed base_band × mode_multiplier within
         epsilon.
      3. For speculative_optionality tier: if headroom < final_max_book_pct,
         the emitted max must be clipped to headroom.
      4. summary_code != BUY ⇒ size_band_if_long must be all zeros; the
         pre-mode-multiplier ``would_be_size_at_*`` trace (when present)
         must still match the conviction band.

    Returns:
        SizingMathResult with valid=True iff all applicable checks pass.
    """
    if not isinstance(envelope, dict):
        return SizingMathResult(
            valid=False,
            conviction=None,
            mode=None,
            tier=None,
            summary_code=None,
            expected_band=None,
            emitted_band=None,
            epsilon=epsilon,
            notes=[
                f"envelope must be a JSON object; got "
                f"{type(envelope).__name__}"
            ],
        )

    conviction = envelope.get("conviction")
    mode = envelope.get("mode")
    tier = envelope.get("tier")
    summary_code = envelope.get("summary_code")
    sleeve_ref = envelope.get("sleeve_reference")

    result = SizingMathResult(
        valid=True,
        conviction=conviction if isinstance(conviction, str) else None,
        mode=mode if isinstance(mode, str) else None,
        tier=tier if isinstance(tier, str) else None,
        summary_code=summary_code if isinstance(summary_code, str) else None,
        expected_band=None,
        emitted_band=None,
        epsilon=epsilon,
    )

    # Enum-level checks first — give a clean diagnostic before doing math.
    if result.conviction not in CONVICTION_BANDS:
        result.valid = False
        result.notes.append(
            f"conviction={conviction!r} not in canonical enum "
            f"{sorted(CONVICTION_BANDS)}"
        )
        return result
    if result.mode not in MODE_MULTIPLIERS:
        result.valid = False
        result.notes.append(
            f"mode={mode!r} not in canonical enum "
            f"{sorted(MODE_MULTIPLIERS)}"
        )
        return result
    if result.tier is not None and result.tier not in VALID_TIERS:
        result.valid = False
        result.notes.append(
            f"tier={tier!r} not in canonical enum {sorted(VALID_TIERS)}"
        )
        return result

    expected = _compute_expected_band(result.conviction, result.mode)
    result.expected_band = expected  # always non-None given enum checks above

    # Locate the emitted band to compare against. When summary_code != BUY
    # the canonical ``size_band_if_long`` is all-zero by §6 line 271; the
    # would-be-size trace carries the meaningful sizing math.
    bands_to_check: list[tuple[str, tuple[float, float, float]]] = []

    sb = _extract_emitted_band(envelope.get("size_band_if_long"))
    if sb is not None:
        bands_to_check.append(("size_band_if_long", sb))
        result.emitted_band = sb

    # would_be_size_at_* trace (free-form key per §6 paragraph). Find any
    # key starting with "would_be_size".
    for k, v in envelope.items():
        if isinstance(k, str) and k.startswith("would_be_size"):
            wb = _extract_emitted_band(v)
            if wb is not None:
                bands_to_check.append((k, wb))

    # If summary_code is BUY, size_band_if_long must equal expected.
    # If summary_code != BUY, size_band_if_long must equal (0, 0, 0) AND
    # the would_be_size_* trace must equal expected.
    is_buy = result.summary_code == "BUY"

    for label, emitted in bands_to_check:
        if label == "size_band_if_long" and not is_buy:
            # Must be all zeros.
            if not all(
                math.isclose(v, 0.0, abs_tol=epsilon) for v in emitted
            ):
                result.valid = False
                result.notes.append(
                    f"summary_code={result.summary_code} (not BUY) but "
                    f"size_band_if_long={emitted} is non-zero; spec §6 "
                    "line 271 requires all-zero band when not BUY"
                )
            continue

        # Otherwise compare to expected (with speculative-tier clip).
        expected_for_compare = expected
        if (
            result.tier == "speculative_optionality"
            and isinstance(sleeve_ref, dict)
        ):
            headroom = _coerce_float(sleeve_ref.get("headroom"))
            if headroom is not None and expected is not None:
                result.headroom = headroom
                if expected[1] > headroom + epsilon:
                    # Clip max to headroom; midpoint = (min + clipped_max)/2.
                    clipped_max = headroom
                    clipped_mid = round(
                        (expected[0] + clipped_max) / 2.0, 2
                    )
                    expected_for_compare = (
                        expected[0],
                        clipped_max,
                        clipped_mid,
                    )
                    result.tier_clip_required = True
                    result.clipped_max_expected = clipped_max

        if expected_for_compare is None:
            continue

        d_min = emitted[0] - expected_for_compare[0]
        d_max = emitted[1] - expected_for_compare[1]
        d_mid = emitted[2] - expected_for_compare[2]

        if label == "size_band_if_long":
            result.min_delta = d_min
            result.max_delta = d_max
            result.midpoint_delta = d_mid

        if not (
            math.isclose(emitted[0], expected_for_compare[0], abs_tol=epsilon)
            and math.isclose(emitted[1], expected_for_compare[1], abs_tol=epsilon)
            and math.isclose(emitted[2], expected_for_compare[2], abs_tol=epsilon)
        ):
            result.valid = False
            result.notes.append(
                f"{label}={emitted} does not match expected "
                f"{expected_for_compare} for "
                f"(conviction={result.conviction}, mode={result.mode}"
                f"{', tier=speculative_optionality clipped to headroom=' + str(result.headroom) if result.tier_clip_required else ''}); "
                f"deltas min={d_min:+.4f} max={d_max:+.4f} mid={d_mid:+.4f}"
            )

    # Speculative-tier mandatory sleeve_reference check.
    if result.tier == "speculative_optionality" and not isinstance(
        sleeve_ref, dict
    ):
        result.valid = False
        result.notes.append(
            "tier=speculative_optionality requires a populated "
            "sleeve_reference block per §7 spec; got "
            f"{type(sleeve_ref).__name__ if sleeve_ref is not None else 'null/missing'}"
        )

    return result


def _result_to_dict(r: SizingMathResult) -> dict:
    return {
        "valid": r.valid,
        "inputs": {
            "conviction": r.conviction,
            "mode": r.mode,
            "tier": r.tier,
            "summary_code": r.summary_code,
        },
        "expected_band": r.expected_band,
        "emitted_band": r.emitted_band,
        "tier_clip_required": r.tier_clip_required,
        "headroom": r.headroom,
        "clipped_max_expected": r.clipped_max_expected,
        "deltas": {
            "min": r.min_delta,
            "max": r.max_delta,
            "midpoint": r.midpoint_delta,
        },
        "epsilon": r.epsilon,
        "notes": r.notes,
    }


def _cli(argv: list[str] | None = None) -> int:
    """CLI wrapper.

    Exit codes:
      0 sizing math valid
      1 sizing math invalid (one or more checks failed)
      2 input unparseable
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="sizing_math",
        description=(
            "Validate the sizing math in a pm-supervisor envelope: "
            "conviction × mode → expected band; speculative-tier "
            "headroom clipping; non-BUY zero-band invariant. "
            "Exit 0 valid, 1 invalid, 2 unparseable."
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

    result = validate_sizing_math(envelope, epsilon=args.epsilon)
    sys.stdout.write(json.dumps(_result_to_dict(result), indent=2) + "\n")
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(_cli())


__all__ = [
    "SizingMathResult",
    "validate_sizing_math",
    "CONVICTION_BANDS",
    "MODE_MULTIPLIERS",
    "VALID_TIERS",
]
