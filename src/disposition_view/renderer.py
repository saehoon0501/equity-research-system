"""Terminal-rendered markdown for /disposition.

Per v3 spec Section 4.6 Q2 schema:

    disposition_row:
      ticker: NVDA
      mode: B'
      primary_horizon: mid
      short_horizon: { signal, key_signal, detail_collapsed_by_default: true }
      mid_horizon:   { signal, key_signal, detail_expanded_by_default: true }   # PRIMARY
      long_horizon:  { signal, key_signal, detail_collapsed_by_default: true }

The renderer emits markdown with:
  - One row per watchlist name in the main multi-horizon table.
  - Primary horizon cell prefixed with `* ` and rendered with the detail
    block expanded.
  - Secondary horizons collapsed inside `<details><summary>...</summary>` so
    the operator can expand on demand (the Claude Code session display +
    GitHub-flavored markdown both render this natively).
  - A supplementary mode-fit dashboard section per Phase 4 Q5.

No third-party dependencies — stdlib only.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Optional, Sequence

from src.disposition_view.horizon_signals import (
    HORIZONS,
    HorizonSignal,
    derive_horizon_signals,
    format_mode_display,
)
from src.disposition_view.loader import DispositionRow
from src.disposition_view.mode_fit_dashboard import derive_flag_status

_HORIZON_TITLES: dict[str, str] = {
    "short": "Short (≤3mo)",
    "mid": "Mid (3-12mo)",
    "long": "Long (12+mo)",
}

_FLAG_LABELS: dict[str, str] = {
    "rule_output_mismatch": "rule_output_mismatch",
    "vol_band_inconsistency": "vol_band_inconsistency",
    "pending_reclassification": "pending_reclassification",
    "none": "OK",
}


def render_disposition(
    rows: Sequence[DispositionRow],
    *,
    primary_overrides: Optional[Mapping[str, str]] = None,
    title: str = "Multi-Horizon Disposition View",
) -> str:
    """Render the full /disposition view.

    Per v3 Section 4.6 Q2:
      - Main multi-horizon table
      - Per-row expanded primary horizon detail
      - Mode-fit dashboard supplementary section (Phase 4 Q5)

    Args:
        rows:               loaded DispositionRow list (one per watchlist name).
        primary_overrides:  optional {ticker: horizon} from CLI --toggle-primary.
        title:              top-level header.
    """
    primary_overrides = primary_overrides or {}
    out: list[str] = []
    out.append(f"# {title}")
    out.append("")
    if not rows:
        out.append("_No watchlist names match the requested filters._")
        return "\n".join(out)

    # ----- Main multi-horizon table -----
    out.append("## Watchlist (one row per name)")
    out.append("")
    out.append(
        "| Ticker | Mode | Primary | Short (≤3mo) | Mid (3-12mo) | Long (12+mo) |"
    )
    out.append(
        "|---|---|---|---|---|---|"
    )

    # Cache horizons per ticker for the per-row detail section below.
    per_ticker_signals: dict[str, dict[str, HorizonSignal]] = {}

    for row in rows:
        primary = primary_overrides.get(row.ticker)
        signals = derive_horizon_signals(row, primary_override=primary)
        per_ticker_signals[row.ticker] = signals
        primary_h = next(h for h, s in signals.items() if s.is_primary)
        out.append(
            "| {tk} | {md} | {pr} | {sh} | {mi} | {lo} |".format(
                tk=row.ticker,
                md=_md_escape(format_mode_display(row.mode)),
                pr=primary_h,
                sh=_cell(signals["short"], primary=(primary_h == "short")),
                mi=_cell(signals["mid"], primary=(primary_h == "mid")),
                lo=_cell(signals["long"], primary=(primary_h == "long")),
            )
        )

    out.append("")
    out.append(
        "_Mode-anchored primary horizon prefixed with `*`. "
        "Expand details below; toggle with `--toggle-primary <T> <horizon>`._"
    )
    out.append("")

    # ----- Per-row detail blocks -----
    out.append("## Per-name detail")
    out.append("")
    for row in rows:
        signals = per_ticker_signals[row.ticker]
        out.append(_render_ticker_block(row, signals))
        out.append("")

    # ----- Mode-fit dashboard -----
    out.append("## Mode-Fit Dashboard (Phase 4 Q5)")
    out.append("")
    out.append(render_mode_fit_dashboard(rows))
    return "\n".join(out)


def render_single_ticker(
    row: DispositionRow,
    *,
    primary_override: Optional[str] = None,
) -> str:
    """Render a single ticker's expanded disposition.

    Used by `--ticker <T>` CLI flag for focused name detail.
    """
    signals = derive_horizon_signals(row, primary_override=primary_override)
    out: list[str] = []
    out.append(f"# Disposition — {row.ticker} (mode {format_mode_display(row.mode)})")
    out.append("")
    primary_h = next(h for h, s in signals.items() if s.is_primary)
    out.append(f"**Primary horizon (mode-anchored):** `{primary_h}`")
    if primary_override:
        out.append(f"**Operator override active:** `{primary_override}`")
    out.append("")
    out.append(_render_ticker_block(row, signals))
    out.append("")
    out.append("## Mode-Fit (Phase 4 Q5)")
    out.append("")
    out.append(render_mode_fit_dashboard([row]))
    return "\n".join(out)


# -----------------------------------------------------------------------------
# Mode-fit dashboard
# -----------------------------------------------------------------------------


def render_mode_fit_dashboard(rows: Sequence[DispositionRow]) -> str:
    """Per Phase 4 Q5 — per-name mode | realized_252d_vol |
    last_confirmed_date | flag_status table.
    """
    out: list[str] = []
    out.append(
        "| Ticker | Mode | realized_252d_vol | mode_band | last_confirmed_date | flag_status |"
    )
    out.append("|---|---|---|---|---|---|")
    for row in rows:
        mf = row.mode_fit
        flag = derive_flag_status(mf)
        flag_label = _FLAG_LABELS.get(flag, flag)
        if mf.realized_vol_252d is None:
            vol_cell = "_n/a_"
        else:
            vol_cell = f"{mf.realized_vol_252d:.1%}"
        if mf.mode_band_low is None or mf.mode_band_high is None:
            band_cell = "_n/a_"
        else:
            band_cell = f"{mf.mode_band_low:.0%}–{mf.mode_band_high:.0%}"
        confirmed = (
            mf.last_confirmed_date.isoformat()
            if mf.last_confirmed_date
            else "_never_"
        )
        out.append(
            f"| {row.ticker} | {_md_escape(format_mode_display(mf.mode))} | {vol_cell} | "
            f"{band_cell} | {confirmed} | **{flag_label}** |"
        )
    out.append("")
    out.append(
        "_Flag types: `rule_output_mismatch` (quarterly reclassification "
        "flagged different mode), `vol_band_inconsistency` (realized vol "
        "outside band for ≥2 consecutive checks), `pending_reclassification` "
        "(awaiting pre-mortem + operator commit), `OK` (within band + "
        "last classification confirmed)._"
    )
    return "\n".join(out)


# -----------------------------------------------------------------------------
# Ticker block (per-name detail with primary expanded; secondary collapsed)
# -----------------------------------------------------------------------------


def _render_ticker_block(
    row: DispositionRow, signals: Mapping[str, HorizonSignal]
) -> str:
    out: list[str] = []
    primary_h = next(h for h, s in signals.items() if s.is_primary)
    out.append(
        f"### {row.ticker} — mode {format_mode_display(row.mode)} — primary `{primary_h}`"
    )
    out.append("")
    held = row.shares_held
    if held and held > 0:
        out.append(
            f"_Held: {held:g} shares; cost-basis ${row.cost_basis:.2f}; "
            f"first acquired {row.first_acquired.isoformat() if row.first_acquired else '_n/a_'}_"
        )
    else:
        out.append("_Not currently held (watchlist-only)._")
    out.append("")

    # Render in canonical order — primary first if it isn't already short,
    # but we preserve short → mid → long for consistency. The 'PRIMARY' marker
    # tells the operator which to scan first.
    for h in HORIZONS:
        sig = signals[h]
        out.append(_render_horizon_section(sig))
        out.append("")
    return "\n".join(out)


def _render_horizon_section(sig: HorizonSignal) -> str:
    title = _HORIZON_TITLES[sig.horizon]
    if sig.is_primary:
        # Primary horizon — render the detail expanded by default.
        out: list[str] = []
        out.append(f"#### {title}  *** PRIMARY ***")
        out.append("")
        out.append(f"- **Signal:** {sig.signal}")
        out.append(f"- **Key:** {sig.key_signal}")
        out.append("")
        out.append("```yaml")
        out.append(f"{sig.horizon}_horizon:")
        out.append(f"  signal: {sig.signal}")
        out.append(f"  key_signal: {_yaml_escape(sig.key_signal)}")
        out.append("  detail_expanded_by_default: true")
        out.append("  detail:")
        out.append(_yaml_indent(sig.detail, 4))
        out.append("```")
        return "\n".join(out)
    else:
        # Secondary — collapse the detail into <details><summary>.
        out = []
        out.append(
            f"<details><summary><strong>{title}</strong> — "
            f"{sig.signal}: {_md_escape(sig.key_signal)} "
            f"<em>(click to expand)</em></summary>"
        )
        out.append("")
        out.append("```yaml")
        out.append(f"{sig.horizon}_horizon:")
        out.append(f"  signal: {sig.signal}")
        out.append(f"  key_signal: {_yaml_escape(sig.key_signal)}")
        out.append("  detail_collapsed_by_default: true")
        out.append("  detail:")
        out.append(_yaml_indent(sig.detail, 4))
        out.append("```")
        out.append("")
        out.append("</details>")
        return "\n".join(out)


# -----------------------------------------------------------------------------
# Cell rendering for the main table
# -----------------------------------------------------------------------------


def _cell(sig: HorizonSignal, *, primary: bool) -> str:
    """One cell in the multi-horizon table.

    Per Section 4.6 Q2 schema: emits 'SIGNAL — key_signal'. Primary horizon
    cell prefixes with '*' marker.
    """
    marker = "* " if primary else ""
    text = f"{sig.signal} — {_md_escape(sig.key_signal)}"
    # Truncate long key_signal text to keep table readable.
    if len(text) > 80:
        text = text[:77] + "..."
    return f"{marker}{text}"


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _md_escape(value: Any) -> str:
    if value is None:
        return ""
    s = str(value)
    return s.replace("|", "\\|").replace("\n", " ")


def _yaml_escape(value: Any) -> str:
    if value is None:
        return "null"
    s = str(value)
    if any(c in s for c in [":", "{", "}", "[", "]", "#", "&", "*"]):
        return json.dumps(s)
    return s


def _yaml_indent(payload: Mapping[str, Any], indent: int) -> str:
    """Indent a JSON-serializable payload as YAML-ish content for display.

    We use json.dumps with indent and prefix each line; quick + safe even for
    nested arrays / dicts. Output is purely informational — not round-tripped.
    """
    if payload is None or payload == {}:
        return " " * indent + "{}"
    text = json.dumps(payload, indent=2, default=str, sort_keys=True)
    lines = text.splitlines()
    pad = " " * indent
    return "\n".join(pad + line for line in lines)
