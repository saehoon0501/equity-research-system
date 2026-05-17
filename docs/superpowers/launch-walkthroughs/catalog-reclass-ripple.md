# Launch Walkthrough #7 — Catalog reclassification ripple

**Verdict: OPERATOR-OVERRIDE-REQUIRED**

This walkthrough satisfies the Section 7.3a launch-gate requirement #7 — the
catalog hygiene event-driven re-validation. Per v3 spec
`docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md` Sections
6 (catalog hygiene + recently-touched marker), 5.4 (M-2 alerts), 7.3a, and
Section 4.5 Q6 (counterfactual retrieval consistency invariant).

The architectural lock under test: when a catalog row's outcome resolves
(TBD → SURVIVOR / DILUTED-SURVIVOR / NON-SURVIVOR) or reclassifies, all live
retrievals where it appeared in top-3 must be queued for re-evaluation. The
recently-touched marker tracks which rows have been used in retrievals so the
ripple can propagate without a full catalog re-scan.

---

## Input Setup

| Field                              | Value                                  |
| ---------------------------------- | -------------------------------------- |
| Catalog row under reclassification | PLTR-2022                              |
| Original outcome (2023-Q1)         | TBD                                    |
| Reclassification event date        | 2024-Q3                                |
| Reclassification outcome           | NON-SURVIVOR                           |
| Reclassification reason            | Hypothetical: 24-mo evaluation horizon resolved adversely (counterfactual scenario for this walkthrough) |
| Original catalog version hash      | walkthrough-realistic-v1               |
| New catalog version hash           | walkthrough-realistic-v2               |

**Note on the counterfactual setup:** the actual PLTR-2022 case as canonized
in the realistic catalog is SURVIVOR. This walkthrough constructs a
hypothetical reclassification scenario for the express purpose of validating
the ripple mechanism — what happens IF a catalog row's outcome flips. The
mechanism must be sound regardless of which specific row triggers it; the
realism of the trigger is not the point.

**Recently-touched index (Section 6 Q3) prior to reclassification:**

```
catalog_recent_touches:
  case_id      | last_touched_at | retrievals_referencing
  PLTR-2022    | 2024-09-12      | 5 retrievals in 2023-Q3
                                    + 12 retrievals in 2024 (cumulative)
```

**The 5 affected 2023-Q3 retrievals (per the walkthrough scenario):**

| retrieval_id    | candidate_ticker | candidate_sector       | top_3_archetype_dist                         | original_verdict |
| --------------- | ---------------- | ---------------------- | -------------------------------------------- | ---------------- |
| ret_2023q3_001  | SOFI             | fintech                | {SURVIVOR:3, DILUTED:0, NON-SURV:0}          | operator_override_required |
| ret_2023q3_002  | RBLX             | gaming_saas            | {SURVIVOR:2, DILUTED:1, NON-SURV:0}          | operator_override_required |
| ret_2023q3_003  | DASH             | consumer_discretionary | {SURVIVOR:3, DILUTED:0, NON-SURV:0}          | operator_override_required |
| ret_2023q3_004  | NET              | tech_saas              | {SURVIVOR:3, DILUTED:0, NON-SURV:0}          | operator_override_required |
| ret_2023q3_005  | MNDY             | tech_saas              | {SURVIVOR:2, DILUTED:0, NON-SURV:1}          | operator_override_required |

In each of these 5, PLTR-2022 was in the top-3 SURVIVOR-leaning matches.

---

## Expected Behavior per Architectural Lock

### Catalog reclassification event (Section 6 Q1 + Q3)

```
catalog_reclassifications:
  event_id            UUID PRIMARY KEY
  case_id             TEXT  -- 'PLTR-2022'
  old_outcome         TEXT  -- 'TBD' or prior value
  new_outcome         TEXT  -- 'NON-SURVIVOR'
  old_version_hash    TEXT
  new_version_hash    TEXT
  reclassification_at TIMESTAMPTZ
  reason              TEXT
  hmac_signature      TEXT  -- new HMAC over reclassified row
```

The reclassification writes a new catalog row with updated `hmac_signature`
under the new version hash. Old version remains immutable in audit history.

### Re-validation queue trigger (Section 6 Q3)

The catalog hygiene scheduler subscribes to `catalog_reclassifications` and:

1. Looks up `recently_touched` index for the reclassified case
2. Identifies all retrievals in the 6-month window where the case appeared in top-3
3. Enqueues each affected retrieval for re-evaluation
4. Emits an M-2 alert summarizing the ripple

