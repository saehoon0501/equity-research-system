# Implementation Plan

> **Scope: Phase 1 only.** Per `design.md`, this builds the pure decision core + parameter contract + persistence schema + inner-ring tests, runnable against a synthetic account state on module defaults. **Phase-2 live wiring is out of scope** (broker account readout, daemon invocation, op-state persistence wiring, screen-predicate extraction, total-book-equity sourcing) — it is blocked on unbuilt specs and recorded as cross-spec/research items in `design.md` / `research.md`. The two daemon contracts (persist-then-act, `assess` cadence) belong to the `execution-daemon` spec. **Real-time per-instrument halt detection is out of boundary entirely (R7, operator 2026-05-29) — not deferred:** the gate has no halt input/branch; the intraday-halt/reopen residual is bounded by the margin monitor + venue stop-out + §16 funding cap.

- [x] 1. Foundation: survival contracts and parameters
- [x] 1.1 Define the gate's input and output data contracts and fixed vocabularies
  - Account state (equity, used/free margin, margin level, balance, stop-out level, and open positions — each mirroring broker `get_positions` 1:1, with NO halt/trading-status field per R7); proposed order (intent, direction, volume, protective stop-loss); operational state (safe-mode grade + kill-switch flag); a clock/closure-imminence input the pure core reads instead of the wall clock.
  - The admission decision (allow/reject with the binding constraint and an advisory maximum) and the standing-monitor directive (next operational state, reduce/flatten directives, emitted events); the binding-constraint enumeration (no `halt_freeze`), the reduce-directive kinds (no flatten-at-reopen), and the safe-mode-grade enumeration.
  - Observable: the full set of typed contracts imports cleanly and type-checks; the enumerations equal the design's fixed vocabularies; the position type carries no trading-status field; decision and directive objects expose the binding constraint and event fields a consumer can inspect.
  - _Requirements: 1, 2, 4, 6, 8, 9_
- [x] 1.2 Define the pinned survival-parameter set and the tighten-only resolver
  - Module-constant defaults for the inner ring: stop-out level, safe-mode buffer, per-order size limit, speculative-sleeve cap, closure-flatten lead time, the `assess` max-latency cadence bound, and the exclusion-stage toggle.
  - Resolve parameters from a pinned snapshot by value (no live re-resolution); a runtime override that would loosen any survival parameter is rejected and the pinned value retained, while a tightening override is applied.
  - Observable: the defaults instantiate with every field present; a loosening override returns the pinned value unchanged and a tightening override returns the tighter value.
  - _Requirements: 2, 10_
  - _Depends: 1.1_

- [x] 2. Foundation: persistence schema and parameter seed
- [x] 2.1 (P) Add the append-only survival event log and the monotonic operational-state store
  - Event log records halt, margin-breach, safe-mode-entry, kill-switch, flatten-directive, and flat-verify-failed events, insert-only, with a trigger that rejects updates and deletes (following the existing append-only-ledger pattern).
  - Operational-state store holds the current safe-mode grade and kill-switch flag; transitions may tighten or engage, while loosening or disengaging requires the explicit operator path (no auto-loosen).
  - Observable: the migration applies cleanly; an attempted update or delete on the event log is rejected; the state store round-trips a tighten transition and blocks an un-gated loosen.
  - _Requirements: 8, 9_
  - _Boundary: db schema (events + state migration — migration 049, first free above the landed 048)_
