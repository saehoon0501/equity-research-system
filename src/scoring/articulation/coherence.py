"""UNION coherence (WS-1, Axis A) — pinned LOCAL model (version-pinned).

UNION-style coherence scores whether the long-form output hangs together
as a single coherent argument (vs locally-fluent but globally-incoherent
text). Per spec this runs on a PINNED LOCAL model — the model VERSION is
stamped via ``src/llm_cache.pin_resolved_model`` so the emission records
exactly which resolved id produced the score.

OFFLINE REALITY / DEGRADE (spec-mandated): there is no local coherence
model server reachable in CI / offline. The default ``model_runner`` is
None; when no runner is supplied this module raises
``ArticulationMetricError`` so the caller writes ``axis_a.coherence =
None`` and stays advisory. A test injects a stub runner to exercise the
populated path. This is the exact degrade behaviour WS-1 requires
(advisory-only on failure; never auto-PASS, never silent skip-to-FAIL).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from src.llm_cache import pin_resolved_model

from .faithfulness import ArticulationMetricError

COHERENCE_METHOD = "union-coherence-v1"
# Pinned local model alias → resolved version stamped into the block.
COHERENCE_MODEL = "union-coherence-local-1.0"

# A local model runner: ``(text) -> float in [0,1]``.
CoherenceRunner = Callable[[str], float]


@dataclass
class CoherenceScore:
    coherence: float
    model_version: str
    method: str = COHERENCE_METHOD
    mode: str = "advisory"

    def to_block(self) -> dict[str, Any]:
        return {
            "coherence": self.coherence,
            "model_version": self.model_version,
            "method": self.method,
            "mode": self.mode,
        }


def score_coherence(
    text: str,
    *,
    model: str = COHERENCE_MODEL,
    model_runner: Optional[CoherenceRunner] = None,
) -> CoherenceScore:
    """UNION coherence on a version-pinned local model.

    Args:
        text:         the long-form output to score.
        model:        the local model alias/id (version-pinned in the block).
        model_runner: callable ``text -> float``. When None (offline default)
                      raises ArticulationMetricError → caller degrades to null.

    The resolved model version is stamped via ``pin_resolved_model`` so the
    record is reproducible even though the model itself runs locally.
    """
    resolved = pin_resolved_model(model)
    if model_runner is None:
        raise ArticulationMetricError(
            "UNION coherence local model unavailable offline "
            f"(pinned={resolved}); degrade to advisory-null"
        )
    try:
        raw = float(model_runner(text))
    except ArticulationMetricError:
        raise
    except Exception as e:
        raise ArticulationMetricError(f"coherence runner failed: {e}") from e
    score = min(1.0, max(0.0, raw))
    return CoherenceScore(coherence=score, model_version=resolved)
