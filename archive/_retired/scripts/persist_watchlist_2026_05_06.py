#!/usr/bin/env python3
"""One-shot watchlist persistence — PMSupervisor synthesis 2026-05-06.

Inserts the 9 WATCH-disposition tickers from the May 6 2026 research session
into the watchlist table via src.p5_watchlist.adder.add_to_watchlist (which
handles HMAC signing internally using WATCHLIST_HMAC_SECRET).

Excludes:
  - GOOGL, AMD, MU (REJECT — disposition determined by CDD/BearCase synthesis)
  - BE (PASS — labeling unresolved, multiple severe concerns)
  - PLTR (already present in watchlist)

Run from repo root:
    python scripts/persist_watchlist_2026_05_06.py
"""
from __future__ import annotations

import os
import sys
import datetime as _dt
from pathlib import Path

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.p5_watchlist.adder import (
    WatchlistAddInput,
    add_to_watchlist,
)

import psycopg


def _build_dsn() -> str:
    if dsn := os.environ.get("DATABASE_URL"):
        return dsn
    user = os.environ.get("POSTGRES_USER", "postgres")
    pwd = os.environ.get("POSTGRES_PASSWORD", "")
    host = os.environ.get("POSTGRES_HOST", "127.0.0.1")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "equity_research")
    return f"postgresql://{user}:{pwd}@{host}:{port}/{db}"


DSN = _build_dsn()


