"""Shared pytest configuration for the tests/ tree.

Loads the repo-root `.env` once at collection time so env vars (notably
`EDGAR_USER_AGENT` for the EDGAR MCP server) are present before any test
imports the parallel subagents' `server` modules.

Also registers the ``integration`` marker used by ``test_e2e_integration.py``
so the slow end-to-end tests can be selected/skipped via ``pytest -m`` without
emitting an UnknownMarker warning.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

# Walk up to repo root from tests/conftest.py → repo root is parent of tests/.
_REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_REPO_ROOT / ".env")


def pytest_configure(config):
    """Register custom markers so collection doesn't emit warnings."""
    config.addinivalue_line(
        "markers",
        "integration: end-to-end multi-module integration tests (slow); "
        "select with `pytest -m integration` or skip with `pytest -m \"not integration\"`.",
    )
    config.addinivalue_line(
        "markers",
        "integration_live: live-Postgres smoke tests requiring a running "
        "Docker DB at 127.0.0.1:5432; skipped by default; select with "
        "`pytest -m integration_live`.",
    )


def pytest_collection_modifyitems(config, items):
    """Skip integration_live tests unless explicitly selected via -m.

    Without this hook, ``pytest tests/`` would attempt to connect to
    Postgres for every live-smoke test on every run.
    """
    import pytest as _pytest

    selected = config.getoption("-m", default="") or ""
    if "integration_live" in selected:
        return
    skip_marker = _pytest.mark.skip(
        reason="live-DB smoke; run with `pytest -m integration_live`"
    )
    for item in items:
        if "integration_live" in item.keywords:
            item.add_marker(skip_marker)
