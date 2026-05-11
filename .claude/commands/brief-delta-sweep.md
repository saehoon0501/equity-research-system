---
description: Sweep all HELD watchlist names for material delta_summary changes between consecutive analyst_briefs runs. Two-tier (Haiku keyword filter → Sonnet narrative explanation for hits). Use when reviewing portfolio after a market-moving week or before macro events.
argument-hint: (no arguments — runs against full watchlist universe)
---

# /brief-delta-sweep

Cross-watchlist material-change sweep over the `analyst_briefs` linked-list. The slow layer's
"what shifted on us this week" view — orthogonal to `/daily-monitor` (which scans external
news/filings); this command instead diffs the *internal* analyst output history. A delta is
"material" when the human-readable `delta_summary` mentions one of a fixed keyword set
(margin, guidance, capex, moat, regulation, litigation, customer concentration, capital return,
exec changes, M&A, solvency). Two-tier so 90% of the watchlist resolves under the Haiku regex
filter and only the genuine hits pay the Sonnet narrative tariff.

Per Flow B v2 task 28.

## §1 Pre-flight — enumerate the universe

Confirm:
- `mcp__postgres` connected (read + write).
- `analyst_briefs` table exists (migration 028) and has rows with non-NULL `delta_summary`.
- `watchlist` table exists (migration 007 + disposition column added in migration 024).

Query the universe (watchlist names operator still cares about):

```sql
SELECT DISTINCT ticker
FROM watchlist
WHERE disposition IN ('HELD', 'TRIGGERED', 'WATCH')
ORDER BY ticker;
```

Schema note: migration 007 names the table `watchlist` (not `v3_watchlist_positions`), and
migration 024 added a `disposition` column with allowed values `HELD` / `WATCH` / `TRIGGERED`
(not `status` / `PROPOSED_ADD` / `WATCHED`). The three dispositions above correspond to:

