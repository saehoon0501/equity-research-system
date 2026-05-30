"""Process entrypoint — ``python -m src.reactive.daemon`` (task 1.2 scaffold).

Task 1.2 builds the **scaffold + config/db lifecycle** only. The Observable is:
``python -m src.reactive.daemon`` imports and constructs a ``DaemonConfig`` from
env *without opening a connection*.

The full single-eval loop (build conn + config, run the loop, restart-safe) is
**task 4.4** — Phase 2, blocked on ``survival-gate`` (`src/survival/gate.py`).
Until that lands, the entrypoint supports two paths:

  * ``DAEMON_SMOKE=1`` — build the config from env, print a one-line marker, and
    exit 0. Opens no connection. This is the by-value config-build Observable.
  * default — build the config (still no connection at this stage of the build),
    then exit with a clear "loop not yet wired" message rather than pretending
    to run. Wiring the loop here would require ``survival-gate``, which is not
    yet on disk; doing so now would violate the Phase-2 dependency gate (P14).
"""

from __future__ import annotations

import os
import sys

from src.reactive.daemon.config import DaemonConfig


def main(argv: list[str] | None = None) -> int:
    """Build the daemon config from env. Returns a process exit code.

    Constructing ``DaemonConfig.from_env`` is a pure read of env and opens no
    connection (the connection lifecycle is owned explicitly by ``db.py`` and is
    not entered here in the 1.2 scaffold).
    """
    config = DaemonConfig.from_env()

    if os.environ.get("DAEMON_SMOKE") == "1":
        # Config-build smoke: prove construction without opening a connection.
        print(
            f"DaemonConfig(paper={config.paper}, "
            f"assess_max_latency_seconds={config.assess_max_latency_seconds}, "
            f"eval_cadence_seconds={config.eval_cadence_seconds})"
        )
        return 0

    # The eval loop is task 4.4 (blocked on survival-gate); not wired in the 1.2
    # scaffold. Exit cleanly rather than entering a non-existent loop.
    print(
        "execution-daemon: config built; the evaluation loop is not yet wired "
        "(task 4.4, blocked on survival-gate). Set DAEMON_SMOKE=1 to build the "
        "config and exit 0.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
