"""Catalog markdown parser — produces structured CaseRecord objects.

The catalog at `.claude/references/empirical/peak-pain-archetypes/catalog-v0.1.md`
is sector-organized markdown tables. Each row in a sector's table is one case.
This parser walks the markdown, identifies sector tables (via `### <Sector>`
headings) and pre-2008 era tables (via `### Era N — <name>` headings under
the "Pre-2008 expansion" section), and emits a CaseRecord per row.

The parser produces the *raw catalog row* — it does NOT do feature extraction.
The extraction step (`extractor.py`) takes a CaseRecord's raw row text + notes
and runs the LLM call. The parser's job is purely to slice the markdown.

Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
           Section 4.4 + .claude/references/empirical/peak-pain-archetypes/
           catalog-v0.1.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Sector heading map — converts catalog markdown sector headings to canonical
# sector keys used in peak_pain_archetypes.sector and FEATURE_TYPES extension
# blocks.
# ---------------------------------------------------------------------------

SECTOR_HEADINGS: dict[str, str] = {
    "Tech / SaaS": "tech_saas",
    "Semis / Hardware": "semis_hardware",
    "Consumer Discretionary": "consumer_discretionary",
    "Consumer Brands": "consumer_brands",
    "Fintech": "fintech",
    "Healthcare / Biotech": "healthcare_biotech",
    "Industrial / Capital Goods": "industrial",
    "Energy / Commodities": "energy",
    "Communications / Media": "comms_media",
    "International / EM": "international_em",
    "EV / Autos": "ev_autos",
    "REITs / Real Estate": "reits",
    "Recent IPO / SPAC": "recent_ipo_spac",
    "Crypto-Adjacent": "crypto_adjacent",
    "Financials / Banks": "financials_banks",
}

# ---------------------------------------------------------------------------
# Era heading map — pre-2008 expansion eras (Section 4.4 + catalog v0.1).
# ---------------------------------------------------------------------------

ERA_HEADINGS: dict[str, str] = {
    "Era 1 — Dot-com bust (2000-2002)": "dot_com",
    "Era 2 — GFC non-financial (2007-2009)": "gfc_nonfin",
    "Era 3 — 1989-1992 (deep recession + S&L + LBO fallout)": "recession_1989_92",
    "Era 4 — 1973-1982 stagflation": "stagflation_1973_82",
}


@dataclass(frozen=True)
class CaseRecord:
    """One row from the catalog markdown, sliced but not yet feature-extracted.

    Attributes:
        case_id:        Synthesized stable identifier, e.g. "NVDA-2008".
        ticker:         Cleaned ticker, e.g. "NVDA" (parens stripped).
        period:         Original parenthetical period string, e.g. "2007-08".
        sector:         Canonical sector key from SECTOR_HEADINGS, or era key
                        from ERA_HEADINGS.
        era_category:   Era classifier — "recent" for 15-sector sweep cases or
                        the era key for pre-2008 expansion cases.
        outcome_raw:    Original outcome cell text (may include parentheticals
                        like "SURVIVOR (Buffett rescue)").
        outcome:        Canonical outcome bucket (SURVIVOR / DILUTED-SURVIVOR /
                        NON-SURVIVOR / TBD).
        peak_dd_pct:    Numeric peak drawdown (negative number). NaN if cell
                        is non-numeric (e.g. ">99%" → -99.5 best-effort).
        raw_row_cells:  All cells of the original markdown row, in order.
        column_headers: Column headers from the parent table (in order).
        descriptive_text: Concatenation of all cells with their headers — the
                        text fed to extractor.py as the LLM input.
    """

    case_id: str
    ticker: str
    period: str
    sector: str
    era_category: str
    outcome_raw: str
    outcome: str
    peak_dd_pct: float
    raw_row_cells: list[str] = field(default_factory=list)
    column_headers: list[str] = field(default_factory=list)
    descriptive_text: str = ""


# ---------------------------------------------------------------------------
# Outcome canonicalization — the catalog uses freeform parentheticals like
# "TBD-survivor", "SURVIVOR (multi-bag)", "NON-SURVIVOR (Ch11)". We collapse
# to the four buckets that match the CHECK constraint on
# peak_pain_archetypes.outcome.
# ---------------------------------------------------------------------------


def _canonicalize_outcome(raw: str) -> str:
    """Map freeform outcome cell to one of SURVIVOR/DILUTED-SURVIVOR/NON-SURVIVOR/TBD.

    Heuristic — TBD takes precedence (since "TBD-survivor" still hasn't
    resolved). Then DILUTED-SURVIVOR (explicit), NON-SURVIVOR, SURVIVOR.
    """
    upper = raw.upper()
    if "TBD" in upper:
        return "TBD"
    if "DILUTED-SURVIVOR" in upper or "DILUTED SURVIVOR" in upper:
        return "DILUTED-SURVIVOR"
    if "NON-SURVIVOR" in upper:
        return "NON-SURVIVOR"
    if "SURVIVOR" in upper:
        return "SURVIVOR"
    return "TBD"


def _parse_dd_pct(cell: str) -> float:
    """Extract numeric drawdown from a cell like ' -85% ' or ' >-99% ' or '-65 to -80%'.

    Returns negative float (peak DD always < 0). Best-effort — picks the
    first signed integer or float in the cell.
    """
    m = re.search(r"-\s*\d+(?:\.\d+)?", cell)
    if m:
        return float(m.group(0).replace(" ", ""))
    # Fallback for ">99%" (Bluebird) → treat as -99.5
    m2 = re.search(r"(>\s*)?(\d+(?:\.\d+)?)\s*%", cell)
    if m2:
        return -float(m2.group(2))
    return float("nan")


def _slugify_period(period: str) -> str:
    """Turn '(2007-08)' or '(2021-22)' into '2008' or '2022' for case_id.

    Convention: end-year of period; if single year, that year. Handles two
    common shapes:
        '(2021-22)'      -> last-year is '22' → '2022' (century from prev 4-digit)
        '(2014-16)'      -> '2016'
        '(2007-08)'      -> '2008'
        '(2020)'         -> '2020'
        '(2021-23)'      -> '2023'
        '(2007)'         -> '2007'
        '(2007-09)'      -> '2009'
    """
    # Find ALL year-like tokens — both 4-digit and 2-digit — preserving order.
    # We tokenize on non-digit boundaries so '2007-08' yields ['2007', '08'].
    tokens = re.findall(r"\d+", period)
    if not tokens:
        return "unknown"
    last = tokens[-1]
    if len(last) == 4:
        return last
    if len(last) == 2:
        # Find a preceding 4-digit token to inherit century from
        for t in tokens:
            if len(t) == 4:
                return t[:2] + last
        return "20" + last
    return last


def _build_case_id(ticker: str, period: str) -> str:
    return f"{ticker}-{_slugify_period(period)}"


def _strip_ticker(cell: str) -> tuple[str, str]:
    """Split ticker cell into (ticker, year-bearing parenthetical).

    Cells take three shapes:
      ' SHOP (2021-22) '          → ('SHOP', '(2021-22)')
      ' FSR (Fisker) (2021-24) '  → ('FSR',  '(2021-24)')   [year-bearing wins]
      ' BBRY (2008-13) '          → ('BBRY', '(2008-13)')

    Strategy: take the first ticker-shaped token, then SCAN every parenthetical
    in the cell and pick the first one that contains 2-or-4-digit year tokens.
    Falls back to the last parenthetical if no year-bearing one is present
    (preserves prior behaviour for cells like 'FOO (Note)').
    """
    cell = cell.strip()
    m = re.match(r"^([A-Za-z0-9./]+)", cell)
    if not m:
        return cell, ""
    ticker = m.group(1)
    parens = re.findall(r"\(([^)]+)\)", cell)
    period = next(
        (f"({p})" for p in parens if re.search(r"\d{2,4}", p)),
        f"({parens[-1]})" if parens else "",
    )
    return ticker, period


# ---------------------------------------------------------------------------
# Markdown table parser — minimal, just what we need.
# ---------------------------------------------------------------------------


def _parse_markdown_table(table_lines: list[str]) -> tuple[list[str], list[list[str]]]:
    """Parse a pipe-delimited markdown table into (headers, rows-of-cells)."""
    if not table_lines:
        return [], []
    rows = []
    for raw in table_lines:
        line = raw.strip()
        if not line.startswith("|"):
            continue
        # Drop leading/trailing pipes, split, strip
        cells = [c.strip() for c in line.strip("|").split("|")]
        rows.append(cells)
    if len(rows) < 2:
        return [], []
    headers = rows[0]
    # rows[1] is the |---|---| separator row — skip
    body = [r for r in rows[2:] if r and any(c for c in r)]
    return headers, body


def parse_catalog(catalog_md_path: str | Path) -> list[CaseRecord]:
    """Walk the catalog markdown and emit a CaseRecord per case.

    Args:
        catalog_md_path: Path to catalog-v0.1.md.

    Returns:
        list[CaseRecord], one per case row. Order preserves catalog order
        (sectors first, then pre-2008 eras).
    """
    text = Path(catalog_md_path).read_text(encoding="utf-8")
    lines = text.splitlines()

    cases: list[CaseRecord] = []
    current_section: str | None = None  # canonical sector or era key
    current_era: str = "recent"
    in_pre2008 = False

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Detect "Pre-2008 expansion" toplevel section
        if stripped.startswith("## Pre-2008 expansion"):
            in_pre2008 = True
            i += 1
            continue
        # Detect "## Cases" — the recent 15-sector sweep
        if stripped == "## Cases":
            in_pre2008 = False
            current_era = "recent"
            i += 1
            continue
        # Detect a heading that ends a section we care about (toplevel ##)
        if stripped.startswith("## ") and not stripped.startswith("## Cases"):
            current_section = None

        # Detect ### sector or era heading
        if stripped.startswith("### "):
            heading = stripped[4:].strip()
            if in_pre2008:
                era_key = ERA_HEADINGS.get(heading)
                if era_key:
                    current_era = era_key
                    current_section = era_key
                else:
                    current_section = None
            else:
                sector_key = SECTOR_HEADINGS.get(heading)
                if sector_key:
                    current_section = sector_key
                else:
                    current_section = None
            i += 1
            continue

        # If we're inside a recognized section and hit a table, parse it
        if current_section and stripped.startswith("|"):
            # Collect contiguous table lines
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i])
                i += 1
            headers, body = _parse_markdown_table(table_lines)
            for row_cells in body:
                if not row_cells or not row_cells[0]:
                    continue
                ticker_cell = row_cells[0]
                ticker, period = _strip_ticker(ticker_cell)
                if not ticker:
                    continue
                case_id = _build_case_id(ticker, period)
                # Outcome column is typically index 2 (after Ticker, Peak DD)
                outcome_raw = row_cells[2] if len(row_cells) > 2 else ""
                peak_dd_cell = row_cells[1] if len(row_cells) > 1 else ""
                desc = _build_descriptive_text(headers, row_cells)
                # Append per-case forensic evidence if a sidecar file exists.
                # Path: <catalog_dir>/evidence/<case_id>.md. Operator (or the
                # `peak_pain_evidence_builder.py` subagent dispatcher) authors
                # these to get descriptive_text past the ~600-char threshold
                # the 3-LLM consensus pipeline needs to ground 6+ verbatim
                # quotes per case at HIGH consensus.
                #
                # Filename sanitization: case_ids may contain `/` (e.g.,
                # "TPR/Coach-2014") which would create unwanted subdirs in
                # filesystem paths. Replace with `_` so the file resolves
                # to a single evidence/<sanitized>.md.
                _safe_case_id = case_id.replace("/", "_")
                evidence_path = (
                    Path(catalog_md_path).parent / "evidence" / f"{_safe_case_id}.md"
                )
                if evidence_path.exists():
                    try:
                        forensic = evidence_path.read_text(encoding="utf-8").strip()
                        if forensic:
                            desc = desc + "\n\nFORENSIC EVIDENCE:\n" + forensic
                    except OSError:
                        # Filesystem hiccup — proceed with table-only desc;
                        # the consensus pipeline will route to pending/disputed
                        # which is the correct degraded behavior.
                        pass
                rec = CaseRecord(
                    case_id=case_id,
                    ticker=ticker,
                    period=period,
                    sector=current_section,
                    era_category=current_era if in_pre2008 else "recent",
                    outcome_raw=outcome_raw,
                    outcome=_canonicalize_outcome(outcome_raw),
                    peak_dd_pct=_parse_dd_pct(peak_dd_cell),
                    raw_row_cells=list(row_cells),
                    column_headers=list(headers),
                    descriptive_text=desc,
                )
                cases.append(rec)
            continue

        i += 1

    return cases


def _build_descriptive_text(headers: list[str], cells: list[str]) -> str:
    """Construct the descriptive text fed to the LLM extractor.

    Format: 'header1: cell1\\nheader2: cell2\\n...' so the LLM can see what
    each value annotates. The extractor prompt frames this as evidence for
    the verbatim-quote requirement.
    """
    parts = []
    for h, c in zip(headers, cells):
        if h and c:
            parts.append(f"{h}: {c}")
    return "\n".join(parts)
