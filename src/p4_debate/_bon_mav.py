"""WS-5 — Synthesis best-of-N with a cross-model verifier (BoN-MAV).

This module upgrades the Phase-D PMSupervisor synthesis from a single naive
pass to **best-of-N (N=5)** candidate generation followed by a **cross-model
verifier** (BoN-MAV — best-of-N with a multi-agent verifier) that ranks and
selects the winning candidate.

Why BoN-MAV instead of multi-agent debate (MAD)?
-------------------------------------------------
Naive multi-agent debate is dominated by inter-agent sycophancy (ICML 2025).
WS-5 replaces it with:

  1. A SINGLE synthesizer model (``opus``) sampled ``N=5`` times
     (self-consistency, first-pass only).
  2. A DIFFERENT verifier model (``sonnet``, read from the agent header
     ``verifier_model`` knob — P0-6) that ranks/selects the best candidate.
     Using a different model for the verifier cuts self-preference bias.
  3. A self-consistency / critic fallback when the verifier errors: NEVER
     auto-PASS — degrade to the self-consistency pick (majority decision,
     median conviction across the N candidates).

The MAD path is GATED: it only runs when BOTH ``heterogeneous_models`` AND
``verifiable_step`` flags are set. Otherwise WS-5 falls back to
self-consistency.

Conviction-input aggregation (LOCKED DECISION)
----------------------------------------------
We aggregate the conviction *INPUTS* (``debate_add_count``, ``kills_fired``,
``drift``) across the N passes BEFORE the deterministic ``conviction_rollup``
runs. We do NOT average the final convictions — averaging post-rollup buckets
would blur the deterministic rule the rollup encodes.

Cost
----
Each BoN pass records exactly one ``attempt_cost_usd`` = sum of all N
candidate-generation token usages + the verifier token usage. The cost cap is
``$15 / pass`` (``COST_CAP_USD``).
"""

from __future__ import annotations

import hashlib
import json
import logging
import statistics
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence

_LOG = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Locked WS-5 constants                                                       #
# --------------------------------------------------------------------------- #

#: best-of-N sample count (LOCKED: N=5, capped at 5).
BON_N: int = 5
BON_N_CAP: int = 5

#: cost cap per BoN pass (sum of all candidate + verifier usage).
COST_CAP_USD: float = 15.0

#: first-pass self-consistency sampling temperature (N samples spread).
SELF_CONSISTENCY_TEMPERATURE: float = 0.7


# --------------------------------------------------------------------------- #
# Token-cost model                                                            #
# --------------------------------------------------------------------------- #

# Per-million-token USD prices, keyed on the RESOLVED model id (or alias).
# Used only to roll candidate+verifier usage into one attempt_cost_usd; these
# are illustrative dev-tier numbers, recalibratable without touching logic.
_PRICE_PER_MTOK_INPUT: dict[str, float] = {
    "claude-opus-4-5": 15.0,
    "claude-sonnet-4-5": 3.0,
    "claude-haiku-4-5": 0.80,
    "opus": 15.0,
    "sonnet": 3.0,
    "haiku": 0.80,
}
_PRICE_PER_MTOK_OUTPUT: dict[str, float] = {
    "claude-opus-4-5": 75.0,
    "claude-sonnet-4-5": 15.0,
    "claude-haiku-4-5": 4.0,
    "opus": 75.0,
    "sonnet": 15.0,
    "haiku": 4.0,
}


@dataclass(frozen=True)
class UsageRecord:
    """One model round-trip's token usage (for cost rollup)."""

    model: str
    input_tokens: int
    output_tokens: int

    def cost_usd(self) -> float:
        key = (self.model or "").strip()
        in_rate = _PRICE_PER_MTOK_INPUT.get(key, _PRICE_PER_MTOK_INPUT.get(key.lower(), 0.0))
        out_rate = _PRICE_PER_MTOK_OUTPUT.get(key, _PRICE_PER_MTOK_OUTPUT.get(key.lower(), 0.0))
        return (self.input_tokens / 1_000_000.0) * in_rate + (
            self.output_tokens / 1_000_000.0
        ) * out_rate


