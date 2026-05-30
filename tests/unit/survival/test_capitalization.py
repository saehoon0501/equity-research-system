"""Task 4.2 — observable proof for ``src.survival.gate.check_capitalization``
(the capitalization-time funding-cap precondition).

``check_capitalization(funded_balance, total_book_equity, params)`` is a
**pre-funding** check (run when wiring / adding funds), **NOT** part of the
per-order ``admit`` walk (R3.2 reconciliation — the §16 funding cap is on funded
capital, fixed at capitalization, so it cannot be breached per order). It
enforces that the Gate account's funded balance does not exceed the
**speculative-sleeve cap** (≤ 8%) of the supplied total-book equity, reusing the
shared sleeve-cap vocabulary (R3.1/R3.3 — no parallel cap definition).

What this proves (R3.1, R3.3, R3.4, R11.1):

  * **Observable:** a funded balance **above** the sleeve cap of the supplied
    total book is REJECTED with ``binding_constraint == "funding_cap"``; a funded
    balance **at or below** the cap ALLOWs.
  * **Exact boundary:** ``funded_pct == cap`` (e.g. funded 8, book 100) → ALLOW
    (at-or-below passes; the strict-``>`` VIOLATION semantics live in
    ``check_sleeve_cap`` — we do not re-implement them here).
  * **Reuse of ``check_sleeve_cap`` (R3.3, no parallel literal):** the cap is the
    canonical ``_SLEEVE_CAPS["speculative_optionality"]`` from
    ``conviction_rollup`` (imported here so impl + test move together if the
    canonical cap ever moves); the boundary is derived from it, never a hardcoded
    ``8.0``. The speculative cap is confirmed ``== 8.0 == params
    .speculative_sleeve_cap_pct``.
  * **``PASS_SOFT_WARNING`` is a pass:** a zero funded balance routes through
    ``check_sleeve_cap``'s ``PASS_SOFT_WARNING`` (current_aggregate == 0.0) and is
    treated as ALLOW (zero funded is trivially at/below the cap), not a violation.
  * **Fail toward not-funding (this is an open/add of funded capital):**
    ``total_book_equity <= 0`` or NaN/inf → REJECT (no divide-by-zero, no
    pass-by-default); negative or NaN/inf ``funded_balance`` → REJECT. These
    guards run **before** ``check_sleeve_cap`` (which silently fail-opens on
    negative / NaN inputs).
  * **Not per-order:** ``check_capitalization`` is never reached by ``admit`` —
    ``admit`` still never emits ``funding_cap`` (cross-checked here).
  * **Determinism (R11.1):** identical inputs → identical ``AdmitDecision``.

Pure unit test — no LLM / MCP / DB (P14, R11.2). The one allowed cross-package
import is ``check_sleeve_cap`` / ``_SLEEVE_CAPS`` from ``conviction_rollup``
(design "Allowed Dependencies").
"""

from __future__ import annotations

import dataclasses
import math

import pytest

from src.supervisor.conviction_rollup import _SLEEVE_CAPS, check_sleeve_cap
from src.survival.gate import admit, check_capitalization
from src.survival.params import DEFAULTS
from src.survival.types import (
    AccountState,
    OrderEvaluation,
    OperationalState,
    Position,
    ProposedOrder,
    ClockState,
)


# The canonical speculative-sleeve cap (%), the single authority — derived from
# the shared vocabulary, NOT a parallel literal (R3.3).
_SPEC_CAP: float = _SLEEVE_CAPS["speculative_optionality"]


def _params():
    return DEFAULTS


# --------------------------------------------------------------------------- #
# Canonical-cap sanity: the shared vocabulary == 8.0 == the pinned param.      #
# --------------------------------------------------------------------------- #

def test_canonical_speculative_cap_is_eight_and_matches_param():
    """R3.3 — the cap comes from the shared ``check_sleeve_cap`` vocabulary; it
    is confirmed ``== 8.0`` and equal to ``params.speculative_sleeve_cap_pct`` so
    there is no parallel cap definition to drift.
    """
    assert _SPEC_CAP == 8.0
    assert DEFAULTS.speculative_sleeve_cap_pct == 8.0
    # check_sleeve_cap echoes the canonical cap as tier_cap.
    assert check_sleeve_cap("speculative_optionality", 0.0, 0.0)["tier_cap"] == _SPEC_CAP


# --------------------------------------------------------------------------- #
# The observable: above cap → REJECT funding_cap; at/below → ALLOW.            #
# --------------------------------------------------------------------------- #

def test_funded_balance_above_cap_rejects_funding_cap():
    """Observable — a funded balance ABOVE the sleeve cap of the supplied total
    book is REJECTED with ``binding_constraint == "funding_cap"`` (R3.1/R3.2).

    funded 9 / book 100 = 9% > 8% cap.
    """
    decision = check_capitalization(
        funded_balance=9.0, total_book_equity=100.0, params=_params()
    )
    assert decision.decision == "REJECT"
    assert decision.binding_constraint == "funding_cap"
    assert decision.reason  # a non-empty reason is emitted for audit


