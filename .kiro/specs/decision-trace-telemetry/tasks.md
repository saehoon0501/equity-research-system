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
  - Add the four lookup indexes (run; code+param+window; event timestamp; parent) and a strict append-only guard trigger that rejects BOTH update and delete (stricter than the ledger).
  - Extend `counterfactual_ledger` additively: three nullable version columns (code version, parameter version, walk-forward window) plus a version+window index.
  - Extend the guard via `CREATE OR REPLACE FUNCTION counterfactual_ledger_guard()` — **start from migration 030's current 19-column immutable blacklist (NOT migration 003's older 11-column body)**, then add the three new columns to it with NULL-safe `IS DISTINCT FROM` checks. `CREATE OR REPLACE` swaps the whole body, so the replacement must reproduce 030's full immutable set verbatim plus the three additions; a fresh 3-column-only guard would silently regress immutability of `summary_code`, `gics_sector`, etc. The window-close completion fields (legacy `evaluation_window_end`/`system_return`/`baseline_return` + HIGH-4 `measurement_date`/`*_return_pct`) stay mutable.
  - Migration is idempotent (`IF NOT EXISTS` / `CREATE OR REPLACE`), forward-only (no down-migration); the column set matches the design's row contract shared with 1.1.
  - Observable: applying `048` to a database that already has the ledger creates the table + trigger + four indexes and adds three nullable columns to the ledger (NULL on legacy rows); re-applying is a no-op.
  - Coordination: claim migration number 048 (047 is currently the highest); renumber if the survival-gate fork also adds a migration.
  - _Requirements: 2.1, 2.2, 4.1, 4.2, 4.3, 4.4, 5.1, 7.4, 8.1_
  - _Boundary: migration 048_

- [ ] 1.3 (P) Build the live-DB migration-apply test harness
  - Provide a reusable `integration_live` fixture that opens a psycopg connection from `_dsn()`/env (per the repo convention) and applies a given migration `.sql` file — the repo has **no migration runner** (`db/README.md`), so tests must read and execute the SQL themselves.
  - Provide a pre-048 ledger bootstrap that applies exactly the `counterfactual_ledger` chain — `003_counterfactual_ledger.sql` then `030_counterfactual_ledger_high4_redesign.sql` — to a fresh test schema/DB, so a migration-safety test has a real pre-048 ledger to ALTER. Both are self-contained (no FK/enum/external-function deps; they need only the `pgcrypto`/`timescaledb` extensions present from `db/init/01-extensions.sql`), so the chain is just those two files.
  - No code dependency on 1.1/1.2 (generic apply mechanism + the already-existing 003/030 files), so it can be built in parallel; it is consumed by the integration suites in task 3, which use it to apply `048` on top.
  - Observable: the fixture applies an arbitrary migration `.sql` over a psycopg connection (demonstrated by bootstrapping the `003 → 030` ledger into a fresh schema) and returns a connection ready for assertions; re-running is safe (idempotent apply).
  - _Requirements: 9.1, 9.2_
  - _Boundary: test harness_

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
  - Using the harness, apply `048`, insert a decision row via direct SQL, then assert DELETE is rejected and UPDATE of any column is rejected by the guard trigger.
  - Observable: the suite passes against live Postgres, demonstrating trace-row immutability (no update, no delete).
  - _Requirements: 2.1, 2.2, 9.1_
  - _Depends: 1.2, 1.3_

- [ ] 3.3 Ledger migration-safety + guard-extension integration test (integration_live)
  - Using the harness, stand up the pre-048 ledger, insert a representative legacy row, snapshot the existing column set and a stratified postmortem query result (e.g. by `summary_code`/`window`/`gics_sector`), then apply `048` and assert: existing columns unchanged, the stratified query returns identical results, and the three new version columns are NULL on the legacy row.
  - Assert the guard extension: an UPDATE of a new version column post-insert is rejected, while the existing window-close completion fields still update.
  - Note: the eval-loop scorer is a pure function that does not read the ledger, so there is no ledger-scoring query to run — equivalence is asserted on column preservation + stratified reads, not a scorer call.
  - Observable: the suite passes against live Postgres, demonstrating the additive migration preserves the ledger's existing columns, stratified-read results, and append-only integrity.
  - _Requirements: 4.2, 4.4, 9.2_
  - _Depends: 1.2, 1.3_

- [ ] 3.4 Link, firewall, and idempotency integration test (integration_live)
  - Through the write/read path: insert a decision then a linked fill; assert the read surface returns both for a (code version, parameter version, walk-forward window) query, joinable by parent id.
  - Late-fill firewall: a decision in window N plus a linked fill whose event timestamp falls in window N+1 → an until-N-boundary read excludes the late fill while the fill still attributes to the decision's window.
  - Idempotency: re-writing a row with the same client-minted id through the writer is a no-op.
  - Build-order gate: these inner-ring suites (3.1–3.4) must be in place before any version-attributed outer-ring (eval-loop) scoring is wired against the ledger.
  - Observable: the suite passes against live Postgres, demonstrating the decision→fill join, the event-timestamp firewall exclusion with decision-window attribution, and the idempotent re-send.
  - _Requirements: 1.4, 3.2, 5.1, 5.2, 6.1, 9.3_
  - _Depends: 1.2, 1.3, 2.1, 2.2_
