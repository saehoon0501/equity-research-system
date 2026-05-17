"""Command-line entry for the P4 debate orchestrator.

Usage::

    python -m p4_debate.cli debate \\
        --ticker NVDA \\
        --mode B_prime \\
        --candidate-facts path/to/facts.txt \\
        --scenarios path/to/scenarios.txt \\
        [--lane-refs path/to/refs.txt] \\
        [--s0-regime path/to/regime.txt] \\
        [--sector Biotech] \\
        [--no-parallel] \\
        [--persist]

Exit codes:
    0 - success
    1 - I/O error
    2 - usage error
    3 - LLM unavailable
    4 - DB error (only when --persist)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Sequence

from . import MODE_B, MODE_B_PRIME, MODE_C
from ._llm import LLMUnavailableError
from .orchestrator import P4Inputs, run_debate


_LOG = logging.getLogger("p4_debate.cli")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="p4_debate.cli",
        description=(
            "Run the 5-style debate (Phase A -> B -> C-conditional -> D) "
            "for one ticker. Per v3 spec Section 2.3 + Section 4.8."
        ),
    )
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("debate", help="Run the debate end-to-end.")
    d.add_argument("--ticker", required=True)
    d.add_argument(
        "--mode",
        required=True,
        choices=[MODE_B, MODE_B_PRIME, MODE_C],
        help="B / B_prime / C — drives the weighting matrix.",
    )
    d.add_argument(
        "--candidate-facts",
        required=True,
        help="Path to a text file containing the verbatim candidate-facts block.",
    )
    d.add_argument(
        "--scenarios",
        default=None,
        help="Path to the P2 scenarios text file (optional).",
    )
    d.add_argument(
        "--lane-refs",
        default=None,
        help="Path to L1/L3 lane-reference text file (optional).",
    )
    d.add_argument(
        "--s0-regime",
        default=None,
        help="Path to S0 regime context text file (optional; only macro_regime style consumes).",
    )
    d.add_argument(
        "--sector",
        default=None,
        help="Sector tag for sector overrides (e.g., Biotech, Banks, Insurers).",
    )
    d.add_argument(
        "--no-parallel",
        action="store_true",
        help="Run within-phase style calls sequentially (deterministic; default is parallel).",
    )
    d.add_argument(
        "--persist",
        action="store_true",
        help="Append a row to debate_consensus_history (requires DB env).",
    )
    d.add_argument(
        "--out",
        default=None,
        help="If set, write the full P4DebateResult JSON to this path.",
    )
    return p


def _read_text(path: str | None) -> str:
    if not path:
        return ""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"file not found: {path}")
    return p.read_text(encoding="utf-8")


def _build_db_conn() -> object:
    """Build a psycopg connection from env. Lazy import — only called under --persist."""
    try:
        import psycopg  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "psycopg not installed; install with `pip install psycopg[binary]` "
            "or run without --persist."
        ) from exc
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("PGURI")
    if not dsn:
        # Fall back to discrete env vars matching docker-compose defaults.
        host = os.environ.get("PGHOST", "127.0.0.1")
        port = os.environ.get("PGPORT", "5432")
        user = os.environ.get("PGUSER", "postgres")
        pw = os.environ.get("PGPASSWORD", "")
        db = os.environ.get("PGDATABASE", "equity_research")
        dsn = f"postgresql://{user}:{pw}@{host}:{port}/{db}"
    return psycopg.connect(dsn)


def _result_to_dict(result) -> dict:
    """Coerce a P4DebateResult to a JSON-safe dict."""
    return {
        "debate_id": str(result.debate_id),
        "ticker": result.ticker,
        "debate_date": result.debate_date.isoformat(),
        "phase_a": result.phase_a.to_payload(),
        "phase_b": result.phase_b.to_payload(),
        "phase_c_judge": result.phase_c_judge.to_payload(),
        "phase_c_negotiation": (
            result.phase_c_negotiation.to_payload()
            if result.phase_c_negotiation
            else None
        ),
        "phase_d": result.phase_d.to_payload(),
        "model_id": result.model_id,
        "debate_prompt_version": result.debate_prompt_version,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if args.command != "debate":
        parser.error(f"unknown command: {args.command}")
        return 2

    try:
        candidate_facts = _read_text(args.candidate_facts)
    except FileNotFoundError as exc:
        _LOG.error(str(exc))
        return 1
    if not candidate_facts.strip():
        _LOG.error("candidate-facts file is empty")
        return 2

    try:
        scenarios = _read_text(args.scenarios) if args.scenarios else ""
        lane_refs = _read_text(args.lane_refs) if args.lane_refs else ""
        s0_regime = _read_text(args.s0_regime) if args.s0_regime else None
    except FileNotFoundError as exc:
        _LOG.error(str(exc))
        return 1

    inputs = P4Inputs(
        ticker=args.ticker,
        mode=args.mode,
        candidate_facts=candidate_facts,
        scenarios=scenarios,
        lane_refs=lane_refs,
        s0_regime_context=s0_regime,
        sector=args.sector,
    )

    conn = None
    if args.persist:
        try:
            conn = _build_db_conn()
        except Exception as exc:  # noqa: BLE001
            _LOG.error("DB connection failed: %s", exc)
            return 4

    try:
        result = run_debate(
            inputs,
            parallel=not args.no_parallel,
            persist=args.persist,
            conn=conn,
        )
    except LLMUnavailableError as exc:
        _LOG.error("LLM unavailable: %s", exc)
        return 3
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    payload = _result_to_dict(result)
    if args.out:
        Path(args.out).write_text(
            json.dumps(payload, indent=2, default=str), encoding="utf-8"
        )
        _LOG.info("Wrote full result to %s", args.out)
    else:
        # Brief stdout summary for human eyes.
        print(json.dumps(
            {
                "decision": result.phase_d.decision,
                "conviction": result.phase_d.recommended_conviction,
                "dissenters": [
                    d.style_id
                    for d in result.phase_d.dissent_trace
                    if d.verdict != result.phase_d.decision
                ],
                "phase_c_triggered": result.phase_c_judge.phase_c_needed,
                "unresolved_conflicts": (
                    result.phase_c_negotiation.unresolved_conflicts
                    if result.phase_c_negotiation
                    else []
                ),
                "debate_id": str(result.debate_id),
            },
            indent=2,
            default=str,
        ))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
