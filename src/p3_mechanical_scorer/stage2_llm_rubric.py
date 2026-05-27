"""Stage 2 — LLM rubric (INFORMATION-ISOLATED from Stage 1).

Per spec Section 4.3 (lines 381-387)::

    Stage 2 (LLM rubric, INFORMATION-ISOLATED from Stage 1):
      - Per-pattern single-attribute call (anchoring-bias mitigation)
      - 3-level ordinal {LOW, MEDIUM, HIGH} -> {0.0, 0.5, 1.0}
      - Forced JSON: {rating, confidence, evidence_quotes[],
                      rationale (<=2 sentences), defer_to_human,
                      tie_break_applied}
      - Required verbatim evidence (no quote -> defaults to LOW)
      - Self-consistency N=5 samples at temp=0.7; median rating
      - Stage 2 LLM does NOT see Stage 1 mechanical output

Information isolation is the load-bearing property: per Section 5 Q1
lock + L8 finding, anchoring-bias mitigation requires the LLM see
*only* the source-evidence corpus and the per-pattern rubric — never
the Stage 1 / Stage 1B numerical/categorical outcomes. We enforce this
in three places:

1. The :func:`build_prompt` function takes ONLY ``ticker``, ``pattern``,
   and ``evidence_corpus``. There is no parameter that could carry
   Stage 1 output. This is enforced at the type level.
2. The orchestrator constructs Stage 2 inputs from the source-evidence
   corpus directly (never from Stage 1 outputs); this is asserted in
   ``orchestrator.score_ticker``.
3. The audit row written for Stage 2 includes the literal flag
   ``saw_rule_output: false``. Stage 3 linter checks this flag and
   raises an integrity error if it is missing or true.

Patterns scored at Stage 2 (Section 4.3)::

    L3-e #4    Pivot-creates-multi-bag (qualitative)
    L3-e #20   Right-thing-right-decade
    L3-e #5    Founder equity stake (qualitative)
    L3-e #16   Narrative reflexivity (CONTESTED)
    L3-e #18   Cultural transmission across CEO transitions (CONTESTED)
    L3-e #19   Founder mystique without execution (NEGATIVE signal)

(The "qualitative" subset of #4/#5 captures cases where the mechanical
boolean in Stage 1B is True but the qualitative strength varies; e.g.,
Bezos pivot AMZN->AWS is HIGH-strength while a typical SaaS pivot is
MEDIUM. Stage 2's rating is the qualitative depth-rating.)
"""

from __future__ import annotations

import json
import logging
import os
import statistics
from collections import Counter
from dataclasses import dataclass
from typing import Optional

from . import (
    DEFAULT_MODEL,
    HIGH_STAKES_MODEL,
    LLM_PROMPT_VERSION,
    RATING_HIGH,
    RATING_LOW,
    RATING_MEDIUM,
    RATING_TO_SCORE,
    SELF_CONSISTENCY_N,
    SELF_CONSISTENCY_TEMP,
)

_LOG = logging.getLogger(__name__)


# Patterns scored at Stage 2 — each is a single-attribute rubric call.
# Mark `contested=True` for patterns flagged CONTESTED in L3-e (Section B);
# these auto-route to high-stakes (Opus) per Section 4.5 model constraint.
@dataclass(frozen=True)
class PatternRubric:
    pattern_id: str
    title: str
    one_line_question: str
    contested: bool = False
    rubric_anchors: tuple = ()  # 3 strings (LOW/MEDIUM/HIGH anchors)


