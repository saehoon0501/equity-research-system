"""Conviction flip-flop launch walkthrough reproducer (Section 7.3a #9).

Validates the Phase 4 Q7 hysteresis defense by walking the exact 6-cadence
oscillation sequence from the walkthrough through ``apply_hysteresis``:

  C-0: drift score 0.23 (clean) → HIGH (anchored)
  C-1: drift score 0.28 (above) → HIGH (cycle 1/2 of pending HIGH→MEDIUM)
  C-2: drift score 0.23 (clean) → HIGH (pending cancelled — revert)
  C-3: drift score 0.28 (above) → HIGH (cycle 1/2 of pending HIGH→MEDIUM)
  C-4: drift score 0.27 (above) → MEDIUM (cycle 2/2 confirmed → commit)
  C-5: drift score 0.23 (clean) → MEDIUM (cycle 1/2 of pending MEDIUM→HIGH)

Asserts:
  * Single-cycle excursions (C-1 alone) do NOT flip emitted bucket.
  * Reverts (C-1 → C-2) cancel pending transitions.
  * 2-cycle persistence (C-3 → C-4) commits.
  * Hysteresis is symmetric: MEDIUM→HIGH transition at C-5 is also pending,
    not committed instantly.
  * Over the 25-day window, only 1 committed flip vs naive 5.

Reproduces ``docs/superpowers/launch-walkthroughs/conviction-flip-flop.md``.
"""

from __future__ import annotations

import datetime as _dt

from src.supervisor.hysteresis import (
    CONVICTION_HIGH,
    CONVICTION_MEDIUM,
    HysteresisInputs,
    apply_hysteresis,
)


def _proposed_from_score(score: float, threshold: float = 0.25) -> str:
    """Naive verdict: drift score > threshold → MEDIUM, else HIGH."""
    return CONVICTION_MEDIUM if score > threshold else CONVICTION_HIGH


