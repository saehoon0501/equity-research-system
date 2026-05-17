# p6_disposition

Pure-derivation step between P5 (watchlist add) and P7 (recommendation
emitter). Produces per-name disposition (mode-anchored primary horizon +
per-horizon signal + suggested pacing).

## Spec references

- `docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md`
  - Section 2.1 (funnel composition; P6 between P5 and P7)
  - Section 4.6 Q2 (multi-horizon disposition view)
  - Section 4.6 (suggested_pacing default per mode)

## Mode → primary horizon (Section 4.6 Q2)

| Mode | Primary horizon |
|---|---|
| B  | Long (12+mo) |
| B' | Mid (3-12mo) |
| C  | Short (≤3mo) |

## Default pacing per mode

| Mode | Pacing |
|---|---|
| B / B' | DCA over 21 days (ride-along default) |
| C | wait-for-arrival (Section 2.5 13G framework) |

## Surface

- `DispositionInput` — typed bundle (ticker + mode + quality + decision + held + conviction)
- `DispositionDecision` — typed output (primary horizon + horizon_signals + pacing + rationale)
- `determine_disposition(inp)` — pure function

## CLI

```sh
python -m src.p6_disposition.cli determine \
  --ticker NVDA --mode B_prime --quality HIGH --decision ADD
```

## Signal table (v0.1 — primary horizon only; non-primary defaults to HOLD)

| PMSupervisor | currently_held | primary signal |
|---|---|---|
| ADD | false | BUY |
| ADD | true | HOLD |
| WATCH | any | HOLD |
| PASS | true | SELL |
| PASS | false | HOLD |