def attempt_cost_usd(usages: Sequence[UsageRecord]) -> float:
    """Sum candidate + verifier usage into ONE attempt_cost_usd.

    Per the WS-5 spec the whole BoN pass (all N candidate generations plus the
    verifier ranking call) is metered as a single ``attempt_cost_usd``.
    """
    return round(sum(u.cost_usd() for u in usages), 6)


def extract_usage(model: str, response: Any) -> UsageRecord:
    """Pull ``input_tokens``/``output_tokens`` from an SDK response or dict.

    Tolerant of: an Anthropic ``Message`` with a ``.usage`` attribute, a plain
    dict ``{"usage": {...}}``, or absence (→ zero usage). Never raises — a
    missing usage block contributes 0 to the cost (and is logged).
    """
    usage = getattr(response, "usage", None)
    if usage is None and isinstance(response, dict):
        usage = response.get("usage")
    in_tok = 0
    out_tok = 0
    if usage is not None:
        in_tok = int(getattr(usage, "input_tokens", None) or (usage.get("input_tokens") if isinstance(usage, dict) else 0) or 0)
        out_tok = int(getattr(usage, "output_tokens", None) or (usage.get("output_tokens") if isinstance(usage, dict) else 0) or 0)
    return UsageRecord(model=model, input_tokens=in_tok, output_tokens=out_tok)


# --------------------------------------------------------------------------- #
# Conviction-INPUT aggregation (BEFORE the deterministic rollup)              #
# --------------------------------------------------------------------------- #


@dataclass
class ConvictionInputSample:
    """The conviction INPUTS a single BoN candidate implies.

    These are the inputs to ``p7.conviction_rollup`` — NOT the final
    conviction bucket. We aggregate across N passes BEFORE the rollup.
    """

    debate_add_count: int
    kills_fired: int
    drift: int  # anchor_drift_channels_triggered, 0..3


@dataclass
class AggregatedConvictionInputs:
    """Conviction inputs aggregated across the N BoN passes."""

    debate_add_count: int
    kills_fired: int
    drift: int
    per_sample: list[ConvictionInputSample] = field(default_factory=list)


def aggregate_conviction_inputs(
    samples: Sequence[ConvictionInputSample],
) -> AggregatedConvictionInputs:
    """Aggregate conviction INPUTS across N passes (NOT the final convictions).

    Aggregation policy (conservative; rollup applies LOW-precedence so erring
    toward "more negative evidence" is safe):

      * ``debate_add_count`` — **median** across samples (rounded to int): the
        self-consistency central tendency of how many styles voted ADD.
      * ``kills_fired``       — **max** across samples: if any candidate
        surfaced a kill, it must flow into the rollup (kills are
        non-negotiable negative evidence).
      * ``drift``             — **max** across samples: same conservatism as
        kills; the most-drifted reading governs.

    Raises ``ValueError`` on an empty sample set.
    """
    if not samples:
        raise ValueError("aggregate_conviction_inputs requires >= 1 sample")
    add_counts = sorted(s.debate_add_count for s in samples)
    # statistics.median on an even-length list averages the two middle values;
    # round to the nearest int so the rollup (which expects an int count) is fed
    # a valid integer.
    med_add = int(round(statistics.median(add_counts)))
    return AggregatedConvictionInputs(
        debate_add_count=med_add,
        kills_fired=max(s.kills_fired for s in samples),
        drift=max(s.drift for s in samples),
        per_sample=list(samples),
    )


# --------------------------------------------------------------------------- #
# Composite quality (Axis-A faithfulness + Axis-B sophistication percentiles) #
# --------------------------------------------------------------------------- #

