# audit_trail — terminal-rendered drill-down

Layered audit drill-down UI scaffold for execution recommendations, terminal-rendered for the v0.1 launch.

Per v3 spec sections:
- **Section 5.2** — Audit-mode UX (layered drill-down)
- **Section 5.4** — `/audit-trail <rec_id>` and `/audit-trail <ticker> --latest` slash commands
- **Section 7 Q4** — layered drill-down lock with HMAC chain
- **Section 7.1** — HMAC chain validates end-to-end (v0.1 launch gate)

## Module layout

```
src/audit_trail/
  __init__.py        — public re-exports
  loader.py          — Postgres query layer (read-only)
  renderer.py        — markdown renderers (top summary + per-stage drill)
  hmac_verify.py     — HMAC-SHA256 chain verification
  cli.py             — `python -m src.audit_trail.cli` entry point
  README.md          — this file
```

The `/audit-trail` slash command lives at `.claude/commands/audit-trail.md` and shells out to the CLI.

## Usage

Top-level summary:

```bash
python -m src.audit_trail.cli 8f2e1234-aaaa-bbbb-cccc-dddddddddddd
```

Drill into a stage:

```bash
python -m src.audit_trail.cli 8f2e1234-...  --stage stage_2_debate
```

Latest by ticker:

```bash
python -m src.audit_trail.cli --latest AAPL
```

HMAC chain verify:

```bash
AUDIT_HMAC_KEY=... python -m src.audit_trail.cli 8f2e1234-... --verify
```

## Design choices

### Markdown over a TUI library

The output target is the Claude Code session display + plain terminals. Both render Markdown natively. Pulling in a third-party TUI library (`rich`, `textual`) would add a dependency without buying anything for v0.1. Pipe-table Markdown renders cleanly in both surfaces.

### HMAC algorithm

- **HMAC-SHA256.** Industry-standard primitive, well-supported by Python's `hmac` + `hashlib` stdlib.
- **Canonical JSON** for the signed input — single source of truth via `canonical_payload_dict`:
  ```python
  json.dumps(obj, sort_keys=True, separators=(',', ':'),
             ensure_ascii=False, default=_json_default).encode('utf-8')
  ```
  Type defaults: `UUID → str()`, `datetime → ISO8601 UTC`, `date → ISO8601`, `Decimal → str()`.
  `ensure_ascii=False` is load-bearing — unicode (Greek letters, em-dash, etc.) round-trips byte-identically only when ASCII-escape is disabled in BOTH emitter and verifier.
- **Constant-time comparison** via `hmac.compare_digest`.
- **Chain semantics**: each row's signed payload includes its `parent_audit_id`. Tampering with any row's `drill_payload`, `versions`, or parent pointer invalidates the HMAC. A separate parent-link integrity check ensures `parent_audit_id` resolves to a prior row with `created_at` ≤ child timestamp.

### HMAC env var scopes (4 distinct, independent rotation lifetimes)

Each module has its own secret so a compromise/rotation in one scope does not force re-signing rows in another:

| Env var                  | Scope                                                                      | Producer module                  | Verifier                                |
|--------------------------|----------------------------------------------------------------------------|----------------------------------|-----------------------------------------|
| `AUDIT_HMAC_KEY`         | `audit_provenance` chain (Stage 1A/1B/2/3 of P3, debate, kills, etc.)      | `src/p3_mechanical_scorer/`      | `src/audit_trail/hmac_verify.py`        |
| `PEAK_PAIN_HMAC_KEY`     | `peak_pain_archetypes` catalog rows (column-stored)                        | `src/peak_pain_catalog/persistence.py` | `verify_hmac` in same file               |
| `PREMORTEM_HMAC_SECRET`  | `premortem` rows (column-stored per migration 016)                         | `src/premortem_scheduler/recorder.py` | `src/premortem_scheduler/hmac.py`       |
| `WATCHLIST_HMAC_SECRET`  | `watchlist.thesis_pillars_original_hmac` + `scenario_A_base_projections_hmac` | `src/watchlist/hmac_producer.py` | `src/anchor_drift/hmac_verify.py`       |

All four producers MUST canonicalize via the helpers in `src/audit_trail/hmac_verify.py` so cross-module verification works under one rule. Per remediation requirement: every audit/HMAC row written by any module verifies cleanly under the canonical scheme.

### Layered drill-down

Per v3 Section 5.2, the top-level summary loads only:
- `execution_recommendations` row (one query)
- per-stage projection of `audit_provenance` (one query, light JSONB read)

The expensive `drill_payload` (verbatim quotes, iteration logs, retrieval results) loads only on `--stage` drill.

This matches the operator UX: skim the decision_path table, drill on demand, never block on heavy reads.

### Tamper-evidence surfacing

When `--verify` fails:
- Per-row failures surface in the result table with `FAIL` markers.
- A prominent `TAMPER-EVIDENT` banner renders at the top.
- The CLI exits with code `3`, which the slash command maps to "flag as M-2 system event per Section 5.3 push-alert pipeline".

This module does NOT push the alert itself — the caller (slash command runner) is responsible for routing to the alert pipeline. We surface the structured result; the alert routing is its own concern.

### Slash-command UX

- Single command, mode flags: `--stage`, `--latest`, `--verify`, `--strict`. Operator does not need to memorize multiple verbs.
- Summary is the default; drilling is opt-in. Aligns with "cheap top-level first" per Section 5.2.
- Each summary row prints the exact follow-up command in its `Drill` cell — operator copies/clicks to drill.

## What this module does NOT do

Per task scope (and v3 spec):

- **No web UI** — deferred to v0.5+.
- **No replay capability** — replay deferred to `/backtest` per Section 7 Q4 PB.
- **No audit row writes** — the recommendation emitter (P5/P9 in Section 4.6) owns writes; `audit_provenance` is append-only at the DB level (trigger in migration 008).
- **No alert routing** — verification surfaces structured results; alert pipeline is Section 5.3's responsibility.

## Tests

Smoke test in `tests/test_audit_trail.py` — uses fake Postgres connections (no live DB required) to exercise:
- Top-level summary rendering
- Per-stage drill rendering for all 5 stages
- HMAC chain verification (OK + tampered cases)
- Latest-by-ticker resolution
- CLI argument parsing

Run with `pytest tests/test_audit_trail.py`.

## Dependencies

Stdlib only (`hashlib`, `hmac`, `json`, `argparse`, `dataclasses`, `uuid`, `datetime`).

The CLI optionally imports `psycopg` (v3) or `psycopg2` to open a real Postgres connection; both are optional at module level so the renderer/loader/verifier are unit-testable without a driver.