- `HELD` = active position (cf. spec's `HELD`)
- `TRIGGERED` = entry condition fired, awaiting operator confirmation (cf. `PROPOSED_ADD`)
- `WATCH` = researched-but-not-held monitor (cf. `WATCHED`)

If the universe is empty, report and exit (no work to do — same exit pattern as
`/daily-monitor` §1).

## §2 Tier-1 — Haiku keyword filter

For each ticker in the universe, pull the most-recent brief per `brief_type` (each ticker has
up to two brief streams: `quantitative` and `strategic`). Only rows with a non-NULL
`delta_summary` matter — those are warm-start briefs where the search-agent had a prior
to diff against.

```sql
WITH ranked AS (
  SELECT *,
         ROW_NUMBER() OVER (PARTITION BY ticker, brief_type ORDER BY created_at DESC) AS rn
  FROM analyst_briefs
  WHERE ticker = $1
)
SELECT ticker,
       brief_type,
       created_at,
       prior_brief_id,
       delta_summary
FROM ranked
WHERE rn = 1
  AND delta_summary IS NOT NULL;
```

(The `prior_brief_id` is captured so §3 can fetch the prior brief's `content` for the Sonnet
narrative pass. If the operator wants the prior `created_at` too, follow the FK in a second
small query — keep it cheap.)

### Material-keyword set (case-insensitive)

Apply this regex/substring filter against `delta_summary`. ANY match qualifies the row as a
Tier-1 hit:

| Theme | Keywords |
|---|---|
| Margin pressure | `margin` (gross/operating/net) |
| Guidance change | `guidance` (raise, cut, reaffirm + any magnitude) |
| Capex delta | `capex` (vs prior plan) |
| Moat erosion / strengthening | `moat` |
| Regulatory exposure | `regulat`, `compliance`, `enforcement` |
| Litigation | `lawsuit`, `litigation`, `injunct` |
| Customer concentration | `customer concentration`, `comp loss`, `key customer` |
| Capital return | `share buyback`, `dividend cut`, `dividend raise` |
| Executive turnover | `executive departure`, `CEO`, `CFO` |
| M&A / divestiture | `M&A`, `acquisition`, `divestiture` |
| Solvency / covenants | `bankruptcy`, `going concern`, `covenant` |

Implementation guidance: a single case-insensitive regex with `|`-separated alternations
suffices; Postgres `ILIKE`-with-OR also works. Either way, capture the *matched* keywords
per hit so the operator can see which themes triggered.

### Tier-1 hit record

For each match, materialize:

```
{
  ticker:           "AAPL",
  brief_type:       "quantitative" | "strategic",
  prior_date:       "<created_at of prior_brief_id>",       // resolve via FK
  current_date:     "<created_at of this row>",
  delta_excerpt:    "<first 200 chars of delta_summary>",
  matched_keywords: ["guidance", "margin"]
}
```

## §3 Tier-2 — Sonnet narrative explanation

For each Tier-1 hit:

1. Fetch the full `content` (and `delta_summary`) of both the current brief and the prior
   brief (`prior_brief_id`).
2. Call Sonnet (`claude-sonnet-4-6`) with a prompt asking for a 2-3 sentence narrative
   covering exactly three points:
   - **What actually changed** (concrete, ≤1 sentence).
   - **Which thesis pillar is implicated** (cross-reference watchlist's
     `thesis_pillars_original` if needed for context).
   - **Direction**: does the change *strengthen*, *weaken*, *mix*, or leave the thesis
     *ambiguous*.

Token budget: cap total Tier-2 output at ~60 tokens per hit. If the §2 sweep produces
more than 20 keyword-rich hits, rank-order by (count of matched keywords DESC, then
`current_date` DESC) and process only the top 20. Note the truncation in the output.

## §4 Output schema

```markdown
# Brief-Delta Sweep — {YYYY-MM-DD}

## Tier-1 hits ({N} of {M} watchlist names)

| Ticker | Brief | Prior | Current | Keywords | Δ excerpt |
|---|---|---|---|---|---|
| AAPL | quantitative | 2026-04-30 | 2026-05-10 | guidance, margin | "Q2 guidance cut by 4%; operating margin guide -120bps vs prior..." |
| MSFT | strategic | 2026-04-28 | 2026-05-09 | moat, M&A | "Activision integration risk re-emerges; AI-search optionality..." |
| ...

## Tier-2 narrative ({K} hits)

### {TICKER} ({brief_type})
- **What changed**: <≤1 sentence>
- **Thesis pillar**: <name of pillar implicated>
- **Direction**: strengthens | weakens | mixed | ambiguous

### {TICKER} ({brief_type})
...

## Names with no material delta (sample of 5)
- {TICKER} — last brief {date}, delta_summary: "<first 80 chars>..."
- {TICKER} — last brief {date}, delta_summary: "<first 80 chars>..."
- ...

## Cost
- Tier-1: ~{N} Haiku calls @ ~$0.0001 each = ${...}
- Tier-2: ~{K} Sonnet calls @ ~$0.003 each = ${...}
- Total: ${...}

## Truncation note (if applicable)
- {H} Tier-1 hits exceeded the 20-cap; processed top 20 by (keyword-count, recency).
- Remaining {H-20} hits listed in §Tier-1 but not narrated in §Tier-2.
```

## §5 Persistence

Write the rendered markdown to:

```
briefs/sweeps/{YYYY-MM-DD}_brief_delta_sweep.md
```

Create the `briefs/sweeps/` directory if missing (idempotent `mkdir -p`). One file per
sweep day; if the operator re-runs the same day, the second run overwrites (operator's call
which run is authoritative — keep simple, no versioning suffix).

No Postgres write-back required for v0.1 — the sweep is read-only against `analyst_briefs`.
A future iteration could insert sweep summaries into `system_events` for cross-audit.

## §6 Cadence guidance

Recommended cadence:

- **Weekly**, Friday post-close — captures the week's accumulated analyst-brief deltas
  before weekend reading.
- **Ad-hoc** after material macro events (FOMC, CPI surprise, geopolitical shock) — the
  search-agent will have refreshed warm-start briefs in response; the sweep surfaces which
  watchlist names absorbed the macro shift.
- **Pre-`/quarterly-reunderwrite` batch** — useful as input when deciding which names need
  re-underwriting in the upcoming quarter.

Not a daily command — `delta_summary` only changes when the search-agent runs (which is
not daily for most watchlist names), so daily invocation would be wasteful.

## Hard gate

Per the v0.1 process rubric:

- Every Tier-1 hit must list its matched keywords (no opaque "this row matched" markers).
- Every Tier-2 narrative must explicitly classify direction (strengthens/weakens/mixed/
  ambiguous) — no implicit signaling.
- The "no material delta" sample must be a random-ish 5 (not cherry-picked), to keep the
  operator calibrated on what a *non-event* looks like in this sweep.

## v0.1 vs v0.5 cadence

- **v0.1**: optional, used for testing the sweep pipeline against accumulated brief history.
- **v0.5**: weekly Friday cron, surfaced in operator's Monday-open queue.
- **v1.0**: weekly + ad-hoc on macro-cycle regime shifts, with LearningLoop tuning the
  keyword set against false-positive / false-negative outcomes.
