# Regime Sidecar (S0)

Critical-path component #1 in v0.1. Implements the L1 / S0 regime sidecar
per v3 spec [§4.1 + §3.3 + §7.5](../../docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md).

## What this is

A daily-cadence Python module that classifies the macro regime across 6
Tier-1 dimensions, computes BOCPD change-point probabilities per dimension,
and writes the results to Postgres (`regime_classification_history`,
migration `005_v3_regime.sql`).

## Dimensions

| ID | Name | Source | States |
|---|---|---|---|
| 1 | `credit_ebp` | Fed CSV (Gilchrist-Zakrajšek) — multi-URL fallback + daily local cache | benign / stressed / crisis |
| 2 | `cycle_2y3m_slope` | FRED `DGS2 − DGS3MO` (CMT slope; full Engstrom-Sharpe NTFS deferred) | expansion / late_cycle / recession |
| 3 | `vol_vrp` | `VIX² − RV_22d` from FRED `VIXCLS` + `SP500` | benign / normal / elevated / crisis |
| 4 | `mp_liquidity` | FRED `WALCL`/`RESBALNS`/`RRPONTSYD`/`M2SL` z-composite | tight / neutral / easy |
| 5 | `dollar_dtwexbgs` | FRED `DTWEXBGS` 60-trading-day trend | strong / neutral / weak |
| 6 | `stock_bond_corr` | 60d `corr(SPX, -Δy10y)` (canonical FR bond proxy), Forbes-Rigobon corrected | negative / neutral / positive |

### Dim 2 — NTFS source decision

Section 3.3 spec line 64 lists the canonical NTFS source as "FRED zero-coupon
curve OR neartermforwardspread.com." The cleanest implementation requires
the Gürkaynak-Sack-Wright zero-coupon Treasury series (`THREEFY1`,
`THREEFY2`, …) with linear interpolation to the 6-quarter-ahead 3-month
forward.

**v0.1 chose: `cycle_2y3m_slope` (CMT slope), GSW NTFS deferred to v0.5+.**

Rationale:
- The GSW THREEFY series wiring + interpolation logic is non-trivial and
  has a separate validation surface (Engstrom-Sharpe replication) that
  warrants its own subagent pass.
- Renamed from `cycle_ntfs` so we do **not** claim Engstrom-Sharpe edge
  under a CMT proxy. The migration `005_v3_regime.sql` CHECK constraint
  + `DIMENSION_REGISTRY` reflect the new name.
- v0.5+ work item: wire FRED `THREEFY1`/`THREEFY2` (or fetch
  neartermforwardspread.com CSV), add the interpolation step, restore the
  `cycle_ntfs` name with the proper validation_depth tag.

## Method overlays applied

- **BOCPD** (Adams-MacKay 2007) — applied to every dimension under an
  operator-locked **dual-signal architecture**. Both signals are
  first-class outputs of this module, persisted in
  `regime_classification_history`, indexed for query, and visible through
  the `regime_state` view (per migration 020):

  | Signal | Posterior summary | Role |
  |---|---|---|
  | `bocpd_change_probability` | canonical Adams-MacKay marginal `P(r_t = 0 \| x_{1:t})` | **academic / audit traceability** — preserves provenance to the canonical reference; structurally pinned near the hazard rate (~0.004) in steady state. Does NOT systematically cross v3 §4.1 firing thresholds. |
  | `bocpd_short_run_mass`     | cumulative posterior `P(r_t < 10 \| x_{1:t})`           | **PRIMARY firing signal** — drives M-2 / M-3 firing per v3 §4.1 thresholds (>0.7 sustained 2+d → M-2; >0.95 single-day → M-3). What actually crosses the operational thresholds on regime shifts. |

  Rationale (operator-locked decision): the canonical marginal is the
  right *academic* signal but rarely trips firing thresholds because the
  prior P(r_t=0)=h and the posterior P(r_t=0|x_{1:t}) share the same
  predictive geometry under constant hazard — the ratio
  P(r_t=0)/P(r_t>0) is structurally pinned near h/(1-h) when one
  run-length dominates the posterior. The cumulative short-run mass is
  what crosses operational thresholds. Architecture stores both:
  short_run_mass drives firing, canonical marginal preserves academic
  provenance.

  Downstream firing consumers (L4 cut_evaluator Mode C; refresh_emitter
  M-2/M-3 paths) MUST source `regime_state.bocpd_short_run_mass`. Audit
  emissions (verbatim posterior trace; provenance JSON) reference
  `bocpd_change_probability`.
