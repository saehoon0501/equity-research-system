"""Inner-ring coverage completion for the broker CFD adapter — order path,
validation chain, gating, paper (Task 6.1).

This file is the *deliverable proving completeness* of the order-path / validation
/ gating / paper acceptance criteria. It does two things, both machine-checkable:

1. **Traceability map (below)** — for each of the 23 acceptance-criteria IDs in
   scope for Task 6.1, it names the EXISTING load-bearing test (file::function)
   that guarantees it. The map is encoded in ``REQUIREMENT_TO_TEST`` so it cannot
   drift from prose.
2. **Existence-assertions** — ``test_every_mapped_requirement_test_exists`` parses
   each referenced test module's AST and asserts every named test callable is
   present. If a referenced test is renamed or removed, this file turns RED — the
   map cannot silently rot into a stale set of names that no longer exist.

It also carries ONE focused, load-bearing **gap-fill** test for Req 7.3 at the
*order-path* level (see ``test_buy_without_volume_is_not_auto_sized_at_order_path``).
The validation layer already rejects a sizeless BUY
(``test_broker_validation.py::test_buy_with_missing_volume_rejects_out_of_bounds``),
but that is a pure-layer assertion; the *conservative-posture* clause of Req 7.3
("shall not perform position sizing ... it shall act only on the volume and side
supplied by the caller") had no end-to-end assertion that ``core.submit_decision``
refuses — rather than invents — a size when the caller omits volume. This test
closes that order-path seam.

No duplication: the 23 IDs are each COVERED by a pre-existing test (the per-task
TDD suite); this file does NOT re-test them — it pins the map to those tests and
adds only the single order-path strengthening above.

------------------------------------------------------------------------------
Requirement-ID -> load-bearing test traceability map (Task 6.1 scope, 23 IDs)
------------------------------------------------------------------------------

  1.1  BUY -> open/increase in caller direction
       test_broker_core_orders.py::test_buy_in_paper_mode_is_simulated_with_no_order_post
       (+ venue-side mapping: test_broker_mappers.py::test_buy_long_maps_to_buy_to_open_side_2
        / ::test_buy_short_maps_to_sell_to_open_side_1)

  1.2  TRIM -> partial close by position_id (not an opposing open)
       test_broker_core_orders.py::test_trim_existing_position_simulated_close_no_post

  1.3  SELL -> full close by position_id (not an opposing open)
       test_broker_core_orders.py::test_sell_existing_position_simulated_full_close

  1.4  HOLD -> structured no-op, transmits nothing
       test_broker_core_orders.py::test_hold_returns_noop_and_transmits_nothing

  1.5  only market/trigger order types (trigger needs a trigger price)
       test_broker_validation.py::test_trigger_without_trigger_price_rejects

  1.6  volume below min / above max (incl. the ~100-lot venue cap), margin-agnostic
       test_broker_validation.py::test_volume_above_venue_cap_rejects

  1.8  TRIM/SELL with no matching position -> reject, open NOTHING
       test_broker_core_orders.py::test_trim_with_no_position_is_rejected_no_open

  1.9  act ONLY on the caller-supplied position_id (never self-select)
       test_broker_mappers.py::test_trim_sell_use_caller_supplied_position_id_verbatim

  1.10 inactive account -> reject all order/close ops
       test_broker_core_orders.py::test_inactive_account_rejects

  1.11 trade_mode disallows the action (disabled/long-only/short-only/close-only)
       test_broker_validation.py::test_close_only_rejects_buy_open

  4.2  restrict to the US-stock CFD category; reject out-of-category
       test_broker_symbol_cache.py::test_out_of_category_symbol_is_rejected

  4.3  symbol absent from the validated set -> reject without transmitting
       test_broker_validation.py::test_unknown_symbol_rejects

  5.1  reject disabled / sub-floor-leverage names (untradable)
       test_broker_validation.py::test_sub_floor_leverage_rejects_untradable

  6.1  market-hours: closed session -> reject + report next_open_time
       test_broker_validation.py::test_closed_session_rejects_with_next_open_time

  7.1  never autonomously increase the requested volume
       test_broker_core_orders.py::test_volume_never_upsized

  7.2  any validation violation -> reject (never silently clamp/modify the intent)
       test_broker_validation.py::test_evaluate_never_mutates_input_intent_on_reject

  7.3  no sizing/scoring/trigger; act only on the caller volume+side
       test_broker_core_orders.py::test_volume_never_upsized
       (+ order-path gap-fill below: test_buy_without_volume_is_not_auto_sized_at_order_path)

  7.4  double-send guard: a guarded re-send issues NO duplicate create POST
       test_broker_core_lifecycle.py::test_double_send_guard_no_second_post_when_prior_order_exists

  8.1  v0.1 paper-only: paper-default never transmits a live order
       test_broker_core_orders.py::test_v01_paper_default_never_transmits_live

  8.2  paper mode = validate + simulate (priced from bid/ask), no venue order-create
       test_broker_core_orders.py::test_paper_buy_issues_no_post_asserted_against_spy

  8.3  live only if paper-off AND active AND survival-clearance AND kill-clear
       test_broker_core_orders.py::test_live_send_blocked_when_clearance_missing_or_kill_engaged

  8.4  kill switch engaged -> refuse live transmission
       test_broker_core_orders.py::test_live_send_blocked_when_clearance_missing_or_kill_engaged
       (parametrized: the kill_switch_clear=False case)

  8.5  any required clearance absent -> refuse to transmit (LIVE_SEND_BLOCKED, no POST)
       test_broker_core_orders.py::test_live_send_blocked_when_clearance_missing_or_kill_engaged
       (parametrized: the survival_clearance=False case)

------------------------------------------------------------------------------
Test-run mechanism (canonical broker pytest command):
    PYTHONSAFEPATH=1 uv run --directory src/mcp/broker python -m pytest \\
        tests/unit/mcp/test_broker_coverage_order_path.py -q

The broker runs in its own uv venv (carries ``mcp`` / ``httpx``); the repo root is
NOT on ``sys.path``. The order-path gap-fill loads the broker modules by path
(importlib-by-path under unique aliases), loading ``models`` FIRST under its
canonical alias so dependent modules' ``from models import ...`` reuse the SAME
class objects (enum / isinstance identity holds) — mirrors
``test_broker_core_orders.py``.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

# Repo root: tests/unit/mcp/test_broker_coverage_order_path.py -> parents[3] == repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_BROKER_DIR = _REPO_ROOT / "src" / "mcp" / "broker"
# core + its deps do by-name sibling imports (the production posture).
if str(_BROKER_DIR) not in sys.path:
    sys.path.insert(0, str(_BROKER_DIR))

_TEST_DIR = _REPO_ROOT / "tests" / "unit" / "mcp"


# --------------------------------------------------------------------------- #
# The traceability map: requirement-ID -> the (test_file, test_function) pairs
# that COVER it. Encoded so the map is machine-checkable, not just prose.
#
# A requirement may list MORE THAN ONE pair (a primary load-bearing test plus a
# complementary one); the existence-assertion below requires EVERY listed pair to
# resolve to a real ``def`` in the named file. The canonical / primary test for
# each ID is the FIRST pair.
# --------------------------------------------------------------------------- #

REQUIREMENT_TO_TEST: dict[str, list[tuple[str, str]]] = {
    "1.1": [
        ("test_broker_core_orders.py", "test_buy_in_paper_mode_is_simulated_with_no_order_post"),
        ("test_broker_mappers.py", "test_buy_long_maps_to_buy_to_open_side_2"),
        ("test_broker_mappers.py", "test_buy_short_maps_to_sell_to_open_side_1"),
    ],
    "1.2": [
        ("test_broker_core_orders.py", "test_trim_existing_position_simulated_close_no_post"),
    ],
    "1.3": [
        ("test_broker_core_orders.py", "test_sell_existing_position_simulated_full_close"),
    ],
    "1.4": [
        ("test_broker_core_orders.py", "test_hold_returns_noop_and_transmits_nothing"),
    ],
    "1.5": [
        ("test_broker_validation.py", "test_trigger_without_trigger_price_rejects"),
    ],
    "1.6": [
        ("test_broker_validation.py", "test_volume_above_venue_cap_rejects"),
    ],
    "1.8": [
        ("test_broker_core_orders.py", "test_trim_with_no_position_is_rejected_no_open"),
    ],
    "1.9": [
        ("test_broker_mappers.py", "test_trim_sell_use_caller_supplied_position_id_verbatim"),
    ],
    "1.10": [
        ("test_broker_core_orders.py", "test_inactive_account_rejects"),
    ],
    "1.11": [
        ("test_broker_validation.py", "test_close_only_rejects_buy_open"),
    ],
    "4.2": [
        ("test_broker_symbol_cache.py", "test_out_of_category_symbol_is_rejected"),
    ],
    "4.3": [
        ("test_broker_validation.py", "test_unknown_symbol_rejects"),
    ],
    "5.1": [
        ("test_broker_validation.py", "test_sub_floor_leverage_rejects_untradable"),
    ],
    "6.1": [
        ("test_broker_validation.py", "test_closed_session_rejects_with_next_open_time"),
    ],
    "7.1": [
        ("test_broker_core_orders.py", "test_volume_never_upsized"),
    ],
    "7.2": [
        ("test_broker_validation.py", "test_evaluate_never_mutates_input_intent_on_reject"),
    ],
    "7.3": [
        ("test_broker_core_orders.py", "test_volume_never_upsized"),
        # The order-path gap-fill lives IN THIS FILE; resolved against it below.
        (
            "test_broker_coverage_order_path.py",
            "test_buy_without_volume_is_not_auto_sized_at_order_path",
        ),
    ],
    "7.4": [
        (
            "test_broker_core_lifecycle.py",
            "test_double_send_guard_no_second_post_when_prior_order_exists",
        ),
    ],
    "8.1": [
        ("test_broker_core_orders.py", "test_v01_paper_default_never_transmits_live"),
    ],
    "8.2": [
        ("test_broker_core_orders.py", "test_paper_buy_issues_no_post_asserted_against_spy"),
    ],
    "8.3": [
        ("test_broker_core_orders.py", "test_live_send_blocked_when_clearance_missing_or_kill_engaged"),
    ],
    "8.4": [
        ("test_broker_core_orders.py", "test_live_send_blocked_when_clearance_missing_or_kill_engaged"),
    ],
    "8.5": [
        ("test_broker_core_orders.py", "test_live_send_blocked_when_clearance_missing_or_kill_engaged"),
    ],
}

# The exact 23 IDs Task 6.1 must guarantee are covered (sanity-pins the map).
_EXPECTED_IDS = {
    "1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.8", "1.9", "1.10", "1.11",
    "4.2", "4.3", "5.1", "6.1", "7.1", "7.2", "7.3", "7.4",
    "8.1", "8.2", "8.3", "8.4", "8.5",
}


def _function_names_in(test_file: str) -> set[str]:
    """Parse a test module's AST and return its top-level ``def`` names.

    AST (not import) so this existence-check neither re-runs the referenced
    module's module-level broker loads nor depends on import side effects — it
    fails IFF a referenced function literally does not exist in the file.
    """
    path = _TEST_DIR / test_file
    assert path.exists(), f"referenced test file does not exist: {test_file}"
    tree = ast.parse(path.read_text())
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


# --------------------------------------------------------------------------- #
# Map integrity — the 23 IDs are all present and only those.
# --------------------------------------------------------------------------- #


def test_map_covers_exactly_the_23_task_6_1_ids():
    """The traceability map names exactly the 23 acceptance-criteria IDs in Task
    6.1's scope — no ID missing, none spuriously added."""
    assert set(REQUIREMENT_TO_TEST) == _EXPECTED_IDS, (
        f"map IDs {sorted(set(REQUIREMENT_TO_TEST))} != "
        f"expected {sorted(_EXPECTED_IDS)}"
    )


