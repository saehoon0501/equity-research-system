# p5_watchlist

P5 phase: append research-approved name to the watchlist after a P4 ADD verdict.

## Spec references

- `docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md`
  - Section 2.1 (funnel composition; watchlist vs portfolio)
  - Section 2.2 (mode-specific conviction thresholds: B≥0.7, B'≥0.6, C≥0.5)
  - Section 4.6 (downstream consumption — P5 row anchors recommendation emitter)
  - Section 4.8 (Macro-Regime sensitivity tagging at P5)
  - Section 6 Q5 (anchor-drift HMAC contract)
- `db/migrations/007_v3_watchlist_positions.sql`

## Surface

- `WatchlistAddInput` — typed input bundle (P4 + Stage 2 mode classifier outputs)
- `WatchlistAddOutcome` — typed output (ticker + HMAC sigs + DB write status)
- `add_to_watchlist(inp, conn=, hmac_key=)` — pure-Python orchestrator
- `derive_conviction_threshold(mode, override=)` — Section 2.2 mode default
- `derive_regime_sensitivity(macro_regime_style_output)` — Section 4.8 tag

## CLI

```sh
python -m src.p5_watchlist.cli add --debate-result /tmp/p4_NVDA.json
python -m src.p5_watchlist.cli add --from-orchestrator < p4.json   # piped
python -m src.p5_watchlist.cli add --debate-result ... --dry-run    # HMAC only
```

## HMAC integration

P5 calls `src/watchlist/hmac_producer.sign_watchlist_row` to sign the two
immutable anchor JSONB columns. The verifier
(`src/anchor_drift/hmac_verify.py`) uses the same canonical-JSON discipline
under `WATCHLIST_HMAC_SECRET`. Watchlist HMACs use a SEPARATE key scope
from the audit chain (`AUDIT_HMAC_KEY`) so secret rotation across modules
is independent.

## Conviction threshold table (Section 2.2)

| Mode | Default threshold |
|---|---|
| B  | 0.70 |
| B' | 0.60 |
| C  | 0.50 |

Per-name override allowed via `WatchlistAddInput.conviction_threshold_override`.

## Failure modes

- `pm_supervisor_decision != 'ADD'` → ValueError (P5 only fires on ADD; WATCH/PASS routes diverge).
- Missing `WATCHLIST_HMAC_SECRET` env → `WatchlistHmacError` from the producer.
- Invalid mode / quality flag → ValueError (CHECK constraints enforced at DB anyway).