def watchlist_inputs() -> list[WatchlistAddInput]:
    """The 9 WATCH-disposition tickers from 2026-05-06 PMSupervisor synthesis.

    Each input bundle carries minimal-but-defensible thesis_pillars +
    scenario_A_base_projections referencing the CDD agent_run_id (Tier 1
    in evidence_index). PMSupervisor reasoning trace lives separately in
    the operator briefing; this is the watchlist-row substrate for
    /daily-monitor coverage.
    """
    return [
        WatchlistAddInput(
            ticker="AMZN",
            mode="B_prime",
            company_quality_flag="HIGH",
            pm_supervisor_decision="ADD",
            thesis_pillars_original=[
                {"id": "TP-1", "claim": "AWS 18-22% growth + 33%+ op margin through FY27",
                 "kpi": "Quarterly AWS segment cc growth + op margin", "resolution_date": "2027-02-15"},
                {"id": "TP-2", "claim": "AWS AI infra drives >=35% of incremental AWS revenue FY26-27",
                 "kpi": "AI-revenue mix commentary in earnings calls", "resolution_date": "2027-02-15"},
                {"id": "TP-3", "claim": "Advertising revenue compounds 18-22% with op margin >50%",
                 "kpi": "Disclosed Advertising segment revenue + implied margin", "resolution_date": "2027-02-15"},
                {"_source_memo": {"as_of_date": "2026-05-06",
                                  "cdd_agent_run_id": "19c6a00c-9eec-5a69-aff0-d15f6456cf6b",
                                  "p50_fair_value_usd": 230,
                                  "current_price_at_research_usd": 275.32}},
            ],
            scenario_A_base_projections={
                # Canonical schema per spec §4.5 Q5 (Channel 2 outcome divergence)
                "revenue": 870e9,         # FY26 P50 USD: FY25 $716.9B + ~22% growth
                "gross_margin": 0.46,     # FY25 ~46%; P50 maintained
                "fcf": 8e9,               # FY26 P50 USD: capex digestion year, materially below FY24 $32B
                # Extended (P10/P50/P90 for richer downstream consumers)
                "fy26_aws_growth_pct": {"p10": 14, "p50": 19, "p90": 24},
                "fy26_op_margin_pct":  {"p10": 7, "p50": 9, "p90": 11},
                "fy26_capex_usd_b":    {"p10": 130, "p50": 165, "p90": 195},
                "_resolution_date": "2027-02-15",
            },
            macro_regime_style_output="HIGH",  # AI-capex-cycle leveraged
            conviction_threshold_override=0.65,  # bear catastrophic concern (vendor-financing circular)
        ),
        WatchlistAddInput(
            ticker="MSFT",
            mode="B",
            company_quality_flag="HIGH",
            pm_supervisor_decision="ADD",
            thesis_pillars_original=[
                {"id": "TP-1", "claim": "Azure cc growth >=28% through FY27",
                 "kpi": "Quarterly Azure & other cloud cc growth", "resolution_date": "2027-06-30"},
                {"id": "TP-2", "claim": "Operating margin >=45% FY27 despite capex/D&A pressure",
                 "kpi": "FY27 consolidated op margin", "resolution_date": "2027-08-15"},
                {"id": "TP-3", "claim": "FY27 FCF >=$80B (relaxed from CDD $90B per bear analysis)",
                 "kpi": "OCF - capex annual", "resolution_date": "2027-08-15"},
                {"_source_memo": {"as_of_date": "2026-05-06",
                                  "cdd_agent_run_id": "44aa8f95-3c67-5649-9c9f-49a397cd7724",
                                  "p50_fair_value_usd": 465,
                                  "current_price_at_research_usd": 409.63}},
            ],
            scenario_A_base_projections={
                # Canonical schema (spec §4.5 Q5)
                "revenue": 322e9,        # FY26 (Jun-end) P50 ~$282B FY25 + ~14% growth
                "gross_margin": 0.68,    # FY25 ~70%; FY26 P50 with capex/D&A pressure
                "fcf": 35e9,             # FY26 P50 (Q3 FY26 9M FCF $17.8B annualized = $24B; recovery to ~$35B P50)
                # Extended
                "fy27_azure_cc_growth_pct": {"p10": 22, "p50": 28, "p90": 34},
                "fy27_op_margin_pct":       {"p10": 42, "p50": 45, "p90": 48},
                "fy27_fcf_usd_b":           {"p10": 60, "p50": 80, "p90": 95},
                "_resolution_date": "2027-08-15",
            },
            macro_regime_style_output="MEDIUM",
        ),
        WatchlistAddInput(
            ticker="ORCL",
            mode="B_prime",
            company_quality_flag="HIGH",
            pm_supervisor_decision="ADD",
            thesis_pillars_original=[
                {"id": "TP-1", "claim": "OCI revenue >=$25B FY27",
                 "kpi": "Cloud Infrastructure offering line FY27", "resolution_date": "2027-06-30"},
                {"id": "TP-2", "claim": "RPO 12mo conversion >=16% by Q3 FY27 (vs 12% current)",
                 "kpi": "Quarterly RPO duration disclosure", "resolution_date": "2027-03-31"},
                {"id": "TP-3", "claim": "FY27 GAAP op margin >=28% despite capex burn",
                 "kpi": "FY27 10-K op margin", "resolution_date": "2027-06-30"},
                {"_source_memo": {"as_of_date": "2026-05-06",
                                  "cdd_agent_run_id": "df94b1f1-c90a-59b9-9377-7dfda54e41ad",
                                  "p50_fair_value_usd": 230,
                                  "current_price_at_research_usd": 182.91,
                                  "catastrophic_flags": 3}},
            ],
            scenario_A_base_projections={
                # Canonical schema
                "revenue": 66e9,         # FY26 (May-end) P50 ~$57B FY25 + ~16% growth
                "gross_margin": 0.68,    # FY25 ~70%; FY26 P50 with OCI capex pressure
                "fcf": -10e9,            # FY26 P50: TTM FCF -$24.7B; capex normalization narrows
                # Extended
                "fy27_oci_revenue_usd_b":      {"p10": 22, "p50": 26, "p90": 32},
                "fy27_rpo_12mo_pct":           {"p10": 12, "p50": 16, "p90": 20},
                "fy27_op_margin_pct":          {"p10": 25, "p50": 28, "p90": 31},
                "fy27_capex_revenue_ratio_pct":{"p10": 60, "p50": 70, "p90": 85},
                "_resolution_date": "2027-06-30",
            },
            macro_regime_style_output="HIGH",
            conviction_threshold_override=0.70,  # 3 catastrophic flags
        ),
        WatchlistAddInput(
            ticker="ASML",
            mode="B_prime",
            company_quality_flag="HIGH",
            pm_supervisor_decision="ADD",
            thesis_pillars_original=[
                {"id": "TP-1", "claim": "FY26 revenue >=EUR36B (lower bound of raised guide)",
                 "kpi": "FY26 20-F net sales", "resolution_date": "2027-02-28"},
                {"id": "TP-2", "claim": "Customer concentration normalizes (top-1 19-26% range)",
                 "kpi": "20-F customer concentration disclosure", "resolution_date": "2027-02-28"},
                {"id": "TP-3", "claim": "High-NA EUV reaches >=8 cumulative HVM units by FY27",
                 "kpi": "Annual High-NA shipment disclosure", "resolution_date": "2028-02-28"},
                {"_source_memo": {"as_of_date": "2026-05-06",
                                  "cdd_agent_run_id": "60f3687b-82fe-42f3-bccd-2420848f894b",
                                  "p50_fair_value_adr_usd": 1250,
                                  "current_price_adr_usd": 1442.92,
                                  "fx_eur_usd": 1.1755}},
            ],
            scenario_A_base_projections={
                # Canonical schema (USD-converted at 1.1755 EUR/USD per FRED 2026-05-01)
                "revenue": 44.6e9,       # FY26 P50 €38B * 1.1755
                "gross_margin": 0.52,    # FY26 guide 51-53% midpoint
                "fcf": 12e9,             # FY26 P50: ~€10B * 1.1755 (FY25 NI €9.6B as proxy)
                # Extended (EUR-native)
                "fy26_revenue_eur_b": {"p10": 35, "p50": 38, "p90": 40.5},
                "fy26_gm_pct":        {"p10": 50, "p50": 52, "p90": 54},
                "fy27_high_na_hvm_units_cumulative": {"p10": 4, "p50": 9, "p90": 14},
                "fy26_top1_customer_pct":            {"p10": 19, "p50": 22, "p90": 26},
                "_resolution_date": "2027-02-28",
            },
            macro_regime_style_output="HIGH",
            conviction_threshold_override=0.65,
        ),
        WatchlistAddInput(
            ticker="ANET",
            mode="B_prime",
            company_quality_flag="HIGH",
            pm_supervisor_decision="ADD",
            thesis_pillars_original=[
                {"id": "TP-1", "claim": "FY26 revenue >=$11.0B (+22% YoY off $9.0B)",
                 "kpi": "FY26 10-K net revenue", "resolution_date": "2027-02-15"},
                {"id": "TP-2", "claim": "FY26 non-GAAP op margin >=45% sustained quarterly",
                 "kpi": "Quarterly non-GAAP op margin", "resolution_date": "2027-02-15"},
                {"id": "TP-3", "claim": "Customer-IDENTITY rotation stabilizes (Microsoft <=44% AND Meta >=14%)",
                 "kpi": "FY26 10-K end-customer disclosure", "resolution_date": "2027-02-17"},
                {"_source_memo": {"as_of_date": "2026-05-06",
                                  "cdd_agent_run_id": "79365f85-ae0e-5132-90d4-090da7bb8016",
                                  "p50_fair_value_usd": 106,
                                  "current_price_at_research_usd": 173.35,
                                  "pltr_style_methodology_review": True,
                                  "lone_bear_envelope_low_usd": 110}},
            ],
            scenario_A_base_projections={
                # Canonical schema
                "revenue": 11.2e9,
                "gross_margin": 0.625,   # FY26 P50 (Q1'26 guide 62-63% non-GAAP, midpoint)
                "fcf": 4e9,
                # Extended
                "fy26_revenue_usd_b":         {"p10": 10.4, "p50": 11.2, "p90": 11.7},
                "fy26_non_gaap_op_margin_pct":{"p10": 41, "p50": 45, "p90": 48},
                "fy26_microsoft_pct":         {"p10": 22, "p50": 28, "p90": 34},
                "fy26_top2_resellers_ar_pct": {"p10": 50, "p50": 54, "p90": 58},
                "_resolution_date": "2027-02-15",
            },
            macro_regime_style_output="HIGH",
            conviction_threshold_override=0.70,  # PLTR-style methodology trigger
        ),
        WatchlistAddInput(
            ticker="CEG",
            mode="B_prime",
            company_quality_flag="HIGH",
            pm_supervisor_decision="ADD",
            thesis_pillars_original=[
                {"id": "TP-1", "claim": "Hyperscaler nuclear PPA pipeline conversion: 6+ GW signed by FY27",
                 "kpi": "Cumulative announced binding PPA capacity", "resolution_date": "2027-12-31"},
                {"id": "TP-2", "claim": "PJM 2027/28 BRA clears >=$200/MW-day (vs $269 2025/26)",
                 "kpi": "PJM BRA auction result", "resolution_date": "2026-12-31"},
                {"id": "TP-3", "claim": "Nuclear fleet capacity factor >=93% TTM through 2027",
                 "kpi": "10-K capacity factor disclosure", "resolution_date": "2027-12-31"},
                {"_source_memo": {"as_of_date": "2026-05-06",
                                  "cdd_agent_run_id": "9508c107-506c-5c2b-b56c-36f109076931",
                                  "p50_fair_value_usd": 245,
                                  "current_price_at_research_usd": 322.62,
                                  "ferc_co_located_load_show_cause_active": True}},
            ],
            scenario_A_base_projections={
                # Canonical schema
                "revenue": 28e9,
                "gross_margin": 0.32,   # FY25 ~32%
                "fcf": 2.5e9,
                # Extended
                "fy26_revenue_usd_b":            {"p10": 26, "p50": 28, "p90": 30},
                "pjm_bra_27_28_dollars_mw_day":  {"p10": 100, "p50": 200, "p90": 280},
                "calpine_synergy_run_rate_usd_b":{"p10": 0.8, "p50": 1.2, "p90": 1.6},
                "_resolution_date": "2027-12-31",
            },
            macro_regime_style_output="MEDIUM",
            conviction_threshold_override=0.70,  # FERC co-located load catastrophic flag
        ),
        WatchlistAddInput(
            ticker="VRT",
            mode="B_prime",
            company_quality_flag="HIGH",
            pm_supervisor_decision="ADD",
            thesis_pillars_original=[
                {"id": "TP-1", "claim": "FY26 revenue $13.5-14.0B per management guide (organic +29-31%)",
                 "kpi": "FY26 net sales actual vs guide", "resolution_date": "2027-02-15"},
                {"id": "TP-2", "claim": "EMEA inflects positive by Q4 2026 (vs Q1 -29.4% organic)",
                 "kpi": "Quarterly EMEA segment organic growth", "resolution_date": "2027-02-15"},
                {"id": "TP-3", "claim": "Inventory normalizes - DIO <90 days by Q3 2026",
                 "kpi": "Quarterly inventory / quarterly COGS", "resolution_date": "2026-11-15"},
                {"_source_memo": {"as_of_date": "2026-05-06",
                                  "cdd_agent_run_id": "f4229a12-9a87-58c9-a3eb-35fbb58b7184",
                                  "current_price_at_research_usd": 335.97,
                                  "cisco_2001_fingerprint_flagged": True}},
            ],
            scenario_A_base_projections={
                # Canonical schema
                "revenue": 13.75e9,      # FY26 guide $13.5-14.0B mid
                "gross_margin": 0.37,    # FY25/Q1'26 actual ~37%
                "fcf": 2.2e9,            # FY26 adj FCF guide $2.1-2.3B mid
                # Extended
                "fy26_revenue_usd_b":     {"p10": 12.8, "p50": 13.8, "p90": 14.0},
                "fy26_adj_op_margin_pct": {"p10": 21, "p50": 23, "p90": 24},
                "emea_organic_yoy_q4_pct":{"p10": -10, "p50": 0, "p90": 8},
                "_resolution_date": "2027-02-15",
            },
            macro_regime_style_output="HIGH",
            conviction_threshold_override=0.70,
        ),
        WatchlistAddInput(
            ticker="CRWD",
            mode="B_prime",
            company_quality_flag="HIGH",
            pm_supervisor_decision="ADD",
            thesis_pillars_original=[
                {"id": "TP-1", "claim": "FY27 ending ARR >=$6.40B (vs $5.25B FY26)",
                 "kpi": "FY27 disclosed ARR", "resolution_date": "2027-03-15"},
                {"id": "TP-2", "claim": "Dollar-based net retention rate >=113% any quarter through Q2 FY27",
                 "kpi": "Quarterly NRR disclosure", "resolution_date": "2026-09-15"},
                {"id": "TP-3", "claim": "SEC/DOJ inquiry resolves without Wells notice or restatement by 2027-12-31",
                 "kpi": "SEC enforcement filing tracker / 8-K disclosures", "resolution_date": "2027-12-31"},
                {"_source_memo": {"as_of_date": "2026-05-06",
                                  "cdd_agent_run_id": "00000000-0000-5000-8000-aa10000000a2",
                                  "p50_fair_value_usd": 415,
                                  "current_price_at_research_usd": 476.01,
                                  "note_16_restatement_verified": True,
                                  "icfr_effective": True,
                                  "buyback_authorization_usd_b": 1.5}},
            ],
            scenario_A_base_projections={
                # Canonical schema (FY27 ending Jan 2027 anchor — closest to "next FY" target)
                "revenue": 5.9e9,        # FY27 guide $5.87-5.93B mid
                "gross_margin": 0.74,    # FY26 GAAP subscription GM ~75-78%; consolidated ~74%
                "fcf": 1.5e9,            # FY27 P50 (vs FY26 $1.24B)
                # Extended
                "fy27_arr_usd_b":              {"p10": 6.20, "p50": 6.50, "p90": 6.80},
                "nrr_pct_q4_fy27":             {"p10": 110, "p50": 115, "p90": 118},
                "fy27_fcf_usd_b":              {"p10": 1.3, "p50": 1.5, "p90": 1.7},
                "_resolution_date": "2027-03-15",
            },
            macro_regime_style_output="MEDIUM",
        ),
        WatchlistAddInput(
            ticker="DDOG",
            mode="B_prime",
            company_quality_flag="HIGH",
            pm_supervisor_decision="ADD",
            thesis_pillars_original=[
                {"id": "TP-1", "claim": "FY26 revenue $4.06-4.18B (within management guide $4.06-4.10B)",
                 "kpi": "FY26 actual revenue vs guide", "resolution_date": "2027-02-28"},
                {"id": "TP-2", "claim": "AI-native cohort growth contribution stops decelerating below 6 ppts",
                 "kpi": "Quarterly AI-native cohort YoY contribution", "resolution_date": "2027-02-28"},
                {"id": "TP-3", "claim": "% customers using 4+ products >=52% by FY26 year-end",
                 "kpi": "10-K multi-product attach disclosure", "resolution_date": "2027-02-28"},
                {"_source_memo": {"as_of_date": "2026-05-06",
                                  "cdd_agent_run_id": "db40e283-dc36-521d-8874-7905bbda7b9e",
                                  "p50_fair_value_usd": 130,
                                  "current_price_at_research_usd": 145.91,
                                  "openai_attribution_press_only": True,
                                  "openai_10k_mentions": 0,
                                  "sbc_adj_fcf_usd_m": 250}},
            ],
            scenario_A_base_projections={
                # Canonical schema
                "revenue": 4.10e9,       # FY26 guide $4.06-4.10B mid
                "gross_margin": 0.80,    # FY25 ~80% gross margin
                "fcf": 1.10e9,           # FY26 P50 (vs FY25 $914.7M, projecting modest growth)
                # Extended
                "fy26_revenue_usd_b":  {"p10": 4.06, "p50": 4.10, "p90": 4.18},
                "ai_native_cohort_q4_2026_ppts": {"p10": 4, "p50": 6, "p90": 8},
                "fy26_nrr_pct":        {"p10": 113, "p50": 115, "p90": 119},
                "_resolution_date": "2027-02-28",
            },
            macro_regime_style_output="MEDIUM",
        ),
    ]