# WS-1 (axis_a articulation) and WS-2 (axis_b sophistication) live scorers are
# built in PARALLEL and are not importable yet (src/scoring/ ships typed stubs
# only at Phase 0). Until they land we read the GOLDEN axis blocks carried on
# each envelope/candidate and pass the metric through an injectable percentile
# function (default: identity, since the golden metrics are already in [0,1]).
# Live-scorer wiring is DEFERRED to Phase 2.

PercentileFn = Callable[[float], float]


def _identity_percentile(x: float) -> float:
    """Default percentile fn: the golden axis metrics are already in [0,1]."""
    return max(0.0, min(1.0, float(x)))


def candidate_envelope(
    *, raw_text: str, payload: Optional[dict]
) -> dict[str, Any]:
    """Build the minimal envelope the enrichment adapter scores per candidate.

    Phase-2 wiring: when ``run_phase_d_bon`` is asked to score candidates live,
    each generated synthesis candidate must be turned into an *envelope* the
    WS-1/WS-2 scorers can read. The parsed synthesis ``payload`` IS that
    envelope when available (it carries ``decision`` / ``dissent_trace`` etc.);
    if the candidate failed JSON parse we fall back to a thin envelope that
    still carries the raw model output as ``answer`` so the scorers degrade
    gracefully rather than seeing nothing.

    Pure: returns a NEW dict; never mutates ``payload``.
    """
    if isinstance(payload, dict):
        env = dict(payload)
        # Ensure an ``answer`` text is present for scorers that read it; do not
        # clobber an answer the payload already carries.
        env.setdefault("answer", raw_text)
        return env
    return {"answer": raw_text or ""}


#: Per-candidate enrichment seam: ``(envelope) -> {"axis_a": .., "axis_b": ..}``.
#: ``run_phase_d_bon`` injects an adapter bound to its (articulation,
#: sophistication, grounding) seams; default-None means "no live scoring".
EnrichFn = Callable[[dict[str, Any]], dict[str, Any]]


def resolve_candidate_axes(
    *,
    sample_index: int,
    raw_text: str,
    payload: Optional[dict],
    candidate_axes: Optional[Sequence[dict]],
    enrich_fn: Optional[EnrichFn],
) -> dict[str, Any]:
    """Resolve ONE candidate's ``{axis_a, axis_b}`` block (precedence-ordered).

    Precedence (backward-compatible by construction):

      1. **Pre-baked fixtures win.** If ``candidate_axes`` supplies a non-empty
         block for ``sample_index``, return it verbatim — this is exactly the
         pre-Phase-2 behavior, so fixture-driven runs are byte-identical.
      2. **Live scoring** (Phase-2). Else, if an ``enrich_fn`` is supplied,
         build the candidate envelope and run the enrichment adapter to compute
         the axes live. The adapter never raises and degrades to advisory-null
         blocks offline.
      3. **Neither.** Return ``{}`` (scoring disabled and no fixtures) — the
         caller maps this to ``composite_quality == 0.0``, as before.
    """
    fixture = (
        candidate_axes[sample_index]
        if candidate_axes is not None and sample_index < len(candidate_axes)
        else None
    ) or None
    if fixture:
        return fixture
    if enrich_fn is not None:
        env = candidate_envelope(raw_text=raw_text, payload=payload)
        return enrich_fn(env) or {}
    return {}