def test_funded_balance_below_cap_allows():
    """Observable — a funded balance well BELOW the cap ALLOWs.

    funded 5 / book 100 = 5% <= 8% cap.
    """
    decision = check_capitalization(
        funded_balance=5.0, total_book_equity=100.0, params=_params()
    )
    assert decision.decision == "ALLOW"
    assert decision.binding_constraint is None


def test_funded_balance_just_above_cap_rejects():
    """A funded balance only marginally above the cap still REJECTs (the strict
    ``>`` boundary belongs to ``check_sleeve_cap``).

    funded 8.5 / book 100 = 8.5% > 8% cap.
    """
    decision = check_capitalization(
        funded_balance=8.5, total_book_equity=100.0, params=_params()
    )
    assert decision.decision == "REJECT"
    assert decision.binding_constraint == "funding_cap"


# --------------------------------------------------------------------------- #
# Exact boundary: funded_pct == cap → ALLOW (at-or-below passes).             #
# --------------------------------------------------------------------------- #

def test_funded_balance_exactly_at_cap_allows():
    """Exact-boundary — a funded balance EXACTLY at the cap of the supplied total
    book ALLOWs (≤ passes per the observable). funded == cap%, book == 100 → the
    computed funded_pct lands exactly on the cap.
    """
    # _SPEC_CAP% of a 100 book is exactly _SPEC_CAP units funded.
    funded = _SPEC_CAP        # 8.0 funded
    book = 100.0              # 8.0 / 100 * 100 == 8.0 == cap (verified exact)
    # Sanity: the computed share lands exactly on the cap.
    assert funded / book * 100.0 == _SPEC_CAP
    decision = check_capitalization(
        funded_balance=funded, total_book_equity=book, params=_params()
    )
    assert decision.decision == "ALLOW"
    assert decision.binding_constraint is None


def test_exact_boundary_derived_from_shared_cap():
    """The boundary is built from the SHARED canonical cap, not a literal 8.0 —
    if the canonical cap ever moves, this test moves with the implementation
    (R3.3 — shared vocabulary, no parallel definition). A book where ``funded ==
    cap`` units gives funded_pct == cap → ALLOW; one unit more → REJECT.
    """
    book = 100.0
    at_cap = check_capitalization(
        funded_balance=_SPEC_CAP, total_book_equity=book, params=_params()
    )
    over_cap = check_capitalization(
        funded_balance=_SPEC_CAP + 1.0, total_book_equity=book, params=_params()
    )
    assert at_cap.decision == "ALLOW"
    assert over_cap.decision == "REJECT"
    assert over_cap.binding_constraint == "funding_cap"


# --------------------------------------------------------------------------- #
# PASS_SOFT_WARNING (zero funded) is a pass, not a violation.                  #
# --------------------------------------------------------------------------- #

def test_zero_funded_balance_allows_via_soft_warning():
    """A zero funded balance routes through ``check_sleeve_cap``'s
    ``PASS_SOFT_WARNING`` (current_aggregate == 0.0) and is treated as ALLOW —
    zero funded is trivially at/below the cap (PASS_SOFT_WARNING is a pass, not a
    violation).
    """
    # Confirm the underlying status is the soft-warning one for the zero case, so
    # this test genuinely exercises the PASS_SOFT_WARNING → ALLOW mapping.
    assert (
        check_sleeve_cap("speculative_optionality", 0.0, 0.0)["status"]
        == "PASS_SOFT_WARNING"
    )
    decision = check_capitalization(
        funded_balance=0.0, total_book_equity=100.0, params=_params()
    )
    assert decision.decision == "ALLOW"
    assert decision.binding_constraint is None


# --------------------------------------------------------------------------- #
# P7 tighten-only reconciliation: a pinned cap BELOW the shared cap tightens.  #
# --------------------------------------------------------------------------- #

def test_pinned_param_tighter_than_shared_cap_rejects():
    """P7 tighten-only — if ``params.speculative_sleeve_cap_pct`` is pinned BELOW
    the canonical shared cap, the gate prefers the tighter (lower) bound. A
    funded share that is a PASS under the canonical 8% cap but ABOVE the tightened
    pinned cap is REJECTED ``funding_cap`` — proving the rejection comes from the
    pinned-cap reconciliation, NOT from ``check_sleeve_cap``.
    """
    tight = dataclasses.replace(DEFAULTS, speculative_sleeve_cap_pct=5.0)
    # funded 6% of book: NOT a VIOLATION under the canonical 8.0 cap...
    assert (
        check_sleeve_cap("speculative_optionality", 6.0, 6.0)["status"] != "VIOLATION"
    )
    # ...but over the tightened 5.0 pinned cap → REJECT via the reconciliation.
    decision = check_capitalization(
        funded_balance=6.0, total_book_equity=100.0, params=tight
    )
    assert decision.decision == "REJECT"
    assert decision.binding_constraint == "funding_cap"


