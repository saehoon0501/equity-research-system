"""Tests for the synthesized Flow-Pressure indicator (BVC + CMF).

Grounds: BVC signed-volume imbalance (Easley/López de Prado/O'Hara) + Chaikin
Money Flow. These are deterministic OHLCV transforms; verify sign, bounds, and
that up-on-volume reads positive pressure.
"""

from __future__ import annotations

from src.micro import indicators as ind


def _bar(c, h=None, l=None, v=1000):
    h = c if h is None else h
    l = c if l is None else l
    return {"open": c, "high": h, "low": l, "close": c, "volume": v}


def test_cmf_sign_and_bounds():
    # Closes printing at the top of each bar's range -> strong buying pressure.
    up = [{"open": 10, "high": 11, "low": 9, "close": 10.9, "volume": 1000} for _ in range(21)]
    dn = [{"open": 10, "high": 11, "low": 9, "close": 9.1, "volume": 1000} for _ in range(21)]
    cu, cd = ind.chaikin_money_flow(up, 21), ind.chaikin_money_flow(dn, 21)
    assert 0.5 < cu <= 1.0
    assert -1.0 <= cd < -0.5


def test_bvc_imbalance_positive_on_uptrend():
    bars = [_bar(c=100.0 + i * 0.5) for i in range(30)]  # steady up moves
    bvc = ind.bvc_imbalance(bars, 20)
    assert bvc is not None and bvc > 0.5  # mostly buy-classified volume


def test_bvc_flat_is_zero():
    bars = [_bar(c=100.0) for i in range(30)]  # no price change
    assert ind.bvc_imbalance(bars, 20) == 0.0


def test_flow_pressure_bounds_and_blend():
    bars = [_bar(c=100.0 + i * 0.3, h=100.5 + i * 0.3, l=99.7 + i * 0.3) for i in range(30)]
    fp = ind.flow_pressure(bars, 20)
    assert fp is not None and -1.0 <= fp <= 1.0
    assert fp > 0  # rising on volume -> positive flow pressure


def test_flow_pressure_none_only_when_no_data():
    # CMF computes on a single bar, so flow_pressure is available (not None);
    # only an empty series yields None (both components unavailable).
    assert ind.flow_pressure([_bar(c=100.0)], 20) is not None
    assert ind.flow_pressure([], 20) is None
