"""Task 3.2 — observable proof for ``src.survival.gate.admit`` (the order veto).

Proves THIS task's observable + the **catastrophe guard** (classify exit-vs-open
by *effect on the held position*, never by the upstream disposition label). The
broad admission suite is task 5.2; here we prove the lexicographic walk, the
first-binding short-circuit, the exit short-circuit (fail-toward-flat), the
reject-never-resize size breach, the missing-SL reject, the kill-switch
freshness (per-call op-state read), and the fail-toward-open ambiguity guards.

What this proves (R2, R4, R5, R9, R11.1):

  * **Lexicographic walk** in the fixed order — kill_switch → safe_mode →
    not_activated → universe → entry_exclusion → margin_distance → size_limit →
    missing_sl — stopping at and reporting the **first** binding constraint via
    ``binding_constraint`` (R2.1/R2.4, R11.3). There is NO halt step (R7) and
    ``funding_cap`` is NEVER emitted here (it is task 4.2's capitalization-time
    precondition).
  * **Exit-vs-open by EFFECT, not label** (P7 — never trust ``intent``): an order
    short-circuits to ALLOW *iff* it is opposite-side to a single held position
    in the same symbol AND its volume ≤ that position's held volume (net-reducing,
    no side flip). A ``SELL`` label on an unheld name (opens a short) or whose
    volume exceeds the held long (flatten-then-flip) is an **open** and takes the
    full walk — proving the label alone never short-circuits (the catastrophe
    guard).
  * **Fail-toward-flat:** a true exit ALLOWs even under an engaged kill switch,
    under safe-mode HALT_NEW/FLATTEN, and with ``stop_loss=None`` — the exit
    short-circuit runs BEFORE every walk step including the missing-SL check.
  * **Fail-toward-open on ambiguity:** an unrecognized ``direction`` value, or
    multiple held positions in the same symbol, never short-circuits as an exit.
  * **Reject-never-resize (R2.3):** a size breach returns REJECT +
    ``advisory_max_volume == per_order_size_max`` and does not mutate the order.
  * **Reject-leaning OrderEvaluation defaults (fail-toward-not-adding):** a
    missing screen never defaults to in-universe / not-excluded / zero-margin.
  * **Kill-switch freshness (R9):** op-state is read per call — toggling it
    between calls flips the result, proving it is not pinned.
  * **Determinism (R11.1):** identical inputs → identical ``AdmitDecision``.

Pure unit test — no LLM / MCP / DB (P14, R11.2).
"""

from __future__ import annotations

import dataclasses
import importlib

import pytest

from src.survival.params import DEFAULTS
from src.survival.types import (
    AccountState,
    OperationalState,
    Position,
    ProposedOrder,
)


# --------------------------------------------------------------------------- #
# Helpers.                                                                     #
# --------------------------------------------------------------------------- #

def _gate_module():
    return importlib.import_module("src.survival.gate")


def _eval_module():
    """``OrderEvaluation`` lives in ``types`` (the daemon-seam input contract)."""
    return importlib.import_module("src.survival.types")


def _admit(**kwargs):
    return _gate_module().admit(**kwargs)


def _order_evaluation(**kwargs):
    return _eval_module().OrderEvaluation(**kwargs)


def _account(*, activated: bool = True, positions=None,
             equity: float = 100_000.0, used_margin: float = 1_000.0) -> AccountState:
    """A synthetic, healthy AccountState (huge margin level so the margin step
    never binds unless a test deliberately starves it via the evaluation)."""
    return AccountState(
        activated=activated,
        equity=equity,
        used_margin=used_margin,
        free_margin=equity - used_margin,
        margin_level=999_999.0,
        balance=equity,
        stop_out_level=50.0,
        positions=list(positions or []),
    )


def _op(*, kill_switch: bool = False, grade: str = "NONE") -> OperationalState:
    return OperationalState(
        kill_switch_engaged=kill_switch,
        safe_mode_grade=grade,
        entered_at=None,
        triggered_by=None,
    )


