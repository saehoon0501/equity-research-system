# `src/backtesting` — BacktestingFramework

Tier 4 substantive-validation infrastructure consumed by the `/backtest` slash
command. Per `docs/v2-final-spec.md` §2.6 and `.claude/commands/backtest.md`.

This is a **Python package**, not an MCP server. It is invoked from
skill-orchestration code that has already constructed `mcp__market_data` and
`mcp__contamination_check` clients (decision-6: framework consumes
capabilities, doesn't construct them).

## Status

This is the **skeleton** that lands now. The substantive correctness gate at
Checkpoint 3 cannot fully fire until Sharadar Core Fundamentals is online —
see `docs/tier4-deferred-work.md` for the operator-unblock sequence.

### Implemented now (no PIT-fundamentals dependency)

| Surface                          | Implementation                              |
|----------------------------------|---------------------------------------------|
| `compute_dsr`                    | Bailey-Lopez de Prado 2014, eq. 6 + 9       |
| `compute_pbo`                    | Bailey et al. 2014 CSCV (default S=16)      |
| `audit_memos`                    | Orchestration over `mcp__contamination_check.verify_memo` plus 50-claim manual-audit sample |
| `counterfactual_baselines["spy"]`| yfinance daily SPY buy-and-hold              |

### Stubbed pending Sharadar / PIT data

| Surface                                   | Why blocked                                                         |
|-------------------------------------------|---------------------------------------------------------------------|
| `walk_forward`                            | Retroactive PIT screen needed to ensure each memo's quantitative thesis was constructible from pre-surfaced_date information only. Raises `NotImplementedError`. |
| `pre_post_cutoff_sharpe_split`            | Depends on `walk_forward` per-memo realized returns. Same gate.     |
| `counterfactual_baselines["equal_weight_watchlist"]` | Needs PIT watchlist roster.                                  |
| `counterfactual_baselines["sector_matched"]`         | Needs PIT sector-mapping feed.                               |
| `counterfactual_baselines["60_40"]`       | Needs cross-asset (bond) price feed wiring.                          |

## Public API

```python
from src.backtesting import (
    BacktestingFramework,
    WalkForwardResult,
    AuditResult,
    deflated_sharpe_ratio,
    expected_max_sharpe,
    probability_of_backtest_overfitting,
)
```

## Invocation from `/backtest`

The slash command's orchestrator (per `.claude/commands/backtest.md` procedure)
is expected to:

```python
from src.backtesting import BacktestingFramework
# clients are pre-built thin wrappers around the MCP servers
from skill_orchestration import market_data_client, evidence_index_client

fw = BacktestingFramework(
    memo_set_path="memos/sample-set-001/",
    market_data_client=market_data_client,
    evidence_index_client=evidence_index_client,
)

# 1. Mechanical contamination check across the set + manual-audit sample
audit = fw.audit_memos(sample_seed=42)

# 2. Walk-forward (gated on Sharadar — for now this raises)
# wf = fw.walk_forward(embargo_days=5)

# 3. DSR / PBO once walk_forward is unblocked and supplies the inputs
# dsr = fw.compute_dsr(trial_count=20,
#                      sharpe_ratio=wf.aggregate_sharpe,
#                      n_observations=len(wf.returns),
#                      sharpe_periods_per_year=12)
# pbo = fw.compute_pbo(returns_matrix=...)

# 4. SPY counterfactual (works today)
cf = fw.counterfactual_baselines(
    baselines=["spy"],
    start="2022-01-01",
    end="2024-12-31",
)
```

## References

- `docs/v2-final-spec.md` §2.6 — full BacktestingFramework spec
- `docs/phasing-plan.md` §2.5 — phase gates the framework metrics feed
- `docs/tier4-deferred-work.md` — what's deferred and operator unblocks
- `.claude/commands/backtest.md` — slash command procedure
- `.claude/references/contamination-check.md` — audit integration
- Bailey, D. H., and Lopez de Prado, M. (2014). "The Deflated Sharpe Ratio."
  *Journal of Portfolio Management*, 40(5), 94–107.
- Bailey, D. H., Borwein, J., Lopez de Prado, M., and Zhu, Q. J. (2014).
  "The Probability of Backtest Overfitting." *Journal of Computational
  Finance*, 20(4), 39–69.
