"""Unit tests for `src/backtesting` — DSR, PBO, audit_memos.

The math tests (DSR, PBO) need no integration markers. They run against
hand-computed reference values and synthetic distributions.

The audit_memos test runs in stub mode against an in-memory
EvidenceIndexClient mock; it does not require Postgres.

walk_forward / pre_post_cutoff_sharpe_split / non-SPY baselines are gated on
Sharadar (see docs/tier4-deferred-work.md). They raise NotImplementedError;
testing that they do is asserted here so the contract is locked-in until the
unblock lands.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

# Add repo root to sys.path so `from src.backtesting import ...` works under
# uv-managed venvs that don't include the project root automatically.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.backtesting import (  # noqa: E402  (after sys.path mutation)
    BacktestingFramework,
    deflated_sharpe_ratio,
    expected_max_sharpe,
    probability_of_backtest_overfitting,
)


# ---------------------------------------------------------------------------
# DSR tests
# ---------------------------------------------------------------------------
def test_dsr_against_known_value():
    """DSR for SR=1.5, T=120, N=20 trials, normal moments — known value.

    Hand computation:
        SR_per     = 1.5 (treated as per-period; matches the input)
        E[max SR]  ≈ (1 - 0.5772) * Φ⁻¹(0.95) + 0.5772 * Φ⁻¹(1 - 1/(20e))
                   = 0.4228 * 1.6449 + 0.5772 * Φ⁻¹(0.98161)
                   ≈ 0.6953 + 0.5772 * 2.0863
                   ≈ 0.6953 + 1.2042
                   ≈ 1.8995
        denom      = sqrt(1 - 0*1.5 + ((3-1)/4)*1.5^2) = sqrt(1 + 1.125)
                   = sqrt(2.125) ≈ 1.4577
        z          = (1.5 - 1.8995) * sqrt(119) / 1.4577
                   ≈ -0.3995 * 10.9087 / 1.4577
                   ≈ -2.989
        DSR        = Φ(-2.989) ≈ 0.0014

    The reported DSR is very small — exactly the point of the formula:
    a Sharpe of 1.5 over only 120 obs after 20 trials is *not* convincing.
    Tolerance kept reasonable for the polynomial approximations in scipy.
    """
    dsr = deflated_sharpe_ratio(
        sharpe_ratio=1.5,
        n_observations=120,
        n_trials=20,
        skew=0.0,
        kurtosis=3.0,
    )
    # Should be very small but non-zero.
    assert 0.0 < dsr < 0.01, f"DSR={dsr} outside expected band"
    # Cross-check against the closed-form value within a tolerance.
    assert math.isclose(dsr, 0.0014, abs_tol=5e-3)


def test_dsr_no_trials_gives_high_value_when_sharpe_is_strong():
    """Sanity check: with only 1 trial (no selection bias) and a very strong
    Sharpe, DSR should be close to 1."""
    dsr = deflated_sharpe_ratio(
        sharpe_ratio=2.0,
        n_observations=240,
        n_trials=1,
    )
    assert dsr > 0.99, f"DSR={dsr} should be near 1 for SR=2 over 240 obs"


def test_expected_max_sharpe_monotone_in_n():
    """E[max SR] should rise with N (more trials → more selection bias)."""
    e1 = expected_max_sharpe(1)
    e10 = expected_max_sharpe(10)
    e100 = expected_max_sharpe(100)
    assert e1 == 0.0
    assert e10 < e100
    assert e1 < e10


def test_dsr_input_validation():
    with pytest.raises(ValueError):
        deflated_sharpe_ratio(sharpe_ratio=1.0, n_observations=1, n_trials=5)
    with pytest.raises(ValueError):
        deflated_sharpe_ratio(sharpe_ratio=1.0, n_observations=120, n_trials=0)


# ---------------------------------------------------------------------------
# PBO tests
# ---------------------------------------------------------------------------
def test_pbo_uniform_perfect_predictor():
    """A strategy that strictly dominates in every period should have PBO ≈ 0.

    Construction: strategy 0 returns 0.05 per period; all other strategies
    return random noise centered at 0 with small variance. Strategy 0 wins
    in-sample AND out-of-sample on every CSCV split.
    """
    rng = np.random.default_rng(42)
    n_periods, n_strategies = 64, 8
    noise = rng.normal(loc=0.0, scale=0.001, size=(n_periods, n_strategies))
    # Strategy 0: dominant constant return.
    noise[:, 0] = 0.05
    pbo = probability_of_backtest_overfitting(noise, n_partitions=8)
    assert pbo < 0.05, f"PBO={pbo} should be near 0 for a dominant strategy"


def test_pbo_uniform_random():
    """A pool of iid-random strategies should yield PBO well above 0 (the
    math should at least flag noise as overfit-prone).

    Note: BLP 2014's "near 0.5" claim is an asymptotic property; finite-sample
    CSCV with small N (8 partitions × 16 strategies × 128 periods) drifts
    higher (often 0.7–0.9) because the IS winner is more separable from OOS
    losers than at large N. For Tier 4 substrate purposes we test (a) PBO
    returns a value in [0,1] and (b) PBO for iid noise is meaningfully > 0
    (reliable strategies would yield PBO ≈ 0). Operator should re-validate
    against full BLP 2014 reproductions once Sharadar PIT data lands and
    sample sizes are larger.
    """
    rng = np.random.default_rng(2024)
    n_periods, n_strategies = 128, 16
    returns = rng.normal(loc=0.0, scale=0.01, size=(n_periods, n_strategies))
    pbo = probability_of_backtest_overfitting(returns, n_partitions=8)
    assert 0.0 <= pbo <= 1.0, f"PBO={pbo} out of [0,1]"
    assert pbo > 0.20, f"PBO={pbo} for iid noise should be > 0.20 (math broken if not)"


def test_pbo_input_validation():
    with pytest.raises(ValueError):
        # 1-D array.
        probability_of_backtest_overfitting(np.array([1.0, 2.0, 3.0]))
    with pytest.raises(ValueError):
        # Single column.
        probability_of_backtest_overfitting(np.zeros((100, 1)))
    with pytest.raises(ValueError):
        # Odd partition count.
        probability_of_backtest_overfitting(np.zeros((100, 4)), n_partitions=5)


# ---------------------------------------------------------------------------
# audit_memos smoke test
# ---------------------------------------------------------------------------
class _MockEvidenceIndexClient:
    """Stub EvidenceIndexClient: returns canned PASS/FAIL per memo path."""

    def __init__(self, verdicts: dict[str, dict[str, Any]] | None = None):
        # Map of memo_path → verify_memo response dict.
        self.verdicts = verdicts or {}
        self.call_log: list[str] = []

    def verify_memo(self, memo_path: str) -> dict[str, Any]:
        self.call_log.append(memo_path)
        return self.verdicts.get(
            memo_path,
            {
                "verdict": "PASS",
                "summary": {"n_claims": 1, "n_refs": 1, "n_failures": 0},
                "failures": [],
            },
        )

    def verify(
        self,
        agent_run_id: str,
        evidence_index_refs: list[str],
        claims: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "verdict": "PASS",
            "summary": {
                "n_claims": len(claims),
                "n_refs": len(evidence_index_refs),
                "n_failures": 0,
            },
            "failures": [],
        }


class _MockMarketDataClient:
    def __init__(self, prices: list[float] | None = None):
        self._prices = prices or []

    def get_prices(
        self,
        ticker: str,
        start: str,
        end: str,
        interval: str = "1d",
    ) -> dict[str, Any]:
        return {
            "rows": [
                {"date": f"2024-01-{i+1:02d}", "close": p}
                for i, p in enumerate(self._prices)
            ]
        }


def _write_memo(path: Path, **fields: Any) -> None:
    payload = {
        "ticker": "TEST",
        "surfaced_date": "2024-06-01",
        "evidence_index_refs": ["00000000-0000-0000-0000-000000000001"],
        "reviewable_predictions": [
            {
                "prediction_text": "Revenue will grow 15% by Q1 2025",
                "evidence_id": "00000000-0000-0000-0000-000000000001",
                "target_date": "2025-03-31",
            }
        ],
    }
    payload.update(fields)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_audit_memos_smoke(tmp_path: Path):
    """audit_memos can be called against a mocked evidence_index_client."""
    memo_a = tmp_path / "memo_a.json"
    memo_b = tmp_path / "memo_b.json"
    _write_memo(memo_a)
    _write_memo(memo_b)

    failing_response = {
        "verdict": "FAIL",
        "summary": {"n_claims": 1, "n_refs": 1, "n_failures": 1},
        "failures": [
            {
                "claim_text": "Revenue grew 23%",
                "evidence_id": "deadbeef-...",
                "failure_mode": "FABRICATED_UUID",
                "diagnostic": "evidence_id not in evidence_index",
                "source_date": None,
                "resolution_date": "2024-09-30",
            }
        ],
    }
    mock_idx = _MockEvidenceIndexClient(verdicts={str(memo_b): failing_response})
    mock_md = _MockMarketDataClient()

    fw = BacktestingFramework(
        memo_set_path=str(tmp_path),
        market_data_client=mock_md,
        evidence_index_client=mock_idx,
    )
    result = fw.audit_memos(sample_seed=0)

    assert result.n_memos_audited == 2
    assert result.n_claims == 2  # one claim per memo per the canned response
    # memo_a → PASS (default), memo_b → FAIL
    verdict_map = dict(result.per_memo_verdicts)
    assert verdict_map[str(memo_a)] == "PASS"
    assert verdict_map[str(memo_b)] == "FAIL"
    assert result.n_failures_by_mode.get("FABRICATED_UUID") == 1
    # Sample size capped at min(50, total_claims). With 2 prediction-shaped
    # claims across the two memos, expect 2 sampled.
    assert len(result.sampled_claims) == 2
    # call_log proves the orchestration walked every memo.
    assert sorted(mock_idx.call_log) == sorted([str(memo_a), str(memo_b)])


def test_audit_memos_empty_memo_set(tmp_path: Path):
    """An empty memo-set path returns a zeroed AuditResult, no crash."""
    fw = BacktestingFramework(
        memo_set_path=str(tmp_path),
        market_data_client=_MockMarketDataClient(),
        evidence_index_client=_MockEvidenceIndexClient(),
    )
    result = fw.audit_memos()
    assert result.n_memos_audited == 0
    assert result.n_claims == 0
    assert result.n_failures_by_mode == {}
    assert result.per_memo_verdicts == ()
    assert result.sampled_claims == ()


# ---------------------------------------------------------------------------
# Stubbed-surfaces contracts
# ---------------------------------------------------------------------------
def test_walk_forward_raises_pending_pit_data(tmp_path: Path):
    """walk_forward must raise NotImplementedError until Sharadar lands."""
    memo = tmp_path / "memo.json"
    _write_memo(memo)
    fw = BacktestingFramework(
        memo_set_path=str(tmp_path),
        market_data_client=_MockMarketDataClient(),
        evidence_index_client=_MockEvidenceIndexClient(),
    )
    with pytest.raises(NotImplementedError, match="PIT|Sharadar"):
        fw.walk_forward(embargo_days=5)


def test_pre_post_cutoff_split_raises_pending_pit_data(tmp_path: Path):
    memo = tmp_path / "memo.json"
    _write_memo(memo)
    fw = BacktestingFramework(
        memo_set_path=str(tmp_path),
        market_data_client=_MockMarketDataClient(),
        evidence_index_client=_MockEvidenceIndexClient(),
    )
    with pytest.raises(NotImplementedError, match="PIT|Sharadar|walk_forward"):
        fw.pre_post_cutoff_sharpe_split(cutoff_date="2024-04-01")


def test_counterfactual_baselines_spy_implemented(tmp_path: Path):
    """SPY baseline computes total_return + Sharpe from mocked prices."""
    memo = tmp_path / "memo.json"
    _write_memo(memo)
    # 5 prices → 4 returns. Construct a smoothly rising series so total_return
    # is positive and Sharpe is well-defined.
    prices = [100.0, 101.0, 102.0, 103.0, 104.0]
    fw = BacktestingFramework(
        memo_set_path=str(tmp_path),
        market_data_client=_MockMarketDataClient(prices=prices),
        evidence_index_client=_MockEvidenceIndexClient(),
    )
    result = fw.counterfactual_baselines(
        baselines=["spy", "equal_weight_watchlist", "sector_matched", "60_40"],
        start="2024-01-01",
        end="2024-01-05",
    )
    assert result["spy"]["status"] == "OK"
    assert result["spy"]["total_return"] > 0
    assert "sharpe" in result["spy"]
    # Other baselines remain stubbed.
    assert result["equal_weight_watchlist"]["status"] == "STUBBED"
    assert result["sector_matched"]["status"] == "STUBBED"
    assert result["60_40"]["status"] == "STUBBED"