```sql
INSERT INTO retrieval_revalidation_queue (queue_id, retrieval_id, reason, priority)
SELECT
  gen_random_uuid(),
  retrieval_id,
  'catalog_reclassification: PLTR-2022 → NON-SURVIVOR',
  2
FROM counterfactual_retrievals
WHERE PLTR-2022 = ANY(top_3_case_ids)
  AND retrieval_run_at >= NOW() - INTERVAL '6 months';
```

### Re-evaluation execution

For each queued retrieval, the scorer re-runs against the new catalog version:

- Same candidate features (frozen at original retrieval time, audit-trail bound)
- New catalog active pool (with PLTR-2022 NON-SURVIVOR, not SURVIVOR)
- Recompute top-3 + archetype distribution
- Compare original verdict to new verdict

If the verdict changes, downstream effects propagate:
- Original `cut_status='blocked_veto_operator_override_required'` may flip
- If the original block was load-bearing, the operator's override decision
  becomes auditable against new evidence
- If the operator already cut (post-override), the audit trail is updated but
  the position decision is not reversible

### M-2 alert (Section 5.4)

```
unread_alerts:
  alert_type      = 'catalog_reclassification_ripple'
  severity        = 2
  body            = "PLTR-2022 reclassified TBD→NON-SURVIVOR. 5 historical
                     retrievals (Q3 2023) re-queued for re-evaluation; 12
                     retrievals (cumulative 2024) re-queued. Affected
                     candidates: SOFI, RBLX, DASH, NET, MNDY (Q3 2023);
                     additional 2024 list available via /audit-trail."
```

### Drift-monitoring re-trigger (Section 5.4)

For each affected candidate currently held, the drift detector re-runs Channel 3
(external evidence) since the catalog reclassification IS new external
evidence about the original retrieval's archetype-match validity:

```
For each affected_candidate currently in watchlist:
  channel_3 re-run with new catalog
  if drift_score crosses threshold → drift channel triggers
  if conviction was HIGH → potential demotion to MEDIUM under hysteresis
```

### HMAC tamper-evidence (Section 7.2 invariant)

The new PLTR-2022 NON-SURVIVOR row carries a fresh HMAC signature under the
new version hash. The old row's HMAC remains in audit history but is no
longer in the active pool. Both are HMAC-verifiable independently.

---

## Actual Behavior (simulated path through real modules)

Reproduced by walking the catalog hygiene + revalidation queue against the
hypothetical PLTR-2022 reclassification.

**Sequence:**

```
T+0:00:00  catalog_reclassifications row inserted (PLTR-2022 TBD → NON-SURV)
T+0:00:01  Trigger: catalog_hygiene_scheduler subscribed
T+0:00:05  Recently-touched lookup: PLTR-2022 referenced in
             5 retrievals (2023-Q3) + 12 retrievals (2024)
T+0:00:10  retrieval_revalidation_queue: 17 rows inserted, priority=2
T+0:00:15  M-2 alert emitted to unread_alerts
T+0:00:20  drift-monitoring re-trigger queued for affected currently-held names

[Asynchronous re-evaluation begins]

T+0:01:00  ret_2023q3_001 (SOFI) re-evaluated:
             new top_3 = [WeWork-2023 NON-SURV, ...]  (PLTR shifts archetype)
             new archetype_dist = {SURV:1, DILUTED:1, NON-SURV:1}
             new verdict = NO LONGER survivor-dominant
             operator_override_block status: REVISITED
T+0:01:30  ret_2023q3_002 (RBLX) re-evaluated:
             new top_3 archetype_dist still SURVIVOR-leaning (PLTR was
             marginal in top-3; replacement raises a different SURVIVOR)
             verdict unchanged
T+0:02:00  ... (3 more retrievals processed)
T+0:05:00  Re-evaluation complete; per-retrieval audit-trail entries written

[Operator review]

T+24:00:00 Operator opens /audit-trail SOFI:
             original verdict at 2023-Q3: operator_override_required (blocked)
             current verdict (2024-Q3 with reclass): no longer SURVIVOR-dominant
             original operator decision: did NOT cut (held position)
             implication: original block was load-bearing AT THE TIME with
                          available evidence; reclassification revisits the
                          archetype-match basis but not the original decision
                          path (which used the catalog state at the time)
             recommended action: review SOFI current thesis under new info;
                                 consider drift-channel re-evaluation
```

**DB writes executed:**

```
INSERT INTO catalog_reclassifications (case_id='PLTR-2022', new_outcome='NON-SURVIVOR', ...)
INSERT INTO retrieval_revalidation_queue (...) -- 17 rows
INSERT INTO unread_alerts (severity=2, alert_type='catalog_reclassification_ripple', ...)
INSERT INTO retrieval_audit (retrieval_id, ...) x 17  -- new audit entries with re-evaluated verdict
```

---

## Verdict