PATTERNS_TO_SCORE: tuple = (
    PatternRubric(
        pattern_id="L3-e-04",
        title="Pivot-creates-multi-bag (qualitative)",
        one_line_question=(
            "Does the company's primary value-creation come from a "
            "post-original-product pivot (AWS-style), or is it still "
            "extracting value from the original idea?"
        ),
        rubric_anchors=(
            "LOW: company is still entirely defined by its original product; "
            "no pivot evidence.",
            "MEDIUM: company has begun pivoting; new product line is growing "
            "but original product still dominates revenue/profit.",
            "HIGH: company's largest value driver is now the pivot, NOT the "
            "original product (AMZN->AWS, NVDA->AI infra, MSFT->Azure).",
        ),
    ),
    PatternRubric(
        pattern_id="L3-e-20",
        title="Right-thing-right-decade",
        one_line_question=(
            "Does the company structurally capture (not merely trade exposure "
            "to) the dominant macro / infra-stack era it operates in?"
        ),
        rubric_anchors=(
            "LOW: era-mismatched (Pets.com analogue) OR trades exposure to a "
            "secular shift without structurally capturing it (COIN-as-Bitcoin-"
            "proxy).",
            "MEDIUM: aligned with era but not the structural capture point; "
            "could be displaced by a more direct capturer.",
            "HIGH: structurally captures the era-defining shift (CUDA-AI, "
            "AWS-cloud, mobile-OS); displacement requires regime change.",
        ),
    ),
    PatternRubric(
        pattern_id="L3-e-05",
        title="Founder equity stake (qualitative)",
        one_line_question=(
            "Beyond the bare 5% threshold, is the founder/CEO equity stake "
            "qualitatively aligned with multi-bag-period discipline?"
        ),
        rubric_anchors=(
            "LOW: founder has exited or is exiting; equity stake declining "
            "or symbolic; signs of value-extraction (e.g., personal-loan "
            "patterns, large secondary sales near peak).",
            "MEDIUM: founder retains stake but no clear discipline signal; "
            "stake static; capital allocation ambiguous.",
            "HIGH: founder retains substantial stake AND has visible "
            "long-horizon discipline (Outsiders-style buybacks, per-share "
            "value letters, no peak-selling).",
        ),
    ),
    PatternRubric(
        pattern_id="L3-e-16",
        title="Narrative reflexivity (CONTESTED)",
        one_line_question=(
            "Is the current price-narrative loop reflexive in a way that "
            "could collapse if execution fails to validate the story?"
        ),
        contested=True,
        rubric_anchors=(
            "LOW: price moves driven by execution / earnings; narrative "
            "follows fundamentals.",
            "MEDIUM: some reflexive elements; price is ahead of execution "
            "but a credible execution path exists.",
            "HIGH: price is largely narrative-driven (TSLA, PLTR live tests; "
            "GME/AMC meme distortion); fundamental anchor weak.",
        ),
    ),
    PatternRubric(
        pattern_id="L3-e-18",
        title="Cultural transmission across CEO transitions (CONTESTED)",
        one_line_question=(
            "Has the company demonstrated, or is it positioned to "
            "demonstrate, intact culture/discipline across CEO transitions?"
        ),
        contested=True,
        rubric_anchors=(
            "LOW: recent CEO transition associated with discipline erosion "
            "(GE Welch->Immelt analogue) OR no successor visible.",
            "MEDIUM: transition handled but outcome unclear; succession "
            "plan exists but unproven.",
            "HIGH: transition completed with discipline preserved/improved "
            "(COST Sinegal->Jelinek, AAPL Jobs->Cook, MSFT Ballmer->Nadella).",
        ),
    ),
    PatternRubric(
        pattern_id="L3-e-19",
        title="Founder mystique without execution (NEGATIVE)",
        one_line_question=(
            "Is the founder's mystique accompanied by hard execution metrics, "
            "or is mystique substituting for execution validation?"
        ),
        rubric_anchors=(
            "LOW (best for the company; rated LOW = mystique-without-execution "
            "RISK is LOW): mystique present but accompanied by clear "
            "execution track record (Buffett, Bezos, Huang, Cook).",
            "MEDIUM: mystique outpaces execution but execution path is "
            "credible.",
            "HIGH (worst for the company; rated HIGH = mystique-without-"
            "execution RISK is HIGH): mystique cultivated without underlying "
            "execution validation (Holmes, Neumann, Lay-Skilling, SBF).",
        ),
    ),
)

PATTERNS_BY_ID = {p.pattern_id: p for p in PATTERNS_TO_SCORE}


