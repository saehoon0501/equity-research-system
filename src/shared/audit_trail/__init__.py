"""audit_trail — terminal-rendered layered drill-down for execution recommendations.

Per v3 spec Section 5.2 (Audit-mode UX) and Section 7 Q4 (layered drill-down lock):
  - Top-level audit summary surfaces decision_path with drill_link per stage.
  - Each drill is fetched on-demand via `/audit-trail <rec_id> --stage <stage>`.
  - HMAC-signed audit chain (parent_audit_id) provides tamper-evidence.

This package is the RENDERER + LOADER + VERIFIER. It does NOT write
audit_provenance rows (that is the recommendation emitter's job — see v3 spec
Section 4.6).

Reference:
  docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
    Section 5.2 (Audit-mode UX — layered drill-down)
    Section 5.4 (Slash commands — `/audit-trail`)
    Section 7 Q4 (layered drill-down lock)
    Section 5 Q1 (audit-trail HMAC chain)
  db/migrations/008_v3_recommendations.sql
    audit_provenance + execution_recommendations schemas

Public surface:
  - render_audit_summary(summary)   → markdown for top-level decision_path
  - render_stage_drill(stage, row)  → markdown for one stage's full payload
  - get_audit_summary(rec_id)       → Postgres loader (top-level)
  - get_stage_drill(rec_id, stage)  → Postgres loader (per-stage payload)
  - get_latest_for_ticker(ticker)   → resolves a ticker to its latest rec_id
  - verify_chain(rows, hmac_key)    → HMAC-chain verification result
"""

from __future__ import annotations

from src.shared.audit_trail.hmac_verify import (
    ChainVerificationResult,
    RowVerification,
    canonical_payload,
    canonical_payload_dict,
    compute_signature,
    compute_signature_dict,
    verify_chain,
    verify_row,
)
from src.shared.audit_trail.loader import (
    AuditSummary,
    StageRow,
    get_audit_summary,
    get_chain_for_recommendation,
    get_latest_for_ticker,
    get_stage_drill,
)
from src.shared.audit_trail.renderer import (
    STAGES,
    render_audit_summary,
    render_chain_verification,
    render_stage_drill,
)

__all__ = [
    "AuditSummary",
    "ChainVerificationResult",
    "RowVerification",
    "STAGES",
    "StageRow",
    "canonical_payload",
    "canonical_payload_dict",
    "compute_signature",
    "compute_signature_dict",
    "get_audit_summary",
    "get_chain_for_recommendation",
    "get_latest_for_ticker",
    "get_stage_drill",
    "render_audit_summary",
    "render_chain_verification",
    "render_stage_drill",
    "verify_chain",
    "verify_row",
]
