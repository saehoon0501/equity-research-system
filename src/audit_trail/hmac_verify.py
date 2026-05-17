"""HMAC chain verification — single source of truth for canonical payloads.

Per v3 spec Section 5 Q1 (audit-trail HMAC chain) + Section 7 Q4 lock
(layered drill-down with tamper-evident chain).

This module is the canonical HMAC implementation for the entire system.
Five distinct write-paths must use the helpers exposed here so every signed
row verifies under one rule:

  * audit_provenance         — `verify_chain` is the verifier
  * p3_mechanical_scorer     — uses ``compute_signature(StageRow, key)``
  * peak_pain_catalog        — uses ``canonical_payload_dict`` for column-
                               stored signatures (separate scope: PEAK_PAIN_HMAC_KEY)
  * premortem_scheduler      — uses ``canonical_payload_dict`` for column-
                               stored signatures (PREMORTEM_HMAC_SECRET)
  * watchlist HMAC producer  — uses ``canonical_payload_dict`` for pillar /
                               scenario JSONB signatures (WATCHLIST_HMAC_SECRET)

Algorithm:
  - HMAC-SHA256 over a canonical JSON serialization of the row payload.
  - Canonical form: ``json.dumps(obj, sort_keys=True, separators=(',', ':'),
    ensure_ascii=False, default=_json_default)`` — UTF-8 encoded.
  - ``ensure_ascii=False`` so unicode (Greek letters, em-dash) round-trips
    byte-identically; emitters and verifiers MUST match on this flag.
  - UUIDs serialize as ``str()``, datetimes as ISO8601 UTC, dates as
    ISO8601, ``Decimal`` as ``str()`` (preserving precision).

Chain semantics: each row's payload includes parent_audit_id; tampering
with any row's drill_payload, versions, or parent pointer invalidates the
HMAC. Chain is therefore tamper-evident in two ways:
  1. Per-row signature mismatch.
  2. Parent-pointer mismatch (a row whose parent_audit_id no longer
     resolves to a prior row in the chain).

Key scopes (do NOT cross-mix):
  - AUDIT_HMAC_KEY       — audit_provenance + p3_mechanical_scorer chain.
  - PEAK_PAIN_HMAC_KEY   — peak_pain_archetypes catalog rows.
  - PREMORTEM_HMAC_SECRET — premortem rows.
  - WATCHLIST_HMAC_SECRET — watchlist anchor pillars + scenario projections.

When verification fails, the renderer surfaces "tamper-evident" output and
the failure SHOULD be flagged as an M-2 system event by the caller (per v3
spec Section 5.3 push-alert M-2/M-3 pipeline). This module returns a
structured ChainVerificationResult — it does not push alerts itself.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Mapping, Optional, Sequence
from uuid import UUID

from src.audit_trail.loader import StageRow


# -----------------------------------------------------------------------------
# Result types
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class RowVerification:
    """Result of verifying a single row."""

    audit_id: UUID
    stage: str
    signature_ok: bool
    parent_link_ok: bool
    # If signature_ok and parent_link_ok, this row is verified.
    @property
    def ok(self) -> bool:
        return self.signature_ok and self.parent_link_ok


@dataclass(frozen=True)
class ChainVerificationResult:
    """Result of verifying a full chain for a recommendation."""

    recommendation_id: UUID
    rows: tuple[RowVerification, ...]
    mode: str  # 'keyed' or 'unkeyed'
    error: Optional[str] = None  # populated on hard failures unrelated to per-row

    @property
    def all_ok(self) -> bool:
        return self.error is None and all(r.ok for r in self.rows)

    @property
    def tampered_rows(self) -> tuple[RowVerification, ...]:
        return tuple(r for r in self.rows if not r.ok)


# -----------------------------------------------------------------------------
# Canonicalization + HMAC
# -----------------------------------------------------------------------------


def canonical_payload_dict(obj: Mapping[str, Any]) -> bytes:
    """Canonical JSON encoder for ANY dict-shaped HMAC input.

    Public function — every cross-module HMAC producer MUST use this.

    Contract::

        json.dumps(obj, sort_keys=True, separators=(',', ':'),
                   ensure_ascii=False, default=_json_default).encode('utf-8')

    Type rules in ``default``:
      * ``UUID`` → ``str(uuid)``
      * ``datetime`` → ISO8601 UTC (trailing ``Z`` if naive)
      * ``date`` → ISO8601 calendar date
      * ``Decimal`` → ``str(value)`` (preserves precision; NUMERIC arrives
        as ``Decimal`` from psycopg)

    ``ensure_ascii=False`` is load-bearing: unicode strings (Greek letters,
    em-dash, etc.) round-trip byte-identically only when ASCII-escape is
    disabled in BOTH emitter and verifier.

    Per v3 spec Section 5 Q1 (audit-chain) + Section 6 Q5 (anchor-drift HMAC).
    """
    return json.dumps(
        dict(obj),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_json_default,
    ).encode("utf-8")


def canonical_payload(row: StageRow) -> bytes:
    """Canonical JSON for an audit_provenance StageRow.

    The signed payload includes:
      - audit_id, recommendation_id, stage
      - drill_payload (verbatim)
      - parent_audit_id (or None)
      - versions (containing parameters_version + model_id at minimum)
      - created_at (ISO8601 UTC)

    Sort keys + tight separators + ``ensure_ascii=False`` ensure byte-stable
    serialization. Emitter must produce the same form when computing the
    signature at INSERT time. Delegates to ``canonical_payload_dict``.
    """
    obj = {
        "audit_id": str(row.audit_id),
        "recommendation_id": str(row.recommendation_id),
        "stage": row.stage,
        "drill_payload": dict(row.drill_payload),
        "parent_audit_id": (
            str(row.parent_audit_id) if row.parent_audit_id is not None else None
        ),
        "versions": dict(row.versions),
        "created_at": _isoformat(row.created_at),
    }
    return canonical_payload_dict(obj)


def compute_signature(row: StageRow, key: bytes) -> str:
    """Compute the expected HMAC-SHA256 hex signature for a StageRow."""
    return hmac.new(key, canonical_payload(row), hashlib.sha256).hexdigest()


def compute_signature_dict(payload: Mapping[str, Any], key: bytes) -> str:
    """Compute HMAC-SHA256 hex signature over an arbitrary dict payload.

    Used by external modules (peak_pain_catalog, premortem_scheduler,
    watchlist HMAC producer) that sign rows whose schema is NOT a StageRow.
    The payload is canonicalized via ``canonical_payload_dict``.
    """
    return hmac.new(key, canonical_payload_dict(payload), hashlib.sha256).hexdigest()


def verify_row(row: StageRow, key: Optional[bytes]) -> bool:
    """Constant-time HMAC verification. Returns False if key is None."""
    if key is None:
        return False
    expected = compute_signature(row, key)
    return hmac.compare_digest(expected, row.hmac_signature or "")


def verify_chain(
    rows: Sequence[StageRow],
    *,
    key: Optional[bytes] = None,
    strict: bool = False,
    recommendation_id: Optional[UUID] = None,
) -> ChainVerificationResult:
    """Verify both per-row HMAC signatures AND parent_audit_id linkage.

    Args:
        rows: rows for ONE recommendation, ordered by created_at ASC.
        key: HMAC key bytes. If None, falls back to env AUDIT_HMAC_KEY.
        strict: if True, raise when key is unavailable; otherwise return
            mode='unkeyed' result that still verifies chain pointers.
        recommendation_id: optional caller-supplied recommendation_id used
            when ``rows`` is empty so the empty-chain result still carries
            the caller's identifier instead of a sentinel zero UUID.

    Per v3 Section 7 Q4: any signature mismatch is tamper-evidence; caller
    should raise an M-2 system event.
    """
    if not rows:
        empty_rec_id = (
            recommendation_id
            if recommendation_id is not None
            else UUID("00000000-0000-0000-0000-000000000000")
        )
        return ChainVerificationResult(
            recommendation_id=empty_rec_id,
            rows=(),
            mode="unkeyed" if key is None else "keyed",
            error="no rows to verify",
        )

    rec_id = rows[0].recommendation_id

    if key is None:
        env_key = os.environ.get("AUDIT_HMAC_KEY")
        if env_key:
            key = env_key.encode("utf-8")
        elif strict:
            raise RuntimeError(
                "AUDIT_HMAC_KEY env var not set and strict=True — refuse to "
                "report unkeyed verification per v3 Section 7 Q4 lock"
            )

    mode = "keyed" if key is not None else "unkeyed"

    # Build audit_id index for parent-link checks.
    by_id = {r.audit_id: r for r in rows}

    results: list[RowVerification] = []
    for r in rows:
        if mode == "keyed":
            sig_ok = verify_row(r, key)
        else:
            # No key — we cannot verify signature. Treat as not-OK so the
            # renderer surfaces "unverified" rather than misleading "OK".
            sig_ok = False

        # Parent-link check: if parent_audit_id is set, it must resolve to
        # a prior row in this chain, AND that prior row must have created_at
        # <= ours (timestamp ordering invariant).
        if r.parent_audit_id is None:
            parent_ok = True
        else:
            parent = by_id.get(r.parent_audit_id)
            parent_ok = parent is not None and parent.created_at <= r.created_at

        results.append(
            RowVerification(
                audit_id=r.audit_id,
                stage=r.stage,
                signature_ok=sig_ok,
                parent_link_ok=parent_ok,
            )
        )

    return ChainVerificationResult(
        recommendation_id=rec_id,
        rows=tuple(results),
        mode=mode,
    )


# -----------------------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------------------


def _isoformat(value: Any) -> str:
    """Canonical ISO-8601 for HMAC payloads.

    Critical invariant: bytes produced at sign-time MUST match bytes
    produced at verify-time after a Postgres ``timestamptz`` round-trip.
    Postgres returns ``timestamptz`` as a timezone-aware datetime in UTC;
    a naive sign-time datetime that uses the legacy ``...Z`` shorthand
    would yield different canonical bytes than the aware ``+00:00`` form
    seen by the verifier.

    Rule: a naive datetime is interpreted as UTC, then serialized in
    aware-UTC form (``...+00:00``) so both sides agree on canonical bytes.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _json_default(o: Any) -> Any:
    if isinstance(o, (datetime, date)):
        return _isoformat(o)
    if isinstance(o, UUID):
        return str(o)
    if isinstance(o, Decimal):
        # Preserve full NUMERIC precision; psycopg returns Postgres NUMERIC
        # columns as Decimal, and float() would lose precision.
        return str(o)
    raise TypeError(f"unserializable type {type(o)!r} in audit canonical payload")