def _position(*, symbol: str = "AAPL", direction: str = "LONG",
              volume: float = 10.0, position_id: str = "p1") -> Position:
    return Position(
        position_id=position_id,
        symbol=symbol,
        direction=direction,
        volume=volume,
        avg_open_price=100.0,
        used_margin=500.0,
        unrealized_pnl=0.0,
    )


def _order(*, symbol: str = "AAPL", intent: str = "BUY", direction: str = "LONG",
           volume: float = 0.5, stop_loss=90.0) -> ProposedOrder:
    return ProposedOrder(
        symbol=symbol,
        intent=intent,
        direction=direction,
        volume=volume,
        stop_loss=stop_loss,
    )


def _params(**overrides):
    return dataclasses.replace(DEFAULTS, **overrides)


def _clean_eval(**overrides):
    """An ``OrderEvaluation`` that passes universe/exclusion/margin for an open
    (the opposite of the reject-leaning defaults) so tests can isolate a single
    binding constraint."""
    base = dict(additional_used_margin=0.0, in_universe=True, is_excluded=False)
    base.update(overrides)
    return _order_evaluation(**base)


# --------------------------------------------------------------------------- #
# 1. Kill switch — rejects every open, admits every true exit (the observable).#
# --------------------------------------------------------------------------- #

def test_kill_switch_rejects_open():
    """An open (BUY/LONG on an unheld name) REJECTs ``kill_switch``."""
    d = _admit(
        order=_order(intent="BUY", direction="LONG", volume=0.5),
        state=_account(),
        op_state=_op(kill_switch=True),
        params=_params(),
        clock=None,
        evaluation=_clean_eval(),
    )
    assert d.decision == "REJECT"
    assert d.binding_constraint == "kill_switch"


def test_kill_switch_admits_true_exit():
    """A true exit (opposite-side, volume ≤ held) ALLOWs even under kill switch."""
    held = _position(symbol="AAPL", direction="LONG", volume=10.0)
    exit_order = _order(symbol="AAPL", intent="SELL", direction="SHORT", volume=10.0)
    d = _admit(
        order=exit_order,
        state=_account(positions=[held]),
        op_state=_op(kill_switch=True),
        params=_params(),
        clock=None,
        evaluation=_order_evaluation(),  # all-reject defaults — exit still ALLOWs
    )
    assert d.decision == "ALLOW"
    assert d.binding_constraint is None


# --------------------------------------------------------------------------- #
# 2. CATASTROPHE GUARD — a SELL label whose EFFECT is an open does NOT          #
#    short-circuit; it is rejected under the kill switch.                       #
# --------------------------------------------------------------------------- #

def test_sell_on_unheld_name_is_an_open_rejected_under_kill_switch():
    """``intent='SELL'`` on an UNHELD name opens a short → full walk → REJECT."""
    d = _admit(
        order=_order(symbol="MSFT", intent="SELL", direction="SHORT", volume=1.0),
        state=_account(positions=[]),  # nothing held in MSFT
        op_state=_op(kill_switch=True),
        params=_params(),
        clock=None,
        evaluation=_clean_eval(),
    )
    assert d.decision == "REJECT"
    assert d.binding_constraint == "kill_switch"


def test_sell_exceeding_held_long_is_flip_open_rejected_under_kill_switch():
    """A SHORT order whose volume EXCEEDS the held LONG (flatten-then-flip) is a
    net-new short → an open → REJECT under the kill switch (label is ignored)."""
    held = _position(symbol="AAPL", direction="LONG", volume=10.0)
    d = _admit(
        order=_order(symbol="AAPL", intent="SELL", direction="SHORT", volume=15.0),
        state=_account(positions=[held]),
        op_state=_op(kill_switch=True),
        params=_params(),
        clock=None,
        evaluation=_clean_eval(),
    )
    assert d.decision == "REJECT"
    assert d.binding_constraint == "kill_switch"


def test_same_side_add_is_an_open_rejected_under_kill_switch():
    """A same-side add (LONG order on a held LONG) increases exposure → open."""
    held = _position(symbol="AAPL", direction="LONG", volume=10.0)
    d = _admit(
        order=_order(symbol="AAPL", intent="BUY", direction="LONG", volume=1.0),
        state=_account(positions=[held]),
        op_state=_op(kill_switch=True),
        params=_params(),
        clock=None,
        evaluation=_clean_eval(),
    )
    assert d.decision == "REJECT"
    assert d.binding_constraint == "kill_switch"


