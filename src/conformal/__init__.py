"""Conformal overlay wrapper (WS-3) for the insight-quality enhancement.

Wraps the three overlay classifier outputs
(src.p8_tactical_overlay...classify, src.p9_flow_overlay...classify_flow,
src.p10_reversion_overlay...classify_reversion) with an Adaptive Conformal
Inference / Conformal-PID layer. It does not fork or edit the classifiers.

Public API:
  * ConformalWrapper   — the classifier-agnostic overlay (disable for identity).
  * ConformalResult    — the enabled-path output envelope (raw nested inside).
  * CalibrationBuffer  — versioned, restart-surviving calibration store.
  * ConformalPID       — PID controller on the conformal coverage error.

Depends on WS-4 (src/calibration/) ONLY for the long-run coverage criterion,
which is deferred (see tests/unit/conformal/test_conformal_wrapper.py xfail).
"""
from __future__ import annotations

from src.conformal.buffer import (
    ABSTAIN_MIN_POINTS,
    SCHEMA_VERSION,
    CalibrationBuffer,
)
from src.conformal.pid import ConformalPID
from src.conformal.wrapper import (
    DEFAULT_ALPHA,
    ConformalResult,
    ConformalWrapper,
    default_score_fn,
)

__all__ = [
    "ABSTAIN_MIN_POINTS",
    "DEFAULT_ALPHA",
    "SCHEMA_VERSION",
    "CalibrationBuffer",
    "ConformalPID",
    "ConformalResult",
    "ConformalWrapper",
    "default_score_fn",
]
