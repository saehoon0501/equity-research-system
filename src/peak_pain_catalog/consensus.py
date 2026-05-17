"""3-LLM iterative-consensus pipeline (Section 5 Q3 + Phase 4 Q4).

Runs the extractor 3 times per case and applies the feature-typed agreement
rule (categorical exact match / ordinal within-±1 step). Iterates up to 5
times to break 2/3 disagreements; if disagreement persists at iteration 5,
the feature is marked `disputed` per Section 5 Q3.

Per-feature consensus quality grades (written to
peak_pain_archetypes.universal_core_consensus JSONB):

    HIGH    — all 3 LLMs agree by iteration 1 (or after surfaced-disagreement
              re-examination converged in 2..N iterations with all 3 in
              agreement-band)
    MEDIUM  — 2/3 majority remained stable across iterations and the dissenter
              was within the agreement band of the other 2 in some sequence
    LOW     — only 2/3 agreement at the cap iteration AND dissenter was off-
              band (still recorded but flagged)
    DISPUTED — no 2/3 agreement at the cap iteration

Model mix (Section 5 Q3 default):
    LLM #1: claude-sonnet-4-6 (cost-efficient primary)
    LLM #2: claude-sonnet-4-6 (independent Sonnet run for cheap diversity)
    LLM #3: claude-opus-4-7   (Opus for tie-breaking power on edge cases)

Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
           Section 5 Q3 (3-LLM iterative-consensus pipeline; 5-iteration cap)
           + Phase 4 Q4 (feature-typed-v0.1 consensus rule).
"""

from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Literal

from src.peak_pain_catalog.extractor import (
    AnthropicClient,
    ExtractedFeature,
    ExtractionResult,
    extract_features,
)


def _extract_3_parallel(
    case,
    *,
    client,
    model_mix: tuple[str, str, str],
    surfaced_disagreement: dict[str, list[str]] | None = None,
) -> list[ExtractionResult]:
    """Dispatch the 3-LLM extractor calls concurrently and preserve order.

    Each ``extract_features`` call ultimately drives one ``claude -p`` subprocess
    via ``ClaudeSdkClient`` (subscription auth) — three of them in parallel
    saturates the 3-LLM consensus per iteration. With sequential dispatch, each
    iteration's wall ≈ 3 × per-call latency (~90s); parallel dispatch collapses
    that to ~30s, the per-call latency itself.

    Order matters because ``model_mix[k]`` indexes feed into ``feat_status``
    accounting; we collect by index, not as_completed.
    """
    results: list[ExtractionResult | None] = [None, None, None]

    def _one(k: int) -> None:
        results[k] = extract_features(
            case,
            client=client,
            model=model_mix[k],
            surfaced_disagreement=surfaced_disagreement,
        )

    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = [ex.submit(_one, k) for k in range(3)]
        for f in futures:
            f.result()  # propagate exceptions

    # All slots populated by the worker; mypy-narrow.
    return [r for r in results if r is not None]
from src.peak_pain_catalog.feature_typing import (
    FEATURE_TYPES,
    FeatureKind,
    categorical_match,
    features_agree,
    is_within_one_step,
)
from src.peak_pain_catalog.parser import CaseRecord


ConsensusStatus = Literal["HIGH", "MEDIUM", "LOW", "DISPUTED"]
ValidationStatus = Literal["validated", "pending", "disputed"]

DEFAULT_MODEL_MIX: tuple[str, str, str] = (
    "claude-sonnet-4-6",
    "claude-sonnet-4-6",
    "claude-opus-4-7",
)
"""Model triplet for the 3-LLM consensus pipeline (Section 5 Q3).

Two Sonnet calls + one Opus call. Sonnet is cost-efficient for the structural-
feature task; Opus brings tie-breaking strength on edge cases. Override the
mix by passing `model_mix=` to `run_consensus`.
"""

MAX_ITERATIONS = 5
"""Hard cap on consensus iterations per Section 5 Q3."""