# --------------------------------------------------------------------------- #
# 3. True exit short-circuits BEFORE the missing-SL check (fail-toward-flat).   #
# --------------------------------------------------------------------------- #

def test_true_exit_with_no_stop_loss_is_allowed():
    """A true exit with ``stop_loss=None`` ALLOWs — the exit short-circuit runs
    BEFORE the mandatory-SL check (getting flat must always be possible)."""
    held = _position(symbol="AAPL", direction="LONG", volume=10.0)
    d = _admit(
        order=_order(symbol="AAPL", intent="SELL", direction="SHORT",
                     volume=8.0, stop_loss=None),
        state=_account(positions=[held]),
        op_state=_op(),
        params=_params(),
        clock=None,
        evaluation=_order_evaluation(),
    )
    assert d.decision == "ALLOW"


def test_true_exit_allowed_under_safe_mode_flatten():
    """Exit short-circuits even when safe-mode is at FLATTEN (halts new entries)."""
    held = _position(symbol="AAPL", direction="SHORT", volume=5.0)
    d = _admit(
        order=_order(symbol="AAPL", intent="BUY", direction="LONG", volume=5.0),
        state=_account(positions=[held]),
        op_state=_op(grade="FLATTEN"),
        params=_params(),
        clock=None,
        evaluation=_order_evaluation(),
    )
    assert d.decision == "ALLOW"


def test_true_exit_allowed_under_kill_switch_and_safe_mode_simultaneously():
    """5.2 catastrophe guard — a TRUE net-reducing exit is ADMITTED even with the
    kill switch engaged AND safe-mode at FLATTEN at the SAME time, with no
    stop-loss and all-reject OrderEvaluation defaults. This is strictly stronger
    than the kill-only and safe-mode-only exit cases above: it proves the exit
    short-circuit runs ahead of EVERY walk step simultaneously (fail-toward-flat —
    getting flat must always be possible). A regression that moved the
    short-circuit after any walk step would reject this order."""
    held = _position(symbol="AAPL", direction="LONG", volume=10.0)
    d = _admit(
        order=_order(symbol="AAPL", intent="SELL", direction="SHORT",
                     volume=10.0, stop_loss=None),
        state=_account(positions=[held]),
        op_state=_op(kill_switch=True, grade="FLATTEN"),
        params=_params(),
        clock=None,
        evaluation=_order_evaluation(),  # all-reject defaults — exit still ALLOWs
    )
    assert d.decision == "ALLOW"
    assert d.binding_constraint is None


# --------------------------------------------------------------------------- #
# 4. Safe-mode — rank ≥ HALT_NEW halts opens; TIGHTEN does not.                 #
# --------------------------------------------------------------------------- #

def test_safe_mode_halt_new_rejects_open():
    d = _admit(
        order=_order(),
        state=_account(),
        op_state=_op(grade="HALT_NEW"),
        params=_params(),
        clock=None,
        evaluation=_clean_eval(),
    )
    assert d.decision == "REJECT"
    assert d.binding_constraint == "safe_mode"


def test_safe_mode_flatten_rejects_open():
    d = _admit(
        order=_order(),
        state=_account(),
        op_state=_op(grade="FLATTEN"),
        params=_params(),
        clock=None,
        evaluation=_clean_eval(),
    )
    assert d.decision == "REJECT"
    assert d.binding_constraint == "safe_mode"


def test_safe_mode_tighten_does_not_block_open():
    """TIGHTEN (rank 1) is the lighter response — opens proceed normally."""
    d = _admit(
        order=_order(),
        state=_account(),
        op_state=_op(grade="TIGHTEN"),
        params=_params(),
        clock=None,
        evaluation=_clean_eval(),
    )
    assert d.decision == "ALLOW"


# --------------------------------------------------------------------------- #
# 5. Account activation.                                                        #
# --------------------------------------------------------------------------- #