# Patterns where HIGH = bad (negative signals); Stage 3 linter / orchestrator
# uses this to invert scoring direction when summarising.
NEGATIVE_PATTERN_IDS = frozenset({"L3-e-16", "L3-e-19"})


@dataclass
class EvidenceCorpus:
    """Source-evidence for Stage 2 — ONLY this is exposed to the LLM.

    NEVER add Stage-1 outputs to this dataclass. Information-isolation
    is enforced by composition: the orchestrator builds this object
    from the source corpus directly, and never re-imports the Stage 1
    dataclasses into Stage 2 inputs.
    """

    ticker: str
    documents: list  # list[{source_id, kind, text}]


@dataclass
class PatternRating:
    """Single-pattern rating after self-consistency aggregation."""

    pattern_id: str
    rating: str  # LOW | MEDIUM | HIGH
    score: float  # 0.0 / 0.5 / 1.0
    confidence: float  # share of N voting modal rating
    dispersion: float  # 1 - confidence; higher = more disagreement
    evidence_quotes: list  # verbatim, validated against corpus
    rationale: str
    defer_to_human: bool
    tie_break_applied: bool
    samples: list  # list of per-sample dicts for audit
    model: str
    saw_rule_output: bool  # MUST be False — info-isolation marker

    def to_audit_payload(self) -> dict:
        return {
            "pattern_id": self.pattern_id,
            "rating": self.rating,
            "score": self.score,
            "confidence": round(self.confidence, 4),
            "dispersion": round(self.dispersion, 4),
            "evidence_quotes": list(self.evidence_quotes),
            "rationale": self.rationale,
            "defer_to_human": self.defer_to_human,
            "tie_break_applied": self.tie_break_applied,
            "samples": list(self.samples),
            "model": self.model,
            "saw_rule_output": self.saw_rule_output,
        }


@dataclass
class Stage2Result:
    """Full Stage 2 result over all patterns."""

    ratings: list  # list[PatternRating]
    aggregate_score: float  # mean of normalised scores (negative patterns inverted)
    saw_rule_output: bool  # global False; redundant marker
    prompt_version: str
    n_self_consistency: int
    temperature: float
    info_isolation_assertions: dict

    def to_audit_payload(self) -> dict:
        return {
            "stage": "stage_2_llm_rubric",
            "saw_rule_output": self.saw_rule_output,
            "prompt_version": self.prompt_version,
            "n_self_consistency": self.n_self_consistency,
            "temperature": self.temperature,
            "info_isolation_assertions": dict(self.info_isolation_assertions),
            "aggregate_score": round(self.aggregate_score, 4),
            "ratings": [r.to_audit_payload() for r in self.ratings],
        }


# ---------------------------------------------------------------------------
# Prompt builder (information-isolated by construction)
# ---------------------------------------------------------------------------


def build_prompt(
    pattern: PatternRubric,
    evidence: EvidenceCorpus,
) -> tuple[str, str]:
    """Build (system, user) prompt strings for one pattern call.

    NOTE: this signature deliberately accepts ONLY (pattern, evidence).
    There is no parameter that could carry Stage 1 mechanical output.
    Adding such a parameter would violate Section 4.3 information
    isolation and Section 5 Q1 lock. Reviewers: do not add a stage1
    parameter to this function — anchoring bias defeats the rubric.
    """
    docs = "\n\n".join(
        f"[{d['source_id']} | {d.get('kind', 'unknown')}]\n{d['text']}"
        for d in evidence.documents
    )
    anchors = "\n".join(f"  - {a}" for a in pattern.rubric_anchors)
    system = (
        "You are scoring a single qualitative pattern about a public company.\n"
        "Output ONLY a JSON object matching the schema. Do NOT include any\n"
        "narrative outside the JSON. You are seeing source documents only;\n"
        "you are NOT seeing any other system's mechanical scoring output.\n"
        "Required fields:\n"
        '  rating: "LOW" | "MEDIUM" | "HIGH"\n'
        "  confidence: number in [0.0, 1.0]\n"
        '  evidence_quotes: array of strings (each MUST appear verbatim '
        "in the source documents above; if you cannot find a verbatim "
        'quote, return [] and rating="LOW")\n'
        "  rationale: string, <= 2 sentences\n"
        "  defer_to_human: boolean (true if evidence is genuinely ambiguous)\n"
        "  tie_break_applied: boolean (true if you broke a tie between two "
        "ratings; false otherwise)\n"
    )
    user = (
        f"TICKER: {evidence.ticker}\n\n"
        f"PATTERN ID: {pattern.pattern_id}\n"
        f"PATTERN TITLE: {pattern.title}\n"
        f"QUESTION: {pattern.one_line_question}\n\n"
        f"RUBRIC ANCHORS:\n{anchors}\n\n"
        f"SOURCE DOCUMENTS:\n{docs}\n\n"
        "Return JSON only."
    )
    return system, user


