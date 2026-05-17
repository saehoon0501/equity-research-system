"""watchlist — producer-side HMAC for the P5 watchlist anchor fields.

The verifier lives in ``src/anchor_drift/hmac_verify.py`` (per Section 6.2 of
the v3 spec). This package houses the WRITE-side helper so any P5 watchlist
INSERT goes out with valid signatures on
``thesis_pillars_original_hmac`` + ``scenario_A_base_projections_hmac``.

Public API:
  * ``sign_watchlist_row`` — return both HMAC fields ready to attach to an
    INSERT.

Per v3 spec Section 6 Q5 + ``db/migrations/007_v3_watchlist_positions.sql``.
"""

from __future__ import annotations

from src.watchlist.hmac_producer import sign_watchlist_row

__all__ = ["sign_watchlist_row"]