def test_not_activated_rejects_open():
    d = _admit(
        order=_order(),
        state=_account(activated=False),
        op_state=_op(),
        params=_params(),
        clock=None,
        evaluation=_clean_eval(),
    )
    assert d.decision == "REJECT"
    assert d.binding_constraint == "not_activated"


# --------------------------------------------------------------------------- #
# 6. Universe.                                                                  #
# --------------------------------------------------------------------------- #

def test_off_universe_rejects_open():
    d = _admit(
        order=_order(),
        state=_account(),
        op_state=_op(),
        params=_params(),
        clock=None,
        evaluation=_clean_eval(in_universe=False),
    )
    assert d.decision == "REJECT"
    assert d.binding_constraint == "universe"


def test_unknown_universe_defaults_to_off_universe_reject():
    """The reject-leaning default: an OrderEvaluation with no in_universe given
    rejects ``universe`` (a missing screen never defaults to in-universe)."""
    d = _admit(
        order=_order(),
        state=_account(),
        op_state=_op(),
        params=_params(),
        clock=None,
        # additional_used_margin set so margin does not bind first; universe
        # and exclusion left to their reject-leaning defaults.
        evaluation=_order_evaluation(additional_used_margin=0.0),
    )
    assert d.decision == "REJECT"
    assert d.binding_constraint == "universe"


# --------------------------------------------------------------------------- #
# 7. Ex-ante exclusion (only when enabled).                                     #
# --------------------------------------------------------------------------- #

def test_exclusion_rejects_when_enabled_and_flagged():
    d = _admit(
        order=_order(),
        state=_account(),
        op_state=_op(),
        params=_params(exclusion_enabled=True),
        clock=None,
        evaluation=_clean_eval(is_excluded=True),
    )
    assert d.decision == "REJECT"
    assert d.binding_constraint == "entry_exclusion"


def test_exclusion_ignored_when_disabled():
    """With exclusion disabled, a flagged symbol passes the exclusion step."""
    d = _admit(
        order=_order(),
        state=_account(),
        op_state=_op(),
        params=_params(exclusion_enabled=False),
        clock=None,
        evaluation=_clean_eval(is_excluded=True),
    )
    assert d.decision == "ALLOW"


def test_unknown_exclusion_defaults_to_flagged_when_enabled():
    """Reject-leaning default: unknown is_excluded → flagged → reject when
    exclusion is enabled (a missing screen never defaults to not-excluded)."""
    d = _admit(
        order=_order(),
        state=_account(),
        op_state=_op(),
        params=_params(exclusion_enabled=True),
        clock=None,
        evaluation=_order_evaluation(additional_used_margin=0.0, in_universe=True),
    )
    assert d.decision == "REJECT"
    assert d.binding_constraint == "entry_exclusion"


# --------------------------------------------------------------------------- #
# 8. Projected margin distance.                                                 #
# --------------------------------------------------------------------------- #

def test_margin_breach_rejects_open():
    """An add whose projected margin level drops at/below the safe-mode buffer
    REJECTs ``margin_distance``."""
    # equity 100k, used 1k → current level 10000%. Add 200k margin → projected
    # 100k/201k×100 ≈ 49.75% ≤ buffer 100 → breach.
    d = _admit(
        order=_order(),
        state=_account(equity=100_000.0, used_margin=1_000.0),
        op_state=_op(),
        params=_params(stop_out_level_pct=50.0, safe_mode_buffer_pct=100.0),
        clock=None,
        evaluation=_clean_eval(additional_used_margin=200_000.0),
    )
    assert d.decision == "REJECT"
    assert d.binding_constraint == "margin_distance"


def test_margin_step_keys_off_buffer_not_stop_out():
    """DISCRIMINATING: a projected level STRICTLY BETWEEN stop-out and buffer
    must REJECT. With stop_out=50 / buffer=100, projected == 75 breaches the
    buffer (≤100) but NOT stop-out (≤50). Buffer-keyed code (correct) rejects; a
    regression to stop-out-keyed code would (wrongly) ALLOW. This locks the
    highest-risk line — the admit step must refuse an add that drops the account
    below the early-warning buffer, not merely below the liquidation line."""
    # equity 75k, used 0 → current level inf; add 100k margin → projected
    # 75k / 100k × 100 = 75.0 (between stop-out 50 and buffer 100).
    d = _admit(
        order=_order(),
        state=_account(equity=75_000.0, used_margin=0.0),
        op_state=_op(),
        params=_params(stop_out_level_pct=50.0, safe_mode_buffer_pct=100.0),
        clock=None,
        evaluation=_clean_eval(additional_used_margin=100_000.0),
    )
    assert d.decision == "REJECT"
    assert d.binding_constraint == "margin_distance"