# ---------------------------------------------------------------------------
# Validation + aggregation
# ---------------------------------------------------------------------------


def _validate_and_normalise_sample(
    sample: dict,
    evidence: EvidenceCorpus,
) -> dict:
    """Normalise one LLM sample; defaults to LOW on validation failure.

    Per Section 4.3: "Required verbatim evidence (no quote -> defaults to LOW)."
    """
    out = {
        "rating": RATING_LOW,
        "confidence": 0.0,
        "evidence_quotes": [],
        "rationale": "",
        "defer_to_human": False,
        "tie_break_applied": False,
        "validation_notes": [],
    }
    if not isinstance(sample, dict):
        out["validation_notes"].append("sample is not a dict")
        return out
    rating = sample.get("rating")
    if rating not in (RATING_LOW, RATING_MEDIUM, RATING_HIGH):
        out["validation_notes"].append(f"invalid rating={rating!r}; defaulting LOW")
        return out

    quotes = sample.get("evidence_quotes") or []
    if not isinstance(quotes, list):
        quotes = []
    # Verbatim verification
    corpus_text = "\n".join(d.get("text", "") for d in evidence.documents)
    verified = [q for q in quotes if isinstance(q, str) and q and q in corpus_text]
    if not verified and rating != RATING_LOW:
        out["validation_notes"].append(
            "no verbatim-verified quote; defaulting rating to LOW per spec"
        )
        return out

    out["rating"] = rating
    try:
        out["confidence"] = float(sample.get("confidence", 0.0))
    except (TypeError, ValueError):
        out["confidence"] = 0.0
    out["evidence_quotes"] = verified
    out["rationale"] = str(sample.get("rationale", ""))[:600]
    out["defer_to_human"] = bool(sample.get("defer_to_human", False))
    out["tie_break_applied"] = bool(sample.get("tie_break_applied", False))
    return out


def _aggregate_self_consistency(samples: list) -> tuple[str, float]:
    """Median (modal) rating + share-confidence."""
    if not samples:
        return RATING_LOW, 0.0
    ratings = [s["rating"] for s in samples]
    counter = Counter(ratings)
    # Median across ordinal: map to 0/1/2 and take statistics.median_low
    ord_map = {RATING_LOW: 0, RATING_MEDIUM: 1, RATING_HIGH: 2}
    inv_map = {v: k for k, v in ord_map.items()}
    ords = sorted(ord_map[r] for r in ratings)
    median_ord = statistics.median_low(ords)
    median_rating = inv_map[median_ord]
    # Confidence = share of samples at modal rating (use modal — robust)
    modal_rating, modal_count = counter.most_common(1)[0]
    share = modal_count / len(samples)
    # Use median_rating for the official rating; confidence is the share
    # voting *with* the median rating.
    median_share = counter.get(median_rating, 0) / len(samples)
    # Prefer median; if median != modal but their counts tie, median wins.
    return median_rating, median_share


# ---------------------------------------------------------------------------
# LLM client
# ---------------------------------------------------------------------------


class LLMUnavailableError(RuntimeError):
    """Raised when the Anthropic SDK or API key is unavailable."""