- [x] 2.2 Seed the survival parameter namespace
  - Insert the survival-namespace parameter rows whose keys correspond one-to-one to the pinned survival-parameter set, following the existing namespaced-seed pattern; uses migration 050 (the distinct sequence number after 2.1's migration 049).
  - Observable: the active-parameters view returns every survival key, and each key matches a field of the pinned parameter set.
  - _Requirements: 10_
  - _Boundary: db schema (params seed migration — migration 050)_
  - _Depends: 1.2_

- [ ] 3. Core: per-order admission veto
- [x] 3.1 Build the shared account-level margin-distance check
  - Compute account margin level (equity versus aggregate used margin) and the projected margin level after a proposed add, comparing against the stop-out threshold and the safe-mode buffer; treat the funded balance — not any stop-loss distance — as the hard account-level loss bound; pure, no I/O.
  - Observable: given a synthetic account state, the check returns the correct buffer/threshold comparison and never reads external state.
  - _Requirements: 1_
  - _Boundary: gate_
  - _Depends: 1.1, 1.2_
- [ ] 3.2 Implement the order-admission veto walk
  - Evaluate a proposed order through the fixed lexicographic order — kill-switch, safe-mode freeze, account activation, universe membership, ex-ante exclusion when enabled, projected margin distance, per-order size limit, mandatory protective stop-loss — stopping at and reporting the first binding constraint. (No held-name-halt step — real-time halt detection is out of boundary, R7.)
  - Classify exit-vs-open by EFFECT on the held position, not by the disposition label (never trust the upstream label): an order short-circuits to admit only if it is opposite-side to a held position in the same symbol and its volume is at most that position's held volume (net-reducing, no side flip). Any order that opens or increases net exposure — a SELL/short on an unheld or same-side position, or an opposite-side order whose volume exceeds the held position — is treated as an open and takes the full walk.
  - An open or add that breaches a constraint is rejected (with an advisory maximum on a size breach) and is never resized; a true exit is always admitted (fail-toward-flat) and is not blocked by the kill switch or safe-mode; operational state is read fresh on every call, never from the pinned snapshot.
  - Observable: a kill-switch-engaged state rejects every open and admits every true (net-reducing) exit; a size breach returns reject-plus-advisory-maximum without mutating the order; a missing stop-loss is rejected.
  - _Requirements: 2, 4, 5, 9_
  - _Boundary: gate_
  - _Depends: 3.1_

- [ ] 4. Core: standing monitor and capitalization precondition
- [ ] 4.1 Implement the no-order standing monitor
  - Evaluate account state with no proposed order: when margin level reaches the safe-mode buffer, escalate the safe-mode grade (monotonic and latched — never auto-loosens) and emit reduce/flatten directives; when a closure is within the flatten-lead window with levered exposure open, emit flatten directives and re-check the flat post-condition, escalating when not flat. There is NO halt branch — real-time halt detection is out of boundary (R7); an intraday halt is invisible to assess except via its account-level margin consequence, which routes through the margin/safe-mode path above.
  - Emit the next operational state, the reduce directives, and the events for the after-market batch; deterministic in all inputs.
  - Observable: a margin breach yields a tightened (never loosened) grade plus directives; a closure with open exposure yields flatten directives and a verify-flat escalation; no halt-triggered freeze/flatten/alert is emitted under any input.
  - _Requirements: 1, 6, 7, 8_
  - _Boundary: gate_
  - _Depends: 3.1_
  - Not parallel with 3.2/4.2: same decision-core module.
- [ ] 4.2 Implement the capitalization-time funding-cap precondition
  - Check that the account's funded balance does not exceed the speculative-sleeve cap of the supplied total-book figure, reusing the existing sleeve-cap math; this is a pre-funding check, not part of the per-order walk.
  - Observable: a funded balance above the sleeve cap of the supplied total book is rejected with the funding-cap constraint, while at or below passes.
  - _Requirements: 3_
  - _Boundary: gate_
  - _Depends: 1.2_
  - Not parallel with 3.2/4.1: same decision-core module.

- [ ] 5. Validation: inner-ring unit tests
- [ ] 5.1 (P) Parameter tests
  - Defaults complete; tighten-only resolver (loosening override rejected, tightening applied); malformed parameters fail closed.
  - Observable: the suite passes with no LLM, MCP, or live-database access.
  - _Requirements: 10, 11_
  - _Boundary: tests_
  - _Depends: 1.2_
- [ ] 5.2 (P) Admission-veto tests
  - Lexicographic order and first-binding short-circuit; the opens-reject-versus-exits-allow catastrophe guard (a true net-reducing exit is admitted even under kill-switch and safe-mode); the classification-by-effect guard — a SELL on an unheld name (opens a short) and a SELL whose volume exceeds the held long (flatten-then-flip) are REJECTED under an engaged kill-switch, proving a TRIM/SELL label alone does not short-circuit; kill-switch freshness (toggling operational state between calls flips the result); size breach yields advisory-maximum with no order mutation; missing stop-loss, off-universe, and exclusion-toggle cases; the capitalization precondition.
  - Observable: the suite passes; the true-exit-admitted, the label-only-SELL-rejected-under-kill-switch, and the kill-switch-freshness cases are explicitly asserted.
  - _Requirements: 2, 3, 4, 5, 9, 11_
  - _Boundary: tests_
  - _Depends: 3.2, 4.2_
- [ ] 5.3 (P) Standing-monitor tests
  - Margin-to-safe-mode escalation with a latched monotonic grade; closure-imminence driven via the clock input — with open levered exposure, assert the flatten directive is emitted AND, when the re-checked flat post-condition still fails, the grade escalates (FLATTEN/safe-mode) and a flat-verify-failed event is recorded (assert on the escalation, not merely that a directive was emitted); no-halt-branch — assert assess emits no halt-triggered freeze/flatten/alert for any input (R7, detection out of boundary) and that a held-name margin move routes through the margin/safe-mode path; determinism on identical inputs.
  - Observable: the suite passes; the latching (a transient blip stays latched), the no-halt-branch (no halt-triggered directive emitted), and the closure verify-flat-failure escalation cases are explicitly asserted.
  - _Requirements: 1, 6, 7, 8, 11_
  - _Boundary: tests_
  - _Depends: 4.1_

## Implementation Notes

- **Test command MUST include `--with python-dotenv`.** The repo-root `tests/conftest.py` imports `dotenv` unconditionally at collection time, so any pytest invocation without it fails at collection BEFORE survival tests run. Pure-unit: `PYTHONPATH="$PWD" uv run --with pytest --with python-dotenv --python 3.13 pytest tests/unit/survival/ -q`. DB/integration (2.1, 2.2): add `--with "psycopg[binary]"` and `-m integration_live`. There is no root `pyproject.toml`; `PYTHONPATH="$PWD"` is the worktree root. (1.1)
- **`src/survival/` is a regular package** (has `__init__.py`, docstring-only/no coupling); absolute imports `from src.survival.types import ...`. Vocabularies are `typing.Literal` aliases (not runtime enums), matching design §Types `= Literal[...]`; introspect via `typing.get_args`/`get_type_hints`. (1.1)
- **Migration test harness already exists and is reusable:** `tests/integration/conftest.py` provides `_dsn()`, session-scoped `apply_migration_chain` (currently `003→030→048`, idempotent), the `conn` fixture (autocommit), and the `expect_rejection` savepoint helper (catches `psycopg.errors.RaiseException`). Tasks 2.1/2.2 should **append 049/050 to `_MIGRATION_CHAIN`** and reuse these fixtures — do not rebuild the harness. Migration 048 (`db/migrations/048_decision_trace_telemetry.sql`) is the reference for the append-only trigger pattern (BEFORE UPDATE OR DELETE + BEFORE TRUNCATE). (parent)
- **Migration 049 monotonic guard compares safe_mode_grade by INTEGER RANK (NONE=0..FLATTEN=3), not string** — a string compare inverts safety (lexically FLATTEN<HALT_NEW<NONE<TIGHTEN). Loosen = `rank(NEW)<rank(OLD)` OR kill_switch TRUE→FALSE (OR, not AND). Bypass seam = session GUC `survival.allow_loosen='on'` (mechanism in-boundary; the loosening *policy* is walkforward-tuning-loop, out of boundary). `survival_gate_events` is append-only (UPDATE/DELETE/TRUNCATE blocked, self-contained `survival_gate_events_no_modify` — no CREATE OR REPLACE of 003/048 functions). event_type CHECK = design's 6 R7-reconciled values (no real-time `halt`; `forced_liquidation` is post-hoc). (2.1)
- **Margin-distance helper (3.1) lives in `src/survival/gate.py`** — `check_margin_distance(...)` returns a frozen `MarginDistanceResult{current_level, projected_level, breaches_stop_out, breaches_safe_mode_buffer}`. Margin level = equity/used_margin×100 (higher %=safer; breach = level ≤ threshold). Breach booleans key off the **projected** (worst-case) level. Consumers (3.2 admit, 4.1 assess) pass `additional_used_margin` = the order's projected margin delta (**≥0 for opens/adds; 0.0 for the no-order assess path**) — deriving margin-from-volume is Phase-2/out-of-boundary, so pass it explicitly. used_margin==0 → not-breaching (inf, no div-by-zero); NaN equity → coerced fail-toward-breach. Computed level is authoritative; the venue `state.margin_level` is deliberately NOT mixed in (an asymmetric `min()` fails open on the assess path). `admit`/`assess`/`check_capitalization` are not yet defined — 3.2/4.1/4.2 add them to this same file. (3.1)
- **Defense-in-depth gap (eyes-open, NOT in 2.1's observable — future hardening / concurrency-revalidation trigger):** `survival_gate_state` has only a BEFORE-UPDATE monotonic guard; a DELETE-then-reINSERT could reset to NONE/disengaged, bypassing it. Protection today = the design's single-threaded-daemon-sole-writer assumption (design §Architecture "Op-state freshness guarantee"). If daemon concurrency is ever introduced, add a DELETE/TRUNCATE guard on `survival_gate_state` alongside the DB-level advisory-lock the design already names as the revalidation fallback. (2.1 reviewer FYI)
- **Param seed (task 2.2 / migration 050) MUST enumerate all 7 `survival.*` keys.** `params.resolve()` requires every field by value and **fails closed** (no silent default) — so the seed must include `survival.assess_max_latency_seconds`, which design §Data-Models's seed list (line 247) omits (it lists only 6). The 7 keys ↔ `SurvivalParameters` float/bool fields: `stop_out_level_pct`, `safe_mode_buffer_pct`, `per_order_size_max`, `speculative_sleeve_cap_pct`, `flatten_lead_seconds`, `assess_max_latency_seconds`, `exclusion_enabled`. `code_version`/`param_version` are run-level identity (bare snapshot keys, NOT `survival.`-prefixed thresholds) — do not seed them in the `survival.*` namespace. (1.2)
