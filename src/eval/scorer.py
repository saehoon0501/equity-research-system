"""Layer 1 — pure-function scorer for the outer-ring Eval loop.

COMPATIBILITY SHIM (WS-4). The verdict primitives now live canonically in
``src.calibration.scorer``; this module re-exports them so the historical
import surface — ``from src.eval.scorer import Label, ScoreInput, Verdict, score``
(used by tests/unit/eval/test_scorer.py) — keeps working unchanged.

WS-4 replaced the former placeholder rule table by relocating it into the
calibration package alongside the resolver + metrics. The hit/miss semantics are
preserved bit-for-bit; only the home of the definitions moved. The operator
``/review-me`` rule-table refinement (spec sec 5.2) still applies and is now
tracked against ``src.calibration.scorer``.

Per docs/superpowers/specs/2026-05-23-ring-architecture-and-layer1-scaffold-design.md sec 5.
"""

from src.calibration.scorer import Label, ScoreInput, Verdict, score

__all__ = ["Label", "ScoreInput", "Verdict", "score"]