class TestFlipFlopSuppression:
    """Section 7.3a #9 — hysteresis defense against drift-score oscillation."""

    def test_walkthrough_full_6_cadence_sequence(self) -> None:
        """Walk all 6 cadences; assert only 1 committed transition."""
        # The walkthrough's drift-score sequence (5-day cadence).
        scores = [
            (_dt.date(2026, 4, 4),  0.23),  # C-0
            (_dt.date(2026, 4, 9),  0.28),  # C-1
            (_dt.date(2026, 4, 14), 0.23),  # C-2
            (_dt.date(2026, 4, 19), 0.28),  # C-3
            (_dt.date(2026, 4, 24), 0.27),  # C-4 (commit)
            (_dt.date(2026, 4, 29), 0.23),  # C-5
        ]

        prior_bucket: str | None = None
        prior_pending_target: str | None = None
        prior_pending_transition = False
        flip_history: list[_dt.date] = []
        emitted: list[str] = []
        committed_flips = 0

        for (when, score) in scores:
            proposed = _proposed_from_score(score)
            result = apply_hysteresis(
                HysteresisInputs(
                    proposed_bucket=proposed,
                    prior_bucket=prior_bucket,
                    prior_pending_target=prior_pending_target,
                    prior_pending_transition=prior_pending_transition,
                    flip_history_30d=flip_history,
                    now_date=when,
                )
            )
            emitted.append(result.effective_bucket)
            # Detect commit (effective bucket changed AND no longer pending).
            if (
                prior_bucket is not None
                and result.effective_bucket != prior_bucket
                and not result.pending_transition
            ):
                committed_flips += 1
            prior_bucket = result.effective_bucket
            prior_pending_target = result.pending_target
            prior_pending_transition = result.pending_transition
            flip_history = result.flip_history_30d

        # C-0: HIGH (new candidate commit)
        # C-1: HIGH (pending HIGH→MEDIUM, cycle 1/2)
        # C-2: HIGH (pending cancelled — proposed reverted to HIGH)
        # C-3: HIGH (pending HIGH→MEDIUM, cycle 1/2 again)
        # C-4: MEDIUM (cycle 2/2 → commit)
        # C-5: MEDIUM (pending MEDIUM→HIGH, cycle 1/2)
        assert emitted == [
            CONVICTION_HIGH,
            CONVICTION_HIGH,
            CONVICTION_HIGH,
            CONVICTION_HIGH,
            CONVICTION_MEDIUM,
            CONVICTION_MEDIUM,
        ], f"unexpected emitted sequence: {emitted}"

        assert committed_flips == 1, (
            f"expected 1 committed flip over 25 days, got {committed_flips}; "
            f"naive (no hysteresis) would produce 5"
        )

    def test_single_cycle_excursion_does_not_flip(self) -> None:
        """C-0 → C-1 alone: pending, not emitted-MEDIUM."""
        result = apply_hysteresis(
            HysteresisInputs(
                proposed_bucket=CONVICTION_MEDIUM,
                prior_bucket=CONVICTION_HIGH,
                prior_pending_target=None,
                prior_pending_transition=False,
                flip_history_30d=[],
                now_date=_dt.date(2026, 4, 9),
            )
        )
        # Cycle 1/2: still HIGH, pending MEDIUM queued.
        assert result.effective_bucket == CONVICTION_HIGH
        assert result.pending_transition
        assert result.pending_target == CONVICTION_MEDIUM

    def test_revert_cancels_pending_transition(self) -> None:
        """C-1 → C-2: proposed reverts to HIGH, pending cleared."""
        result = apply_hysteresis(
            HysteresisInputs(
                proposed_bucket=CONVICTION_HIGH,  # reverted
                prior_bucket=CONVICTION_HIGH,
                prior_pending_target=CONVICTION_MEDIUM,
                prior_pending_transition=True,  # was pending
                flip_history_30d=[],
                now_date=_dt.date(2026, 4, 14),
            )
        )
        # No transition (proposed == prior); pending cleared.
        assert result.effective_bucket == CONVICTION_HIGH
        assert not result.pending_transition
        assert result.pending_target is None

    def test_2_cycle_persistence_commits(self) -> None:
        """C-3 → C-4: same target proposed for 2 cycles → commit."""
        result = apply_hysteresis(
            HysteresisInputs(
                proposed_bucket=CONVICTION_MEDIUM,
                prior_bucket=CONVICTION_HIGH,
                prior_pending_target=CONVICTION_MEDIUM,
                prior_pending_transition=True,  # cycle 2/2
                flip_history_30d=[],
                now_date=_dt.date(2026, 4, 24),
            )
        )
        assert result.effective_bucket == CONVICTION_MEDIUM  # committed
        assert not result.pending_transition  # commit complete
        assert result.flip_count_30d == 1

    def test_hysteresis_is_symmetric_on_reverse_transition(self) -> None:
        """MEDIUM → HIGH reverse: also requires 2 cycles (no fast recovery)."""
        # C-5: MEDIUM is committed; proposed becomes HIGH (clean).
        result = apply_hysteresis(
            HysteresisInputs(
                proposed_bucket=CONVICTION_HIGH,
                prior_bucket=CONVICTION_MEDIUM,
                prior_pending_target=None,
                prior_pending_transition=False,
                flip_history_30d=[_dt.date(2026, 4, 24)],
                now_date=_dt.date(2026, 4, 29),
            )
        )
        # Cycle 1/2 of MEDIUM→HIGH: still emit MEDIUM.
        assert result.effective_bucket == CONVICTION_MEDIUM
        assert result.pending_transition
        assert result.pending_target == CONVICTION_HIGH

    def test_excessive_flips_freeze_at_MEDIUM(self) -> None:
        """>3 flips in 30d → auto-demote to MEDIUM + escalate M-2."""
        # 3 prior flips already on the books; this would be flip #4.
        prior_flips = [
            _dt.date(2026, 4, 5),
            _dt.date(2026, 4, 10),
            _dt.date(2026, 4, 15),
        ]
        result = apply_hysteresis(
            HysteresisInputs(
                proposed_bucket=CONVICTION_MEDIUM,
                prior_bucket=CONVICTION_HIGH,
                prior_pending_target=CONVICTION_MEDIUM,
                prior_pending_transition=True,
                flip_history_30d=prior_flips,
                now_date=_dt.date(2026, 4, 29),
            )
        )
        assert result.effective_bucket == CONVICTION_MEDIUM
        assert result.frozen_pending_review
        assert result.escalate_m2
        assert result.flip_count_30d > 3
