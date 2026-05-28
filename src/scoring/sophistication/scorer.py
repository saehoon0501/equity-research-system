"""WS-2 sophistication scorer (Axis B) — ``ScoreProvider`` implementation.

Scores an envelope's ``reasoning_trace[].rationale`` sentences along
Axis B (sophistication):

  * ROSCOE / ReCEval structural proxies (``metrics``),
  * CoT-faithfulness intervention (``faithfulness``),
  * novelty-frontier = perplexity-surprise percentile-vs-rolling-baseline,
    ANDed with grounding (``metrics.novelty_anded_with_grounding``).

Three contractual behaviours (WS-2 acceptance criteria):

  1. ABSTAIN — input with labels but no usable rationale sentences
     (``reasoning_trace`` absent / null / empty / all-blank) returns an
     ABSTAIN result with every numeric score ``None`` and ``abstained:
     True``. Never a silent number.
  2. RELATIVE — ROSCOE/ReCEval are uncalibrated on prose; the meaningful
     output is the percentile-vs-rolling-baseline. The intervention flags
     post-hoc rationalization (``cot_faithfulness_flag``).
  3. NOVELTY-AND-GROUNDING + DEGRADE — high surprise is only rewarded
     when grounded (multiplicative AND); any scorer error degrades to
     ``axis_b = null`` / advisory and NEVER blocks the gate alone.

Output ``scores`` block matches the locked Axis-B shape:
``{roscoe, receval, cot_faithfulness_flag, novelty_percentile, surprise,
mode}`` plus diagnostic keys (``roscoe_raw`` / ``receval_raw`` /
``grounding_credit`` / ``abstained`` / ``degraded`` / ``reason`` /
``model_version``).

WS-6 CONTRACT NOTE — the DEGRADE result is the in-band representation of
"axis_b is null": ``block_name="axis_b"``, ``mode="advisory"``, every
numeric metric ``None``, ``degraded=True``. The hybrid gate (WS-6) MUST
treat this as a null Axis-B block — advisory-only, never an auto-PASS,
never a block-on-its-own. The same all-null/advisory shape is used for
ABSTAIN (``abstained=True``); the two differ only in the diagnostic
flags + ``reason``.

RELATIVE SCORING — ROSCOE/ReCEval/surprise are uncalibrated on prose, so
each is stored as a *percentile vs its rolling baseline* (criterion 2),
NOT as an absolute proxy value. The raw proxy is kept under ``*_raw`` for
diagnostics only. When a metric has no baseline window yet, its percentile
is ``None`` (explicit abstain — no silent absolute number) while the raw
diagnostic is still recorded.
"""
from __future__ import annotations

from typing import Any, Optional, Sequence

# _percentile inlined (src.l4_daily_monitor.drift_detector removed in main's
# reorg). Linear-interpolation percentile, p in [0,100].
def _percentile(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)
from src.scoring.contracts import ScoreResult

from . import faithfulness as _faith
from . import metrics as _metrics
from .seams import (
    BaselineStore,
    PerplexityModel,
    RationaleLM,
    StaticBaselineStore,
    UnavailablePerplexityModel,
)

BLOCK_NAME = "axis_b"
MODE = "advisory"  # WS-2 is advisory-only (locked).

# Numeric keys that are None on abstain/degrade.
_NUMERIC_KEYS = ("roscoe", "receval", "cot_faithfulness_flag", "novelty_percentile", "surprise")


def _null_scores(**extra: Any) -> dict[str, Any]:
    block: dict[str, Any] = {k: None for k in _NUMERIC_KEYS}
    block["mode"] = MODE
    block.update(extra)
    return block


def _percentile_vs_baseline(value: float, history: Sequence[float]) -> Optional[float]:
    """Rank ``value`` against ``history`` as a percentile in [0, 1].

    Returns the fraction of baseline values ``<= value``. Returns ``None``
    when there is no baseline (the absolute value is meaningless on its
    own, so we abstain rather than emit a silent number).
    """
    hist = list(history)
    if not hist:
        return None
    below = sum(1 for h in hist if h <= value)
    return below / len(hist)


def extract_rationales(envelope: dict[str, Any]) -> list[str]:
    """Pull non-blank rationale sentences from ``reasoning_trace``.

    Reads ``reasoning_trace[].rationale`` (natural language), NOT the
    opcode ``reasoning_path_taken``. Returns [] when the trace is
    absent / null / empty / non-list, or when every rationale is blank.
    """
    trace = envelope.get("reasoning_trace")
    if not isinstance(trace, list):
        return []
    out: list[str] = []
    for entry in trace:
        if not isinstance(entry, dict):
            continue
        rationale = entry.get("rationale")
        if isinstance(rationale, str) and rationale.strip():
            out.append(rationale.strip())
    return out


def _evidence_tokens(envelope: dict[str, Any]) -> set[str]:
    """Union of content tokens from the envelope's evidence/ref/framework fields.

    Used to derive grounding: a rationale step is grounded if it shares a
    token with this set. Walks the whole envelope for any *_ref(s) /
    evidence* / framework_keys / cdd_memo_refs string leaves.
    """
    toks: set[str] = set()

    def _walk(obj: Any, key_hint: str = "") -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                _walk(v, str(k))
        elif isinstance(obj, list):
            for v in obj:
                _walk(v, key_hint)
        elif isinstance(obj, str):
            kh = key_hint.lower()
            if any(t in kh for t in ("ref", "evidence", "framework", "cdd")):
                toks.update(_metrics.tokenize(obj))

    _walk(envelope)
    return toks


