"""Tests for resolve_latest_value_in_window — the shared FRED walker utility.

Single source of truth for "latest valid value at/before target_date" used by:
- src.shared.regime_sidecar.fred_client.latest_value (regime sidecar)
- src.overlays.tactical.bin_classifier.resolve_rf_at (tactical overlay)

Per Section 3 integration debt consolidation (was deferred by /simplify).
"""

from datetime import date

from src.shared.regime_sidecar.fred_client import resolve_latest_value_in_window


def _obs(d: str, v: float | None) -> dict:
    return {"date": d, "value": v}


def test_returns_latest_valid_with_no_target():
    obs = [_obs("2026-05-18", 4.61), _obs("2026-05-19", 4.62), _obs("2026-05-20", 4.63)]
    assert resolve_latest_value_in_window(obs, target_date=None) == ("2026-05-20", 4.63)


def test_skips_none_values():
    obs = [_obs("2026-05-18", 4.61), _obs("2026-05-19", None), _obs("2026-05-20", None)]
    assert resolve_latest_value_in_window(obs, target_date=None) == ("2026-05-18", 4.61)


def test_returns_latest_at_or_before_target_string():
    obs = [_obs("2026-05-18", 4.61), _obs("2026-05-19", 4.62), _obs("2026-05-20", 4.63)]
    assert resolve_latest_value_in_window(obs, target_date="2026-05-19") == ("2026-05-19", 4.62)


def test_returns_latest_at_or_before_target_date_obj():
    obs = [_obs("2026-05-18", 4.61), _obs("2026-05-19", 4.62), _obs("2026-05-20", 4.63)]
    assert resolve_latest_value_in_window(obs, target_date=date(2026, 5, 19)) == ("2026-05-19", 4.62)


def test_staleness_gate_accepts_within_threshold():
    obs = [_obs("2026-05-15", 4.50)]
    result = resolve_latest_value_in_window(
        obs, target_date=date(2026, 5, 20), max_staleness_calendar_days=7,
    )
    assert result == ("2026-05-15", 4.50)


def test_staleness_gate_rejects_beyond_threshold():
    obs = [_obs("2026-05-05", 4.50)]  # 15 days stale
    result = resolve_latest_value_in_window(
        obs, target_date=date(2026, 5, 20), max_staleness_calendar_days=7,
    )
    assert result == (None, None)


def test_empty_observations():
    assert resolve_latest_value_in_window([], target_date=None) == (None, None)


def test_all_none_values():
    obs = [_obs("2026-05-18", None), _obs("2026-05-19", None)]
    assert resolve_latest_value_in_window(obs, target_date=None) == (None, None)


def test_target_before_all_observations():
    obs = [_obs("2026-05-18", 4.61), _obs("2026-05-19", 4.62)]
    assert resolve_latest_value_in_window(obs, target_date="2026-05-01") == (None, None)


def test_walks_backward_through_nd_cluster():
    """Christmas + holiday gap → walk backward to find valid."""
    obs = [
        _obs("2026-12-22", 4.50),
        _obs("2026-12-23", 4.51),
        _obs("2026-12-24", None),
        _obs("2026-12-25", None),
        _obs("2026-12-26", None),
    ]
    result = resolve_latest_value_in_window(
        obs, target_date=date(2026, 12, 26), max_staleness_calendar_days=7,
    )
    assert result == ("2026-12-23", 4.51)


def test_legacy_latest_value_unchanged_signature():
    """Backward-compat: regime_sidecar.latest_value still returns ('', None) sentinel."""
    from src.shared.regime_sidecar.fred_client import resolve_latest_value_in_window as _walker

    # Confirm the new utility returns None,None for empty (not '',None)
    assert _walker([], target_date=None) == (None, None)
    # The legacy adapter latest_value (which calls _walker) coerces None→''
    # for backward compat; tested in test_regime_sidecar.py.


def test_consolidation_bin_classifier_adapter_matches_walker():
    """bin_classifier.resolve_rf_at must delegate to resolve_latest_value_in_window."""
    from src.overlays.tactical.bin_classifier import resolve_rf_at

    fred_window = [
        (date(2026, 5, 18), 4.61),
        (date(2026, 5, 19), 4.62),
        (date(2026, 5, 20), None),
    ]
    # bin_classifier shape: takes target_date as the window-start anchor
    adapter_result = resolve_rf_at(
        fred_window, target_date=date(2026, 5, 20), max_staleness_calendar_days=7,
    )
    walker_result = resolve_latest_value_in_window(
        [{"date": d.isoformat(), "value": v} for d, v in fred_window],
        target_date=date(2026, 5, 20),
        max_staleness_calendar_days=7,
    )
    assert adapter_result == walker_result[1]  # adapter returns float, walker returns (date, float)
