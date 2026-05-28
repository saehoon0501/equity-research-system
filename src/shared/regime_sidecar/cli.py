"""S0 regime sidecar CLI entry point.

Per v3 spec §4.1 (refresh cadence: daily) and §7.5 (cold-start procedure).

Usage:

    # Daily run (today). Default.
    python -m src.shared.regime_sidecar.cli

    # Specific date.
    python -m src.shared.regime_sidecar.cli --date 2026-04-29

    # Cold-start backfill: T-12mo of history, write cold_start=True.
    python -m src.shared.regime_sidecar.cli --cold-start

    # Cold-start with custom horizon.
    python -m src.shared.regime_sidecar.cli --cold-start --months 18

    # Dry run: print results JSON to stdout, no DB write.
    python -m src.shared.regime_sidecar.cli --dry-run

Exit codes:
    0 — success
    1 — Postgres / DB write failure
    2 — fatal fetcher error (every dimension failed)

Per §7.5 error handling: a single dimension failure is captured as a
warning on a degraded result; only when every dimension fails do we exit
non-zero.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timezone

from src.shared.regime_sidecar.classifier import (
    run_daily_classification,
    to_serializable,
)
from src.shared.regime_sidecar.persistence import backfill_cold_start, write_classifications


logger = logging.getLogger("regime_sidecar.cli")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="regime_sidecar",
        description="S0 regime sidecar — daily 6-dimension classification (v3 §4.1).",
    )
    p.add_argument(
        "--date",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
        # UTC date — ``date.today()`` reads server local tz; also resolve at
        # parse-time (not module-import time) so a long-running invocation
        # picks the day the CLI is actually invoked.
        default=datetime.now(timezone.utc).date(),
        help="Classification date (YYYY-MM-DD). Default: today (UTC).",
    )
    p.add_argument(
        "--history-days",
        type=int,
        default=365,
        help="History window for BOCPD seeding (default: 365).",
    )
    p.add_argument(
        "--cold-start",
        action="store_true",
        help="Run cold-start backfill (T-N months, default 12) per §7.5.",
    )
    p.add_argument(
        "--months",
        type=int,
        default=12,
        help="Cold-start backfill horizon in months (default: 12).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print results JSON to stdout; do not write to DB.",
    )
    p.add_argument(
        "--parameters-version",
        type=str,
        default=None,
        help="Optional parameters.version_id UUID to attach to written rows.",
    )
    return p.parse_args()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    args = _parse_args()

    if args.cold_start:
        logger.info(
            "cold-start backfill: %d months ending %s",
            args.months,
            args.date.isoformat(),
        )
        try:
            inserted = backfill_cold_start(
                end_date=args.date,
                months=args.months,
                parameters_version=args.parameters_version,
            )
            logger.info("cold-start backfill complete: %d rows inserted", inserted)
            return 0
        except Exception as exc:  # noqa: BLE001
            logger.exception("cold-start backfill failed: %s", exc)
            return 1

    logger.info("daily classification: %s", args.date.isoformat())
    results = run_daily_classification(args.date, history_days=args.history_days)

    # Detect catastrophic case: every dimension is in DEGRADED state.
    degraded = [r for r in results.values() if r.validation_depth == "DEGRADED"]
    if len(degraded) == len(results):
        logger.error("every dimension fetcher failed; refusing to write degraded snapshot")
        return 2

    if args.dry_run:
        json.dump(to_serializable(results), sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
        return 0

    try:
        inserted = write_classifications(
            list(results.values()),
            parameters_version=args.parameters_version,
        )
        logger.info("daily classification persisted: %d rows", inserted)
        return 0
    except Exception as exc:  # noqa: BLE001
        logger.exception("DB write failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
