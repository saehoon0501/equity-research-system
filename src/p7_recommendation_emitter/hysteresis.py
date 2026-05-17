"""P7 conviction hysteresis — Section 4.6 Phase 4 Q7.

Per v3 spec lines 631-634::

    Conviction hysteresis (Phase 4 Q7):
      - Conviction transition (any direction) requires the transitioning
        condition to persist 2 consecutive cadence cycles
      - Per-name `conviction_flip_count_30d` tracked
      - >3 flips in 30 days → name escalates to operator review (M-2 system
        event); auto-demote to MEDIUM and freeze until reviewed

This module is DETERMINISTIC. Inputs:
  * proposed_bucket: what the deterministic rollup says NOW.
  * prior_bucket: what was emitted last cycle (None for new candidates).
  * prior_pending_target: bucket queued from previous cycle (state machine).
  * flip_history_30d: list of dates of conviction flips in last 30d.

Output:
  * effective_bucket: bucket the recommendation should report (post-hysteresis).
  * pending_transition: state-machine flag.
  * pending_target: bucket queued for next cycle (None if not pending).
  * flip_count_30d: count of flips in trailing 30 days.
  * frozen_pending_review: True when >3 flips → auto-demote+freeze fired.
  * escalate_m2: True when >3 flips → fire M-2 system event.

Spec ambiguity resolution + DECISION LOCKS (Section 4.6 Phase 4 Q7):
  * "2 consecutive cadence cycles" — interpreted as: a transition is COMMITTED
    only on the second cycle that proposes the same target. First cycle:
    pending_transition=true, pending_target=<new>; second cycle (still same
    proposed_bucket): commit. If proposed bucket changes between cycle 1
    and cycle 2, pending state resets (target replaced or cleared).
  * **Cycle counting on mid-stream pending_target change (Case 4)**: when
    the proposed bucket changes mid-stream (e.g., MEDIUM→HIGH was queued,
    then MEDIUM→LOW is proposed), the new target replaces the old and
    the 2-cycle clock RESTARTS — i.e., the change cycle counts as
    cycle 1/2 of the NEW transition, not cycle 2/2 of the prior. This is
    the permissive interpretation: it requires real persistence on the
    new direction before committing rather than treating any persisted
    "cycle 2 with a different target" as confirmation of an unrelated
    transition. Locked here per Phase 4 Q7 subagent decision; alternative
    interpretation (commit immediately on cycle-2 regardless of target
    match) was rejected as defeating the persistence guarantee.
  * Freeze is at MEDIUM (the conservative middle bucket).
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Optional, Sequence


CONVICTION_HIGH = "HIGH"
CONVICTION_MEDIUM = "MEDIUM"
CONVICTION_LOW = "LOW"
_VALID_BUCKETS: tuple[str, ...] = (CONVICTION_HIGH, CONVICTION_MEDIUM, CONVICTION_LOW)


FLIP_FREQ_THRESHOLD: int = 3  # >3 flips in 30 days → escalate
FLIP_WINDOW_DAYS: int = 30


@dataclass
class HysteresisInputs:
    """Per-cycle inputs for the hysteresis state machine."""

    proposed_bucket: str  # output of conviction_rollup.roll_up_conviction
    prior_bucket: Optional[str] = None  # last emitted bucket (None = new)
    prior_pending_target: Optional[str] = None  # bucket queued last cycle
    prior_pending_transition: bool = False  # was last cycle pending a flip?
    flip_history_30d: Sequence[_dt.date] = ()  # dates of flips
    now_date: Optional[_dt.date] = None  # default = today UTC

    def effective_now(self) -> _dt.date:
        return self.now_date or _dt.datetime.now(_dt.timezone.utc).date()


@dataclass
class HysteresisResult:
    """Output of one hysteresis evaluation cycle."""

    effective_bucket: str
    pending_transition: bool
    pending_target: Optional[str]
    flip_count_30d: int
    flip_history_30d: list[_dt.date]
    frozen_pending_review: bool
    escalate_m2: bool
    rationale: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _trim_window(
    flip_history_30d: Sequence[_dt.date], now: _dt.date
) -> list[_dt.date]:
    """Keep only flips within trailing 30 days."""
    cutoff = now - _dt.timedelta(days=FLIP_WINDOW_DAYS)
    return [d for d in flip_history_30d if d > cutoff]


def _validate_bucket(bucket: str, *, allow_none: bool = False) -> None:
    if bucket is None and allow_none:
        return
    if bucket not in _VALID_BUCKETS:
        raise ValueError(
            f"bucket {bucket!r} not in {_VALID_BUCKETS}"
        )


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------


def apply_hysteresis(inp: HysteresisInputs) -> HysteresisResult:
    """Apply Phase 4 Q7 conviction hysteresis.

    State machine (per cycle):

      Case 0 — new candidate (prior_bucket is None):
        commit proposed immediately; no flip tracked.

      Case 1 — proposed == prior:
        no transition needed. Clear any pending state.

      Case 2 — proposed != prior, prior_pending_transition=False:
        Cycle 1 of a transition. effective stays prior; queue pending.

      Case 3 — proposed != prior, prior_pending_transition=True,
              proposed == prior_pending_target:
        Cycle 2 confirms. Commit transition. Record flip.

      Case 4 — proposed != prior, prior_pending_transition=True,
              proposed != prior_pending_target:
        Pending target changed mid-stream. Restart 2-cycle clock with the
        new proposed bucket as the queue target. effective stays prior.

      Post-commit (Case 3): if flip_count_30d > 3 → freeze@MEDIUM + escalate.
    """
    _validate_bucket(inp.proposed_bucket)
    _validate_bucket(inp.prior_bucket, allow_none=True)
    _validate_bucket(inp.prior_pending_target, allow_none=True)

    now = inp.effective_now()
    flips = _trim_window(inp.flip_history_30d, now)

    # Case 0: new candidate — commit immediately.
    if inp.prior_bucket is None:
        return HysteresisResult(
            effective_bucket=inp.proposed_bucket,
            pending_transition=False,
            pending_target=None,
            flip_count_30d=len(flips),
            flip_history_30d=list(flips),
            frozen_pending_review=False,
            escalate_m2=False,
            rationale=(
                "new candidate: no prior bucket → commit proposed bucket "
                f"({inp.proposed_bucket}) immediately"
            ),
        )

    # Case 1: no change.
    if inp.proposed_bucket == inp.prior_bucket:
        return HysteresisResult(
            effective_bucket=inp.prior_bucket,
            pending_transition=False,
            pending_target=None,
            flip_count_30d=len(flips),
            flip_history_30d=list(flips),
            frozen_pending_review=False,
            escalate_m2=False,
            rationale=(
                f"no transition: proposed == prior == {inp.prior_bucket}; "
                "clear any pending state"
            ),
        )

    # Case 2: cycle 1 of new transition.
    if not inp.prior_pending_transition:
        return HysteresisResult(
            effective_bucket=inp.prior_bucket,
            pending_transition=True,
            pending_target=inp.proposed_bucket,
            flip_count_30d=len(flips),
            flip_history_30d=list(flips),
            frozen_pending_review=False,
            escalate_m2=False,
            rationale=(
                f"transition cycle 1/2: prior={inp.prior_bucket}, "
                f"proposed={inp.proposed_bucket}; queued, awaiting "
                "confirmation next cycle (Phase 4 Q7 2-cycle persistence)"
            ),
        )

    # Case 3: cycle 2 confirms.
    if inp.proposed_bucket == inp.prior_pending_target:
        flips_with_new = list(flips) + [now]
        flip_count = len(flips_with_new)
        if flip_count > FLIP_FREQ_THRESHOLD:
            return HysteresisResult(
                effective_bucket=CONVICTION_MEDIUM,
                pending_transition=False,
                pending_target=None,
                flip_count_30d=flip_count,
                flip_history_30d=flips_with_new,
                frozen_pending_review=True,
                escalate_m2=True,
                rationale=(
                    f">{FLIP_FREQ_THRESHOLD} flips in 30 days "
                    f"(count={flip_count}) → escalate operator review "
                    "(M-2 system event); auto-demote to MEDIUM and freeze "
                    "(Phase 4 Q7)"
                ),
            )
        return HysteresisResult(
            effective_bucket=inp.proposed_bucket,
            pending_transition=False,
            pending_target=None,
            flip_count_30d=flip_count,
            flip_history_30d=flips_with_new,
            frozen_pending_review=False,
            escalate_m2=False,
            rationale=(
                f"transition cycle 2/2 confirmed: {inp.prior_bucket} → "
                f"{inp.proposed_bucket}; flip recorded "
                f"(count_30d={flip_count})"
            ),
        )

    # Case 4: pending target changed mid-stream.
    # DECISION LOCK (Phase 4 Q7): the new proposed bucket replaces the
    # old pending_target and the 2-cycle clock RESTARTS — this cycle
    # counts as cycle 1/2 of the NEW transition. We do NOT commit the
    # old pending_target (which would defeat persistence) nor commit the
    # new proposed_bucket (which would defeat the 2-cycle requirement).
    # See module docstring for the rejected alternative interpretation.
    return HysteresisResult(
        effective_bucket=inp.prior_bucket,
        pending_transition=True,
        pending_target=inp.proposed_bucket,
        flip_count_30d=len(flips),
        flip_history_30d=list(flips),
        frozen_pending_review=False,
        escalate_m2=False,
        rationale=(
            f"pending target changed: was {inp.prior_pending_target}, now "
            f"{inp.proposed_bucket}; restart 2-cycle clock (Phase 4 Q7 lock)"
        ),
    )


__all__ = [
    "FLIP_FREQ_THRESHOLD",
    "FLIP_WINDOW_DAYS",
    "HysteresisInputs",
    "HysteresisResult",
    "apply_hysteresis",
]
