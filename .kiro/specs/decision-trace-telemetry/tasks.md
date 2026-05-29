# Implementation Plan

- [ ] 1. Foundation: correlation-key contract, storage migration, test harness
- [ ] 1.1 Define the correlation-key contract and trace row types
  - Create the telemetry leaf package and the pure-types module holding the single definition of the correlation keys (run id, code version, parameter version, walk-forward window) and the two row kinds (decision, fill).
  - Decision row: client-minted trace id, an event timestamp pinned at decision time, and a flexible payload (gate link, signal values, derived probability, liquidation proximity, stop-out, declined flag).
  - Fill row: its own client-minted trace id, the parent decision id, its own (later) event timestamp, the decision's walk-forward window for attribution, and a fill payload (expected vs actual price, slippage, volume, counterparty price).
  - Types are pure (no I/O), frozen, and import-only; a fill type carries a parent reference and a decision type does not.
  - The package `__init__.py` (including any re-exports of the key/row types) is created and owned here, so later leaf tasks add new modules without modifying it.
  - Observable: importing the module yields the frozen key/row dataclasses with the documented fields, and the package imports as a leaf with no DB or MCP dependency.
  - _Requirements: 1.4, 3.1, 8.2_
  - _Boundary: schema_

- [ ] 1.2 (P) Author the append-only storage migration (048)
  - Create `decision_process_trace`: a client-minted UUID primary key (no default), a kind discriminator constrained to decision/fill, a nullable self-referencing parent id (set on fill rows), an event timestamp, the four typed correlation-key columns, a JSONB payload, and a created-at default.
  - Add the four lookup indexes (run; code+param+window; event timestamp; parent) and a strict append-only guard that rejects UPDATE, DELETE, **and TRUNCATE** — the row-level `BEFORE UPDATE OR DELETE` trigger plus a separate `BEFORE TRUNCATE FOR EACH STATEMENT` trigger, both using the same guard function (it raises unconditionally on `TG_OP` and references no `NEW`/`OLD`, so it serves both). This makes the trace truly append-only — stricter than the ledger, whose TRUNCATE carve-out is left unchanged (out of boundary; additive-only on the ledger).
  - Extend `counterfactual_ledger` additively: three nullable version columns (code version, parameter version, walk-forward window) plus a version+window index.
  - Extend the guard via `CREATE OR REPLACE FUNCTION counterfactual_ledger_guard()` — **start from migration 030's current 19-column immutable blacklist (NOT migration 003's older 11-column body)**, then add the three new columns to it with NULL-safe `IS DISTINCT FROM` checks. `CREATE OR REPLACE` swaps the whole body, so the replacement must reproduce 030's full immutable set verbatim plus the three additions; a fresh 3-column-only guard would silently regress immutability of `summary_code`, `gics_sector`, etc. The window-close completion fields (legacy `evaluation_window_end`/`system_return`/`baseline_return` + HIGH-4 `measurement_date`/`*_return_pct`) stay mutable.
  - Migration is idempotent (`IF NOT EXISTS` / `CREATE OR REPLACE`), forward-only (no down-migration); the column set matches the design's row contract shared with 1.1.
  - Observable: applying `048` to a database that already has the ledger creates the table + trigger + four indexes and adds three nullable columns to the ledger (NULL on legacy rows); re-applying is a no-op.
  - Coordination: claim migration number 048 (047 is currently the highest); renumber if the survival-gate fork also adds a migration.
  - _Requirements: 2.1, 2.2, 4.1, 4.2, 4.3, 4.4, 5.1, 7.4, 8.1_
  - _Boundary: migration 048_

- [ ] 1.3 Build the shared `integration_live` test harness
  - Follow the existing `integration_live` convention (`tests/integration/test_contamination_check.py`): a `_dsn()`/`.env` psycopg connection against the **shared, already-running dev DB** — there is no fresh-schema/`search_path` precedent and no migration runner (`db/README.md`), so do NOT bootstrap a throwaway schema.
  - Provide a session-scoped fixture that **idempotently applies the chain `003 → 030 → 048`** (all `IF NOT EXISTS`/`CREATE OR REPLACE`, so safe to re-run and safe if the operator already applied them) so the suite is self-bootstrapping and robust to dev-DB migration drift; this leaves 048 permanently applied, which is also what the execution-daemon will need.
  - Provide a savepoint-based "expect-rejection" helper so a deliberately-failing op (a guard `RAISE`) can be asserted without poisoning the connection for later assertions (no rollback/savepoint precedent exists in the tree — this is the first).
  - Design note for the consumers: tests assert **post-migration invariants** against the migrated DB (column set present, new columns nullable, guard behavior), NOT a live before/after column diff — a before/after goes vacuous once 048 is permanently applied (and `IF NOT EXISTS` would hide the failure).
  - Observable: a consuming test can acquire a connection with the `003→030→048` chain guaranteed-applied and assert an expected guard rejection via the helper without breaking the session; re-running the suite is safe (idempotent).
  - _Requirements: 9.1, 9.2_
  - _Boundary: test harness_
  - _Depends: 1.2_

