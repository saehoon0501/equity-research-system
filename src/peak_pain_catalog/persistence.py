"""Persistence — write validated catalog rows to peak_pain_archetypes.

Per migration 011_v3_counterfactual_retrieval.sql + 016_v3_hmac_columns.sql,
the schema is:

    peak_pain_archetypes (
        case_id, ticker, peak_date, trough_date, peak_dd_pct, outcome,
        sector, era_category,
        universal_core_features        JSONB,
        sector_extensions              JSONB,
        universal_core_consensus       JSONB,    # per-feat HIGH/MEDIUM/LOW/DISPUTED
        validation_status              TEXT,     # validated / pending / disputed
        consensus_method               TEXT,     # 'feature-typed-v0.1'
        notes                          TEXT,
        source_urls                    JSONB,
        hmac_signature                 TEXT,     # added in 016
        signed_at                      TIMESTAMPTZ, # added in 016
        ...
    )

This module:
    1. Builds the JSONB payloads from a ConsensusResult.
    2. HMAC-signs the row payload using the canonical scheme from
       ``src/audit_trail/hmac_verify.py`` per Section 5 Q1 + Section 6 Q5.
    3. UPSERTs the row (UPDATE allowed for catalog hygiene per PB#6).
    4. Provides a dry-run mode (`dsn=None`) that returns the SQL + payload
       without touching the database — used by tests and the priority runner
       in offline cold-start mode.

HMAC scope:
    Catalog rows are signed with the env var PEAK_PAIN_HMAC_KEY — a separate
    scope from the audit-chain (AUDIT_HMAC_KEY) and watchlist
    (WATCHLIST_HMAC_SECRET) keys, because the catalog has a different
    rotation lifetime. The signature is stored in the dedicated
    ``hmac_signature`` column (per migration 016); the prior notes-prefix
    scheme has been removed.

Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
           Section 5 Q1 (HMAC-signed audit chain), Section 6 Q5 (anchor-drift
           HMAC); db/migrations/011_v3_counterfactual_retrieval.sql,
           db/migrations/016_v3_hmac_columns.sql.
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import hmac
import json
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional, Protocol

from src.audit_trail.hmac_verify import (
    canonical_payload_dict,
    compute_signature_dict,
)
from src.peak_pain_catalog.consensus import ConsensusResult, FeatureConsensus
from src.peak_pain_catalog.parser import CaseRecord


HMAC_KEY_ENV = "PEAK_PAIN_HMAC_KEY"
"""Env var holding the HMAC secret. Required when not in dry-run mode."""

CONSENSUS_METHOD_VERSION = "feature-typed-v0.1"
"""Per Phase 4 Q4 lock — bump when the consensus rule changes."""


@dataclass(frozen=True)
class PersistencePayload:
    """The materialized row payload, ready for SQL UPSERT or audit storage.

    `as_sql_params()` flattens this to a positional tuple matching the column
    order of the UPSERT statement.
    """

    case_id: str
    ticker: str
    peak_date: str  # YYYY-MM-DD; best-effort from era/period
    trough_date: str
    peak_dd_pct: Decimal  # NUMERIC column — Decimal preserves write/read parity
    outcome: str
    sector: str
    era_category: str
    universal_core_features: dict[str, str]  # {feature: value}
    sector_extensions: dict[str, str]
    universal_core_consensus: dict[str, dict[str, Any]]  # rich JSONB per feat
    validation_status: str
    consensus_method: str
    notes: str
    source_urls: list[str]
    hmac_signature: str

    def as_sql_params(self) -> tuple[Any, ...]:
        """Tuple in column-order matching the UPSERT statement below."""
        return (
            self.case_id,
            self.ticker,
            self.peak_date,
            self.trough_date,
            self.peak_dd_pct,
            self.outcome,
            self.sector,
            self.era_category,
            json.dumps(self.universal_core_features, sort_keys=True),
            json.dumps(self.sector_extensions, sort_keys=True),
            json.dumps(self.universal_core_consensus, sort_keys=True),
            self.validation_status,
            self.consensus_method,
            self.notes,
            json.dumps(self.source_urls),
            self.hmac_signature,
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def write_validated_case(
    case: CaseRecord,
    consensus: ConsensusResult,
    *,
    dsn: Optional[str] = None,
    hmac_key: Optional[bytes] = None,
    extra_notes: str = "",
    source_urls: Optional[list[str]] = None,
) -> PersistencePayload:
    """Build the row payload, HMAC-sign it, and (optionally) UPSERT to Postgres.

    Args:
        case:        CaseRecord parsed from the markdown.
        consensus:   ConsensusResult from run_consensus.
        dsn:         Postgres DSN. If None, runs in dry-run mode (no DB write).
        hmac_key:    Override HMAC secret. If None, read from PEAK_PAIN_HMAC_KEY.
        extra_notes: Operator-supplied free-text notes appended to `notes`.
        source_urls: Optional source URLs (catalog row backing).

    Returns:
        The PersistencePayload that was (or would be) written. The HMAC
        signature is stored in the dedicated ``hmac_signature`` column
        (per migration 016) — NOT embedded in ``notes``.

    Raises:
        RuntimeError if dsn is set but psycopg is not installed, or
        if hmac_key is unavailable and dsn is set.
    """
    payload_no_hmac = _build_payload_unsigned(
        case=case,
        consensus=consensus,
        extra_notes=extra_notes,
        source_urls=source_urls or [],
    )
    sig = _hmac_sign(payload_no_hmac, hmac_key=hmac_key, dry_run=(dsn is None))
    payload = PersistencePayload(
        **{**payload_no_hmac, "hmac_signature": sig},
    )
    if dsn is not None:
        _upsert_row(dsn, payload)
    return payload


# ---------------------------------------------------------------------------
# Payload construction
# ---------------------------------------------------------------------------


def _feature_consensus_to_jsonb(fc: FeatureConsensus) -> dict[str, Any]:
    """Render a FeatureConsensus to JSON-friendly dict.

    Stored under universal_core_consensus[feature_name].
    """
    return {
        "value": fc.value,
        "consensus": fc.consensus,
        "iterations": fc.iterations,
        "agreement_count": fc.agreement_count,
        "verbatim_quotes": list(fc.verbatim_quotes),
        "per_iteration_values": [
            {"iter": i, "values": vals} for (i, vals) in fc.per_iteration_values
        ],
    }


def _build_payload_unsigned(
    *,
    case: CaseRecord,
    consensus: ConsensusResult,
    extra_notes: str,
    source_urls: list[str],
) -> dict[str, Any]:
    universal_core_features = {
        k: v.value for k, v in consensus.universal_core.items()
    }
    sector_ext_features = {
        k: v.value for k, v in consensus.sector_extensions.items()
    }
    consensus_jsonb = {
        k: _feature_consensus_to_jsonb(v)
        for k, v in {**consensus.universal_core, **consensus.sector_extensions}.items()
    }
    peak_date, trough_date = _infer_peak_trough(case)
    notes = (
        f"era={case.era_category}; outcome_raw={case.outcome_raw!r}; "
        f"model_mix={consensus.model_mix}; method={CONSENSUS_METHOD_VERSION}; "
        f"{extra_notes}".strip()
    )
    # peak_dd_pct lives in a NUMERIC column; psycopg returns NUMERIC as
    # ``Decimal`` on SELECT-readback, and ``canonical_payload_dict`` serializes
    # ``Decimal`` via ``str()`` — but a Python ``float`` would serialize as a
    # JSON number. Signing the float at INSERT and re-signing the Decimal on
    # readback would produce different canonical bytes and the HMAC would
    # mismatch in production. Convert to ``Decimal(str(...))`` at the signing
    # site so write-time and read-time canonical bytes are byte-identical.
    raw_dd = case.peak_dd_pct if case.peak_dd_pct == case.peak_dd_pct else -50.0
    peak_dd_pct_dec = Decimal(str(raw_dd))
    return {
        "case_id": case.case_id,
        "ticker": case.ticker,
        "peak_date": peak_date,
        "trough_date": trough_date,
        "peak_dd_pct": peak_dd_pct_dec,
        "outcome": case.outcome,
        "sector": case.sector,
        "era_category": case.era_category,
        "universal_core_features": universal_core_features,
        "sector_extensions": sector_ext_features,
        "universal_core_consensus": consensus_jsonb,
        "validation_status": consensus.validation_status,
        "consensus_method": CONSENSUS_METHOD_VERSION,
        "notes": notes,
        "source_urls": list(source_urls),
    }


def _infer_peak_trough(case: CaseRecord) -> tuple[str, str]:
    """Best-effort peak/trough dates from the catalog period string.

    Catalog tables don't carry exact dates. Convention: peak = Jan-1 of first
    year of the period, trough = Dec-31 of the last year. Operator-curated
    refinements live in the catalog via the audit cadence (PB#6).
    """
    import re

    years = re.findall(r"\d{4}", case.period)
    short = re.findall(r"\d{2}", case.period)
    if not years and short:
        years = ["20" + s for s in short[-2:]]
    if not years:
        return ("2000-01-01", "2000-12-31")
    if len(years) == 1:
        y = years[0]
        return (f"{y}-01-01", f"{y}-12-31")
    return (f"{years[0]}-01-01", f"{years[-1]}-12-31")


# ---------------------------------------------------------------------------
# HMAC signing
# ---------------------------------------------------------------------------


def _hmac_sign(
    payload: dict[str, Any], *, hmac_key: Optional[bytes], dry_run: bool
) -> str:
    """HMAC-SHA256 over the canonical payload via audit_trail.hmac_verify.

    Uses ``compute_signature_dict`` so the canonical-payload contract
    (sort_keys + ``ensure_ascii=False`` + UUID/Decimal/datetime defaults)
    matches every other HMAC producer in the system.

    Dry-run mode allows a default key for offline cold-start; production
    requires PEAK_PAIN_HMAC_KEY to be set explicitly.
    """
    key = hmac_key
    if key is None:
        env = os.environ.get(HMAC_KEY_ENV)
        if env:
            key = env.encode("utf-8")
    if key is None:
        if dry_run:
            key = b"dry-run-default-key-not-for-production"
        else:
            raise RuntimeError(
                f"{HMAC_KEY_ENV} not set; cannot HMAC-sign for production write"
            )
    return compute_signature_dict(payload, key)


# ---------------------------------------------------------------------------
# Postgres UPSERT
# ---------------------------------------------------------------------------


_UPSERT_SQL = """
INSERT INTO peak_pain_archetypes (
    case_id, ticker, peak_date, trough_date, peak_dd_pct,
    outcome, sector, era_category,
    universal_core_features, sector_extensions, universal_core_consensus,
    validation_status, consensus_method, notes, source_urls,
    hmac_signature, signed_at
) VALUES (
    %s, %s, %s, %s, %s,
    %s, %s, %s,
    %s::jsonb, %s::jsonb, %s::jsonb,
    %s, %s, %s, %s::jsonb,
    %s, NOW()
)
ON CONFLICT (case_id) DO UPDATE SET
    universal_core_features  = EXCLUDED.universal_core_features,
    sector_extensions        = EXCLUDED.sector_extensions,
    universal_core_consensus = EXCLUDED.universal_core_consensus,
    validation_status        = EXCLUDED.validation_status,
    consensus_method         = EXCLUDED.consensus_method,
    notes                    = EXCLUDED.notes,
    source_urls              = EXCLUDED.source_urls,
    hmac_signature           = EXCLUDED.hmac_signature,
    signed_at                = NOW(),
    last_updated_at          = NOW();
"""


class _DBConnection(Protocol):
    def cursor(self) -> Any: ...
    def commit(self) -> None: ...
    def close(self) -> None: ...


def _upsert_row(dsn: str, payload: PersistencePayload) -> None:
    """Run the UPSERT against Postgres. Imports psycopg lazily."""
    try:
        import psycopg  # type: ignore[import-not-found]
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "psycopg not installed; install psycopg[binary] or pass dsn=None for dry-run"
        ) from e
    with psycopg.connect(dsn) as conn:  # type: ignore[attr-defined]
        with conn.cursor() as cur:
            cur.execute(_UPSERT_SQL, payload.as_sql_params())
        conn.commit()


# ---------------------------------------------------------------------------
# Verification helper
# ---------------------------------------------------------------------------


def verify_hmac(
    payload: PersistencePayload, *, hmac_key: Optional[bytes] = None
) -> bool:
    """Re-compute HMAC over a stored payload and compare to its signature.

    Used by /audit-trail and the system-health verification surface.

    Fails-closed when the key is unavailable (``dry_run=False``) — operator
    must set ``PEAK_PAIN_HMAC_KEY`` or pass ``hmac_key=`` explicitly. The
    prior dry-run-fallback in this verifier let unkeyed runs return False
    silently, masking missing-key configuration; per remediation
    requirement we fail loud now.
    """
    unsigned = {
        f.name: getattr(payload, f.name)
        for f in dataclasses.fields(payload)
        if f.name != "hmac_signature"
    }
    expected = _hmac_sign(unsigned, hmac_key=hmac_key, dry_run=False)
    return hmac.compare_digest(expected, payload.hmac_signature)


__all__ = [
    "CONSENSUS_METHOD_VERSION",
    "HMAC_KEY_ENV",
    "PersistencePayload",
    "verify_hmac",
    "write_validated_case",
]
