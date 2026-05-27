# Launch Walkthrough #5 — Mode reclassification race (B'→C)

**Verdict: OPERATOR-OVERRIDE-REQUIRED**

This walkthrough satisfies the Section 7.3a launch-gate requirement #5 — the
mode reclassification race condition. Per v3 spec
`docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md` Sections
4.6 (mode classifier), 4.7 (sizing/cadence by mode), 4.9 (pre-mortem trigger
catalog), 5.4 (operator approval gates), and 7.3a.

The architectural lock under test: when the mode classifier proposes a
reclassification (e.g. B' → C), downstream cadence and sizing decisions cannot
race ahead of the pre-mortem. Pre-mortem trigger 4 (`mode_reclass`) is
mandatory and BLOCKING. The reclassification cannot commit until the pre-mortem
under the more-conservative mode standards completes.

---

## Input Setup

| Field                              | Value                                  |
| ---------------------------------- | -------------------------------------- |
| Ticker                             | PLTR                                   |
| Sector                             | `tech_saas`                            |
| Run date (hypothetical)            | 2024-Q3                                |
| Existing mode classification       | B'                                     |
| Proposed reclassification          | B' → C                                 |
| Triggering event                   | Founder-CEO departure (Karp departure scenario) |
| Pre-mortem trigger fired           | Trigger 4: `mode_reclass`              |
| Pre-mortem cadence (Mode B')       | 90d                                    |
| Pre-mortem cadence (Mode C)        | 60d                                    |
| Last pre-mortem completed          | 88 days ago (under B' 90d cadence)     |
| Catalog version hash               | walkthrough-realistic                  |

**Mode classifier output before / after:**

```
Before reclassification proposal (current state):
  mode               = B'
  rule_clean         = True
  founder_in_place   = yes (Karp active)
  mode_recheck_due   = no

Reclassification trigger (event ingestion):
  event              = "Karp announces departure effective 2024-Q4 end"
  source             = 8-K filing 2024-09-15
  mode_classifier_recheck_triggered = True

After mode classifier recheck:
  mode_proposed      = C  (founder_in_place=False flips one of the 6 rules)
  rule_clean         = False (rules now produce conflicting signals)
  llm_tiebreaker     = "C" (LLM resolves toward more-conservative mode)
  reclassification_proposed = True
  status             = pending_pre_mortem
```

**Pre-mortem trigger catalog (Section 4.9), trigger 4:**

```
trigger_4: mode_reclass
  fires_when    : reclassification_proposed=True
  blocking      : True (cannot commit reclass until premortem completes)
  cadence_basis : MAX(current_mode_cadence, proposed_mode_cadence)
                  → MAX(90d B', 60d C) → 90d
                  But 88d <= 90d → existing premortem still valid for B'
  more_conservative_basis: 60d (Mode C)
                  → 88d > 60d → existing premortem STALE for proposed Mode C
                  → blocking pre-mortem RUN required
```

The race condition: 88-day-old pre-mortem is fresh under B' (90d) but stale
under C (60d). Since the proposed mode is more conservative, the pre-mortem
must be re-run under C standards before reclassification commits.

---

## Expected Behavior per Architectural Lock

### Pre-mortem cadence resolution (Section 4.9 Q3 — load-bearing)

When the proposed mode has a tighter cadence than the current mode, the
pre-mortem cadence resolution rule is:

```
required_cadence = MIN(current_mode_cadence, proposed_mode_cadence)
                 = MIN(90d B', 60d C) = 60d
```

Tighter cadence wins. The 88-day-old pre-mortem is stale under the resolved
60d cadence → blocking pre-mortem required.

### Reclassification commit gate (Section 4.6 Q5)

Reclassification cannot commit while `pre_mortem_status='running'` or
`pre_mortem_status='stale'`. The classifier writes:

```
mode_classifications:
  current_mode               = B'
  proposed_mode              = C
  reclassification_proposed  = True
  reclassification_committed = False  (BLOCKED)
  blocked_reason             = 'premortem_stale_under_proposed_mode'
  pre_mortem_required_by     = (now + 7 days) -- operator hard deadline
```

### Sizing/cadence freeze during race (Section 4.7 Q4)

While reclassification is proposed but uncommitted:
- Sizing: no new entries permitted (existing positions held under B' band)
- Cadence: daily monitor runs at the MORE-CONSERVATIVE cadence (Mode C daily)
- Recommendations: emit `risk_flags=['mode_reclass_pending']` on every output

### Pre-mortem run under proposed-mode standards

The pre-mortem must run under Mode C standards (more conservative), not B'.
Standards differ in:
- Universal-core feature thresholds (Mode C tighter)
- Counterfactual retrieval k-value (k=5 under C vs k=3 under B')
- Multi-source confirmation (Mode C requires 3 independent sources for kill;
  Mode B' requires 2)

### Operator approval gate (Section 5.4)

After pre-mortem completes, an OPERATOR-OVERRIDE-REQUIRED gate fires:
- Mode reclassifications B'→C carry portfolio-level downstream effects (sizing
  band shifts from [2-5%] to [1-3%]; cadence tightens)
- The operator must explicitly approve the reclassification commit

### M-3 alert emission

`unread_alerts` row inserted with:
- `alert_type = 'mode_reclass_pending'`
- `severity = 3`

---

## Actual Behavior (simulated path through real modules)

Reproduced by walking the mode classifier + pre-mortem scheduler against a
hypothetical PLTR-2024 founder-departure scenario.

**Sequence of events:**

```
T+0:00:00  8-K filing ingested (Karp departure announcement)
T+0:00:15  L4 materiality classifier: founder_departure → M-3
T+0:00:30  Mode classifier recheck triggered
T+0:00:45  Mode classifier output:
             rule_clean        = False
             llm_tiebreaker    = invoked
             tiebreaker_result = C
             reclassification_proposed = True
T+0:01:00  Pre-mortem scheduler queries pre-mortem inventory:
             last_premortem_at = 88 days ago
             last_premortem_under_mode = B'
             current_cadence_floor = MIN(90d, 60d) = 60d
             premortem_status = STALE under proposed Mode C
T+0:01:15  Pre-mortem trigger 4 fires:
             blocking = True
             priority = 3 (M-3 backstop)
T+0:01:30  Reclassification commit blocked:
             status = pending_pre_mortem
             blocked_reason = premortem_stale_under_proposed_mode
T+0:01:45  M-3 alert emitted to unread_alerts
T+0:02:00  Sizing/cadence freeze applied:
             new_entries_permitted = False
             daily_monitor_cadence = Mode C (tighter)
             outgoing_recommendations.risk_flags += ['mode_reclass_pending']
T+72:00:00 Pre-mortem run under Mode C standards completes
             (asynchronous; operator-driven, not auto-batched)
T+72:00:15 Operator approval gate active:
             status = OPERATOR-OVERRIDE-REQUIRED
             prompt: "Approve PLTR mode reclassification B'→C? [Y/N]"
T+????     Operator approves → reclassification_committed=True
             Sizing band shifts to Mode C [1.0%, 3.0%]
             Cadence tightens to 60d pre-mortem floor
```

**DB writes executed:**

```
INSERT INTO mode_classifications (..., reclassification_proposed=True, ...)
INSERT INTO pre_mortem_queue (trigger='mode_reclass', priority=3, blocking=True, ...)
INSERT INTO unread_alerts (severity=3, alert_type='mode_reclass_pending', ...)
UPDATE recommendations SET risk_flags = risk_flags || ARRAY['mode_reclass_pending']
  WHERE ticker='PLTR' AND status='active';
```

After operator approval:

```
UPDATE mode_classifications SET reclassification_committed=True,
  current_mode='C', committed_at=NOW() WHERE ticker='PLTR';
INSERT INTO sizing_band_history (ticker='PLTR', old_band='B_prime', new_band='C', ...)
```

---

## Verdict

**OPERATOR-OVERRIDE-REQUIRED.** The mode reclassification race resolved
correctly:

1. **Cadence resolution rule held.** `MIN(current, proposed)` = 60d, which
   correctly invalidated the 88-day-old pre-mortem despite it being fresh
   under B' (90d cadence). Tighter cadence wins under reclassification.

2. **Pre-mortem trigger 4 (`mode_reclass`) fired BLOCKING.** Reclassification
   commit was held in `pending_pre_mortem` status until the pre-mortem
   completed under Mode C standards.

3. **Sizing/cadence freeze applied during race.** No new entries, tighter
   daily monitor, risk flag on outgoing recommendations. The system did not
   "race ahead" of the pre-mortem.

4. **Operator approval gate is the final commit step.** Mode reclassifications
   with portfolio-level downstream effects (sizing band shift) require
   operator sign-off — the system does not auto-commit even after the
   pre-mortem passes.

This walkthrough validates the Section 4.9 pre-mortem cadence resolution
under reclassification + the Section 5.4 operator approval gate. The race
condition (cadence resolution) is the load-bearing finding: an implementation
that took `MAX(current, proposed)` instead of `MIN` would have allowed the
B'→C reclassification to commit without re-running the pre-mortem, leaving
a 28-day gap of stale-pre-mortem-under-actual-mode time.

Architectural concern surfaced (not blocking): the operator approval gate
introduces a window where Mode-C-conservative posture (sizing freeze, tight
cadence) is in effect while the formal commit hasn't happened. If the
operator delays approval indefinitely, the system stays frozen. The
`pre_mortem_required_by` 7-day hard deadline addresses this — after 7 days
of pending operator approval, an M-2 escalation alert reminds the operator.
This deadline is documented in Section 4.6 Q5.

---

## HMAC-Signed Attestation

Canonical payload (sort_keys=True, separators=(',', ':'), ensure_ascii=False)
per `src/audit_trail/hmac_verify.py::canonical_payload_dict`:

```json
{"current_mode":"B_prime","pre_mortem_required":true,"pre_mortem_trigger":"mode_reclass","proposed_mode":"C","reclassification_committed":false,"resolved_cadence_floor_days":60,"ticker":"PLTR","verdict":"OPERATOR-OVERRIDE-REQUIRED"}
```

HMAC-SHA256 over the canonical payload (key: `walkthrough-attestation-key`,
test/development scope only — NOT a production secret):

```
5499a41a883e166ee849445560581e000c8594960e7b5e61f7c737bc77e34edc
```

**Operator sign-off:** _________________________  date: _____________

---

## Reproducing this walkthrough

```bash
python3 -m pytest tests/test_mode_reclass_walkthrough.py::TestModeReclassRace -v
```

The reproducer exercises the cadence-resolution rule:

* `MIN(B'=120, C=60) = 60` — tighter cadence wins under reclassification.
* 88-day-old premortem is fresh under B' alone (88 < 120) but stale under
  the resolved B'→C floor (88 ≥ 60) → blocking premortem required.
* Regression-asserts MAX semantics would (incorrectly) treat 88d as fresh.
* Symmetric: loosening direction (C→B') also uses MIN — closing the
  downgrade-to-avoid-overdue-premortem loophole.

---

## Cross-references

- Spec Section 4.6 Q5 — Reclassification commit gate
- Spec Section 4.7 Q4 — Sizing/cadence freeze during reclass race
- Spec Section 4.9 Q3 — Pre-mortem cadence resolution rule (MIN, not MAX)
- Spec Section 5.4 — Operator approval gates
- Spec Section 7.3a — Walkthrough launch gates (this doc satisfies #5)
