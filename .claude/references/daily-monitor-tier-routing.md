# DailyMonitor Two-Tier Classification

Per v2-final §1.5. Used by `/daily-monitor` command.

## Why two tiers

DailyMonitor is the slow layer's daily heartbeat. With 30–50 watchlist names × ~10–25 news/filings items per day = 300–1250 items to score daily. Running every item through Sonnet would be expensive ($30–80/mo at v0.5 cadence per cost model in v2-final §4.7).

But: missing a thesis-breaking event (score-3 false negative) is the most expensive error the slow layer can make. A bad miss could cost a position 20%+ before the next memo cycle catches it.

Two-tier resolution:
- **Tier 1 (Haiku-class)**: cheap first-pass scoring of every item
- **Tier 2 (Sonnet-class)**: auto-escalation. Anything Tier 1 scores ≥2 routes to Sonnet for confirmation before being released as final score

This bounds cost AND bounds the worst-case error.

## Materiality scoring schema

| Score | Meaning | Action |
|---|---|---|
| **0** | Noise / routine | Logged with justification; no action |
| **1** | Noteworthy but does not affect thesis | Logged with justification; included in daily digest summary |
| **2** | Thesis-relevant; requires monitoring | Logged with justification; **auto-escalates to Tier 2 for confirmation** |
| **3** | Thesis-impacting; triggers re-underwrite | Logged with justification; **auto-escalates to Tier 2 for confirmation**; if confirmed, triggers `/quarterly-reunderwrite <ticker>` for that name |

## Score guidance

### Score 0 (most common — typical day)

- Generic financial news mentioning the company without thesis relevance
- Routine analyst notes with consensus updates (1-cent EPS change, etc.)
- Industry mentions
- Macro headlines unless directly relevant
- Routine SEC filings (Form 4 with normal-sized insider transactions; routine 8-K corporate actions)
- Mere stock price movement without news
- Sentiment swings without underlying news

**Justification example:** "Routine analyst note from BMO Capital lifting PT $5; consensus revision; no thesis implication."

### Score 1

- Sector news that's relevant but not specific to the company
- Material insider transactions (large buys/sells but not at the "abandon ship" level)
- New competitor entries that don't change competitive position materially
- Macro events with indirect exposure
- Litigation or regulatory items that are notable but not thesis-changing
- Earnings beats/misses that fall within expected ranges

**Justification example:** "Insider sells 10K shares (~$2M); within historical pattern of CFO; not meaningful enough to trigger reunderwrite but worth noting."

### Score 2 (auto-escalates to Tier 2)

- Material customer/contract events
- Significant management changes
- New regulatory inquiries
- Earnings beats/misses outside expected ranges
- Material competitive announcements (specific to company's moat)
- Macro events with direct material exposure
- Operational issues (recalls, plant closures, supply chain breaks)
- M&A speculation or activity

**Justification example:** "Apple announces transition away from supplier X for Component Y in 2 years; X has 25% revenue exposure; thesis pillar 2 explicitly relies on Apple revenue stability."

### Score 3 (auto-escalates to Tier 2)

- Thesis pillar fail (KPI test failed at scheduled review)
- Major management departure / restructuring
- Major regulatory enforcement / fine
- Material accounting issue / restatement
- Significant litigation outcome
- Major operational failure (catastrophic recall, security breach, etc.)
- Fundamental business model challenge (strategic announcement that changes the thesis)
- Earnings completely outside expectation with negative guidance
- Activist campaign launched

**Justification example:** "Company X announces FDA halt on lead asset Phase 3 trial; this asset is the centerpiece of thesis pillar 1 ('FDA approval of asset by FY26'); thesis is broken."

## Tier 1 (Haiku) procedure

For each item:
1. Read item
2. Cross-reference watchlist names + thesis pillars
3. Apply scoring per above
4. Write justification (mandatory, even for zeros)
5. Tier 1 outputs: (item, score, justification, ticker, related_thesis_pillar_id)

If Tier 1 scores 2 or 3: escalate to Tier 2.

## Tier 2 (Sonnet) procedure

For each item Tier 1 escalated:
1. Read item with full thesis pillars context
2. Confirm or correct Tier 1 score
3. If confirmed score ≥ 2: enrich with materiality classification details
4. If score 3: produce specific actionable recommendation (e.g., "Trigger immediate re-underwrite of <ticker>; specifically, thesis pillar X is at risk because Y")
5. Tier 2 outputs: (final_score, confirmation_or_correction, action_recommendation)

Tier 2 confirmation absorbs the Tier 1 false-negative risk.

## Cost optimization

| Tier | Model | Items/day | Tokens/item | Cost/item |
|---|---|---|---|---|
| Tier 1 | Haiku | ~750 | ~500 input + 200 output | ~$0.001 |
| Tier 2 | Sonnet | ~75-150 (10-20% escalation rate) | ~2000 input + 400 output | ~$0.012 |

Daily cost: $0.75 (Tier 1) + $1-2 (Tier 2) = ~$2-3/day, or $60-90/mo. Within v2-final §4.7 budget allocation.

## False positive / false negative discipline

Per v2-final §1.5 success criteria:
- Score-3 events: >70% should actually require thesis revision (false positive rate <30%)
- Score-0 events: >95% should NOT require revision (false negative rate <5%)
- Tier 2 escalation accuracy: when Tier 1 escalates and Tier 2 confirms, outcomes validate

These are tracked in calibration history. If false positive rate exceeds 50% (lots of escalations that turn out to be nothing), Tier 1 is being too aggressive and prompt should be tuned conservative. If false negative rate exceeds 10% (real events being scored 0 or 1), Tier 1 is being too aggressive on noise filtering.

## Justification quality (mandatory)

Every score has written justification. Even zeros. Justifications are part of the calibration record over time.

A justification like "no thesis implication" is too thin. Better:
- Reference specific thesis pillar (or absence thereof)
- Explain why the item doesn't (or does) move the thesis
- Note specific pillar IDs being affected

The Evaluator hard-gate per `process-rubric.md` HG-6 returns DailyMonitor digests with score-0 entries lacking justification.

## Sector-level observations

Beyond per-name scoring, DailyMonitor surfaces cross-cutting observations:
- "Regulatory shift across all banking names" (when items 1-5 all touch the same regulatory event)
- "Macroeconomic acceleration affecting consumer discretionary basket"
- "AI infrastructure thesis affirmation across 4 watchlist names"

These observations don't trigger re-underwrites but inform MacroCycleAgent inputs and the operator's mental model.
