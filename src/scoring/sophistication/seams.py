"""Injection seams for the WS-2 sophistication scorer.

The scorer depends on three external capabilities that are NOT available
as offline, version-pinned implementations in this environment:

  * a local perplexity / "surprise" model (novelty-frontier signal),
  * an LLM that can re-derive a conclusion from reasoning steps (used by
    the CoT-faithfulness intervention),
  * a rolling baseline of historical surprise scores (for the
    percentile-vs-baseline transform).

Each is expressed here as a small ``Protocol`` so the scorer can be
exercised fully offline by injecting fakes. The production wiring (a
real version-pinned model, the persisted baseline store) lands behind
these same seams without touching the scorer body.

NOTE (blocker): no offline version-pinned perplexity model is downloadable
in this environment. ``UnavailablePerplexityModel`` is the default and
raises; callers MUST inject a concrete model. The novelty-AND-grounding
logic remains fully testable via an injected stub (see tests).
"""
from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable


@runtime_checkable
class PerplexityModel(Protocol):
    """Version-pinned local model exposing a per-text surprise score.

    ``model_version`` MUST be a concrete, pinned id (not a moving alias),
    so a run can stamp exactly which model produced the surprise numbers.
    ``surprise`` returns a non-negative float (higher = more surprising /
    novel); the scorer treats it as an uncalibrated raw signal and only
    ever uses its *percentile vs a rolling baseline*.
    """

    @property
    def model_version(self) -> str:  # pragma: no cover - interface
        ...

    def surprise(self, text: str) -> float:  # pragma: no cover - interface
        ...


@runtime_checkable
class RationaleLM(Protocol):
    """LLM seam for the CoT-faithfulness intervention.

    ``conclude`` takes an ordered list of reasoning-step rationale
    sentences and returns the conclusion the model would draw from them.
    The intervention perturbs one step and checks whether ``conclude``'s
    output *responds* to the perturbation; a conclusion that is invariant
    to a material perturbation signals post-hoc rationalization.

    Implementations route through ``src.llm_cache.cached_call_messages``
    so self-consistency samples cache distinctly.
    """

    @property
    def model_version(self) -> str:  # pragma: no cover - interface
        ...

    def conclude(self, steps: Sequence[str], *, sample_index: int = 0) -> str:  # pragma: no cover - interface
        ...


@runtime_checkable
class BaselineStore(Protocol):
    """Rolling baseline of historical scores, per metric.

    ROSCOE/ReCEval/surprise are all uncalibrated on analytical prose, so
    none of their ABSOLUTE values is meaningful (WS-2 spec); the scorer
    only ever stores each as a *percentile vs this rolling baseline*.
    ``history(metric)`` returns the window of prior raw values for
    ``metric`` (one of ``"roscoe"`` / ``"receval"`` / ``"surprise"``).
    An empty window means "no baseline yet" for that metric — the scorer
    abstains from that metric's percentile (stores ``None`` + a raw
    diagnostic) rather than emit a meaningless absolute number.
    """

    def history(self, metric: str) -> Sequence[float]:  # pragma: no cover - interface
        ...


class UnavailablePerplexityModel:
    """Default :class:`PerplexityModel` — raises until a real model is injected.

    A version-pinned local perplexity model is not downloadable offline in
    this environment (declared blocker). This default makes the missing
    dependency explicit (fail loud at the seam) instead of silently
    fabricating a surprise number. The scorer catches this and DEGRADES
    (advisory-only, axis_b=null) rather than blocking.
    """

    _MODEL_VERSION = "UNAVAILABLE-no-offline-perplexity-model"

    @property
    def model_version(self) -> str:
        return self._MODEL_VERSION

    def surprise(self, text: str) -> float:  # noqa: ARG002
        raise NotImplementedError(
            "No offline version-pinned perplexity model available; inject a "
            "concrete PerplexityModel implementation."
        )


class StaticBaselineStore:
    """Trivial :class:`BaselineStore` backed by per-metric in-memory lists.

    Useful for tests and for callers that already hold the rolling windows
    in memory. Production may swap a DB-backed store behind the same seam.

    Construct either with explicit per-metric windows
    (``roscoe=[...], receval=[...], surprise=[...]``) or — for backward
    convenience — with a single positional window that is used for the
    ``surprise`` metric (the others default to empty).
    """

    def __init__(
        self,
        surprise: Sequence[float] | None = None,
        *,
        roscoe: Sequence[float] | None = None,
        receval: Sequence[float] | None = None,
    ) -> None:
        self._windows: dict[str, list[float]] = {
            "surprise": list(surprise or []),
            "roscoe": list(roscoe or []),
            "receval": list(receval or []),
        }

    def history(self, metric: str) -> Sequence[float]:
        return list(self._windows.get(metric, []))


__all__ = [
    "PerplexityModel",
    "RationaleLM",
    "BaselineStore",
    "UnavailablePerplexityModel",
    "StaticBaselineStore",
]
