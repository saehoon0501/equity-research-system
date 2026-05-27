"""Phase-2 envelope enrichment adapter — the single scorer integration seam.

Runs the WS-1 ``ArticulationScorer`` (axis A) + WS-2 ``SophisticationScorer``
(axis B) on an emitted envelope and returns the FLAT ``axis_a`` / ``axis_b``
blocks to splice onto it.

This is the ONE place the scorers are invoked in the pipeline. Both consumers
go through it:
  * the orchestrator post-step (P2-A) enriches the persisted envelope file;
  * WS-5 BoN ``composite_quality`` (P2-D) scores each synthesis candidate.

Design contract:
  * NEVER raises and NEVER blocks — both scorers already degrade to an
    all-null advisory block on any error; this adapter adds defence-in-depth
    so a programming error in a scorer still yields an advisory-null block
    rather than propagating.
  * Does NOT mutate the input envelope.
  * All scorer dependencies are injectable. With no seams supplied, both
    scorers construct their default (cached, default-OFF) callers, which
    offline degrade to null — so enrichment is deterministic and offline-safe.

The two WS-1 inputs that production resolves from ``evidence_documents``
(``grounding`` text + ``supported_frameworks`` set) are passed in explicitly;
``resolve_grounding`` is the live seam that fetches them from the DB, kept
separate so ``enrich_axes`` stays pure and unit-testable with fixtures.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from src.scoring.articulation.scorer import ArticulationScorer
from src.scoring.sophistication.scorer import SophisticationScorer

ADAPTER_VERSION = "p2-enrichment-1"


def _advisory_null(block_name: str) -> dict[str, Any]:
    """A minimal all-null advisory block used when a scorer cannot be run."""
    return {
        "mode": "advisory",
        "degraded": True,
        "reason": "enrichment_unavailable",
        "scorer_version": ADAPTER_VERSION,
    }


def _scores_or_null(result: Any, block_name: str) -> dict[str, Any]:
    """Extract the flat scores dict from a ScoreResult (TypedDict), or null.

    ScoreResult is a TypedDict, so it is a plain dict at runtime: read
    ``result["scores"]``. A None/absent scores payload (older total-degrade
    convention) maps to an advisory-null block so consumers never see None.
    """
    if isinstance(result, dict):
        scores = result.get("scores")
        if isinstance(scores, dict):
            return scores
    return _advisory_null(block_name)


def enrich_axes(
    envelope: dict[str, Any],
    *,
    articulation: Optional[ArticulationScorer] = None,
    sophistication: Optional[SophisticationScorer] = None,
    grounding: str = "",
    supported_frameworks: Optional[set[str]] = None,
) -> dict[str, dict[str, Any]]:
    """Return ``{"axis_a": <flat block>, "axis_b": <flat block>}`` for ``envelope``.

    Pure (does not mutate ``envelope``). Both blocks are advisory; on any
    scorer degrade the corresponding block is an all-null flat block — never
    ``None``, never raised.
    """
    art = articulation if articulation is not None else ArticulationScorer()
    soph = sophistication if sophistication is not None else SophisticationScorer()

    try:
        a_result = art.score(
            envelope, grounding=grounding, supported_frameworks=supported_frameworks
        )
        axis_a = _scores_or_null(a_result, "axis_a")
    except Exception:  # noqa: BLE001 - defence in depth; never propagate
        axis_a = _advisory_null("axis_a")

    try:
        b_result = soph.score(envelope)
        axis_b = _scores_or_null(b_result, "axis_b")
    except Exception:  # noqa: BLE001
        axis_b = _advisory_null("axis_b")

    return {"axis_a": axis_a, "axis_b": axis_b}


def enrich_envelope(
    envelope: dict[str, Any],
    **kwargs: Any,
) -> dict[str, Any]:
    """Return a NEW envelope dict with ``axis_a``/``axis_b`` spliced in.

    Non-mutating. A non-dict envelope is returned unchanged (the caller's
    validation step owns the not-a-dict failure; enrichment never raises).
    """
    if not isinstance(envelope, dict):
        return envelope
    out = dict(envelope)
    out.update(enrich_axes(envelope, **kwargs))
    return out


# --- live grounding seam (NOT used offline) --------------------------------

GroundingResolver = Callable[[dict[str, Any]], "tuple[str, set[str]]"]


def resolve_grounding(
    envelope: dict[str, Any],
    *,
    fetch: Optional[GroundingResolver] = None,
) -> tuple[str, set[str]]:
    """Resolve ``(grounding_text, supported_frameworks)`` for WS-1.

    The ``fetch`` callable is the live seam that queries ``evidence_documents``
    by the envelope's ``evidence_index_refs`` (joined on ``source_uri``).
    Offline / without ``fetch`` this returns ``("", set())`` — WS-1 then
    degrades faithfulness to null (it will NOT fabricate a 0.0; see the WS-1
    grounding-absent guard). The actual DB query is wired at the live
    integration boundary, not here.
    """
    if fetch is None:
        return "", set()
    try:
        text, frameworks = fetch(envelope)
        return (text or ""), (set(frameworks) if frameworks else set())
    except Exception:  # noqa: BLE001 - grounding failure must not break scoring
        return "", set()
