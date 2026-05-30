"""Inner-ring guard for the daemon runtime dependency manifest (task 1.5).

Boundary: packaging (Requirements 1, 3). Asserts the Observable from tasks.md
1.5: a manifest exists that pins the daemon's four runtime deps
(``psycopg[binary]>=3.2``, ``httpx>=0.27``, ``numpy``, ``python-dotenv``) in the
per-package pin style of ``src/shared/regime_sidecar/pyproject.toml:11``, and the
listed deps are importable in the current interpreter (the verification method
named in the task: ``python -c "import psycopg, httpx, numpy, dotenv"``).

This is a **packaging artifact** test, not a behavioral one — there is no daemon
code path to exercise. It pins (a) the manifest's existence + location (root
``requirements.txt``, gap G2 / research.md Option A), (b) the exact pins so a
verbatim-copy / pin-drift regression is caught, and (c) that the four runtime
imports resolve on the interpreter that runs the daemon. No LLM, no MCP, no live
DB (P14 inner ring).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_MANIFEST = _REPO_ROOT / "requirements.txt"
_REGIME_PYPROJECT = _REPO_ROOT / "src" / "shared" / "regime_sidecar" / "pyproject.toml"


def _requirement_lines() -> list[str]:
    """Non-comment, non-blank requirement lines from the manifest."""
    text = _MANIFEST.read_text()
    lines: list[str] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped)
    return lines


def test_manifest_exists_at_repo_root() -> None:
    """The daemon runtime manifest is a root ``requirements.txt`` (G2 Option A).

    The repo had no root manifest before task 1.5; the daemon rides the existing
    namespace package (no pyproject/uv per tasks.md scope), so its runtime deps
    live in this root manifest, installable on a fresh box / CI / container.
    """
    assert _MANIFEST.is_file(), f"missing daemon runtime manifest at {_MANIFEST}"


def test_manifest_pins_all_four_runtime_deps() -> None:
    """The manifest pins exactly the four runtime deps the daemon imports.

    ``psycopg`` (db.py owned conn), ``httpx`` (3.6 feed client), ``numpy``
    (candidate feature compute), ``python-dotenv`` (conftest/.env load).
    """
    lines = _requirement_lines()
    joined = "\n".join(lines)

    # psycopg with the [binary] extra (libpq wheel — no system libpq on a fresh box).
    assert any(
        re.match(r"psycopg\[binary\]\s*>=\s*3\.2", line) for line in lines
    ), f"psycopg[binary]>=3.2 pin missing/mis-styled in:\n{joined}"

    # httpx lower-bounded at 0.27 (the feed client's REST transport).
    assert any(
        re.match(r"httpx\s*>=\s*0\.27", line) for line in lines
    ), f"httpx>=0.27 pin missing/mis-styled in:\n{joined}"

    # numpy and python-dotenv present (unpinned per the task's pin list).
    names = {re.split(r"[<>=\[\s]", line, maxsplit=1)[0].lower() for line in lines}
    assert "numpy" in names, f"numpy missing in:\n{joined}"
    assert "python-dotenv" in names, f"python-dotenv missing in:\n{joined}"

    # Exactly the daemon's runtime surface — no stray repo-wide deps leaked in.
    assert names == {"psycopg", "httpx", "numpy", "python-dotenv"}, (
        f"manifest must list ONLY the daemon's four runtime deps, got {names}"
    )


def test_psycopg_pin_matches_regime_sidecar_style() -> None:
    """The psycopg pin matches the per-package style (regime_sidecar:11).

    The task fixes the pin style on ``src/shared/regime_sidecar/pyproject.toml:11``
    — ``psycopg[binary]>=3.2.0``. The manifest must carry the same binary-extra,
    lower-bound, no-upper-cap shape so the two stay consistent.
    """
    reference = _REGIME_PYPROJECT.read_text()
    assert "psycopg[binary]>=3.2.0" in reference, (
        "regime_sidecar reference pin moved; re-confirm the manifest style"
    )
    manifest_psycopg = next(
        line for line in _requirement_lines() if line.startswith("psycopg")
    )
    # Same extra + lower-bound shape (the manifest may carry the .0 patch or not;
    # both satisfy >=3.2 — assert the binary extra and the >= operator).
    assert manifest_psycopg.startswith("psycopg[binary]>=3.2")


def test_listed_deps_importable_in_current_interpreter() -> None:
    """The four runtime deps import on the interpreter that runs the daemon.

    This is the task's named verification:
    ``python -c "import psycopg, httpx, numpy, dotenv"``. ``python-dotenv`` is
    imported as the ``dotenv`` package.
    """
    import dotenv  # noqa: F401
    import httpx  # noqa: F401
    import numpy  # noqa: F401
    import psycopg  # noqa: F401


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
