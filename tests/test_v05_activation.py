"""Tests for src.orchestrator.v05_activation."""

from __future__ import annotations

import datetime as _dt

import pytest

from src.orchestrator.phase_detector import Phase
from src.orchestrator.v05_activation import (
    V05Feature,
    get_activation_status,
    is_feature_live,
)


# --------------------------------------------------------------------------- #
# Fake conn that returns scripted phase-detector inputs                       #
# --------------------------------------------------------------------------- #


def _conn_with_phase(
    *,
    launch_signed_off: bool,
    resolved_predictions: int = 0,
    real_money_active: bool = False,
    days_since_launch: int = 0,
):
    """Return a fake conn whose cursor scripts the three phase_detector
    queries:
        1) launch_signoff
        2) resolved_predictions
        3) real_money_active
    """
    if launch_signed_off:
        # `not_green=0, total=1, launch_date=today - days_since_launch`
        launch_date = _dt.date.today() - _dt.timedelta(days=days_since_launch)
        signoff_row = (0, 1, _dt.datetime.combine(launch_date, _dt.time()))
    else:
        signoff_row = (1, 1, None)

    real_money_row = (1,) if real_money_active else None
    scripted = [
        [signoff_row],                        # launch signoff fetchone
        [(resolved_predictions,)],            # resolved fetchone
        [real_money_row] if real_money_row else [None],
    ]

    class _Conn:
        def __init__(self):
            self._call = 0

        def cursor(self):
            outer = self

            class _Cur:
                def execute(self, *_a, **_k):
                    pass

                def fetchone(self):
                    if outer._call >= len(scripted):
                        return None
                    res = scripted[outer._call]
                    outer._call += 1
                    return res[0] if res else None

                def close(self):
                    pass

                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return False

            return _Cur()

    return _Conn()


def test_features_off_in_v01_launch_readiness():
    conn = _conn_with_phase(launch_signed_off=False)
    status = get_activation_status(conn)
    assert status.phase == Phase.V01_LAUNCH_READINESS
    assert all(not v for v in status.features_live.values())


def test_features_off_in_v01_active():
    conn = _conn_with_phase(launch_signed_off=True, resolved_predictions=0)
    status = get_activation_status(conn)
    assert status.phase == Phase.V01_ACTIVE
    assert all(not v for v in status.features_live.values())


def test_features_on_in_v05_active():
    """≥50 resolved predictions trips v0.5 (per spec §8.1)."""
    conn = _conn_with_phase(launch_signed_off=True, resolved_predictions=100)
    status = get_activation_status(conn)
    assert status.phase == Phase.V05_ACTIVE
    for feat in V05Feature:
        assert status.is_live(feat) is True


def test_features_on_in_v10_active():
    """v1.0-active is a strict superset of v0.5 — features remain live."""
    conn = _conn_with_phase(
        launch_signed_off=True,
        resolved_predictions=100,
        real_money_active=True,
    )
    status = get_activation_status(conn)
    assert status.phase == Phase.V10_ACTIVE
    for feat in V05Feature:
        assert status.is_live(feat) is True


def test_parameter_override_can_force_feature_off_in_v05():
    """Operator can disable an individual v0.5 feature even after v0.5-active —
    e.g., to roll back BB-regime-weights if shrinkage is unstable."""
    conn = _conn_with_phase(launch_signed_off=True, resolved_predictions=100)
    status = get_activation_status(
        conn,
        parameter_overrides={V05Feature.BB_REGIME_WEIGHTS: False},
    )
    assert status.is_live(V05Feature.BRIER_HAIRCUT) is True
    assert status.is_live(V05Feature.BB_REGIME_WEIGHTS) is False


def test_parameter_override_can_force_feature_on_in_v01_active():
    """Operator can opt-in a single v0.5 feature for shadow → live in v0.1
    (e.g., continuous conviction, which has no sample-size dependency)."""
    conn = _conn_with_phase(launch_signed_off=True, resolved_predictions=0)
    is_live = is_feature_live(
        conn,
        V05Feature.CONTINUOUS_CONVICTION,
        parameter_overrides={V05Feature.CONTINUOUS_CONVICTION: True},
    )
    assert is_live is True


def test_is_feature_live_helper_round_trips():
    conn = _conn_with_phase(launch_signed_off=True, resolved_predictions=100)
    assert is_feature_live(conn, V05Feature.BRIER_HAIRCUT) is True
    conn = _conn_with_phase(launch_signed_off=False)
    assert is_feature_live(conn, V05Feature.BRIER_HAIRCUT) is False