class SophisticationScorer:
    """Axis-B ``ScoreProvider``.

    All external dependencies are injected via seams so the scorer runs
    fully offline under test:

      * ``perplexity_model`` — version-pinned surprise model. Defaults to
        :class:`UnavailablePerplexityModel` (raises => DEGRADE) because no
        offline model is downloadable here.
      * ``rationale_lm`` — LLM for the CoT-faithfulness intervention.
        When ``None`` the faithfulness flag is left ``None`` (skipped,
        not failed).
      * ``baseline_store`` — rolling surprise baseline for the percentile
        transform. When empty, the novelty signal abstains (percentile is
        meaningless without a baseline) but the rest of the block still
        computes.
    """

    def __init__(
        self,
        *,
        perplexity_model: Optional[PerplexityModel] = None,
        rationale_lm: Optional[RationaleLM] = None,
        baseline_store: Optional[BaselineStore] = None,
    ) -> None:
        self.perplexity_model: PerplexityModel = (
            perplexity_model or UnavailablePerplexityModel()
        )
        self.rationale_lm = rationale_lm
        self.baseline_store: BaselineStore = baseline_store or StaticBaselineStore()

    # -- ScoreProvider ---------------------------------------------------

    def score(self, envelope: dict[str, Any]) -> ScoreResult:
        """Return the Axis-B ``ScoreResult``. Never raises; degrades instead."""
        # Total-degrade guard: a non-dict envelope (None / list / str / ...)
        # cannot be parsed => axis_b null / advisory. Must NOT raise out of
        # score() (mirrors the sibling ArticulationScorer's non-dict guard).
        if not isinstance(envelope, dict):
            return ScoreResult(
                block_name=BLOCK_NAME,
                scores=_null_scores(degraded=True, reason="non_dict_envelope"),
                mode=MODE,
            )

        rationales = extract_rationales(envelope)

        # Criterion 1: label-only / no rationale => ABSTAIN (no silent number).
        if not rationales:
            return ScoreResult(
                block_name=BLOCK_NAME,
                scores=_null_scores(abstained=True, reason="no_rationale"),
                mode=MODE,
            )

        # Criterion 3: any error in the compute body => DEGRADE (advisory,
        # axis_b null, never blocks the gate alone).
        try:
            return self._compute(envelope, rationales)
        except Exception as exc:  # noqa: BLE001 - degrade on ANY scorer error
            return ScoreResult(
                block_name=BLOCK_NAME,
                scores=_null_scores(
                    degraded=True,
                    reason=f"scorer_error:{type(exc).__name__}",
                ),
                mode=MODE,
            )

    # -- internals -------------------------------------------------------

    def _compute(
        self, envelope: dict[str, Any], rationales: Sequence[str]
    ) -> ScoreResult:
        # Structural proxies (deterministic; no self-consistency needed).
        # Their ABSOLUTE values are meaningless (WS-2 spec) — kept only as
        # *_raw diagnostics; what we store is the percentile-vs-baseline.
        roscoe_raw = _metrics.roscoe_proxy(rationales)
        receval_raw = _metrics.receval_proxy(rationales)
        roscoe = _percentile_vs_baseline(
            roscoe_raw, self.baseline_store.history("roscoe")
        )
        receval = _percentile_vs_baseline(
            receval_raw, self.baseline_store.history("receval")
        )

        # CoT-faithfulness intervention (LLM, N=5 @ temp 0.7 median).
        cot_flag: Optional[bool]
        if self.rationale_lm is None:
            cot_flag = None  # skipped, not failed
        else:
            cot_flag = _faith.intervene(rationales, self.rationale_lm)

        # Novelty-frontier: surprise -> percentile-vs-rolling-baseline,
        # then ANDed with grounding. Surprise model may raise (no offline
        # model) -> that bubbles to score()'s degrade handler.
        surprise = float(self.perplexity_model.surprise(" ".join(rationales)))
        surprise_history = list(self.baseline_store.history("surprise"))
        surprise_percentile = _percentile_vs_baseline(surprise, surprise_history)
        # Diagnostic: baseline median via the reused drift-detector util.
        baseline_surprise_p50 = (
            _percentile(surprise_history, 50.0) if surprise_history else None
        )

        grounding = _metrics.grounding_credit(rationales, _evidence_tokens(envelope))

        if surprise_percentile is None:
            novelty_percentile: Optional[float] = None
        else:
            novelty_percentile = _metrics.novelty_anded_with_grounding(
                surprise_percentile, grounding
            )

        scores: dict[str, Any] = {
            # Relative (percentile-vs-baseline) — the meaningful values.
            "roscoe": roscoe,
            "receval": receval,
            "cot_faithfulness_flag": cot_flag,
            "novelty_percentile": novelty_percentile,
            "surprise": surprise,
            "mode": MODE,
            # Diagnostics (NOT the calibrated signal).
            "roscoe_raw": roscoe_raw,
            "receval_raw": receval_raw,
            "grounding_credit": grounding,
            "baseline_surprise_p50": baseline_surprise_p50,
            "model_version": self.perplexity_model.model_version,
            "abstained": False,
            "degraded": False,
        }
        return ScoreResult(block_name=BLOCK_NAME, scores=scores, mode=MODE)


__all__ = ["SophisticationScorer", "extract_rationales", "BLOCK_NAME", "MODE"]