# --------------------------------------------------------------------------- #
# Existence-assertions — every mapped test callable must really exist. This is
# what keeps the map from silently rotting: rename/remove a referenced test and
# THIS test turns RED.
# --------------------------------------------------------------------------- #


def test_every_mapped_requirement_test_exists():
    """For every (test_file, test_function) the map cites, the function must be a
    real top-level ``def`` in that file. A renamed/removed referenced test makes
    this FAIL — the map can't claim coverage that no longer exists."""
    # Cache the per-file function-name sets so each file is parsed once.
    names_by_file: dict[str, set[str]] = {}
    missing: list[str] = []

    for req_id, pairs in REQUIREMENT_TO_TEST.items():
        assert pairs, f"requirement {req_id} maps to no test"
        for test_file, test_fn in pairs:
            names = names_by_file.setdefault(test_file, _function_names_in(test_file))
            if test_fn not in names:
                missing.append(f"{req_id} -> {test_file}::{test_fn}")

    assert not missing, (
        "mapped coverage test(s) do not exist (the map has rotted); "
        f"missing: {missing}"
    )


@pytest.mark.parametrize("req_id", sorted(_EXPECTED_IDS))
def test_each_requirement_has_at_least_one_existing_load_bearing_test(req_id):
    """Per-ID guarantee: each of the 23 IDs resolves to at least one EXISTING
    test callable (parametrized so a failure names the exact ID that lost its
    coverage)."""
    pairs = REQUIREMENT_TO_TEST.get(req_id)
    assert pairs, f"requirement {req_id} has no mapped test"
    resolved = [
        f"{f}::{fn}" for (f, fn) in pairs if fn in _function_names_in(f)
    ]
    assert resolved, (
        f"requirement {req_id} maps to no EXISTING test; "
        f"candidates were {[f'{f}::{fn}' for (f, fn) in pairs]}"
    )


