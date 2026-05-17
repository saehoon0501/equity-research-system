"""BacktestingFramework — Tier 4 substantive validation infrastructure.

Per BUILD_LOG.md, `.claude/commands/backtest.md`, and v2-final §2.6.

This package is consumed by the `/backtest` slash command. It is NOT an MCP
server — it's a Python package whose entrypoint (`BacktestingFramework`) is
instantiated by skill orchestration code with already-constructed MCP clients
(decision-6: framework consumes capabilities, doesn't construct them).

Skeleton scope (current session):
- DSR (Bailey, Lopez de Prado 2014) — implemented; pure stats.
- PBO (Bailey-Lopez de Prado 2014, CSCV) — implemented; pure stats.
- audit_memos — implemented; orchestration over mcp__contamination_check.
- counterfactual_baselines — SPY implemented via yfinance; others stubbed.
- walk_forward — structure stubbed; raises on PIT-fundamentals math.
- pre_post_cutoff_sharpe_split — structure stubbed; raises on PIT math.

Operator unblocks (per docs/tier4-deferred-work.md):
- Sharadar Core Fundamentals subscription → flips the NotImplementedErrors.
"""

from __future__ import annotations

from src.backtesting.dsr import deflated_sharpe_ratio, expected_max_sharpe
from src.backtesting.framework import BacktestingFramework
from src.backtesting.pbo import probability_of_backtest_overfitting
from src.backtesting.results import AuditResult, WalkForwardResult

__all__ = [
    "AuditResult",
    "BacktestingFramework",
    "WalkForwardResult",
    "deflated_sharpe_ratio",
    "expected_max_sharpe",
    "probability_of_backtest_overfitting",
]
