"""Mechanical similarity retrieval against peak-pain archetype catalog.

INVARIANT (Section 7.2 + 7.3a launch-gate): the retrieval pool MUST be HMAC-
verified at load time. Tampering with peak_pain_archetypes.universal_core_features
(or any signed column) MUST be detected and the offending row dropped from the
pool, with an M-2 system_error event emitted (source='counterfactual_veto.retrieval',
error_type='peak_pain_hmac_invalid'). Without this gate, an attacker who flips
a SURVIVOR row's features could swing the top-3 archetype distribution from
SURVIVOR-dominant to NON-SURVIVOR-dominant and silently turn a blocking veto
into a non-blocking one.

Per v3 spec Section 4.4 retrieval scoring:

    similarity = 0.7 × universal_core_similarity
               + 0.3 × sector_extension_similarity   IF sector(candidate) == sector(case)
               + 0   × sector_extension_similarity   IF sectors differ

Universal-core similarity = Hamming over 6 features, equal-weight (1/6 each).
Sector-extension similarity = Hamming over the (intersection of) sector-
specific feature sets present on both candidate and case.

Bayesian shrinkage λ=1.0 at v0.1 (Section 4.4 lock): observed Hamming
similarity is shrunk toward the prior 0.5 with weight λ=1 over a sample
size of 6 features:

    universal_core_sim = (matches + λ × 0.5 × N_prior) / (N_obs + λ × N_prior)

where matches = number of feature agreements per Phase 4 Q4 feature-typed
rule (categorical exact match / ordinal within-±1 step), N_obs = 6 (universal
core), N_prior = N_obs (so shrinkage weight equals one observation's worth).

Filters applied at retrieval time:
    - outcome IN ('SURVIVOR', 'DILUTED-SURVIVOR', 'NON-SURVIVOR') — TBD
      excluded per Section 4.4 active retrieval pool lock.
    - validation_status != 'disputed' — disputed catalog rows excluded
      per PB#7 5-iteration cap.

Returns top-3 cases with similarity scores and per-feature match details.

Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
           Section 4.4 (retrieval scoring + active-pool filter),
           Phase 4 Q4 (feature-typed agreement rule).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from src.audit_trail.hmac_verify import compute_signature_dict
from src.peak_pain_catalog.feature_typing import UNIVERSAL_CORE, features_agree


# Bayesian shrinkage parameters (Section 4.4 lock at v0.1).
SHRINKAGE_LAMBDA: float = 1.0
SHRINKAGE_PRIOR_MEAN: float = 0.5
UNIVERSAL_CORE_WEIGHT: float = 0.7
SECTOR_EXTENSION_WEIGHT: float = 0.3


# Outcome filter — active retrieval pool excludes TBD and disputed.
ACTIVE_OUTCOMES: frozenset[str] = frozenset(
    {"SURVIVOR", "DILUTED-SURVIVOR", "NON-SURVIVOR"}
)


@dataclass(frozen=True)
class CatalogCase:
    """A peak_pain_archetypes row materialized for retrieval scoring.

    Mirrors the migration 011 + 016 columns the retrieval code touches.
    `loader.py` (DB-backed) or test fixtures populate these objects.
    """

    case_id: str
    ticker: str
    sector: str
    outcome: str
    universal_core_features: dict[str, str]
    sector_extensions: dict[str, str]
    validation_status: str
    era_category: str = "recent"
    peak_dd_pct: float | None = None


@dataclass(frozen=True)
class FeatureMatch:
    """Per-feature match detail (audit chain line item)."""

    feature_name: str
    candidate_value: str
    case_value: str
    agreed: bool


@dataclass(frozen=True)
class RetrievalMatch:
    """One scored top-K result."""

    case: CatalogCase
    similarity: float
    universal_core_similarity: float
    sector_extension_similarity: float | None  # None when sectors differ
    universal_core_matches: list[FeatureMatch] = field(default_factory=list)
    sector_extension_matches: list[FeatureMatch] = field(default_factory=list)


def _bayesian_shrink(matches: int, n_obs: int) -> float:
    """Bayesian-shrunk Hamming similarity per Section 4.4 v0.1 (λ=1.0).

    Formula::

        sim = (matches + λ × prior_mean × n_obs) / (n_obs + λ × n_obs)

    With λ=1 and prior_mean=0.5 this reduces toward 0.5 with the weight of
    one observation's worth (one full feature vector).
    """
    if n_obs <= 0:
        return SHRINKAGE_PRIOR_MEAN
    numerator = matches + SHRINKAGE_LAMBDA * SHRINKAGE_PRIOR_MEAN * n_obs
    denominator = n_obs + SHRINKAGE_LAMBDA * n_obs
    return numerator / denominator


def _score_universal_core(
    candidate_core: dict[str, str], case_core: dict[str, str]
) -> tuple[float, list[FeatureMatch]]:
    """Score universal-core Hamming similarity (Bayesian-shrunk)."""
    matches = 0
    detail: list[FeatureMatch] = []
    n = 0
    for feat in UNIVERSAL_CORE:
        cv = candidate_core.get(feat, "")
        kv = case_core.get(feat, "")
        if not cv or not kv:
            # Missing feature on either side → conservative non-match
            detail.append(FeatureMatch(feat, cv, kv, agreed=False))
            n += 1
            continue
        agreed = features_agree(feat, cv, kv)
        if agreed:
            matches += 1
        detail.append(FeatureMatch(feat, cv, kv, agreed=agreed))
        n += 1
    return _bayesian_shrink(matches, n), detail


def _score_sector_extensions(
    candidate_ext: dict[str, str], case_ext: dict[str, str]
) -> tuple[float, list[FeatureMatch]]:
    """Score sector-extension Hamming similarity over intersection of features.

    Bayesian shrinkage applied with the same λ=1.0; n_obs is the number of
    sector features the candidate and case both carry. If neither carries any
    sector feature (e.g., pre-2008 era cases with empty sector_extensions),
    we return the prior 0.5 — encoding "no signal" rather than "perfect" or
    "zero" agreement.
    """
    common = sorted(set(candidate_ext) & set(case_ext))
    if not common:
        return SHRINKAGE_PRIOR_MEAN, []
    matches = 0
    detail: list[FeatureMatch] = []
    for feat in common:
        cv = candidate_ext.get(feat, "")
        kv = case_ext.get(feat, "")
        if not cv or not kv:
            detail.append(FeatureMatch(feat, cv, kv, agreed=False))
            continue
        agreed = features_agree(feat, cv, kv)
        if agreed:
            matches += 1
        detail.append(FeatureMatch(feat, cv, kv, agreed=agreed))
    return _bayesian_shrink(matches, len(common)), detail


def score_case(
    *,
    candidate_sector: str,
    candidate_universal_core: dict[str, str],
    candidate_sector_extensions: dict[str, str],
    case: CatalogCase,
) -> RetrievalMatch:
    """Compute similarity for a single candidate→case pair.

    Per Section 4.4: sector-extension similarity contributes only when the
    candidate and case share a sector. Cross-sector matches drop the
    extension term entirely (weight 0), so a cross-sector top-3 leans purely
    on the universal-core 0.7-weighted score.
    """
    core_sim, core_detail = _score_universal_core(
        candidate_universal_core, case.universal_core_features
    )

    if candidate_sector == case.sector:
        ext_sim, ext_detail = _score_sector_extensions(
            candidate_sector_extensions, case.sector_extensions
        )
        similarity = (
            UNIVERSAL_CORE_WEIGHT * core_sim
            + SECTOR_EXTENSION_WEIGHT * ext_sim
        )
        return RetrievalMatch(
            case=case,
            similarity=similarity,
            universal_core_similarity=core_sim,
            sector_extension_similarity=ext_sim,
            universal_core_matches=core_detail,
            sector_extension_matches=ext_detail,
        )

    # Cross-sector: only the universal-core term contributes (PB#1 lock).
    similarity = UNIVERSAL_CORE_WEIGHT * core_sim
    return RetrievalMatch(
        case=case,
        similarity=similarity,
        universal_core_similarity=core_sim,
        sector_extension_similarity=None,
        universal_core_matches=core_detail,
        sector_extension_matches=[],
    )


def retrieve_top_3(
    *,
    candidate_sector: str,
    candidate_universal_core: dict[str, str],
    candidate_sector_extensions: dict[str, str],
    catalog: list[CatalogCase],
    k: int = 3,
) -> list[RetrievalMatch]:
    """Score every catalog case in the active pool and return top-K.

    Args:
        candidate_sector:              Candidate's canonical sector key.
        candidate_universal_core:      6-feature universal-core dict.
        candidate_sector_extensions:   Sector-specific feature dict.
        catalog:                        Pre-loaded list of CatalogCase rows.
        k:                              Top-K to return (default 3).

    Returns:
        Top-K RetrievalMatch objects sorted by similarity DESC. Cases with
        ``outcome='TBD'`` or ``validation_status='disputed'`` are dropped
        before scoring (active retrieval pool filter, Section 4.4).
    """
    active = [
        c for c in catalog
        if c.outcome in ACTIVE_OUTCOMES
        and c.validation_status != "disputed"
    ]
    scored = [
        score_case(
            candidate_sector=candidate_sector,
            candidate_universal_core=candidate_universal_core,
            candidate_sector_extensions=candidate_sector_extensions,
            case=c,
        )
        for c in active
    ]
    # Deterministic ordering: similarity DESC, then case_id ASC for tie-breaking.
    # Without the case_id tiebreaker, Python's stable sort preserves the SQL
    # query's row order, which Postgres does NOT guarantee across query plans
    # — producing run-to-run drift on tied similarity scores (observed in
    # MSFT 2026-05-14/15/16 where the top-3 analog set rotated across days
    # despite identical inputs). Post-audit fix 2026-05-17.
    scored.sort(key=lambda m: (-m.similarity, m.case.case_id))
    return scored[:k]


def archetype_distribution(matches: list[RetrievalMatch]) -> dict[str, int]:
    """Count outcome distribution across a top-K retrieval result.

    Returns ``{'SURVIVOR': n1, 'DILUTED-SURVIVOR': n2, 'NON-SURVIVOR': n3}``
    where missing buckets are zero. Used by Layer 3 veto rule.
    """
    out: dict[str, int] = {
        "SURVIVOR": 0,
        "DILUTED-SURVIVOR": 0,
        "NON-SURVIVOR": 0,
    }
    for m in matches:
        if m.case.outcome in out:
            out[m.case.outcome] += 1
    return out


# ---------------------------------------------------------------------------
# DB loader (kept here so retrieval.py is self-contained for tests).
# ---------------------------------------------------------------------------


CatalogLoader = Callable[[], list[CatalogCase]]
PgExecuteFn = Callable[[str, tuple[Any, ...]], None]
"""(sql, params) -> None — DI signature shared with lifecycle.PgExecuteFn."""


# Columns that participate in the HMAC-signed payload of peak_pain_archetypes.
# MUST match `peak_pain_catalog.persistence._build_payload_unsigned` exactly,
# else the verifier silently mismatches every row.
_HMAC_PAYLOAD_FIELDS: tuple[str, ...] = (
    "case_id",
    "ticker",
    "peak_date",
    "trough_date",
    "peak_dd_pct",
    "outcome",
    "sector",
    "era_category",
    "universal_core_features",
    "sector_extensions",
    "universal_core_consensus",
    "validation_status",
    "consensus_method",
    "notes",
    "source_urls",
)


def _row_hmac_payload(row: dict[str, Any]) -> dict[str, Any]:
    """Reconstruct the canonical HMAC payload from a SELECT row.

    Mirrors ``peak_pain_catalog.persistence._build_payload_unsigned`` so the
    canonical-JSON bytes match byte-for-byte.
    """
    return {f: row.get(f) for f in _HMAC_PAYLOAD_FIELDS}


def _emit_hmac_invalid_system_error(
    *,
    execute: Optional[PgExecuteFn],
    case_id: str,
    detail: str,
) -> None:
    """Insert a system_errors row for a peak-pain HMAC verification failure.

    Per v3 spec Section 5.3 + Phase 4 Q9: every silent-failure path must log
    to system_errors so /system-health can surface the breach. The row is
    delete-protected by migration 014's append-mostly trigger.
    """
    if execute is None:
        return
    sql = (
        "INSERT INTO system_errors "
        "(source, error_type, error_detail, blocked_decision) "
        "VALUES ($1, $2, $3, $4)"
    )
    try:
        execute(
            sql,
            (
                "counterfactual_veto.retrieval",
                "peak_pain_hmac_invalid",
                detail,
                f"counterfactual_retrieval_skip_case:{case_id}",
            ),
        )
    except Exception:
        # Never let logging failure mask the underlying skip — the caller
        # already excluded the tampered row from the active pool.
        pass


def load_catalog_from_pg(
    query_fn: Callable[[str], list[dict[str, Any]]],
    *,
    peak_pain_hmac_secret: Optional[bytes] = None,
    execute: Optional[PgExecuteFn] = None,
) -> list[CatalogCase]:
    """Load active catalog rows via a pg-execute callable (DI for testing).

    `query_fn` is expected to return a list of dicts with keys matching the
    peak_pain_archetypes columns. Production wires this to mcp__postgres
    or psycopg2; tests pass a stub that returns canned rows.

    Per v3 spec Section 7.2 + 7.3a launch-gate, every loaded row MUST have a
    valid HMAC over its canonical payload. Rows whose ``hmac_signature`` does
    not match are SKIPPED and an M-2 system_errors row is written (source
    ``counterfactual_veto.retrieval``, error_type ``peak_pain_hmac_invalid``).
    Rows missing ``hmac_signature`` (e.g., legacy un-signed) are also skipped.

    Args:
        query_fn:               DI hook for SELECT execution.
        peak_pain_hmac_secret:  HMAC key bytes. Defaults to env
                                ``PEAK_PAIN_HMAC_KEY`` (matches
                                ``peak_pain_catalog.persistence`` HMAC scope).
        execute:                DI hook for system_errors INSERT. If None,
                                tampered rows are still skipped silently —
                                callers SHOULD pass an executor in production.
    """
    sql = (
        "SELECT case_id, ticker, peak_date, trough_date, peak_dd_pct, "
        "outcome, sector, era_category, "
        "universal_core_features, sector_extensions, universal_core_consensus, "
        "validation_status, consensus_method, notes, source_urls, "
        "hmac_signature, signed_at "
        "FROM peak_pain_archetypes "
        "WHERE outcome IN ('SURVIVOR','DILUTED-SURVIVOR','NON-SURVIVOR') "
        "AND validation_status != 'disputed' "
        # Deterministic load order — protects against Postgres returning rows
        # in different physical order across query plans, which would change
        # the input order to the stable similarity sort downstream. Pair with
        # the case_id tiebreaker in score_case + sort at line ~261.
        "ORDER BY case_id ASC"
    )
    rows = query_fn(sql)

    # Resolve HMAC key once for the whole load.
    key = peak_pain_hmac_secret
    if key is None:
        env_key = os.environ.get("PEAK_PAIN_HMAC_KEY")
        if env_key:
            key = env_key.encode("utf-8")

    out: list[CatalogCase] = []
    for r in rows:
        case_id = r.get("case_id", "<unknown>")
        stored_sig = r.get("hmac_signature") or ""

        # Verify HMAC if we have a key and a stored signature; otherwise log
        # and skip. Fail-closed: missing signature = treated as tampered.
        if not stored_sig:
            _emit_hmac_invalid_system_error(
                execute=execute,
                case_id=case_id,
                detail=f"missing hmac_signature on case {case_id}",
            )
            continue

        if key is not None:
            payload = _row_hmac_payload(r)
            try:
                expected = compute_signature_dict(payload, key)
            except Exception as exc:
                _emit_hmac_invalid_system_error(
                    execute=execute,
                    case_id=case_id,
                    detail=f"hmac compute error on case {case_id}: {exc}",
                )
                continue
            import hmac as _hmac

            if not _hmac.compare_digest(expected, stored_sig):
                _emit_hmac_invalid_system_error(
                    execute=execute,
                    case_id=case_id,
                    detail=(
                        f"hmac mismatch on case {case_id} — "
                        f"row dropped from active retrieval pool"
                    ),
                )
                continue
        # If no key is available we still emit a system_error so the operator
        # can fix the missing-secret configuration; we DO NOT silently include
        # rows we can't verify.
        else:
            _emit_hmac_invalid_system_error(
                execute=execute,
                case_id=case_id,
                detail=(
                    f"PEAK_PAIN_HMAC_KEY unavailable; cannot verify case "
                    f"{case_id} — row dropped from active pool"
                ),
            )
            continue

        out.append(
            CatalogCase(
                case_id=case_id,
                ticker=r["ticker"],
                sector=r["sector"],
                outcome=r["outcome"],
                universal_core_features=r.get("universal_core_features") or {},
                sector_extensions=r.get("sector_extensions") or {},
                validation_status=r.get("validation_status", "validated"),
                era_category=r.get("era_category", "recent"),
                peak_dd_pct=r.get("peak_dd_pct"),
            )
        )
    return out
