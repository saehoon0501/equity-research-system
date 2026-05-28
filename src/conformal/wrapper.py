"""Conformal-overlay wrapper (WS-3).

Wraps the OUTPUT of the three overlay classifiers with an Adaptive Conformal
Inference (ACI) / Conformal-PID layer. It does NOT fork or edit the
classifiers — it imports and calls them, then post-processes their result.

The three classifiers return three different shapes and two label vocabularies:

    p8  classify          -> {bin, rf_degenerate, unavailable_reason}
                              labels: positive / neutral / negative / unavailable
    p9  classify_flow     -> {bin, components, unavailable_reason}
                              labels: positive / neutral / negative / unavailable
    p10 classify_reversion-> {bin, components, sub_signal_fires, unavailable_reason}
                              labels: MR_OVERSOLD / MR_NEUTRAL / MR_OVERBOUGHT / MR_UNAVAILABLE

So the wrapper is classifier-agnostic: it takes the classifier callable plus its
label space, and reads the predicted label out of the result via a small
extractor (default: ``result["bin"]``). Nothing about p8's keys is baked in.

Behaviour (LOCKED decisions):
  * alpha = 0.10 (90% coverage target).
  * DISABLED (enabled=False) => returns the SAME object the raw classifier
    returned (``is`` identity), so the regression-identity criterion holds
    bit-for-bit.
  * Abstain precedence when enabled:
      1. calibration buffer < 100 points  -> abstain "calibration_insufficient"
         (covers the wholesale-degrade criterion: no bogus set).
      2. prediction set non-singleton     -> abstain "non_singleton_set".
      3. else                             -> the singleton prediction.
  * Degrade default: advisory-only, never auto-PASS, never silent skip-to-FAIL.
    Abstain carries the nested raw result so callers can still inspect it.

Prediction-set construction uses an injectable nonconformity score. The default
score is binary mismatch (1 if predicted != observed-label else 0); the
conformal quantile of those scores at level (1 - current_alpha) decides which
candidate labels enter the set. WS-4's real continuous scores can be plugged in
later via the ``score_fn`` parameter without touching this module.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence

from src.conformal.buffer import ABSTAIN_MIN_POINTS, CalibrationBuffer
from src.conformal.pid import ConformalPID

# Locked: 90% coverage target.
DEFAULT_ALPHA = 0.10

# A nonconformity score: given (predicted_label, candidate_label) -> float.
# Higher = more nonconforming. Default below is binary mismatch.
ScoreFn = Callable[[Any, Any], float]


def default_score_fn(predicted: Any, label: Any) -> float:
    """Binary nonconformity: 0 if labels agree, 1 otherwise."""
    return 0.0 if predicted == label else 1.0


def _default_extract_label(result: dict[str, Any]) -> Any:
    """Pull the predicted label out of a classifier result dict."""
    return result["bin"]


def _conformal_quantile(scores: Sequence[float], alpha: float) -> float:
    """Split-conformal quantile of calibration scores at level (1 - alpha).

    Uses the finite-sample-corrected rank ceil((n+1)(1-alpha))/n per
    Vovk / Romano-Sesia-Candès. Returns +inf when the rank exceeds n
    (i.e. not enough data to bound the score) so that, in that regime, the
    full label space is admitted — which the wrapper then treats as a
    non-singleton abstain rather than a false-confidence singleton.
    """
    n = len(scores)
    if n == 0:
        return math.inf
    rank = math.ceil((n + 1) * (1.0 - alpha))
    if rank > n:
        return math.inf
    if rank < 1:
        rank = 1
    return sorted(scores)[rank - 1]


@dataclass
class ConformalResult:
    """Wrapper output envelope (enabled path).

    The raw classifier result is nested verbatim under ``raw`` so it stays
    fully inspectable; the wrapper never mutates the raw dict in place.
    """

    raw: dict[str, Any]
    prediction_set: list[Any]
    abstained: bool
    abstain_reason: Optional[str]
    alpha_used: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw": self.raw,
            "prediction_set": list(self.prediction_set),
            "abstained": self.abstained,
            "abstain_reason": self.abstain_reason,
            "alpha_used": self.alpha_used,
        }


class ConformalWrapper:
    """Classifier-agnostic conformal overlay around a classify* output."""

    def __init__(
        self,
        classifier: Callable[..., dict[str, Any]],
        label_space: Sequence[Any],
        *,
        buffer: Optional[CalibrationBuffer] = None,
        enabled: bool = True,
        alpha: float = DEFAULT_ALPHA,
        score_fn: ScoreFn = default_score_fn,
        extract_label: Callable[[dict[str, Any]], Any] = _default_extract_label,
        pid: Optional[ConformalPID] = None,
    ) -> None:
        self.classifier = classifier
        self.label_space = list(label_space)
        self.enabled = enabled
        self.alpha = alpha
        self.score_fn = score_fn
        self.extract_label = extract_label
        self.buffer = buffer if buffer is not None else CalibrationBuffer(
            alpha_target=alpha, current_alpha=alpha
        )
        self.pid = pid if pid is not None else ConformalPID.from_state(
            self.buffer.pid_state, alpha_target=alpha
        )

    # ---- core call --------------------------------------------------------

    def __call__(self, *args: Any, **kwargs: Any):
        """Run the wrapped classifier and apply the conformal layer.

        DISABLED: returns the raw classifier result object unchanged (``is``
        identity preserved) — this is what makes criterion 1 bit-identical.

        ENABLED: returns a ConformalResult envelope (raw nested inside).
        """
        raw = self.classifier(*args, **kwargs)
        if not self.enabled:
            return raw

        predicted = self.extract_label(raw)

        # (1) Insufficient calibration => abstain wholesale, no bogus set.
        if len(self.buffer) < ABSTAIN_MIN_POINTS:
            return ConformalResult(
                raw=raw,
                prediction_set=[],
                abstained=True,
                abstain_reason="calibration_insufficient",
                alpha_used=self.buffer.current_alpha,
            )

        # (2)/(3) Build the conformal prediction set and decide.
        pred_set = self.predict_set(predicted)
        if len(pred_set) != 1:
            return ConformalResult(
                raw=raw,
                prediction_set=pred_set,
                abstained=True,
                abstain_reason="non_singleton_set",
                alpha_used=self.buffer.current_alpha,
            )

        return ConformalResult(
            raw=raw,
            prediction_set=pred_set,
            abstained=False,
            abstain_reason=None,
            alpha_used=self.buffer.current_alpha,
        )

    # ---- conformal machinery ---------------------------------------------

    def predict_set(self, predicted: Any) -> list[Any]:
        """Conformal prediction set for the just-emitted prediction.

        A candidate label enters the set iff its nonconformity score against
        the observed prediction is <= the conformal quantile (at the current,
        PID-adapted alpha) of the calibration scores. Empty calibration =>
        quantile is +inf => every candidate admitted (=> non-singleton =>
        the caller abstains rather than fabricating a singleton).
        """
        cal_scores = [
            self.score_fn(obs["predicted"], obs["label"])
            for obs in self.buffer.observations
        ]
        qhat = _conformal_quantile(cal_scores, self.buffer.current_alpha)
        return [lbl for lbl in self.label_space if self.score_fn(predicted, lbl) <= qhat]

    def observe(self, predicted: Any, label: Any, *, persist: bool = False) -> None:
        """Record a realised (predicted, label) outcome and adapt alpha.

        Updates the calibration buffer, runs the PID alpha-update on the
        coverage outcome, and (optionally) persists the versioned state.
        """
        pred_set = self.predict_set(predicted) if self.buffer.is_ready else []
        covered = label in pred_set if pred_set else False

        self.buffer.add(predicted, label)
        if self.buffer.is_ready:
            self.buffer.current_alpha = self.pid.update(self.buffer.current_alpha, covered)
        self.buffer.pid_state = self.pid.to_state()

        if persist:
            self.buffer.persist()


__all__ = [
    "DEFAULT_ALPHA",
    "ConformalResult",
    "ConformalWrapper",
    "default_score_fn",
]
