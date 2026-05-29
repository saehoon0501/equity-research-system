"""Broker (Gate TradFi CFD) configuration and secret resolution.

Source of truth: ``.kiro/specs/broker-cfd-adapter/design.md`` — the ``config``
Components row, "Security Considerations", and the "Live-send gating (4-condition
AND)" flow; plus requirements 8.1 (paper-only default), 8.3 (live = paper-off AND
account-active AND survival-clearance AND kill-clear), 8.4 (kill switch engaged →
block live).

Layer position (``models → config → gate_client → …``): config sits just above
the domain types. It owns two things and no more:

1. **Secret resolution** — read ``GATE_API_KEY`` / ``GATE_API_SECRET`` FRESH from
   the process environment on every call so operator key-rotation needs no
   restart (mirrors the house ``src/mcp/polygon/server.py`` ``_client()`` pattern:
   ``os.environ.get(...).strip()``). When a credential is absent the read returns
   a STRUCTURED result — it NEVER raises (a missing secret must not crash the
   adapter; the conservative posture is to surface a structured error the caller
   can turn into an ``OrderResult``/readout error). Secret VALUES are never logged
   and never echoed back in the error string.

2. **Runtime mode** — the live-send gating inputs, all safe-by-default. Paper /
   dry-run defaults ON (8.1). Survival-gate clearance, the kill switch, and the
   account-active flag are boolean INPUTS the adapter *consumes* (it owns neither
   the clearance state nor the kill-switch state — those belong to
   ``survival-gate``; see design "Out of Boundary"). Their defaults are the SAFE
   state: clearance not present, kill switch not clear, account not active — so a
   freshly-constructed ``RuntimeMode`` permits NO live transmit. Live transmit is
   allowed only when all four 8.3 conditions hold simultaneously.

Config also holds two venue constants: the settlement currency for the in-scope
category and the US-stock CFD ``category_id`` (= 2 per the Gate TradFi API
reference ``/tradfi/symbols/categories``, "stocks = category 2").

This module performs NO transport and constructs no HTTP client; it only reads the
environment and exposes plain value objects. ``models`` is the only intra-broker
import it needs, and only for narrow typing — none is required at runtime, so this
module stays import-light (it must be safe to import under the broker venv without
pulling heavy deps).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

# US-stock CFD category id per the Gate TradFi API reference
# (`/tradfi/symbols/categories`, "stocks = category 2 per §11.3").
US_STOCK_CATEGORY_ID: int = 2

# Default settlement currency for the US-stock CFD category. The venue reports a
# per-symbol `settlement_currency` (see `/tradfi/symbols`); this is the adapter's
# expected settlement currency for the in-scope (US-stock) category.
DEFAULT_SETTLEMENT_CURRENCY: str = "USD"

# Environment variable names for the Gate credentials. The CFD execution venue is
# `gate`, distinct from the pre-existing `BROKER_PROVIDER=schwab` block.
_ENV_API_KEY = "GATE_API_KEY"
_ENV_API_SECRET = "GATE_API_SECRET"


@dataclass(frozen=True)
class Credentials:
    """The structured result of a credential resolution.

    On success ``ok`` is ``True`` and ``api_key`` / ``api_secret`` carry the
    whitespace-stripped values; ``error`` is ``None``. On failure ``ok`` is
    ``False``, the secret fields are ``None``, and ``error`` carries a structured,
    secret-free message naming the missing variable(s). The credential resolver
    NEVER raises (design "Security Considerations" + Req 8.1 conservative posture).

    ``error`` never contains a credential VALUE — only the missing variable
    name(s) — so the result is safe to log / surface downstream.
    """

    ok: bool
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    error: Optional[str] = None


def resolve_credentials() -> Credentials:
    """Read the Gate credentials FRESH from the environment and return a structured
    result. Never raises.

    Both ``GATE_API_KEY`` and ``GATE_API_SECRET`` must be present and non-blank
    after stripping; a partially-set or whitespace-only pair is a structured error
    (we never return a partial-success credential). Reading anew on every call is
    what lets operator key-rotation take effect without a restart — mirrors the
    house ``polygon/server.py`` ``_client()`` ``os.environ.get(...).strip()``
    pattern.
    """
    key = os.environ.get(_ENV_API_KEY, "").strip()
    secret = os.environ.get(_ENV_API_SECRET, "").strip()

    missing: list[str] = []
    if not key:
        missing.append(_ENV_API_KEY)
    if not secret:
        missing.append(_ENV_API_SECRET)

    if missing:
        # Name only the missing variable(s); never the value (it may be blank
        # here, but partial/typo cases must not leak a real secret either).
        return Credentials(
            ok=False,
            api_key=None,
            api_secret=None,
            error="missing Gate credential(s): " + ", ".join(missing),
        )

    return Credentials(ok=True, api_key=key, api_secret=secret, error=None)


@dataclass(frozen=True)
class RuntimeMode:
    """Runtime mode + the four live-send gating inputs, all safe-by-default.

    The adapter consumes ``survival_clearance``, ``kill_switch_clear``, and
    ``account_active`` as boolean INPUTS — it owns none of the underlying state
    (that belongs to ``survival-gate``; see design "Out of Boundary"). Every
    default is the SAFE state, so a default-constructed ``RuntimeMode`` permits no
    live transmit:

    - ``paper_enabled`` defaults ``True`` (Req 8.1 — v0.1 is paper-only).
    - ``account_active`` defaults ``False`` (Req 1.10 / 8.3 — inactive until proven
      active).
    - ``survival_clearance`` defaults ``False`` (Req 8.3 / 8.5 — clearance must be
      explicitly present).
    - ``kill_switch_clear`` defaults ``False`` (Req 8.4 — the kill switch is
      treated as engaged/unknown-safe, i.e. live blocked, until explicitly clear).

    ``settlement_currency`` and ``us_stock_category_id`` carry the venue constants.
    """

    paper_enabled: bool = True
    account_active: bool = False
    survival_clearance: bool = False
    kill_switch_clear: bool = False
    settlement_currency: str = DEFAULT_SETTLEMENT_CURRENCY
    us_stock_category_id: int = US_STOCK_CATEGORY_ID

    def live_transmit_allowed(self) -> bool:
        """Return ``True`` only when ALL four Req 8.3 conditions hold at once:
        paper/dry-run disabled AND account active AND survival clearance present
        AND kill switch clear. Any single condition false → ``False`` (Req 8.4 /
        8.5). v0.1 never satisfies this because ``paper_enabled`` defaults ``True``
        (Req 8.1).
        """
        return (
            (not self.paper_enabled)
            and self.account_active
            and self.survival_clearance
            and self.kill_switch_clear
        )


__all__ = [
    "Credentials",
    "resolve_credentials",
    "RuntimeMode",
    "US_STOCK_CATEGORY_ID",
    "DEFAULT_SETTLEMENT_CURRENCY",
]
