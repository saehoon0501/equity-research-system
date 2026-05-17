"""spec_approve — operator HMAC-attested sign-off on spec revisions.

Per v3 spec Section 5.4 + Section 8 PB#1.

Writes a sign-off attestation file to:

    docs/superpowers/specs/v<version>-signoff-attestation.md

Matching the pattern of the manually-authored
``docs/superpowers/specs/v3.0-signoff-attestation.md`` (canonical at v0.1).

The HMAC signature uses the canonical-payload contract from
``src/audit_trail/hmac_verify.py`` (sort_keys=True, separators=(',',':'),
ensure_ascii=False), keyed with ``AUDIT_HMAC_KEY``. The attestation file
captures: spec version, timestamp, operator, and HMAC signature. The
signature is over a canonical JSON of (version, spec_path, timestamp,
operator) — replayable for verification.

Reference:
  docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
    Section 5.4 (slash commands)
    Section 8  PB#1 (sign-off chain)
  docs/superpowers/specs/v3.0-signoff-attestation.md (template).
"""

from __future__ import annotations

__all__: list[str] = []
