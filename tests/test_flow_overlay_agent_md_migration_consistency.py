"""Cross-validates that the PARAMETERS_USED list in .claude/agents/flow-overlay.md
matches the rows inserted by db/migrations/039_flow_overlay_parameters.sql.

Per /review-me iteration 1 finding #5: agent .md and migration are independent
artifacts; without a consistency test, a future operator can add a row to
the migration but forget the agent definition (or vice versa), and no
existing HG catches the drift.

This test parses BOTH files and asserts that the set of flow.*, flow_disposition.*,
and flow_cell.* namespaces enumerated under "## PARAMETERS_USED block is ground
truth" in the agent .md matches the rows inserted by migration 039.

The cross-cutting sizing.* additions in migration 039 (catalyst_modifier_magnitude_scaler
+ flow_modifier_pp_per_unit) are NOT enumerated in flow-overlay.md (they are
consumed by pm-supervisor, not flow-overlay) — so they are explicitly excluded
from the comparison.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

AGENT_MD = REPO_ROOT / ".claude" / "agents" / "flow-overlay.md"
MIGRATION_SQL = REPO_ROOT / "db" / "migrations" / "039_flow_overlay_parameters.sql"

# Migration 039 also seeds sizing.* rows consumed by pm-supervisor (not flow-overlay).
# These are explicitly NOT expected to appear in flow-overlay.md's PARAMETERS_USED.
SIZING_CROSS_CUTTING_KEYS = {
    "sizing.catalyst_modifier_magnitude_scaler.low",
    "sizing.catalyst_modifier_magnitude_scaler.medium",
    "sizing.catalyst_modifier_magnitude_scaler.high",
    "sizing.flow_modifier_pp_per_unit",
}

# Sizing keys flow-overlay consumes (band lookup for cell-size selector) ARE
# enumerated in its agent .md but live in legacy migrations (033). They are
# not flow.*/flow_disposition.*/flow_cell.* but DO appear in the agent .md.
# We exclude them from the comparison because they pre-exist this migration.
FLOW_OVERLAY_LEGACY_SIZING_KEYS = {
    "sizing.conviction_band.HIGH.min_pct",
    "sizing.conviction_band.HIGH.max_pct",
    "sizing.conviction_band.MEDIUM.min_pct",
    "sizing.conviction_band.MEDIUM.max_pct",
}


def _parse_agent_md_parameter_keys() -> set[str]:
    """Extract flow.*, flow_disposition.*, flow_cell.* keys from the
    PARAMETERS_USED block section of flow-overlay.md.

    The section is delimited by '## PARAMETERS_USED block is ground truth'
    on the open and '## Tools' on the close (per the agent .md structure).
    Bullet items take the form '- `<key>` ...' with the key in backticks.
    """
    text = AGENT_MD.read_text(encoding="utf-8")
    match = re.search(
        r"## PARAMETERS_USED block is ground truth(.+?)## Tools",
        text,
        re.DOTALL,
    )
    assert match is not None, "PARAMETERS_USED section not found in agent .md"
    section = match.group(1)

    # Pull every `key.path` instance from backtick-quoted strings in the section.
    # We accept both bare keys and dotted globs like `flow_disposition.mapping.<conviction>_<flow_bin>`.
    raw_keys = re.findall(r"`([a-z_]+(?:\.[a-zA-Z_<>{},.]+)+)`", section)

    # Normalize the disposition mapping glob (`flow_disposition.mapping.<conviction>_<flow_bin>`)
    # to the 12 concrete rows the migration emits.
    expanded: set[str] = set()
    for key in raw_keys:
        if "<conviction>" in key and "<flow_bin>" in key:
            for conv in ("HIGH", "MEDIUM", "LOW"):
                for fb in ("positive", "neutral", "negative", "unavailable"):
                    expanded.add(
                        key.replace("<conviction>", conv).replace("<flow_bin>", fb)
                    )
        elif "{min,max}" in key:
            for side in ("min", "max"):
                expanded.add(key.replace("{min,max}", side))
        else:
            expanded.add(key)

    return {k for k in expanded if k.startswith(("flow.", "flow_disposition.", "flow_cell."))}


def _parse_migration_parameter_keys() -> set[str]:
    """Extract every parameter_key inserted by migration 039 that begins with
    one of the flow-overlay namespaces.
    """
    text = MIGRATION_SQL.read_text(encoding="utf-8")
    raw_keys = re.findall(r"SELECT '([a-zA-Z_][\w.]*)',", text)
    return {
        k for k in raw_keys
        if k.startswith(("flow.", "flow_disposition.", "flow_cell."))
    }


def test_agent_md_section_exists():
    """Sanity: the PARAMETERS_USED section is locatable in the agent .md."""
    text = AGENT_MD.read_text(encoding="utf-8")
    assert "## PARAMETERS_USED block is ground truth" in text


def test_migration_file_exists():
    assert MIGRATION_SQL.is_file()


def test_flow_overlay_keys_match_between_agent_md_and_migration():
    """Every flow.*/flow_disposition.*/flow_cell.* key in migration 039 must
    appear in the flow-overlay.md PARAMETERS_USED block (and vice versa).

    If this test fails:
    - In migration but not agent .md → operator forgot to update agent definition
      after adding a row to the migration.
    - In agent .md but not migration → operator removed a migration row without
      updating the agent definition (or the agent .md is hallucinating a key).
    """
    agent_keys = _parse_agent_md_parameter_keys()
    migration_keys = _parse_migration_parameter_keys()

    only_in_agent = agent_keys - migration_keys
    only_in_migration = migration_keys - agent_keys

    assert not only_in_agent, (
        f"keys in agent .md but missing from migration 039: {sorted(only_in_agent)}"
    )
    assert not only_in_migration, (
        f"keys in migration 039 but missing from agent .md PARAMETERS_USED: "
        f"{sorted(only_in_migration)}"
    )


def test_sizing_cross_cutting_keys_in_migration_only():
    """The 4 cross-cutting sizing.* rows added by 039 are consumed by
    pm-supervisor, not flow-overlay. They MUST be in the migration but MUST
    NOT appear in flow-overlay.md (separation of consumption-namespace concerns).
    """
    migration_text = MIGRATION_SQL.read_text(encoding="utf-8")
    for key in SIZING_CROSS_CUTTING_KEYS:
        assert key in migration_text, (
            f"expected cross-cutting sizing key {key} in migration 039"
        )
    agent_text = AGENT_MD.read_text(encoding="utf-8")
    for key in SIZING_CROSS_CUTTING_KEYS:
        assert key not in agent_text, (
            f"cross-cutting sizing key {key} should NOT appear in flow-overlay.md "
            f"(consumed by pm-supervisor, not flow-overlay)"
        )
