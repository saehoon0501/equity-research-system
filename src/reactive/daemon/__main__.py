"""Process entrypoint — ``python -m src.reactive.daemon`` (task 4.4).

The persistent execution daemon's process entrypoint. Two paths:

  * ``DAEMON_SMOKE=1`` — build the ``DaemonConfig`` from env, print a one-line
    marker, and exit 0. Opens **no connection** (the by-value config-build
    Observable from task 1.2; kept so a quick "does the config build?" smoke
    needs no DB).
  * default — **run the loop** (task 4.4): build the owned connection + config and
    drive the persistent single-eval loop via :func:`loop.build_and_run`,
    restart-safe (the connection lifecycle is a context manager; the epoch is
    re-minted per start; all durable state is in the append-only DB tables).

The live drive (``build_and_run``) needs a running Postgres (a live
``parameters_active`` to pin, a broker session, the market feed) — an
``integration_live`` bring-up, **not** an inner-ring unit (P14). The loop LOGIC
(single-eval, intake-first, cadence, fail-toward-minimum-exposure) is unit-tested
in ``tests/unit/reactive/daemon/test_loop.py`` against synthetic deps; this
entrypoint is the production wiring of those tested pieces. Until a DB is up,
``build_and_run`` raises a clear ``NotImplementedError`` naming the deferred live
seam rather than pretending to run.
"""

from __future__ import annotations

import os
import sys

from src.reactive.daemon.config import DaemonConfig


def main(argv: list[str] | None = None) -> int:
    """Run the daemon (or, under ``DAEMON_SMOKE=1``, just build the config).

    Returns a process exit code. The default path enters
    :func:`src.reactive.daemon.loop.build_and_run` — the persistent loop drive.
    """
    if os.environ.get("DAEMON_SMOKE") == "1":
        # Config-build smoke: prove construction without opening a connection.
        config = DaemonConfig.from_env()
        print(
            f"DaemonConfig(paper={config.paper}, "
            f"assess_max_latency_seconds={config.assess_max_latency_seconds}, "
            f"eval_cadence_seconds={config.eval_cadence_seconds})"
        )
        return 0

    # Default: run the persistent loop (task 4.4). Imported here so the smoke /
    # config path pulls in no loop/DB machinery.
    from src.reactive.daemon.loop import build_and_run

    try:
        return build_and_run()
    except NotImplementedError as exc:
        # The live drive needs a running DB + broker + feed (deferred
        # integration_live bring-up, P14). Surface the deferred-seam message
        # cleanly rather than crashing with a traceback.
        print(f"execution-daemon: {exc}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
