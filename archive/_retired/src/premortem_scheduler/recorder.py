"""Premortem recorder — captures completed pre-mortem session into ``premortem``.

Per spec ``docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md``
Section 4.5 Q4 + migrations ``012_v3_premortem.sql`` (base table) and
``016_v3_hmac_columns.sql`` (added ``hmac_signature`` + ``signed_at``).

This module owns the row-write contract for ``premortem``:

  * operator_imagined_failure_modes (jsonb; array of mode dicts incl.
    probability_estimate, kill_criterion_added, etc.)
  * thesis_pillars_revisited        (jsonb; array of pillar dicts incl.
    confidence_delta + verbatim_evidence)
  * net_thesis_strength             (numeric aggregate)
  * llm_assist_metadata             (jsonb; model='opus-*' for high-stakes)
  * trigger                         (one of VALID_TRIGGERS)
  * mode                            (B / B_prime / C)
  * days_since_last_premortem       (int)
  * hmac_signature                  (text; column-stored per migration 016)
  * signed_at                       (timestamptz; auto-stamped at write time)

The premortem JSONB blob (operator_imagined_failure_modes +
thesis_pillars_revisited) is HMAC-signed via canonical-JSON
serialization (canonical_payload_dict from src/audit_trail/hmac_verify.py).
Per Section 5 Q1, the secret comes from ``PREMORTEM_HMAC_SECRET`` —
a SEPARATE scope from the audit-chain (``AUDIT_HMAC_KEY``) and watchlist
(``WATCHLIST_HMAC_SECRET``) keys; rotating one does not affect the others.
The signature now lives in its own column rather than as a JSONB key under
``llm_assist_metadata.payload_hmac``.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from src.audit_trail.hmac_verify import _json_default

from . import VALID_TRIGGERS
from .devils_advocate import DevilsAdvocateOutput

_LOG = logging.getLogger(__name__)


def _dsn() -> str:
    return os.environ.get(
        "EQUITY_RESEARCH_DSN",
        "postgresql://postgres@127.0.0.1:5432/equity_research",
    )


@dataclass
class PremortemRecord:
    """Operator-completed pre-mortem session payload."""

    ticker: str
    premortem_date: str  # ISO date
    trigger: str
    mode: Optional[str]
    operator_imagined_failure_modes: list[dict[str, Any]] = field(
        default_factory=list
    )
    thesis_pillars_revisited: list[dict[str, Any]] = field(default_factory=list)
    net_thesis_strength: Optional[float] = None
    llm_assist: Optional[DevilsAdvocateOutput] = None
    operator_accepted_count: int = 0
    operator_rejected_count: int = 0
    days_since_last_premortem: Optional[int] = None
    parameters_version: Optional[uuid.UUID] = None


def _compute_payload_hmac(
    failure_modes: list[dict[str, Any]],
    pillars: list[dict[str, Any]],
) -> Optional[str]:
    """Sign the operator-authored JSONB blobs with PREMORTEM_HMAC_SECRET.

    Uses the canonical scheme from ``src/audit_trail/hmac_verify.py`` via
    the dedicated wrapper ``src/premortem_scheduler/hmac.py``. Returns
    None when the secret is unset so dev/test paths can record unsigned
    rows; production callers should arrange the env var to be set.

    Per v3 spec Section 5 Q1.
    """
    from src.premortem_scheduler.hmac import compute_premortem_hmac

    payload = {
        "failure_modes": failure_modes,
        "pillars_revisited": pillars,
    }
    return compute_premortem_hmac(payload, strict=False)


def record_premortem(
    record: PremortemRecord,
    *,
    persist: bool = True,
    connection: Any | None = None,
) -> uuid.UUID:
    """Insert one pre-mortem session into the ``premortem`` table.

    Args:
        record: PremortemRecord populated by the operator session.
        persist: when False, skip the DB INSERT (returns a fresh uuid).
        connection: optional psycopg connection (tests).

    Returns:
        ``premortem_id`` (uuid).

    Raises:
        ValueError: trigger not in the migration's CHECK constraint set.
    """
    if record.trigger not in VALID_TRIGGERS:
        raise ValueError(
            f"trigger {record.trigger!r} not in {sorted(VALID_TRIGGERS)}"
        )

    pid = uuid.uuid4()
    payload_hmac = _compute_payload_hmac(
        record.operator_imagined_failure_modes,
        record.thesis_pillars_revisited,
    )

    if record.llm_assist is not None:
        llm_metadata = record.llm_assist.to_metadata(
            accepted_count=record.operator_accepted_count,
            rejected_count=record.operator_rejected_count,
        )
    else:
        llm_metadata = {
            "model": None,
            "role": None,
            "operator_accepted_count": record.operator_accepted_count,
            "operator_rejected_count": record.operator_rejected_count,
        }
    # NOTE: payload_hmac is no longer embedded inside llm_assist_metadata.
    # Per migration 016 it lives in the dedicated `hmac_signature` column.

    if not persist:
        return pid

    import psycopg  # deferred

    own = connection is None
    conn = connection or psycopg.connect(_dsn())
    try:
        with conn.cursor() as cur:
            # Idempotency: migration 022 adds UNIQUE (ticker, premortem_date,
            # trigger) on premortem. Operator double-click on /premortem
            # would otherwise duplicate rows — and because the row is
            # HMAC-signed (column hmac_signature), the duplicate would have
            # an identical signature, making the audit chain ambiguous
            # ("which row is the canonical capture?"). First-call-wins via
            # ON CONFLICT DO NOTHING is correct: the operator's first
            # successful submit is the canonical record; a retry on top of
            # it is silently a no-op. RETURNING premortem_id lets us return
            # the canonical id (either the new one we just inserted, or the
            # prior one we conflict-bounced against — re-fetched below).
            cur.execute(
                """
                INSERT INTO premortem (
                    premortem_id, ticker, premortem_date,
                    trigger, days_since_last_premortem, mode,
                    operator_imagined_failure_modes,
                    thesis_pillars_revisited,
                    net_thesis_strength,
                    llm_assist_metadata,
                    parameters_version,
                    hmac_signature,
                    signed_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
                )
                ON CONFLICT (ticker, premortem_date, trigger) DO NOTHING
                RETURNING premortem_id
                """,
                (
                    pid,
                    record.ticker.upper().strip(),
                    record.premortem_date,
                    record.trigger,
                    record.days_since_last_premortem,
                    record.mode,
                    json.dumps(
                        record.operator_imagined_failure_modes, default=_json_default
                    ),
                    json.dumps(record.thesis_pillars_revisited, default=_json_default),
                    record.net_thesis_strength,
                    json.dumps(llm_metadata, default=_json_default),
                    record.parameters_version,
                    payload_hmac or "",
                ),
            )
            inserted = cur.fetchone()
            if inserted is None:
                # Conflict no-op: re-fetch the prior canonical premortem_id
                # so the caller has a stable handle into the audit chain.
                cur.execute(
                    "SELECT premortem_id FROM premortem "
                    "WHERE ticker = %s AND premortem_date = %s "
                    "  AND trigger = %s",
                    (
                        record.ticker.upper().strip(),
                        record.premortem_date,
                        record.trigger,
                    ),
                )
                existing = cur.fetchone()
                if existing is not None:
                    pid = existing[0]
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()
    return pid


__all__ = ["PremortemRecord", "record_premortem"]
