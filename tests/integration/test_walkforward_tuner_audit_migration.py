"""`integration_live` tests for the walkforward-tuning-loop DB surfaces (task 4.3).

Task 4.3 (requirements 7.1, 7.3, 8.1, 8.4; design.md "Data Models →
walkforward_tuner_audit (migration 053)" + "Integrity"; the publish leaf's
"resolvable parameters_active rows + boundary stamp"). Proves THREE observable
invariants against the SHARED, already-running dev DB (container
`equity-research-db`, 127.0.0.1:5432), each AUTO-SKIPPED without `-m
integration_live` + a live DB:

  (1) mig-053 GUARD (R8.1/R8.4) — `walkforward_tuner_audit` is append-only
      (STRICT, no mutable column, mirroring mig 048): an UPDATE, a DELETE, and a
      TRUNCATE are each rejected by the migration's self-contained guard (a
      row-level BEFORE UPDATE OR DELETE trigger + a statement-level BEFORE
      TRUNCATE trigger sharing one RAISE function). The INSERT is unguarded.
      Unlike the survival-gate precedent, this table has NO inbound FK
      (mig-053 header), so the TRUNCATE probe is BARE — it reaches the
      statement-level trigger directly and raises P0001 (no CASCADE dance).

  (2) THE 4-KEY JOIN (R8.3/8.4) — an `audit.py`-assembled audit row joins to a
      seeded `decision_process_trace` (mig 048) row by the four correlation keys
      (run_id, code_version, param_version, walk_forward_window). This is the
      separate-but-correlated audit surface (R8.4, P11): the loop owns
      `walkforward_tuner_audit`; the model trace is owned by decision-trace
      telemetry; the two join by VALUE on the four keys (no FK). The join uses a
      PROMOTE audit so `walk_forward_window` is NON-NULL on BOTH rows — `=` never
      matches NULL=NULL, so a decline (null window) would silently return nothing
      and a four-`=` join would vacuously "pass".

  (3) THE PUBLISH ROUND-TRIP (R7.1/7.3) — `publish.publish` on a PROMOTE writes
      the `reactive.*` + `survival.*` rows so `parameters_active` RESOLVES to the
      tuned values (R7.1) and stamps the advanced `walk_forward_window` boundary
      label (R7.3/1.4), discoverable to the daemon at its next hot-swap. The live
      write is wrapped in a transaction that is ROLLED BACK: publish writes the
      EXACT `reactive.threshold` / `survival.*` keys the daemon resolves from
      `parameters_active`, so a COMMIT would hijack the shared dev DB's active
      params for every other consumer. `now()` is constant within the
      transaction, so the inserted `effective_at = now()` satisfies the view's
      `effective_at <= now()` and the new row wins the latest-effective_at race
      IN-TRANSACTION (the read-back proves resolution before the rollback). We
      assert on the VALUE + the minted version_id, NOT a row count — the shared
      DB already holds `reactive.threshold` etc.; our row resolves only via the
      latest effective_at.

MIGRATION LAYERING. The shared harness (`tests/integration/conftest.py`) applies
`003→030→048→049→050`, which ALREADY assumes mig 004 (`parameters` /
`parameters_active`) is live on the shared dev DB (050 is a parameters *seed*).
This file layers ONLY mig 053 on top of that `conn` — it does NOT re-apply 004
(re-running 004's `CREATE OR REPLACE VIEW parameters_active` would error if the
shared view has drifted) and does NOT modify the shared conftest.

SHARED-DB DISCIPLINE (NEVER `docker compose down` / wipe — the DB is shared
across worktrees):
  * the append-only audit + trace rows use deterministic `uuid5` ids +
    `ON CONFLICT DO NOTHING`, so the seed + savepoint-wrapped rejection probes
    leave nothing growing (re-run = clean no-op), mirroring the survival-gate
    precedent;
  * the publish round-trip is the ONLY unsafe-to-commit write, so it is wrapped
    in an explicit `with conn.transaction(): … raise psycopg.Rollback()` (the
    autocommit `conn` makes publish's own inner `conn.transaction()` a SAVEPOINT
    inside ours); the read-back happens in-transaction, before the rollback;
  * the `audit.py` envelope-on-disk write is UNCONDITIONAL (even on the live
    path), so `audit._REPO_ROOT` is monkeypatched to `tmp_path` so no test ever
    pollutes the worktree's `memos/envelopes/`.

Reuses the shared harness: the `conn` fixture (autocommit, chain
guaranteed-applied) and the savepoint-based `expect_rejection` helper (asserts a
guard `RAISE` / SQLSTATE P0001 without poisoning the connection). Connection /
chain logic is NOT re-implemented here. Run:

    PYTHONPATH="$PWD" .venv-wf/bin/python -m pytest \
        tests/integration/test_walkforward_tuner_audit_migration.py \
        -m integration_live -q
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg.types.json import Jsonb

from src.reactive.params import ParamSnapshot
from src.reactive.replay.types import Candidate
from src.reactive.types import CalibrationEvidence, Weights
from src.skills.walkforward_tune import audit as A
from src.skills.walkforward_tune import publish as P
from src.skills.walkforward_tune.types import GateVerdict, TunerActionAudit
from src.survival.params import SurvivalParameters

pytestmark = pytest.mark.integration_live

# tests/integration/<this>.py → parents[0]=integration, [1]=tests, [2]=repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION_053 = _REPO_ROOT / "db" / "migrations" / "053_walkforward_tuner_audit.sql"

# Deterministic, idempotent fixture ids (mirrors the uuid5 convention in
# test_survival_gate_migration.py / test_decision_trace_migration.py). A fixed
# namespace so re-runs reuse the SAME ids → the append-only seed + ON CONFLICT
# DO NOTHING is a clean no-op on the shared DB.
_NS = uuid.uuid5(uuid.NAMESPACE_URL, "walkforward-tuning-loop/task-4.3")

# The four correlation keys, shared by the seeded trace row AND the audit row so
# the four-`=` join matches. walk_forward_window is NON-NULL (a PROMOTE audit) —
# `=` never matches NULL=NULL, so a null window would make the join vacuous.
_RUN_ID = str(uuid.uuid5(_NS, "run_id"))
_CODE_VERSION = "cv-2026.05-task43"
_PARAM_VERSION = "pv-cand-A-task43"
_WALK_FORWARD_WINDOW = "2026-05-31..2026-06-30"


# --------------------------------------------------------------------------- #
# Migration layering — apply ONLY 053 on top of the shared chain.             #
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")
def apply_053(apply_migration_chain: str) -> str:
    """Idempotently apply mig 053 (`walkforward_tuner_audit`) onto the shared DB.

    Depends on the shared-conftest `apply_migration_chain` (which leaves
    `003→030→048→049→050` applied — and assumes mig 004's `parameters` /
    `parameters_active` already live on the shared dev DB). We layer ONLY 053:
    re-applying 004 would re-run its `CREATE OR REPLACE VIEW parameters_active`
    and could error on a drifted shared view. 053 is `CREATE TABLE IF NOT EXISTS`
    + `CREATE OR REPLACE FUNCTION` + `DROP TRIGGER IF EXISTS` + `CREATE TRIGGER`,
    so re-running is a clean no-op. The file drives its own `BEGIN; … COMMIT;`,
    so we execute its full text in autocommit (no `;`-splitting — its plpgsql
    `$$ … $$` body + `COMMENT ON … '…; …'` strings contain semicolons).

    Returns the DSN so dependent fixtures can reuse it.
    """
    dsn = apply_migration_chain
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(_MIGRATION_053.read_text())
    return dsn


@pytest.fixture
def conn053(apply_053: str):
    """A fresh autocommit connection with the chain + mig 053 guaranteed-applied.

    Function-scoped (clean session per test); autocommit so the savepoint helper's
    nested `with conn.transaction()` is the only transaction boundary in play.
    """
    with psycopg.connect(apply_053, autocommit=True) as connection:
        yield connection


@pytest.fixture(autouse=True)
def _redirect_envelope_dir(tmp_path, monkeypatch):
    """`audit.write_audit` writes the envelope-on-disk UNCONDITIONALLY (even on
    the live path, P4), so redirect the module-level repo-root seam to `tmp_path`
    — no test pollutes the worktree's `memos/envelopes/`."""
    monkeypatch.setattr(A, "_REPO_ROOT", tmp_path)
    return tmp_path