@dataclass(frozen=True)
class FeatureConsensus:
    """Per-feature consensus output.

    Attributes:
        feature_name:        Feature key.
        value:               Consensus value (chosen via majority + agreement
                             rule). For DISPUTED features, this is set to the
                             most-conservative default for downstream filtering.
        consensus:           HIGH / MEDIUM / LOW / DISPUTED.
        iterations:          Number of LLM rounds run (1..5).
        agreement_count:     How many of the 3 LLMs were in the agreement band
                             at the final iteration (2 or 3).
        verbatim_quotes:     Quotes from each agreeing LLM, for audit.
        per_iteration_values: Full history [(iter, [v1, v2, v3]), ...].
    """

    feature_name: str
    value: str
    consensus: ConsensusStatus
    iterations: int
    agreement_count: int
    verbatim_quotes: list[str] = field(default_factory=list)
    per_iteration_values: list[tuple[int, list[str]]] = field(default_factory=list)


@dataclass(frozen=True)
class ConsensusResult:
    """Aggregate result of running 3-LLM consensus on one case.

    Attributes:
        case_id:           The case validated.
        universal_core:    feature_name → FeatureConsensus for the 6 core feats.
        sector_extensions: feature_name → FeatureConsensus for sector extensions.
        validation_status: validated / pending / disputed (rolled-up over feats).
        model_mix:         The triplet used (for audit chain).
        all_extractions:   Full per-iteration ExtractionResults (audit chain).
    """

    case_id: str
    universal_core: dict[str, FeatureConsensus]
    sector_extensions: dict[str, FeatureConsensus]
    validation_status: ValidationStatus
    model_mix: tuple[str, str, str]
    all_extractions: list[list[ExtractionResult]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Agreement-band helpers
# ---------------------------------------------------------------------------


def _agreement_band(feature_name: str, values: list[str]) -> tuple[int, list[int]]:
    """Find the largest pairwise-agreeing subset of `values` for a feature.

    Phase 4 Q4 rule applied pairwise: a value v_i agrees with v_j iff
    `features_agree(feature, v_i, v_j)` (categorical exact / ordinal ±1).

    Returns:
        (size_of_largest_band, indices_in_band).

    Implementation: 3 values → check all 3 pairs. Largest band is whichever
    of {3, 2, 1} is realized.
    """
    n = len(values)
    if n == 0:
        return 0, []
    # Check unanimous
    if n >= 3:
        if (
            features_agree(feature_name, values[0], values[1])
            and features_agree(feature_name, values[1], values[2])
            and features_agree(feature_name, values[0], values[2])
        ):
            return 3, [0, 1, 2]
    # Check best pair
    best_size = 1
    best: list[int] = [0]
    for i in range(n):
        for j in range(i + 1, n):
            if features_agree(feature_name, values[i], values[j]):
                if 2 > best_size:
                    best_size = 2
                    best = [i, j]
    return best_size, best


def _consensus_value(
    feature_name: str, values: list[str], band: list[int]
) -> str:
    """Pick the value to record from the agreement band.

    For categorical: any band member (they all match).
    For ordinal: pick the median index along the declared order so we don't
    bias toward one end of the within-±1 spread.
    """
    band_values = [values[i] for i in band]
    kind = FEATURE_TYPES.get(feature_name)
    if kind != FeatureKind.ORDINAL:
        # Categorical or unknown — return canonical (most common in band)
        most_common = Counter(band_values).most_common(1)[0][0]
        return most_common
    # Ordinal: pick middle by index
    from src.peak_pain_catalog.feature_typing import ORDINAL_ORDERS

    order = ORDINAL_ORDERS.get(feature_name)
    if not order:
        return band_values[0]
    indexed = []
    for v in band_values:
        try:
            idx = order.index(v)
        except ValueError:
            idx = -1
        indexed.append((idx, v))
    indexed = [iv for iv in indexed if iv[0] >= 0]
    if not indexed:
        return band_values[0]
    indexed.sort()
    return indexed[len(indexed) // 2][1]


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------


def run_consensus(
    case: CaseRecord,
    *,
    client: AnthropicClient,
    model_mix: tuple[str, str, str] = DEFAULT_MODEL_MIX,
    max_iterations: int = MAX_ITERATIONS,
) -> ConsensusResult:
    """Run the 3-LLM iterative-consensus pipeline on one case.

    Args:
        case:        CaseRecord from parser.parse_catalog.
        client:      Shared Anthropic client (or stub) for all 3 LLM calls.
        model_mix:   Triplet of model ids; defaults to (sonnet, sonnet, opus).
        max_iterations: Hard cap (default 5 per Section 5 Q3).

    Returns:
        ConsensusResult with per-feature HIGH/MEDIUM/LOW/DISPUTED grades and
        a rolled-up validation_status.
    """
    # Per-feature state machine: tracks the running 3-LLM triple of values for
    # each feature. We re-run only LLMs whose vote is dissenting (sticky 2/3
    # agreement is preserved into iteration 2..N to surface disagreement only
    # on the dissenting feature(s)).
    iteration = 1
    history: list[list[ExtractionResult]] = []

    # Iteration 1: independent runs on all 3 LLMs (parallel — see
    # _extract_3_parallel docstring for the wall-time rationale).
    iter_1: list[ExtractionResult] = _extract_3_parallel(
        case, client=client, model_mix=model_mix
    )
    history.append(iter_1)

    # Build the running set of features to track
    feature_names = list(iter_1[0].universal_core) + list(iter_1[0].sector_extensions)

    # Track per-iteration values per feature
    per_feat_history: dict[str, list[tuple[int, list[str]]]] = {f: [] for f in feature_names}
    per_feat_quotes: dict[str, list[str]] = {f: [] for f in feature_names}
    feat_status: dict[str, FeatureConsensus] = {}
    pending_features: set[str] = set(feature_names)

    def _values_at(extractions: list[ExtractionResult], feat: str) -> list[str]:
        out = []
        for er in extractions:
            ef = er.universal_core.get(feat) or er.sector_extensions.get(feat)
            out.append(ef.value if ef else "")
        return out

    def _quotes_at(
        extractions: list[ExtractionResult], feat: str, band: list[int]
    ) -> list[str]:
        out = []
        for i in band:
            er = extractions[i]
            ef = er.universal_core.get(feat) or er.sector_extensions.get(feat)
            if ef and ef.verbatim_quote:
                out.append(ef.verbatim_quote)
        return out

    # Resolve iteration 1
    current_extractions = iter_1
    while pending_features and iteration <= max_iterations:
        resolved_this_round: set[str] = set()
        for feat in list(pending_features):
            values = _values_at(current_extractions, feat)
            per_feat_history[feat].append((iteration, list(values)))
            band_size, band_idx = _agreement_band(feat, values)
            quotes = _quotes_at(current_extractions, feat, band_idx)
            per_feat_quotes[feat] = quotes
            if band_size == 3:
                # Unanimous agreement — HIGH if iter 1, MEDIUM if needed re-runs
                consensus = "HIGH" if iteration == 1 else "MEDIUM"
                feat_status[feat] = FeatureConsensus(
                    feature_name=feat,
                    value=_consensus_value(feat, values, band_idx),
                    consensus=consensus,
                    iterations=iteration,
                    agreement_count=3,
                    verbatim_quotes=quotes,
                    per_iteration_values=list(per_feat_history[feat]),
                )
                resolved_this_round.add(feat)
            elif band_size == 2 and iteration >= max_iterations:
                # 2/3 agreement at cap — LOW grade
                feat_status[feat] = FeatureConsensus(
                    feature_name=feat,
                    value=_consensus_value(feat, values, band_idx),
                    consensus="LOW",
                    iterations=iteration,
                    agreement_count=2,
                    verbatim_quotes=quotes,
                    per_iteration_values=list(per_feat_history[feat]),
                )
                resolved_this_round.add(feat)
            elif band_size == 1 and iteration >= max_iterations:
                # No agreement at cap — DISPUTED
                from src.peak_pain_catalog.extractor import CONSERVATIVE_DEFAULTS

                feat_status[feat] = FeatureConsensus(
                    feature_name=feat,
                    value=CONSERVATIVE_DEFAULTS.get(feat, ""),
                    consensus="DISPUTED",
                    iterations=iteration,
                    agreement_count=1,
                    verbatim_quotes=[],
                    per_iteration_values=list(per_feat_history[feat]),
                )
                resolved_this_round.add(feat)
            # else: still pending, will re-iterate

        pending_features -= resolved_this_round
        if not pending_features:
            break

        # Need another iteration: re-run the 3 LLMs with surfaced disagreement
        # for the still-pending features. Cheapest approach: re-run all 3
        # LLMs but pass the disagreement payload so each can re-examine.
        if iteration >= max_iterations:
            # Force-resolve remaining pending features as DISPUTED. (Should not
            # happen because the iteration-cap branch above catches them, but
            # defensive.)
            from src.peak_pain_catalog.extractor import CONSERVATIVE_DEFAULTS

            for feat in pending_features:
                values = _values_at(current_extractions, feat)
                feat_status[feat] = FeatureConsensus(
                    feature_name=feat,
                    value=CONSERVATIVE_DEFAULTS.get(feat, ""),
                    consensus="DISPUTED",
                    iterations=iteration,
                    agreement_count=1,
                    verbatim_quotes=[],
                    per_iteration_values=list(per_feat_history[feat]),
                )
            pending_features.clear()
            break

        iteration += 1
        surfaced: dict[str, list[str]] = {}
        for feat in pending_features:
            surfaced[feat] = _values_at(current_extractions, feat)
        # Re-iteration: 3 LLMs again with surfaced disagreement payload,
        # parallel dispatch for the same wall-time reason as iter 1.
        next_extractions: list[ExtractionResult] = _extract_3_parallel(
            case,
            client=client,
            model_mix=model_mix,
            surfaced_disagreement=surfaced,
        )
        history.append(next_extractions)
        current_extractions = next_extractions

    # Roll up validation_status
    core_keys = list(iter_1[0].universal_core.keys())
    ext_keys = list(iter_1[0].sector_extensions.keys())
    universal_core = {k: feat_status[k] for k in core_keys if k in feat_status}
    sector_extensions = {k: feat_status[k] for k in ext_keys if k in feat_status}

    rollup = _rollup_validation(universal_core, sector_extensions)

    return ConsensusResult(
        case_id=case.case_id,
        universal_core=universal_core,
        sector_extensions=sector_extensions,
        validation_status=rollup,
        model_mix=model_mix,
        all_extractions=history,
    )


def _rollup_validation(
    core: dict[str, FeatureConsensus], ext: dict[str, FeatureConsensus]
) -> ValidationStatus:
    """Roll per-feature consensus grades up to the case's validation_status.

    Per Section 5 Q3 / catalog v0.1 pre-launch gate:
        - Any DISPUTED feature in universal-core → 'disputed'
        - All universal-core features HIGH or MEDIUM → 'validated'
        - At least one LOW universal-core (no disputes) → 'pending'
        - Sector extensions can be MEDIUM/LOW per the spec; only DISPUTED in
          a sector extension also marks 'disputed' (we exclude from active
          retrieval).
    """
    all_feats = list(core.values()) + list(ext.values())
    if any(f.consensus == "DISPUTED" for f in all_feats):
        return "disputed"
    if any(f.consensus == "LOW" for f in core.values()):
        return "pending"
    return "validated"


# ---------------------------------------------------------------------------
# Convenience: legacy strict-equality reference (NOT used in production)
# ---------------------------------------------------------------------------


def strict_equality_agreement(
    feature_name: str, values: list[str]
) -> tuple[int, list[int]]:
    """Strict-equality variant for testing — used by the simplify path that
    ignores Phase 4 Q4 within-±1 leniency. Production uses _agreement_band.
    """
    if not values:
        return 0, []
    counts = Counter(values)
    most_common_value, most_common_count = counts.most_common(1)[0]
    if most_common_count == len(values):
        return len(values), list(range(len(values)))
    if most_common_count >= 2:
        idxs = [i for i, v in enumerate(values) if v == most_common_value]
        return len(idxs), idxs
    return 1, [0]


__all__ = [
    "ConsensusResult",
    "ConsensusStatus",
    "DEFAULT_MODEL_MIX",
    "FeatureConsensus",
    "MAX_ITERATIONS",
    "ValidationStatus",
    "run_consensus",
    "strict_equality_agreement",
]


# Avoid an unused-import lint in the LOW-band fallthrough above
_ = (categorical_match, is_within_one_step)
