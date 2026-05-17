"""Phase detection for the master orchestrator.

Per v3 spec Section 5.4 + Section 7 (launch gates) + Section 8.1 (v0.5+
activation triggers), the orchestrator decides which workflow to surface
based on observable database state — never an operator-set config flag.

Phases:
  v0.1-launch-readiness  — pre-launch; not all Section 7 launch gates green
  v0.1-active            — launched, < 50 resolved predictions, daily/event
                           cadences active (Section 8.1 default v0.1)
  v0.5-active            — ≥50 resolved predictions OR 18-24 months elapsed
                           since v0.1 launch → calibration haircut +
                           believability-weighting active (Section 6.4 / 8.1)
  v1.0-active            — post-real-money execution (Checkpoint 3
                           advancement; LearningLoop activation gate passed)

Inference rules (no operator config):
  - launch_readiness_log row with all_gates_green=true and signed_off=true
    → at least v0.1-active.
  - parameters table has any active row in namespace 'real_money_execution'
    with status='LIVE' → v1.0-active.
  - count(recommendation_outcomes WHERE t_plus_90d_return IS NOT NULL) ≥ 50
    OR (now() - launch_date) ≥ 540d → v0.5-active.
  - else v0.1-launch-readiness.

The detector is defensive: if a referenced table does not exist (e.g.,
launch_readiness_log absent in early v0.1 builds), the corresponding
predicate returns False rather than raising, and the phase falls back
to v0.1-launch-readiness with a `reason` annotation.
"""

from __future__ import annotations

import datetime as _dt
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


_LOG = logging.getLogger(__name__)

# Section 8.1 activation triggers.
_V05_RESOLVED_THRESHOLD = 50  # ≥50 resolved predictions
_V05_CALENDAR_DAYS = 540  # 18 months ≈ lower bound of "18-24 months"


class Phase(str, Enum):
    """Operational phase. Values are stable identifiers used in CLI output."""

    V01_LAUNCH_READINESS = "v0.1-launch-readiness"
    V01_ACTIVE = "v0.1-active"
    V05_ACTIVE = "v0.5-active"
    V10_ACTIVE = "v1.0-active"


@dataclass(frozen=True)
class PhaseSnapshot:
    """Inputs that drove the phase decision; surfaced for operator transparency."""

    phase: Phase
    reason: str
    launch_signed_off: bool
    launch_date: Optional[_dt.date]
    resolved_predictions: int
    real_money_active: bool
    days_since_launch: Optional[int]


def detect_phase(
    conn: Any,
    *,
    now: Optional[_dt.datetime] = None,
) -> PhaseSnapshot:
    """Detect the orchestrator's current operating phase.

    Args:
        conn: PEP-249 Postgres connection (psycopg or psycopg2).
        now: Clock override for tests.

    Returns:
        PhaseSnapshot with the resolved phase + the inputs that drove it.
    """
    now = now or _dt.datetime.now(_dt.timezone.utc)
    launch_signed_off, launch_date = _query_launch_signoff(conn)
    resolved = _query_resolved_predictions(conn)
    real_money = _query_real_money_active(conn)

    days_since_launch: Optional[int] = None
    if launch_date is not None:
        delta = now.date() - launch_date
        days_since_launch = max(delta.days, 0)

    if not launch_signed_off:
        return PhaseSnapshot(
            phase=Phase.V01_LAUNCH_READINESS,
            reason="launch gates not all green / launch_readiness_log unsigned",
            launch_signed_off=False,
            launch_date=launch_date,
            resolved_predictions=resolved,
            real_money_active=real_money,
            days_since_launch=days_since_launch,
        )

    if real_money:
        return PhaseSnapshot(
            phase=Phase.V10_ACTIVE,
            reason="real-money execution path active (Checkpoint 3 advancement)",
            launch_signed_off=True,
            launch_date=launch_date,
            resolved_predictions=resolved,
            real_money_active=True,
            days_since_launch=days_since_launch,
        )

    elapsed_trigger = (
        days_since_launch is not None and days_since_launch >= _V05_CALENDAR_DAYS
    )
    if resolved >= _V05_RESOLVED_THRESHOLD or elapsed_trigger:
        reason_bits = []
        if resolved >= _V05_RESOLVED_THRESHOLD:
            reason_bits.append(f"resolved_predictions={resolved} ≥ 50")
        if elapsed_trigger:
            reason_bits.append(f"days_since_launch={days_since_launch} ≥ 540")
        return PhaseSnapshot(
            phase=Phase.V05_ACTIVE,
            reason="; ".join(reason_bits) or "v0.5 activation trigger met",
            launch_signed_off=True,
            launch_date=launch_date,
            resolved_predictions=resolved,
            real_money_active=False,
            days_since_launch=days_since_launch,
        )

    return PhaseSnapshot(
        phase=Phase.V01_ACTIVE,
        reason=(
            f"launched; resolved_predictions={resolved} < 50; "
            f"days_since_launch={days_since_launch} < 540"
        ),
        launch_signed_off=True,
        launch_date=launch_date,
        resolved_predictions=resolved,
        real_money_active=False,
        days_since_launch=days_since_launch,
    )


