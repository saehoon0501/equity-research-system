"""Inner-ring smoke test for the daemon config + db scaffold (task 1.2).

Boundary: config, db (Requirements 1, 3). Asserts the Observable from
tasks.md 1.2:

  * ``python -m src.reactive.daemon`` imports and constructs a
    ``DaemonConfig`` from env *without opening a connection*.
  * ``.env.example`` carries the new daemon keys.

No LLM, no MCP, no live DB (P14 inner ring). The whole point of the
"no connection opened" assertion is that importing the package and
building the config is a pure, side-effect-free operation — the daemon
owns its psycopg3 connection lifecycle explicitly in ``db.py`` (§14.10),
never as an import or config side effect.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]

# A complete synthetic env so _dsn() and DaemonConfig.from_env() resolve
# without depending on the operator's real .env.
_FAKE_ENV = {
    "POSTGRES_USER": "u",
    "POSTGRES_PASSWORD": "p",
    "POSTGRES_HOST": "db-host",
    "POSTGRES_PORT": "5433",
    "POSTGRES_DB": "equity_research",
}


def test_dsn_mirrors_trace_writer_shape() -> None:
    """``_dsn()`` builds the same DSN string as the telemetry writer's helper."""
    from src.reactive.daemon import config

    with mock.patch.dict(os.environ, _FAKE_ENV, clear=False):
        dsn = config._dsn()

    assert dsn == "postgresql://u:p@db-host:5433/equity_research"


def test_dsn_defaults_host_and_port() -> None:
    """Host/port default to 127.0.0.1:5432 (mirrors trace_writer._dsn)."""
    from src.reactive.daemon import config

    env = {k: v for k, v in _FAKE_ENV.items() if k not in ("POSTGRES_HOST", "POSTGRES_PORT")}
    with mock.patch.dict(os.environ, env, clear=True):
        dsn = config._dsn()

    assert dsn == "postgresql://u:p@127.0.0.1:5432/equity_research"


def test_daemon_config_from_env_constructs_without_connection() -> None:
    """``DaemonConfig.from_env`` builds a fully-typed config and opens NO conn.

    Guards the Observable: constructing the config must be a pure read of env
    — if anything tried to open a psycopg3 connection at config-build time the
    patched ``psycopg.connect`` would record a call.
    """
    from src.reactive.daemon import config as config_mod

    with mock.patch("psycopg.connect") as connect:
        with mock.patch.dict(os.environ, _FAKE_ENV, clear=False):
            cfg = config_mod.DaemonConfig.from_env()

    connect.assert_not_called()

    # Paper flag defaults to True (v0.1 paper-only, Req 3.1).
    assert cfg.paper is True
    # The cadence / latency / poll fields are present and positive numerics.
    assert cfg.assess_max_latency_seconds > 0
    assert cfg.poll_timeout_seconds > 0
    assert cfg.eval_cadence_seconds > 0
    assert cfg.intake_poll_cadence_seconds > 0
    # The protective-stop ATR multiplier (Req 11.3) is a positive float.
    assert cfg.stop_loss_atr_mult > 0
    # The DSN is carried so db.py can open the owned connection.
    assert cfg.dsn == "postgresql://u:p@db-host:5433/equity_research"


def test_daemon_config_carries_market_feed_keys() -> None:
    """The fast-clock market-feed provider keys are surfaced on the config."""
    from src.reactive.daemon import config as config_mod

    env = {
        **_FAKE_ENV,
        "MASSIVE_API_KEY": "feed-key",
        "MASSIVE_REST_URL": "https://api.massive.example",
    }
    with mock.patch.dict(os.environ, env, clear=False):
        cfg = config_mod.DaemonConfig.from_env()

    assert cfg.market_feed_api_key == "feed-key"
    assert cfg.market_feed_rest_url == "https://api.massive.example"


def test_paper_flag_overridable_to_false_but_defaults_true() -> None:
    """``DAEMON_PAPER`` can be set, but absent it defaults to paper-only."""
    from src.reactive.daemon import config as config_mod

    with mock.patch.dict(os.environ, {**_FAKE_ENV, "DAEMON_PAPER": "0"}, clear=False):
        cfg = config_mod.DaemonConfig.from_env()
    assert cfg.paper is False

    with mock.patch.dict(os.environ, _FAKE_ENV, clear=False):
        cfg_default = config_mod.DaemonConfig.from_env()
    assert cfg_default.paper is True


def test_db_module_does_not_open_connection_on_import() -> None:
    """Importing ``db`` opens no connection; the lifecycle is explicit."""
    with mock.patch("psycopg.connect") as connect:
        import src.reactive.daemon.db as db_mod  # noqa: F401

    connect.assert_not_called()
    assert hasattr(db_mod, "DaemonConnection")


def test_db_connection_lifecycle_opens_and_closes_owned_conn() -> None:
    """``DaemonConnection`` opens exactly one conn via _dsn and closes it."""
    from src.reactive.daemon import config as config_mod
    from src.reactive.daemon import db as db_mod

    fake_conn = mock.MagicMock()
    with mock.patch("psycopg.connect", return_value=fake_conn) as connect:
        with mock.patch.dict(os.environ, _FAKE_ENV, clear=False):
            cfg = config_mod.DaemonConfig.from_env()
            handle = db_mod.DaemonConnection(cfg)
            # Lazy: no connection until open() is called.
            connect.assert_not_called()
            conn = handle.open()
            connect.assert_called_once()
            assert conn is fake_conn
            # The per-cycle transaction helper delegates to conn.transaction().
            handle.cycle_transaction()
            fake_conn.transaction.assert_called_once()
            handle.close()
            fake_conn.close.assert_called_once()


def test_python_dash_m_entrypoint_builds_config_without_connection() -> None:
    """``python -m src.reactive.daemon`` imports + builds config, opens no conn.

    Drives the literal Observable via a subprocess. The entrypoint is run in a
    mode that constructs ``DaemonConfig.from_env`` and exits 0 without entering
    the loop or opening a connection (guarded by ``DAEMON_SMOKE=1``).
    """
    env = {
        **os.environ,
        **_FAKE_ENV,
        "DAEMON_SMOKE": "1",
        "PYTHONPATH": str(_REPO_ROOT),
    }
    proc = subprocess.run(
        [sys.executable, "-m", "src.reactive.daemon"],
        cwd=str(_REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    # The smoke path prints the resolved config marker, proving construction.
    assert "DaemonConfig" in proc.stdout


def test_env_example_carries_daemon_keys() -> None:
    """``.env.example`` carries the new daemon config section + keys."""
    text = (_REPO_ROOT / ".env.example").read_text()
    for key in (
        "DAEMON_PAPER",
        "DAEMON_ASSESS_MAX_LATENCY_SECONDS",
        "DAEMON_POLL_TIMEOUT_SECONDS",
        "DAEMON_EVAL_CADENCE_SECONDS",
        "DAEMON_INTAKE_POLL_CADENCE_SECONDS",
        "DAEMON_STOP_LOSS_ATR_MULT",
    ):
        assert key in text, f"missing daemon key {key} in .env.example"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