def main() -> int:
    inputs = watchlist_inputs()
    print(f"Persisting {len(inputs)} WATCH-disposition tickers to watchlist...")
    print()

    inserted = 0
    errors = 0
    with psycopg.connect(DSN) as conn:
        for inp in inputs:
            try:
                outcome = add_to_watchlist(inp, conn=conn)
                # add_to_watchlist auto-commits via INSERT ... RETURNING
                conn.commit()
                # The default disposition is 'HELD'; we want 'WATCH'
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE watchlist SET disposition = 'WATCH' WHERE ticker = %s",
                        (inp.ticker,),
                    )
                conn.commit()
                if outcome.inserted:
                    inserted += 1
                    print(
                        f"  ✓ {inp.ticker:6s}  mode={outcome.mode:8s}  "
                        f"thresh={outcome.conviction_threshold:.2f}  "
                        f"sens={outcome.regime_sensitivity:6s}  "
                        f"hmac=...{outcome.thesis_pillars_original_hmac[-12:]}"
                    )
                else:
                    errors += 1
                    print(f"  ✗ {inp.ticker}: not inserted ({outcome.error})")
            except Exception as exc:  # noqa: BLE001
                errors += 1
                conn.rollback()
                print(f"  ✗ {inp.ticker}: {type(exc).__name__}: {exc}")

    print()
    print(f"Inserted: {inserted}/{len(inputs)} | Errors: {errors}")

    # Verify final state
    with psycopg.connect(DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ticker, disposition, mode FROM watchlist "
                "WHERE disposition IN ('HELD','WATCH','TRIGGERED') "
                "ORDER BY ticker"
            )
            rows = cur.fetchall()
    print(f"\n/daily-monitor will sweep {len(rows)} tickers tomorrow:")
    for ticker, disposition, mode in rows:
        print(f"  {ticker:6s}  {disposition:10s}  mode={mode}")

    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
