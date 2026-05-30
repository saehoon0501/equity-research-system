"""`integration_live` inner-ring test for migration 050's `survival.*` param seed.

Task 2.2 (requirement 10 — pinned survival parameters consumed BY VALUE, no
fit, fail-closed; design.md "Data Models → `survival.*` parameters" + "Allowed
Dependencies" — the `parameters` / `parameters_active` / `run_parameters_snapshot`
machinery). Proves the migration's ONE observable invariant against the SHARED,
already-migrated dev DB:

  The active-parameters view (`parameters_active`, mig 004) returns EVERY
  `survival.*` key, and that key set is 1:1 with the float/bool fields of the
  pinned `SurvivalParameters` dataclass (the keys `params.resolve()` consumes).

WHY SET-EQUALITY, BOTH DIRECTIONS. The expected key set is derived from
`params.py` itself (`_FLOAT_KEYS` ∪ `_BOOL_KEYS` — already `survival.`-prefixed,
already excludes the run-identity version fields), NOT from design.md's narrative
6-key list (which OMITS `survival.assess_max_latency_seconds`; see CONCERNS in the
task report). A subset check would silently pass on the exact two mistakes this
seed must avoid: (a) the omitted 7th key, and (b) a stray version key
(`survival.code_version` / `survival.param_version`) wrongly placed in the
namespace. Equality catches both.

THE ROUND-TRIP IS THE STRONGEST ASSERTION. `resolve()` fails closed on a missing
key, so building a snapshot from the seeded rows and resolving it proves the seed
is complete + consumable + correctly-typed in one shot. `resolve()` also requires
the run-identity `code_version` / `param_version` (`_STR_KEYS`), which are
DELIBERATELY NOT seeded in `survival.*` (they are run-level identity, not
survival-domain thresholds — task brief + params.py docstring). So the test
INJECTS synthetic versions into the snapshot before resolving — it does NOT seed
them. The resolved object must equal `DEFAULTS` (with the injected versions),
proving seed-value == pinned production default, by value.

JSONB TYPING. Float keys are seeded as JSONB decimals (`'8.0'::jsonb`) and the
bool key as `'true'::jsonb`; psycopg3 decodes JSONB scalars to native
`float`/`bool`, so `resolve()`'s strict type coercion (which rejects a `bool` in
a numeric field and a non-bool in `exclusion_enabled`) passes only if the seed
used the right JSONB scalar type per field.

Reuses the task-1.3 harness (`tests/integration/conftest.py`): the `conn`
fixture (autocommit, chain guaranteed-applied — now `003→030→048→049→050`).
Connection/chain logic is NOT re-implemented here.

Non-destructive against the SHARED dev DB: the seed is additive + idempotent
(`WHERE NOT EXISTS … tag IS NULL`), the test only READS `parameters_active`.
NEVER `docker compose down` / `TRUNCATE` / wipe — the DB is shared across
worktrees. Run:

    PYTHONPATH="$PWD" uv run --with pytest --with python-dotenv \
        --with "psycopg[binary]" --python 3.13 \
        pytest tests/integration/test_survival_params_seed.py -m integration_live -q
"""

from __future__ import annotations

import dataclasses

import pytest

from src.survival import params

pytestmark = pytest.mark.integration_live


# The expected `survival.*` key set, derived from the resolver itself — the keys
# `params.resolve()` consumes by value. Already `survival.`-prefixed; already
# excludes the run-identity version fields (`_STR_KEYS`). This is the ground
# truth the seed must match 1:1.
_EXPECTED_SURVIVAL_KEYS = set(params._FLOAT_KEYS) | set(params._BOOL_KEYS)


def _active_survival_rows(conn) -> dict[str, object]:
    """Return the `survival.*` rows from the active-parameters view as a dict.

    Reads `parameters_active` (mig 004 — latest `effective_at` per
    `parameter_key`), the canonical "what's active now?" view that 038/039 query.
    psycopg3 decodes the JSONB `value` to a native Python scalar.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT parameter_key, value FROM parameters_active "
            "WHERE parameter_key LIKE 'survival.%%' "
            "ORDER BY parameter_key"
        )
        return {key: value for key, value in cur.fetchall()}


def test_active_view_returns_all_survival_keys_one_to_one(conn):
    """The active view returns EXACTLY the `survival.*` keys `resolve()` consumes.

    Set-equality (both directions) catches the two seed mistakes the brief warns
    of: the omitted `survival.assess_max_latency_seconds`, and a stray version
    key wrongly placed in the namespace.
    """
    seeded = _active_survival_rows(conn)
    assert set(seeded) == _EXPECTED_SURVIVAL_KEYS, (
        "seeded survival.* keys must be 1:1 with the fields resolve() consumes; "
        f"missing={_EXPECTED_SURVIVAL_KEYS - set(seeded)}, "
        f"extra={set(seeded) - _EXPECTED_SURVIVAL_KEYS}"
    )
    # All 7 (6 float + 1 bool) present — the explicit count guards against the
    # design-doc's 6-key narrative quietly re-asserting itself.
    assert len(seeded) == 7


def test_survival_keys_map_one_to_one_to_dataclass_fields(conn):
    """Each seeded `survival.<field>` corresponds to a `SurvivalParameters` field.

    Strip the `survival.` prefix and compare against the float/bool field names
    of the dataclass (i.e. all fields except the two run-identity version
    strings). Proves the namespace key ↔ dataclass field correspondence the
    observable requires.
    """
    seeded = _active_survival_rows(conn)
    seeded_fields = {key.removeprefix("survival.") for key in seeded}

    dataclass_fields = {f.name for f in dataclasses.fields(params.SurvivalParameters)}
    survival_domain_fields = dataclass_fields - {"code_version", "param_version"}

    assert seeded_fields == survival_domain_fields, (
        "each survival.* key must map 1:1 to a survival-domain dataclass field; "
        f"missing={survival_domain_fields - seeded_fields}, "
        f"extra={seeded_fields - survival_domain_fields}"
    )


def test_seed_round_trips_into_default_survival_parameters(conn):
    """The seeded values `resolve()` into `SurvivalParameters` == pinned DEFAULTS.

    This is the strongest assertion. Building a snapshot from the seeded rows and
    calling `resolve()` proves the seed is (a) complete — `resolve()` fails
    closed on any missing key, (b) correctly typed — `resolve()` rejects a bool
    in a float field or a non-bool `exclusion_enabled`, and (c) equal by value to
    the pinned production defaults.

    `resolve()` also requires the run-identity `code_version` / `param_version`
    (`_STR_KEYS`), which are NOT seeded in `survival.*` by design. We INJECT
    synthetic versions into the snapshot (we do NOT seed them); the expected
    object is `DEFAULTS` with those same versions substituted.
    """
    seeded = _active_survival_rows(conn)

    snapshot = dict(seeded) | {
        "code_version": "test-seed-round-trip",
        "param_version": "test-seed-round-trip",
    }
    resolved = params.resolve(snapshot)

    expected = dataclasses.replace(
        params.DEFAULTS,
        code_version="test-seed-round-trip",
        param_version="test-seed-round-trip",
    )
    assert resolved == expected
