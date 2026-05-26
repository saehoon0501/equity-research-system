"""HMAC helper for premortem rows — thin wrapper around audit_trail.hmac_verify.

Per v3 spec Section 5 Q1 (audit-chain HMAC) + Section 6 Q5 (anchor-drift HMAC):
the canonical-payload contract lives in ``src/audit_trail/hmac_verify.py``;
every HMAC producer in the system MUST use it. This module specializes that
contract to:

  * the dedicated ``PREMORTEM_HMAC_SECRET`` env var (separate scope from
    AUDIT_HMAC_KEY, PEAK_PAIN_HMAC_KEY, WATCHLIST_HMAC_SECRET so secrets
    can rotate independently across modules), and
  * the column-stored HMAC schema added by migration ``016_v3_hmac_columns.sql``
    (``premortem.hmac_signature TEXT`` + ``premortem.signed_at TIMESTAMPTZ``).

Public API:
  * ``compute_premortem_hmac(payload)`` — sign the operator-authored payload.
  * ``verify_premortem_hmac(payload, expected)`` — constant-time check.
"""

from __future__ import annotations

import hmac as _hmac
import os
from typing import Any, Mapping, Optional

from src.audit_trail.hmac_verify import (
    canonical_payload_dict,
    compute_signature_dict,
)

PREMORTEM_HMAC_ENV = "PREMORTEM_HMAC_SECRET"
"""Env var holding the premortem HMAC secret. Required for production writes."""


class PremortemHmacError(RuntimeError):
    """Raised when the premortem HMAC secret is unavailable in strict mode."""


def _read_secret(hmac_key: Optional[bytes], *, strict: bool) -> Optional[bytes]:
    if hmac_key is not None:
        return hmac_key
    env = os.environ.get(PREMORTEM_HMAC_ENV)
    if env:
        return env.encode("utf-8")
    if strict:
        raise PremortemHmacError(
            f"{PREMORTEM_HMAC_ENV} not set; refusing to compute premortem HMAC"
        )
    return None


def compute_premortem_hmac(
    payload: Mapping[str, Any],
    *,
    hmac_key: Optional[bytes] = None,
    strict: bool = True,
) -> Optional[str]:
    """Sign a premortem payload using the canonical scheme.

    Args:
        payload:  dict containing the operator-authored JSONB blobs (commonly
                  ``{"failure_modes": [...], "pillars_revisited": [...]}``).
        hmac_key: explicit override; falls back to ``PREMORTEM_HMAC_SECRET``.
        strict:   when True (default) and no key is found, raises
                  ``PremortemHmacError``. When False, returns ``None`` so the
                  caller can choose to write an unsigned row in dev paths.

    Returns:
        Hex-encoded HMAC-SHA256, or ``None`` only when ``strict=False`` and
        no key is available.
    """
    key = _read_secret(hmac_key, strict=strict)
    if key is None:
        return None
    return compute_signature_dict(payload, key)


def verify_premortem_hmac(
    payload: Mapping[str, Any],
    expected: str,
    *,
    hmac_key: Optional[bytes] = None,
) -> bool:
    """Constant-time verify a stored premortem signature.

    Returns False on any mismatch including empty/missing signatures.
    Strict-mode key lookup: a missing key raises ``PremortemHmacError`` so
    misconfiguration is loud rather than silently False.
    """
    if not expected:
        return False
    key = _read_secret(hmac_key, strict=True)
    if key is None:  # pragma: no cover — strict above raises
        return False
    actual = compute_signature_dict(payload, key)
    return _hmac.compare_digest(actual, expected)


__all__ = [
    "PREMORTEM_HMAC_ENV",
    "PremortemHmacError",
    "compute_premortem_hmac",
    "verify_premortem_hmac",
]
