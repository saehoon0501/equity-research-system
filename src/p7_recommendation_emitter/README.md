# p7_recommendation_emitter

Section 4.6 critical-path output module — produces the operator-facing
`execution_recommendations` row + chained `audit_provenance` audit log.

## Spec references

- `docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md`
  - Section 2.1 (funnel composition; P7 = entry execution → recommendation output)
  - Section 4.6 Q1 (full execution_recommendation schema)
  - Section 4.6 PB#2 (sizing v0.1 — mode-static + 3 hard overlays)
  - Section 4.6 Phase 4 Q2 (conviction rollup HIGH/MEDIUM/LOW)
  - Section 4.6 Phase 4 Q7 (conviction hysteresis 2-cycle persistence + flip-frequency escalation)
  - Section 4.6 Q3 (trigger logic — mode cadence + materiality interrupts)
  - Section 5 Q1 (audit-chain HMAC lock)
  - Section 7 Q4 (layered drill-down)
- `db/migrations/008_v3_recommendations.sql`

## Sub-modules

| File | Responsibility |
|---|---|
| `sizing.py` | Mode-static (B/B'/C) + 3 hard overlays (cash / drawdown / vol) |
| `conviction_rollup.py` | Deterministic Phase 4 Q2 HIGH/MEDIUM/LOW rollup |
| `hysteresis.py` | 2-cycle persistence + flip-frequency M-2 escalation |
| `execution_context.py` | Section 4.6 Q1 execution_context envelope assembly |
| `trigger_logic.py` | Mode cadence floor + materiality-interrupt metadata |
| `emitter.py` | Top-level orchestrator + HMAC sign + DB write |
| `cli.py` | `python -m src.p7_recommendation_emitter.cli emit ...` |

## Sizing overlays (Section 4.6 PB#2)

| Mode | Initial | Max |
|---|---|---|
| B  | 3% | 8% |
| B' | 2% | 5% |
| C  | 1% | 3% |

Hard overlays (each returns its own `multiplier` + `reason`):

1. **Cash constraint** — `min(mode_band, available_cash_pct)`. Multiplier
   applies to `initial_pct` only; if cash binds → `funding_required=true`.
2. **Drawdown auto-tighten** — if portfolio underperformance vs benchmark
   exceeds (B/S&P 5pp, B'/QQQ 7pp, C/IWO 10pp) → `× 0.5` on initial AND max.
3. **S0 vol-elevated** — if S0 vol-dimension z-score > +1σ → `× 0.7` on
   initial AND max.

`net_multiplier` = product of all three (computed on the initial path).

## Conviction rollup (Phase 4 Q2)

- **HIGH** = `≥4/5 debate AND 0 kills AND ≥2 SURVIVOR matches in top-3 AND ≤1 anchor-drift channel`
- **MEDIUM** = ANY ONE of `{3/5 debate, 1 kill, mixed counterfactual, ≥2 anchor-drift channels}`
- **LOW** = ANY ONE of `{<3/5 debate, ≥2 kills, ≥2 NON-SURVIVOR matches}`

Precedence resolved (spec ambiguity): LOW > HIGH > MEDIUM > fallback MEDIUM.
`mode_certainty` is a separate annotation (not a conviction determinant).

## Hysteresis (Phase 4 Q7)

- 2 consecutive cadence cycles required for any transition
- `conviction_flip_count_30d` tracked
- > 3 flips in 30 days → auto-demote to MEDIUM + freeze + M-2 escalation

## Trigger logic (Section 4.6 Q3)

| Mode | Cadence floor | Interrupts |
|---|---|---|
| B  | Weekly Monday open | M-2 / M-3 → immediate |
| B' | Every 3 days | M-2 / M-3 → immediate |
| C  | Daily | M-2 / M-3 → immediate |

`new_candidate` trigger fires immediately on P3+P4 funnel approval.

## HMAC integration

- **Key scope:** `AUDIT_HMAC_KEY` (env var). Distinct from `WATCHLIST_HMAC_SECRET`.
- **Canonical-payload contract:** `src/audit_trail/hmac_verify.canonical_payload_dict`
  (single source of truth — same scheme as p3_mechanical_scorer + audit_provenance).
- **Row signature:** computed over the canonical projection of the
  `execution_recommendations` row, EXCLUDING:
  - `audit_signature` itself
  - the conviction-pending state-machine columns (those mutate post-insert
    per migration 008's narrow UPDATE allowance)
- **Audit chain:** per-stage `audit_provenance` rows are chained via
  `parent_audit_id`; each row signed with `compute_signature_dict`.
  Verification by `audit_trail.verify_chain` succeeds round-trip.

## CLI

```sh
python -m src.p7_recommendation_emitter.cli emit \
  --ticker NVDA --mode B_prime --quality HIGH \
  --debate-add-count 4 --kills-fired 0 \
  --counterfactual SURVIVOR,SURVIVOR,SURVIVOR \
  --anchor-drift 0 \
  --primary BUY --pacing "DCA over 21 days" \
  --triggered-by new_candidate \
  --dry-run
```
