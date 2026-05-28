"""Structural reasoning-quality proxies + grounding for WS-2.

IMPORTANT — these are *proxies*, not the literature implementations of
ROSCOE (Golovneva et al., 2023) or ReCEval (Prasad et al., 2023). The
offline runtime has no numpy / torch / transformers / nltk, and per the
WS-2 spec ROSCOE/ReCEval are uncalibrated on analytical prose so their
ABSOLUTE values are meaningless — only the percentile-vs-rolling-baseline
transform applied downstream is semantically meaningful. These functions
give a deterministic, stdlib-only structural signal (lexical cohesion,
redundancy penalty, premise→conclusion overlap) so the pipeline has a
number to rank; do not read them as faithful metric reproductions.
"""
from __future__ import annotations

import re
from typing import Iterable, Sequence

_TOKEN_RE = re.compile(r"[a-z0-9]+")
# Very small closed-class stoplist — kept tiny on purpose (no nltk).
_STOP = frozenset(
    "the a an of to and or in on for with is are was were be been being "
    "this that these those it its as at by from into per via not no yes "
    "pct vs".split()
)


def tokenize(text: str) -> list[str]:
    """Lowercase content-word tokens (digits kept; tiny stoplist removed)."""
    return [t for t in _TOKEN_RE.findall((text or "").lower()) if t not in _STOP]


def _jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 0.0
    union = sa | sb
    if not union:
        return 0.0
    return len(sa & sb) / len(union)


def roscoe_proxy(steps: Sequence[str]) -> float:
    """Structural cohesion proxy in [0, 1] (ROSCOE-flavoured).

    Mean step-to-step lexical cohesion (consecutive steps should share
    *some* but not be identical) minus a redundancy penalty for
    near-duplicate adjacent steps. A single step (or none) yields 0.0 —
    there is no chain to score.
    """
    toks = [tokenize(s) for s in steps]
    toks = [t for t in toks if t]
    if len(toks) < 2:
        return 0.0
    cohesions: list[float] = []
    for prev, cur in zip(toks, toks[1:]):
        j = _jaccard(prev, cur)
        # Penalise exact-duplicate adjacency (no progress in the chain).
        if j >= 0.95:
            j = 0.0
        cohesions.append(j)
    raw = sum(cohesions) / len(cohesions)
    # Squash gently so the proxy spreads across [0,1] rather than hugging 0.
    return max(0.0, min(1.0, raw * 2.0))


def receval_proxy(steps: Sequence[str]) -> float:
    """Premise→conclusion entailment proxy in [0, 1] (ReCEval-flavoured).

    Approximates "is the conclusion supported by the preceding steps" via
    the lexical overlap between the final step (conclusion) and the union
    of all prior steps (premises). High overlap => the conclusion's terms
    are grounded in the chain; near-zero overlap => a non-sequitur leap.
    """
    toks = [tokenize(s) for s in steps]
    toks = [t for t in toks if t]
    if len(toks) < 2:
        return 0.0
    premises: set[str] = set()
    for t in toks[:-1]:
        premises.update(t)
    conclusion = set(toks[-1])
    if not conclusion:
        return 0.0
    supported = len(conclusion & premises) / len(conclusion)
    return max(0.0, min(1.0, supported))


def grounding_credit(steps: Sequence[str], evidence_tokens: Iterable[str]) -> float:
    """Fraction of rationale steps that reference the envelope's evidence.

    "Grounding" is derived from the envelope itself: a step is grounded
    if its rationale shares at least one content token with the union of
    the envelope's evidence / reference / framework tokens. Returns a
    value in [0, 1]. When there is no evidence to reference at all, every
    step is ungrounded (0.0) — surprising-but-unsupported reasoning must
    not earn novelty credit.
    """
    ev = set(evidence_tokens)
    real = [tokenize(s) for s in steps]
    real = [t for t in real if t]
    if not real:
        return 0.0
    if not ev:
        return 0.0
    grounded = sum(1 for t in real if ev & set(t))
    return grounded / len(real)


def novelty_anded_with_grounding(
    surprise_percentile: float, grounding: float
) -> float:
    """Combine novelty (surprise percentile) with grounding via an AND.

    novelty_frontier = surprise_percentile * grounding_credit

    Multiplicative AND: a high surprise percentile is only rewarded to
    the extent the reasoning is grounded. A high-surprise / zero-grounding
    rationale collapses toward 0 — exactly the "surprising-but-unsupported
    must not score high" requirement (criterion 3). Inputs are clamped to
    [0, 1].
    """
    sp = max(0.0, min(1.0, surprise_percentile))
    g = max(0.0, min(1.0, grounding))
    return sp * g


__all__ = [
    "tokenize",
    "roscoe_proxy",
    "receval_proxy",
    "grounding_credit",
    "novelty_anded_with_grounding",
]