def _get_anthropic_client():
    """Lazy-import Anthropic SDK; raise LLMUnavailableError if unavailable."""
    try:
        import anthropic  # type: ignore
    except ImportError as e:
        raise LLMUnavailableError(f"anthropic SDK not installed: {e}") from e
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise LLMUnavailableError("ANTHROPIC_API_KEY env var not set")
    return anthropic.Anthropic()


def _call_llm_once(
    system: str,
    user: str,
    model: str,
    temperature: float,
    client=None,
    sample_index: int = 0,
) -> dict:
    """One LLM call returning parsed JSON dict. Raises on parse failure.

    Opt-in response-replay cache (P0-5): when ``LLM_CACHE_ENABLED`` is set,
    the call is routed through ``src.llm_cache`` keyed on the resolved model
    id + ``(prompt_sha, temperature, max_tokens, sample_index)``. Default OFF.
    ``sample_index`` lets self-consistency's N=5 samples cache distinctly
    instead of collapsing to one entry (which would degenerate the median).
    """
    cache = None
    try:
        from src.llm_cache import cache_from_env, cached_call_once  # noqa: WPS433

        cache = cache_from_env()
    except Exception:  # pragma: no cover - cache import must never break runtime
        cache = None

    if cache is not None:
        return cached_call_once(
            cache=cache,
            model=model,
            system=system,
            user=user,
            temperature=temperature,
            max_tokens=1024,
            sample_index=sample_index,
            compute=lambda: _raw_call_llm_once(system, user, model, temperature, client),
            dumps=json.dumps,
            loads=json.loads,
        )
    return _raw_call_llm_once(system, user, model, temperature, client)


