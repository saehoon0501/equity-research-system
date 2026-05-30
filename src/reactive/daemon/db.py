"""Daemon-owned psycopg3 connection lifecycle (task 1.2).

Boundary: db (Requirements 1, 3).

The repo has **no connection pool** and the house convention is a per-module
``_dsn()`` + a caller-passed ``conn`` (the telemetry writer's ``conn=None`` is
its dry-run path). The daemon is the caller that *owns* the connection: it opens
**one** psycopg3 connection at startup, serialized through the single-threaded
eval loop (Requirement 1 — at most one evaluation at a time; the loop already
serializes, so no pool and no dedicated write conn are needed), and passes that
``conn`` explicitly to ``write_decision_trace`` / ``write_fill_outcome`` and the
other persist paths.

``DaemonConnection`` is a thin lifecycle wrapper, not an ORM:

  * ``open()``    — open the single owned connection from the config DSN
                    (lazy: nothing is opened until ``open()`` is called, so
                    constructing the daemon stays side-effect-free).
  * ``conn``      — the live connection (raises if not yet opened).
  * ``cycle_transaction()`` — the per-cycle ``conn.transaction()`` context
                    manager the persist-then-act path (Req 5.1) runs each
                    evaluation cycle: a single atomic batch so a mid-cycle DB
                    error rolls the cycle's writes back together.
  * ``close()``   — close the owned connection (idempotent).
  * context-manager support so ``with DaemonConnection(cfg) as conn:`` opens
                    and guarantees close.

Importing this module opens no connection (P2 — the lifecycle is explicit).
"""

from __future__ import annotations

from types import TracebackType
from typing import Any

import psycopg

from src.reactive.daemon.config import DaemonConfig


class DaemonConnection:
    """The daemon's single owned psycopg3 connection + per-cycle transaction.

    One connection, serialized through the single-threaded loop. Open lazily via
    ``open()`` (or the context-manager ``__enter__``); the daemon owns its full
    lifecycle and is the sole writer through it.
    """

    def __init__(self, config: DaemonConfig) -> None:
        self._config = config
        self._conn: Any | None = None

    def open(self) -> Any:
        """Open the single owned connection from the config DSN.

        Idempotent: a second call returns the already-open connection rather
        than leaking a second one (the daemon owns exactly one).
        """
        if self._conn is None:
            self._conn = psycopg.connect(self._config.dsn)
        return self._conn

    @property
    def conn(self) -> Any:
        """The live owned connection. Raises if ``open()`` has not run."""
        if self._conn is None:
            raise RuntimeError(
                "DaemonConnection.conn accessed before open(); call open() first."
            )
        return self._conn

    @property
    def is_open(self) -> bool:
        """True once ``open()`` has run and the connection has not been closed."""
        return self._conn is not None

    def cycle_transaction(self) -> Any:
        """Return the per-cycle ``conn.transaction()`` context manager.

        The persist-then-act path (Req 5.1) wraps each evaluation cycle's writes
        in this single atomic transaction — a mid-cycle DB error rolls the whole
        cycle back, never leaving a half-persisted op-state transition.
        """
        return self.conn.transaction()

    def close(self) -> None:
        """Close the owned connection. Idempotent (no-op if never opened)."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> Any:
        return self.open()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
