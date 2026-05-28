"""The src/eval/scorer.py shim must re-export the calibration scorer identically."""

from __future__ import annotations

import src.calibration.scorer as cal
import src.eval.scorer as shim


class TestShimIdentity:
    def test_symbols_are_the_same_objects(self):
        assert shim.Label is cal.Label
        assert shim.Verdict is cal.Verdict
        assert shim.ScoreInput is cal.ScoreInput
        assert shim.score is cal.score

    def test_score_delegates(self):
        inp = cal.ScoreInput(label=cal.Label.BUY, excess_return_pct=5.0, margin_pct=2.0)
        assert shim.score(inp) is cal.Verdict.HIT
        inp2 = cal.ScoreInput(label=cal.Label.SELL, excess_return_pct=5.0, margin_pct=2.0)
        assert shim.score(inp2) is cal.Verdict.MISS