- [ ] 2. Core: append-only write path + read/replay surface
- [ ] 2.1 (P) Implement the append-only trace writers
  - Implement the decision-trace writer and the fill-outcome writer as direct-psycopg leaf functions following the repo's `_dsn()` + `.transaction()` + `conn=None` dry-run convention.
  - Writers issue INSERT only — never update or delete — and use `ON CONFLICT` on the client-minted trace id so a re-sent write is a no-op (the idempotency key; addresses the broker double-send residual).
  - Fail-fast at the boundary: reject a row missing any correlation key, an unknown kind, or a fill with an unresolvable parent before any INSERT; partial writes roll back.
  - Capture the model trace only — gate link, signals, probability, liq/stop-out, declined entries, and expected-vs-actual fill/slippage — and do not own the emission calls (the daemon calls the writer), compute no aggregates, and make no account/survival or MCP reads.
  - Observable: a dry-run call (`conn=None`) returns the shaped row(s) and writes nothing; a live call persists durable rows and returns the count actually written, and a re-send of the same id writes zero.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 7.1, 7.2, 7.3, 8.1, 8.2_
  - _Boundary: trace_writer_
  - _Depends: 1.1_

- [ ] 2.2 (P) Implement the read/replay surface
  - Implement the consumer-agnostic read surface that retrieves trace rows filtered by any subset of the correlation keys plus a since/until time bound and kind.
  - Read-only; returns decision and linked fill rows joinable by the parent id; surfaces the event timestamp + walk-forward window so a consumer can enforce its own temporal firewall (this surface provides, never enforces).
  - Observable: a query by a (code version, parameter version, walk-forward window) tuple returns the matching decision and its linked fill, and an until-bound query excludes rows whose event timestamp is past the bound.
  - _Requirements: 3.2, 5.2, 6.1, 6.2_
  - _Boundary: reader_
  - _Depends: 1.1_

- [ ] 3. Validation: inner-ring tests (pure-unit + integration_live)
  - The three integration sub-tasks (3.2–3.4) all live in the single integration test file from the design's File Structure Plan, so they are intentionally **not** `(P)` with each other and run in order.
- [ ] 3.1 (P) Pure-unit writer tests
  - Cover dry-run (returns the shaped row, writes nothing), fail-fast on a missing correlation key, a fill requiring a parent id, and a decision forbidding one — no LLM, no MCP, no live DB, sub-second.
  - Observable: the unit suite runs without a database and asserts the dry-run no-write and each fail-fast rejection.
  - _Requirements: 9.1_
  - _Boundary: unit tests_
  - _Depends: 2.1_

- [ ] 3.2 Trace-table append-only integration test (integration_live)
  - Using the harness (chain already applied), insert a decision row via direct SQL with a deterministic `uuid5` id (`ON CONFLICT DO NOTHING`, per the repo convention), then via the savepoint helper assert each of DELETE, UPDATE (any column), and TRUNCATE is rejected by the guard.
  - Observable: the suite passes against live Postgres, demonstrating trace-row immutability against all three of update, delete, and truncate.
  - _Requirements: 2.1, 2.2, 9.1_
  - _Depends: 1.2, 1.3_

- [ ] 3.3 Ledger migration-safety + guard-extension integration test (integration_live)
  - Against the migrated DB, assert **post-migration invariants** (not a live before/after diff, which goes vacuous once 048 is permanently applied): the full enumerated pre-048 ledger column set (the 003 + 030 columns) is still present with unchanged types, the three new version columns exist and are nullable, and the version+window index exists. The enumerated pre-048 column list IS the "before" — a dropped/retyped column fails the assertion, so this still catches regressions (R4.2 preservation).
  - Insert a representative legacy-style row (NULL version columns, deterministic `uuid5` + `ON CONFLICT`); confirm a stratified postmortem read (e.g. by `summary_code`/`window`/`gics_sector`) still returns it.
  - Assert the guard extension via the savepoint helper: an UPDATE of a new version column post-insert is rejected, while a window-close completion field (e.g. `measurement_date`) still updates.
  - Note: the eval-loop scorer is a pure function that does not read the ledger, so there is no ledger-scoring query to run — preservation is asserted on the column set + stratified read, not a scorer call.
  - Observable: the suite passes against live Postgres, demonstrating the additive migration preserves every pre-048 ledger column, keeps stratified reads working, and extends append-only integrity to the new columns.
  - _Requirements: 4.2, 4.4, 9.2_
  - _Depends: 1.2, 1.3_

- [ ] 3.4 Link, firewall, and idempotency integration test (integration_live)
  - Through the write/read path (harness chain already applied; deterministic `uuid5` ids per the convention): insert a decision then a linked fill; assert the read surface returns both for a (code version, parameter version, walk-forward window) query, joinable by parent id.
  - Late-fill firewall: a decision in window N plus a linked fill whose event timestamp falls in window N+1 → an until-N-boundary read excludes the late fill while the fill still attributes to the decision's window.
  - Idempotency: re-writing a row with the same client-minted id through the writer is a no-op.
  - Build-order gate: these inner-ring suites (3.1–3.4) must be in place before any version-attributed outer-ring (eval-loop) scoring is wired against the ledger.
  - Observable: the suite passes against live Postgres, demonstrating the decision→fill join, the event-timestamp firewall exclusion with decision-window attribution, and the idempotent re-send.
  - _Requirements: 1.4, 3.2, 5.1, 5.2, 6.1, 9.3_
  - _Depends: 1.2, 1.3, 2.1, 2.2_
