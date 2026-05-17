"""Smoke tests for the mechanical contamination check MCP server.

Covers the test cases in `src/mcp/contamination_check/DESIGN.md` §7, which
mirrors `.claude/references/contamination-check.md` "Test cases for week 6
implementation". Each case is one pytest function.

Fixtures are inserted directly via psycopg (not through the MCP server) — the
fixture layer is setup, not the system under test. UUIDs are deterministic
via `uuid.uuid5` from a fixed namespace so re-running is idempotent against
the append-only `evidence_index` table; inserts use ON CONFLICT DO NOTHING.

Run from repo root after both subagents finish:
    pytest tests/test_contamination_check.py -v
"""

from __future__ import annotations

import importlib.util
import os
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

import psycopg
import pytest
from dotenv import load_dotenv

# Load this MCP's `server.py` directly by file path under a unique module
# name; bare `from server import X` collides across MCP test files because
# every MCP module is named `server` and Python caches by module name.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SERVER_PATH = _REPO_ROOT / "src/mcp/contamination_check/server.py"
_spec = importlib.util.spec_from_file_location(
    "contamination_check_mcp_server", _SERVER_PATH
)
_module = importlib.util.module_from_spec(_spec)
sys.modules["contamination_check_mcp_server"] = _module
_spec.loader.exec_module(_module)

verify = _module.verify

# -----------------------------------------------------------------------------
# Fixed test namespace + deterministic UUIDs
# -----------------------------------------------------------------------------
NAMESPACE = uuid.UUID("00000000-0000-0000-0000-000000000099")
AGENT_ID = "test-fixture-contamination-check"

FIXTURE_UUID_PREDATING = uuid.uuid5(NAMESPACE, "predating-source")
FIXTURE_UUID_BOUNDARY = uuid.uuid5(NAMESPACE, "boundary-source")
FIXTURE_UUID_LATE = uuid.uuid5(NAMESPACE, "postdated-source")

# A UUID that is NOT inserted — used to trigger FABRICATED_UUID.
FIXTURE_UUID_FABRICATED = uuid.uuid5(NAMESPACE, "fabricated-never-inserted")

# Source dates per task spec.
SOURCE_DATE_PREDATING = date(2024, 6, 1)
SOURCE_DATE_BOUNDARY = date(2024, 9, 30)
SOURCE_DATE_LATE = date(2024, 12, 15)

# Fixture rows: (evidence_id, source_date, claim_text label).
_FIXTURE_ROWS = [
    (FIXTURE_UUID_PREDATING, SOURCE_DATE_PREDATING, "predating fixture row"),
    (FIXTURE_UUID_BOUNDARY, SOURCE_DATE_BOUNDARY, "boundary fixture row"),
    (FIXTURE_UUID_LATE, SOURCE_DATE_LATE, "postdated fixture row"),
]

# Single shared agent_run_id for the fixture rows themselves (the verify()
# calls use their own per-test agent_run_ids, derived via uuid5).
_FIXTURE_AGENT_RUN_ID = uuid.uuid5(NAMESPACE, "fixture-agent-run")


def _dsn() -> str:
    load_dotenv(_REPO_ROOT / ".env")
    user = os.environ["POSTGRES_USER"]
    password = os.environ["POSTGRES_PASSWORD"]
    host = os.environ.get("POSTGRES_HOST", "127.0.0.1")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ["POSTGRES_DB"]
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


@pytest.fixture(scope="session", autouse=True)
def _seed_evidence_index_fixtures():
    """Insert the deterministic fixture rows into evidence_index.

    No teardown — `evidence_index` is append-only by design. Deterministic
    uuid5 + ON CONFLICT DO NOTHING make this idempotent across reruns.
    """
    insert_sql = """
        INSERT INTO evidence_index (
            evidence_id, agent_id, agent_run_id,
            claim_text, claim_type, source_uri, source_date,
            source_quality_tier
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (evidence_id) DO NOTHING
    """
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            for evidence_id, source_date, label in _FIXTURE_ROWS:
                cur.execute(
                    insert_sql,
                    (
                        str(evidence_id),
                        AGENT_ID,
                        str(_FIXTURE_AGENT_RUN_ID),
                        f"test fixture: {label}",
                        "numerical",
                        "sec://10-K/TEST/2024",
                        source_date,
                        1,
                    ),
                )
        conn.commit()
    yield
    # No teardown.


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _run_id(label: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"run-{label}"))


def _failure_modes(result: dict) -> list[str]:
    return [f["failure_mode"] for f in result.get("failures", [])]


# -----------------------------------------------------------------------------
# Test cases (DESIGN.md §7)
# -----------------------------------------------------------------------------
def test_case1_pass():
    """Case 1 — PASS: claims all reference existing rows, source_date < resolution_date."""
    result = verify(
        agent_run_id=_run_id("case1"),
        evidence_index_refs=[str(FIXTURE_UUID_PREDATING)],
        claims=[
            {
                "claim_text": "Q3 2024 revenue grew 23%",
                "claim_type": "numerical",
                "evidence_id": str(FIXTURE_UUID_PREDATING),
                "resolution_date": "2024-09-30",
            }
        ],
    )
    assert result["verdict"] == "PASS"
    assert result["summary"]["n_claims"] == 1
    assert result["summary"]["n_refs"] == 1
    assert result["summary"]["n_failures"] == 0
    assert result.get("failures", []) == []


