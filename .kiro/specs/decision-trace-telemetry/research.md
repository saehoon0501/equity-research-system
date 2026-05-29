# Gap Analysis: decision-trace-telemetry

**Date:** 2026-05-29 · **Inputs:** `requirements.md` (R1–R9), `brief.md`, codebase scan. **Steering note:** only `roadmap.md` exists under `.kiro/steering/` (no `product/tech/structure.md`); `CLAUDE.md` is the de-facto steering and was used.

## Analysis summary

- **Mostly reuse, low architectural risk.** Both deliverables — the append-only `decision_process_trace` table and the additive `counterfactual_ledger` model-version dimension — map cleanly onto established repo patterns: append-only tables + `plpgsql` guard triggers, idempotent expand-then-contract migrations, and direct-psycopg writes (`src/shared/regime_sidecar/persistence.py`, `src/supervisor/emitter.py`).
- **The additive migration is provably safe.** The eval-loop scorer (`src/calibration/scorer.py`, shim `src/eval/scorer.py`) is a **pure function** — it does not read the ledger; calibration metrics operate on `calibration_emission_snapshot.continuous_score`, not ledger columns. Postmortem queries stratify on existing columns (`summary_code`, `window`, `gics_sector`, `measurement_date`) via idempotent indexes. Adding **nullable** columns breaks nothing (satisfies R4.2).
- **The writer is the real new code, and its caller is downstream.** No `counterfactual_ledger` writer exists in `src/` today (MCP-driven / deferred to a future CLI/scheduler). The trace writer is new — but it follows the regime-sidecar/emitter shape exactly. Its *invoker* is the `execution-daemon` (a later spec); this spec owns the schema + writer + tests, not the emission calls (R7.2).
- **⚠️ A real requirements tension to resolve in design:** R1.4 (capture **expected-vs-actual fill / slippage**) + R2 (strict **append-only**, no update) collide with **async orders** (§11.4: placement returns a queue ref; the fill confirms *later*). The decision row is written at decision time, before the fill is known — so the actual-fill cannot be an UPDATE to that row without breaking R2. **Resolution (design decision): model the fill as a separate append-only record linked by a correlation/decision id**, not an update. May warrant a small R1.4 rewording.
- **P14 nuance:** trigger + migration correctness can only be verified against a live Postgres (`integration_live`), not pure-unit (<1s, no DB). So R9's "inner-ring" splits: **pure-unit** for the writer's row-shaping logic (`conn=None` dry-run, per emitter), **integration_live** for append-only enforcement + migration-preserves-scoring. No trigger tests exist in the tree today — this spec adds the first.

## Requirement → Asset map (gaps tagged)

| Req | Existing asset to reuse | Tag |
|---|---|---|
| R1 capture | `write_classifications`/`emit_recommendation` direct-psycopg shape; daemon supplies data | **Missing** (writer new; daemon downstream) |
| R2 append-only | `counterfactual_ledger_guard()` trigger (mig 003/030) | **Reuse** (replicate, stricter) |
| R3 correlation keys | `run_id` conventions (P2/P3); `parameters_version` UUID precedent (mig 011) | **Reuse** |
| R4 ledger version-dim | additive `ALTER … ADD COLUMN IF NOT EXISTS` (mig 030); pure-fn scorer; stratified idempotent indexes | **Reuse** (safe) |
| R5 firewall support | existing `window`/`measurement_date`; new `walk_forward_window` | **Reuse + new col** |
| R6 replay/read | idempotent index + stratified-query precedent | **Reuse** |
| R7 boundary | scope discipline (model-only; daemon owns calls) | **Constraint** |
| R8 durable + schema-stable | JSONB precedent (`parameters.value`, `archetype_distribution`, `m3_refreshes`) | **Reuse** |
| R9 test surface | `integration_live` marker (`tests/conftest.py`); psycopg fixture | **Reuse + Constraint** (trigger/migration = `integration_live`, not pure-unit) |

## Implementation approach options

**Option A — Extend (fold trace into the ledger or an existing table).** ❌ Rejected: the trace is high-frequency per-*decision* process data with a distinct lifecycle from the per-*outcome* ledger; folding it bloats the ledger and violates the process/outcome separation (§14.8).

**Option B — New table + additive ledger migration (RECOMMENDED).** New `decision_process_trace` (single fat-JSONB `trace` + typed `trace_id/run_id/decision_ts/code_version/param_version/walk_forward_window`, per the brief) with its own strict-append-only guard trigger; additive migration **048** adds the three nullable version columns to `counterfactual_ledger` and extends `counterfactual_ledger_guard()`'s immutable set to cover them; a new `src/…/write_decision_trace(rows, conn=None)` leaf mirroring `regime_sidecar/persistence.py`. ✅ Clean process/outcome separation; isolatable tests; matches every existing convention.
- Trade-offs: ✅ separation of concerns, isolatable, reuses patterns · ❌ new table + first-in-repo trigger test.