def composite_quality(
    candidate_axes: dict[str, Any],
    *,
    faithfulness_percentile: PercentileFn = _identity_percentile,
    sophistication_percentile: PercentileFn = _identity_percentile,
) -> float:
    """composite_quality = mean(Axis-A faithfulness pctile, Axis-B soph pctile).

    ``candidate_axes`` is the per-candidate dict carrying ``axis_a`` and
    ``axis_b`` blocks (the golden blocks from the fixtures, or — once WS-1/WS-2
    land — the live-scored blocks). We read:

      * Axis-A **faithfulness** (the articulation-faithfulness metric).
      * Axis-B **roscoe** as the sophistication proxy (the golden block's
        primary sophistication metric; swap to the live WS-2 metric when wired).

    Each is mapped through its percentile fn (default identity) and averaged.
    Missing metrics contribute 0.0 (a candidate with no axis block scores 0).
    """
    axis_a = candidate_axes.get("axis_a") or {}
    axis_b = candidate_axes.get("axis_b") or {}
    faith = axis_a.get("faithfulness")
    soph = axis_b.get("roscoe")
    a_pct = faithfulness_percentile(faith) if faith is not None else 0.0
    b_pct = sophistication_percentile(soph) if soph is not None else 0.0
    return (a_pct + b_pct) / 2.0


# --------------------------------------------------------------------------- #
# BoN candidate + result containers                                           #
# --------------------------------------------------------------------------- #


@dataclass
class BoNCandidate:
    """One synthesizer (producer) candidate in the best-of-N set."""

    sample_index: int
    raw_text: str
    payload: Optional[dict]  # parsed synthesis JSON (or None on parse fail)
    conviction_inputs: ConvictionInputSample
    usage: UsageRecord
    axes: dict[str, Any] = field(default_factory=dict)  # axis_a/axis_b blocks
    composite_quality: float = 0.0

    def to_payload(self) -> dict:
        return {
            "sample_index": self.sample_index,
            "payload": self.payload,
            "conviction_inputs": {
                "debate_add_count": self.conviction_inputs.debate_add_count,
                "kills_fired": self.conviction_inputs.kills_fired,
                "drift": self.conviction_inputs.drift,
            },
            "usage": {
                "model": self.usage.model,
                "input_tokens": self.usage.input_tokens,
                "output_tokens": self.usage.output_tokens,
            },
            "composite_quality": self.composite_quality,
        }


@dataclass
class VerifierPick:
    """The verifier's selection over the N candidates."""

    selected_index: int
    method: str  # "verifier" | "self_consistency_fallback" | "critic_fallback"
    rationale: str = ""
    verifier_model: str = ""
    fallback_reason: Optional[str] = None

    def to_payload(self) -> dict:
        return {
            "selected_index": self.selected_index,
            "method": self.method,
            "rationale": self.rationale,
            "verifier_model": self.verifier_model,
            "fallback_reason": self.fallback_reason,
        }


# --------------------------------------------------------------------------- #
# MAD gate                                                                    #
# --------------------------------------------------------------------------- #


def mad_allowed(*, heterogeneous_models: bool, verifiable_step: bool) -> bool:
    """The multi-agent-debate path is allowed ONLY when BOTH flags are set.

    Per WS-5 spec criterion 3: no MAD path unless (heterogeneous models) AND
    (verifiable step). Default = self-consistency.
    """
    return bool(heterogeneous_models) and bool(verifiable_step)


# --------------------------------------------------------------------------- #
# Self-consistency fallback (NEVER auto-PASS)                                 #
# --------------------------------------------------------------------------- #


