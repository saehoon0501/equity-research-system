# Gap Analysis — survival-gate (2026-05-29)

`/kiro-validate-gap`. Two parallel codebase sweeps (reuse surface + integration/current-state surface), key claims spot-verified. **Headline: the decision *core* is greenfield-but-cleanly-buildable and inner-ring-testable *now*; every *live data dependency* (account readout, halt status, order+SL placement, the daemon caller) is NOT built.** This maps exactly onto P14 (inner ring first): build + unit-test the pure decision core against a synthetic account-state + pinned params, decoupled from the unbuilt broker/daemon.

## Current State (what exists)

**Reusable (verified):**
- **`src/supervisor/conviction_rollup.py::check_sleeve_cap(...)`** (line 234) — pure; canonical caps `{core_fundamental:80, thematic_growth:25, speculative_optionality:8}`; returns status ∈ {PASS, PASS_SOFT_WARNING, VIOLATION} + headroom. **Direct reuse for R3.**
- **HG-validator pattern** (`src/eval/gates/`): pure fn + frozen result dataclass + CLI; registered in `_outcome.py` `GATE_IDS` + `_registry.py` runner. `GATE_IDS` shows HG-35/36/38 taken → **HG-37 is free** for the survival-gate's own envelope validator (P11).
- **Parameter pinning** (verified): `parameters` table (mig 004, `namespace.key` CHECK) → `parameters_active` view → `run_parameters_snapshot` (mig 034) pinned by value (P2). Namespaced seeds exist (033 research_company, 038 tactical, 039 flow) — **the template for a new `survival.*` seed migration.**
- **Append-only ledger** (mig 003 `counterfactual_ledger` + `counterfactual_ledger_guard()` trigger) — the gold-standard pattern for the gate's event log.
- **`src/eval/gates/sizing_math.py` (HG-25)** — reuse the *shape* (pure validator + epsilon + result dataclass), not the logic.

**Greenfield (no existing code):** margin-level / liquidation-distance math, the blocking decision, safe-mode state machine, kill switch, halt detection. Confirmed by grep — no risk/margin/kill-switch/safe-mode implementation exists.

**Misframing to correct (from the sweep):** the survival-gate is **NOT** a research-pipeline (PM-envelope) validator wired into `REGISTRY[pm_envelope]`. It is a **real-time pre-order gate in the execution path** (called by `execution-daemon` before each order). Its HG-37 validator only shape-checks the gate's *own emitted decision envelope* (P11) — decoupled from the `/research-company` validation pipeline.

## Requirement-to-Asset Map

| Req | Asset / verdict | Gap tag |
|---|---|---|
| R1 account margin model | margin math **NEW**; account readout from broker (specced, **NOT-BUILT**) | core buildable on synthetic input; live readout **Missing (broker)** |
| R2 blocking / lexicographic / tighten-only | decision core **NEW** | buildable now |
| R3 sleeve / funding cap | **REUSE** `check_sleeve_cap()` | — |
| R4 size limit + **mandatory SL** | size check **NEW**; SL-attach on orders **NOT-BUILT** (broker Req 1) | gate-side check now; SL placement **Missing (broker)** |
| R5 entry eligibility | universe list source **Unknown**; screens (catalyst-scout + quality-gate) are **prose memos**, need consumable predicates | **Unknown (universe list)** + **Constraint (screen extraction)** |
| R6 flat-before-close invariant + verify | invariant + "am-I-flat?" verify **NEW**; flatten *action* = `execution-daemon` (**NOT-BUILT, no spec**) | verify buildable now; action **Missing (daemon)** |
| R7 halt-while-holding (alert-only) | response logic **NEW**; **halt-detection source has no current feed** | **Missing (halt source) — critical** |
| R8 safe-mode + anomaly queue | state machine **NEW**; event table = new (mig-003 append-only pattern) | buildable now (schema + logic) |
| R9 kill switch | logic + monotonic state **NEW** | buildable now |
| R10 pinned params | **EXTEND** `parameters` (`survival.*` namespace) + snapshot | buildable now |
| R11 determinism / inner-ring | matches P14 + eval-gates convention | buildable now |

## Implementation Approach Options

