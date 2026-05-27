"""Pure-logic unit tests for src/mcp/evidence_persistence.py (P0-3).

These exercise the content-hash + body-serialization + fail-soft DSN logic
WITHOUT a live DB and without the psycopg driver. The actual INSERT path needs
a live Postgres and is flagged for manual verification in the report.

Loaded by file path under a unique module name (the MCP convention) so it does
not collide with the many `server`-named modules.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MOD_PATH = _REPO_ROOT / "src/mcp/evidence_persistence.py"


def _load():
    spec = importlib.util.spec_from_file_location(
        "evidence_persistence_under_test", _MOD_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["evidence_persistence_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_module_loads_without_psycopg_or_db():
    """Importing the helper must not require psycopg or any POSTGRES_* env."""
    mod = _load()
    assert hasattr(mod, "persist_document")
    assert hasattr(mod, "content_hash")
    assert hasattr(mod, "serialize_body")


def test_content_hash_is_sha256_hex():
    mod = _load()
    text = "the quick brown fox"
    expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert mod.content_hash(text) == expected
    assert len(mod.content_hash(text)) == 64


def test_content_hash_stable_and_distinguishes():
    mod = _load()
    assert mod.content_hash("a") == mod.content_hash("a")
    assert mod.content_hash("a") != mod.content_hash("b")


def test_serialize_body_passthrough_for_str():
    mod = _load()
    assert mod.serialize_body("raw filing text") == "raw filing text"


def test_serialize_body_json_for_dict_is_key_order_stable():
    mod = _load()
    a = mod.serialize_body({"b": 2, "a": 1})
    b = mod.serialize_body({"a": 1, "b": 2})
    # sorted keys => identical serialization => identical hash for same payload
    assert a == b
    assert json.loads(a) == {"a": 1, "b": 2}
    assert mod.content_hash(a) == mod.content_hash(b)


def test_dsn_returns_none_when_env_missing(monkeypatch):
    mod = _load()
    for var in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"):
        monkeypatch.delenv(var, raising=False)
    assert mod._dsn() is None


def test_dsn_assembled_when_env_present(monkeypatch):
    mod = _load()
    monkeypatch.setenv("POSTGRES_USER", "u")
    monkeypatch.setenv("POSTGRES_PASSWORD", "p")
    monkeypatch.setenv("POSTGRES_DB", "equity_research")
    monkeypatch.setenv("POSTGRES_HOST", "host")
    monkeypatch.setenv("POSTGRES_PORT", "6543")
    assert mod._dsn() == "postgresql://u:p@host:6543/equity_research"


def test_persist_document_failsoft_returns_none_without_db(monkeypatch):
    """No POSTGRES_* env => persist is a silent no-op returning None, never raises."""
    mod = _load()
    for var in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"):
        monkeypatch.delenv(var, raising=False)
    # Must not raise even with a non-string body.
    assert mod.persist_document("sec://10-K/AAPL/2024", {"facts": 1}, "edgar") is None