# --------------------------------------------------------------------------- #
# Query helpers — defensive against missing tables                            #
# --------------------------------------------------------------------------- #


def _query_launch_signoff(conn: Any) -> tuple[bool, Optional[_dt.date]]:
    """Returns (signed_off, launch_date). Defensive: no table → (False, None).

    Schema: launch_readiness_log is row-per-gate (gate_name, status, signed_at).
    "Signed off" = every required gate has status IN ('PASS', 'DEFERRED').
    Launch date = MAX(signed_at) across the PASS rows.
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE status NOT IN ('PASS', 'DEFERRED')) AS not_green,
                    COUNT(*) AS total,
                    MAX(signed_at) FILTER (WHERE status = 'PASS') AS launch_date
                FROM launch_readiness_log
                """
            )
            row = cur.fetchone()
    except Exception as exc:  # noqa: BLE001 — defensive, but logged
        _LOG.warning(
            "phase_detector._query_launch_signoff failed: %s: %s",
            type(exc).__name__, exc,
        )
        return (False, None)

    if not row or row[1] == 0:
        return (False, None)
    not_green, total, launch_ts = row
    all_green = (not_green == 0) and (total > 0)
    launch_date = launch_ts.date() if launch_ts else None
    return (all_green, launch_date)


def _query_resolved_predictions(conn: Any) -> int:
    """Count recommendation_outcomes rows where T+90d window has closed.

    Section 8.1: Brier-haircut + believability weighting activate at ~50
    resolved predictions. T+90d closure is the proxy for 'resolved' at
    v0.1 (matches the calibration_capture migration choice).
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM recommendation_outcomes
                WHERE t_plus_90d_return IS NOT NULL
                """
            )
            row = cur.fetchone()
    except Exception as exc:  # noqa: BLE001 — defensive, but logged
        _LOG.warning(
            "phase_detector._query_resolved_predictions failed: %s: %s",
            type(exc).__name__, exc,
        )
        return 0
    return int(row[0]) if row else 0


def _query_real_money_active(conn: Any) -> bool:
    """Detect v1.0 by parameters_active row in 'real_money_execution' namespace.

    Per v3 spec §8.1, v1.0-active activates once an operator-approved
    `real_money_execution` parameter row carries `status = 'LIVE'` (the
    LearningLoop activation gate; Checkpoint 3 advancement). Match the
    JSONB ``status`` field exactly rather than substring-matching the
    serialized value — substring matching would false-positive on
    namespaces that happen to contain the literal "LIVE" inside an
    unrelated string (e.g., "delivery_alive", "livelihood").

    The migration 004 view uses the column name ``value`` (the source
    `parameters` table column); ``parameter_value`` was the prior name
    in this query and would have raised "no such column" on real
    Postgres — masked by the broad ``except Exception`` fallthrough.
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM parameters_active
                WHERE parameter_namespace = 'real_money_execution'
                  AND value->>'status' = 'LIVE'
                LIMIT 1
                """
            )
            row = cur.fetchone()
    except Exception as exc:  # noqa: BLE001 — defensive, but logged
        _LOG.warning(
            "phase_detector._query_real_money_active failed: %s: %s",
            type(exc).__name__, exc,
        )
        return False
    return row is not None