- **Forbes-Rigobon** vol-conditional correlation correction — applied
  *only* to dimension 6. Bond return proxy is now `-Δy10` (canonical
  first-difference of yield), not `-Δlog(y10)`.
- **Surprises (actual − consensus)** — deferred to v0.5+ for **all three**
  affected dimensions (dim 1 credit, dim 2 cycle, dim 4 monetary). Each
  dimension's `raw_inputs` carries an explicit
  `surprise_overlay_status: "deferred_to_v0.5"` annotation that downstream
  consumers can surface in `execution_context.risk_flags`.
- **MSGARCH** (R) — deferred to v0.5+.

Equal-weight (1/6) headline composition at v0.1; pseudo-BMA+ shadow weights
deferred to v0.5+.

## Cold-start boundary semantics

Per v3 §7.5 (spec line 824): launch day is day 1; first 90 days carry the
flag; clears on day 91. v0.1 implementation uses pandas `bdate_range`
(Mon-Fri business days; NYSE holiday-list integration deferred to v0.5+
via `pandas-market-calendars`). The 5/7 calendar approximation has been
retired — it drifted by ~3 days on the 90-trading-day window.

Boundary tests at day 89 / 90 / 91 are wired in
`tests/test_regime_sidecar.py::test_cold_start_boundary_day_89_90_91`.

## EBP source resilience

Dim 1 is the highest-edge dimension per v3 §4.1, and the canonical Fed
CSV URL has been an operational fragility (no cache, no fallback, no test).
v0.1 hardens this:

1. **Multi-URL probe**: tries the canonical
   `econresdata/notes/feds-notes/2016/files/ebp_csv.csv` first; falls
   through to `econres/notes/feds-notes/files/ebp_csv.csv` on failure.
2. **Daily local cache**: every successful fetch writes
   `cache/ebp_YYYYMMDD.csv` (under repo root). On total network failure,
   `_fetch_ebp_series` falls back to the most-recent cached snapshot.
3. **Validation-depth flag**: cache fallback stamps
   `validation_depth = "STALE_CACHE"` so the daily monitor / sizing
   consumer can surface in `execution_context.risk_flags`.
4. **Test coverage**: `test_dim1_credit_ebp_classifies_states` +
   `test_dim1_credit_ebp_stale_cache_path_tags_validation_depth`.

## Q3 firing thresholds (consumer-side)

The sidecar **writes** BOCPD probabilities (both signals); it does not
enforce M-2/M-3 materiality firing. Downstream consumers (P8 daily
monitor) read the `regime_state` view and apply the v3 §4.1 thresholds
to **`bocpd_short_run_mass`** (per operator-locked dual-signal
architecture; see Method overlays above):

- 1 dim short-run-mass > 0.7 sustained 2+ days → M-2
- 2+ dims short-run-mass > 0.7 sustained 2+ days → M-3
- Any dim short-run-mass > 0.95 single-day → M-3 + alert

The canonical `bocpd_change_probability` is consumed by audit-trail and
provenance flows (verbatim posterior emission), NOT by firing logic.

## Required env vars

Loaded from repo-root `.env` via `python-dotenv` (same pattern as
`src/mcp/postgres/server.py`):

- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_DB`
- `POSTGRES_HOST` (default `127.0.0.1`)
- `POSTGRES_PORT` (default `5432`)
- `FRED_API_KEY` — register a free key at
  https://fredaccountmanager.research.stlouisfed.org/apikey

## Usage

### Daily run (production cron)

```
python -m src.shared.regime_sidecar.cli --date 2026-04-29
```

Writes 6 rows (one per dimension) to `regime_classification_history` with
`cold_start` resolved automatically against the launch date (first row in
the table). Idempotent — re-running is a no-op via the (date, dim_id)
unique constraint.

### Dry-run (no DB write)

```
python -m src.shared.regime_sidecar.cli --date 2026-04-29 --dry-run
```

Prints results JSON to stdout. Useful for spot-checking after threshold
tuning.

### Cold-start backfill (§7.5)

First-time launch only: pull T-12mo history and write rows with
`cold_start=true`:

```
python -m src.shared.regime_sidecar.cli --cold-start --date 2026-04-29
```

Custom horizon:

```
python -m src.shared.regime_sidecar.cli --cold-start --months 18 --date 2026-04-29
```

Backfill is idempotent (ON CONFLICT DO NOTHING). The 90-trading-day
cold-start window is resolved at *write time* against the launch date;
backfilled rows for dates earlier than the launch date always carry
`cold_start=true`.

## Output schema

One row per (date, dimension_id) tuple in `regime_classification_history`
(see `db/migrations/005_v3_regime.sql`):

```sql
classification_date      DATE
dimension_id             SMALLINT (1..6)
dimension_name           TEXT
state_probabilities      JSONB        -- {"benign": 1.0, "stressed": 0.0, ...}
headline_state           TEXT         -- argmax of state_probabilities
bocpd_change_probability NUMERIC      -- canonical Adams-MacKay marginal P(r_t=0|x_{1:t}); academic / audit
bocpd_short_run_mass     NUMERIC      -- cumulative posterior P(r_t<10|x_{1:t}); firing signal (migration 020)
raw_inputs               JSONB        -- replay-quality audit data
cold_start               BOOLEAN
history_length_days      INTEGER
rule_engine_version      TEXT         -- "regime_sidecar.v0.1.1" (dual-signal mode)
parameters_version       UUID         -- FK to parameters table (optional)
```

The latest row per dimension is exposed via the `regime_state` view.

## State probabilities at v0.1

Every dimension currently produces a *point* classification with
`P(headline_state) = 1.0` and `P(other_states) = 0.0`. This satisfies the
v3 spec's "probability distribution per state" contract while deferring
soft assignments to v0.5+ (when MSGARCH-style smoothing arrives). The
JSONB shape is forward-compatible — only the numerical values change.

## Cold-start procedure (§7.5)

1. On first launch, run `--cold-start` to seed T-12mo of history.
2. The first 90 trading days post-launch carry `cold_start=true`. The
   `idx_regime_history_cold_start` partial index supports diagnostic
   queries.
3. During cold-start, downstream consumers (sizing, recommendation
   emitter) attach a `cold_start_caveat` annotation to
   `execution_context.risk_flags` per v3 §4.6.
4. After 90 trading days, the flag clears automatically (resolved at
   write time, not retroactively).

## Files

- `__init__.py` — package init.
- `types.py` — `DimensionResult` dataclass.
- `bocpd.py` — Adams-MacKay 2007 implementation.
- `forbes_rigobon.py` — vol-conditional correlation correction.
- `fred_client.py` — minimal FRED HTTP client.
- `dimensions/dim{1..6}_*.py` — one fetcher per dimension.
- `classifier.py` — orchestrates the 6 fetchers.
- `persistence.py` — Postgres writer (psycopg3).
- `cli.py` — entry point.

## Tests

`tests/test_regime_sidecar.py` covers:

- BOCPD on a synthetic step-shift series (peak at the shift).
- Forbes-Rigobon math (degenerate cases + Forbes-Rigobon 2002 worked example).
- Each dimension's `compute()` with mocked HTTP/FRED responses.
- `run_daily_classification` end-to-end with mocks.
- `write_classifications` schema validity (mocked psycopg connection).