def test_case2_fabricated_uuid():
    """Case 2 — FAIL: one claim references a non-existent UUID."""
    result = verify(
        agent_run_id=_run_id("case2"),
        evidence_index_refs=[str(FIXTURE_UUID_FABRICATED)],
        claims=[
            {
                "claim_text": "Net debt is $2.4B",
                "claim_type": "numerical",
                "evidence_id": str(FIXTURE_UUID_FABRICATED),
                "resolution_date": date.today().isoformat(),
            }
        ],
    )
    assert result["verdict"] == "FAIL"
    assert "FABRICATED_UUID" in _failure_modes(result)
    assert result["summary"]["n_failures"] >= 1


def test_case3_postdated_source():
    """Case 3 — FAIL: source_date > resolution_date (the contamination signature)."""
    result = verify(
        agent_run_id=_run_id("case3"),
        evidence_index_refs=[str(FIXTURE_UUID_LATE)],
        claims=[
            {
                "claim_text": "Q3 2024 revenue grew 23%",
                "claim_type": "numerical",
                "evidence_id": str(FIXTURE_UUID_LATE),
                # Resolution = 2024-09-30, source = 2024-12-15 → POSTDATED.
                "resolution_date": "2024-09-30",
            }
        ],
    )
    assert result["verdict"] == "FAIL"
    assert "POSTDATED_SOURCE" in _failure_modes(result)
    assert result["summary"]["n_failures"] >= 1


def test_case4_empty_refs():
    """Case 4 — FAIL: evidence_index_refs=[] with non-qualitative claims."""
    result = verify(
        agent_run_id=_run_id("case4"),
        evidence_index_refs=[],
        claims=[
            {
                "claim_text": "Revenue grew 12%",
                "claim_type": "numerical",
                "evidence_id": None,
                "resolution_date": "2024-09-30",
            }
        ],
    )
    assert result["verdict"] == "FAIL"
    assert "EMPTY_REFS" in _failure_modes(result)


def test_case5_incoherent_prediction():
    """Case 5 — FAIL: prediction with target_date in the past (self-resolving)."""
    past_date = (date.today() - timedelta(days=30)).isoformat()
    result = verify(
        agent_run_id=_run_id("case5"),
        evidence_index_refs=[str(FIXTURE_UUID_PREDATING)],
        claims=[
            {
                "claim_text": "Revenue will grow 15% by Q1 2024",
                "claim_type": "prediction",
                "evidence_id": str(FIXTURE_UUID_PREDATING),
                # For predictions, resolution_date == prediction.target_date
                # per DESIGN.md §3 step 4. A date in the past is incoherent.
                "resolution_date": past_date,
            }
        ],
    )
    assert result["verdict"] == "FAIL"
    assert "INCOHERENT_PREDICTION" in _failure_modes(result)


def test_boundary_same_day_pass():
    """Boundary — PASS: source_date == resolution_date (same-day allowed)."""
    result = verify(
        agent_run_id=_run_id("boundary"),
        evidence_index_refs=[str(FIXTURE_UUID_BOUNDARY)],
        claims=[
            {
                "claim_text": "Filing dated 2024-09-30 confirms a 23% growth",
                "claim_type": "numerical",
                "evidence_id": str(FIXTURE_UUID_BOUNDARY),
                "resolution_date": "2024-09-30",
            }
        ],
    )
    assert result["verdict"] == "PASS"
    assert result["summary"]["n_failures"] == 0


def test_bonus_qualitative_no_evidence_id_pass():
    """Bonus — PASS: claim_type='qualitative' with no evidence_id (qualitative exempt)."""
    result = verify(
        agent_run_id=_run_id("bonus-qual"),
        evidence_index_refs=[str(FIXTURE_UUID_PREDATING)],
        claims=[
            {
                "claim_text": "The company has a strong competitive moat",
                "claim_type": "qualitative",
                "evidence_id": None,
                "resolution_date": None,
            }
        ],
    )
    assert result["verdict"] == "PASS"
    assert result["summary"]["n_failures"] == 0


def test_bonus_missing_ref_numerical_fail():
    """Bonus — FAIL: claim_type='numerical' with evidence_id=None → MISSING_REF."""
    result = verify(
        agent_run_id=_run_id("bonus-missing"),
        evidence_index_refs=[str(FIXTURE_UUID_PREDATING)],
        claims=[
            {
                "claim_text": "Revenue grew 23%",
                "claim_type": "numerical",
                "evidence_id": None,
                "resolution_date": "2024-09-30",
            }
        ],
    )
    assert result["verdict"] == "FAIL"
    assert "MISSING_REF" in _failure_modes(result)
