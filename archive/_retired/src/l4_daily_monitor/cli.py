"""Command-line entry points for L4 daily monitor.

Usage::

    python -m l4_daily_monitor.cli refresh --date 2026-04-30
    python -m l4_daily_monitor.cli refresh --date 2026-04-30 --ticker NVDA
    python -m l4_daily_monitor.cli refresh --date 2026-04-30 --dry-run
    python -m l4_daily_monitor.cli drift-check --period 2026-Q4

Exit codes:
    0 - success
    1 - DB error / IO error
    2 - usage error
    3 - LLM unavailable / classifier failure

Per spec Section 4.5 the daily monitor sweeps the full watchlist by
default. The single-ticker mode is for ad-hoc investigation. Drift
check is the Phase 4 Q8 quarterly run.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import os
import sys
from typing import Optional, Sequence

from .drift_detector import GoldStandardEvent, run_quarterly_drift_check
from .materiality_classifier import LLMUnavailableError
from .refresh_emitter import DailyRefreshOutcome, run_daily_refresh

_LOG = logging.getLogger("l4_daily_monitor.cli")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="l4_daily_monitor.cli",
        description=(
            "L4 / P8 daily monitor: ingest events, classify materiality, "
            "route to agents, evaluate cut thresholds (Section 4.5 of the v3 spec)."
        ),
    )
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    # refresh
    r = sub.add_parser(
        "refresh",
        help="Run the daily refresh pipeline (Section 4.5 Q1+Q2+Q3).",
    )
    r.add_argument(
        "--date",
        required=True,
        help="ISO date for the refresh (YYYY-MM-DD).",
    )
    r.add_argument(
        "--ticker",
        default=None,
        help="Single ticker. Default: scan full watchlist (DB lookup).",
    )
    r.add_argument(
        "--mode",
        default=None,
        help=(
            "Mode override (B / B_prime / C). When omitted the runtime "
            "looks up mode_classifications for the ticker."
        ),
    )
    r.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip DB writes; print outcome JSON to stdout.",
    )
    r.add_argument(
        "--regime-context-json",
        default=None,
        help="Optional inline JSON for regime_context_at_eval.",
    )

    # drift-check
    d = sub.add_parser(
        "drift-check",
        help="Run the Phase 4 Q8 quarterly materiality classifier drift watch.",
    )
    d.add_argument(
        "--period",
        required=True,
        help="Period label (e.g., '2026-Q4').",
    )
    d.add_argument(
        "--gold-standard-json",
        required=False,
        default=None,
        help=(
            "Path to a JSON file with the rolling 30-event gold standard. "
            "Schema: [{event_id, operator_classification, "
            "system_classification, system_confidence}, ...]. "
            "When omitted, the CLI tries to fetch from materiality_events "
            "(DB-backed; not implemented in v0.1 stub)."
        ),
    )
    d.add_argument(
        "--prior-kappa-below-floor",
        action="store_true",
        help=(
            "Set when last quarter's kappa was also below floor; "
            "enables Phase 4 Q8 M-2 system event fire on 2 consec quarters."
        ),
    )
    d.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip DB writes; print outcome JSON to stdout.",
    )

    return p


def _list_watchlist_tickers() -> list[str]:
    """Look up active watchlist names from DB.

    Reads from `watchlist` (the canonical v3 table per migration 007 +
    migration 024). A row is considered "active for monitoring" when its
    disposition is HELD, WATCH, or TRIGGERED. Operators pass --ticker
    explicitly when DATABASE_URL isn't set.
    """
    if not os.environ.get("DATABASE_URL"):
        raise RuntimeError(
            "DATABASE_URL not set; pass --ticker explicitly or set the env var."
        )
    try:
        import psycopg2  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("psycopg2 not installed.") from exc
    with psycopg2.connect(os.environ["DATABASE_URL"]) as conn:  # pragma: no cover
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT ticker FROM watchlist "
                "WHERE disposition IN ('HELD', 'WATCH', 'TRIGGERED') "
                "ORDER BY ticker"
            )
            return [r[0] for r in cur.fetchall()]


def _lookup_mode(ticker: str) -> str:
    """Look up the most-recent mode classification for a ticker.

    Stub-friendly: defaults to 'B_prime' when no DB and no override.
    """
    if not os.environ.get("DATABASE_URL"):
        _LOG.warning("DATABASE_URL not set; defaulting mode to B_prime for %s", ticker)
        return "B_prime"
    try:
        import psycopg2  # type: ignore[import-not-found]
    except ImportError:
        return "B_prime"
    with psycopg2.connect(os.environ["DATABASE_URL"]) as conn:  # pragma: no cover
        with conn.cursor() as cur:
            cur.execute(
                "SELECT final_mode FROM mode_classifications "
                "WHERE ticker = %s ORDER BY classified_at DESC LIMIT 1",
                (ticker,),
            )
            row = cur.fetchone()
            return row[0] if row else "B_prime"


def cmd_refresh(args: argparse.Namespace) -> int:
    try:
        date = _dt.date.fromisoformat(args.date)
    except ValueError:
        print(f"error: --date must be YYYY-MM-DD; got {args.date!r}", file=sys.stderr)
        return 2

    regime_context: dict = {}
    if args.regime_context_json:
        try:
            regime_context = json.loads(args.regime_context_json)
        except json.JSONDecodeError as exc:
            print(f"error: --regime-context-json invalid: {exc}", file=sys.stderr)
            return 2

    if args.ticker:
        tickers = [args.ticker]
    else:
        try:
            tickers = _list_watchlist_tickers()
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    rc = 0
    for tkr in tickers:
        mode = args.mode or _lookup_mode(tkr)
        try:
            outcome = run_daily_refresh(
                ticker=tkr,
                date=date,
                mode=mode,
                regime_context=regime_context,
                dry_run=args.dry_run,
            )
        except LLMUnavailableError as exc:
            print(f"error: LLM unavailable for {tkr}: {exc}", file=sys.stderr)
            rc = max(rc, 3)
            continue
        except Exception as exc:  # pragma: no cover - defensive
            print(f"error: refresh failed for {tkr}: {exc}", file=sys.stderr)
            rc = max(rc, 1)
            continue
        _print_outcome(outcome)
    return rc


def cmd_drift_check(args: argparse.Namespace) -> int:
    if not args.gold_standard_json:
        print(
            "error: --gold-standard-json is required in v0.1 (DB-backed "
            "fetch is a stub). Provide a JSON file with the rolling "
            "30-event operator-rated gold standard.",
            file=sys.stderr,
        )
        return 2
    try:
        with open(args.gold_standard_json, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except OSError as exc:
        print(f"error: cannot read gold-standard file: {exc}", file=sys.stderr)
        return 1

    gold: list[GoldStandardEvent] = []
    import uuid as _uuid
    for entry in payload:
        gold.append(
            GoldStandardEvent(
                event_id=_uuid.UUID(str(entry["event_id"])),
                operator_classification=int(entry["operator_classification"]),
                system_classification=int(entry["system_classification"]),
                system_confidence=float(entry["system_confidence"]),
            )
        )

    try:
        result = run_quarterly_drift_check(
            period=args.period,
            gold_standard=gold,
            prior_kappa_below_floor=args.prior_kappa_below_floor,
            dry_run=args.dry_run,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover - defensive
        print(f"error: drift check failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(
        {
            "drift_check_id": str(result.drift_check_id),
            "period": result.period,
            "sample_size": result.sample_size,
            "kappa": result.kappa,
            "confidence_p50": result.confidence_p50,
            "confidence_p90": result.confidence_p90,
            "delta_from_prior_quarter": result.delta_from_prior_quarter,
            "flags": result.flags,
            "fired_m2_system_event": result.fired_m2_system_event,
            "triggered_alert_id": (
                str(result.triggered_alert_id) if result.triggered_alert_id else None
            ),
        },
        indent=2, default=str,
    ))
    return 0


def _print_outcome(outcome: DailyRefreshOutcome) -> None:
    print(json.dumps(
        {
            "log_id": str(outcome.log_id),
            "ticker": outcome.ticker,
            "date": outcome.date.isoformat(),
            "mode": outcome.mode,
            "materiality": outcome.materiality_rollup,
            "materiality_label": outcome.materiality_label,
            "events_count": len(outcome.events),
            "verdict_summary": [
                {
                    "type": ev.type,
                    "label": v.label,
                    "confidence": v.confidence,
                    "kill_id": v.cited_kill_criterion_id,
                    "tier_escalated_to_opus": v.tier_escalated_to_opus,
                    "flags": list(v.flags),
                }
                for ev, v in zip(outcome.events, outcome.verdicts)
            ],
            "routings": [
                {
                    "action": r.action,
                    "agents": r.agents,
                    "operator_alert": r.operator_alert,
                    "used_fallback_table": r.used_fallback_table,
                    "agent_selection_model": r.agent_selection_model,
                }
                for r in outcome.routings
            ],
            "cut_decision": outcome.cut_decision.to_jsonb(),
            "recommended_action": outcome.recommended_action,
            "llm_call_metadata": outcome.llm_call_metadata,
            "triggered_alerts": [str(a) for a in outcome.triggered_alerts],
        },
        indent=2, default=str,
    ))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    if args.command == "refresh":
        return cmd_refresh(args)
    if args.command == "drift-check":
        return cmd_drift_check(args)
    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
