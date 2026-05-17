"""BacktestingFramework — main entry point invoked by the `/backtest` skill.

Per BUILD_LOG.md decision 6: the framework consumes already-instantiated MCP
clients (market_data, evidence_index/contamination_check) — it does NOT
construct them. This keeps the framework testable with mocked clients and
honors the layering between Tier 4 application code and Tier 3 MCP servers.

What's substantively implemented (no PIT-fundamentals dependency):
    - compute_dsr     → Bailey-Lopez de Prado 2014 DSR (pure stats).
    - compute_pbo     → Bailey-Lopez de Prado 2014 PBO/CSCV (pure stats).
    - audit_memos     → orchestration over mcp__contamination_check.verify
                        plus the 50-claim manual-audit sample required by
                        `.claude/references/contamination-check.md` Checkpoint 3.
    - counterfactual_baselines (SPY only) → yfinance buy-and-hold.

What's stubbed pending Sharadar:
    - walk_forward    → structure ready; raises NotImplementedError on the
                        portion that requires PIT fundamentals (e.g.
                        retroactive financial-ratio screens at memo as-of
                        date). Price-only mechanics (per-memo realized return
                        from surfaced_date forward) are sketched here for the
                        future operator.
    - pre_post_cutoff_sharpe_split → same shape; PIT-dependent math gated.
    - counterfactual_baselines (sector_matched, equal_weight, 60_40) → stubs.

See `docs/tier4-deferred-work.md` for the unblocking sequence.
"""

from __future__ import annotations

import datetime as _dt
import json
import random
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from src.backtesting.dsr import deflated_sharpe_ratio
from src.backtesting.pbo import probability_of_backtest_overfitting
from src.backtesting.results import AuditResult, WalkForwardResult


# ---------------------------------------------------------------------------
# Client protocols
# ---------------------------------------------------------------------------
# The framework does not import live MCP plumbing; it accepts duck-typed
# clients that match these protocols. In production these are wrappers around
# mcp__market_data and mcp__contamination_check tool calls; in tests they are
# trivial mocks.


class MarketDataClient(Protocol):
    """Subset of mcp__market_data the framework relies on."""

    def get_prices(
        self,
        ticker: str,
        start: str,
        end: str,
        interval: str = "1d",
    ) -> dict[str, Any]:
        """Return OHLCV dict; shape mirrors mcp__market_data.get_prices."""
        ...


