"""Inner-ring coverage completion for the broker CFD adapter — readouts,
transport errors, and history (Task 6.2).

Sibling deliverable to ``test_broker_coverage_order_path.py`` (Task 6.1). Where
6.1 proved completeness of the order-path / validation / gating / paper criteria,
THIS file proves completeness of the READOUT / TRANSPORT-ERROR / HISTORY criteria.
It does two things, both machine-checkable:

1. **Traceability map (below)** — for each of the 18 acceptance-criteria IDs in
   scope for Task 6.2, it names the EXISTING load-bearing test(s) (file::function)
   that guarantee it. The map is encoded in ``REQUIREMENT_TO_TEST`` so it cannot
   drift from prose.
2. **Existence-assertions** — ``test_every_mapped_requirement_test_exists`` parses
   each referenced test module's AST and asserts every named test callable is
   present. If a referenced test is renamed or removed, this file turns RED — the
   map cannot silently rot into a stale set of names that no longer exist.

NO GAP-FILL TEST IS NEEDED. Every one of the 18 IDs is already COVERED by a
load-bearing test from the per-task TDD suite — verified clause-by-clause against
``.kiro/specs/broker-cfd-adapter/requirements.md`` (see the per-ID notes below).
This file therefore does NOT re-test any behavior; it pins the map to the existing
tests and proves (via the rename mutation) that the pin is load-bearing. (6.1's
single gap-fill closed an order-path seam specific to conservative-posture sizing;
the readouts/transport/history surface has no analogous uncovered seam.)

------------------------------------------------------------------------------
Requirement-ID -> load-bearing test traceability map (Task 6.2 scope, 18 IDs)
------------------------------------------------------------------------------

  2.1  positions readout: every open position w/ id, symbol, direction, volume,
       avg open price, used margin, unrealized PnL
       test_broker_mappers.py::test_parse_position_parses_strings_and_reports_venue_upnl_verbatim
       (asserts the FULL field set id/symbol/direction/volume/avg_open_price/
        used_margin/unrealized_pnl)
       (+ readout-level: test_broker_core_readouts.py::
        test_get_positions_returns_typed_list_with_venue_upnl_verbatim)

  2.2  report VENUE unrealized PnL verbatim; no self-computed mid/mark
       test_broker_core_readouts.py::test_get_positions_returns_typed_list_with_venue_upnl_verbatim
       (+ parse-level verbatim incl. negative-uPnL preservation:
        test_broker_mappers.py::test_parse_position_short_direction_and_negative_upnl_preserved)

  2.3  no positions -> empty set, not an error
       test_broker_core_readouts.py::test_get_positions_empty_book_returns_empty_list_not_error

  3.1  assets readout: equity, used margin, free margin, margin level, balance
       test_broker_core_readouts.py::test_get_account_assets_exposes_stop_out_and_no_liquidation_distance
       (+ parse-level: test_broker_mappers.py::test_parse_account_assets_exposes_stop_out_no_liq_distance)

  3.2  expose stop-out / liquidation margin ratio; NO self-computed liq distance
       test_broker_core_readouts.py::test_get_account_assets_exposes_stop_out_and_no_liquidation_distance
       (+ parse-level: test_broker_mappers.py::test_parse_account_assets_exposes_stop_out_no_liq_distance)

  3.3  per-symbol swap/financing rates + realized swap on closed positions
       test_broker_symbol_cache.py::test_resolution_surfaces_per_symbol_swap_rates
       (per-symbol rates) + realized-swap-on-closed-positions:
       test_broker_core_readouts.py::test_get_history_returns_fills_swap_and_forced_liquidation_flag

  4.1  identity is US-ticker ONLY; never the venue free-text description
       test_broker_symbol_cache.py::test_identity_is_ticker_only_misleading_description_ignored

  5.2  control exposure via volume; NO per-order leverage parameter on the request
       test_broker_mappers.py::test_order_request_carries_no_per_order_leverage

  5.3  used-margin/exposure = volume-derived notional / per-symbol leverage
       test_broker_mappers.py::test_used_margin_is_notional_over_leverage_known_vector

  9.1  auth failure -> structured error naming the failure class; NO transmit
       test_broker_gate_client.py::test_missing_credentials_returns_structured_error_no_transmit
       (+ injected-401 auth class: test_broker_gate_client.py::test_injected_401_returns_structured_auth_error)

  9.2  venue error/unreachable -> structured result, never an unhandled raise;
       unconfirmed async outcome surfaced as unconfirmed (not assumed filled)
       test_broker_server.py::test_readout_tool_wraps_broker_readout_error_into_structured_dict
       (never-raises seam) + test_broker_gate_client.py::
       test_injected_network_error_returns_structured_error (transport-level) +
       test_broker_core_lifecycle.py::test_async_buy_unconfirmed_when_never_appears_within_cap
       (unconfirmed surfaced, never filled)

  9.3  on fill, surface actual fill price + fill volume (via the Req-10 history)
       test_broker_core_readouts.py::test_get_history_returns_fills_swap_and_forced_liquidation_flag

  9.4  emit NO decision-trace telemetry itself
       test_broker_core_readouts.py::test_core_emits_no_telemetry_or_decision_trace

  9.5  respect rate-limit signals (back off, not immediate retry); discover the
       effective limit at runtime from headers (not hardcoded)
       test_broker_gate_client.py::test_injected_429_backs_off_via_injected_sleep
       (+ runtime discovery: test_broker_gate_client.py::test_injected_429_discovers_limit_from_headers)

  10.1 history readout: closed orders/positions w/ fill price, fill volume,
       realized PnL, realized swap, close reason
       test_broker_core_readouts.py::test_get_history_returns_fills_swap_and_forced_liquidation_flag
       (+ parse-level field coverage: test_broker_mappers.py::
        test_parse_positions_history_forced_liquidation_from_position_status /
        ::test_parse_orders_history_forced_liquidation_flag_from_opt_type)

  10.2 close reason flags normal vs forced liquidation; adapter does not interpret
       test_broker_mappers.py::test_parse_orders_history_forced_liquidation_flag_from_opt_type
       (order force-close opt_type 5|6) + test_broker_mappers.py::
       test_parse_positions_history_forced_liquidation_from_position_status (position_status 2)

  10.3 report venue-supplied history values verbatim; no self-computed substitution
       test_broker_mappers.py::test_parse_positions_history_forced_liquidation_from_position_status
       (+ order side: test_broker_mappers.py::test_parse_orders_history_forced_liquidation_flag_from_opt_type)

  10.4 no history in the window -> empty set, not an error
       test_broker_core_readouts.py::test_get_history_empty_window_returns_empty_list_not_error

------------------------------------------------------------------------------
Test-run mechanism (canonical broker pytest command):
    PYTHONSAFEPATH=1 uv run --directory src/mcp/broker python -m pytest \\
        tests/unit/mcp/test_broker_coverage_readouts.py -q

This file performs NO broker-module import — its assertions are pure AST parses of
the referenced test modules + set algebra over the map. It therefore needs no
``models``-first canonical-alias loading (there is no enum/isinstance identity to
preserve); it only resolves test-file paths relative to the repo root. (Were a
future gap-fill added here that DID import broker modules, it must load ``models``
FIRST under its canonical alias, mirroring the 6.1 file.)
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

# Repo root: tests/unit/mcp/test_broker_coverage_readouts.py -> parents[3] == repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_TEST_DIR = _REPO_ROOT / "tests" / "unit" / "mcp"


# --------------------------------------------------------------------------- #
# The traceability map: requirement-ID -> the (test_file, test_function) pairs
# that COVER it. Encoded so the map is machine-checkable, not just prose.
#
# A requirement may list MORE THAN ONE pair (a primary load-bearing test plus a
# complementary one — e.g. a multi-clause criterion such as 3.3 "per-symbol swap
# rates AND realized swap on closed positions", or 9.2 "structured error AND
# unconfirmed surfaced"). The existence-assertion below requires EVERY listed pair
# to resolve to a real ``def``. The canonical / primary test for each ID is the
# FIRST pair.
# --------------------------------------------------------------------------- #

REQUIREMENT_TO_TEST: dict[str, list[tuple[str, str]]] = {
    "2.1": [
        (
            "test_broker_mappers.py",
            "test_parse_position_parses_strings_and_reports_venue_upnl_verbatim",
        ),
        (
            "test_broker_core_readouts.py",
            "test_get_positions_returns_typed_list_with_venue_upnl_verbatim",
        ),
    ],
    "2.2": [
        (
            "test_broker_core_readouts.py",
            "test_get_positions_returns_typed_list_with_venue_upnl_verbatim",
        ),
        (
            "test_broker_mappers.py",
            "test_parse_position_short_direction_and_negative_upnl_preserved",
        ),
    ],
    "2.3": [
        (
            "test_broker_core_readouts.py",
            "test_get_positions_empty_book_returns_empty_list_not_error",
        ),
    ],
    "3.1": [
        (
            "test_broker_core_readouts.py",
            "test_get_account_assets_exposes_stop_out_and_no_liquidation_distance",
        ),
        (
            "test_broker_mappers.py",
            "test_parse_account_assets_exposes_stop_out_no_liq_distance",
        ),
    ],
    "3.2": [
        (
            "test_broker_core_readouts.py",
            "test_get_account_assets_exposes_stop_out_and_no_liquidation_distance",
        ),
        (
            "test_broker_mappers.py",
            "test_parse_account_assets_exposes_stop_out_no_liq_distance",
        ),
    ],
    "3.3": [
        (
            "test_broker_symbol_cache.py",
            "test_resolution_surfaces_per_symbol_swap_rates",
        ),
        (
            "test_broker_core_readouts.py",
            "test_get_history_returns_fills_swap_and_forced_liquidation_flag",
        ),
    ],
    "4.1": [
        (
            "test_broker_symbol_cache.py",
            "test_identity_is_ticker_only_misleading_description_ignored",
        ),
    ],
    "5.2": [
        ("test_broker_mappers.py", "test_order_request_carries_no_per_order_leverage"),
    ],
    "5.3": [
        (
            "test_broker_mappers.py",
            "test_used_margin_is_notional_over_leverage_known_vector",
        ),
    ],
    "9.1": [
        (
            "test_broker_gate_client.py",
            "test_missing_credentials_returns_structured_error_no_transmit",
        ),
        (
            "test_broker_gate_client.py",
            "test_injected_401_returns_structured_auth_error",
        ),
    ],
    "9.2": [
        (
            "test_broker_server.py",
            "test_readout_tool_wraps_broker_readout_error_into_structured_dict",
        ),
        (
            "test_broker_gate_client.py",
            "test_injected_network_error_returns_structured_error",
        ),
        (
            "test_broker_core_lifecycle.py",
            "test_async_buy_unconfirmed_when_never_appears_within_cap",
        ),
    ],
    "9.3": [
        (
            "test_broker_core_readouts.py",
            "test_get_history_returns_fills_swap_and_forced_liquidation_flag",
        ),
    ],
    "9.4": [
        (
            "test_broker_core_readouts.py",
            "test_core_emits_no_telemetry_or_decision_trace",
        ),
    ],
    "9.5": [
        (
            "test_broker_gate_client.py",
            "test_injected_429_backs_off_via_injected_sleep",
        ),
        (
            "test_broker_gate_client.py",
            "test_injected_429_discovers_limit_from_headers",
        ),
    ],
    "10.1": [
        (
            "test_broker_core_readouts.py",
            "test_get_history_returns_fills_swap_and_forced_liquidation_flag",
        ),
        (
            "test_broker_mappers.py",
            "test_parse_positions_history_forced_liquidation_from_position_status",
        ),
        (
            "test_broker_mappers.py",
            "test_parse_orders_history_forced_liquidation_flag_from_opt_type",
        ),
    ],
    "10.2": [
        (
            "test_broker_mappers.py",
            "test_parse_orders_history_forced_liquidation_flag_from_opt_type",
        ),
        (
            "test_broker_mappers.py",
            "test_parse_positions_history_forced_liquidation_from_position_status",
        ),
    ],
    "10.3": [
        (
            "test_broker_mappers.py",
            "test_parse_positions_history_forced_liquidation_from_position_status",
        ),
        (
            "test_broker_mappers.py",
            "test_parse_orders_history_forced_liquidation_flag_from_opt_type",
        ),
    ],
    "10.4": [
        (
            "test_broker_core_readouts.py",
            "test_get_history_empty_window_returns_empty_list_not_error",
        ),
    ],
}

# The exact 18 IDs Task 6.2 must guarantee are covered (sanity-pins the map).
_EXPECTED_IDS = {
    "2.1", "2.2", "2.3",
    "3.1", "3.2", "3.3",
    "4.1",
    "5.2", "5.3",
    "9.1", "9.2", "9.3", "9.4", "9.5",
    "10.1", "10.2", "10.3", "10.4",
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
# Map integrity — the 18 IDs are all present and only those.
# --------------------------------------------------------------------------- #


def test_map_covers_exactly_the_18_task_6_2_ids():
    """The traceability map names exactly the 18 acceptance-criteria IDs in Task
    6.2's scope — no ID missing, none spuriously added."""
    assert set(REQUIREMENT_TO_TEST) == _EXPECTED_IDS, (
        f"map IDs {sorted(set(REQUIREMENT_TO_TEST))} != "
        f"expected {sorted(_EXPECTED_IDS)}"
    )


def test_map_disjoint_from_task_6_1_scope():
    """Guard against duplication with the sibling 6.1 deliverable: none of the
    23 order-path/validation/gating/paper IDs (Task 6.1) leak into the 18 here."""
    task_6_1_ids = {
        "1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.8", "1.9", "1.10", "1.11",
        "4.2", "4.3", "5.1", "6.1", "7.1", "7.2", "7.3", "7.4",
        "8.1", "8.2", "8.3", "8.4", "8.5",
    }
    overlap = set(REQUIREMENT_TO_TEST) & task_6_1_ids
    assert not overlap, f"6.2 map must not re-claim 6.1 IDs; overlap: {sorted(overlap)}"


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
    """Per-ID guarantee: each of the 18 IDs resolves to at least one EXISTING
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


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
