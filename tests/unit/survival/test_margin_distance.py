"""Task 3.1 — observable proof for ``src.survival.gate.check_margin_distance``.

Proves the task-3.1 observable: given a synthetic :class:`AccountState`, the
account-level margin-distance check returns the correct buffer/threshold
comparison and never reads external state (it only touches its arguments).

What this proves (R1.1–R1.3, R11.1):

  * **Margin level (R1.1)** is computed as account equity / aggregate used margin
    × 100 (cross-margin, account-level; higher % = safer), not trusted blindly
    from the venue-supplied ``state.margin_level``.
  * **Projection** = equity / (aggregate used margin + ``additional_used_margin``)
    × 100; the breach booleans key off the *projected* (worst-case) level so an
    add that pushes a safe account into breach is caught (the admit consumer,
    task 3.2). With the default ``additional_used_margin == 0.0`` (the no-order
    ``assess`` case, task 4.1) projected == current.
  * **Breach = level ≤ threshold** (higher % = safer): ``breaches_stop_out`` when
    projected ≤ ``stop_out_level_pct`` (R1.2 liquidation line); and
    ``breaches_safe_mode_buffer`` when projected ≤ ``safe_mode_buffer_pct`` (R1.3
    buffer strictly above stop-out). Exact-boundary cases exercised.
  * **Zero used margin** (no leverage / no open positions) → margin level is
    undefined / infinite → treated as **not breaching** (no liquidation risk
    with zero leverage); no divide-by-zero.
  * **Determinism (R11.1):** identical inputs → identical result; the function
    reads no external state (only its arguments).

Pure unit test — no LLM / MCP / DB (P14, R11.2). This is a minimal observable
proof for THIS task; the broader admit/assess suites are tasks 5.2 / 5.3.
"""

from __future__ import annotations

import dataclasses
import importlib
import math

import pytest

from src.survival.params import DEFAULTS
from src.survival.types import AccountState, Position


# --------------------------------------------------------------------------- #
# Helpers.                                                                     #
# --------------------------------------------------------------------------- #

def _gate_module():
    return importlib.import_module("src.survival.gate")


def _account(*, equity: float, used_margin: float, positions=None) -> AccountState:
    """A synthetic AccountState. ``margin_level`` is deliberately set to a
    bogus high value so a test that (wrongly) trusted the venue field instead of
    computing it would give a different answer — proving R1.1 is *computed*.
    """
    return AccountState(
        activated=True,
        equity=equity,
        used_margin=used_margin,
        free_margin=equity - used_margin,
        margin_level=999_999.0,  # bogus venue value: never the authoritative source
        balance=equity,
        stop_out_level=50.0,
        positions=list(positions or []),
    )


def _params(*, stop_out: float, buffer: float):
    return dataclasses.replace(
        DEFAULTS, stop_out_level_pct=stop_out, safe_mode_buffer_pct=buffer
    )


# --------------------------------------------------------------------------- #
# R1.1 — margin level is COMPUTED (equity / used_margin × 100), not trusted.   #
# --------------------------------------------------------------------------- #

def test_current_level_is_computed_not_taken_from_venue_field():
    m = _gate_module()
    # equity 8000 / used 10000 × 100 = 80.0 ; the bogus venue 999_999 is ignored.
    state = _account(equity=8_000.0, used_margin=10_000.0)
    res = m.check_margin_distance(state, _params(stop_out=50.0, buffer=100.0))
    assert res.current_level == pytest.approx(80.0)


# --------------------------------------------------------------------------- #
# Projection moves with the supplied additional_used_margin input.             #
# --------------------------------------------------------------------------- #

