"""CLI for /spec-approve — operator HMAC-attested sign-off on spec revisions.

Usage::

    python -m src.spec_approve.cli <version> [--operator <id>] \\
        [--spec-path <path>] [--scope-summary <text>] [--out <path>]

Per v3 Section 5.4 + Section 8 PB#1. Writes an attestation file matching
the v3.0 template at
``docs/superpowers/specs/v<version>-signoff-attestation.md``.

Exit codes:
    0 - success
    1 - IO error (write failure)
    2 - usage error
    3 - file already exists (refuses to overwrite without --force)
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys
from pathlib import Path
from typing import Sequence

# Reuse the canonical HMAC contract — same module backs all 4 HMAC scopes
# per v3 Section 5.2 / Section 8 PB#1.
from src.audit_trail.hmac_verify import compute_signature_dict


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SPECS_DIR = _REPO_ROOT / "docs" / "superpowers" / "specs"


def _default_spec_path(version: str) -> str:
    """Best-effort resolver: pick the spec file matching `<version>`.

    Returns a relative POSIX path from repo root, or a placeholder
    string if the spec file isn't on disk yet (operator must override).
    """
    matches = sorted(_SPECS_DIR.glob(f"*{version}*.md"))
    matches = [m for m in matches if "signoff" not in m.name]
    if matches:
        return str(matches[0].relative_to(_REPO_ROOT))
    return f"docs/superpowers/specs/<TBD-{version}>.md"


def _build_attestation_md(
    *,
    version: str,
    spec_path: str,
    operator: str,
    timestamp: str,
    signature: str,
    scope_summary: str,
) -> str:
    """Render the attestation Markdown body.

    Mirrors `v3.0-signoff-attestation.md` structure: header block,
    scope-of-approval section, effects section, caveats, next action,
    and the HMAC signature stamp.
    """
    return f"""# v{version} Spec Sign-off Attestation

**Spec version:** {spec_path}
**Approval mode:** HMAC-attested via `/spec-approve` (canonical-payload contract from `src/audit_trail/hmac_verify.py`)
**Operator:** {operator}
**Sign-off timestamp:** {timestamp}
**Approved via:** `python -m src.spec_approve.cli {version}`

## Scope of approval

{scope_summary}

## Effects of sign-off

1. **v{version} frozen** — immutable post-attestation. Subsequent revisions tracked as a new version with explicit change-log per Section 8 PB#1.
2. **Implementation may proceed** per the v{version} spec.
3. **Launch gates active** per v{version} Section 7 (or successor).

## Caveats

- HMAC signature below is computed over a canonical JSON payload of
  (version, spec_path, timestamp, operator) using `AUDIT_HMAC_KEY`.
  Verify by recomputing with the same canonical-payload contract.
- For replay verification, see `src/audit_trail/hmac_verify.py`.

## HMAC signature

```
{signature}
```

---

**Spec-approve attestation captured.** v{version} frozen.
"""


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m src.spec_approve.cli",
        description=(
            "Operator HMAC-attested sign-off on a spec revision. "
            "Per v3 Section 5.4 + Section 8 PB#1."
        ),
    )
    p.add_argument(
        "version",
        help="Spec version string (e.g. '3.1', '3.0').",
    )
    p.add_argument(
        "--operator",
        default=os.environ.get("OPERATOR_ID", "saehoon0501"),
        help="Operator identifier. Defaults to $OPERATOR_ID env var "
        "or 'saehoon0501'.",
    )
    p.add_argument(
        "--spec-path",
        default=None,
        help="Path to the spec file being signed. Defaults to "
        "auto-resolve from `docs/superpowers/specs/`.",
    )
    p.add_argument(
        "--scope-summary",
        default=(
            "Operator approves the v{version} spec for engineering "
            "implementation. See spec change-log for the full set of "
            "locks introduced relative to the prior version."
        ),
        help="Free-form scope-of-approval text. Use '{version}' "
        "placeholder for substitution.",
    )
    p.add_argument(
        "--out",
        default=None,
        help="Output path for the attestation file. Defaults to "
        "docs/superpowers/specs/v<version>-signoff-attestation.md.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing attestation file if present.",
    )
    args = p.parse_args(argv)

    version = args.version.lstrip("v")
    spec_path = args.spec_path or _default_spec_path(version)
    timestamp = _dt.datetime.now(_dt.timezone.utc).isoformat()

    payload = {
        "version": version,
        "spec_path": spec_path,
        "timestamp": timestamp,
        "operator": args.operator,
    }
    hmac_key = os.environ.get("AUDIT_HMAC_KEY", "")
    if not hmac_key:
        print(
            "WARN: AUDIT_HMAC_KEY env var not set; attestation will "
            "be signed with empty key (verifier will flag).",
            file=sys.stderr,
        )
    signature = compute_signature_dict(
        payload, hmac_key.encode("utf-8") if hmac_key else b""
    )

    out_path = (
        Path(args.out)
        if args.out
        else _SPECS_DIR / f"v{version}-signoff-attestation.md"
    )
    if out_path.exists() and not args.force:
        print(
            f"ERROR: {out_path} already exists. Use --force to "
            "overwrite (rare; sign-offs are append-only by convention).",
            file=sys.stderr,
        )
        return 3

    body = _build_attestation_md(
        version=version,
        spec_path=spec_path,
        operator=args.operator,
        timestamp=timestamp,
        signature=signature,
        scope_summary=args.scope_summary.replace("{version}", version),
    )
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(body, encoding="utf-8")
    except OSError as e:
        print(f"ERROR: failed to write {out_path}: {e}", file=sys.stderr)
        return 1
    try:
        rendered_path: str = str(out_path.relative_to(_REPO_ROOT))
    except ValueError:
        # Out path is outside repo root (test tmp dir, operator override).
        rendered_path = str(out_path)
    print(f"Wrote {rendered_path}")
    print(f"HMAC: {signature}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
