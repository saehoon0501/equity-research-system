# /resolve-outcomes

Resolves T+30 / T+90 / T+1y returns for every `execution_recommendations`
row whose horizon window has closed but `recommendation_outcomes` is
missing the corresponding column. Per v3 spec §6.4 + §8.1, this is the
load-bearing job for v0.5 calibration: without it the resolved-prediction
count stays at 0 and v0.5-active never trips.

## Argument

`[--as-of YYYY-MM-DD]` — optional cutoff date. Defaults to today (UTC).
`[--ticker T]` — optional restriction to a single ticker.
`[--dry-run]` — compute but don't write.

## Cadence

**Daily** (post-market close + 30 min) per spec §5.4 cadence-actions
table. The default operator routine is:

```
/resolve-outcomes        # populate any newly-closed windows
/calibration-status      # surface distance-to-v0.5-activation
```

This command is also re-runnable on demand for backfill (e.g., after a
historical run of memos lands in `execution_recommendations`).

## Procedure

1. Pre-flight: `mcp__postgres` connected; `mcp__market_data` (Polygon)
   reachable. The CLI exits 5 if either is missing.
2. Shell out:
   ```bash
   python -m src.outcomes.cli resolve [--as-of ...] [--ticker ...] [--dry-run]
   ```
3. Render the printed summary as-is. The CLI emits:
   ```
   candidates examined : <n>
   rows inserted       : <n>
   rows updated        : <n>
   horizons resolved   :
     T+30  : <n>
     T+90  : <n>
     T+1y  : <n>
   errors (...): ...
   ```

The override-outcome resolver runs alongside (calibration-circularity
defense, spec §6.0):

```bash
python -m src.outcomes.override_cli resolve [--as-of ...]
```

(Both writers are append/UPSERT-only; safe to invoke multiple times.)

## Failure modes

- **Polygon network/auth error** — propagates up; CLI exits non-zero. The
  resolver's per-row error guard catches per-recommendation failures so
  the batch continues, but provider auth/global failures halt the run.
- **Missing tables** (early v0.1) — psycopg surfaces the schema error.
  Apply the missing migration first.

## Reference

- v3 spec §6.4 (calibration upgrades), §8.1 (v0.5+ activation)
- Module: `src/outcomes/resolver.py`, `src/outcomes/cli.py`
- Companion: `/calibration-status`, `/parameters-review`