**Option A — everything in `src/eval/gates/`** (the sweep's lean). All gate logic + validator in one module under the existing gates dir. ✅ one place, minimal new dirs. ❌ conflates a *decision core* (margin math, state machine) with the *validators* that dir holds; `src/eval/gates/` is for shape-checks, not stateful decision cores.

**Option B — decision core in new `src/survival/`, HG-37 validator in `src/eval/gates/` (recommended).** Mirrors the established split: `src/supervisor/conviction_rollup.py` (core) vs `src/eval/gates/sizing_math.py` (validator). Core takes a synthetic `AccountState` + pinned `SurvivalParameters` → `SurvivalDecision`; the HG-37 validator shape-checks that decision envelope. ✅ clean separation, inner-ring-isolatable, matches repo convention. ❌ one new dir.

**Option C — hybrid / phased (recommended *for sequencing*, composes with B).**
- **Phase 1 (unblocked, now):** build the pure decision core (Option B placement) + HG-37 validator + `survival.*` param seed + `survival_gate_events`/`survival_gate_state` schema; full inner-ring unit tests against synthetic `AccountState` + params — **no broker, no daemon, no live DB.** This is the P14-correct first deliverable and is *not* blocked by the unbuilt deps.
- **Phase 2 (blocked):** wire live account readout (margin level, positions), order+SL placement, the daemon invocation, and the halt-detection source.

## Effort & Risk

- **Phase 1 (core + validator + params + schema + inner-ring tests):** **M (3–7 days)**, **Risk Medium** — established reuse (`check_sleeve_cap`, HG/param/append-only patterns) lowers it, but it's the highest-blast-radius node so the correctness bar is high; inner-ring testability is the mitigation.
- **Phase 2 (live wiring):** **L (1–2 weeks)**, **Risk High** — blocked on broker-cfd-adapter (requirements-only), execution-daemon (no spec), and the halt-detection gap.

## Recommendations for Design

- **Preferred: Option B placement + Option C phasing.** Build the inner ring first (P14): a pure `decide(account_state, proposed_order, survival_params) -> SurvivalDecision` core in `src/survival/`, unit-tested in isolation; HG-37 envelope validator in `src/eval/gates/survival_gate_check.py`; `survival.*` param seed migration; new append-only `survival_gate_events` + monotonic `survival_gate_state` tables (new, *not* `system_errors` — trading anomalies ≠ system failures).
- **Key design decision — the `AccountState` seam.** Define the gate's account-state input contract (equity, aggregate used margin, margin level, open positions, per-name trading-status) **jointly with broker-cfd-adapter's `get_account_assets` / `get_positions` shapes** so Phase-2 wiring is a clean adapter, not a refactor. This seam is what lets Phase 1 proceed against a synthetic struct.
- **Correct the placement framing:** standalone execution-path gate, *not* a `REGISTRY[pm_envelope]` research-pipeline validator.

### Research Needed (carry to design)
1. **Halt-detection source [CRITICAL]** — no feed exposes per-instrument intraday halt. Decide: a broker-adapter trading-status field / Polygon news-halt / an SEC/UTP halt feed / accept as an external dependency. R7 cannot wire live without this.
2. **Screen extraction** — catalyst-scout (event proximity) + quality-gate (Altman-Z / F-score) are agent *prose memos*. R5 needs consumable predicates (`has_imminent_catalyst(ticker)->bool`, `fails_quality_gate(ticker)->bool`). Quality-gate math is deterministic → extractable to a pure fn; or read the latest memo's fields from DB.
3. **Universe-list source** — R5.1 needs the S&P 500 membership set (∩ Gate-441 from broker `/tradfi/symbols`). Where is S&P 500 membership sourced/maintained?
4. **Event/state schema choice** — confirm new `survival_gate_events` (append-only, mig-003 pattern) + `survival_gate_state` (safe-mode grade + kill-switch, monotonic transitions) vs extending `system_errors`. Lean new tables.

### Sequencing (blocking summary)
Phase 1 (core) is **unblocked** — build + inner-ring-test now. Live cutover (Phase 2) is **blocked** on: broker-cfd-adapter (design+build), execution-daemon (spec first), halt-detection source. Recommend defining the `AccountState` contract with broker-cfd-adapter's design so the two specs converge on one shape.

---

## Design Synthesis (2026-05-29)

`/kiro-spec-design` adopted **Option B placement + Option C phasing**. Six synthesis decisions (three reshaped the core interface — advisor-flagged):

1. **Two entry points, not one (structural).** `admit(order,…)` (the veto) **and** `assess(state,…)` (a standing monitor that runs every tick with *no order*). Rationale: margin-breach-while-idle, closure-imminence, and held-name halts must fire when the book is sitting still — exactly when a gap moves against you. A single order-triggered `decide(…)` would have dropped all three.
2. **Op-state read fresh, never pinned (structural).** Params pin by value (P2); `OperationalState` (kill-switch / safe-mode) is read fresh + authoritative per call. The freshness guarantee is named: a single-threaded daemon eval loop serializes the op-state read-modify-write so a just-engaged kill switch can't be raced by an in-flight order (DB-level guard is the concurrency fallback / revalidation trigger).
3. **Fail toward minimum exposure, not monolithic reject (structural).** Opens (BUY) fail→REJECT; exits (TRIM/SELL) + `assess` reduces fail→ALLOW/flatten. A naive "reject everything" would reject the flatten that gets you out — catastrophic. Encoded as the opens-vs-exits catastrophe-guard test.
4. **Veto-only.** `admit` returns REJECT + an *advisory* max; never a mutated order (the daemon resizes + re-submits) — keeps sizing the daemon's boundary, avoids a re-gate loop.
5. **Funding-cap = capitalization-cadence.** `check_sleeve_cap` reuse is the funded-balance-≤8%-of-book check; it rarely binds per-order. The per-order hot path is margin-distance + size + SL — framed so the walk doesn't imply an every-order tier computation.
6. **Clock as input; Phase-2 out-of-scope-for-tasks.** Closure-imminence + session state are `ClockState` inputs (the pure core can't read the clock). Phase-2 wiring (broker `AccountState`, halt source, daemon, op-state persistence, screen-predicate extraction) is explicitly excluded from this spec's task surface so `/kiro-spec-tasks` doesn't generate against unbuilt deps.

**Build-vs-adopt:** adopt `check_sleeve_cap` + HG-validator + pinned-param + append-only-ledger patterns; build new the two-entry-point core, the HG-37 validator, the `survival.*` seed, and the `survival_gate_state` + `survival_gate_events` tables. Inner ring runs against a synthetic `AccountState` on `DEFAULTS`, independent of the unbuilt broker/daemon and the §14.11 fork.

---

## Seam reconciliation — broker-cfd-adapter design `72020a0` (2026-05-29)

`git pull` brought broker-cfd-adapter to **requirements-approved + design-generated** (commit `72020a0`). The `AccountState`/`Position` seam (research item #4 + design Revalidation Trigger) is now checkable against a concrete contract. Result: **seam is clean and the boundary is explicitly corroborated** — no requirements/design change to survival-gate; three reconciliation notes folded into `design.md`.

**Boundary corroboration (broker design states it explicitly):**
- Broker *Non-Goals*: "Survival/liquidation-distance computation, sleeve-cap enforcement, kill-switch **state** ownership (→ `survival-gate`)" and "the kill-switch & survival-gate-clearance **state** (owned by `survival-gate`; consumed here as boolean inputs)." → exact P7 upstream-gate relationship: survival-gate's `admit` clearance is a **boolean input** to broker's live-send validation chain (broker §8.3 "live-send clearances when live").
- Broker reports venue-authoritative readouts and does **not** self-compute PnL / liquidation distance / sizing — survival-gate owns that math. No overlap.

**Broker contract (as landed):**
- `Position`: position_id, symbol, direction, volume, **`avg_open_price`**, used_margin, unrealized_pnl. (No halt field.)
- `AccountAssets`: equity, used_margin, free_margin, margin_level, balance, stop_out_level (no derived liquidation distance).
- mt5-account: leverage, stop_out_level, **status**. Per-symbol `leverage` is a cached `SymbolInfo` attribute; exposure controlled by volume, **no per-order leverage param** (`used_margin = notional ÷ leverage`) — consistent with survival-gate R1/§16 premises (fixed per-instrument leverage, cross-margin, stop-out ≤ 50%). No NBP change.

**Reconciliation items folded into design.md:**
1. **Field rename** `open_price` → `avg_open_price` (match broker `Position`). Passthrough field; not used by the decision core; no `tasks.md` impact.
2. **`AccountState` is composed** by the Phase-2 adapter from two broker calls (`get_account_assets` + `get_positions`); `activated` ← mt5-account `status`.
3. **`stop_out_level` dual source**: venue readout (broker) now exists alongside the pinned `survival.stop_out_level_pct` → gate uses the **tighter** (P7 tighten-only).

**Unchanged critical gap (R7 halt source):** broker `Position` carries **no `trading_status`/halt flag**; it surfaces only post-hoc `close_reason: forced_liquidation` via `get_history`. So broker is **confirmed NOT the halt-detection source**. R7 live wiring still needs a separate per-instrument halt feed (Polygon news-halt / SEC-UTP / a broker requirement addition). The gate's missing-`trading_status`→HALTED conservative default keeps Phase-1 safe-by-default; live R7 stays Phase-2-blocked.

---

## R7 reframe — real-time halt detection OUT of boundary (2026-05-29)

**Operator decision (this session):** real-time per-instrument trading-halt detection is **out of survival-gate's boundary** — confirmed after `git pull` brought broker-cfd-adapter `c79738f` ("design-validation fixes + halt-detection boundary"), which states the broker is **not** a live halt source. No feed exists anywhere. R7 is reframed from the prior *alert-only halt-while-holding behavior* to an **accepted-residual / out-of-boundary** requirement.

**Removed from survival-gate (all of it):** `Position.trading_status`; the `halt_freeze` binding constraint + the admit-walk halt step; the `assess` HALT branch; `FLATTEN_AT_REOPEN`; the `halt_detected` event_type; the `missing-trading-status → HALTED` conservative default (incoherent once no feed exists — it would freeze everything). **Kept:** post-hoc `forced_liquidation` (broker `get_history` `close_reason`) → event log; the **ex-ante entry-exclusion stage** (R5) + S&P 500 ∩ Gate-441 universe (base-rate reduction, entry-time screening — *not* real-time halt sensing).

**Where the intraday-halt/reopen residual is actually bounded (honest attribution):** while halted, price is frozen → no exposure change; the **reopen gap** is caught by `assess`'s continuous account-level margin monitor (next tick → safe-mode/flatten escalation), bounded by the **venue account-level stop-out + §16 funding cap**. **NOT** the per-order stop-loss (gaps through it) and **NOT** R6 flat-before-closure (closure-keyed — blind to a mid-session halt that reopens before close).

**Accepted residual (named, eyes-open) vs. the prior alert-only choice — what is lost:** (1) the halt-time **alert**; (2) the account-wide **new-entry freeze while holding an un-flattenable halted name** — so the system may keep adding leverage elsewhere while unknowingly holding a halted position, and the reopen gap then hits a more-levered book. This is the real widening; it is accepted for the paper phase.

### ⚠️ Cross-spec conflict to resolve (broker-cfd-adapter `c79738f` — FORK LANE, not edited here)

The broker commit's wording **over-assigns** survival-gate and is now stale against this decision:
1. Broker *Out of Boundary*: "Intraday-halt and gap-proximity sight is **owned by survival-gate's `gap-risk-veto-filter`**." — survival-gate owns only the **ex-ante** entry-exclusion (gap-*proximity* base-rate screen); it does **not** own **real-time intraday-halt sight** of a held position (that's now out of boundary for everyone — no feed). The broker conflates ex-ante exclusion with real-time detection.
2. Broker: "the `missing-trading-status → HALTED` fail-safe is a **consumer** rule (survival-gate / execution-daemon)." — survival-gate has **removed** this rule (incoherent with no feed). Whether the daemon keeps any analogue is the daemon spec's call (fork lane).

**Recommended broker-side fix (for the fork):** scope survival-gate's ownership to *ex-ante gap-risk entry exclusion* only; state that *real-time held-position halt detection is out of boundary for both broker and survival-gate (no feed)*; drop the survival-gate attribution of `missing→HALTED`. Survival-gate's own boundary (requirements R7 / design Out-of-Boundary) now states this authoritatively from its side.
