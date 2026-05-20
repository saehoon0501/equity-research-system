"""Dual-read shim for the `frameworks_cited` field schema migration.

Per Bug 3 Phase B continuation (consensus doc CAF-2, Phase 0 enum v3.1):
the `frameworks_cited` field schema is migrating from a list-of-entries
form to a keyed-object form so that HG-29 Check 4d's restricted path
grammar can use named-key syntax (e.g.
`frameworks_cited.mauboussin_reverse_dcf.output.implied_growth_pct`)
instead of brittle integer indices (`frameworks_cited.0.output.x`).

Legacy form (pre-v3.1):
    frameworks_cited: [
        {framework_key: "damodaran_narrative_dcf", output: {...}},
        {framework_key: "buffett_2007_inevitables", output: {...}},
        ...
    ]

New form (v3.1+):
    frameworks_cited: {
        "damodaran_narrative_dcf": {framework_key: "damodaran_narrative_dcf", output: {...}},
        "buffett_2007_inevitables": {framework_key: "buffett_2007_inevitables", output: {...}},
        ...
    }

Dual-read: both forms are accepted indefinitely. Historical analyst_briefs
rows continue to work; new envelopes emit keyed-object form. Cutover
to keyed-object-only is a separate dated commit after the 2-week
transition window per consensus.
"""

from __future__ import annotations

from collections.abc import Iterator


def find_framework(memo: dict, framework_key: str) -> dict | None:
    """Resolve a framework entry by its short-key, accepting both schemas.

    Returns the entry dict (with output/framework_key/etc.) or None when
    the framework_key is not present or the field is missing/malformed.
    """
    fc = memo.get("frameworks_cited")
    if fc is None:
        return None
    if isinstance(fc, dict):
        entry = fc.get(framework_key)
        return entry if isinstance(entry, dict) else None
    if isinstance(fc, list):
        for entry in fc:
            if isinstance(entry, dict) and entry.get("framework_key") == framework_key:
                return entry
    return None


def iter_frameworks(memo: dict) -> Iterator[dict]:
    """Iterate over all framework entries regardless of underlying schema.

    Yields entry dicts in insertion order (list) or dict-iteration order
    (Python 3.7+ preserves insertion order on dicts).
    """
    fc = memo.get("frameworks_cited")
    if fc is None:
        return
    if isinstance(fc, dict):
        for entry in fc.values():
            if isinstance(entry, dict):
                yield entry
        return
    if isinstance(fc, list):
        for entry in fc:
            if isinstance(entry, dict):
                yield entry


def get_framework_keys(memo: dict) -> set[str]:
    """Return the set of framework_keys present in frameworks_cited."""
    fc = memo.get("frameworks_cited")
    if fc is None:
        return set()
    if isinstance(fc, dict):
        return {k for k in fc.keys() if isinstance(k, str)}
    if isinstance(fc, list):
        return {
            entry["framework_key"]
            for entry in fc
            if isinstance(entry, dict) and isinstance(entry.get("framework_key"), str)
        }
    return set()


def is_keyed_object_form(memo: dict) -> bool:
    """True iff frameworks_cited is in the v3.1+ keyed-object form.

    Useful for migration telemetry: count what fraction of envelopes
    have migrated to the new form so the cutover deadline can be set.
    """
    return isinstance(memo.get("frameworks_cited"), dict)
