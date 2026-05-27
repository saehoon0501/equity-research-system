"""ArticulationScorer — WS-1 Axis-A orchestrator implementing ScoreProvider.

Composes the five sub-metrics into the ``axis_a`` block:

  - faithfulness + answer_relevancy  (RAGAS, LLM, cached, N=5)   [faithfulness.py]
  - citation precision/recall        (ALCE, DETERMINISTIC)        [citation.py]
  - factuality_precision             (VERISCORE, LLM, N=5)        [veriscore.py]
  - coherence                        (UNION, pinned local model)  [coherence.py]
  - clarity                          (G-Eval, advisory only)      [clarity.py]

CONTRACTS (Phase 0):
  - Implements ``src.scoring.contracts.ScoreProvider`` structurally:
    ``score(envelope) -> ScoreResult`` with ``block_name="axis_a"``.
  - Returns the ScoreResult; does NOT mutate the envelope. The caller
    writes ``result["scores"]`` into ``envelope["axis_a"]``.

CONTRACT — FLAT axis_a block (canonical, criterion 1):
  The ``scores`` payload is FLAT with these 8 canonical top-level keys, all
  bare scalars (matching tests/fixtures/golden_score_blocks/*.json and the
  consumer src/p4_debate/_bon_mav.py ``composite_quality``, which reads
  ``axis_a["faithfulness"]`` directly as a number):

      faithfulness, answer_relevancy, citation_precision, citation_recall,
      veriscore, coherence, clarity   (float | None each)   +   mode (str)

  A degraded sub-metric contributes ``None`` for its scalar key(s) — NEVER a
  fabricated number. Rich per-metric diagnostics (claim counts, self-
  consistency samples, methods, model_version, ...) are preserved under the
  single non-canonical key ``_diagnostics`` (AXIS_SCHEMA is permissive,
  additionalProperties=True, so extra keys are fine). ``scorer_version`` and
  ``errors`` are also top-level non-canonical keys.

DEGRADE (LOCKED, criterion 4):
  - Each sub-metric is run inside ``_safe`` — on ANY exception the
    sub-metric's scalar(s) are set to ``None`` and the error recorded under
    ``axis_a.errors[<metric>]``. The scorer NEVER raises out of ``score``.
  - ``mode`` is always ``"advisory"`` at the block level: axis_a never
    blocks the gate alone; never auto-PASS; never silent skip-to-FAIL.
  - TOTAL failure (e.g. envelope is not a dict): ``score`` returns a dict
    with every canonical scalar ``None``, ``mode="advisory"`` and
    ``degraded=True`` — i.e. an all-null FLAT block — NOT ``scores=None``.
    This mirrors the WS-2 sibling scorer (src/scoring/sophistication) so
    both axis scorers share one total-degrade shape; the ScoreResult
    ``scores`` field stays a dict as its TypedDict declares, and every
    documented consumer (``composite_quality`` does ``.get("axis_a") or {}``
    then ``axis_a.get("faithfulness")``) handles it uniformly.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from src.scoring.contracts import ScoreResult

from .citation import score_citation
from .clarity import score_clarity
from .coherence import CoherenceRunner, score_coherence
from .faithfulness import LLMCaller, score_faithfulness
from .veriscore import score_veriscore

BLOCK_NAME = "axis_a"
SCORER_MODE = "advisory"  # WS-1: axis_a is advisory; never gates alone.
SCORER_VERSION = "ws1-articulation-v1"

# The 8 canonical FLAT keys consumers read (golden fixture contract). Seven
# are numeric scalars (float | None); ``mode`` is the advisory flag.
CANONICAL_NUMERIC_KEYS = (
    "faithfulness",
    "answer_relevancy",
    "citation_precision",
    "citation_recall",
    "veriscore",
    "coherence",
    "clarity",
)


def _null_flat_scores(**extra: Any) -> dict[str, Any]:
    """All-null FLAT axis_a block (total-degrade shape; mirrors WS-2)."""
    block: dict[str, Any] = {k: None for k in CANONICAL_NUMERIC_KEYS}
    block["mode"] = SCORER_MODE
    block.update(extra)
    return block


def _safe(name: str, fn: Callable[[], Any], errors: dict[str, str]) -> Optional[Any]:
    """Run a sub-metric; on ANY failure record the error and return None.

    This is the degrade primitive (criterion 4). It guarantees the scorer
    never raises and that a failed sub-metric becomes a null block entry
    rather than blocking or auto-passing.
    """
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 - degrade is intentionally catch-all
        errors[name] = f"{type(e).__name__}: {e}"
        return None


class ArticulationScorer:
    """Axis-A articulation ScoreProvider (WS-1).

    Args (all injectable for offline/deterministic tests):
        faithfulness_llm: ``(system,user,model,temp,sample_index)->dict``
                          seam for RAGAS faithfulness/relevancy.
        veriscore_llm:    seam for VERISCORE.
        clarity_llm:      seam for G-Eval clarity.
        coherence_runner: ``text->float`` local-model seam for UNION coherence.

    When a seam is None the corresponding sub-metric uses its real
    (cached, default-OFF) caller — which, offline, degrades to null.
    """

    def __init__(
        self,
        *,
        faithfulness_llm: Optional[LLMCaller] = None,
        veriscore_llm: Optional[LLMCaller] = None,
        clarity_llm: Optional[LLMCaller] = None,
        coherence_runner: Optional[CoherenceRunner] = None,
    ) -> None:
        self._faithfulness_llm = faithfulness_llm
        self._veriscore_llm = veriscore_llm
        self._clarity_llm = clarity_llm
        self._coherence_runner = coherence_runner

    # -- inputs -----------------------------------------------------------

    @staticmethod
    def _answer_text(envelope: dict[str, Any]) -> str:
        """Best-effort articulated-text extraction from an envelope.

        Concatenates the common free-text fields agents emit. Stays
        permissive: missing fields contribute nothing rather than raising.
        """
        parts: list[str] = []
        for key in (
            "thesis",
            "rationale",
            "summary",
            "narrative",
            "key_insight",
            "disposition_rationale",
        ):
            v = envelope.get(key)
            if isinstance(v, str) and v.strip():
                parts.append(v.strip())
        rt = envelope.get("reasoning_trace")
        if isinstance(rt, list):
            for step in rt:
                if isinstance(step, dict) and isinstance(step.get("rationale"), str):
                    parts.append(step["rationale"])
        return "\n".join(parts)

    # -- ScoreProvider ----------------------------------------------------

    def score(
        self,
        envelope: dict[str, Any],
        *,
        grounding: str = "",
        supported_frameworks: Optional[set[str]] = None,
    ) -> ScoreResult:
        """Score Axis A for ``envelope``. Never raises (degrade contract).

        Args:
            envelope:  the agent envelope dict (read-only; not mutated).
            grounding: retrieved grounding text (evidence_documents.raw_text)
                       for faithfulness/veriscore. Offline this is a fixture.
            supported_frameworks: framework keys grounded in the evidence
                       index, for the DETERMINISTIC citation P/R. In
                       production resolved from evidence_documents; offline a
                       fixture. Defaults to empty set (=> recall 0.0).

        Returns:
            ScoreResult: block_name="axis_a", mode="advisory", scores=the
            FLAT axis_a payload (8 canonical scalar keys). On total failure
            the payload is an all-null FLAT block with ``degraded=True`` —
            NOT ``None`` (mirrors the WS-2 sibling; see module docstring).
        """
        errors: dict[str, str] = {}

        # Total-degrade guard: a non-dict envelope => all-null FLAT block.
        if not isinstance(envelope, dict):
            return ScoreResult(
                block_name=BLOCK_NAME,
                scores=_null_flat_scores(
                    degraded=True,
                    scorer_version=SCORER_VERSION,
                    errors={"envelope": "envelope is not a dict"},
                ),
                mode=SCORER_MODE,
            )

        answer = _safe("answer_extract", lambda: self._answer_text(envelope), errors) or ""
        supported = supported_frameworks if supported_frameworks is not None else set()

        # BUG 2 guard: without grounding, RAGAS faithfulness judges every
        # claim unsupported and returns a fabricated ~0.0 — a WRONG real
        # score. When grounding is absent/empty, faithfulness (and
        # answer_relevancy, which is judged in the same grounded pass)
        # must DEGRADE to null (advisory), not score 0.0.
        if not grounding or not grounding.strip():
            faith = None
            errors["faithfulness"] = (
                "grounding absent/empty — faithfulness degraded to advisory "
                "null (not fabricated 0.0)"
            )
        else:
            faith = _safe(
                "faithfulness",
                lambda: score_faithfulness(
                    answer, grounding, llm_caller=self._faithfulness_llm
                ),
                errors,
            )
        citation = _safe(
            "citation",
            lambda: score_citation(envelope, supported),
            errors,
        )
        veri = _safe(
            "veriscore",
            lambda: score_veriscore(answer, grounding, llm_caller=self._veriscore_llm),
            errors,
        )
        coher = _safe(
            "coherence",
            lambda: score_coherence(answer, model_runner=self._coherence_runner),
            errors,
        )
        clar = _safe(
            "clarity",
            lambda: score_clarity(answer, llm_caller=self._clarity_llm),
            errors,
        )

        # FLAT canonical block (BUG 1 fix): hoist sub-block scalars to the
        # top level. Each scalar is the metric value or None on degrade —
        # never a fabricated number. Rich per-metric diagnostics go under the
        # single non-canonical ``_diagnostics`` key (schema is permissive).
        scores: dict[str, Any] = {
            "faithfulness": faith.faithfulness if faith is not None else None,
            "answer_relevancy": faith.answer_relevancy if faith is not None else None,
            "citation_precision": citation.precision if citation is not None else None,
            "citation_recall": citation.recall if citation is not None else None,
            "veriscore": veri.factuality_precision if veri is not None else None,
            "coherence": coher.coherence if coher is not None else None,
            "clarity": clar.clarity if clar is not None else None,
            "mode": SCORER_MODE,
            "scorer_version": SCORER_VERSION,
            "errors": errors,
            "_diagnostics": {
                "faithfulness": faith.to_block() if faith is not None else None,
                "citation": citation.to_block() if citation is not None else None,
                "veriscore": veri.to_block() if veri is not None else None,
                "coherence": coher.to_block() if coher is not None else None,
                "clarity": clar.to_block() if clar is not None else None,
            },
        }
        return ScoreResult(block_name=BLOCK_NAME, scores=scores, mode=SCORER_MODE)
