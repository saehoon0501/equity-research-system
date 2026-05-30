"""Execution Daemon — the persistent, non-LLM fast-clock process.

The only component that *runs* the four foundation leaf modules — the broker
adapter (Route), the reactive signal model (Edge), the survival gate (Survive),
and the decision-trace store (the trace) — on a single-threaded evaluation
loop, enforcing the §13 lexicographic chain Survive ⊳ Preserve ⊳ Edge ⊳ Return.

This package rides the existing ``src.reactive`` namespace (no pyproject/uv).
It is a **leaf executor and event emitter only** (P1) — it never dispatches an
agent and never re-computes the survival, edge, or sizing logic its
dependencies own (Requirement 10).

Task 1.2 scope: ``config`` (``_dsn()`` + ``DaemonConfig``) and ``db`` (the
owned psycopg3 connection lifecycle). Importing this package builds nothing and
opens no connection — the connection lifecycle is explicit in ``db.py``.
"""

from __future__ import annotations

from src.reactive.daemon.config import DaemonConfig, _dsn
from src.reactive.daemon.db import DaemonConnection

__all__ = ["DaemonConfig", "DaemonConnection", "_dsn"]
