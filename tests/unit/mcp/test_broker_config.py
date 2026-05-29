"""Unit tests for the broker configuration + secret resolution layer (Task 1.3).

Covers the design "config" component + Security Considerations contract:

- Gate credentials (``GATE_API_KEY`` / ``GATE_API_SECRET``) read FRESH per call so
  operator key-rotation needs no restart (mirrors the house ``polygon/server.py``
  ``_client()`` ``os.environ.get(...).strip()`` pattern).
- A missing credential returns a STRUCTURED result/error — NEVER raises (Req 8.1
  paper-only posture means a missing secret must not crash the adapter; config is
  the conservative seam).
- Credentials are never echoed back verbatim in the structured error.
- Runtime mode is safe-by-default: paper/dry-run defaults ON; survival-gate
  clearance + kill switch are boolean INPUTS that default to the SAFE state
  (clearance = not-present/false; kill switch = engaged-or-safe so live is
  BLOCKED). Live transmit is not permitted unless all four 8.3 conditions hold.
- Settlement currency + the US-stock category id (stocks = category 2 per the
  Gate TradFi API reference) are held by config.

Requirements: 8.1 (paper-only default), 8.3 (live = paper-off AND active AND
survival-clearance AND kill-clear), 8.4 (kill switch engaged -> block live).

Test-run mechanism (canonical broker pytest command):
    PYTHONSAFEPATH=1 uv run --directory src/mcp/broker python -m pytest \
        tests/unit/mcp/test_broker_config.py -q

The broker runs in its own uv venv (carries ``mcp`` / ``httpx``); the repo root is
NOT on ``sys.path``. This test loads ``config.py`` by path (importlib-by-path,
under a unique module alias) to avoid any module-name collision, mirroring
``tests/unit/mcp/test_broker_models.py`` / ``test_polygon.py``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# Repo root: tests/unit/mcp/test_broker_config.py -> parents[3] == repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_BROKER_DIR = _REPO_ROOT / "src" / "mcp" / "broker"
_CONFIG_PATH = _BROKER_DIR / "config.py"
_spec = importlib.util.spec_from_file_location("broker_config", _CONFIG_PATH)
assert _spec is not None and _spec.loader is not None
broker_config = importlib.util.module_from_spec(_spec)
sys.modules["broker_config"] = broker_config
_spec.loader.exec_module(broker_config)


# --------------------------------------------------------------------------- #
# Credentials — fresh-read, structured-on-missing, never raise, never echoed.
# --------------------------------------------------------------------------- #


def test_resolve_credentials_missing_returns_structured_error_not_exception(
    monkeypatch,
):
    """With both keys unset, a credential read returns a structured error result
    (no exception raised)."""
    monkeypatch.delenv("GATE_API_KEY", raising=False)
    monkeypatch.delenv("GATE_API_SECRET", raising=False)

    # Must NOT raise.
    result = broker_config.resolve_credentials()

    assert result.ok is False
    assert result.api_key is None
    assert result.api_secret is None
    # A structured error code/message is present.
    assert result.error is not None
    assert isinstance(result.error, str) and result.error != ""


def test_resolve_credentials_missing_secret_only_is_structured_error(monkeypatch):
    """A partially-set credential pair (key present, secret absent) is still a
    structured error, not a partial success."""
    monkeypatch.setenv("GATE_API_KEY", "k-present")
    monkeypatch.delenv("GATE_API_SECRET", raising=False)

    result = broker_config.resolve_credentials()

    assert result.ok is False
    assert result.error is not None


def test_resolve_credentials_error_never_echoes_secret_value(monkeypatch):
    """The structured error must never surface a credential value verbatim
    (Security Considerations: secrets never logged / never returned)."""
    monkeypatch.setenv("GATE_API_KEY", "SUPER-SECRET-KEY-123")
    monkeypatch.delenv("GATE_API_SECRET", raising=False)

    result = broker_config.resolve_credentials()

    assert result.ok is False
    assert "SUPER-SECRET-KEY-123" not in (result.error or "")


def test_resolve_credentials_present_returns_ok_and_stripped(monkeypatch):
    """With both keys present, credentials resolve OK and are whitespace-stripped
    (mirrors the house ``.strip()`` pattern)."""
    monkeypatch.setenv("GATE_API_KEY", "  key-with-space  ")
    monkeypatch.setenv("GATE_API_SECRET", "  secret-with-space  ")

    result = broker_config.resolve_credentials()

    assert result.ok is True
    assert result.api_key == "key-with-space"
    assert result.api_secret == "secret-with-space"
    assert result.error is None


def test_resolve_credentials_blank_after_strip_is_missing(monkeypatch):
    """A key set to whitespace-only is treated as absent (strip then empty)."""
    monkeypatch.setenv("GATE_API_KEY", "   ")
    monkeypatch.setenv("GATE_API_SECRET", "   ")

    result = broker_config.resolve_credentials()

    assert result.ok is False
    assert result.error is not None


def test_resolve_credentials_reads_env_fresh_each_call(monkeypatch):
    """Key rotation needs no restart: a second call after the env changes reflects
    the new value (no caching of the secret)."""
    monkeypatch.setenv("GATE_API_KEY", "key-1")
    monkeypatch.setenv("GATE_API_SECRET", "secret-1")
    first = broker_config.resolve_credentials()
    assert first.ok is True
    assert first.api_key == "key-1"

    # Rotate without re-importing the module.
    monkeypatch.setenv("GATE_API_KEY", "key-2")
    monkeypatch.setenv("GATE_API_SECRET", "secret-2")
    second = broker_config.resolve_credentials()
    assert second.ok is True
    assert second.api_key == "key-2"
    assert second.api_secret == "secret-2"


# --------------------------------------------------------------------------- #
# Runtime mode — safe-by-default (paper ON, live blocked).
# --------------------------------------------------------------------------- #


def test_runtime_mode_paper_defaults_enabled():
    """Req 8.1 — paper/dry-run mode defaults ON."""
    cfg = broker_config.RuntimeMode()
    assert cfg.paper_enabled is True


def test_runtime_mode_survival_clearance_defaults_not_cleared():
    """Req 8.3/8.5 — survival-gate clearance is a boolean INPUT defaulting to the
    safe state (not present / not cleared)."""
    cfg = broker_config.RuntimeMode()
    assert cfg.survival_clearance is False


def test_runtime_mode_kill_switch_defaults_to_blocking_state():
    """Req 8.4 — the kill switch defaults to the SAFE state: live transmissions
    are blocked when its state is unknown/engaged."""
    cfg = broker_config.RuntimeMode()
    # Whatever the field name/representation, the SAFE default means live is NOT
    # cleared by the kill switch.
    assert cfg.kill_switch_clear is False


def test_runtime_mode_account_active_defaults_inactive():
    """Req 8.3 / 1.10 — the account-active input defaults to the safe (inactive)
    state so live is blocked until explicitly proven active."""
    cfg = broker_config.RuntimeMode()
    assert cfg.account_active is False


def test_live_transmit_blocked_by_default():
    """Req 8.1 / 8.3 — with all inputs at their safe defaults, live transmit is
    NOT permitted (paper ON is itself disqualifying)."""
    cfg = broker_config.RuntimeMode()
    assert cfg.live_transmit_allowed() is False


def test_live_transmit_requires_all_four_conditions():
    """Req 8.3 — live transmit needs paper OFF AND account active AND survival
    clearance present AND kill switch clear, simultaneously."""
    # All four satisfied -> allowed.
    allowed = broker_config.RuntimeMode(
        paper_enabled=False,
        account_active=True,
        survival_clearance=True,
        kill_switch_clear=True,
    )
    assert allowed.live_transmit_allowed() is True

    # Drop each condition individually -> blocked (4 negative cases).
    assert (
        broker_config.RuntimeMode(
            paper_enabled=True,  # paper still on
            account_active=True,
            survival_clearance=True,
            kill_switch_clear=True,
        ).live_transmit_allowed()
        is False
    )
    assert (
        broker_config.RuntimeMode(
            paper_enabled=False,
            account_active=False,  # inactive account
            survival_clearance=True,
            kill_switch_clear=True,
        ).live_transmit_allowed()
        is False
    )
    assert (
        broker_config.RuntimeMode(
            paper_enabled=False,
            account_active=True,
            survival_clearance=False,  # no clearance
            kill_switch_clear=True,
        ).live_transmit_allowed()
        is False
    )
    assert (
        broker_config.RuntimeMode(
            paper_enabled=False,
            account_active=True,
            survival_clearance=True,
            kill_switch_clear=False,  # kill switch engaged
        ).live_transmit_allowed()
        is False
    )


def test_kill_switch_engaged_blocks_live_even_when_otherwise_cleared():
    """Req 8.4 — an engaged kill switch blocks live even with paper off, account
    active, and survival clearance present."""
    cfg = broker_config.RuntimeMode(
        paper_enabled=False,
        account_active=True,
        survival_clearance=True,
        kill_switch_clear=False,
    )
    assert cfg.live_transmit_allowed() is False


# --------------------------------------------------------------------------- #
# Venue constants — settlement currency + US-stock category id.
# --------------------------------------------------------------------------- #


def test_settlement_currency_present_and_nonempty():
    """Config holds the settlement currency for the US-stock category."""
    cfg = broker_config.RuntimeMode()
    assert isinstance(cfg.settlement_currency, str)
    assert cfg.settlement_currency != ""


def test_us_stock_category_id_is_two():
    """The US-stock CFD category id is 2 per the Gate TradFi API reference
    (``/tradfi/symbols/categories``, stocks = category 2)."""
    cfg = broker_config.RuntimeMode()
    assert cfg.us_stock_category_id == 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