**Option C — Hybrid / phased (trace now; defer ledger version-dim).** Splits into two migrations across phases. Viable but the version-dim is cheap and load-bearing for the §14.6 firewall (R5) and the tuner's scoreability — no strong reason to defer. Use only if the tuner spec slips far.

## Effort & Risk

| Component | Effort | Risk | Justification |
|---|---|---|---|
| `decision_process_trace` table + strict append-only trigger | S–M | Low | established guard-trigger pattern; first trigger *test* is new |
| Additive ledger migration 048 + trigger extension | S | Low | pure-fn scorer + stratified queries unaffected; idempotent |
| `write_decision_trace` leaf (dry-run + atomic) | S | Low | direct copy of regime-sidecar/emitter shape |
| **Overall** | **M** | **Low** | reuse-dominated; one genuine design decision (async-fill, below) |

## Recommendations for design phase

- **Preferred approach:** Option B.
- **Key design decisions to make:**
  1. **Async-fill modeling (load-bearing):** decision row at decision-time + a *separate, linked, append-only* fill/outcome record (joined by a decision/order id) — preserves R2 while satisfying R1.4 for async fills. Consider rewording R1.4 to reference the linked fill record rather than "the trace record captures the fill."
  2. **Trace is strictly append-only** (block DELETE *and* UPDATE) — stricter than the ledger (which allows window-close completion updates). Confirm no legitimate trace-row update once #1 removes the fill-update need.
  3. **Trigger extension for the ledger:** add `code_version, param_version, walk_forward_window` to the immutable set (insert-set, never mutable), using `IS DISTINCT FROM` for NULL-safe checks.
  4. **Writer placement (Decision-6 / P1):** a leaf module (e.g. `src/reactive/telemetry/` or `src/telemetry/`), `conn=None` dry-run convention; the daemon imports it directly (non-MCP, §14.10).
- **Research-needed carried forward:**
  - Migration **048** number coordination with the `survival-gate` fork (flagged in `spec.json.notes`).
  - JSONB expression index for any hot field the tuner later filters inside `trace` (deferred; matches the fat-JSONB decision).
  - Confirm the daemon's decision id / correlation-id scheme so the decision row and the linked fill record join cleanly (cross-spec seam with `execution-daemon`).
  - **Flatten / safe-mode exit seam (cross-spec: `execution-daemon` + in-session-monitor).** Flatten events — both the scheduled **flat-before-closure** invariant (§16.1) and **safe-mode/monitor-triggered** flattens (§14.3/§15) — are traced daemon *exit* decisions (R1.1/R1.2, gate-link = Survive/safe-mode; the close fill via R1.4). The monitor's *decision* to flatten is an LLM-action audit owned by the monitor spec (R7.1), **joined** to the daemon's flatten-trace via the correlation keys (R3). Design must confirm the trace captures exit/flatten decisions (not only entries/declines) and that the key set lets a reviewer reconstruct **trigger → flatten → outcome**. (Seam noted by the execution-daemon fork 2026-05-29; not editing that lane.)

---

## Design synthesis (2026-05-29)

- **Generalization:** the model trace and the per-spec LLM-action audits share one shape (append-only event + correlation keys), but per the model-only scope (R7.1) only the model trace is built here; the shared interface is the **correlation-key contract**, not a shared table. The async decision + fill are unified in **one table with a `kind` discriminator** (decision/fill), not two tables.
- **Build vs adopt:** adopt the existing append-only guard-trigger pattern, the JSONB-payload convention, and the `_dsn()` + `.transaction()` + `conn=None` direct-psycopg writer; build nothing new at the infra level. The eval-loop scorer is a **pure function** -> the ledger extension is additive-safe with no scorer change.
- **Simplification:** one table (kind-discriminated) + one migration (048) + one leaf module (schema/writer/reader); no adapters or abstraction layers; JSONB absorbs new signal fields without future migrations (R8.2).
- **Async-fill resolution (was the open gap-analysis decision):** decision row at decision-time + a separate linked `kind=fill` row at fill confirmation, joined by `parent_trace_id` -> satisfies R1.4 (expected-vs-actual fill) while preserving R2 (strict append-only). No R1.4 reword required; wording could be tightened in a later requirements pass (non-blocking).
