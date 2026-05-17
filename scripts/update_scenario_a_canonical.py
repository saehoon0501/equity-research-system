#!/usr/bin/env python3
"""One-shot UPDATE: add canonical {revenue, gross_margin, fcf} top-level keys
to each watchlist row's scenario_A_base_projections + re-sign HMAC.

Spec context (v3 §4.5 Q5): Channel 2 outcome divergence reads top-level
``revenue``, ``gross_margin``, ``fcf`` keys. The 9 watchlist rows persisted
on 2026-05-06 used a richer nested schema (fy26_op_margin_pct etc.) that
Channel 2 cannot consume. This script adds the canonical scalar P50 anchors
WITHOUT removing the extended nested data — both coexist.

Spec immutability note: scenario_A_base_projections is "immutable at P5
lock". This UPDATE is a one-time schema-correction during initial v0.1
setup (rows added 2026-05-05; corrected 2026-05-06). After this point
scenario_A is treated as immutable per the spec contract.

Run:
    python scripts/update_scenario_a_canonical.py
"""
from __future__ import annotations

import os
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg
from src.watchlist.hmac_producer import sign_watchlist_row


def _build_dsn() -> str:
    if dsn := os.environ.get("DATABASE_URL"):
        return dsn
    user = os.environ.get("POSTGRES_USER", "postgres")
    pwd = os.environ.get("POSTGRES_PASSWORD", "")
    host = os.environ.get("POSTGRES_HOST", "127.0.0.1")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "equity_research")
    return f"postgresql://{user}:{pwd}@{host}:{port}/{db}"


# Per-ticker canonical anchors (USD, fractions). Derived from the same data
# the persist_watchlist_2026_05_06.py script's updated scenario_A blocks.
CANONICAL_OVERRIDES: dict[str, dict[str, float]] = {
    "AMZN": {"revenue": 870e9, "gross_margin": 0.46, "fcf": 8e9},
    "MSFT": {"revenue": 322e9, "gross_margin": 0.68, "fcf": 35e9},
    "ORCL": {"revenue": 66e9,  "gross_margin": 0.68, "fcf": -10e9},
    "ASML": {"revenue": 44.6e9, "gross_margin": 0.52, "fcf": 12e9},
    "ANET": {"revenue": 11.2e9, "gross_margin": 0.625, "fcf": 4e9},
    "CEG":  {"revenue": 28e9,  "gross_margin": 0.32, "fcf": 2.5e9},
    "VRT":  {"revenue": 13.75e9, "gross_margin": 0.37, "fcf": 2.2e9},
    "CRWD": {"revenue": 5.9e9, "gross_margin": 0.74, "fcf": 1.5e9},
    "DDOG": {"revenue": 4.10e9, "gross_margin": 0.80, "fcf": 1.10e9},
}


def main() -> int:
    dsn = _build_dsn()
    updated = 0
    skipped = 0
    with psycopg.connect(dsn) as conn:
        for ticker, canon in CANONICAL_OVERRIDES.items():
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT thesis_pillars_original, scenario_a_base_projections "
                    "FROM watchlist WHERE ticker = %s",
                    (ticker,),
                )
                row = cur.fetchone()
                if row is None:
                    print(f"  ! {ticker}: not in watchlist; skip")
                    skipped += 1
                    continue
                pillars, scenario_a = row
                # Skip if already has canonical keys (idempotent)
                if all(k in scenario_a for k in ("revenue", "gross_margin", "fcf")):
                    print(f"  = {ticker}: canonical keys already present; skip")
                    skipped += 1
                    continue
                # Insert canonical keys at top level (preserves nested extended fields)
                new_scenario_a = {**canon, **scenario_a}
                # Re-sign HMACs (both fields, since sign_watchlist_row signs together)
                sigs = sign_watchlist_row(
                    list(pillars) if isinstance(pillars, list) else pillars,
                    new_scenario_a,
                )
                cur.execute(
                    "UPDATE watchlist SET "
                    "  scenario_a_base_projections = %s::jsonb, "
                    "  scenario_a_base_projections_hmac = %s, "
                    "  thesis_pillars_original_hmac = %s "
                    "WHERE ticker = %s",
                    (
                        json.dumps(new_scenario_a),
                        sigs["scenario_A_base_projections_hmac"],
                        sigs["thesis_pillars_original_hmac"],
                        ticker,
                    ),
                )
                conn.commit()
                print(
                    f"  ✓ {ticker}: canonical {canon} added; "
                    f"hmac=...{sigs['scenario_A_base_projections_hmac'][-12:]}"
                )
                updated += 1
    print(f"\nUpdated: {updated} | Skipped: {skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