# --------------------------------------------------------------------------- #
# Real frozen-dataclass fixtures — the audit, the candidate, the verdict.      #
# (never a loose dict — the unit-green/integration-broken trap class).         #
# --------------------------------------------------------------------------- #


def _promote_verdict() -> GateVerdict:
    return GateVerdict(
        promote=True,
        selected_config=_PARAM_VERSION,
        reasons=["dsr>=threshold", "psr>=threshold", "lexicographic_ok"],
        dsr=2.1,
        psr=0.97,
        min_trl_met=True,
        pbo=0.05,
        effective_n=4,
        lexicographic_ok=True,
    )


def _promote_audit() -> TunerActionAudit:
    """A PROMOTE audit with a NON-NULL `walk_forward_window` so the four-`=` join
    to the seeded trace row matches (a decline leaves the window NULL → no match).
    """
    v = _promote_verdict()
    return TunerActionAudit(
        audit_id=A.mint_audit_id(run_id=_RUN_ID),
        run_id=_RUN_ID,
        code_version=_CODE_VERSION,
        param_version=_PARAM_VERSION,
        walk_forward_window=_WALK_FORWARD_WINDOW,  # advanced on promote
        promoted=True,
        track="param",
        gate_metrics=A.gate_metrics_from_verdict(v),
        hypothesis={
            "statement": (
                "Candidate pv-cand-A's survival-net OOS edge over the incumbent "
                "persists out-of-sample across the CPCV partitions."
            ),
            "falsifiers": [
                "next cycle's OOS survival-net return falls below the incumbent's",
                "a survival breach / stop-out appears the incumbent did not incur",
            ],
        },
    )