# --------------------------------------------------------------------------- #
# Gap-fill (Req 7.3, order-path): a sizeless BUY through ``core.submit_decision``
# is REJECTED — the adapter never invents a size. Distinct from the pure
# validation-layer assertion (it exercises the whole order path: snapshot ->
# validation -> reject), and from ``test_volume_never_upsized`` (verbatim/no-upsize).
# --------------------------------------------------------------------------- #


def _load_by_path(alias: str, path: Path):
    spec = importlib.util.spec_from_file_location(alias, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module


# The 1.4 mock transport + fixture loader (the injectable-transport seam).
_FAKES_PATH = _REPO_ROOT / "tests" / "unit" / "mcp" / "broker_gate_fakes.py"
broker_gate_fakes = _load_by_path("broker_gate_fakes", _FAKES_PATH)

# LOAD-BEARING ordering: ``models`` FIRST under its canonical alias, then deps,
# then the unit-under-test (enum / isinstance identity must match the instances the
# production modules close over).
broker_models = _load_by_path("models", _BROKER_DIR / "models.py")
broker_config = _load_by_path("config", _BROKER_DIR / "config.py")
_load_by_path("mappers", _BROKER_DIR / "mappers.py")
gate_client = _load_by_path("gate_client", _BROKER_DIR / "gate_client.py")
symbol_cache = _load_by_path("symbol_cache", _BROKER_DIR / "symbol_cache.py")
_load_by_path("validation", _BROKER_DIR / "validation.py")
_load_by_path("paper", _BROKER_DIR / "paper.py")
core = _load_by_path("broker_core", _BROKER_DIR / "core.py")

Label = broker_models.Label
Direction = broker_models.Direction
RejectionCode = broker_models.RejectionCode
RuntimeMode = broker_config.RuntimeMode


def test_buy_without_volume_is_not_auto_sized_at_order_path(monkeypatch):
    """Req 7.3 (order-path): a BUY submitted with NO volume is REJECTED through
    ``core.submit_decision`` — the adapter performs no position sizing, never
    fabricating a default size — and issues NO order/close POST.

    Load-bearing: were the adapter to auto-size (e.g. default volume = min lot),
    the status would be ``simulated`` (a fill), not ``rejected``; the assertion on
    ``VOLUME_OUT_OF_BOUNDS`` + ``posted == []`` fails on any such regression.
    """
    monkeypatch.setenv("GATE_API_KEY", "k-test")
    monkeypatch.setenv("GATE_API_SECRET", "s-test")

    base = broker_gate_fakes.make_mock_transport()
    posted: list[tuple] = []

    class _SpyClient:
        def request(self, method, path, *, params=None, body=None, transport=None, **kw):
            if method.upper() == "POST":
                posted.append((method, path))
            return gate_client.request(
                method, path, params=params, body=body, transport=base
            )

        def get(self, path, *, params=None, transport=None, **kw):
            return self.request("GET", path, params=params, transport=base)

    clients = core.ReadoutClients(
        gate_client=_SpyClient(),
        symbol_cache=symbol_cache.SymbolCache(gate_client=gate_client, transport=base),
        transport=None,
    )

    result = core.submit_decision(
        Label.BUY,
        "AAPL",
        Direction.LONG,
        volume=None,  # caller supplied NO size — the adapter must not invent one
        clients=clients,
        runtime_mode=RuntimeMode(paper_enabled=True, account_active=True),
    )

    assert result.status == "rejected", (
        "a sizeless BUY must be rejected, never auto-sized into a fill (Req 7.3)"
    )
    assert result.reason is not None
    assert result.reason.code is RejectionCode.VOLUME_OUT_OF_BOUNDS
    # And nothing was transmitted while refusing to size.
    assert posted == [], "an auto-size refusal must transmit nothing"
    # Explicitly: the adapter did not fabricate a fill_volume of its own.
    assert result.fill_volume is None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
