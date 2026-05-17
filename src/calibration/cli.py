"""CLI entrypoint for `/calibration-status`.

Usage:
    python -m src.calibration.cli status

Prints phase + per-feature live/shadow + Brier per cell + per-style
believability + system-vs-operator override comparison.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from src.calibration.believability import score_per_style_brier
from src.calibration.brier import BrierScope, score_brier
from src.orchestrator.phase_detector import detect_phase
from src.orchestrator.v05_activation import V05Feature, get_activation_status


def _open_connection() -> Any:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        user = os.environ.get("POSTGRES_USER", "postgres")
        password = os.environ.get("POSTGRES_PASSWORD", "")
        host = os.environ.get("POSTGRES_HOST", "127.0.0.1")
        port = os.environ.get("POSTGRES_PORT", "5432")
        db = os.environ.get("POSTGRES_DB", "equity_research")
        cred = f"{user}:{password}" if password else user
        dsn = f"postgresql://{cred}@{host}:{port}/{db}"
    try:
        import psycopg  # type: ignore[import-not-found]
        return psycopg.connect(dsn)
    except ImportError:
        pass
    try:
        import psycopg2  # type: ignore[import-not-found]
        return psycopg2.connect(dsn)
    except ImportError as e:
        print("ERROR: neither psycopg nor psycopg2 installed.", file=sys.stderr)
        raise SystemExit(5) from e


def _phase_block(conn) -> None:
    snapshot = detect_phase(conn)
    activation = get_activation_status(conn)
    print(
        f"PHASE: {snapshot.phase.value}   "
        f"(resolved={snapshot.resolved_predictions}; "
        f"days_since_launch={snapshot.days_since_launch})"
    )
    print("FEATURES (live=●  shadow=○):")
    for feat in V05Feature:
        marker = "●" if activation.is_live(feat) else "○"
        print(f"  {marker} {feat.value}")
    print()


def _resolved_counts_block(conn) -> None:
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE t_plus_30d_return IS NOT NULL) AS r30,
                COUNT(*) FILTER (WHERE t_plus_90d_return IS NOT NULL) AS r90,
                COUNT(*) FILTER (WHERE t_plus_1y_return  IS NOT NULL) AS r1y
            FROM recommendation_outcomes
            """
        )
        r30, r90, r1y = cur.fetchone()
    finally:
        cur.close()
    print("RESOLVED OUTCOMES:")
    print(f"  T+30d : {r30}")
    print(f"  T+90d : {r90}     (v0.5 trigger ≥ 50)")
    print(f"  T+1y  : {r1y}")
    print()


def _brier_block(conn) -> None:
    print("BRIER (90d, global):")
    cells = score_brier(conn, scope=BrierScope.GLOBAL, horizon="90d")
    if not cells:
        print("  (no resolved outcomes yet — run /resolve-outcomes)")
    else:
        c = cells[0]
        print(f"  N      : {c.n}")
        print(f"  Brier  : {c.brier:.3f}     (random baseline 0.250)")
        print(f"  mean_p : {c.mean_predicted:.3f}")
        print(f"  mean_y : {c.mean_realized:.3f}")
    print()

    print("BRIER (90d, by mode):")
    for c in score_brier(conn, scope=BrierScope.BY_MODE, horizon="90d"):
        mode = c.scope_key[0]
        print(f"  {mode:<8}: N={c.n}  Brier={c.brier:.3f}")
    print()


def _believability_block(conn) -> None:
    print("BELIEVABILITY (per-style, 90d, BUY-only):")
    styles = score_per_style_brier(conn, horizon="90d", rec_type_filter="BUY")
    if not styles:
        print("  (no debate-resolved outcomes yet)")
    else:
        for sb in styles:
            print(
                f"  {sb.style:<16}: N={sb.n}  "
                f"Brier={sb.brier:.3f}  weight={sb.weight_inverse_brier:.3f}"
            )
    print()


def _operator_block(conn) -> None:
    print("OPERATOR vs SYSTEM (per cell, 90d):")
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT mode, materiality, recommendation,
                   n_system, n_overrides,
                   system_brier, operator_brier, operator_better
            FROM system_vs_operator_brier
            ORDER BY n_overrides DESC NULLS LAST, n_system DESC
            LIMIT 20
            """
        )
        rows = cur.fetchall()
    except Exception as exc:  # noqa: BLE001
        # Migration 025 may not be applied yet at very early v0.1.
        print(f"  view not available: {type(exc).__name__}")
        cur.close()
        return
    finally:
        cur.close()
    if not rows:
        print("  (no resolved overrides yet)")
        return
    for r in rows:
        mode, materiality, rec, n_sys, n_ovr, sys_b, op_b, op_better = r
        print(
            f"  {mode}/{materiality}/{rec}: "
            f"N_sys={n_sys}  N_ovr={n_ovr or 0}  "
            f"sys_brier={sys_b:.3f}  "
            f"op_brier={op_b if op_b is not None else float('nan'):.3f}  "
            f"operator_better={op_better}"
        )


def _cmd_status(_: argparse.Namespace) -> int:
    conn = _open_connection()
    try:
        _phase_block(conn)
        _resolved_counts_block(conn)
        _brier_block(conn)
        _believability_block(conn)
        _operator_block(conn)
    finally:
        conn.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="calibration")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_status = sub.add_parser("status", help="Show v0.5 calibration status")
    p_status.set_defaults(func=_cmd_status)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
