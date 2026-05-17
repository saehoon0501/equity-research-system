"""CLI for P7 recommendation emitter.

    python -m src.p7_recommendation_emitter.cli emit \\
        --ticker NVDA --mode B_prime --quality HIGH \\
        --debate-add-count 4 --kills-fired 0 \\
        --counterfactual SURVIVOR,SURVIVOR,SURVIVOR \\
        --anchor-drift 0 \\
        --primary BUY --pacing "DCA over 21 days" \\
        --triggered-by new_candidate

Per v3 spec Section 2.1 (P7 critical-path) + Section 4.6 Q1.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from typing import Any

from src.p7_recommendation_emitter.emitter import (
    EmitInputs,
    emit_recommendation,
)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="p7_recommendation_emitter")
    sub = parser.add_subparsers(dest="cmd", required=True)
    em = sub.add_parser("emit", help="emit one execution_recommendation row")
    em.add_argument("--ticker", required=True)
    em.add_argument("--mode", required=True, choices=("B", "B_prime", "C"))
    em.add_argument("--quality", required=True, choices=("HIGH", "STANDARD"))
    em.add_argument(
        "--mode-certainty",
        default="rule_clean",
        choices=("rule_clean", "llm_tiebreaker"),
    )
    em.add_argument("--debate-add-count", type=int, required=True)
    em.add_argument(
        "--debate-summary",
        default=None,
        help="Human-readable debate consensus summary",
    )
    em.add_argument("--kills-fired", type=int, required=True)
    em.add_argument(
        "--counterfactual",
        required=True,
        help="comma-separated SURVIVOR/NON_SURVIVOR top-3 tags",
    )
    em.add_argument("--anchor-drift", type=int, required=True)
    em.add_argument(
        "--primary",
        required=True,
        choices=("BUY", "HOLD", "TRIM", "SELL"),
        help="primary recommendation from P6",
    )
    em.add_argument("--pacing", required=True, help="suggested pacing string")
    em.add_argument(
        "--triggered-by",
        required=True,
        choices=(
            "new_candidate",
            "mode_cadence_floor",
            "m2_event",
            "m3_event",
        ),
    )
    em.add_argument("--available-cash-pct", type=float, default=None)
    em.add_argument(
        "--portfolio-underperformance-pp", type=float, default=None
    )
    em.add_argument("--s0-vol-z", type=float, default=None)
    em.add_argument("--current-price", type=float, default=None)
    em.add_argument("--dry-run", action="store_true")
    em.add_argument(
        "--prior-conviction-bucket",
        default=None,
        choices=("HIGH", "MEDIUM", "LOW"),
    )
    em.add_argument("--parameters-version", default=None)
    return parser.parse_args(argv)


def _connect() -> Any:
    """Lazy psycopg connection."""
    import psycopg  # type: ignore

    dsn = os.environ.get(
        "EQUITY_RESEARCH_DSN",
        "postgresql://postgres@127.0.0.1:5432/equity_research",
    )
    return psycopg.connect(dsn)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    counterfactual = [
        s.strip().upper() for s in args.counterfactual.split(",") if s.strip()
    ]
    inp = EmitInputs(
        ticker=args.ticker,
        mode=args.mode,
        company_quality_flag=args.quality,
        mode_certainty=args.mode_certainty,
        debate_add_count=args.debate_add_count,
        debate_consensus_summary=(
            args.debate_summary or f"{args.debate_add_count}/5 ADD"
        ),
        kills_fired=args.kills_fired,
        counterfactual_top_3=counterfactual,
        anchor_drift_channels_triggered=args.anchor_drift,
        primary_recommendation=args.primary,
        suggested_pacing=args.pacing,
        triggered_by=args.triggered_by,
        available_cash_pct=args.available_cash_pct,
        portfolio_underperformance_pp_vs_bench=args.portfolio_underperformance_pp,
        s0_vol_z=args.s0_vol_z,
        current_price=args.current_price,
        prior_conviction_bucket=args.prior_conviction_bucket,
        parameters_version=(
            uuid.UUID(args.parameters_version) if args.parameters_version else None
        ),
    )
    conn = None if args.dry_run else _connect()
    try:
        out = emit_recommendation(inp, conn=conn)
    finally:
        if conn is not None:
            conn.close()

    print(
        json.dumps(
            {
                "recommendation_id": str(out.recommendation_id),
                "ticker": out.ticker,
                "recommendation": out.recommendation,
                "conviction": out.conviction,
                "audit_signature": out.audit_signature,
                "audit_chain_ids": [str(a) for a in out.audit_chain_ids],
                "sizing_suggestion": out.sizing_payload,
                "conviction_breakdown": out.conviction_breakdown,
                "trigger_metadata": out.trigger_metadata,
                "execution_context": out.execution_context,
                "escalate_m2": out.escalate_m2,
            },
            ensure_ascii=False,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