def _candidate() -> Candidate:
    """A real consumed `Candidate` carrying tuned reactive + survival values
    (mirrors test_publish.py's construction)."""
    snap = ParamSnapshot(
        weights=Weights(w_trend=0.5, w_flow=0.3, w_meanrev=0.2),
        temperature=1.25,
        threshold=0.62,
        calibration=CalibrationEvidence(brier=0.18, reliability=0.81),
        code_version=_CODE_VERSION,
        param_version=_PARAM_VERSION,
    )
    surv = SurvivalParameters(
        stop_out_level_pct=55.0,
        safe_mode_buffer_pct=110.0,
        per_order_size_max=0.8,
        speculative_sleeve_cap_pct=8.0,
        flatten_lead_seconds=300.0,
        assess_max_latency_seconds=5.0,
        exclusion_enabled=True,
        code_version=_CODE_VERSION,
        param_version=_PARAM_VERSION,
    )
    return Candidate(param_snapshot=snap, survival_parameters=surv, code_version=None)


def _seed_audit_row(cur) -> None:
    """INSERT one audit row via the mig-053 column set (unguarded INSERT;
    idempotent — deterministic audit_id + ON CONFLICT DO NOTHING). Uses the same
    SQL shape `audit.py` writes."""
    audit = _promote_audit()
    cur.execute(
        """
        INSERT INTO walkforward_tuner_audit
            (audit_id, run_id, code_version, param_version, walk_forward_window,
             promoted, track, gate_metrics, hypothesis)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (audit_id) DO NOTHING
        """,
        (
            audit.audit_id,
            audit.run_id,
            audit.code_version,
            audit.param_version,
            audit.walk_forward_window,
            audit.promoted,
            audit.track,
            Jsonb(audit.gate_metrics),
            Jsonb(audit.hypothesis),
        ),
    )


# --------------------------------------------------------------------------- #
# (1) mig-053 GUARD — append-only: UPDATE, DELETE, TRUNCATE all rejected.      #
# --------------------------------------------------------------------------- #