def test_pinned_param_tighter_still_allows_below_tightened_cap():
    """The tightened pinned cap is the operative bound, but a funded share below
    *it* still ALLOWs — the reconciliation tightens, it does not reject
    everything. funded 4% < tightened 5% cap → ALLOW.
    """
    tight = dataclasses.replace(DEFAULTS, speculative_sleeve_cap_pct=5.0)
    decision = check_capitalization(
        funded_balance=4.0, total_book_equity=100.0, params=tight
    )
    assert decision.decision == "ALLOW"
    assert decision.binding_constraint is None


# --------------------------------------------------------------------------- #
# Edge cases — fail toward not-funding (this is an open/add of funded capital).#
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("bad_book", [0.0, -1.0, -100.0, float("nan"), float("inf")])
def test_nonpositive_or_nonfinite_total_book_rejects(bad_book):
    """``total_book_equity <= 0`` or NaN/inf → cannot assess the ratio → REJECT
    ``funding_cap`` (no divide-by-zero, no pass-by-default). Guards run BEFORE
    ``check_sleeve_cap`` (which would silently fail-open).
    """
    decision = check_capitalization(
        funded_balance=1.0, total_book_equity=bad_book, params=_params()
    )
    assert decision.decision == "REJECT"
    assert decision.binding_constraint == "funding_cap"


@pytest.mark.parametrize("bad_funded", [-1.0, -0.01, float("nan"), float("inf")])
def test_negative_or_nonfinite_funded_balance_rejects(bad_funded):
    """A negative or NaN/inf funded balance (programmer / degraded input) →
    REJECT ``funding_cap`` (fail toward not-funding); never silently allowed.
    """
    decision = check_capitalization(
        funded_balance=bad_funded, total_book_equity=100.0, params=_params()
    )
    assert decision.decision == "REJECT"
    assert decision.binding_constraint == "funding_cap"


def test_does_not_divide_by_zero_on_zero_book():
    """``total_book_equity == 0`` must not raise (ZeroDivisionError) across the
    boundary — it is caught by the guard and returns a REJECT.
    """
    # Should not raise:
    decision = check_capitalization(
        funded_balance=1.0, total_book_equity=0.0, params=_params()
    )
    assert decision.decision == "REJECT"


# --------------------------------------------------------------------------- #
# Determinism (R11.1).                                                         #
# --------------------------------------------------------------------------- #

def test_deterministic_identical_inputs():
    """Identical inputs → identical ``AdmitDecision`` (R11.1)."""
    a = check_capitalization(funded_balance=7.0, total_book_equity=100.0, params=_params())
    b = check_capitalization(funded_balance=7.0, total_book_equity=100.0, params=_params())
    assert a == b
    # And for a reject case.
    c = check_capitalization(funded_balance=20.0, total_book_equity=100.0, params=_params())
    d = check_capitalization(funded_balance=20.0, total_book_equity=100.0, params=_params())
    assert c == d


# --------------------------------------------------------------------------- #
# Not per-order: admit still never emits funding_cap.                          #
# --------------------------------------------------------------------------- #

def test_admit_never_emits_funding_cap():
    """``check_capitalization`` is a capitalization-time precondition, NOT part of
    the per-order walk (R3.2 reconciliation). ``admit`` must still never emit
    ``funding_cap`` — even for an order that would, naively, look over a sleeve
    cap. We drive an order through ``admit`` and assert ``funding_cap`` is never
    the binding constraint.
    """
    order = ProposedOrder(
        symbol="AAPL",
        intent="BUY",
        direction="LONG",
        volume=0.5,
        stop_loss=190.0,
    )
    state = AccountState(
        activated=True,
        equity=10_000.0,
        used_margin=1_000.0,
        free_margin=9_000.0,
        margin_level=1_000.0,
        balance=10_000.0,
        stop_out_level=50.0,
        positions=[],
    )
    op_state = OperationalState(
        kill_switch_engaged=False,
        safe_mode_grade="NONE",
        entered_at=None,
        triggered_by=None,
    )
    clock = ClockState(session_open=True, seconds_to_next_closure=None)
    evaluation = OrderEvaluation(
        additional_used_margin=10.0,
        in_universe=True,
        is_excluded=False,
    )
    decision = admit(order, state, op_state, _params(), clock, evaluation)
    # Whatever the disposition, funding_cap is never emitted by admit.
    assert decision.binding_constraint != "funding_cap"