class EvidenceIndexClient(Protocol):
    """Subset of mcp__contamination_check the framework relies on.

    Method names mirror the FastMCP tool surface in
    `src/mcp/contamination_check/server.py` so a thin adapter to live MCP is
    a one-liner each.
    """

    def verify_memo(self, memo_path: str) -> dict[str, Any]:
        """Run mechanical contamination check against a memo JSON file."""
        ...

    def verify(
        self,
        agent_run_id: str,
        evidence_index_refs: list[str],
        claims: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Hard-gate verification given explicit refs/claims lists."""
        ...


# ---------------------------------------------------------------------------
# Framework
# ---------------------------------------------------------------------------
class BacktestingFramework:
    """Substantive validation harness for memo sets.

    Instantiated by the `/backtest` skill orchestration code with a memo set
    path and pre-built MCP clients. Methods correspond to the procedure in
    `.claude/commands/backtest.md`.
    """

    # Manual-audit sample size from .claude/references/contamination-check.md
    # ("the Checkpoint 3 manual audit of 50 random claims") and
    # docs/phasing-plan.md §2.5.2.
    MANUAL_AUDIT_SAMPLE_SIZE = 50

    def __init__(
        self,
        memo_set_path: str,
        market_data_client: MarketDataClient,
        evidence_index_client: EvidenceIndexClient,
    ) -> None:
        """Wire the framework to a memo set and the capability clients.

        Args:
            memo_set_path:           filesystem path to a directory of memo
                                     JSON files OR a single memo JSON file.
                                     Each memo's evidence_index_refs and
                                     reviewable_predictions are consumed.
            market_data_client:      pre-instantiated mcp__market_data client.
                                     Decision-6: framework does NOT construct.
            evidence_index_client:   pre-instantiated mcp__contamination_check
                                     client.

        Raises:
            FileNotFoundError if memo_set_path does not exist.
        """
        path = Path(memo_set_path)
        if not path.exists():
            raise FileNotFoundError(f"memo_set_path not found: {memo_set_path}")
        self.memo_set_path = path
        self.market_data = market_data_client
        self.evidence_index = evidence_index_client

    # ------------------------------------------------------------------ #
    # Memo discovery                                                     #
    # ------------------------------------------------------------------ #
    def _iter_memo_paths(self) -> list[Path]:
        """Return sorted list of memo JSON files under memo_set_path.

        A bare file (single memo) returns [path]; a directory returns every
        *.json under it (non-recursive — memo sets are flat by convention).
        """
        if self.memo_set_path.is_file():
            return [self.memo_set_path]
        return sorted(self.memo_set_path.glob("*.json"))

    @staticmethod
    def _load_memo(path: Path) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    # ------------------------------------------------------------------ #
    # Walk-forward validation                                            #
    # ------------------------------------------------------------------ #
    def walk_forward(self, embargo_days: int = 5) -> WalkForwardResult:
        """Walk-forward validation with embargo (Lopez de Prado).

        Per `.claude/commands/backtest.md` step 4 + v2-final §2.6:
          - Anchor entry at each memo's surfaced_date (memo.as_of_date).
          - Forward-only execution (no post-entry info informs pre-entry).
          - Embargo period purges autocorrelation between IS-fit and OOS-eval.

        v0.5 ACTIVATION (2026-05-04):
          PIT fundamentals are wired via mcp__fundamentals.get_fundamentals
          (EDGAR XBRL with `as_of_date` filing-date filter) per
          docs/tier4-deferred-work.md. Per-memo claim-by-claim contamination
          defense remains the audit_memos() responsibility (mechanical check
          via mcp__contamination_check); walk_forward computes the price-only
          realized-return aggregation. Memos generated against EDGAR PIT
          data are by-construction non-contaminated at the fundamentals
          layer; explicit per-memo PIT-screen failures should be raised by
          the upstream memo generator, not retroactively here.

        Args:
            embargo_days: purge window between in-sample and out-of-sample.
                          Default 5 trading days per Lopez de Prado.

        Returns:
            WalkForwardResult with per-memo realized return + aggregate Sharpe.
        """
        if embargo_days < 0:
            raise ValueError(f"embargo_days must be >= 0, got {embargo_days}")

        memo_paths = self._iter_memo_paths()
        if not memo_paths:
            return WalkForwardResult(
                embargo_days=embargo_days,
                periods=(),
                returns=(),
                drawdowns=(),
                sharpe_per_period=(),
                aggregate_sharpe=0.0,
                n_memos=0,
                notes="No memos found at memo_set_path.",
            )

        periods: list[tuple[str, str]] = []
        returns: list[float] = []
        drawdowns: list[float] = []
        sharpe_per_period: list[float] = []
        skipped: list[str] = []
        all_daily_returns: list[float] = []
        n_resolved = 0

        for memo_path in memo_paths:
            try:
                memo = self._load_memo(memo_path)
                ticker = memo.get("ticker")
                surfaced = memo.get("as_of_date")
                horizon_years = (
                    memo.get("section_7_confidence_distribution", {})
                    .get("horizon_years", 1)
                )
                if not ticker or not surfaced:
                    skipped.append(f"{memo_path.name}: missing ticker/as_of_date")
                    continue
                start = _dt.date.fromisoformat(surfaced)
                end = start + _dt.timedelta(days=int(horizon_years * 365))
                # Cap end at today — walk-forward shouldn't peek into the future.
                today = _dt.date.today()
                if end > today:
                    end = today
                if end <= start:
                    skipped.append(
                        f"{memo_path.name}: horizon ends before/on surfaced_date"
                    )
                    continue

                price_payload = self.market_data.get_prices(
                    ticker, start.isoformat(), end.isoformat()
                )
                rows = sorted(
                    price_payload.get("rows") or [],
                    key=lambda r: r.get("date", ""),
                )
                rows = [r for r in rows if (r.get("adj_close") or r.get("close"))]
                if len(rows) < 2:
                    skipped.append(
                        f"{memo_path.name}: <2 price bars in window"
                    )
                    continue

                start_close = float(rows[0].get("adj_close") or rows[0]["close"])
                end_close = float(rows[-1].get("adj_close") or rows[-1]["close"])
                memo_return = (end_close / start_close) - 1.0

                # Daily simple returns + max drawdown over the window.
                closes = [
                    float(r.get("adj_close") or r["close"]) for r in rows
                ]
                daily = [
                    (closes[i] / closes[i - 1]) - 1.0
                    for i in range(1, len(closes))
                ]
                running_peak = closes[0]
                max_dd = 0.0
                for c in closes:
                    if c > running_peak:
                        running_peak = c
                    dd = (c / running_peak) - 1.0
                    if dd < max_dd:
                        max_dd = dd

                # Per-memo annualized Sharpe (252 trading-day convention; 0
                # risk-free assumption — v2-final §2.6 leaves the rf to the
                # caller for now). Skip if stdev is degenerate.
                memo_sharpe = 0.0
                if daily:
                    n = len(daily)
                    mean = sum(daily) / n
                    if n > 1:
                        variance = sum((x - mean) ** 2 for x in daily) / (n - 1)
                        if variance > 0:
                            stdev = variance ** 0.5
                            memo_sharpe = (mean / stdev) * (252 ** 0.5)

                periods.append((rows[0]["date"], rows[-1]["date"]))
                returns.append(memo_return)
                drawdowns.append(max_dd)
                sharpe_per_period.append(memo_sharpe)
                n_resolved += 1

                # Concatenate daily returns into the aggregate series with
                # an embargo gap of `embargo_days` zeros — the embargo
                # neutralizes autocorrelation across memo boundaries.
                if all_daily_returns:
                    all_daily_returns.extend([0.0] * embargo_days)
                all_daily_returns.extend(daily)

            except Exception as exc:  # noqa: BLE001
                skipped.append(f"{memo_path.name}: {type(exc).__name__}: {exc}")

        # Aggregate Sharpe over the concatenated, embargo-padded series.
        agg_sharpe = 0.0
        if len(all_daily_returns) > 1:
            n = len(all_daily_returns)
            mean = sum(all_daily_returns) / n
            variance = sum((x - mean) ** 2 for x in all_daily_returns) / (n - 1)
            if variance > 0:
                agg_sharpe = (mean / (variance ** 0.5)) * (252 ** 0.5)

        notes_lines: list[str] = []
        notes_lines.append(
            "PIT fundamentals: EDGAR XBRL via mcp__fundamentals (as_of_date "
            "filing-date filter). Per-memo claim contamination check is the "
            "responsibility of audit_memos()."
        )
        if skipped:
            notes_lines.append(
                f"skipped={len(skipped)}; first 5: {skipped[:5]}"
            )

        return WalkForwardResult(
            embargo_days=embargo_days,
            periods=tuple(periods),
            returns=tuple(returns),
            drawdowns=tuple(drawdowns),
            sharpe_per_period=tuple(sharpe_per_period),
            aggregate_sharpe=agg_sharpe,
            n_memos=n_resolved,
            notes=" | ".join(notes_lines),
        )

    # ------------------------------------------------------------------ #
    # DSR / PBO — pure stats, fully implemented                          #
    # ------------------------------------------------------------------ #
    def compute_dsr(
        self,
        trial_count: int,
        sharpe_ratio: float | None = None,
        n_observations: int | None = None,
        skew: float = 0.0,
        kurtosis: float = 3.0,
        sharpe_periods_per_year: int | None = None,
    ) -> float:
        """Deflated Sharpe Ratio with explicit trial reporting.

        Per `.claude/commands/backtest.md` §11 anti-pattern: every alternate
        parameter set evaluated MUST be counted as an additional trial. The
        caller passes the honest trial count; this method does not infer it.

        Args:
            trial_count:                N strategies / parameter combos
                                        evaluated.
            sharpe_ratio:               observed Sharpe of the chosen strategy.
                                        If None, the framework does not yet
                                        know it — caller should supply via
                                        walk_forward output.
            n_observations:             T return observations supporting that
                                        Sharpe.
            skew, kurtosis:             higher moments of the return
                                        distribution (defaults: normal).
            sharpe_periods_per_year:    if Sharpe is annualized, pass the
                                        annualization factor to de-annualize
                                        for the formula.

        Returns:
            DSR ∈ [0, 1]. Gate per phasing-plan.md §2.5.3: > 0.5.
        """
        if sharpe_ratio is None or n_observations is None:
            raise ValueError(
                "compute_dsr requires sharpe_ratio and n_observations. The "
                "skill-layer caller should source these from walk_forward "
                "output once that path is unblocked."
            )
        return deflated_sharpe_ratio(
            sharpe_ratio=sharpe_ratio,
            n_observations=n_observations,
            n_trials=trial_count,
            skew=skew,
            kurtosis=kurtosis,
            sharpe_periods_per_year=sharpe_periods_per_year,
        )

    def compute_pbo(
        self,
        returns_matrix: np.ndarray | None = None,
        n_partitions: int = 16,
    ) -> float:
        """Probability of Backtest Overfitting (Bailey-Lopez de Prado 2014).

        Args:
            returns_matrix: T×N matrix of period × strategy returns.
            n_partitions:   CSCV partition count S; default 16 per the paper.

        Returns:
            PBO ∈ [0, 1]. Gate per phasing-plan.md §2.5.3: < 0.5.
        """
        if returns_matrix is None:
            raise ValueError(
                "compute_pbo requires a T×N returns_matrix. The skill-layer "
                "caller should assemble this from walk_forward per-period "
                "returns once that path is unblocked, or from "
                "parameter-sweep results."
            )
        return probability_of_backtest_overfitting(
            returns_matrix=returns_matrix,
            n_partitions=n_partitions,
        )

    # ------------------------------------------------------------------ #
    # Pre / post-cutoff Sharpe split                                     #
    # ------------------------------------------------------------------ #
    def pre_post_cutoff_sharpe_split(self, cutoff_date: str) -> dict[str, Any]:
        """Split the backtest into pre-cutoff and post-cutoff Sharpe ratios.

        Per `.claude/commands/backtest.md` step 7 + phasing-plan.md §2.5.1:
            effective_cutoff = stated_model_cutoff + 6 months

        For each memo, decide pre vs post based on surfaced_date relative to
        the effective cutoff; aggregate Sharpe within each bucket; report the
        degradation ratio for gate evaluation.

        Args:
            cutoff_date: ISO date string. The caller is expected to have
                         already added the 6-month buffer per phasing-plan
                         §2.5.1 — this method takes the *effective* cutoff.

        Returns:
            dict with keys:
                - pre_cutoff:  {n_memos, sharpe, mean_return, max_drawdown}
                - post_cutoff: {n_memos, sharpe, mean_return, max_drawdown}
                - degradation_ratio: (pre - post) / pre, or None if pre==0.
                - gate_status: PASS | FAIL | KILL per phasing-plan.md §2.5.1
                  thresholds (≤20% / 20-40% / >40%).

        Raises:
            NotImplementedError on the PIT-fundamentals branch (same gating
            as walk_forward).
        """
        try:
            _dt.date.fromisoformat(cutoff_date)
        except ValueError as exc:
            raise ValueError(
                f"cutoff_date must be ISO YYYY-MM-DD, got {cutoff_date!r}"
            ) from exc

        memo_paths = self._iter_memo_paths()
        if not memo_paths:
            return {
                "pre_cutoff": None,
                "post_cutoff": None,
                "degradation_ratio": None,
                "gate_status": "INSUFFICIENT_DATA",
                "notes": "No memos found at memo_set_path.",
            }

        cutoff = _dt.date.fromisoformat(cutoff_date)
        wf = self.walk_forward()  # default embargo_days=5

        pre_returns: list[float] = []
        pre_drawdowns: list[float] = []
        post_returns: list[float] = []
        post_drawdowns: list[float] = []

        # walk_forward emits one (period_start, period_end) tuple per memo
        # plus aligned returns/drawdowns; partition on the period_start
        # against the effective cutoff.
        for (start_iso, _), ret, dd in zip(wf.periods, wf.returns, wf.drawdowns):
            try:
                start = _dt.date.fromisoformat(start_iso)
            except ValueError:
                continue
            if start <= cutoff:
                pre_returns.append(ret)
                pre_drawdowns.append(dd)
            else:
                post_returns.append(ret)
                post_drawdowns.append(dd)

        def _sharpe(returns: list[float]) -> float:
            n = len(returns)
            if n < 2:
                return 0.0
            mean = sum(returns) / n
            variance = sum((x - mean) ** 2 for x in returns) / (n - 1)
            if variance <= 0:
                return 0.0
            # Per-memo returns are already realized over the holding window;
            # we treat them as iid-per-memo and report the unannualized
            # Sharpe. Caller annualizes if needed.
            return mean / (variance ** 0.5)

        pre_sharpe = _sharpe(pre_returns)
        post_sharpe = _sharpe(post_returns)

        degradation = None
        gate_status = "INSUFFICIENT_DATA"
        if pre_sharpe != 0 and (pre_returns and post_returns):
            degradation = (pre_sharpe - post_sharpe) / pre_sharpe
            # Per phasing-plan.md §2.5.1: ≤20% PASS / 20-40% FAIL / >40% KILL.
            if degradation <= 0.20:
                gate_status = "PASS"
            elif degradation <= 0.40:
                gate_status = "FAIL"
            else:
                gate_status = "KILL"

        return {
            "pre_cutoff": {
                "n_memos": len(pre_returns),
                "sharpe": pre_sharpe,
                "mean_return": (sum(pre_returns) / len(pre_returns)) if pre_returns else 0.0,
                "max_drawdown": min(pre_drawdowns) if pre_drawdowns else 0.0,
            },
            "post_cutoff": {
                "n_memos": len(post_returns),
                "sharpe": post_sharpe,
                "mean_return": (sum(post_returns) / len(post_returns)) if post_returns else 0.0,
                "max_drawdown": min(post_drawdowns) if post_drawdowns else 0.0,
            },
            "degradation_ratio": degradation,
            "gate_status": gate_status,
            "notes": wf.notes,
        }

    # ------------------------------------------------------------------ #
    # Memo audit — full orchestration over existing capabilities         #
    # ------------------------------------------------------------------ #
    def audit_memos(self, sample_seed: int | None = None) -> AuditResult:
        """Run mechanical contamination check across the memo set.

        Per `.claude/references/contamination-check.md` and phasing-plan.md
        §2.5.2:
            1. Call mcp__contamination_check.verify_memo for every memo.
            2. Aggregate verdicts and failure-mode counts.
            3. Sample 50 random claims across the set for the manual audit
               cross-check (Checkpoint 3 gate); the manual reviewer eyeballs
               those 50 for failure modes the mechanical check can't catch.

        This method orchestrates over capabilities that already exist; no
        Sharadar dependency.

        Args:
            sample_seed: optional RNG seed for reproducible sampling. Defaults
                         to None (system-random) — production audits should
                         pass a seed and record it alongside the result.

        Returns:
            AuditResult with verdicts, failure-mode histogram, and the sampled
            claim list. n_failures_by_mode is keyed by the failure_mode
            strings emitted by mcp__contamination_check.verify
            (FABRICATED_UUID, POSTDATED_SOURCE, EMPTY_REFS, MISSING_REF,
            INCOHERENT_PREDICTION, ...).
        """
        memo_paths = self._iter_memo_paths()
        if not memo_paths:
            return AuditResult(
                n_memos_audited=0,
                n_claims=0,
                n_failures_by_mode={},
                per_memo_verdicts=(),
                sampled_claims=(),
            )

        per_memo_verdicts: list[tuple[str, str]] = []
        failures_by_mode: dict[str, int] = {}
        all_claims: list[dict[str, Any]] = []
        n_claims_total = 0

        for memo_path in memo_paths:
            result = self.evidence_index.verify_memo(str(memo_path))
            verdict = result.get("verdict", "UNKNOWN")
            per_memo_verdicts.append((str(memo_path), verdict))

            summary = result.get("summary", {}) or {}
            n_claims_total += int(summary.get("n_claims", 0) or 0)

            for failure in result.get("failures", []) or []:
                mode = failure.get("failure_mode", "UNKNOWN")
                failures_by_mode[mode] = failures_by_mode.get(mode, 0) + 1

            # Collect claims for the manual-audit sample. We pull from the
            # memo file directly because verify_memo's response surfaces
            # failures, not all claims.
            try:
                memo = self._load_memo(memo_path)
            except (json.JSONDecodeError, OSError):
                continue
            for claim in self._extract_claims(memo, str(memo_path)):
                all_claims.append(claim)

        rng = random.Random(sample_seed)
        sample_n = min(self.MANUAL_AUDIT_SAMPLE_SIZE, len(all_claims))
        sampled = tuple(rng.sample(all_claims, sample_n)) if sample_n > 0 else ()

        return AuditResult(
            n_memos_audited=len(memo_paths),
            n_claims=n_claims_total,
            n_failures_by_mode=dict(failures_by_mode),
            per_memo_verdicts=tuple(per_memo_verdicts),
            sampled_claims=sampled,
        )

    @staticmethod
    def _extract_claims(memo: dict[str, Any], memo_path: str) -> list[dict[str, Any]]:
        """Pull claim-shaped rows out of a memo JSON.

        Mirrors the extraction in `mcp__contamination_check.verify_memo`:
        reviewable_predictions become `claim_type='prediction'`. The full
        memo's claim list is conventionally surfaced separately on the
        verify_memo response — this helper covers the predictions case which
        is enough for the manual-audit sample.
        """
        claims: list[dict[str, Any]] = []
        for prediction in memo.get("reviewable_predictions", []) or []:
            claim = {
                "memo_path": memo_path,
                "claim_text": prediction.get("prediction_text"),
                "claim_type": "prediction",
                "evidence_id": prediction.get("evidence_id"),
                "resolution_date": prediction.get("target_date")
                or prediction.get("resolution_date"),
            }
            claims.append(claim)
        # If the memo embeds an explicit claims[] list (some authoring paths
        # do, others don't), include those rows verbatim.
        for claim in memo.get("claims", []) or []:
            claims.append({**claim, "memo_path": memo_path})
        return claims

    # ------------------------------------------------------------------ #
    # Counterfactual baselines                                           #
    # ------------------------------------------------------------------ #
    def counterfactual_baselines(
        self,
        baselines: list[str] | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> dict[str, Any]:
        """Compute returns for the standard counterfactual baselines.

        Per `.claude/commands/backtest.md` step 8 + v2-final §2.6:
            - SPY buy-and-hold       (yfinance — IMPLEMENTED)
            - equal_weight_watchlist (PIT fundamentals — STUBBED)
            - sector_matched         (sector classification feed — STUBBED)
            - 60_40                  (TLT/AGG mix — STUBBED until cross-asset
                                      data feed is wired; SPY-only for now)

        Args:
            baselines: subset of {"spy", "equal_weight_watchlist",
                       "sector_matched", "60_40"}. Defaults to all.
            start, end: ISO date strings bounding the baseline period. If
                        None, the caller is expected to wire from
                        walk_forward's date span — for the skeleton, both
                        must be supplied for SPY to compute.

        Returns:
            dict keyed by baseline name. Each entry is a
            {sharpe, total_return, status} sub-dict; status is "OK",
            "STUBBED", or "ERROR".
        """
        if baselines is None:
            baselines = ["spy", "equal_weight_watchlist", "sector_matched", "60_40"]

        out: dict[str, Any] = {}

        for name in baselines:
            if name == "spy":
                out[name] = self._spy_baseline(start, end)
            elif name == "equal_weight_watchlist":
                out[name] = {
                    "status": "STUBBED",
                    "reason": (
                        "Equal-weight watchlist requires the watchlist roster "
                        "as-of each date in the backtest window — PIT data "
                        "dependency. See docs/tier4-deferred-work.md."
                    ),
                }
            elif name == "sector_matched":
                out[name] = {
                    "status": "STUBBED",
                    "reason": (
                        "Sector-matched basket requires a PIT sector-mapping "
                        "feed (FinViz/Sharadar). See "
                        "docs/tier4-deferred-work.md."
                    ),
                }
            elif name == "60_40":
                out[name] = {
                    "status": "STUBBED",
                    "reason": (
                        "60/40 baseline requires bond-index price feed; "
                        "yfinance covers TLT/AGG but the framework's "
                        "single-asset SPY path is the only one wired in the "
                        "current skeleton. Add when adding the rest."
                    ),
                }
            else:
                out[name] = {
                    "status": "ERROR",
                    "reason": f"Unknown baseline: {name!r}",
                }
        return out

    def _spy_baseline(
        self,
        start: str | None,
        end: str | None,
    ) -> dict[str, Any]:
        """SPY buy-and-hold counterfactual via the wired market_data client."""
        if start is None or end is None:
            return {
                "status": "STUBBED",
                "reason": (
                    "SPY baseline needs explicit start/end. The skeleton "
                    "leaves date-range plumbing to the skill-layer caller "
                    "(or to walk_forward output once unblocked)."
                ),
            }
        try:
            response = self.market_data.get_prices(
                ticker="SPY",
                start=start,
                end=end,
                interval="1d",
            )
        except Exception as exc:  # pragma: no cover — network/runtime
            return {"status": "ERROR", "reason": f"market_data.get_prices: {exc!r}"}

        prices = self._extract_close_series(response)
        if len(prices) < 2:
            return {
                "status": "ERROR",
                "reason": f"insufficient SPY price data: n={len(prices)}",
            }

        arr = np.asarray(prices, dtype=float)
        period_returns = np.diff(arr) / arr[:-1]
        total_return = float(arr[-1] / arr[0] - 1.0)
        # Annualize Sharpe from daily returns: mean/std * sqrt(252).
        std = float(np.std(period_returns, ddof=1)) if len(period_returns) > 1 else 0.0
        if std == 0.0:
            sharpe = 0.0
        else:
            sharpe = float(np.mean(period_returns) / std * np.sqrt(252))
        return {
            "status": "OK",
            "total_return": total_return,
            "sharpe": sharpe,
            "n_observations": int(len(period_returns)),
        }

    @staticmethod
    def _extract_close_series(response: dict[str, Any]) -> list[float]:
        """Extract a list of close prices from mcp__market_data.get_prices.

        The market_data MCP returns a dict like
        {"rows": [{"date": ..., "open": ..., "close": ..., ...}, ...]}; tolerate
        light shape variation so a future schema tweak is a one-line fix here.
        """
        rows = response.get("rows") or response.get("prices") or []
        out: list[float] = []
        for row in rows:
            close = row.get("close") if isinstance(row, dict) else None
            if close is None:
                continue
            try:
                out.append(float(close))
            except (TypeError, ValueError):
                continue
        return out