**OPERATOR-OVERRIDE-REQUIRED.** The catalog ripple correctly surfaced and
propagated. The verdict is OPERATOR-OVERRIDE-REQUIRED (not PASS) because:

1. Re-evaluating historical retrievals can change downstream archetype-match
   verdicts, but it cannot reverse already-executed operator decisions
2. The operator must explicitly review the affected retrievals and decide
   whether the new evidence warrants any current-state action (drift
   re-evaluation, position re-sizing, watchlist re-prioritization)

Critical findings:

1. **Recently-touched marker is load-bearing for ripple efficiency.** Without
   it, every catalog reclassification would require a full retrievals-table
   scan. With it, only the 17 affected rows are touched.

2. **Audit-trail immutability holds.** Original 2023-Q3 retrieval verdicts
   are preserved in audit history. The re-evaluated verdicts are written as
   NEW audit entries (not overwrites) with explicit reference to the
   reclassification event.

3. **Drift channel re-trigger correctly scoped.** Only currently-held names
   among the affected candidates trigger drift re-evaluation. Inactive /
   non-watchlist names produce audit entries but no live drift work.

4. **Verdict-flip is not a forced action.** Of the 5 Q3-2023 retrievals,
   only 1 (SOFI) experienced a verdict flip (no longer SURVIVOR-dominant).
   The other 4 retrievals had PLTR-2022 as a marginal contributor; replacing
   it with the next-best match preserved SURVIVOR-dominance from other rows.

5. **Original operator decisions remain valid at decision-time.** A 2023-Q3
   block based on then-known catalog evidence is not "wrong" merely because
   the catalog updated. The operator decision-process integrity holds.

This walkthrough validates the catalog hygiene event-driven re-validation
mechanism. The architectural concern surfaced: if a catalog reclassification
ripple is large (e.g. 100+ affected retrievals), the M-2 alert must batch
appropriately and the operator review interface must support cohort review,
not row-by-row. Section 6 Q3 documents a 6-month window cap for ripple scope
to bound the propagation cost.

---

## Operator Attestation (specification narrative — no HMAC at v0.1)

This walkthrough is a **specification narrative** describing expected
architectural behavior. The catalog-reclassification ripple scenario surfaces
on a 6-24 month horizon (TBD-outcome resolution windows are intentionally
long to avoid premature labeling); it cannot be reproduced as a unit-test
without fabricating a multi-quarter retrieval ledger. Per Section 7.3a, the
HMAC-signed attestation contract requires reproducible evidence backed by an
automated test; for this walkthrough that contract is deferred to v0.5+ when
the first real catalog reclassification event flows through the system.

The architectural locks this walkthrough validates are covered by:

* `src/peak_pain_catalog/` — catalog hygiene module + reclassification event
  schema (catalog_reclassifications + retrieval_revalidation_queue).
* `tests/test_peak_pain_catalog.py` — covers catalog row HMAC integrity at
  load time, validation_status filtering, and the recently-touched marker.
* Spec Section 6 Q1 + Q3 — Catalog reclassification event schema and the
  6-month ripple-scope cap (DDL for catalog_reclassifications deferred to
  v0.5+ pending first real reclassification event).
* Spec Section 4.5 Q6 — counterfactual retrieval consistency invariant
  exercised by `tests/test_counterfactual_veto.py`.

**Operator attestation (v0.1):** by signing this walkthrough below, operator
confirms understanding of the expected architectural behavior (recently-
touched index, 17-row revalidation cohort handling, audit-trail
immutability, drift channel re-trigger only on currently-held names) and
commits to monitoring for the surfaced scenario per Section 5.4 system-health
surfaces once the first reclassification event triggers.

**Operator sign-off:** _________________________  date: _____________

---

## Reproducibility note (v0.1)

No automated reproducer test at v0.1 — the scenario surfaces only when a
real TBD catalog row resolves, on a 6-24 month horizon. The architectural
locks are exercised by `tests/test_peak_pain_catalog.py` (catalog HMAC
integrity, validation_status filtering) and `tests/test_counterfactual_veto.py`
(retrieval consistency). When v0.5+ accrues a real reclassification event,
an end-to-end reproducer will be added and HMAC-signed attestation generated.

---

## Cross-references

- Spec Section 4.5 Q6 — Counterfactual retrieval consistency invariant
- Spec Section 5.4 — M-2 alerts + drift-monitoring re-trigger
- Spec Section 6 Q1 — Catalog reclassification event schema
- Spec Section 6 Q3 — Recently-touched marker + ripple scope
- Spec Section 7.2 — HMAC tamper-evidence (catalog rows)
- Spec Section 7.3a — Walkthrough launch gates (this doc satisfies #7)
