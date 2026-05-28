"""Conformal-PID controller for Adaptive Conformal Inference (ACI), WS-3.

Classic ACI (Gibbs & Candès 2021) adapts the miscoverage level alpha online:

    alpha_{t+1} = alpha_t + gamma * (alpha_target - err_t)

where err_t = 1 if the realised label fell OUTSIDE the prediction set at step t,
else 0. The Conformal-PID generalisation (Angelopoulos et al. 2024) replaces
the single integral-like step with a full PID law on the coverage error so the
controller reacts to recent error (P), accumulated drift (I), and trend (D).

This controller is intentionally small: it owns only the alpha-update math and
its own integral/prev-error state. The state is serialisable so it round-trips
through CalibrationBuffer.pid_state across restarts. Defaults are conservative
(Kp small, Ki tiny, Kd=0) — the wrapper, not this class, decides coverage.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Conservative defaults — gentle adaptation, no derivative kick by default.
DEFAULT_KP = 0.05
DEFAULT_KI = 0.005
DEFAULT_KD = 0.0

# Keep adapted alpha in a sane open interval so the prediction set never
# degenerates to "always empty" (alpha→1) or "always full" (alpha→0).
ALPHA_MIN = 0.001
ALPHA_MAX = 0.999


@dataclass
class ConformalPID:
    """PID controller on the conformal coverage error.

    Error convention: error_t = alpha_target - miscoverage_indicator_t, where
    miscoverage_indicator_t = 1 if the label was NOT covered. A run of misses
    drives the error negative, which lowers alpha (tightening toward the
    target), and vice-versa.
    """

    alpha_target: float = 0.10
    kp: float = DEFAULT_KP
    ki: float = DEFAULT_KI
    kd: float = DEFAULT_KD
    integral: float = 0.0
    prev_error: float = 0.0

    def update(self, current_alpha: float, covered: bool) -> float:
        """Return the next alpha given the latest coverage outcome.

        Args:
            current_alpha: the alpha used for the just-resolved step.
            covered: True iff the realised label was inside the prediction set.
        Returns:
            the next alpha, clamped to [ALPHA_MIN, ALPHA_MAX].
        """
        miscoverage = 0.0 if covered else 1.0
        error = self.alpha_target - miscoverage
        self.integral += error
        derivative = error - self.prev_error
        self.prev_error = error

        delta = self.kp * error + self.ki * self.integral + self.kd * derivative
        next_alpha = current_alpha + delta
        if next_alpha < ALPHA_MIN:
            next_alpha = ALPHA_MIN
        elif next_alpha > ALPHA_MAX:
            next_alpha = ALPHA_MAX
        return next_alpha

    # ---- serialisation (round-trips through CalibrationBuffer.pid_state) ----

    def to_state(self) -> dict[str, Any]:
        return {
            "kp": self.kp,
            "ki": self.ki,
            "kd": self.kd,
            "integral": self.integral,
            "prev_error": self.prev_error,
        }

    @classmethod
    def from_state(cls, state: dict[str, Any], *, alpha_target: float = 0.10) -> "ConformalPID":
        if not state:
            return cls(alpha_target=alpha_target)
        return cls(
            alpha_target=alpha_target,
            kp=state.get("kp", DEFAULT_KP),
            ki=state.get("ki", DEFAULT_KI),
            kd=state.get("kd", DEFAULT_KD),
            integral=state.get("integral", 0.0),
            prev_error=state.get("prev_error", 0.0),
        )


__all__ = ["ALPHA_MAX", "ALPHA_MIN", "ConformalPID"]
