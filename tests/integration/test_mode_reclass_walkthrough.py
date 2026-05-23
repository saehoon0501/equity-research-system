"""Mode-reclass-race launch walkthrough reproducer (Section 7.3a #5).

Validates the pre-mortem cadence resolution rule under mode reclassification.
Per Section 4.9 Q3:

  When the proposed mode has a tighter cadence than the current mode, the
  resolved cadence floor = MIN(current_mode_cadence, proposed_mode_cadence).

  Tighter cadence wins. An older premortem fresh under the current mode but
  stale under the proposed mode forces a blocking premortem re-run.

The walkthrough scenario: PLTR Mode B' (90d cadence — actually 120d per
``CADENCE_DAYS_BY_MODE['B_prime']``) → C (60d). Last premortem 88 days ago.

  Under MAX(120, 60) = 120 → 88d still fresh → no premortem required (WRONG)
  Under MIN(120, 60) =  60 → 88d STALE under proposed mode → blocking ✓

The architectural lock under test is the MIN, not MAX, semantics.

Asserts:
  * MIN-based resolution flags 88d-old premortem as stale under B'→C reclass.
  * MAX-based resolution would (incorrectly) treat it as fresh.
  * No-reclass path uses ``current_mode_cadence`` only and 88d is fresh under B'.
  * Tighter-to-looser direction (C→B') still applies MIN — no premortem
    short-circuit.

Reproduces ``docs/superpowers/launch-walkthroughs/mode-reclass-race.md``.
"""

from __future__ import annotations

from src.premortem_scheduler import CADENCE_DAYS_BY_MODE


def resolve_cadence_floor(
    *, current_mode: str, proposed_mode: str | None
) -> int:
    """Section 4.9 Q3 cadence-resolution rule.

    No reclass: floor = current_mode_cadence.
    Reclass:    floor = MIN(current_mode_cadence, proposed_mode_cadence).

    Tighter cadence (smaller days) wins under reclassification.
    """
    cur = CADENCE_DAYS_BY_MODE[current_mode]
    if proposed_mode is None or proposed_mode == current_mode:
        return cur
    prop = CADENCE_DAYS_BY_MODE[proposed_mode]
    return min(cur, prop)


def is_premortem_stale(
    *, days_since: int, current_mode: str, proposed_mode: str | None
) -> bool:
    """Stale check: days_since >= resolved cadence floor."""
    floor = resolve_cadence_floor(
        current_mode=current_mode, proposed_mode=proposed_mode
    )
    return days_since >= floor


class TestModeReclassRace:
    """Section 7.3a #5 — premortem cadence resolution under reclass."""

    def test_b_prime_to_c_reclass_uses_MIN_resolves_to_60d(self) -> None:
        """B'→C reclass: MIN(120, 60)=60. 88d-old premortem stale."""
        floor = resolve_cadence_floor(
            current_mode="B_prime", proposed_mode="C"
        )
        assert floor == 60
        assert is_premortem_stale(
            days_since=88, current_mode="B_prime", proposed_mode="C"
        )

    def test_b_prime_to_c_reclass_NOT_max_semantics(self) -> None:
        """If MAX semantics were used, 88d under MAX(120,60)=120 would be fresh.

        This regression-tests against an alternative implementation.
        """
        # MAX(120, 60) would be 120; 88 < 120 → "fresh" (WRONG).
        # MIN(120, 60) = 60; 88 >= 60 → "stale" (CORRECT).
        max_floor = max(
            CADENCE_DAYS_BY_MODE["B_prime"], CADENCE_DAYS_BY_MODE["C"]
        )
        assert max_floor == 120
        assert 88 < max_floor  # would be fresh under MAX (incorrect)
        # The actual implementation uses MIN, so the result is stale.
        floor = resolve_cadence_floor(
            current_mode="B_prime", proposed_mode="C"
        )
        assert floor != max_floor
        assert floor == 60

    def test_no_reclass_uses_current_cadence_only(self) -> None:
        """No reclass: 88d under B' (120d cadence) is fresh."""
        floor = resolve_cadence_floor(
            current_mode="B_prime", proposed_mode=None
        )
        assert floor == 120
        assert not is_premortem_stale(
            days_since=88, current_mode="B_prime", proposed_mode=None
        )

    def test_same_mode_proposal_is_no_op(self) -> None:
        """current==proposed → MIN(x, x) = x; no change."""
        floor = resolve_cadence_floor(
            current_mode="B_prime", proposed_mode="B_prime"
        )
        assert floor == CADENCE_DAYS_BY_MODE["B_prime"]

    def test_b_to_b_prime_reclass_min_semantics(self) -> None:
        """B(180)→B'(120) reclass: MIN=120 — tighter wins."""
        floor = resolve_cadence_floor(
            current_mode="B", proposed_mode="B_prime"
        )
        assert floor == 120

    def test_c_to_b_prime_loosening_reclass_uses_MIN(self) -> None:
        """Loosening direction (C→B'): MIN(60, 120)=60 — keep tighter floor.

        This is the asymmetry-defense: even when reclassifying to a LOOSER
        mode, the cadence floor must remain at the tighter (current) value
        until a fresh premortem under the new (looser) standards is run.
        Otherwise an operator could downgrade C→B' and instantly avoid an
        overdue C-cadence premortem.
        """
        floor = resolve_cadence_floor(
            current_mode="C", proposed_mode="B_prime"
        )
        assert floor == 60
        # 75d under MIN(60, 120)=60 → stale; under naive proposed-only it
        # would be 75 < 120 → fresh (WRONG).
        assert is_premortem_stale(
            days_since=75, current_mode="C", proposed_mode="B_prime"
        )

    def test_walkthrough_88d_b_prime_to_c_blocks(self) -> None:
        """The exact walkthrough case: 88d-old premortem, B'→C → STALE/BLOCK."""
        assert is_premortem_stale(
            days_since=88, current_mode="B_prime", proposed_mode="C"
        )
        # Verify the floor.
        floor = resolve_cadence_floor(
            current_mode="B_prime", proposed_mode="C"
        )
        assert floor == 60, "Section 4.9 Q3: MIN(B'=120, C=60) = 60"

    def test_below_floor_is_fresh(self) -> None:
        """Sanity: 30d-old premortem on B'→C → fresh (30 < MIN(120,60)=60)."""
        assert not is_premortem_stale(
            days_since=30, current_mode="B_prime", proposed_mode="C"
        )
