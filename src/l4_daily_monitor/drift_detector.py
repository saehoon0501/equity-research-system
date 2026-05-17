"""Drift detector — Phase 4 Q8 quarterly materiality classifier drift watch.

Per v3 spec §6.2 (line 776) + Phase 4 Q8 + Section 7.2 launch gate
(line 834): the materiality classifier is calibrated against an
operator-rated **rolling 30-event gold standard** every quarter.

Hard floors:
  - N >= 30 sample size (migration 010 CHECK constraint).
  - Cohen's kappa >= 0.61 against gold standard (launch gate).
  - Confidence-distribution drift (P50/P90 shifts > 0.1) flagged.

Output:
  - One ``materiality_classifier_drift`` row per period (e.g., '2026-Q4').
  - If kappa < 0.61 sustained for 2 consecutive quarters → fires an
    M-2 system event into ``unread_alerts`` (Phase 4 Q8: classifier
    drift is itself a materiality-2 event for the operator).

Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
    Section 6.2 — drift monitoring per subsystem
    Section 7.2 — calibration launch gate (kappa >= 0.61)
    Phase 4 Q8 — materiality production drift detection
    db/migrations/010_v3_drift_detection.sql — schema
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from . import (
    DRIFT_KAPPA_FLOOR,
    MIN_DRIFT_SAMPLE_SIZE,
)

_LOG = logging.getLogger(__name__)


@dataclass
class GoldStandardEvent:
    """One operator-rated event for the rolling gold standard.

    Attributes:
        event_id: FK into materiality_events.event_id.
        operator_classification: Operator's gold-standard label (1/2/3).
        system_classification: What the LLM judge produced (1/2/3).
        system_confidence: The judge's reported confidence at the time.
    """

    event_id: uuid.UUID
    operator_classification: int
    system_classification: int
    system_confidence: float


@dataclass
class DriftCheckResult:
    """Output of one quarterly drift check."""

    drift_check_id: uuid.UUID
    period: str
    sample_size: int
    rolling_gold_standard_event_ids: list[uuid.UUID]
    kappa: float
    confidence_p50: float
    confidence_p90: float
    delta_from_prior_quarter: Optional[dict[str, Any]]
    flags: list[str] = field(default_factory=list)
    fired_m2_system_event: bool = False
    triggered_alert_id: Optional[uuid.UUID] = None


# --------------------------------------------------------------------------- #
# Cohen's kappa                                                               #
# --------------------------------------------------------------------------- #


def cohens_kappa(a: list[int], b: list[int], categories: tuple[int, ...] = (1, 2, 3)) -> float:
    """Compute Cohen's kappa between two integer rating vectors.

    Per Phase 4 Q8 + launch gate: kappa is the agreement metric for the
    materiality classifier vs operator gold-standard.

    Args:
        a, b: Equal-length integer rating lists.
        categories: Universe of categorical labels (1/2/3 for M-1/M-2/M-3).

    Returns:
        kappa ∈ [-1, 1]. Returns 1.0 if perfect agreement and ratings are
        constant (degenerate case where p_e == 1).
    """
    if len(a) != len(b):
        raise ValueError(f"length mismatch: {len(a)} vs {len(b)}")
    n = len(a)
    if n == 0:
        return 0.0
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pe = 0.0
    for c in categories:
        pa = sum(1 for x in a if x == c) / n
        pb = sum(1 for y in b if y == c) / n
        pe += pa * pb
    if pe == 1.0:
        return 1.0 if po == 1.0 else 0.0
    return (po - pe) / (1.0 - pe)


def _percentile(xs: list[float], p: float) -> float:
    """Linear-interpolation percentile (p ∈ [0, 100])."""
    if not xs:
        return 0.0
    s = sorted(xs)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


# --------------------------------------------------------------------------- #
# Persistence                                                                 #
# --------------------------------------------------------------------------- #


class _TransactionalDbWriter:
    """Default Postgres writer that holds ONE connection across all SQL calls.

    Atomicity contract: ``run_quarterly_drift_check`` writes 1 drift row
    + (when 2 consecutive quarters below kappa floor) 1 unread_alerts row.
    A partial commit would leave the alert orphaned vs. the drift row —
    operator sees the M-2 alert with no drift_check_id evidence to drill
    into. This writer commits both rows or neither.
    """

    def __init__(self, dsn: Optional[str] = None) -> None:
        self._dsn = dsn or os.environ.get("DATABASE_URL")
        self._conn = None  # type: Any

    def __enter__(self):
        try:
            import psycopg2  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "psycopg2 not installed; pass a stub db_writer for tests."
            ) from exc
        if not self._dsn:
            raise RuntimeError(
                "DATABASE_URL not set; pass a stub db_writer for tests."
            )
        self._conn = psycopg2.connect(self._dsn)  # pragma: no cover
        self._conn.autocommit = False
        return self

    def __exit__(self, exc_type, exc, tb):  # pragma: no cover
        if self._conn is None:
            return False
        try:
            if exc_type is not None:
                # Roll back the multi-row drift+alert write atomically.
                # If rollback itself fails the transaction may be in an
                # inconsistent state — log so the operator sees the signal
                # rather than masking it.
                try:
                    self._conn.rollback()
                except Exception as rb_exc:  # noqa: BLE001
                    _LOG.error(
                        "drift_detector _TransactionalDbWriter rollback "
                        "FAILED — drift+alert atomicity may be broken. "
                        "original_exc=%s: %s; rollback_exc=%s: %s",
                        exc_type.__name__ if exc_type else "?",
                        exc,
                        type(rb_exc).__name__,
                        rb_exc,
                    )
            else:
                self._conn.commit()
        finally:
            try:
                self._conn.close()
            except Exception as close_exc:  # noqa: BLE001
                _LOG.warning(
                    "drift_detector _TransactionalDbWriter close failed: "
                    "%s: %s",
                    type(close_exc).__name__, close_exc,
                )
        return False

    def __call__(self, sql: str, params: tuple) -> Optional[uuid.UUID]:
        if self._conn is None:
            raise RuntimeError(
                "_TransactionalDbWriter must be entered as a context manager"
            )
        with self._conn.cursor() as cur:  # pragma: no cover
            cur.execute(sql, params)
            row = cur.fetchone() if cur.description else None
            return row[0] if row else None


def _default_db_writer(sql: str, params: tuple) -> Optional[uuid.UUID]:
    """Backward-compatible single-shot writer (deprecated for multi-row)."""
    try:
        import psycopg2  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "psycopg2 not installed; pass a stub db_writer for tests."
        ) from exc
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError(
            "DATABASE_URL not set; pass a stub db_writer for tests."
        )
    with psycopg2.connect(dsn) as conn:  # pragma: no cover
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone() if cur.description else None
            return row[0] if row else None


# --------------------------------------------------------------------------- #
# Public entry                                                                #
# --------------------------------------------------------------------------- #


def run_quarterly_drift_check(
    period: str,
    gold_standard: list[GoldStandardEvent],
    *,
    prior_quarter: Optional[DriftCheckResult] = None,
    prior_kappa_below_floor: bool = False,
    parameters_version: Optional[uuid.UUID] = None,
    db_writer: Any = None,
    dry_run: bool = False,
) -> DriftCheckResult:
    """Run the Phase 4 Q8 quarterly drift watch.

    Args:
        period: Period label, e.g., '2026-Q4'.
        gold_standard: List of >= 30 operator-rated events.
        prior_quarter: Last quarter's result (for delta computation).
            Optional.
        prior_kappa_below_floor: If True AND this quarter's kappa is also
            below floor, we fire the M-2 system event (Phase 4 Q8: 2
            consecutive quarters below floor = persistent drift).
        parameters_version: FK into parameters table.
        db_writer: Optional callable for tests; defaults to psycopg2.
        dry_run: If True, skip DB writes.

    Returns:
        :class:`DriftCheckResult`.

    Raises:
        ValueError: if sample_size < MIN_DRIFT_SAMPLE_SIZE.
    """
    n = len(gold_standard)
    if n < MIN_DRIFT_SAMPLE_SIZE:
        raise ValueError(
            f"sample_size={n} < {MIN_DRIFT_SAMPLE_SIZE} (Phase 4 Q8 hard floor)"
        )

    operator = [g.operator_classification for g in gold_standard]
    system = [g.system_classification for g in gold_standard]
    confidences = [g.system_confidence for g in gold_standard]

    kappa = cohens_kappa(operator, system)
    p50 = _percentile(confidences, 50.0)
    p90 = _percentile(confidences, 90.0)

    flags: list[str] = []
    if kappa < DRIFT_KAPPA_FLOOR:
        flags.append(f"kappa_{kappa:.3f}_below_floor_{DRIFT_KAPPA_FLOOR}")

    delta: Optional[dict[str, Any]] = None
    if prior_quarter is not None:
        prior_event_ids = set(str(eid) for eid in prior_quarter.rolling_gold_standard_event_ids)
        this_event_ids = set(str(g.event_id) for g in gold_standard)
        overlap_pct = (
            (len(prior_event_ids & this_event_ids) / len(prior_event_ids)) * 100.0
            if prior_event_ids else 0.0
        )
        delta = {
            "kappa_delta": kappa - prior_quarter.kappa,
            "p50_delta": p50 - prior_quarter.confidence_p50,
            "p90_delta": p90 - prior_quarter.confidence_p90,
            "gold_event_overlap_pct": overlap_pct,
        }
        # Phase 4 Q8: confidence-distribution shifts > 0.1 flag drift.
        if abs(delta["p50_delta"]) > 0.1:
            flags.append(f"p50_shift_{delta['p50_delta']:+.3f}_>_0.1")
        if abs(delta["p90_delta"]) > 0.1:
            flags.append(f"p90_shift_{delta['p90_delta']:+.3f}_>_0.1")

    drift_check_id = uuid.uuid4()
    result = DriftCheckResult(
        drift_check_id=drift_check_id,
        period=period,
        sample_size=n,
        rolling_gold_standard_event_ids=[g.event_id for g in gold_standard],
        kappa=kappa,
        confidence_p50=p50,
        confidence_p90=p90,
        delta_from_prior_quarter=delta,
        flags=flags,
    )

    if dry_run:
        _LOG.info(
            "dry_run drift check %s: kappa=%.3f p50=%.3f p90=%.3f flags=%s",
            period, kappa, p50, p90, flags,
        )
        return result

    # --- Persist (atomic across drift row + optional M-2 alert) -----------
    # Per Phase 4 Q8: the drift row + the optional M-2 system_event alert
    # must commit together so the alert always references a real drift
    # row by drift_check_id. Atomic boundary fixes the prior bug where
    # each call opened a fresh psycopg2 connection.
    if db_writer is None:
        with _TransactionalDbWriter() as writer:
            _persist_drift_row(result, parameters_version, writer)
            if kappa < DRIFT_KAPPA_FLOOR and prior_kappa_below_floor:
                alert_id = _persist_m2_system_event(result, writer)
                result.fired_m2_system_event = True
                result.triggered_alert_id = alert_id
    else:
        # Caller-supplied writer: caller owns the transaction boundary.
        _persist_drift_row(result, parameters_version, db_writer)
        if kappa < DRIFT_KAPPA_FLOOR and prior_kappa_below_floor:
            alert_id = _persist_m2_system_event(result, db_writer)
            result.fired_m2_system_event = True
            result.triggered_alert_id = alert_id

    return result


def _persist_drift_row(
    r: DriftCheckResult,
    parameters_version: Optional[uuid.UUID],
    db_writer: Any,
) -> None:
    # Idempotency: migration 010 declares UNIQUE(period) on
    # materiality_classifier_drift. A crash+retry of the quarterly drift
    # check (e.g., the operator re-runs `/parameters-review` after fixing
    # gold-standard input) would raise UniqueViolation and roll back the
    # entire transaction including the optional M-2 alert row. ON CONFLICT
    # DO NOTHING gives first-call-wins semantics for the period; if the
    # operator wants to re-run with revised gold standard they can DELETE
    # the prior row out-of-band (the table is append-only via trigger so
    # this requires explicit admin intervention, which is correct).
    sql = (
        "INSERT INTO materiality_classifier_drift "
        "(drift_check_id, period, sample_size, rolling_gold_standard_event_ids, "
        " kappa, confidence_p50, confidence_p90, delta_from_prior_quarter, "
        " flags, parameters_version) "
        "VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s::jsonb, %s::jsonb, %s) "
        "ON CONFLICT (period) DO NOTHING"
    )
    params = (
        str(r.drift_check_id),
        r.period,
        r.sample_size,
        json.dumps([str(eid) for eid in r.rolling_gold_standard_event_ids]),
        r.kappa,
        r.confidence_p50,
        r.confidence_p90,
        json.dumps(r.delta_from_prior_quarter) if r.delta_from_prior_quarter else None,
        json.dumps(r.flags),
        str(parameters_version) if parameters_version else None,
    )
    db_writer(sql, params)


def _persist_m2_system_event(
    r: DriftCheckResult,
    db_writer: Any,
) -> uuid.UUID:
    """Fire an M-2 system event when kappa < floor for 2 consecutive quarters."""
    alert_id = uuid.uuid4()
    summary = (
        f"Materiality classifier drift: kappa={r.kappa:.3f} below floor "
        f"{DRIFT_KAPPA_FLOOR} for 2 consecutive quarters (period={r.period})."
    )
    payload = {
        "drift_check_id": str(r.drift_check_id),
        "period": r.period,
        "kappa": r.kappa,
        "confidence_p50": r.confidence_p50,
        "confidence_p90": r.confidence_p90,
        "flags": list(r.flags),
        "delta_from_prior_quarter": r.delta_from_prior_quarter,
    }
    sql = (
        "INSERT INTO unread_alerts "
        "(alert_id, severity, alert_type, ticker, summary, payload) "
        "VALUES (%s, %s, %s, %s, %s, %s::jsonb) RETURNING alert_id"
    )
    params = (
        str(alert_id),
        2,                       # M-2 system event per Phase 4 Q8.
        "calibration_drift",     # added in migration 017 (Phase 4 Q8 semantics).
        None,                    # system-level alert; no ticker.
        summary,
        json.dumps(payload, default=str),
    )
    db_writer(sql, params)
    return alert_id
