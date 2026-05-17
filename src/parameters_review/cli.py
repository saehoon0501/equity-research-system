"""CLI for parameter-recalibration review (STUB at v0.1).

Usage::

    python -m src.parameters_review.cli summary
    python -m src.parameters_review.cli summary --namespace mode_classifier
    python -m src.parameters_review.cli suggest [--since-days 90]
    python -m src.parameters_review.cli propose

Per v3 spec Section 1.5 + Section 5.4. See module docstring for v0.1-vs-v0.5+
scope split.

Exit codes:
    0 - success
    1 - DB / IO error
    2 - usage error
    5 - environment / driver missing
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Sequence


def _open_connection() -> Any:
    """Open a Postgres connection from env vars (psycopg v3 then psycopg2).

    Mirrors `src/audit_trail/cli.py::_open_connection` so the same env-var
    contract applies across CLIs (DATABASE_URL or POSTGRES_* fallbacks).
    """
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
        print(
            "ERROR: neither psycopg (v3) nor psycopg2 is installed. "
            "Install one to run the parameters_review CLI.",
            file=sys.stderr,
        )
        raise SystemExit(5) from e


def _cmd_summary(args: argparse.Namespace) -> int:
    """Group `parameters` rows by namespace.

    Returns latest + immediately-prior `value` per `parameter_key`. Useful
    for spotting recently-changed parameters operator may want to roll
    back. v0.1 surface — operator runs by hand to scan; v0.5+ wraps the
    same query with proposal-generation logic.
    """
    conn = _open_connection()
    try:
        cur = conn.cursor()
        sql = """
            WITH ranked AS (
                SELECT
                    parameter_key,
                    value,
                    effective_at,
                    description,
                    change_rationale,
                    approved_by,
                    ROW_NUMBER() OVER (
                        PARTITION BY parameter_key
                        ORDER BY effective_at DESC
                    ) AS rn
                FROM parameters
                WHERE (%s IS NULL OR parameter_key LIKE %s)
            )
            SELECT
                parameter_key,
                MAX(value) FILTER (WHERE rn = 1) AS current_value,
                MAX(value) FILTER (WHERE rn = 2) AS prior_value,
                MAX(effective_at) FILTER (WHERE rn = 1) AS effective_at,
                MAX(change_rationale) FILTER (WHERE rn = 1) AS rationale
            FROM ranked
            WHERE rn <= 2
            GROUP BY parameter_key
            ORDER BY parameter_key
        """
        ns_pattern = (
            f"{args.namespace}.%" if args.namespace else None
        )
        cur.execute(sql, (args.namespace, ns_pattern))
        rows = cur.fetchall()
        out = [
            {
                "parameter_key": r[0],
                "current_value": r[1],
                "prior_value": r[2],
                "effective_at": (
                    r[3].isoformat() if r[3] is not None else None
                ),
                "change_rationale": r[4],
            }
            for r in rows
        ]
        print(json.dumps(out, indent=2, default=str))
        return 0
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _cmd_suggest(args: argparse.Namespace) -> int:
    """Surface the parameter keys most frequently overridden.

    v0.1 heuristic only: group `operator_overrides` rows by extracted
    `parameter_key` (when JSONB rationale references one) and rank by
    count over the last `--since-days` window.

    v0.5+ extends this to coordinate proposed changes against rolling
    90-day counterfactual ledger outcomes (per Section 6.3).
    """
    conn = _open_connection()
    try:
        cur = conn.cursor()
        sql = """
            SELECT
                rationale->>'parameter_key' AS parameter_key,
                COUNT(*) AS override_count
            FROM operator_overrides
            WHERE created_at >= NOW() - %s::INTERVAL
              AND rationale ? 'parameter_key'
            GROUP BY parameter_key
            ORDER BY override_count DESC
            LIMIT 20
        """
        cur.execute(sql, (f"{args.since_days} days",))
        rows = cur.fetchall()
        out = [
            {"parameter_key": r[0], "override_count": int(r[1])}
            for r in rows
        ]
        print(json.dumps(out, indent=2, default=str))
        return 0
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _cmd_propose(_args: argparse.Namespace) -> int:
    """Placeholder — full proposal-generation lands at v0.5+.

    Per v3 spec Section 5.4 + operator-reference §1.5. The full
    workflow requires:
      1. 90-day counterfactual ledger outcome stratification.
      2. Parameter-vs-outcome attribution (which key explained the miss?).
      3. Proposed-change generation + operator approve/modify/reject UI.
      4. Append-only write of the new `parameters` row with rationale.

    None of (1)-(4) is in v0.1 scope. The stub explicitly refuses to
    generate proposals so an operator does not mistake the placeholder
    for a real recommendation.
    """
    print(
        json.dumps(
            {
                "status": "stub",
                "message": (
                    "Full /parameters-review proposal generation is "
                    "v0.5+ scope. At v0.1 use `summary` + `suggest` to "
                    "scan recent changes + override patterns; commit "
                    "approved parameter changes manually via "
                    "mcp__postgres__execute with `change_rationale` "
                    "populated."
                ),
                "spec_ref": (
                    "docs/superpowers/specs/"
                    "2026-04-29-empirical-foundation-design-v3.md "
                    "Section 5.4 + Section 6.3"
                ),
            },
            indent=2,
        )
    )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m src.parameters_review.cli",
        description=(
            "Quarterly parameter recalibration review (v0.1 STUB). "
            "Per v3 Section 1.5 + 5.4 + 6.3."
        ),
    )
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser(
        "summary",
        help="List recent parameter changes (current + prior value).",
    )
    s.add_argument(
        "--namespace",
        default=None,
        help=(
            "Filter to one parameter_key prefix "
            "(e.g. 'mode_classifier', 'bocpd', 'peak_pain')."
        ),
    )
    s.set_defaults(func=_cmd_summary)

    g = sub.add_parser(
        "suggest",
        help="Rank parameter_keys by override frequency.",
    )
    g.add_argument("--since-days", type=int, default=90)
    g.set_defaults(func=_cmd_suggest)

    pr = sub.add_parser(
        "propose",
        help="(STUB) Full proposal generation deferred to v0.5+.",
    )
    pr.set_defaults(func=_cmd_propose)

    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
