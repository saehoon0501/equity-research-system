r"""Regression test for /review-me v5-final analog-as-prediction retirement (2026-05-24).

Per Stage 1 /research adjudication, single-case historical analog citation as
forecasting evidence is empirically falsified:

- Green & Armstrong 2007 (J. Int. Forecasting 23(3)) — single-analog forecasts
  32% accurate (~chance); multi-analog with experience 60%.
- Tversky-Kahneman 1973/1974 — representativeness heuristic triggers base-rate
  neglect.
- Bessembinder 2018 (JFE 129:3) — 57.4% of US stocks 1926-2016 had returns BELOW
  T-bills; citable-analog pool structurally biased toward surviving 4.3%.
- Mauboussin Base Rate Book 2016 + Measuring the Moat 2024 + Damodaran 2025
  position analogs as illustrative-only, NOT primary forecasting evidence.

The codebase retired the mechanical analog mechanism (peak_pain_archetypes +
counterfactual_veto + §3.5) on 2026-05-17. /review-me v5-final retires the
narrative residual.

This test enforces the post-retirement shape:

  Assertion A — pm-supervisor envelope adversarial_stress_test.kills_fired_evidence[]
                field_path references mechanical thresholds (frameworks_cited.*),
                NOT analog narrative.

  Assertion B — pm-supervisor envelope has NO tl_dr.scenarios_strategic key
                (block deleted entirely per Step 2 of v5-final).

  Assertion C — TL;DR section + §7.6 Strategic Scenarios markdown body of PM
                Report contain ZERO regex \b(CSCO|NOK|IBM)\s+\d{4}(?!-\d{2}-\d{2})
                matches. Analog references confined to report.reasoning.detail and
                report.structural_theory.detail ONLY. ISO-date provenance refs
                (e.g., "MSFT 2026-05-15" BUILD_LOG citations) excluded by negative
                lookahead; MSFT removed from match list (collides with too many
                provenance refs).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest


# Repo-relative paths
REPO_ROOT = Path(__file__).resolve().parents[2]
ENVELOPES_DIR = REPO_ROOT / "memos" / "envelopes"
PM_REPORTS_DIR = REPO_ROOT / "memos" / "pm_reports"

# Cutover timestamp matching evaluator.md HG-3 Check 2 grandfather clause.
CUTOVER = "2026-05-24T00:00:00Z"

# Frameworks registry — frameworks_cited.<key>.output.* paths are ACCEPTed by
# HG-3 Check 2; any other field_path is REJECTed. Source of truth lives in
# .claude/references/canonical-frameworks.md (subset checked here).
MECHANICAL_FRAMEWORK_KEYS = frozenset({
    "mauboussin_reverse_dcf",
    "damodaran_narrative_dcf",
    "austere_dcf",
    "helmer_7_powers",
    "buffett_2007_inevitables",
    "piotroski_2000",
    "altman_1968",
    "sloan_1996",
    "beneish_1999_dsri",
    "mauboussin_moat_2024",
    "mauboussin_capital_allocation_2024",
    "mauboussin_base_rates_2016",
    "lovallo_kahneman_2003",
    "damodaran_implied_erp",
    "antonacci_dual_momentum_2014",
    "moskowitz_ooi_pedersen_tsmom_2012",
})

# Regex per /review-me v5-final Step 5: year-only analog cite, excluding ISO-date
# provenance refs of form MSFT 2026-05-15. MSFT removed from match list because
# it collides with too many BUILD_LOG provenance refs.
ANALOG_REGEX = re.compile(r"\b(CSCO|NOK|IBM)\s+\d{4}(?!-\d{2}-\d{2})")


def _load_envelope(run_id: str) -> dict:
    """Load pm-supervisor envelope for a run_id from canonical path."""
    p = ENVELOPES_DIR / f"pm-supervisor__{run_id}.json"
    if not p.exists():
        pytest.skip(f"envelope not found at {p} (skipping — provide fixture or run live)")
    return json.loads(p.read_text())


def _load_pm_report(ticker: str, date: str) -> str:
    """Load PM Report markdown for a ticker/date."""
    p = PM_REPORTS_DIR / f"{ticker.lower()}_pm_report_{date}.md"
    if not p.exists():
        pytest.skip(f"pm report not found at {p} (skipping — provide fixture or run live)")
    return p.read_text()


def _extract_section(markdown: str, header_pattern: str) -> str:
    """Extract a markdown section by H2/H3 header pattern up to next H2.

    Used to scope the regex assertion to TL;DR + §7.6 Strategic Scenarios body
    (not whole envelope) per Step 5 reviewer-tightened regex scope.
    """
    lines = markdown.splitlines()
    out, in_section = [], False
    for line in lines:
        if re.match(header_pattern, line):
            in_section = True
            continue
        if in_section and re.match(r"^##\s+\S", line):
            break  # next H2 ends the section
        if in_section:
            out.append(line)
    return "\n".join(out)


def _is_pre_cutover(envelope: dict) -> bool:
    """Grandfather check: envelopes with created_at < cutover are N/A for new
    HG-3 Check 2. Mirrors evaluator.md HG-3 grandfather clause.
    """
    created_at = envelope.get("created_at") or envelope.get("as_of")
    if not created_at:
        return True  # missing timestamp → conservative grandfather
    return created_at < CUTOVER


# ────────────────────────────────────────────────────────────────────────────
# Assertion A — kills_fired_evidence[].field_path mechanical-only
# ────────────────────────────────────────────────────────────────────────────


def _assert_field_path_mechanical(field_path: str) -> None:
    """Mirror HG-3 Check 2 field_path validation. Forbidden substrings + required
    framework-key prefix.
    """
    # REJECT patterns first (sharper failure messages)
    forbidden_substrings = ("analog", "drawdown_implied", "historical_analogs", "scenarios_strategic")
    for sub in forbidden_substrings:
        assert sub not in field_path, (
            f"field_path contains forbidden substring {sub!r}: {field_path!r} "
            f"— violates HG-3 Check 2 (analog-retirement enforcement)"
        )

    # ACCEPT pattern: frameworks_cited.<known_key>.output.<metric>
    m = re.match(r"^frameworks_cited\.(?P<key>[a-z0-9_]+)\.output\.[a-z0-9_]+$", field_path)
    assert m is not None, (
        f"field_path does not match mechanical pattern "
        f"`frameworks_cited.<key>.output.<metric>`: {field_path!r}"
    )
    key = m.group("key")
    assert key in MECHANICAL_FRAMEWORK_KEYS, (
        f"field_path references unknown framework_key {key!r}; canonical registry "
        f"in .claude/references/canonical-frameworks.md"
    )


def assert_kills_fired_evidence_mechanical(envelope: dict) -> None:
    """Assertion A — all kills_fired_evidence field_paths mechanical.

    Skipped (N/A-PRE-CUTOVER) for envelopes with created_at < CUTOVER per
    evaluator.md HG-3 grandfather clause.
    """
    if _is_pre_cutover(envelope):
        pytest.skip(
            f"envelope is pre-cutover (created_at < {CUTOVER}) — HG-3 Check 2 N/A "
            f"per grandfather clause; not a regression"
        )

    stress = envelope.get("adversarial_stress_test") or {}
    kills = stress.get("kills_fired_evidence") or []
    if not kills:
        # No kills fired = nothing to check; consistent with HG-3 Check 1's
        # conditional "REQUIRED when kills_fired >= 1" wording.
        return

    for i, kill in enumerate(kills):
        field_path = kill.get("field_path", "")
        assert field_path, f"kills_fired_evidence[{i}].field_path is empty"
        _assert_field_path_mechanical(field_path)


# ────────────────────────────────────────────────────────────────────────────
# Assertion B — no tl_dr.scenarios_strategic key (block deleted)
# ────────────────────────────────────────────────────────────────────────────


def assert_no_scenarios_strategic(envelope: dict) -> None:
    """Assertion B — envelope MUST NOT contain tl_dr.scenarios_strategic.

    Per Step 2 v5-final: block deleted entirely (9 sites in pm-supervisor.md).
    Grandfather does NOT apply here — the §10 check #3 was flipped from
    'Empty=hard-fail' to 'MUST be ABSENT' (guardrail against regression).
    """
    if _is_pre_cutover(envelope):
        pytest.skip(
            f"envelope is pre-cutover (created_at < {CUTOVER}) — scenarios_strategic "
            f"absence enforced post-cutover only"
        )

    tl_dr = envelope.get("tl_dr") or {}
    assert "scenarios_strategic" not in tl_dr, (
        "tl_dr.scenarios_strategic present in envelope — block was retired per "
        "/review-me v5-final 2026-05-24. Per §10 check #3 (pm-supervisor.md line "
        "~1248 post-edit), this is a guardrail against regression. Mechanical "
        "magnitude signal lives in mauboussin_reverse_dcf cohort multiple + "
        "cf-07 catastrophic-FAIL override; strategic narrative routes to "
        "report.structural_theory.detail + report.reasoning.detail."
    )


# ────────────────────────────────────────────────────────────────────────────
# Assertion C — TL;DR + §7.6 markdown body ZERO analog regex matches
# ────────────────────────────────────────────────────────────────────────────


def assert_pm_report_no_analog_in_tldr_or_section_7_6(pm_report_markdown: str) -> None:
    """Assertion C — TL;DR + §7.6 Strategic Scenarios body have zero analog refs.

    Regex pattern per v5-final reviewer-tightened scope:
      \\b(CSCO|NOK|IBM)\\s+\\d{4}(?!-\\d{2}-\\d{2})
    Year-only analog cites; ISO-date provenance refs (MSFT 2026-05-15) excluded
    by negative lookahead. MSFT removed from match list (collides with too many
    provenance refs).

    Scope is pinned to TL;DR + §7.6 Strategic Scenarios markdown body ONLY.
    report.structural_theory.detail and report.reasoning.detail are PERMITTED
    locations for multi-analog triangulation per Mauboussin (defensible
    illustrative narrative).
    """
    tldr_body = _extract_section(pm_report_markdown, r"^##\s+TL;DR\s*$")
    section_7_6_body = _extract_section(
        pm_report_markdown, r"^##\s+Decision Cell Matrix\s*$"
    )

    for label, body in [("TL;DR", tldr_body), ("§7.6 Decision Cell Matrix", section_7_6_body)]:
        matches = list(ANALOG_REGEX.finditer(body))
        assert not matches, (
            f"{label} section contains {len(matches)} analog regex match(es): "
            f"{[m.group(0) for m in matches]}. Per /review-me v5-final, analog "
            f"citations must be confined to report.structural_theory.detail or "
            f"report.reasoning.detail ONLY (Mauboussin multi-analog triangulation "
            f"defensible there). Magnitude-anchoring lives in mechanical signals."
        )


# ────────────────────────────────────────────────────────────────────────────
# Test entrypoints
# ────────────────────────────────────────────────────────────────────────────


def _live_run_id() -> str | None:
    """If RUN_LIVE_ANALOG_RETIREMENT=1, expect a freshly-dispatched run_id from
    /research-company AAPL. Otherwise tests run against the most-recent envelope
    found on disk (smoke-mode); or skip if none found.
    """
    return os.environ.get("ANALOG_RETIREMENT_TEST_RUN_ID")


def _latest_aapl_envelope_run_id() -> str | None:
    """Find the most-recent post-cutover AAPL pm-supervisor envelope on disk."""
    candidates = sorted(ENVELOPES_DIR.glob("pm-supervisor__*.json"))
    for p in reversed(candidates):
        try:
            env = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if env.get("ticker") != "AAPL":
            continue
        # Extract run_id from filename
        name = p.stem  # pm-supervisor__<run_id>
        run_id = name.split("__", 1)[1] if "__" in name else None
        if run_id:
            return run_id
    return None


@pytest.fixture(scope="module")
def aapl_envelope() -> dict:
    run_id = _live_run_id() or _latest_aapl_envelope_run_id()
    if run_id is None:
        pytest.skip(
            "No AAPL pm-supervisor envelope found. Set ANALOG_RETIREMENT_TEST_RUN_ID "
            "to a run_id, or place a fixture at memos/envelopes/pm-supervisor__<run_id>.json"
        )
    return _load_envelope(run_id)


@pytest.fixture(scope="module")
def aapl_pm_report_pair(aapl_envelope) -> tuple[str, dict]:
    """Return (pm_report_markdown, corresponding_envelope).

    The PM Report is co-grandfathered with its corresponding pm-supervisor envelope
    (same dispatch). Pairing inherits the envelope's pre/post-cutover status.
    """
    candidates = sorted(PM_REPORTS_DIR.glob("aapl_pm_report_*.md"))
    if not candidates:
        pytest.skip("No AAPL PM Report found.")
    return candidates[-1].read_text(), aapl_envelope


def test_assertion_a_kills_fired_evidence_mechanical(aapl_envelope):
    """Step 5 Assertion A — kills_fired_evidence field_paths must reference
    mechanical thresholds (frameworks_cited.*), NOT analog narrative.
    """
    assert_kills_fired_evidence_mechanical(aapl_envelope)


def test_assertion_b_no_scenarios_strategic_key(aapl_envelope):
    """Step 5 Assertion B — tl_dr.scenarios_strategic block must be absent
    (retired in /review-me v5-final 2026-05-24).
    """
    assert_no_scenarios_strategic(aapl_envelope)


def test_assertion_c_no_analog_in_tldr_or_decision_cell_matrix(aapl_pm_report_pair):
    """Step 5 Assertion C — TL;DR + §7.6 Decision Cell Matrix sections must have
    zero analog regex matches (CSCO|NOK|IBM + year-only, excluding ISO-date refs).

    Co-grandfathered with envelope: skips for pre-cutover reports.
    """
    pm_report, envelope = aapl_pm_report_pair
    if _is_pre_cutover(envelope):
        pytest.skip(
            f"PM Report co-grandfathered with pre-cutover envelope (created_at < {CUTOVER}). "
            f"The existing pre-retirement report is expected to contain analog refs in TL;DR. "
            f"This is not a regression."
        )
    assert_pm_report_no_analog_in_tldr_or_section_7_6(pm_report)


# ────────────────────────────────────────────────────────────────────────────
# Unit tests for the assertion helpers themselves (deterministic)
# ────────────────────────────────────────────────────────────────────────────


def test_field_path_helper_accepts_mechanical():
    _assert_field_path_mechanical("frameworks_cited.mauboussin_reverse_dcf.output.implied_growth")
    _assert_field_path_mechanical("frameworks_cited.helmer_7_powers.output.powers_held_count")


def test_field_path_helper_rejects_analog_narrative():
    with pytest.raises(AssertionError, match="forbidden substring"):
        _assert_field_path_mechanical("historical_analogs[0].drawdown_implied")
    with pytest.raises(AssertionError, match="forbidden substring"):
        _assert_field_path_mechanical("scenarios_strategic.bull.drawdown_implied")


def test_field_path_helper_rejects_unknown_framework_key():
    with pytest.raises(AssertionError, match="unknown framework_key"):
        _assert_field_path_mechanical("frameworks_cited.fictional_framework.output.something")


def test_regex_matches_year_only_analog():
    assert ANALOG_REGEX.search("the CSCO 1999 setup")
    assert ANALOG_REGEX.search("IBM 2011 buybacks-above-intrinsic")
    assert ANALOG_REGEX.search("NOK 2007 switching-cost collapse")


def test_regex_excludes_iso_date_provenance():
    # ISO-date provenance refs (MSFT 2026-05-15 BUILD_LOG) must NOT match
    assert not ANALOG_REGEX.search("MSFT 2026-05-15")
    assert not ANALOG_REGEX.search("CSCO 1999-04-22")


def test_regex_excludes_msft():
    # MSFT removed from match list per v5-final (collides with provenance refs)
    assert not ANALOG_REGEX.search("MSFT 2002")


def test_extract_section_handles_h2_boundaries():
    md = "## A\nfoo\n## B\nbar\n## C\nbaz"
    assert _extract_section(md, r"^##\s+B\s*$").strip() == "bar"


def test_pre_cutover_grandfather():
    assert _is_pre_cutover({"created_at": "2026-05-23T09:13:00Z"})
    assert not _is_pre_cutover({"created_at": "2026-05-24T01:00:00Z"})
    assert _is_pre_cutover({})  # missing timestamp = conservative grandfather