def self_consistency_pick(
    candidates: Sequence[BoNCandidate],
    *,
    fallback_reason: str,
    verifier_model: str = "",
) -> VerifierPick:
    """Pick a candidate by self-consistency when the verifier is unavailable.

    Strategy:
      * Among candidates that PARSED (payload is not None) AND carry a
        non-empty ``decision``, choose the one whose ``decision`` matches the
        MAJORITY decision; tie-break by highest ``composite_quality`` then
        lowest sample_index.
      * If NO candidate has a valid (non-empty) decision, select the
        lowest-index candidate but DO NOT coerce its decision — the caller's
        validator will mark it invalid. We NEVER auto-PASS: we never fabricate
        a PASS decision here, and we never let a candidate with a
        missing/empty ``decision`` win the tally (BUG 1: an empty-string
        decision could previously gather a majority and select a malformed,
        decision-less payload as the consensus winner).
    """
    # A candidate is only a valid contender if it parsed AND carries a
    # non-empty decision. Candidates missing a 'decision' key (or with an
    # empty/whitespace value) are excluded from BOTH the tally and contention.
    valid = [
        c
        for c in candidates
        if c.payload is not None and str(c.payload.get("decision", "")).strip()
    ]
    if not valid:
        # No usable candidate with a real decision. Return the lowest index;
        # downstream validation decides. Critically we do not synthesise a PASS
        # and we never select a decision-less payload as a "winner".
        idx = candidates[0].sample_index if candidates else 0
        return VerifierPick(
            selected_index=idx,
            method="self_consistency_fallback",
            rationale=(
                "no candidate has a valid decision; lowest-index returned "
                "for validator"
            ),
            verifier_model=verifier_model,
            fallback_reason=fallback_reason,
        )
    # Majority decision among VALID candidates (those with a non-empty decision).
    tally: dict[str, int] = {}
    for c in valid:
        d = str(c.payload.get("decision", "")).strip().upper()
        tally[d] = tally.get(d, 0) + 1
    majority_decision = max(tally.items(), key=lambda kv: kv[1])[0]
    contenders = [
        c for c in valid if str(c.payload.get("decision", "")).strip().upper() == majority_decision
    ]
    contenders.sort(key=lambda c: (-c.composite_quality, c.sample_index))
    selected = contenders[0]
    # Guard: the selected candidate MUST carry a non-empty decision. The only
    # path allowed to select a decision-less candidate is the no-valid branch
    # above (which never reaches here).
    assert str(selected.payload.get("decision", "")).strip(), (
        "self_consistency_pick selected a candidate without a decision"
    )
    return VerifierPick(
        selected_index=selected.sample_index,
        method="self_consistency_fallback",
        rationale=(
            f"verifier unavailable; majority decision={majority_decision!r} "
            f"({tally[majority_decision]}/{len(valid)} valid candidates), "
            f"tie-broken by composite_quality"
        ),
        verifier_model=verifier_model,
        fallback_reason=fallback_reason,
    )


# --------------------------------------------------------------------------- #
# BoN cache key                                                               #
# --------------------------------------------------------------------------- #


def bon_input_sha(*, system: str, user: str) -> str:
    """Stable SHA over the (system, user) synthesis prompt pair.

    Reuses the same length-prefixed hashing discipline as
    ``llm_cache.cache.prompt_sha`` so the BoN input_sha is consistent with the
    per-sample cache keys.
    """
    h = hashlib.sha256()
    for part in (system or "", user or ""):
        b = part.encode("utf-8")
        h.update(str(len(b)).encode("ascii"))
        h.update(b"\x00")
        h.update(b)
    return h.hexdigest()


