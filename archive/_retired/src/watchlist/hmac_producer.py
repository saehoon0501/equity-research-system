"""Watchlist HMAC producer — signs the immutable anchor fields at P5 lock.

Per spec ``docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md``
Section 6.2 (HMAC-signed thesis pillars + scenario A baselines) and the
schema in ``007_v3_watchlist_positions.sql``::

    thesis_pillars_original           JSONB NOT NULL,
    thesis_pillars_original_hmac      TEXT NOT NULL,
    scenario_A_base_projections       JSONB NOT NULL,
    scenario_A_base_projections_hmac  TEXT NOT NULL,

The verifier (``src/anchor_drift/hmac_verify.py``) checks signatures using
``WATCHLIST_HMAC_SECRET`` and the canonical-JSON discipline from
``src/audit_trail/hmac_verify.py``. Until this module existed, no producer
wrote those signatures — the verifier had nothing to verify against. This
module fills the gap.

Canonical-payload contract: shared with every other HMAC producer in the
system via ``src/audit_trail/hmac_verify.py::canonical_payload_dict``::

    json.dumps(obj, sort_keys=True, separators=(',', ':'),
               ensure_ascii=False, default=_json_default).encode('utf-8')

  * UUIDs as ``str()``
  * datetimes as ISO8601 UTC
  * Decimals as ``str()`` (NUMERIC arrives as Decimal in psycopg)
  * unicode round-trips byte-identically (``ensure_ascii=False``)

Key scope: ``WATCHLIST_HMAC_SECRET`` only. Kept distinct from
``AUDIT_HMAC_KEY`` / ``PEAK_PAIN_HMAC_KEY`` / ``PREMORTEM_HMAC_SECRET`` so
secret rotation across modules is independent.

CRITICAL: every P5 watchlist INSERT MUST call ``sign_watchlist_row`` and
include the returned HMAC fields in the INSERT — otherwise the
NOT NULL ``*_hmac`` columns reject the row at the DB layer (and the
anchor-drift orchestrator would fire-false on the missing signatures).
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import os
from typing import Any, Optional

from src.anchor_drift.hmac_verify import canonical_json


WATCHLIST_HMAC_ENV = "WATCHLIST_HMAC_SECRET"
"""Env var holding the watchlist HMAC secret. REQUIRED for production writes."""


class WatchlistHmacError(RuntimeError):
    """Raised when the watchlist HMAC secret is unavailable."""


def _read_secret(hmac_key: Optional[bytes]) -> bytes:
    if hmac_key is not None:
        return hmac_key
    env = os.environ.get(WATCHLIST_HMAC_ENV)
    if not env:
        raise WatchlistHmacError(
            f"{WATCHLIST_HMAC_ENV} not set; refusing to sign watchlist row"
        )
    return env.encode("utf-8")


def _sign(payload: Any, key: bytes) -> str:
    """HMAC-SHA256 hex digest using the canonical_json scheme.

    Mirror of ``src/anchor_drift/hmac_verify.compute_hmac`` but with an
    explicit key argument so the producer doesn't have to re-read env
    twice. Both producer and verifier share ``canonical_json`` —
    canonicalization is byte-identical across the two paths.
    """
    msg = canonical_json(payload).encode("utf-8")
    return _hmac.new(key, msg, hashlib.sha256).hexdigest()


def sign_watchlist_row(
    thesis_pillars_original: Any,
    scenario_A_base_projections: Any,
    *,
    hmac_key: Optional[bytes] = None,
) -> dict[str, str]:
    """Sign the two immutable anchor fields for a P5 watchlist INSERT.

    Args:
        thesis_pillars_original:     JSONB payload going into the
                                     ``thesis_pillars_original`` column.
        scenario_A_base_projections: JSONB payload going into the
                                     ``scenario_A_base_projections`` column.
        hmac_key: explicit override; falls back to ``WATCHLIST_HMAC_SECRET``.

    Returns:
        dict with keys::

            {
                "thesis_pillars_original_hmac": "<hex>",
                "scenario_A_base_projections_hmac": "<hex>",
            }

        Caller spreads these into the INSERT alongside the JSONB columns.

    Raises:
        WatchlistHmacError: when no secret is available.

    Per v3 spec Section 6 Q5 + Section 6.2 anchor-drift HMAC contract.
    """
    key = _read_secret(hmac_key)
    return {
        "thesis_pillars_original_hmac": _sign(thesis_pillars_original, key),
        "scenario_A_base_projections_hmac": _sign(
            scenario_A_base_projections, key
        ),
    }


__all__ = [
    "WATCHLIST_HMAC_ENV",
    "WatchlistHmacError",
    "sign_watchlist_row",
]