def test_walkforward_tuner_audit_rejects_update_delete_and_truncate(
    conn053, expect_rejection
):
    """`walkforward_tuner_audit` is append-only (R8.1/8.4): UPDATE / DELETE /
    TRUNCATE rejected.

    Seed one row (idempotent: deterministic uuid5 + ON CONFLICT DO NOTHING; the
    INSERT is unguarded — the guard is BEFORE UPDATE/DELETE/TRUNCATE only) so the
    row-level trigger has a row to fire against, then prove all three forbidden
    ops raise. The TRUNCATE case is the one a plain row-level UPDATE/DELETE guard
    would MISS — it exercises the separate statement-level BEFORE TRUNCATE
    trigger, so this would FAIL if that trigger were absent even though
    UPDATE/DELETE still passed (mirrors mig 048's stricter guard).

    The TRUNCATE probe is BARE (no CASCADE): unlike the survival-gate precedent,
    this table has NO inbound FK (mig-053 header), so a bare TRUNCATE reaches the
    statement-level trigger directly → P0001, caught by `expect_rejection`.
    """
    audit_id = A.mint_audit_id(run_id=_RUN_ID)
    with conn053.cursor() as cur:
        _seed_audit_row(cur)

    # UPDATE rejected (any column → here, flip the verdict).
    expect_rejection(
        conn053,
        "UPDATE walkforward_tuner_audit SET promoted = FALSE WHERE audit_id = %s",
        (audit_id,),
    )
    # DELETE rejected.
    expect_rejection(
        conn053,
        "DELETE FROM walkforward_tuner_audit WHERE audit_id = %s",
        (audit_id,),
    )
    # BARE TRUNCATE rejected — reaches the statement-level BEFORE TRUNCATE guard
    # directly (no inbound FK, so no CASCADE / FeatureNotSupported shadow). This
    # is the case a plain row-level guard would MISS.
    expect_rejection(conn053, "TRUNCATE walkforward_tuner_audit")

    # The seeded row survives all three rejected probes (savepoints rolled back).
    with conn053.cursor() as cur:
        cur.execute(
            "SELECT promoted, track FROM walkforward_tuner_audit WHERE audit_id = %s",
            (audit_id,),
        )
        row = cur.fetchone()
        assert row is not None, "seeded audit row missing after rejection probes"
        assert row == (True, "param")


# --------------------------------------------------------------------------- #
# (2) THE 4-KEY JOIN — audit row joins the seeded decision_process_trace row.  #
# --------------------------------------------------------------------------- #


def _seed_trace_row(cur) -> str:
    """INSERT one `decision_process_trace` (mig 048) row carrying the SAME four
    correlation keys (idempotent: deterministic trace_id + ON CONFLICT). Returns
    the trace_id."""
    trace_id = str(uuid.uuid5(_NS, "trace_id"))
    cur.execute(
        """
        INSERT INTO decision_process_trace
            (trace_id, kind, event_ts, run_id, code_version, param_version,
             walk_forward_window, trace)
        VALUES (%s, %s, now(), %s, %s, %s, %s, %s)
        ON CONFLICT (trace_id) DO NOTHING
        """,
        (
            trace_id,
            "decision",
            _RUN_ID,
            _CODE_VERSION,
            _PARAM_VERSION,
            _WALK_FORWARD_WINDOW,
            Jsonb({"probe": "task-4.3-join", "symbol": "AAPL"}),
        ),
    )
    return trace_id


