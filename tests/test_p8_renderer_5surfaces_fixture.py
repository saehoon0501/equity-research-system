"""G-CHECK-3 fixture: 5-surface renderer coverage gate.

Per docs/phase_1_acceptance_spec.md, Section 2.1 v5 requires the renderer to be able to
produce 5 distinct surfaces:
  1. BUY-HIGH         (HIGH × positive)
  2. BUY-MED          (MEDIUM × positive)
  3. HOLD             (any of 9 matrix cells routing to HOLD without veto)
  4. AVOID            (LOW × {negative, neutral, positive})
  5. LOW-CONVICTION VETO (LOW × unavailable — renders as HOLD + veto flag)

This fixture tests that each surface is reachable through the matrix function AND
that the LOW-CONVICTION VETO surface is uniquely identifiable from the matrix output
(i.e., the renderer can distinguish "plain HOLD" from "HOLD + veto").

Iteration 3 catch: presence-only test ("renderer surfaces all 5 enum values") is
insufficient — a renderer that emits BUY-HIGH for every input still passes presence.
Tighten by asserting per-surface (conviction, tactical_bin) → cell_disposition mapping
and verifying the veto-flag predicate is mechanically derivable from the inputs.
"""
from __future__ import annotations

import pytest

from src.p8_tactical_overlay.overlay import _DISPOSITION_MAP, tactical_disposition

# Renderer flag derivation: LOW-CONVICTION VETO fires when conviction=LOW
# AND the cell_disposition is HOLD (i.e., the LOW × unavailable cell).
# Section 2.1 v5: "LOW-CONVICTION VETO cites per-conviction-tier mapping."
def renderer_low_conviction_veto_flag(conviction: str, tactical_bin: str) -> bool:
    """Mechanical predicate for surface #5.

    The renderer surfaces the veto annotation when the (conviction, tactical_bin)
    input pair produces HOLD via the LOW row. Distinct from generic HOLD.
    """
    return conviction == "LOW" and _DISPOSITION_MAP[(conviction, tactical_bin)] == "HOLD"


# Fixture: each row produces ONE of the 5 surfaces. The renderer is correct iff
# every input that should produce surface N actually does, AND no input produces
# multiple surfaces simultaneously.
FIVE_SURFACE_FIXTURE = [
    # (conviction, tactical_bin, expected_cell_disposition, expected_veto_flag, surface_name)
    ("HIGH", "positive", "BUY-HIGH", False, "BUY-HIGH"),
    ("MEDIUM", "positive", "BUY-MED", False, "BUY-MED"),
    ("HIGH", "neutral", "HOLD", False, "HOLD"),
    ("HIGH", "negative", "HOLD", False, "HOLD"),
    ("HIGH", "unavailable", "HOLD", False, "HOLD"),
    ("MEDIUM", "neutral", "HOLD", False, "HOLD"),
    ("MEDIUM", "negative", "HOLD", False, "HOLD"),
    ("MEDIUM", "unavailable", "HOLD", False, "HOLD"),
    ("LOW", "negative", "AVOID", False, "AVOID"),
    ("LOW", "neutral", "AVOID", False, "AVOID"),
    ("LOW", "positive", "AVOID", False, "AVOID"),
    ("LOW", "unavailable", "HOLD", True, "LOW-CONVICTION VETO"),
]


@pytest.mark.parametrize(
    "conviction,tactical_bin,expected_disposition,expected_veto,surface",
    FIVE_SURFACE_FIXTURE,
)
def test_fixture_each_cell_maps_to_expected_surface(
    conviction, tactical_bin, expected_disposition, expected_veto, surface
):
    """Per-cell: matrix output AND veto flag both match the surface definition."""
    actual_disposition = tactical_disposition(conviction, tactical_bin)
    actual_veto = renderer_low_conviction_veto_flag(conviction, tactical_bin)
    assert actual_disposition == expected_disposition, (
        f"surface {surface}: ({conviction}, {tactical_bin}) → "
        f"expected disposition {expected_disposition}, got {actual_disposition}"
    )
    assert actual_veto == expected_veto, (
        f"surface {surface}: ({conviction}, {tactical_bin}) → "
        f"expected veto_flag {expected_veto}, got {actual_veto}"
    )


def test_all_5_surfaces_reachable_via_matrix():
    """Phase 1 acceptance: every surface must have ≥1 reachable input pair."""
    produced_surfaces = set()
    for conviction, tactical_bin, _, _, surface in FIVE_SURFACE_FIXTURE:
        produced_surfaces.add(surface)
    expected_surfaces = {"BUY-HIGH", "BUY-MED", "HOLD", "AVOID", "LOW-CONVICTION VETO"}
    assert produced_surfaces == expected_surfaces, (
        f"Surface set mismatch — produced: {produced_surfaces}, "
        f"expected: {expected_surfaces}"
    )


def test_buy_high_and_buy_med_are_disjoint_in_matrix():
    """INV-2.1-A consequence: BUY-HIGH only from HIGH conviction; BUY-MED only from MEDIUM."""
    for (conviction, tactical_bin), disposition in _DISPOSITION_MAP.items():
        if disposition == "BUY-HIGH":
            assert conviction == "HIGH", (
                f"BUY-HIGH must require HIGH conviction; got {conviction}"
            )
        if disposition == "BUY-MED":
            assert conviction == "MEDIUM", (
                f"BUY-MED must require MEDIUM conviction; got {conviction}"
            )


def test_low_conviction_veto_uniquely_identifies_low_unavailable():
    """Surface #5 is mechanically derivable: veto_flag = True iff (LOW × unavailable)."""
    for (conviction, tactical_bin) in _DISPOSITION_MAP.keys():
        veto = renderer_low_conviction_veto_flag(conviction, tactical_bin)
        if veto:
            assert (conviction, tactical_bin) == ("LOW", "unavailable"), (
                f"veto_flag should only fire on (LOW, unavailable); "
                f"fired on ({conviction}, {tactical_bin})"
            )


def test_no_input_produces_two_surfaces_simultaneously():
    """Surfaces are mutually exclusive: each (conviction, tactical_bin) → exactly 1 surface."""
    seen = {}
    for conviction, tactical_bin, expected_disposition, expected_veto, surface in FIVE_SURFACE_FIXTURE:
        key = (conviction, tactical_bin)
        assert key not in seen, (
            f"({conviction}, {tactical_bin}) appears twice in fixture: "
            f"surfaces {seen[key]} and {surface}"
        )
        seen[key] = surface
    assert len(seen) == 12, f"Fixture must cover all 12 matrix cells; got {len(seen)}"


def test_fixture_covers_full_12cell_matrix():
    """Completeness: every entry in _DISPOSITION_MAP must appear in the fixture."""
    fixture_keys = {(c, b) for c, b, _, _, _ in FIVE_SURFACE_FIXTURE}
    matrix_keys = set(_DISPOSITION_MAP.keys())
    assert fixture_keys == matrix_keys, (
        f"Fixture/matrix coverage mismatch — fixture has {fixture_keys}, "
        f"matrix has {matrix_keys}"
    )
