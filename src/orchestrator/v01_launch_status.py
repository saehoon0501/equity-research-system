"""Launch-gate status grid for the v0.1-launch-readiness phase.

Per v3 spec Section 7 (v0.1 Launch Gates), all gates must pass before
launch. This module surfaces the four gate categories:

  Section 7.1  — Hard gates (functional correctness; all green required)
  Section 7.2  — Calibration gates (≥80%/≥90% targets per gate)
  Section 7.3  — Operator sign-off gates (5 attestations)
  Section 7.3a — Walkthrough launch gates (10 walkthroughs)

Each gate status is queried from the corresponding evidence table.
Gates without a recorded result default to PENDING (never silently PASS).

Render-only. The orchestrator does NOT mark gates green; that's done by
the operator via ``/launch-confirm <gate_name>`` (Section 5.4) which
writes to ``launch_readiness_log`` directly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

_LOG = logging.getLogger(__name__)


class GateStatus(str, Enum):
    """Status of a single launch gate."""

    PASS = "PASS"
    FAIL = "FAIL"
    PENDING = "PENDING"


@dataclass(frozen=True)
class LaunchGate:
    """One Section 7 launch gate."""

    gate_name: str
    category: str  # 'hard' | 'calibration' | 'operator_signoff' | 'walkthrough'
    status: GateStatus
    evidence_link: Optional[str] = None
    detail: Optional[str] = None


@dataclass(frozen=True)
class LaunchGateGrid:
    """Full Section 7 launch-gate grid for rendering."""

    hard_gates: list[LaunchGate] = field(default_factory=list)
    calibration_gates: list[LaunchGate] = field(default_factory=list)
    operator_signoff_gates: list[LaunchGate] = field(default_factory=list)
    walkthrough_gates: list[LaunchGate] = field(default_factory=list)

    @property
    def total(self) -> int:
        return (
            len(self.hard_gates)
            + len(self.calibration_gates)
            + len(self.operator_signoff_gates)
            + len(self.walkthrough_gates)
        )

    @property
    def green(self) -> int:
        return sum(
            1
            for g in (
                *self.hard_gates,
                *self.calibration_gates,
                *self.operator_signoff_gates,
                *self.walkthrough_gates,
            )
            if g.status == GateStatus.PASS
        )

    @property
    def all_green(self) -> bool:
        return self.green == self.total and self.total > 0


# --------------------------------------------------------------------------- #
# Section 7 gate definitions                                                  #
# --------------------------------------------------------------------------- #

# Gate names aligned with v0.1-launch-readiness-audit.md Appendix H (canonical
# 33-gate list under which all v0.1 attestations were recorded). Prior naming
# was a different spec organization that pre-dated the audit doc.

# H.1 — Code-foundation gates (auto-attestable from test output).
_HARD_GATE_NAMES: list[str] = [
    "calibration_harness_pass",
    "walkthrough_nvda_2023",
    "walkthrough_svb_2023",
    "walkthrough_cold_start_day_1",
    "walkthrough_mode_reclass_race",
    "walkthrough_conviction_flip_flop",
    "hmac_chain_integrity",
    "e2e_clean_buy_path",
    "e2e_kill_criterion_fires",
    "e2e_anchor_drift_triggers",
    "e2e_full_chain_smoke",
]

# H.2 — Architectural-lock gates (auto-attestable from module test output).
_CALIBRATION_GATE_NAMES: list[str] = [
    "bocpd_dual_signal_locked",
    "mode_classifier_layered_locked",
    "conviction_rollup_precedence_locked",
    "high_gate_monotonic_locked",
    "hysteresis_pending_target_locked",
    "max_email_attempts_4_locked",
    "canonical_payload_byte_stable",
    "forced_review_pending_sidecar_locked",
    "mode_certainty_separate_from_conviction",
]

# H.3 — Catalog + calibration gates (operator-driven).
# broker_mcp_oauth REMOVED 2026-05-01: operator holds tokenized equities (Gate.io
# xStocks); conventional brokerage architecture doesn't fit. Removed from plan
# entirely (was previously DEFERRED). v0.5+ may add a CryptoExchangeAdapter or
# Plaid-based positions feed if/when needed; src/mcp/broker_mcp/ code retained
# as scaffold for that future revival but not in v0.1 launch gate set.
_OPERATOR_SIGNOFF_GATE_NAMES: list[str] = [
    "peak_pain_priority_consensus",
    "materiality_kappa_>=0_61",
    "peak_pain_pltr_2022_anchor_verified",
    "peak_pain_svb_2023_anchor_verified",
    # H.4 infrastructure gates, here-grouped because they are also operator-driven
    "hmac_keys_4_scopes_set",
    "smtp_credentials_set",
    "postgres_migrations_applied",
    "mcp_servers_running",
]

# H.5 — Spec + governance gates (operator-driven).
_WALKTHROUGH_GATE_NAMES: list[str] = [
    "spec_v3_signoff",
    "operator_reference_read",
    "launch_readiness_audit_read",
    "tier4_deferred_acknowledged",
]


# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #


def collect_launch_gates(conn: Any) -> LaunchGateGrid:
    """Build the full Section 7 launch-gate grid from Postgres state.

    Defensive: missing ``launch_readiness_log`` table → all gates PENDING.

    Returns:
        LaunchGateGrid populated with hard / calibration / operator / walkthrough.
    """
    statuses = _query_launch_readiness_log(conn)

    hard = [_resolve_gate(name, "hard", statuses) for name in _HARD_GATE_NAMES]
    cal = [
        _resolve_gate(name, "calibration", statuses)
        for name in _CALIBRATION_GATE_NAMES
    ]
    op = [
        _resolve_gate(name, "operator_signoff", statuses)
        for name in _OPERATOR_SIGNOFF_GATE_NAMES
    ]
    wt = [
        _resolve_gate(name, "walkthrough", statuses)
        for name in _WALKTHROUGH_GATE_NAMES
    ]

    return LaunchGateGrid(
        hard_gates=hard,
        calibration_gates=cal,
        operator_signoff_gates=op,
        walkthrough_gates=wt,
    )


def render_launch_gate_grid(grid: LaunchGateGrid) -> str:
    """Render a terminal markdown checklist of the gate grid."""
    lines: list[str] = []
    lines.append("## Launch Gate Status (Section 7)")
    lines.append("")
    lines.append(f"**Summary: {grid.green} of {grid.total} gates green**")
    if grid.all_green:
        lines.append("")
        lines.append("All gates green — ready for `/launch-confirm` final pass.")
    lines.append("")

    def _section(title: str, gates: list[LaunchGate]) -> None:
        lines.append(f"### {title} ({_count(gates)})")
        lines.append("")
        for g in gates:
            mark = _mark(g.status)
            line = f"- {mark} `{g.gate_name}` — {g.status.value}"
            if g.detail:
                line += f" ({g.detail})"
            if g.evidence_link:
                line += f" — [evidence]({g.evidence_link})"
            lines.append(line)
        lines.append("")

    _section("Section 7.1 — Hard gates (functional correctness)", grid.hard_gates)
    _section("Section 7.2 — Calibration gates", grid.calibration_gates)
    _section(
        "Section 7.3 — Operator sign-off gates", grid.operator_signoff_gates
    )
    _section(
        "Section 7.3a — Walkthrough launch gates (Phase 4 Q3)",
        grid.walkthrough_gates,
    )

    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------------- #
# Internals                                                                   #
# --------------------------------------------------------------------------- #


def _resolve_gate(
    name: str, category: str, statuses: dict[str, dict]
) -> LaunchGate:
    rec = statuses.get(name)
    if rec is None:
        return LaunchGate(
            gate_name=name,
            category=category,
            status=GateStatus.PENDING,
            detail="no row in launch_readiness_log",
        )
    raw = (rec.get("status") or "").upper()
    try:
        status = GateStatus(raw)
    except ValueError:
        status = GateStatus.PENDING
    return LaunchGate(
        gate_name=name,
        category=category,
        status=status,
        evidence_link=rec.get("evidence_link"),
        detail=rec.get("detail"),
    )


def _query_launch_readiness_log(conn: Any) -> dict[str, dict]:
    """Returns gate_name → row dict. Defensive: missing table → empty."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT gate_name, status, evidence_link, detail
                FROM launch_readiness_log
                """
            )
            rows = cur.fetchall()
    except Exception as exc:  # noqa: BLE001 — defensive, but logged
        _LOG.warning(
            "v01_launch_status._query_launch_readiness_log failed: %s: %s",
            type(exc).__name__, exc,
        )
        return {}
    out: dict[str, dict] = {}
    for r in rows:
        gate_name, status, evidence_link, detail = r
        out[gate_name] = {
            "status": status,
            "evidence_link": evidence_link,
            "detail": detail,
        }
    return out


def _mark(status: GateStatus) -> str:
    if status == GateStatus.PASS:
        return "[x]"
    if status == GateStatus.FAIL:
        return "[!]"
    return "[ ]"


def _count(gates: list[LaunchGate]) -> str:
    green = sum(1 for g in gates if g.status == GateStatus.PASS)
    return f"{green}/{len(gates)}"