def test_audit_row_joins_decision_trace_by_four_correlation_keys(conn053):
    """An audit row joins to a seeded `decision_process_trace` row by the FOUR
    correlation keys (R8.3 — the audit surface is separate-but-correlated, R8.4).

    Both rows are seeded with the SAME non-null (run_id, code_version,
    param_version, walk_forward_window) — a PROMOTE audit, so `walk_forward_window`
    is non-null on both (a four-`=` join silently returns nothing if either side
    is NULL, since `=` never matches NULL=NULL). The join then resolves the
    audit's verdict + hypothesis alongside the trace's row by value, with no FK.
    """
    audit_id = A.mint_audit_id(run_id=_RUN_ID)
    with conn053.cursor() as cur:
        _seed_audit_row(cur)
        trace_id = _seed_trace_row(cur)

    with conn053.cursor() as cur:
        cur.execute(
            """
            SELECT a.audit_id, t.trace_id, a.promoted, a.walk_forward_window
            FROM walkforward_tuner_audit a
            JOIN decision_process_trace t
              ON  a.run_id              = t.run_id
              AND a.code_version        = t.code_version
              AND a.param_version       = t.param_version
              AND a.walk_forward_window = t.walk_forward_window
            WHERE a.audit_id = %s
            """,
            (audit_id,),
        )
        rows = cur.fetchall()

    assert len(rows) == 1, (
        f"the 4-key join must resolve exactly one (audit, trace) pair, got {rows!r}"
    )
    joined = rows[0]
    # psycopg adapts the uuid columns back to uuid.UUID; the minted ids are str
    # (mint_audit_id / _seed_trace_row return str). Wrap to compare like-for-like —
    # `UUID == str` is always False (cf. the str(version_id) precedent below).
    assert str(joined[0]) == audit_id
    assert str(joined[1]) == trace_id
    assert joined[2] is True  # the promote verdict rides through the join
    assert joined[3] == _WALK_FORWARD_WINDOW  # the non-null key that made it match


# --------------------------------------------------------------------------- #
# (2b) write_audit live path — the real leaf appends a joinable row.           #
# --------------------------------------------------------------------------- #


def test_write_audit_live_appends_a_joinable_row(conn053):
    """`audit.write_audit(conn=live)` appends one append-only row through the real
    leaf, and that row joins the trace by the four keys (the leaf's own SQL, not a
    hand-rolled INSERT). Idempotent on the cycle (deterministic audit_id + ON
    CONFLICT), so a re-run on the shared DB is a clean no-op."""
    with conn053.cursor() as cur:
        _seed_trace_row(cur)

    out = A.write_audit(_promote_audit(), conn=conn053)
    # Either a fresh write (1) or a resume no-op (0) on a re-run — both are valid
    # against the shared, append-only DB (the row is guaranteed present either way).
    assert out["written"] in (0, 1)

    audit_id = A.mint_audit_id(run_id=_RUN_ID)
    with conn053.cursor() as cur:
        cur.execute(
            """
            SELECT a.audit_id
            FROM walkforward_tuner_audit a
            JOIN decision_process_trace t
              USING (run_id, code_version, param_version, walk_forward_window)
            WHERE a.audit_id = %s
            """,
            (audit_id,),
        )
        assert cur.fetchone() is not None, (
            "the leaf-written audit row must join the trace by the 4 keys"
        )


# --------------------------------------------------------------------------- #
# (3) THE PUBLISH ROUND-TRIP — parameters_active resolves + boundary stamped.  #
# --------------------------------------------------------------------------- #


