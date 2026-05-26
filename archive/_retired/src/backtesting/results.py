"""Result dataclasses for the BacktestingFramework.

Frozen dataclasses so results are immutable once produced — a backtest output
should not be mutated downstream; if you want a derived view, build a new one.

The shapes here track v2-final §2.6 ("Compute metrics") and the
`.claude/commands/backtest.md` output schema.
"""

from __future__ import annotations

import dataclasses
from typing import Any


@dataclasses.dataclass(frozen=True)
class WalkForwardResult:
    """Output of `BacktestingFramework.walk_forward`.

    Per Lopez de Prado walk-forward + embargo discipline. `embargo_days` is
    the purge window between the end of an in-sample fit and the start of the
    out-of-sample evaluation; without it, leakage from autocorrelated features
    inflates Sharpe.

    Fields:
        embargo_days:        embargo length used for the run.
        periods:             list of (start_date_iso, end_date_iso) per period.
        returns:             per-period realized returns (decimal, e.g. 0.045).
        drawdowns:           per-period max drawdown (negative or zero).
        sharpe_per_period:   per-period annualized Sharpe.
        aggregate_sharpe:    Sharpe over the concatenated period series.
        n_memos:             number of memos that produced any per-period row.
        notes:               free-form notes (e.g. "PIT-fundamentals stubbed").
    """

    embargo_days: int
    periods: tuple[tuple[str, str], ...]
    returns: tuple[float, ...]
    drawdowns: tuple[float, ...]
    sharpe_per_period: tuple[float, ...]
    aggregate_sharpe: float
    n_memos: int
    notes: str = ""


@dataclasses.dataclass(frozen=True)
class AuditResult:
    """Output of `BacktestingFramework.audit_memos`.

    Tracks the mechanical contamination check (`mcp__contamination_check`)
    sweep across a memo set plus the 50-claim manual-audit sample required
    by `.claude/references/contamination-check.md`.

    Fields:
        n_memos_audited:        memo count submitted to verify_memo.
        n_claims:               total claim rows seen across all memos.
        n_failures_by_mode:     counts keyed by failure_mode strings emitted by
                                mcp__contamination_check.verify (FABRICATED_UUID,
                                POSTDATED_SOURCE, EMPTY_REFS, MISSING_REF,
                                INCOHERENT_PREDICTION, ...).
        per_memo_verdicts:      ordered list of (memo_path, verdict) tuples,
                                verdict ∈ {"PASS", "FAIL"}.
        sampled_claims:         the 50 (or fewer) claims pulled for manual audit.
                                Each is a dict matching the verify() claim schema
                                plus the originating memo_path.
    """

    n_memos_audited: int
    n_claims: int
    n_failures_by_mode: dict[str, int]
    per_memo_verdicts: tuple[tuple[str, str], ...]
    sampled_claims: tuple[dict[str, Any], ...]