def test_unknown_margin_defaults_to_reject():
    """Reject-leaning default: an absent ``additional_used_margin`` (None) cannot
    assess margin → REJECT ``margin_distance`` (never defaults to zero-margin)."""
    d = _admit(
        order=_order(),
        state=_account(),
        op_state=_op(),
        params=_params(),
        clock=None,
        # in_universe / not-excluded so they don't bind first; margin left None.
        evaluation=_order_evaluation(in_universe=True, is_excluded=False),
    )
    assert d.decision == "REJECT"
    assert d.binding_constraint == "margin_distance"


# --------------------------------------------------------------------------- #
# 9. Per-order size limit — reject + advisory_max, NO mutation (R2.3).          #
# --------------------------------------------------------------------------- #

def test_size_breach_rejects_with_advisory_max_and_no_mutation():
    order = _order(volume=5.0)
    before = dataclasses.replace(order)  # snapshot
    d = _admit(
        order=order,
        state=_account(),
        op_state=_op(),
        params=_params(per_order_size_max=1.0),
        clock=None,
        evaluation=_clean_eval(),
    )
    assert d.decision == "REJECT"
    assert d.binding_constraint == "size_limit"
    assert d.advisory_max_volume == 1.0
    # The order object is NOT mutated/resized (the daemon resizes + resubmits).
    assert order == before
    assert order.volume == 5.0


def test_size_at_limit_is_allowed():
    """Volume exactly at the cap is not a breach (breach is strictly above)."""
    d = _admit(
        order=_order(volume=1.0),
        state=_account(),
        op_state=_op(),
        params=_params(per_order_size_max=1.0),
        clock=None,
        evaluation=_clean_eval(),
    )
    assert d.decision == "ALLOW"


# --------------------------------------------------------------------------- #
# 10. Mandatory stop-loss.                                                      #
# --------------------------------------------------------------------------- #

def test_missing_stop_loss_on_open_rejects():
    d = _admit(
        order=_order(volume=0.5, stop_loss=None),
        state=_account(),
        op_state=_op(),
        params=_params(per_order_size_max=1.0),
        clock=None,
        evaluation=_clean_eval(),
    )
    assert d.decision == "REJECT"
    assert d.binding_constraint == "missing_sl"


def test_clean_open_is_allowed():
    d = _admit(
        order=_order(volume=0.5, stop_loss=90.0),
        state=_account(),
        op_state=_op(),
        params=_params(per_order_size_max=1.0),
        clock=None,
        evaluation=_clean_eval(),
    )
    assert d.decision == "ALLOW"
    assert d.binding_constraint is None
    assert d.advisory_max_volume is None


# --------------------------------------------------------------------------- #
# 11. Lexicographic first-binding order.                                        #
# --------------------------------------------------------------------------- #