def _raw_call_llm_once(
    system: str,
    user: str,
    model: str,
    temperature: float,
    client=None,
) -> dict:
    """The actual round-trip + parse (cache-agnostic)."""
    if client is None:
        client = _get_anthropic_client()
    msg = client.messages.create(
        model=model,
        max_tokens=1024,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    raw = "".join(
        block.text for block in msg.content if getattr(block, "type", None) == "text"
    )
    raw = raw.strip()
    # Strip code fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def score_pattern(
    pattern: PatternRubric,
    evidence: EvidenceCorpus,
    *,
    model: Optional[str] = None,
    n: int = SELF_CONSISTENCY_N,
    temperature: float = SELF_CONSISTENCY_TEMP,
    llm_caller=None,
) -> PatternRating:
    """Score one pattern with N=5 self-consistency.

    Args:
        pattern: pattern rubric.
        evidence: source documents (NOT Stage-1 outputs).
        model: override default. If None, contested patterns get Opus,
            non-contested get Sonnet.
        llm_caller: optional callable (system, user, model, temperature)
            returning dict — used in tests to inject mocked responses.
    """
    chosen_model = model or (
        HIGH_STAKES_MODEL if pattern.contested else DEFAULT_MODEL
    )
    system, user = build_prompt(pattern, evidence)

    raw_samples: list = []
    for i in range(n):
        try:
            if llm_caller is not None:
                sample = llm_caller(system, user, chosen_model, temperature)
            else:
                # Pass the sample ordinal so the opt-in cache (P0-5) stores
                # each of the N self-consistency samples as a distinct entry
                # rather than collapsing them (which would degenerate the
                # median). No effect when the cache is disabled (default).
                sample = _call_llm_once(
                    system, user, chosen_model, temperature, sample_index=i
                )
        except (json.JSONDecodeError, LLMUnavailableError, Exception) as e:
            _LOG.warning("Stage-2 sample %d failed for %s: %s", i, pattern.pattern_id, e)
            sample = {}
        raw_samples.append(sample)

    normalised = [_validate_and_normalise_sample(s, evidence) for s in raw_samples]
    median_rating, median_share = _aggregate_self_consistency(normalised)
    counter = Counter(s["rating"] for s in normalised)
    dispersion = 1.0 - median_share

    # Aggregate evidence quotes (union of verified quotes across samples)
    seen: set = set()
    all_quotes: list = []
    for s in normalised:
        for q in s["evidence_quotes"]:
            if q not in seen:
                seen.add(q)
                all_quotes.append(q)

    # Pick a rationale from a sample matching the median rating.
    rationale = ""
    defer = False
    tie_break = False
    for s in normalised:
        if s["rating"] == median_rating:
            rationale = s["rationale"] or rationale
            defer = defer or s["defer_to_human"]
            tie_break = tie_break or s["tie_break_applied"]
            if rationale:
                break

    # defer_to_human if dispersion is high (no clear modal answer)
    if counter and counter.most_common(1)[0][1] < (n // 2 + 1):
        defer = True

    return PatternRating(
        pattern_id=pattern.pattern_id,
        rating=median_rating,
        score=RATING_TO_SCORE[median_rating],
        confidence=median_share,
        dispersion=dispersion,
        evidence_quotes=all_quotes,
        rationale=rationale,
        defer_to_human=defer,
        tie_break_applied=tie_break,
        samples=normalised,
        model=chosen_model,
        saw_rule_output=False,
    )


def score_all_patterns(
    evidence: EvidenceCorpus,
    *,
    model: Optional[str] = None,
    llm_caller=None,
) -> Stage2Result:
    """Score every pattern in PATTERNS_TO_SCORE (information-isolated).

    Caller MUST pass ``evidence`` constructed from the source corpus only.
    The function asserts this by inspecting the EvidenceCorpus type and
    rejecting any payload that has a 'stage1' or 'rule_output' key.
    """
    # Information-isolation assertions (defence in depth)
    assertions = _assert_info_isolation(evidence)

    ratings: list = []
    for pattern in PATTERNS_TO_SCORE:
        r = score_pattern(
            pattern,
            evidence,
            model=model,
            llm_caller=llm_caller,
        )
        ratings.append(r)

    # Aggregate score: invert negative-pattern scores (HIGH=bad -> 1 - score)
    contributions = []
    for r in ratings:
        s = r.score
        if r.pattern_id in NEGATIVE_PATTERN_IDS:
            s = 1.0 - s
        contributions.append(s)
    aggregate = sum(contributions) / len(contributions) if contributions else 0.0

    return Stage2Result(
        ratings=ratings,
        aggregate_score=aggregate,
        saw_rule_output=False,
        prompt_version=LLM_PROMPT_VERSION,
        n_self_consistency=SELF_CONSISTENCY_N,
        temperature=SELF_CONSISTENCY_TEMP,
        info_isolation_assertions=assertions,
    )


def _assert_info_isolation(evidence: EvidenceCorpus) -> dict:
    """Defence-in-depth check that no Stage-1 output leaks into Stage 2.

    Returns a dict of the assertions made (recorded in audit). Raises
    AssertionError on violation.
    """
    assertions: dict = {
        "evidence_type": type(evidence).__name__,
        "checked_attrs": [],
    }
    # The dataclass schema only has ticker + documents. If anyone
    # subclassed and added stage1 fields, fail loud.
    forbidden = {"stage1", "stage_1", "rule_output", "tier_a_score", "knockout"}
    seen_attrs = set(getattr(evidence, "__dict__", {}).keys())
    leaks = forbidden & seen_attrs
    assertions["forbidden_attrs_seen"] = sorted(leaks)
    assertions["passed"] = not leaks
    if leaks:
        raise AssertionError(
            f"Information-isolation violation: EvidenceCorpus has forbidden "
            f"Stage-1 attributes {leaks}. Stage 2 LLM must NOT see Stage 1 "
            f"output (Section 4.3 + Section 5 Q1 lock + L8 finding)."
        )
    # Check documents do not embed Stage-1 mechanical phrasings either.
    forbidden_phrases = (
        "stage 1a outcome",
        "stage 1b outcome",
        "tier-a pass count",
        "fraud_signature_count",
    )
    for d in evidence.documents:
        text = (d.get("text") or "").lower()
        for phrase in forbidden_phrases:
            if phrase in text:
                raise AssertionError(
                    f"Information-isolation violation: source document "
                    f"{d.get('source_id')!r} contains Stage-1 phrasing "
                    f"{phrase!r}. Source corpus must be raw evidence only."
                )
    assertions["forbidden_phrase_scan"] = "passed"
    return assertions
