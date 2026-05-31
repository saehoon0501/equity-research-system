"""Broker-import seam — the one place the daemon imports the broker leaf.

Source of truth: ``.kiro/specs/execution-daemon/design.md`` — "Allowed
Dependencies → In-process leaf imports (never via MCP): ``broker-cfd-adapter``
``core`` (``submit_decision``, ``get_positions`` …) … ``broker.models``" and the
File Structure Plan. Requirements: 3 (paper-mode lifecycle drives
``submit_decision``), 10 (leaf-executor boundary — venue actions obtained from
the owning dependency, never re-implemented), 11 (order construction consumes
``Position`` / ``Direction`` / ``OrderIntent``).

Why this module exists (the import landmine, verified against landed code)
--------------------------------------------------------------------------
``src/mcp/broker/`` is a self-contained ``uv`` package (``pyproject.toml`` with
``package = false``) and has **no ``__init__.py``**, so it is not a dotted
Python package. Its production modules use **flat imports** — ``core.py`` does
``import config`` / ``import gate_client`` / ``from models import ...`` (the MCP
runtime launches the server as ``python server.py`` with the broker dir on
``sys.path[0]``, so the flat names resolve there). Consequences:

  * The dotted path ``from src.mcp.broker.core import submit_decision`` **fails**
    — ``core``'s top-level ``import config`` raises
    ``ModuleNotFoundError: No module named 'config'`` (there is no top-level
    ``config`` module on the daemon's path).
  * ``core`` is importable **only** with ``src/mcp/broker`` itself on
    ``sys.path`` so the bare sibling names (``config`` / ``gate_client`` /
    ``mappers`` / ``paper`` / ``symbol_cache`` / ``validation`` / ``models``)
    resolve.
  * ``broker.models.Label`` is a transitive re-export of
    ``src.calibration.scorer.Label`` (``models.py:57``); ``models.py``
    self-bootstraps the repo root onto ``sys.path`` for that import, so the seam
    only needs to add the **broker directory** — the repo-root bootstrap is
    already handled inside ``models.py``.

The scoping constraint (load-bearing — task 1.4)
------------------------------------------------
Leaving ``src/mcp/broker`` permanently on ``sys.path`` would let a future bare
``import config`` *anywhere* in the daemon interpreter silently resolve to the
broker's ``config`` (a latent global-shadowing hazard — gap-analysis G2, probe
dim 5). So the seam inserts the broker dir on ``sys.path`` **only for the
duration of the broker import** and removes it in a ``finally``. The imported
broker modules stay cached in ``sys.modules`` under their bare names (which
``core`` needs to keep functioning after the path is gone — Python resolves
already-imported modules from the cache, not the path), but **no
broker-package directory lingers on ``sys.path``** to capture an unrelated
future bare import.

This module is the boundary: nothing else in the daemon imports the broker
package directly. The daemon binds to the four symbols re-exported here.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Optional

# ``broker_seam.py`` lives at <repo>/src/reactive/daemon/broker_seam.py:
#   parents[0] = .../src/reactive/daemon
#   parents[1] = .../src/reactive
#   parents[2] = .../src
#   parents[3] = <repo root>
# The broker package is the self-contained uv dir at <repo>/src/mcp/broker.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_BROKER_DIR = _REPO_ROOT / "src" / "mcp" / "broker"


def _import_broker_module(name: str) -> ModuleType:
    """Import a flat broker module by its bare name under a scoped ``sys.path``.

    Inserts ``_BROKER_DIR`` at the front of ``sys.path`` (so the broker's flat
    ``import config`` / ``from models import ...`` resolve), imports ``name``,
    then removes the path entry it added — leaving the module cached in
    ``sys.modules`` but no broker dir on ``sys.path``. Idempotent: a module
    already cached is returned from the cache without re-inserting the path.

    Defense-in-depth (P6): the path removal runs in ``finally`` so a failed
    broker import never leaves the broker dir lingering on ``sys.path``.
    """
    cached = sys.modules.get(name)
    if isinstance(cached, ModuleType):
        return cached

    broker_dir = str(_BROKER_DIR)
    inserted = False
    if broker_dir not in sys.path:
        sys.path.insert(0, broker_dir)
        inserted = True
    try:
        return importlib.import_module(name)
    finally:
        # Remove only the entry we added — never disturb a path some other
        # component owns. Remove every occurrence we are responsible for so a
        # re-entrant call cannot accumulate duplicates.
        if inserted:
            while broker_dir in sys.path:
                sys.path.remove(broker_dir)


# --- resolve the broker leaf modules through the scoped seam ---------------- #
# ``models`` first: it self-bootstraps the repo root for ``Label`` and defines
# the value objects ``core`` re-imports. ``core`` then re-exports those same
# objects, so importing ``models`` first keeps a single resolution. ``config``
# carries the ``RuntimeMode`` the paper-lifecycle driver pins to paper (task 4.2).
_models = _import_broker_module("models")
_config = _import_broker_module("config")
_core = _import_broker_module("core")

# --- the four symbols the daemon binds to (plus the transitive Label) ------- #
# Leaf venue functions (Req 3 paper lifecycle / Req 10 obtained-from-dependency):
submit_decision = _core.submit_decision
get_positions = _core.get_positions
# Account-level readout (the survival ``AccountState`` account scalars + the
# mt5-account-derived activation flag — the loop assembles the fresh per-tick
# survival ``AccountState`` from this + ``get_positions`` via ``account_state``).
get_account_assets = _core.get_account_assets

# Value objects (Req 11 order construction; Req 10 no self-computed venue types):
Position = _models.Position
AccountAssets = _models.AccountAssets  # the account-level readout shape
Direction = _models.Direction  # broker str-Enum venue side (LONG / SHORT)
OrderIntent = _models.OrderIntent
OrderResult = _models.OrderResult  # the terminal-outcome carrier (Req 3 lifecycle)
# P9 canonical decision vocabulary, transitively re-exported from
# ``src.calibration.scorer`` by ``models.py`` (the seam resolves it).
Label = _models.Label

# The runtime-mode gate (Req 3.1 paper-only) — the paper-lifecycle driver pins
# ``paper_enabled=True`` so ``submit_decision`` can never route to ``_submit_live``
# (``live_transmit_allowed()`` is False while paper is on, by construction).
RuntimeMode = _config.RuntimeMode


def account_activated(*, clients: Optional[Any] = None) -> bool:
    """Read the broker account-activation flag (the survival
    ``AccountState.activated`` source — broker mt5-account ``status``).

    Delegates to the broker leaf's own ``_resolve_account_active`` (the documented
    source of truth: mt5-account venue ``status``, only ``3`` = active), under a
    conservative **paper** ``RuntimeMode`` (the safe-default fallback when the
    venue read omits ``status``). The loop assembles the per-tick survival
    ``AccountState`` from this + ``get_account_assets`` + ``get_positions`` via
    ``account_state.build_account_state`` — the activation flag is a genuine venue
    readout, never invented daemon-side (Req 10.2).

    Args:
        clients: an optional broker ``ReadoutClients`` (a mock-transport-backed
            holder in the integration test); ``None`` uses the broker's production
            memoized clients (``default_clients``).

    Returns:
        ``True`` iff the venue mt5-account status reads active; conservatively
        ``False`` on an omitted status under the paper default.
    """
    c = clients if clients is not None else _core.default_clients()
    return _core._resolve_account_active(c, runtime_mode=_config.RuntimeMode())

__all__ = [
    "submit_decision",
    "get_positions",
    "get_account_assets",
    "account_activated",
    "Position",
    "AccountAssets",
    "Direction",
    "OrderIntent",
    "OrderResult",
    "Label",
    "RuntimeMode",
]