def test_kill_switch_beats_universe_beats_margin_beats_size_beats_sl():
    """With many constraints all violated at once, the FIRST in the fixed walk
    order is the reported binding constraint (short-circuit)."""
    # Everything is broken: kill switch on, off-universe, margin starved, size
    # over cap, no SL. Kill switch is first → it wins.
    bad_eval = _order_evaluation(
        additional_used_margin=None,  # margin unknown (would reject)
        in_universe=False,            # off-universe (would reject)
        is_excluded=True,             # flagged (would reject)
    )
    d = _admit(
        order=_order(volume=99.0, stop_loss=None),  # size over + no SL
        state=_account(),
        op_state=_op(kill_switch=True, grade="FLATTEN"),
        params=_params(per_order_size_max=1.0),
        clock=None,
        evaluation=bad_eval,
    )
    assert d.binding_constraint == "kill_switch"

    # Drop kill switch → safe_mode (FLATTEN) is now first.
    d2 = _admit(
        order=_order(volume=99.0, stop_loss=None),
        state=_account(),
        op_state=_op(kill_switch=False, grade="FLATTEN"),
        params=_params(per_order_size_max=1.0),
        clock=None,
        evaluation=bad_eval,
    )
    assert d2.binding_constraint == "safe_mode"

    # Drop safe_mode but deactivate the account → not_activated is next (it must
    # win over the still-bad universe/margin/size/SL downstream of it). This locks
    # the ordering position of step 3, not merely that not_activated can fire.
    d3a = _admit(
        order=_order(volume=99.0, stop_loss=None),
        state=_account(activated=False),
        op_state=_op(kill_switch=False, grade="NONE"),
        params=_params(per_order_size_max=1.0),
        clock=None,
        evaluation=bad_eval,  # off-universe + margin/exclusion still bad
    )
    assert d3a.binding_constraint == "not_activated"

    # Re-activate → universe is next (account active, margin/size/SL still bad).
    d3 = _admit(
        order=_order(volume=99.0, stop_loss=None),
        state=_account(),
        op_state=_op(kill_switch=False, grade="NONE"),
        params=_params(per_order_size_max=1.0),
        clock=None,
        evaluation=bad_eval,
    )
    assert d3.binding_constraint == "universe"

    # Fix universe but flag exclusion (enabled) → entry_exclusion is next: it must
    # win over the still-bad margin/size/SL downstream of it. This locks the
    # ordering position of step 5 (exclusion binds before margin_distance), not
    # merely that exclusion can fire.
    d3b = _admit(
        order=_order(volume=99.0, stop_loss=None),
        state=_account(),
        op_state=_op(kill_switch=False, grade="NONE"),
        params=_params(per_order_size_max=1.0, exclusion_enabled=True),
        clock=None,
        evaluation=_order_evaluation(additional_used_margin=None,  # margin still bad
                                     in_universe=True, is_excluded=True),
    )
    assert d3b.binding_constraint == "entry_exclusion"

    # Fix universe + exclusion → margin is next.
    d4 = _admit(
        order=_order(volume=99.0, stop_loss=None),
        state=_account(),
        op_state=_op(kill_switch=False, grade="NONE"),
        params=_params(per_order_size_max=1.0),
        clock=None,
        evaluation=_order_evaluation(additional_used_margin=None,
                                     in_universe=True, is_excluded=False),
    )
    assert d4.binding_constraint == "margin_distance"

    # Fix margin → size is next.
    d5 = _admit(
        order=_order(volume=99.0, stop_loss=None),
        state=_account(),
        op_state=_op(kill_switch=False, grade="NONE"),
        params=_params(per_order_size_max=1.0),
        clock=None,
        evaluation=_clean_eval(),
    )
    assert d5.binding_constraint == "size_limit"

    # Fix size → missing SL is last.
    d6 = _admit(
        order=_order(volume=0.5, stop_loss=None),
        state=_account(),
        op_state=_op(kill_switch=False, grade="NONE"),
        params=_params(per_order_size_max=1.0),
        clock=None,
        evaluation=_clean_eval(),
    )
    assert d6.binding_constraint == "missing_sl"


# --------------------------------------------------------------------------- #
# 12. Kill-switch freshness — op-state read per call (not pinned).              #
# --------------------------------------------------------------------------- #

def test_kill_switch_freshness_toggles_result_between_calls():
    order = _order(volume=0.5, stop_loss=90.0)
    state = _account()
    params = _params(per_order_size_max=1.0)
    ev = _clean_eval()

    engaged = _admit(order=order, state=state, op_state=_op(kill_switch=True),
                     params=params, clock=None, evaluation=ev)
    assert engaged.decision == "REJECT"
    assert engaged.binding_constraint == "kill_switch"

    cleared = _admit(order=order, state=state, op_state=_op(kill_switch=False),
                     params=params, clock=None, evaluation=ev)
    assert cleared.decision == "ALLOW"


# --------------------------------------------------------------------------- #
# 13. Fail-toward-open on ambiguity.                                            #
# --------------------------------------------------------------------------- #

