"""Fail-soft persistence of fetched source-document bodies to evidence_documents.

Phase-0 (P0-3) helper shared by the edgar / market_data / fundamentals MCP
servers. At fetch time each server calls ``persist_document`` with the raw
body it just retrieved, keyed to a ``source_uri``. The body is stored in the
``evidence_documents`` table (migration 046) so a downstream scorer can later
fetch the actual grounding passage behind an ``evidence_index`` reference.

Design constraints (per the parallel plan + advisor review):

- **Additive / non-breaking.** Callers invoke this *after* building their
  normal return dict and *ignore* its return value for tool-shape purposes.
  Nothing about the existing MCP tool return shapes changes.

- **Fail-soft.** MCP servers run in environments where ``POSTGRES_*`` env vars
  may be unset (offline sample-memo generation, CI without a DB) and where the
  ``psycopg`` driver may not be importable. Any failure to persist is logged at
  WARNING and swallowed — a fetch tool must NEVER raise because the audit write
  failed. ``persist_document`` returns the ``document_id`` on success or
  ``None`` on any skip/failure.

- **Idempotent / dedupe.** ``content_hash = sha256(raw_text)``. The insert is
  ``ON CONFLICT (source_uri, content_hash) DO NOTHING`` so a re-fetch of the
  same body does not pile up duplicate rows.

The DSN is assembled from the same ``POSTGRES_*`` env vars the postgres MCP
server uses (``src/mcp/postgres/server.py``).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any

_LOG = logging.getLogger(__name__)


def content_hash(raw_text: str) -> str:
    """Return the lowercase-hex sha256 of ``raw_text`` (the dedupe key).

    Pure function — unit-testable without a DB or any driver.
    """
    return hashlib.sha256(raw_text.encode("utf-8")).hexdigest()


def serialize_body(body: Any) -> str:
    """Coerce a fetched body into the canonical ``raw_text`` string.

    - ``str`` passes through unchanged (e.g. EDGAR filing text).
    - anything else (dict/list price payloads, etc.) is JSON-serialized with
      sorted keys so the same logical payload hashes identically across runs.

    Pure function — unit-testable without a DB.
    """
    if isinstance(body, str):
        return body
    return json.dumps(body, sort_keys=True, default=str, ensure_ascii=False)


def _dsn() -> str | None:
    """Assemble the Postgres DSN, or return None if required vars are unset.

    Mirrors ``src/mcp/postgres/server.py::_dsn`` but tolerates missing vars by
    returning None instead of raising KeyError — that is what makes persistence
    fail-soft in offline/CI environments.
    """
    user = os.environ.get("POSTGRES_USER")
    password = os.environ.get("POSTGRES_PASSWORD")
    db = os.environ.get("POSTGRES_DB")
    if not (user and password and db):
        return None
    host = os.environ.get("POSTGRES_HOST", "127.0.0.1")
    port = os.environ.get("POSTGRES_PORT", "5432")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def persist_document(
    source_uri: str,
    body: Any,
    fetched_by: str | None = None,
) -> str | None:
    """Persist a fetched body to evidence_documents. Fail-soft.

    Args:
        source_uri: the canonical identifier the body was fetched under (same
            vocabulary as ``evidence_index.source_uri`` so scorers can JOIN).
        body: the fetched body — a string (filing text) or a JSON-serializable
            object (price/fundamentals payload). Serialized via ``serialize_body``.
        fetched_by: optional provenance tag (the MCP server name).

    Returns:
        The inserted ``document_id`` (UUID string) on success, or ``None`` if
        persistence was skipped (no DB configured / driver missing) or failed,
        or if the row already existed (ON CONFLICT DO NOTHING).

    Never raises — any error is logged at WARNING and swallowed.
    """
    dsn = _dsn()
    if dsn is None:
        _LOG.debug(
            "evidence_documents persistence skipped: POSTGRES_* env not set "
            "(source_uri=%s)",
            source_uri,
        )
        return None

    try:
        import psycopg  # local import so missing driver is a soft skip
    except Exception as exc:  # pragma: no cover - exercised only without driver
        _LOG.warning(
            "evidence_documents persistence skipped: psycopg unavailable (%s)",
            exc,
        )
        return None

    try:
        raw_text = serialize_body(body)
        digest = content_hash(raw_text)
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO evidence_documents
                        (source_uri, raw_text, content_hash, fetched_by)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (source_uri, content_hash) DO NOTHING
                    RETURNING document_id
                    """,
                    (source_uri, raw_text, digest, fetched_by),
                )
                row = cur.fetchone()
        return str(row[0]) if row else None
    except Exception as exc:  # pragma: no cover - requires live DB to hit
        _LOG.warning(
            "evidence_documents persistence failed for source_uri=%s: %s: %s",
            source_uri,
            type(exc).__name__,
            exc,
        )
        return None
