"""CLI for the counterfactual veto pipeline.

Entry point::

    python -m src.counterfactual_veto.cli evaluate --ticker NVDA --drawdown-pct 25

This is a thin wrapper that:
    - Loads the active catalog from peak_pain_archetypes (or a JSON snapshot
      when --catalog-json is supplied for offline use).
    - Loads the candidate's structural-features descriptor (from --features-json
      or via the peak_pain_catalog 3-LLM consensus pipeline).
    - Runs the orchestrator and prints the VetoDecision summary.

For wiring into /daily-monitor or /entry-check skill flows, prefer importing
``run_pipeline`` directly — the CLI is intended for ad-hoc operator use and
acceptance-test reproductions of Section 7.3a walkthrough scenarios.

Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
           Section 4.5 Q6 + Section 7.3a Walkthrough #1.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any

from .feature_extractor import CandidateFeatures, candidate_from_dict
from .layer1_cooling_off import evaluate_cooling_off
from .layer2_multi_source import KillCriterionFire
from .orchestrator import PipelineInputs, run_pipeline
from .retrieval import CatalogCase


def _load_catalog_from_json(path: str) -> list[CatalogCase]:
    """Load a catalog snapshot from JSON (for offline / acceptance tests)."""
    with open(path) as f:
        rows = json.load(f)
    return [
        CatalogCase(
            case_id=r["case_id"],
            ticker=r["ticker"],
            sector=r["sector"],
            outcome=r["outcome"],
            universal_core_features=r.get("universal_core_features") or {},
            sector_extensions=r.get("sector_extensions") or {},
            validation_status=r.get("validation_status", "validated"),
            era_category=r.get("era_category", "recent"),
            peak_dd_pct=r.get("peak_dd_pct"),
        )
        for r in rows
    ]


def _load_candidate_from_json(path: str) -> CandidateFeatures:
    with open(path) as f:
        return candidate_from_dict(json.load(f))


def _load_fires_from_json(path: str | None) -> list[KillCriterionFire]:
    if not path:
        return []
    with open(path) as f:
        rows = json.load(f)
    out: list[KillCriterionFire] = []
    for r in rows:
        fired_at = _dt.datetime.fromisoformat(r["fired_at"])
        # Coerce naive ISO strings ("2026-04-29T12:00:00") to aware UTC so
        # downstream cooling-off comparisons (which compare against an
        # aware `now`) do not raise TypeError on aware-vs-naive subtract.
        if fired_at.tzinfo is None:
            fired_at = fired_at.replace(tzinfo=_dt.timezone.utc)
        out.append(
            KillCriterionFire(
                kill_id=r["kill_id"],
                fired_at=fired_at,
                bocpd_correlation_group=r.get("bocpd_correlation_group"),
                verbatim_primary_quote=r.get("verbatim_primary_quote"),
                primary_source_type=r.get("primary_source_type"),
            )
        )
    return out


def _no_op_premortem_lookup(ticker: str, evaluated_at: _dt.datetime, lookback_days: int) -> bool:
    """Default lookup for offline CLI runs — returns False (no premortem)."""
    return False


def _no_op_execute(sql: str, params: tuple[Any, ...]) -> None:
    """Default execute for dry-run CLI invocations — prints the call instead."""
    print(f"[DRY-RUN SQL] {sql.split()[0]} ... ({len(params)} params)")


def _summarize_decision(decision: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "ticker": decision.ticker,
        "retrieval_id": decision.retrieval_id,
        "veto_id": decision.veto_id,
        "cut_status": decision.cut_status,
        "rationale": decision.rationale,
        "m3_alert_fired": decision.m3_alert_fired,
        "cooling_off": {
            "mode": decision.cooling_off.mode,
            "duration_h": decision.cooling_off.duration_h,
            "blocking": decision.cooling_off.blocking,
            "remaining_seconds": decision.cooling_off.remaining_seconds,
        },
    }
    if decision.multi_source is not None:
        out["multi_source"] = {
            "independent_kill_count": decision.multi_source.independent_kill_count,
            "verbatim_primary_source": decision.multi_source.verbatim_primary_source,
            "premortem_within_30d": decision.multi_source.premortem_within_30d,
            "all_satisfied": decision.multi_source.all_satisfied,
            "cut_blocked_reason": decision.multi_source.cut_blocked_reason,
        }
    if decision.veto is not None:
        out["veto"] = {
            "veto_invoked": decision.veto.veto_invoked,
            "status": decision.veto.status,
            "archetype_distribution": decision.veto.archetype_distribution,
            "top_3": [
                {
                    "case_id": m.case.case_id,
                    "outcome": m.case.outcome,
                    "similarity": round(float(m.similarity), 4),
                }
                for m in decision.veto.top_3_matches
            ],
        }
    return out


def _cmd_evaluate(args: argparse.Namespace) -> int:
    catalog = _load_catalog_from_json(args.catalog_json) if args.catalog_json else []
    candidate = _load_candidate_from_json(args.features_json) if args.features_json else None
    if candidate is None:
        print(
            "ERROR: --features-json is required for offline CLI runs. "
            "Live extraction (3-LLM consensus over the candidate's filings) "
            "is wired through the daemon, not the CLI.",
            file=sys.stderr,
        )
        return 2

    fires = _load_fires_from_json(args.fires_json)
    if args.trigger_at:
        trigger_at = _dt.datetime.fromisoformat(args.trigger_at)
        # Coerce naive ISO strings to aware UTC — required by cooling-off
        # layer (compares against aware `now`).
        if trigger_at.tzinfo is None:
            trigger_at = trigger_at.replace(tzinfo=_dt.timezone.utc)
    else:
        trigger_at = _dt.datetime.now(_dt.timezone.utc)

    inputs = PipelineInputs(
        ticker=args.ticker,
        mode=args.mode,
        candidate=candidate,
        catalog=catalog,
        fires=fires,
        trigger_event_at=trigger_at,
        drawdown_vs_benchmark_pp=float(args.drawdown_pct),
        catalog_version_hash=args.catalog_version_hash,
    )
    decision = run_pipeline(
        inputs,
        premortem_lookup=_no_op_premortem_lookup,
        execute=_no_op_execute,
    )
    print(json.dumps(_summarize_decision(decision), indent=2, default=str))
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.counterfactual_veto.cli",
        description="Counterfactual VETO pipeline (Section 4.5 Q6 d').",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_eval = sub.add_parser(
        "evaluate",
        help="Run the 3-layer pipeline against a candidate at peak-pain trigger.",
    )
    p_eval.add_argument("--ticker", required=True, help="Candidate ticker, e.g. NVDA.")
    p_eval.add_argument(
        "--mode",
        default="B_prime",
        choices=["B", "B_prime", "C"],
        help="Mode bin (default B_prime).",
    )
    p_eval.add_argument(
        "--drawdown-pct",
        required=True,
        type=float,
        help="Drawdown vs benchmark in pp (e.g., 25 means -25pp).",
    )
    p_eval.add_argument(
        "--features-json",
        help="Path to candidate features JSON (CandidateFeatures.to_dict() schema).",
    )
    p_eval.add_argument(
        "--catalog-json",
        help="Path to catalog snapshot JSON (offline runs).",
    )
    p_eval.add_argument(
        "--fires-json",
        help="Path to JSON list of KillCriterionFire dicts.",
    )
    p_eval.add_argument(
        "--trigger-at",
        help="ISO timestamp of the peak-pain trigger event.",
    )
    p_eval.add_argument(
        "--catalog-version-hash",
        default="cli-snapshot",
        help="Catalog snapshot hash to record on the retrieval row.",
    )
    p_eval.set_defaults(func=_cmd_evaluate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
