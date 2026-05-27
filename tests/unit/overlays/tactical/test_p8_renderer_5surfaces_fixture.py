"""G-CHECK-3 fixture: tactical-overlay MAPPING coverage gate (v2 — scope corrected).

v1 → v2 changes (iteration-1 reviewer catches):
- Scope claim corrected: this fixture tests the **overlay mapping function**, NOT the
  pm-supervisor markdown renderer. The renderer is a markdown agent spec, not
  executable code; verifying it requires a separate golden-file/output-snapshot test
  not covered here. v1 over-claimed "renderer coverage."
- INV-2.1-A direct assertion added (one cheap line): the matrix values must be a
  subset of {BUY-HIGH, BUY-MED, HOLD, AVOID}, never containing canonical
  {BUY, TRIM, SELL}.
- Public accessor used (`overlay.disposition_map()` instead of `_DISPOSITION_MAP`)
  to decouple the test from private-name internals.

Per docs/phase_1_acceptance_spec.md, Section 2.1 v5 requires the renderer to be able
to produce 5 distinct surfaces:
  1. BUY-HIGH         (HIGH × positive)
  2. BUY-MED          (MEDIUM × positive)
  3. HOLD             (any of 8 matrix cells routing to HOLD without veto)
  4. AVOID            (LOW × {negative, neutral, positive})
  5. LOW-CONVICTION VETO (LOW × unavailable — renders as HOLD + veto flag)

This fixture verifies that each surface is reachable through the matrix mapping AND
that the LOW-CONVICTION VETO predicate is mechanically identifiable from inputs.
Mutation resistance: expected dispositions are HAND-WRITTEN LITERALS in the fixture
(NOT derived from the matrix), so a swap of (HIGH, positive) ↔ (MEDIUM, positive) in
the matrix would flip the function output and fail the per-cell assertion.
"""
from __future__ import annotations

import pytest

from src.overlays.tactical.overlay import disposition_map, tactical_disposition


def renderer_low_conviction_veto_flag(conviction: str, tactical_bin: str) -> bool:
    """Mechanical predicate for surface #5.

    The renderer surfaces the veto annotation when the (conviction, tactical_bin)
    input pair produces HOLD via the LOW row. Distinct from generic HOLD.

    Note: this predicate reads the matrix at call time. The per-cell fixture rows
    below include LITERAL expected_veto values, so a mutation of either the matrix
    OR this predicate would be caught by the literal assertions.
    """
    return conviction == "LOW" and disposition_map()[(conviction, tactical_bin)] == "HOLD"


# Fixture: each row encodes the expected (disposition, veto_flag) per cell as
# hand-written literals. Mutation of either matrix or predicate fails an assertion.
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
    """Per-cell: matrix output AND veto flag both match the surface definition.

    Expected values are hand-written literals; matrix mutations break the
    disposition assertion and predicate mutations break the veto assertion.
    """
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
    for _, _, _, _, surface in FIVE_SURFACE_FIXTURE:
        produced_surfaces.add(surface)
    expected_surfaces = {"BUY-HIGH", "BUY-MED", "HOLD", "AVOID", "LOW-CONVICTION VETO"}
    assert produced_surfaces == expected_surfaces, (
        f"Surface set mismatch — produced: {produced_surfaces}, "
        f"expected: {expected_surfaces}"
    )


def test_buy_high_and_buy_med_are_disjoint_in_matrix():
    """INV-2.1-A consequence: BUY-HIGH only from HIGH conviction; BUY-MED only from MEDIUM."""
    for (conviction, _tactical_bin), disposition in disposition_map().items():
        if disposition == "BUY-HIGH":
            assert conviction == "HIGH", (
                f"BUY-HIGH must require HIGH conviction; got {conviction}"
            )
        if disposition == "BUY-MED":
            assert conviction == "MEDIUM", (
                f"BUY-MED must require MEDIUM conviction; got {conviction}"
            )


def test_inv_2_1_a_matrix_values_disjoint_from_canonical_enum():
    """v2 NEW (iteration-1 catch): direct assertion that matrix outputs never contain
    canonical summary_code values {BUY, TRIM, SELL}. Cheap defense against future
    typos that swap BUY-HIGH for BUY etc.
    """
    matrix_values = set(disposition_map().values())
    tactical_enum = {"BUY-HIGH", "BUY-MED", "HOLD", "AVOID"}
    canonical_enum = {"BUY", "TRIM", "SELL"}
    assert matrix_values <= tactical_enum, (
        f"Matrix contains non-tactical values: {matrix_values - tactical_enum}"
    )
    assert not (matrix_values & canonical_enum), (
        f"INV-2.1-A violation — matrix contains canonical enum values: "
        f"{matrix_values & canonical_enum}"
    )


def test_low_conviction_veto_uniquely_identifies_low_unavailable():
    """Surface #5 is mechanically derivable: veto_flag = True iff (LOW × unavailable)."""
    for (conviction, tactical_bin) in disposition_map().keys():
        veto = renderer_low_conviction_veto_flag(conviction, tactical_bin)
        if veto:
            assert (conviction, tactical_bin) == ("LOW", "unavailable"), (
                f"veto_flag should only fire on (LOW, unavailable); "
                f"fired on ({conviction}, {tactical_bin})"
            )


def test_no_input_produces_two_surfaces_simultaneously():
    """Surfaces are mutually exclusive: each (conviction, tactical_bin) → exactly 1 surface."""
    seen: dict[tuple[str, str], str] = {}
    for conviction, tactical_bin, _, _, surface in FIVE_SURFACE_FIXTURE:
        key = (conviction, tactical_bin)
        assert key not in seen, (
            f"({conviction}, {tactical_bin}) appears twice in fixture: "
            f"surfaces {seen[key]} and {surface}"
        )
        seen[key] = surface
    assert len(seen) == 12, f"Fixture must cover all 12 matrix cells; got {len(seen)}"


def test_fixture_covers_full_12cell_matrix():
    """Completeness: every entry in the matrix must appear in the fixture."""
    fixture_keys = {(c, b) for c, b, _, _, _ in FIVE_SURFACE_FIXTURE}
    matrix_keys = set(disposition_map().keys())
    assert fixture_keys == matrix_keys, (
        f"Fixture/matrix coverage mismatch — fixture has {fixture_keys}, "
        f"matrix has {matrix_keys}"
    )


def test_matrix_cardinality_is_12():
    """iter-2 nit fold: catches accidental row deletion/duplication in matrix."""
    assert len(disposition_map()) == 12, (
        f"Matrix must have exactly 12 cells (3 conviction × 4 tactical_bin); "
        f"got {len(disposition_map())}"
    )


def test_matrix_keys_are_exact_cartesian_product():
    """iter-2 nit fold: catches typos in conviction/tactical_bin tokens that would
    silently shift behavior (e.g., 'MED' instead of 'MEDIUM', 'pos' instead of
    'positive')."""
    expected_convictions = {"HIGH", "MEDIUM", "LOW"}
    expected_bins = {"positive", "neutral", "negative", "unavailable"}
    expected_keys = {(c, b) for c in expected_convictions for b in expected_bins}
    assert set(disposition_map().keys()) == expected_keys, (
        f"Matrix keys must be exactly Cartesian product of "
        f"{expected_convictions} × {expected_bins}; "
        f"unexpected: {set(disposition_map().keys()) - expected_keys}, "
        f"missing: {expected_keys - set(disposition_map().keys())}"
    )