def test_publish_roundtrip_resolves_parameters_active_and_stamps_boundary(conn053):
    """A PROMOTE `publish` writes resolvable `parameters_active` rows (R7.1) +
    stamps the advanced `walk_forward_window` boundary label (R7.3/1.4).

    Wrapped in a transaction that is ROLLED BACK: publish writes the EXACT
    `reactive.*` / `survival.*` keys the daemon resolves from `parameters_active`,
    so a COMMIT would hijack the shared dev DB's active params for every other
    consumer. The autocommit `conn053` makes publish's own inner
    `conn.transaction()` a SAVEPOINT inside ours. `now()` is constant within the
    transaction, so the inserted `effective_at = now()` satisfies the view's
    `effective_at <= now()` and the new row wins the latest-effective_at race
    IN-TRANSACTION — the read-back (before rollback) proves resolution.

    We assert on the VALUE + the minted version_id, NOT a row count: the shared DB
    already holds `reactive.threshold` etc., so our row resolves only via the
    latest effective_at.
    """
    verdict = _promote_verdict()
    candidate = _candidate()
    boundary_key = P._BOUNDARY_KEY  # "walkforward.walk_forward_window"

    try:
        with conn053.transaction():
            out = P.publish(
                verdict,
                candidate,
                run_id=_RUN_ID,
                advanced_window=_WALK_FORWARD_WINDOW,
                conn=conn053,
            )
            assert out["promoted"] is True
            # reactive(7) + survival(7) + boundary(1) = 15 freshly-written rows
            # (the deterministic version_ids are unique to this run_id, so a
            # rolled-back prior run left none behind → all 15 land here).
            assert out["written"] == 15, (
                f"a promote must write all 15 P2 rows, got {out['written']}"
            )

            with conn053.cursor() as cur:
                # (a) parameters_active RESOLVES to the tuned reactive value. The
                # view is DISTINCT ON (parameter_key) ORDER BY effective_at DESC;
                # our row's effective_at = now() (this txn) wins over any prior.
                cur.execute(
                    "SELECT value, version_id FROM parameters_active "
                    "WHERE parameter_key = %s",
                    ("reactive.threshold",),
                )
                row = cur.fetchone()
                assert row is not None, "reactive.threshold must resolve in parameters_active"
                value, version_id = row
                # JSONB scalar comes back as a native python float here.
                assert value == 0.62, f"parameters_active did not resolve to the tuned value: {value!r}"
                # The active row is OUR published row (the deterministic version_id).
                assert str(version_id) == P.mint_version_id(
                    run_id=_RUN_ID, parameter_key="reactive.threshold"
                ), "the active reactive.threshold row must be the one publish minted"

                # (b) a survival.* threshold resolves too (R7.1 — both namespaces).
                cur.execute(
                    "SELECT value FROM parameters_active WHERE parameter_key = %s",
                    ("survival.stop_out_level_pct",),
                )
                surv_row = cur.fetchone()
                assert surv_row is not None
                assert surv_row[0] == 55.0

                # (c) the advanced walk_forward_window boundary label is stamped +
                # resolvable (R7.3/1.4 — discoverable to the daemon at hot-swap).
                cur.execute(
                    "SELECT value FROM parameters_active WHERE parameter_key = %s",
                    (boundary_key,),
                )
                stamp = cur.fetchone()
                assert stamp is not None, "the boundary label must be stamped into P2"
                assert stamp[0] == _WALK_FORWARD_WINDOW, (
                    f"the stamped boundary must be the advanced window: {stamp[0]!r}"
                )

            # NEVER commit — roll back so the shared dev DB's active params are
            # untouched (publish writes the real daemon-resolved keys).
            raise psycopg.Rollback()
    except psycopg.Rollback:
        pass


def test_publish_dry_run_touches_no_db():
    """The `conn=None` dry-run seam (R7.2-adjacent): shape + return the rows, open
    no connection, write NOTHING.

    `conn=None` means publish literally cannot open a connection — `written == 0`
    plus the full shaped-row set (15 rows) prove the dry-run property completely.
    We deliberately do NOT probe `parameters_active` to "confirm nothing was
    written": that would assert a GLOBAL invariant (no committed
    `walkforward.walk_forward_window` row anywhere) on a dev DB shared across
    worktrees, which the real orchestrator (task 4.1) or another worktree's
    committed promote would false-fail — without revealing any real defect here."""
    out = P.publish(
        _promote_verdict(),
        _candidate(),
        run_id=_RUN_ID,
        advanced_window=_WALK_FORWARD_WINDOW,
        conn=None,
    )
    assert out["promoted"] is True
    assert out["written"] == 0  # dry-run writes nothing (no conn to write through)
    assert len(out["param_rows"]) == 15  # reactive(7) + survival(7) + boundary(1)
    assert out["boundary_row"]["value"] == _WALK_FORWARD_WINDOW


def test_publish_envelope_dry_run_serializes_for_disk():
    """A sanity check that the shaped rows are JSON-serializable (the orchestrator
    persists them) — a dry-run, no DB. The JSONB `value` of each row must survive
    a json round-trip (the live INSERT serializes them the same way)."""
    out = P.publish(
        _promote_verdict(),
        _candidate(),
        run_id=_RUN_ID,
        advanced_window=_WALK_FORWARD_WINDOW,
        conn=None,
    )
    reloaded = json.loads(json.dumps([r["value"] for r in out["param_rows"]]))
    assert _WALK_FORWARD_WINDOW in reloaded  # the boundary value round-trips
    assert 0.62 in reloaded  # the tuned reactive.threshold round-trips
