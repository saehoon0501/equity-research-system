"""Mode-fit dashboard derivation per Phase 4 Q5.

Per v3 spec Section 2.2 (Mode silent-failure detection):
  - Per-name quarterly re-classification — mismatch with stored mode →
    operator review + pre-mortem before reclassification (Section 6 Q4
    trigger 4).
  - Mode-implied-vol check (semi-annual) — 252d realized vol; >2σ outside
    mode band per Section 2.2 (B <25%, B' 25-50%, C >50%) for 2 consecutive
    checks → flag.
  - Mode-fit dashboard integrated into `/disposition`: per-row
    `mode | realized_252d_vol | last_confirmed_date | flag_status`.

Flag types surfaced (per Phase 4 Q5):
  - rule_output_mismatch        — quarterly reclassification flagged a
                                   different mode than current (recheck_status
                                   in {pending_review, reclassification_proposed}).
  - vol_band_inconsistency      — realized 252d vol outside mode band for
                                   2+ consecutive semi-annual checks
                                   (mode_vol_checks.flagged = true).
  - pending_reclassification    — recheck_status = 'reclassification_proposed';
                                   awaiting Section 6 Q4 pre-mortem and
                                   operator commit.
  - none                        — within band + last classification confirmed.

This module is a pure-derivation layer; reads from ModeFitRow + DispositionRow
data already loaded by `loader.py`.
"""

from __future__ import annotations

from typing import Any

# Closed-set of flag statuses surfaced in the dashboard.
FLAG_STATUSES: tuple[str, ...] = (
    "rule_output_mismatch",
    "vol_band_inconsistency",
    "pending_reclassification",
    "none",
)


def derive_flag_status(mode_fit: Any) -> str:
    """Return one of FLAG_STATUSES for a ModeFitRow.

    Precedence (most-severe first):
      1. pending_reclassification — operator must review pre-mortem.
      2. rule_output_mismatch     — quarterly reclassification disagrees.
      3. vol_band_inconsistency   — realized vol outside band for ≥2 checks.
      4. none                     — clean.

    Per Phase 4 Q5: flagged names cannot ride along quietly; surfaced for
    operator review.
    """
    recheck = (mode_fit.recheck_status or "").lower()

    if recheck == "reclassification_proposed":
        return "pending_reclassification"
    if recheck == "pending_review":
        return "rule_output_mismatch"

    # mode_vol_checks.flagged = true means consecutive_outside_count >= 2 per
    # Phase 4 Q5 + migration 010 schema.
    if mode_fit.flagged:
        return "vol_band_inconsistency"

    return "none"