def test_unrecognized_direction_does_not_short_circuit_as_exit():
    """An unrecognized order ``direction`` value (not LONG/SHORT) never
    short-circuits as an exit — it takes the full walk (REJECT under kill)."""
    held = _position(symbol="AAPL", direction="LONG", volume=10.0)
    d = _admit(
        order=_order(symbol="AAPL", intent="SELL", direction="BUY", volume=5.0),
        state=_account(positions=[held]),
        op_state=_op(kill_switch=True),
        params=_params(),
        clock=None,
        evaluation=_clean_eval(),
    )
    assert d.decision == "REJECT"
    assert d.binding_constraint == "kill_switch"


def test_unrecognized_held_direction_does_not_short_circuit_as_exit():
    """A garbage HELD-position direction also fails toward open (the held side
    must pass the recognized-value check too)."""
    held = _position(symbol="AAPL", direction="??", volume=10.0)
    d = _admit(
        order=_order(symbol="AAPL", intent="SELL", direction="SHORT", volume=5.0),
        state=_account(positions=[held]),
        op_state=_op(kill_switch=True),
        params=_params(),
        clock=None,
        evaluation=_clean_eval(),
    )
    assert d.decision == "REJECT"
    assert d.binding_constraint == "kill_switch"


def test_multiple_held_positions_same_symbol_does_not_short_circuit():
    """Two held positions in the same symbol → ambiguous netting → fail toward
    open (do not build a netting engine; never short-circuit an ambiguous case)."""
    held1 = _position(symbol="AAPL", direction="LONG", volume=10.0, position_id="p1")
    held2 = _position(symbol="AAPL", direction="LONG", volume=4.0, position_id="p2")
    d = _admit(
        order=_order(symbol="AAPL", intent="SELL", direction="SHORT", volume=5.0),
        state=_account(positions=[held1, held2]),
        op_state=_op(kill_switch=True),
        params=_params(),
        clock=None,
        evaluation=_clean_eval(),
    )
    assert d.decision == "REJECT"
    assert d.binding_constraint == "kill_switch"


def test_exit_volume_at_held_volume_is_a_true_exit():
    """Boundary: order volume EQUAL to held volume is a true exit (≤, inclusive)."""
    held = _position(symbol="AAPL", direction="SHORT", volume=7.0)
    d = _admit(
        order=_order(symbol="AAPL", intent="BUY", direction="LONG",
                     volume=7.0, stop_loss=None),
        state=_account(positions=[held]),
        op_state=_op(kill_switch=True),
        params=_params(),
        clock=None,
        evaluation=_order_evaluation(),
    )
    assert d.decision == "ALLOW"


# --------------------------------------------------------------------------- #
# 14. funding_cap is NEVER the binding constraint in admit.                     #
# --------------------------------------------------------------------------- #

def test_funding_cap_is_never_the_binding_constraint():
    """``funding_cap`` belongs to task 4.2's capitalization-time precondition,
    never to the per-order walk. No admit path may emit it."""
    cases = [
        # open under every kind of breach we can provoke here
        dict(op_state=_op(kill_switch=True), evaluation=_clean_eval()),
        dict(op_state=_op(grade="HALT_NEW"), evaluation=_clean_eval()),
        dict(op_state=_op(), evaluation=_clean_eval(in_universe=False)),
        dict(op_state=_op(), evaluation=_clean_eval(additional_used_margin=None)),
        dict(op_state=_op(), evaluation=_clean_eval()),
    ]
    for c in cases:
        d = _admit(
            order=_order(volume=0.5, stop_loss=90.0),
            state=_account(),
            params=_params(per_order_size_max=1.0),
            clock=None,
            **c,
        )
        assert d.binding_constraint != "funding_cap"


# --------------------------------------------------------------------------- #
# 15. Determinism (R11.1).                                                      #
# --------------------------------------------------------------------------- #

def test_identical_inputs_yield_identical_decision():
    kwargs = dict(
        order=_order(volume=0.5, stop_loss=90.0),
        state=_account(),
        op_state=_op(),
        params=_params(per_order_size_max=1.0),
        clock=None,
        evaluation=_clean_eval(),
    )
    assert _admit(**kwargs) == _admit(**kwargs)
