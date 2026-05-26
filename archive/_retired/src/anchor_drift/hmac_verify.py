"""HMAC verification for the immutable anchor fields on the watchlist.

Per spec ``docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md``
Section 6.2 (HMAC-signed thesis pillars + scenario A baselines) and the
schema choice in ``007_v3_watchlist_positions.sql``::

    thesis_pillars_original         JSONB NOT NULL,
    thesis_pillars_original_hmac    TEXT NOT NULL,
    scenario_A_base_projections     JSONB NOT NULL,
    scenario_A_base_projections_hmac TEXT NOT NULL,

The HMAC is computed over the **canonical-JSON serialization** of the
JSONB at P5 lock. We delegate canonicalization to
``src/audit_trail/hmac_verify.py`` — single source of truth for the
canonical-payload contract (sort_keys, separators, ``ensure_ascii=False``,
UUID/datetime/Decimal defaults). We use ``hmac.compare_digest`` for
constant-time comparison; mismatch surfaces tampering as a system event
the anchor-drift orchestrator treats the same as a triggered channel.

The shared secret is read from the env var ``WATCHLIST_HMAC_SECRET`` —
provisioned out-of-band by the operator at install time. This is a
SEPARATE scope from AUDIT_HMAC_KEY / PEAK_PAIN_HMAC_KEY /
PREMORTEM_HMAC_SECRET so the four modules' secrets rotate independently.

Producer side: ``src/watchlist/hmac_producer.py::sign_watchlist_row``
writes signatures using the same canonical scheme; round-trip tests live
in ``tests/test_watchlist_hmac_producer.py``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any

from src.audit_trail.hmac_verify import _json_default


class HmacVerificationError(RuntimeError):
    """Raised when HMAC verification fails or the secret is missing."""


def canonical_json(obj: Any) -> str:
    """Stable JSON serialization for HMAC computation.

    Delegates to the canonical-payload contract from
    ``src/audit_trail/hmac_verify.py``: sort_keys, tight separators,
    ``ensure_ascii=False`` (unicode round-trips byte-identically),
    UUID/datetime/Decimal handled via ``_json_default``.
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_json_default,
    )


def _secret() -> bytes:
    secret = os.environ.get("WATCHLIST_HMAC_SECRET")
    if not secret:
        raise HmacVerificationError(
            "WATCHLIST_HMAC_SECRET not set; refusing to verify anchor HMAC"
        )
    return secret.encode("utf-8")


def compute_hmac(payload: Any) -> str:
    """Return the hex digest for the canonical-JSON serialization of payload."""
    msg = canonical_json(payload).encode("utf-8")
    return hmac.new(_secret(), msg, hashlib.sha256).hexdigest()


def verify_hmac(payload: Any, expected_hmac: str) -> bool:
    """Constant-time verify; returns True on match, False on mismatch.

    A False return indicates tampering OR a secret-rotation skew; either
    way the anchor-drift orchestrator treats it as a triggered channel.
    """
    if not isinstance(expected_hmac, str) or not expected_hmac:
        return False
    actual = compute_hmac(payload)
    return hmac.compare_digest(actual, expected_hmac)


def verify_pillars_hmac(
    thesis_pillars_original: Any, hmac_signature: str
) -> bool:
    """Verify the HMAC on ``watchlist.thesis_pillars_original``."""
    return verify_hmac(thesis_pillars_original, hmac_signature)


def verify_scenario_hmac(
    scenario_A_base_projections: Any, hmac_signature: str
) -> bool:
    """Verify the HMAC on ``watchlist.scenario_A_base_projections``."""
    return verify_hmac(scenario_A_base_projections, hmac_signature)


__all__ = [
    "HmacVerificationError",
    "canonical_json",
    "compute_hmac",
    "verify_hmac",
    "verify_pillars_hmac",
    "verify_scenario_hmac",
]
