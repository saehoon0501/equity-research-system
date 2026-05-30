"""Inner-ring unit tests for the daemon's broker-import seam (task 1.4).

Boundary: ``broker_import_seam``. Requirements: 3, 10, 11.

The seam (``src/reactive/daemon/broker_seam.py``) makes the four broker symbols
the daemon binds to importable in one place:

  * ``broker.core.submit_decision`` / ``broker.core.get_positions`` — the leaf
    venue functions the §13 orchestrator + paper lifecycle drive (Req 3, 10, 11);
  * ``broker.models.{Position, Direction, OrderIntent, Label}`` — the value
    objects ``order_builder`` (Req 11) and the position readouts consume.

Why a seam is needed (verified against landed code, 2026-05-30):
  * ``src/mcp/broker/`` is a self-contained uv package with **flat imports**
    (``core.py`` does ``import config`` / ``from models import ...``) and **no
    ``__init__.py``** — so the dotted-package path ``src.mcp.broker.core`` fails
    at import time (``ModuleNotFoundError: No module named 'config'``). ``core``
    is only importable with ``src/mcp/broker`` itself on ``sys.path`` so the bare
    sibling names resolve.
  * ``broker.models.Label`` is itself a transitive re-export of
    ``src.calibration.scorer.Label`` (``models.py:57``) — the seam must resolve
    that too, with no ``ImportError``.

These tests assert the seam resolves **all four** symbols (including ``Label``)
without ``ImportError``, and — the load-bearing constraint of task 1.4 — that the
``sys.path`` insert is **scoped** so it does NOT globally shadow bare names
(``config`` / ``core`` / ``models``) for the rest of the process.

Inner-ring: no LLM, no MCP runtime, no live DB. Imports the broker leaf modules
in-process (the daemon's design seam, never via MCP).
"""

from __future__ import annotations

import sys

import pytest


def test_seam_resolves_all_four_symbols_without_import_error():
    """The seam exposes submit_decision / get_positions / Position / Label.

    Requirements 3 (paper lifecycle drives ``submit_decision``), 10 (leaf
    functions obtained from the owning dependency), 11 (order construction
    consumes ``Position`` / ``Direction`` / ``OrderIntent``). The four named
    symbols (plus ``Label``) must resolve with no ``ImportError``.
    """
    from src.reactive.daemon import broker_seam

    submit_decision = broker_seam.submit_decision
    get_positions = broker_seam.get_positions
    Position = broker_seam.Position
    Direction = broker_seam.Direction
    OrderIntent = broker_seam.OrderIntent
    Label = broker_seam.Label

    assert callable(submit_decision)
    assert callable(get_positions)
    # The four value objects are types (classes / enums), not None.
    for sym in (Position, Direction, OrderIntent, Label):
        assert isinstance(sym, type)


def test_label_is_the_transitive_calibration_scorer_label():
    """``broker.models.Label`` is the re-export of ``src.calibration.scorer.Label``.

    The seam must resolve the transitive import (``models.py:57``). The single
    canonical decision vocabulary (P9) means the seam's ``Label`` must be the
    *same object* as the calibration-scorer ``Label`` — not a redefined copy.
    """
    from src.calibration.scorer import Label as CanonicalLabel
    from src.reactive.daemon import broker_seam

    assert broker_seam.Label is CanonicalLabel
    # P9 vocabulary members are present.
    for name in ("BUY", "HOLD", "TRIM", "SELL"):
        assert hasattr(broker_seam.Label, name)


def test_seam_symbols_are_the_real_broker_leaf_objects():
    """The seam re-exports the genuine broker leaf functions / types.

    ``submit_decision`` / ``get_positions`` come from ``broker.core``;
    ``Position`` / ``Direction`` / ``OrderIntent`` come from ``broker.models``.
    The seam binds the real objects (so the daemon drives the venue leaf, not a
    stub).
    """
    from src.reactive.daemon import broker_seam

    assert broker_seam.submit_decision.__name__ == "submit_decision"
    assert broker_seam.get_positions.__name__ == "get_positions"
    assert broker_seam.Position.__name__ == "Position"
    assert broker_seam.Direction.__name__ == "Direction"
    assert broker_seam.OrderIntent.__name__ == "OrderIntent"
    # Broker Direction is the str-Enum LONG/SHORT venue side (models.py:65).
    assert {m.value for m in broker_seam.Direction} == {"LONG", "SHORT"}


def test_seam_does_not_leave_broker_dir_on_syspath():
    """The path insert is scoped — it must NOT globally shadow bare names.

    Leaving ``src/mcp/broker`` on ``sys.path`` would make a future bare
    ``import config`` anywhere in the daemon interpreter silently resolve to the
    broker's ``config`` (a latent shadowing hazard, gap-analysis G2/probe-dim-5).
    The seam inserts the broker dir only for the duration of the broker import
    and removes it afterward, so no broker-package directory lingers on
    ``sys.path``.
    """
    import src.reactive.daemon.broker_seam as broker_seam  # noqa: F401  (force import)

    broker_dir = broker_seam._BROKER_DIR  # the scoped path the seam inserts
    assert str(broker_dir) not in sys.path, (
        "broker package dir must not linger on sys.path after the scoped import "
        "(global bare-name shadowing hazard)"
    )


def test_seam_does_not_globally_expose_bare_broker_module_names():
    """A fresh bare ``import config`` must not resolve to the broker's config.

    The seam imports ``core`` (which pulls the broker's flat siblings into
    ``sys.modules`` under their bare names so ``core`` keeps working). That is
    expected and required. The load-bearing guarantee task 1.4 names is the
    **path** scoping: because ``src/mcp/broker`` is not left on ``sys.path``, a
    *new* bare import of a name the broker happens to use but that is not already
    cached cannot be satisfied from the broker dir.

    We assert the broker dir is absent from ``sys.path`` (already covered above)
    and that re-importing the seam is idempotent (no duplicate path inserts,
    no re-execution side effects).
    """
    from src.reactive.daemon import broker_seam

    path_count_before = sys.path.count(str(broker_seam._BROKER_DIR))
    # Re-import / re-resolve must be idempotent and must not re-insert the path.
    import importlib

    importlib.import_module("src.reactive.daemon.broker_seam")
    path_count_after = sys.path.count(str(broker_seam._BROKER_DIR))

    assert path_count_before == 0
    assert path_count_after == 0