def bon_cache_digest(
    *, input_sha: str, model_version: str, n: int, temperature: float
) -> str:
    """Digest for the BoN-level cache key ``(input_sha, model_version, n, temp)``.

    Distinct from the per-sample ``llm_cache.CacheKey`` (which also carries
    ``sample_index``): this keys the WHOLE best-of-N result
    ``{candidates, verifier_pick}`` so a replayed run returns both the N
    candidates AND the verifier's selection in one shot.
    """
    payload = json.dumps(
        {
            "input_sha": input_sha,
            "model_version": model_version,
            "n": int(n),
            "temperature": float(temperature),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "bon:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def serialize_bon_result(
    candidates: Sequence[BoNCandidate],
    pick: VerifierPick,
    verifier_usage: Optional[UsageRecord] = None,
) -> str:
    """Serialize the BoN result (candidates + verifier_pick + verifier_usage).

    Stores the N candidates, the verifier pick AND the verifier's token usage
    under one BoN-level cache value (per the WS-5 spec ``(input_sha,
    model_version, n, temp) -> [candidates, verifier_pick]``). We persist the
    candidates' raw_text/axes so a replay can faithfully rebuild
    :class:`BoNCandidate` objects (and thus the re-validated synthesis + cost
    rollup) without re-calling any model.

    BUG 2 fix: ``verifier_usage`` MUST be persisted too. Previously the replay
    branch hardcoded verifier usage to zero, so a recorded pass (with a real
    verifier call) and its replay computed DIFFERENT ``attempt_cost_usd``
    values. Serializing it makes the cost field reproducible on replay.
    """
    return json.dumps(
        {
            "candidates": [
                {
                    **c.to_payload(),
                    "raw_text": c.raw_text,
                    "axes": c.axes,
                }
                for c in candidates
            ],
            "verifier_pick": pick.to_payload(),
            "verifier_usage": {
                "model": verifier_usage.model if verifier_usage else "",
                "input_tokens": verifier_usage.input_tokens if verifier_usage else 0,
                "output_tokens": verifier_usage.output_tokens if verifier_usage else 0,
            },
        },
        sort_keys=True,
    )


def deserialize_bon_result(
    text: str,
) -> tuple[list[BoNCandidate], VerifierPick, UsageRecord]:
    """Rebuild ``(candidates, verifier_pick, verifier_usage)`` from a cache value.

    ``verifier_usage`` round-trips the recorded verifier token counts so the
    replayed ``attempt_cost_usd`` reproduces the recorded value (BUG 2). Older
    cache values without a ``verifier_usage`` block deserialize to a zero
    :class:`UsageRecord` (backward compatible — they predate the cost fix).
    """
    obj = json.loads(text)
    candidates: list[BoNCandidate] = []
    for raw in obj.get("candidates", []):
        ci = raw.get("conviction_inputs", {})
        u = raw.get("usage", {})
        candidates.append(
            BoNCandidate(
                sample_index=int(raw.get("sample_index", 0)),
                raw_text=raw.get("raw_text", ""),
                payload=raw.get("payload"),
                conviction_inputs=ConvictionInputSample(
                    debate_add_count=int(ci.get("debate_add_count", 0)),
                    kills_fired=int(ci.get("kills_fired", 0)),
                    drift=int(ci.get("drift", 0)),
                ),
                usage=UsageRecord(
                    model=u.get("model", ""),
                    input_tokens=int(u.get("input_tokens", 0)),
                    output_tokens=int(u.get("output_tokens", 0)),
                ),
                axes=raw.get("axes", {}) or {},
                composite_quality=float(raw.get("composite_quality", 0.0)),
            )
        )
    vp = obj.get("verifier_pick", {})
    pick = VerifierPick(
        selected_index=int(vp.get("selected_index", 0)),
        method=str(vp.get("method", "verifier")),
        rationale=str(vp.get("rationale", "")),
        verifier_model=str(vp.get("verifier_model", "")),
        fallback_reason=vp.get("fallback_reason"),
    )
    vu = obj.get("verifier_usage", {}) or {}
    verifier_usage = UsageRecord(
        model=str(vu.get("model", "")),
        input_tokens=int(vu.get("input_tokens", 0)),
        output_tokens=int(vu.get("output_tokens", 0)),
    )
    return candidates, pick, verifier_usage


__all__ = [
    "BON_N",
    "BON_N_CAP",
    "COST_CAP_USD",
    "SELF_CONSISTENCY_TEMPERATURE",
    "UsageRecord",
    "attempt_cost_usd",
    "extract_usage",
    "ConvictionInputSample",
    "AggregatedConvictionInputs",
    "aggregate_conviction_inputs",
    "PercentileFn",
    "composite_quality",
    "EnrichFn",
    "candidate_envelope",
    "resolve_candidate_axes",
    "BoNCandidate",
    "VerifierPick",
    "mad_allowed",
    "self_consistency_pick",
    "bon_input_sha",
    "bon_cache_digest",
    "serialize_bon_result",
    "deserialize_bon_result",
]
