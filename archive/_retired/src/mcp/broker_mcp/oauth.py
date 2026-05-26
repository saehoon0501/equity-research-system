"""OAuth 2.0 token management for broker MCPs.

Per `docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md`
Section 4.6 (broker MCP architecture) + Section 7.1 launch gate ("Broker MCP
OAuth flow tested; token refresh validated").

Token storage:
  - Tokens are written to / read from the repo-root `.env` file via
    python-dotenv (same convention as `EDGAR_USER_AGENT`,
    `POSTGRES_PASSWORD`).
  - `.env` is gitignored. Tokens NEVER land in version control.
  - This module exposes `load_tokens()` / `save_tokens()` helpers; the
    adapter is the only caller. Skills / agents do not read tokens.

Initial-bring-up flow (operator-driven, ONE-time per broker per machine):
  1. Operator registers an app with the broker (e.g., Schwab developer
     portal); records `BROKER_CLIENT_ID` + `BROKER_CLIENT_SECRET` in `.env`.
  2. Operator runs `python -m broker_mcp.oauth authorize` (or the broker-
     specific equivalent in `schwab_adapter.py`); browser opens, operator
     authorizes the read-only scope, callback URL receives the auth code.
  3. Auth code is exchanged for `access_token` + `refresh_token`; both
     written back to `.env` via `save_tokens()`.
  4. From here on, runtime calls use `load_tokens()` and silently refresh
     when access expires.

For CI / mocked tests we bypass this entirely; see
`tests/test_broker_mcp.py`.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv

# Walk: oauth.py → broker_mcp/ → mcp/ → src/ → repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
_ENV_PATH = _REPO_ROOT / ".env"

load_dotenv(_ENV_PATH)


@dataclass
class OAuthTokens:
    """Snapshot of the current token set for one broker.

    Attributes:
        access_token: short-lived bearer token used on API calls.
        refresh_token: long-lived token used to mint new access tokens.
        expires_at_epoch: Unix timestamp when `access_token` expires.
    """

    access_token: str
    refresh_token: str
    expires_at_epoch: int

    def is_expired(self, skew_seconds: int = 60) -> bool:
        """True if access token is within `skew_seconds` of expiring."""
        return time.time() + skew_seconds >= self.expires_at_epoch


def load_tokens(prefix: str) -> OAuthTokens | None:
    """Load tokens from `.env` for a given broker prefix.

    Args:
        prefix: env-var prefix per broker, e.g., 'SCHWAB' resolves to
                SCHWAB_ACCESS_TOKEN / SCHWAB_REFRESH_TOKEN /
                SCHWAB_TOKEN_EXPIRES_AT.

    Returns:
        OAuthTokens if all three vars are present; None otherwise (caller
        should trigger the operator-driven authorize flow).
    """
    access = os.environ.get(f"{prefix}_ACCESS_TOKEN")
    refresh = os.environ.get(f"{prefix}_REFRESH_TOKEN")
    expires = os.environ.get(f"{prefix}_TOKEN_EXPIRES_AT")
    if not (access and refresh and expires):
        return None
    try:
        expires_at_epoch = int(expires)
    except ValueError:
        return None
    return OAuthTokens(
        access_token=access,
        refresh_token=refresh,
        expires_at_epoch=expires_at_epoch,
    )


def save_tokens(prefix: str, tokens: OAuthTokens) -> None:
    """Persist tokens back to the repo-root `.env`.

    Idempotent in-place rewrite: existing `{prefix}_ACCESS_TOKEN=...` lines
    are replaced; missing keys are appended. We deliberately do NOT use a
    third-party `dotenv.set_key` helper because the format-preservation
    semantics across python-dotenv versions are inconsistent — we want a
    deterministic, auditable rewrite.

    Atomic-write: rewrite is staged to a sibling `.env.tmp` file and renamed
    via `os.replace` so a crash mid-write cannot leave a torn `.env`. This
    matches Section 7.1 launch gate ("token refresh validated") — an
    interrupted refresh must not corrupt operator credentials.

    Args:
        prefix: env-var prefix, e.g., 'SCHWAB'.
        tokens: token set to persist.
    """
    pairs = {
        f"{prefix}_ACCESS_TOKEN": tokens.access_token,
        f"{prefix}_REFRESH_TOKEN": tokens.refresh_token,
        f"{prefix}_TOKEN_EXPIRES_AT": str(int(tokens.expires_at_epoch)),
    }

    if _ENV_PATH.exists():
        existing = _ENV_PATH.read_text()
    else:
        existing = ""

    lines = existing.splitlines()
    seen: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        match = re.match(r"^([A-Z0-9_]+)=", line)
        if match and match.group(1) in pairs:
            new_lines.append(f"{match.group(1)}={pairs[match.group(1)]}")
            seen.add(match.group(1))
        else:
            new_lines.append(line)
    for key, value in pairs.items():
        if key not in seen:
            new_lines.append(f"{key}={value}")

    # Refresh in-process env so subsequent reads see the new values without
    # requiring a `load_dotenv` round-trip.
    for key, value in pairs.items():
        os.environ[key] = value

    # Atomic write: stage to .env.tmp then os.replace into place. On Unix
    # os.replace is atomic; on Windows it overwrites if dest exists.
    tmp_path = _ENV_PATH.with_suffix(_ENV_PATH.suffix + ".tmp")
    tmp_path.write_text("\n".join(new_lines) + "\n")
    os.replace(tmp_path, _ENV_PATH)


def refresh_access_token(
    *,
    refresh_url: str,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Exchange a refresh_token for a new access_token at `refresh_url`.

    OAuth-2.0 RFC-6749 §6 standard refresh-token grant. Schwab + most
    brokers follow this shape; per-broker quirks (e.g., extra headers,
    Basic vs body credentials) live in the adapter's `_refresh_token()`.

    Args:
        refresh_url: broker token endpoint, e.g.,
            'https://api.schwabapi.com/v1/oauth/token'.
        client_id: registered app client id.
        client_secret: registered app client secret.
        refresh_token: currently held refresh_token.
        timeout: HTTP timeout (seconds).

    Returns:
        Raw JSON response from the broker (caller normalizes into
        `OAuthTokens`).

    Raises:
        httpx.HTTPStatusError: on non-2xx response.
    """
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(
            refresh_url,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            auth=(client_id, client_secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        return resp.json()


# -----------------------------------------------------------------------------
# CLI: `python -m broker_mcp.oauth authorize` — operator-interactive bring-up
# -----------------------------------------------------------------------------

# Schwab Trader OAuth endpoints (default broker). For other brokers wire a
# different `_BROKER_OAUTH_CONFIG` map keyed by `--broker`.
_BROKER_OAUTH_CONFIG: dict[str, dict[str, str]] = {
    "schwab": {
        "prefix": "SCHWAB",
        "client_id_env": "SCHWAB_CLIENT_ID",
        "client_secret_env": "SCHWAB_CLIENT_SECRET",
        "redirect_uri_env": "SCHWAB_REDIRECT_URI",
        "auth_url": "https://api.schwabapi.com/v1/oauth/authorize",
        "token_url": "https://api.schwabapi.com/v1/oauth/token",
        "scope": "readonly",
    },
}


def _build_authorize_url(cfg: dict[str, str], client_id: str, redirect_uri: str) -> str:
    """Construct the broker-specific authorize URL with required query params."""
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": cfg["scope"],
    }
    return f"{cfg['auth_url']}?{urlencode(params)}"


def _exchange_code_for_tokens(
    *,
    token_url: str,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Exchange authorization code for token pair via authorization_code grant.

    OAuth-2.0 RFC-6749 §4.1.3.
    """
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(
            token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            },
            auth=(client_id, client_secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        return resp.json()


def authorize(broker: str = "schwab") -> int:
    """Operator-interactive OAuth bring-up.

    Prints the authorize URL, instructs the operator to open it in a browser,
    authorize the read-only scope, then paste the redirect URL `code` query
    parameter on stdin. Exchanges code for tokens and writes them to `.env`
    via `save_tokens()`.

    Per Section 7.1 launch gate ("Broker MCP OAuth flow tested"). This is a
    one-time-per-broker-per-machine bring-up step.

    Returns:
        0 on success, 1 on missing config, 2 on HTTP / parsing failure.
    """
    cfg = _BROKER_OAUTH_CONFIG.get(broker)
    if cfg is None:
        print(f"ERROR: unknown broker {broker!r}", file=sys.stderr)
        return 1

    client_id = os.environ.get(cfg["client_id_env"])
    client_secret = os.environ.get(cfg["client_secret_env"])
    redirect_uri = os.environ.get(cfg["redirect_uri_env"]) or "https://localhost:8443/callback"

    if not (client_id and client_secret):
        print(
            f"ERROR: {cfg['client_id_env']} and {cfg['client_secret_env']} "
            f"must be set in .env. Register an app with the broker first.",
            file=sys.stderr,
        )
        return 1

    auth_url = _build_authorize_url(cfg, client_id, redirect_uri)
    print(f"Open the following URL in your browser:\n\n  {auth_url}\n")
    print(
        "Authorize the read-only scope. Your browser will redirect to:\n"
        f"  {redirect_uri}?code=<AUTH_CODE>&...\n\n"
        "Copy the value of the `code` query parameter and paste it below.\n"
    )
    sys.stdout.write("Authorization code: ")
    sys.stdout.flush()
    code = sys.stdin.readline().strip()
    if not code:
        print("ERROR: empty authorization code", file=sys.stderr)
        return 2

    try:
        payload = _exchange_code_for_tokens(
            token_url=cfg["token_url"],
            client_id=client_id,
            client_secret=client_secret,
            code=code,
            redirect_uri=redirect_uri,
        )
    except httpx.HTTPStatusError as exc:
        body = exc.response.text if exc.response is not None else ""
        print(
            f"ERROR: token exchange failed (HTTP {exc.response.status_code}): {body}",
            file=sys.stderr,
        )
        return 2
    except Exception as exc:  # noqa: BLE001 — operator-facing CLI surface
        print(f"ERROR: token exchange raised {exc!r}", file=sys.stderr)
        return 2

    expires_in = int(payload.get("expires_in", 1800))
    tokens = OAuthTokens(
        access_token=payload["access_token"],
        refresh_token=payload["refresh_token"],
        expires_at_epoch=int(time.time()) + expires_in,
    )
    save_tokens(cfg["prefix"], tokens)
    print(
        f"\nSuccess: tokens saved to .env. Access token expires in "
        f"{expires_in}s ({expires_in // 60} min). Refresh token will mint "
        "fresh access tokens automatically until the broker's refresh-token "
        "TTL elapses (Schwab: 7 days)."
    )
    return 0


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m broker_mcp.oauth",
        description="Broker-MCP OAuth bring-up CLI (operator-interactive).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    auth = sub.add_parser("authorize", help="Run the OAuth authorization-code flow.")
    auth.add_argument(
        "--broker",
        default="schwab",
        choices=tuple(_BROKER_OAUTH_CONFIG.keys()),
        help="Broker to authorize (default: schwab).",
    )
    args = parser.parse_args(argv)
    if args.cmd == "authorize":
        return authorize(broker=args.broker)
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(_main())