def test_current_level_is_authoritative_not_pulled_by_low_venue_field():
    # Compute-authoritative (task 3.1 "keep it simple"): the venue margin_level is
    # NOT mixed into current_level. A LOW venue value (60) must not drag the
    # computed current (80) down — an asymmetric current-only venue-min would break
    # the projected <= current invariant and fail-open in the no-add assess path.
    m = _gate_module()
    state = AccountState(
        activated=True,
        equity=8_000.0,
        used_margin=10_000.0,  # computes to 80.0
        free_margin=-2_000.0,
        margin_level=60.0,  # low venue value — deliberately ignored
        balance=8_000.0,
        stop_out_level=50.0,
        positions=[],
    )
    # buffer 70 sits strictly between the (ignored) venue 60 and the computed 80.
    # With delta 0, projected == current == 80 > 70 → no buffer breach. A
    # venue-trusting (min) impl would report current 60 <= 70 and break this.
    res = m.check_margin_distance(state, _params(stop_out=50.0, buffer=70.0))
    assert res.current_level == pytest.approx(80.0)
    assert res.projected_level == pytest.approx(80.0)
    assert res.breaches_safe_mode_buffer is False


def test_nan_equity_fails_toward_breach_not_all_clear():
    # A degraded AccountState (NaN equity field) must fail toward BREACH, never
    # toward "all clear": NaN <= threshold is False (fail-open) — so the helper
    # coerces a NaN level to the most-dangerous 0.0 and reports a breach.
    m = _gate_module()
    state = AccountState(
        activated=True,
        equity=math.nan,
        used_margin=10_000.0,
        free_margin=0.0,
        margin_level=999_999.0,
        balance=0.0,
        stop_out_level=50.0,
        positions=[],
    )
    res = m.check_margin_distance(state, _params(stop_out=50.0, buffer=100.0))
    assert res.breaches_stop_out is True
    assert res.breaches_safe_mode_buffer is True


def test_projection_uses_additional_used_margin_input():
    m = _gate_module()
    # equity 8000 / (used 10000 + add 6000) × 100 = 50.0
    state = _account(equity=8_000.0, used_margin=10_000.0)
    res = m.check_margin_distance(
        state, _params(stop_out=50.0, buffer=100.0), additional_used_margin=6_000.0
    )
    assert res.current_level == pytest.approx(80.0)
    assert res.projected_level == pytest.approx(50.0)


def test_default_additional_margin_makes_projected_equal_current():
    m = _gate_module()
    state = _account(equity=8_000.0, used_margin=10_000.0)
    res = m.check_margin_distance(state, _params(stop_out=50.0, buffer=100.0))
    assert res.projected_level == res.current_level == pytest.approx(80.0)


# --------------------------------------------------------------------------- #
# Breach booleans — key off PROJECTED (worst-case) level; breach = level ≤ thr. #
# --------------------------------------------------------------------------- #

def test_no_breach_when_projected_above_both_thresholds():
    m = _gate_module()
    # 80.0 projected, stop-out 50, buffer 70 → above both → no breach.
    state = _account(equity=8_000.0, used_margin=10_000.0)
    res = m.check_margin_distance(state, _params(stop_out=50.0, buffer=70.0))
    assert res.breaches_stop_out is False
    assert res.breaches_safe_mode_buffer is False


def test_safe_mode_buffer_breach_but_not_stop_out():
    m = _gate_module()
    # 80.0 projected: ≤ buffer 100 (breach) but > stop-out 50 (no breach).
    state = _account(equity=8_000.0, used_margin=10_000.0)
    res = m.check_margin_distance(state, _params(stop_out=50.0, buffer=100.0))
    assert res.breaches_safe_mode_buffer is True
    assert res.breaches_stop_out is False


def test_stop_out_breach_implies_buffer_breach():
    m = _gate_module()
    # 40.0 projected: ≤ stop-out 50 AND ≤ buffer 100 → both breach.
    state = _account(equity=4_000.0, used_margin=10_000.0)
    res = m.check_margin_distance(state, _params(stop_out=50.0, buffer=100.0))
    assert res.breaches_stop_out is True
    assert res.breaches_safe_mode_buffer is True


def test_add_pushes_safe_account_into_buffer_breach():
    # The admit (task 3.2) case the booleans-on-current-only bug would miss:
    # current 80 is safe (> buffer 70), but the proposed add drops projected to 50.
    m = _gate_module()
    state = _account(equity=8_000.0, used_margin=10_000.0)
    res = m.check_margin_distance(
        state, _params(stop_out=40.0, buffer=70.0), additional_used_margin=6_000.0
    )
    assert res.current_level == pytest.approx(80.0)
    assert res.projected_level == pytest.approx(50.0)
    # current was safe; the add breaches the buffer → caught off the projection.
    assert res.breaches_safe_mode_buffer is True
    assert res.breaches_stop_out is False


