"""Daemon configuration — DSN + the by-value run-config (task 1.2).

Boundary: config (Requirements 1, 3).

``_dsn()`` mirrors ``src/reactive/telemetry/trace_writer.py::_dsn`` exactly so
the daemon, the telemetry writer, and their tests all build the Postgres DSN
the same way (a single house convention; the repo has no connection pool).

``DaemonConfig`` is the daemon's pinned-by-value run configuration — paper
flag, the survival ``assess`` max-latency interval (Req 1.2), the bounded
order-poll timeout (Req 3.2 — a slow venue poll must not stall the loop past
the assess cadence), the eval-loop cadence, the command-intake poll cadence
(the loop polls intake first each cycle), the protective-stop ATR multiplier
(Req 11.3 — the daemon owns the stop-loss as an *order parameter*), and the
fast-clock market-feed provider keys (§14.10 — accessed directly, not via the
MCP wrapper).

Building a ``DaemonConfig`` is a **pure read of env**: it opens no connection
(P2 — pin by value at the boundary; the connection lifecycle is owned by
``db.py``, never a config side effect).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# v0.1 paper-only defaults (Req 1, 3). All are by-value at config-build time and
# do not change mid-run; the loop reads them once and propagates by value (P2).
_DEFAULT_ASSESS_MAX_LATENCY_SECONDS = 5.0
_DEFAULT_POLL_TIMEOUT_SECONDS = 2.0
_DEFAULT_EVAL_CADENCE_SECONDS = 1.0
_DEFAULT_INTAKE_POLL_CADENCE_SECONDS = 1.0
_DEFAULT_STOP_LOSS_ATR_MULT = 2.0

# Fast-clock market-feed provider (the massive.com / Polygon-compatible feed,
# §14.10). The daemon reads the same provider keys ``src/mcp/massive`` uses, but
# accesses the feed directly — the concrete client is a later task (3.6); here
# the keys are surfaced onto the config so that task has a single source.
_DEFAULT_MARKET_FEED_REST_URL = "https://api.massive.com"


def _dsn() -> str:
    """Build the Postgres DSN from env — mirrors
    ``src/reactive/telemetry/trace_writer.py::_dsn`` exactly.

    The daemon owns its connection (§14.10); this is the single DSN helper its
    ``db.py`` and tests share. Host/port default to ``127.0.0.1:5432`` for local
    dev; inside a container the compose service must set ``POSTGRES_HOST``.
    """
    return (
        f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
        f"@{os.environ.get('POSTGRES_HOST', '127.0.0.1')}:{os.environ.get('POSTGRES_PORT', '5432')}"
        f"/{os.environ['POSTGRES_DB']}"
    )


def _env_bool(name: str, default: bool) -> bool:
    """Parse a boolean env var; absent → ``default``.

    Truthy: ``1/true/yes/on`` (case-insensitive). Anything else → False.
    Used for the paper flag, which defaults to True (v0.1 paper-only).
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    """Parse a positive-float env var; absent/blank → ``default``."""
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


@dataclass(frozen=True)
class DaemonConfig:
    """Pinned-by-value daemon run configuration (P2).

    Frozen: once built from env at startup it does not mutate mid-run. The DSN
    is carried so ``db.DaemonConnection`` opens the owned connection from it
    without re-reading env.
    """

    # Paper/dry-run flag — v0.1 is paper-only and there is no live transmission
    # path (Req 3.1). Defaults to True; an explicit ``DAEMON_PAPER=0`` is the
    # only way to clear it (and v0.1 wires no live path regardless).
    paper: bool

    # Survival ``assess`` standing-monitor max-latency interval (Req 1.2) — the
    # hard upper bound between standing-monitor invocations when no order is
    # contemplated.
    assess_max_latency_seconds: float

    # Bounded order-poll timeout (Req 3.2/3.3) — a slow venue poll surfaces
    # ``unconfirmed`` rather than stalling the single-threaded loop.
    poll_timeout_seconds: float

    # Eval-loop cadence — the monotonic tick interval of the single-eval loop.
    eval_cadence_seconds: float

    # Command-intake poll cadence — the loop polls intake first each cycle.
    intake_poll_cadence_seconds: float

    # Protective-stop ATR multiplier (Req 11.3) — stop_loss price level =
    # reference_price ∓ (atr × stop_loss_atr_mult). The SL is an order
    # parameter the daemon owns, not a survival/edge value (not a P7 recompute).
    stop_loss_atr_mult: float

    # Fast-clock market-feed provider keys (§14.10) — surfaced for the concrete
    # feed client (task 3.6); the daemon accesses the feed directly, not via MCP.
    market_feed_api_key: str | None
    market_feed_rest_url: str

    # The Postgres DSN, resolved once at build time and carried by value so the
    # owned connection opens from it (db.py) without a second env read.
    dsn: str

    @classmethod
    def from_env(cls) -> "DaemonConfig":
        """Construct the config from env — a pure read, opens NO connection.

        Pinning by value at the boundary (P2): every field is resolved here,
        once, at daemon startup. The DSN is resolved (which requires the
        ``POSTGRES_*`` vars) but no connection is opened — that is ``db.py``.
        """
        return cls(
            paper=_env_bool("DAEMON_PAPER", default=True),
            assess_max_latency_seconds=_env_float(
                "DAEMON_ASSESS_MAX_LATENCY_SECONDS",
                _DEFAULT_ASSESS_MAX_LATENCY_SECONDS,
            ),
            poll_timeout_seconds=_env_float(
                "DAEMON_POLL_TIMEOUT_SECONDS", _DEFAULT_POLL_TIMEOUT_SECONDS
            ),
            eval_cadence_seconds=_env_float(
                "DAEMON_EVAL_CADENCE_SECONDS", _DEFAULT_EVAL_CADENCE_SECONDS
            ),
            intake_poll_cadence_seconds=_env_float(
                "DAEMON_INTAKE_POLL_CADENCE_SECONDS",
                _DEFAULT_INTAKE_POLL_CADENCE_SECONDS,
            ),
            stop_loss_atr_mult=_env_float(
                "DAEMON_STOP_LOSS_ATR_MULT", _DEFAULT_STOP_LOSS_ATR_MULT
            ),
            market_feed_api_key=os.environ.get("MASSIVE_API_KEY") or None,
            market_feed_rest_url=os.environ.get(
                "MASSIVE_REST_URL", _DEFAULT_MARKET_FEED_REST_URL
            ),
            dsn=_dsn(),
        )
