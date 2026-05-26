---
description: Quarterly parameter recalibration per v3 §1.5 + §6.3 — system proposes, operator approves. Runs against rolling 90-day counterfactual ledger. v0.1 surface = read-only summary + override-pattern suggest; full proposal generation deferred to v0.5+.
argument-hint: [summary [--namespace <ns>] | suggest [--since-days N] | propose]
---

# /parameters-review

Cadence-driven parameter recalibration per v3 spec Section 1.5 + Section 5.4 + Section 6.3. **v0.1 STUB** — surfaces read-only visibility into the `parameters` table + `operator_overrides` patterns. Full proposal generation lands at v0.5+ once the rolling 90-day counterfactual ledger has accumulated enough signal.

## Subcommands

`summary` (default) — group `parameters` rows by `parameter_key`; surface current + prior `value`. Useful for spotting recently-changed parameters operator may want to roll back.

`suggest` — rank `parameter_key` by `operator_overrides` frequency over the last N days. Highly-overridden keys are candidates for recalibration.

`propose` — STUB. Refuses to generate proposals at v0.1; points to v0.5+ scope. Per spec the workflow requires (i) 90-day counterfactual ledger with outcome stratification, (ii) parameter-vs-outcome attribution model, (iii) operator approve/modify/reject UI. None is in v0.1 scope.

## Procedure

### 1. Pre-flight checks

- `mcp__postgres` connected. The `parameters` and `operator_overrides` tables both live there.
- `psycopg` (v3) or `psycopg2` available in the CLI environment.

### 2. Invoke the CLI

```bash
python -m src.parameters_review.cli summary
python -m src.parameters_review.cli summary --namespace mode_classifier
python -m src.parameters_review.cli suggest --since-days 90
python -m src.parameters_review.cli propose
```

The CLI prints JSON to stdout. Render to operator unchanged.

Exit code mapping:
- `0` — success
- `1` — DB / IO error
- `2` — usage error
- `5` — environment / driver missing

### 3. v0.1 operator workflow

Until v0.5+:
1. Run `summary` (optionally with `--namespace`) at quarterly cadence.
2. Run `suggest --since-days 90` to identify keys most frequently overridden.
3. Manually scan the rationale + change-rationale text for cohort patterns.
4. Apply approved parameter changes via direct `mcp__postgres__execute` insert into `parameters` table; populate `change_rationale` + `approved_by` per the v3 §1.5 contract.

## What `/parameters-review` does NOT do at v0.1

- **No automatic recalibration.** Per spec the system proposes, the operator approves; v0.1 stops at "operator scans" and "operator manually inserts the new row".
- **No counterfactual-ledger attribution.** The link from `recommendation_outcomes` / `override_outcomes` back to the parameter that produced the miss is v0.5+ scope.
- **No writes.** Read-only. Parameter changes are committed by direct insert into `parameters` until v0.5+ wraps the workflow.

## HIGH-4 consensus 2026-05-16 — counterfactual_ledger schema change

Per `docs/high-4-enum-drift-consensus.md` Consensus Item #5, the `counterfactual_ledger` now writes 4 rows per `/research-company` run (one per window: `90d / 1y / 3y / 5y`) with the canonical row-level signal `vs_sector_etf_return_pct` and bin info preserved as the `summary_code` column. When `propose` lands at v0.5+, the calibration aggregation should:

1. **Read `vs_sector_etf_return_pct`** as the primary calibration signal (uniform raw active return vs sector ETF; see consensus doc §3 Consensus Item #5 + §9 sources [⁷]).
2. **Stratify by `summary_code`** for bin-conditional postmortem queries — same uniform metric, different interpretation per bin (BUY = good call; HOLD = opportunity cost; SELL = sell regret; TRIM = trim regret). See consensus doc §3 postmortem-query interpretation map.
3. **Aggregate Information Ratio across rows** per Goodwin 1998 — the IR's denominator (tracking error / std-dev of active return) wants a multi-decision time series and is statistically valid at the aggregate layer (not per-row). This is the canonical place to apply risk-adjustment; row-level math stays raw alpha per CFA single-name convention.
4. **Suggested SQL skeleton** (v0.5+ proposal generator):

   ```sql
   SELECT
     summary_code,
     window,
     COUNT(*)                                    AS n_decisions,
     AVG(vs_sector_etf_return_pct)               AS mean_active_return,
     STDDEV_SAMP(vs_sector_etf_return_pct)       AS active_return_stdev,
     AVG(vs_sector_etf_return_pct) /
       NULLIF(STDDEV_SAMP(vs_sector_etf_return_pct), 0) AS information_ratio
   FROM counterfactual_ledger
   WHERE summary_code IS NOT NULL
     AND measurement_date IS NOT NULL
     AND measurement_date >= CURRENT_DATE - INTERVAL '5 years'
   GROUP BY summary_code, window;
   ```

   Treat the resulting `information_ratio` per `(summary_code, window)` cell as the calibration-history input for parameter recalibration proposals.

5. **Legacy column note.** Migration 003's `system_return` / `baseline_return` / `delta_vs_baseline` columns are preserved for back-compat with pre-HIGH-4 rows but should NOT be consumed by new aggregation logic — they used the deprecated 4-baseline counterfactual {SPY, equal_weight_watchlist, sector_matched, 60_40} which is replaced by `vs_sector_etf_return_pct` (sector-ETF-only, Brinson-Fachler convention).

## Examples

Quarterly summary scan:
```
/parameters-review summary
```

Filter to one namespace:
```
/parameters-review summary --namespace bocpd
```

Override-pattern surface:
```
/parameters-review suggest --since-days 90
```

## Reference

- v3 spec: `docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md` Section 1.5 (parameter governance), Section 5.4 (slash commands), Section 6.3 (calibration cadence).
- Schema: `db/migrations/004_v3_parameters.sql`, `db/migrations/013_v3_calibration.sql` (operator_overrides).
- Module: `src/parameters_review/` (cli.py — STUB at v0.1).
- Operator-reference deferred-status: `docs/superpowers/operator-reference.md` §1.5.