# --------------------------------------------------------------------------- #
# Exact-boundary cases — breach uses ≤ (at-or-below).                          #
# --------------------------------------------------------------------------- #

def test_exact_stop_out_boundary_breaches():
    m = _gate_module()
    # projected exactly == stop-out 50 → breach (≤, at-or-below).
    state = _account(equity=5_000.0, used_margin=10_000.0)
    res = m.check_margin_distance(state, _params(stop_out=50.0, buffer=100.0))
    assert res.projected_level == pytest.approx(50.0)
    assert res.breaches_stop_out is True


def test_exact_buffer_boundary_breaches():
    m = _gate_module()
    # projected exactly == buffer 100 → buffer breach (≤); stop-out 50 not hit.
    state = _account(equity=10_000.0, used_margin=10_000.0)
    res = m.check_margin_distance(state, _params(stop_out=50.0, buffer=100.0))
    assert res.projected_level == pytest.approx(100.0)
    assert res.breaches_safe_mode_buffer is True
    assert res.breaches_stop_out is False


# --------------------------------------------------------------------------- #
# Zero used margin — no leverage → margin level infinite → NOT breaching.      #
# --------------------------------------------------------------------------- #

def test_zero_used_margin_is_not_breaching_and_no_divide_by_zero():
    m = _gate_module()
    state = _account(equity=8_000.0, used_margin=0.0)
    res = m.check_margin_distance(state, _params(stop_out=50.0, buffer=100.0))
    assert res.breaches_stop_out is False
    assert res.breaches_safe_mode_buffer is False


def test_zero_projected_denominator_is_not_breaching():
    # used_margin == 0 and additional == 0 → projected denominator 0 → not breach.
    m = _gate_module()
    state = _account(equity=8_000.0, used_margin=0.0)
    res = m.check_margin_distance(
        state, _params(stop_out=50.0, buffer=100.0), additional_used_margin=0.0
    )
    assert res.breaches_stop_out is False
    assert res.breaches_safe_mode_buffer is False


# --------------------------------------------------------------------------- #
# Determinism / purity (R11.1, R11.2) — same inputs → same result; no external #
# state read (the function touches only its arguments).                        #
# --------------------------------------------------------------------------- #

def test_deterministic_identical_inputs_identical_result():
    m = _gate_module()
    state = _account(equity=8_000.0, used_margin=10_000.0)
    params = _params(stop_out=50.0, buffer=100.0)
    r1 = m.check_margin_distance(state, params, additional_used_margin=2_000.0)
    r2 = m.check_margin_distance(state, params, additional_used_margin=2_000.0)
    assert r1 == r2


def test_result_is_frozen_dataclass():
    m = _gate_module()
    state = _account(equity=8_000.0, used_margin=10_000.0)
    res = m.check_margin_distance(state, _params(stop_out=50.0, buffer=100.0))
    assert dataclasses.is_dataclass(res)
    with pytest.raises(dataclasses.FrozenInstanceError):
        res.current_level = 1.0  # type: ignore[misc]


def test_reads_no_external_state_only_its_arguments():
    # A position list on the account must not change the account-level computation
    # (used_margin is the aggregate, supplied on AccountState; the check does not
    # re-sum positions or reach for anything outside its arguments).
    m = _gate_module()
    pos = Position(
        position_id="p1",
        symbol="AAPL",
        direction="BUY",
        volume=1.0,
        avg_open_price=100.0,
        used_margin=4_242.0,  # deliberately inconsistent with the aggregate below
        unrealized_pnl=0.0,
    )
    with_pos = _account(equity=8_000.0, used_margin=10_000.0, positions=[pos])
    without_pos = _account(equity=8_000.0, used_margin=10_000.0)
    params = _params(stop_out=50.0, buffer=100.0)
    assert m.check_margin_distance(with_pos, params) == m.check_margin_distance(
        without_pos, params
    )
