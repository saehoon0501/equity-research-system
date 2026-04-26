# Big Finance Stack vs Ours — Phase-by-Phase Comparison

**Purpose.** For each phase of the operator's investment funnel, document what big finance shops actually utilize (people, data, tools, process), what our system uses for the same purpose, where we're materially behind, and where the gap is structurally accepted by design.

**Audience.** The operator (deciding what to build / buy / accept), and future skill-builders (deciding which gap to close first).

---

## Anchor firms for comparison

Different shop archetypes use radically different stacks. The right comparison depends on which archetype our system is closest to.

| Archetype | Examples | Style | Why useful as a comparator |
|---|---|---|---|
| **Discretionary thematic / global macro** | Druckenmiller (Duquesne), Soros (Quantum, Druckenmiller-era 1989-2000), Tepper (Appaloosa), Loeb (Third Point), Ackman (Pershing Square) | Top-down regime → thematic scenario → concentrated names → tactical execution | **Closest in spirit to our operator's funnel.** Primary comparator. |
| **Multi-strategy pod shops** | Citadel, Millennium, Point72, Balyasny | Many independent pods, each with own mandate; centralized risk + drawdown stops | **Upper bound on tooling.** Useful as ceiling — what's possible if cost is no object. |
| **Pure quant / systematic** | Renaissance, Two Sigma, AQR, DE Shaw | Signal libraries, factor exposures, execution algos | Different paradigm; useful where their tooling translates (e.g., factor research, regime classifiers). |
| **Long-horizon discretionary value** | Buffett/BRK, GMO, Klarman/Baupost, Marks/Oaktree | Bottom-up valuation, multi-year holds, low turnover | Different paradigm but operationally simpler — useful as a "what if we accepted the long-only constraint" comparison. |
| **Growth-equity / VC-public hybrid** | Tiger Global, Coatue, Whale Rock, Lone Pine | Story-driven concentrated growth-stock book + private exposure | Closest to the "next-Palantir" name-discovery phase specifically. |

The operator's funnel maps most directly to **discretionary thematic / global macro**, scaled down to a single-operator size. So this comparison anchors on Druckenmiller / Tepper / Loeb / Ackman as the primary "what would a big version of this look like?" reference.

---

## Summary table

| Funnel phase | Big firm utilizes | Our system utilizes | Material gap | Structural diff |
|---|---|---|---|---|
| 1. Regime capture | Bloomberg + alt-data + dedicated macro analysts + proprietary signal libraries | MCP-data servers + LLM signal extraction + L1 empirical reference + Postgres | Real-time alt-data, breadth of signals | LLM amplifies single-operator across many signals at low cost |
| 2. Scenario writing | Sell-side consensus + internal macro team + idea-share networks + Bridgewater-style "Daily Observations" archive | Claude as analyst + L2 empirical reference + multi-year scenario branching | Lacks 24/7 macro-team coverage | Persistent, structured scenario archive in Postgres; no career-incentive distortion |
| 3. Name discovery | Quant screens + sell-side initiations + expert networks (GLG/AlphaSights) + idea conferences (Sohn) + Sumzero/VIC | CompanyDeepDive subagent + Evidence Index + L3 empirical reference (cross-era patterns + counterfactuals) | No expert-network access; no industry-conference attendance | Adversarial bull/bear isolation built in; PASS-default discipline; full source-citation contamination defense |
| 4. Watchlist management | Bloomberg watchlists + FactSet + Aladdin + 30-50-name analyst coverage | Postgres watchlist + PMSupervisor decisions + quarterly reunderwrite cadence | Smaller analyst coverage per name | No turf wars; no career-survival incentive on any name |
| 5. Entry/exit technical | Bloomberg charting + prime-broker exec algos (VWAP/TWAP/IS) + dedicated execution traders | EntryTimingModel + ExitSignalModel + L5 empirical reference | No microstructure execution edge | Designed for low-turnover scale; transaction cost is small fraction of pre-tax alpha at our size |
| 6. Daily refresh | 8am morning meeting + weekly strategy + quarterly review + Bridgewater-style "Issue Log" + pod-shop drawdown stops | DailyMonitor (Tier 1 Haiku → Tier 2 Sonnet escalation) + materiality-3 reunderwrite triggers + L4 empirical reference | No human-team second-opinion in real time | Fully calibrated, auditable, no anchor-drift via human politics |
| 7. Disposition (swing/invest/both) | Pod-shop has separate books per timeframe + multi-strat platforms run all simultaneously | PositionSizingModel + EntryCheck + ExitCheck overlay + L6 empirical reference (22-row decision table) | No separate intraday book; no leveraged exposure | Single book with explicit horizon labels per name; no leverage risk; tax-aware by design |

---

## Phase-by-phase deep dive

### 1. Regime capture (news / indexes / futures → trend)

**Big firm utilizes:**
- **Bloomberg terminal** (~$24k/yr/seat). Real-time price + news + chat (IB chat is where macro flows propagate). Most discretionary shops have 5-30 seats.
- **Alt-data feeds**: Earnest / Yodlee credit-card data ($100k-$1M/yr); SimilarWeb web traffic; Orbital Insight satellite imagery; MarineTraffic shipping; LinkedIn hiring trends. Mid/large discretionary shops spend $1-10M/yr on alt-data alone.
- **Dedicated macro analysts** — Bridgewater has a "research" team of 100+; Tepper / Druckenmiller had 5-15 analysts watching specific signal categories (rates, FX, EM, commodities, vol).
- **Proprietary signal libraries** — Bridgewater "Daily Observations" archive (40 years); Brevan Howard signal book; CTA-shop regime classifiers running thousands of asset-time-series factors.
- **Sell-side morning calls** — 6:30-7:30am NY: GS, MS, JPM macro strategists call out regime reads; BofA's Hartnett "Flow Show"; UBS / DB rates desks.

**Our system utilizes:**
- **MCP-data servers**: `mcp__market_data` (prices, news, real-time quotes), `mcp__edgar` (filings), `mcp__fred` (macro series), `mcp__fundamentals` (Sharadar / point-in-time financials).
- **LLM (Claude)** as the regime analyst — reads news, filings, quant data; classifies regime via L1 empirical reference signals.
- **L1 empirical reference** (`.claude/references/empirical/L1-regime-capture.md`): codifies which signals empirically work — yield-curve (Estrella-Mishkin), excess bond premium (Gilchrist-Zakrajšek), Cochrane-Piazzesi, etc. Pattern #20 (Goyal-Welch-Zafirov OOS audit) keeps the system honest about which signals have survived scrutiny.
- **Postgres** for persistence + continuity (so today's regime read can be compared to last quarter's).
- **MacroCycleAgent** (per v2-final spec) — quarterly full update + daily refresh on major regime indicators.

**Material gap.** No real-time alt-data; no 24/7 macro-team coverage; no IB-chat embedding (where flow info propagates). The "what's actually happening right now" inputs are slower for us.

**Structural diff.** LLM amplifies a single operator across many signals at near-zero marginal cost — a big firm's macro team of 10 analysts costs ~$5M/yr; our equivalent cognitive amplification is dollars per call. The empirical reference + database give us *persistence and structure* a 10-analyst team typically lacks (most macro teams' institutional memory is in private chats, lost on departures).

---

### 2. Scenario writing (3 / 5 / 10 year)

**Big firm utilizes:**
- **Sell-side research** — GS / MS / JPM publish formal scenario decks (e.g., "Top of Mind" GS, "Sunday Start" MS, "Eye on the Market" JPM) consumed by buy-side daily.
- **Internal macro / strategy team** — Bridgewater runs continuous scenario revision via "Daily Observations"; Tepper / Druckenmiller run formal whiteboard scenario sessions; macro-fund PMs personally maintain 3-5 scenario branches with assigned probabilities.
- **GMO 7-year forecast** — quarterly published methodology + per-asset-class prediction.
- **Idea-share networks** — Sumzero, Value Investors Club, sell-side analyst day attendance, Sohn / Robin Hood / Ira Sohn conferences.
- **Bayesian / probabilistic models** — Damodaran-style narrative + numbers; some quant overlay (e.g., AQR's "expected returns" framework).

**Our system utilizes:**
- **Claude** as the scenario writer — informed by L2 empirical reference (Tetlock superforecaster, GMO methodology, Marks "Illusion of Knowledge", Soros reflexivity, Damodaran 3P test).
- **L2 reference patterns** — particularly Pattern #1 (5y point macro forecasts decline toward chance), Pattern #4 (valuation-based 10y forecasts retain power), Pattern #6 (granular probabilities like 60/40 vs 55/45), Pattern #18 (long-term-return decomposition: fundamental growth + valuation re-rating + dividend yield).
- **Postgres** for scenario archive — written at thesis entry, versioned over time.
- **CompanyDeepDive memo's `failure_scenarios` section** — mandatory pre-mortem per v2-final §1.2 process discipline.

**Material gap.** No 24/7 macro-team running parallel scenario revisions; no sell-side digestion at scale; no industry-conference attendance.

**Structural diff.** **Persistent + auditable scenario archive** with no career-incentive distortion (sell-side scenarios chase consensus to manage reputation; buy-side macro teams chase the boss's view). Our scenarios get the contamination check: every probability-weighted claim cites a source date, not a vibe. Pattern #11 (process-vs-outcome separation) is enforced by the Evaluator — the scenario is reviewed for *quality of construction*, not refit to actual outcomes.

---

### 3. Name discovery — "next Palantir" candidates

**Big firm utilizes:**
- **Quantitative screens** — Bloomberg / FactSet for fundamental screens; CapIQ for M&A; PitchBook for private-to-public pipeline.
- **Sell-side initiations** — when GS or MS initiates coverage with a Buy, smart shops read the entire model. Tiger Global at peak had 100+ analysts reading every initiation in their universe.
- **Expert networks** — GLG, AlphaSights, Third Bridge: $500-2000/hr to talk to a former CIO of the company / a current customer / a former regulator. A serious deep-dive at Tiger / Coatue typically includes 10-30 expert calls per name. ~$15-50k of expert-network spend per memo.
- **Idea-share networks** — Sumzero (~$10k/yr), Value Investors Club (free but vetted), Sohn / Robin Hood / Ira Sohn investor conferences, GMI Ratings, Hedgeye.
- **Internal analyst coverage** — Pershing has 2-4 deep-dive analysts per name; Tiger ran 100+ analysts at peak.
- **Counterfactual / loser awareness** — better shops formally track passed names ("file 13 graveyard"); most shops don't, leading to survivorship bias.

**Our system utilizes:**
- **CompanyDeepDive subagent** — produces full memo per v2-final §1.2 procedure: business summary → failure_scenarios → thesis_pillars → variant_view → valuation → confidence_distribution → catalysts → risks → recommended_action.
- **Evidence Index** (`mcp__postgres` table) — every numerical / dated claim cites a source row resolved to a real source predating the claim. Mechanical contamination defense.
- **L3 empirical reference** — 6 sub-files including the cross-era patterns file (`e-cross-era-patterns.md`), the candidate-evaluation checklist, and **the 16-name counterfactual catalog** (Theranos, WeWork, Pets.com, Enron, Valeant, GE, Sears, Cisco, Polaroid, Kodak, Blockbuster, Nokia, BlackBerry, Lehman, Bear, LTCM).
- **Counterfactual ledger** (per v2-final spec) — first-class object measuring system performance against simple baselines (SPY, equal-weight watchlist, sector-matched, 60/40).
- **Adversarial bull / bear isolation** — CompanyDeepDive (bull) and BearCase (bear) run as isolated subagents; PMSupervisor synthesizes.

**Material gap.** **No expert-network access.** This is the biggest single tooling gap vs Tiger Global / Coatue / Pershing. We can't pay $1500 to call a former Salesforce CIO about ServiceNow's competitive position.

**Structural diff.** **Adversarial bull/bear architecture** is rare even at big shops (where bull memos rarely face an organized bear writer with equal context-isolation). **PASS-default** is structural — we have no career penalty for doing nothing, while big-shop analysts must justify their existence with active recommendations. **Counterfactual catalog** is built in (L3 sub-file `d`); most big shops have weak survivorship-bias defenses outside of dedicated quant teams.

---

### 4. Watchlist management

**Big firm utilizes:**
- **Bloomberg watchlists** + **FactSet portfolios** + **Aladdin** (BlackRock's risk system, used by 200+ buy-side firms) for live position monitoring.
- **30-50-name analyst coverage** — typical mid-size discretionary shop. Each name has an analyst who owns updates.
- **Quarterly Investment Committee** — formal portfolio review; each name defended.
- **Risk reports** — daily VaR, factor exposure, beta-adjusted gross/net, sector concentration.

**Our system utilizes:**
- **Postgres watchlist table** — versioned PMSupervisor decisions; each name has conviction score + recommended size band.
- **/quarterly-reunderwrite** slash command — re-underwrites all held names per v2-final §1.2 quarterly cadence.
- **Calibration history** — Brier-score trends per agent over rolling 90-day windows; haircuts applied to overconfident sub-agents.
- **Hard human-approval gate** — no automated trading; operator approves every trade.

**Material gap.** Smaller analyst coverage per name (one operator + Claude vs 2-4 analysts at Pershing per name). Less continuous coverage day-to-day.

**Structural diff.** **No turf wars; no career-survival incentive on any specific name.** A Tiger Global analyst who owns NVDA has a structural incentive to find reasons to stay long; our system's incentive structure is calibration-based and outcome-agnostic. **Full audit trail** — every Watchlist change has an Evidence Index citation; big-shop watchlist changes are typically a Slack message + a verbal handoff.

---

### 5. Entry / exit technical analysis

**Big firm utilizes:**
- **Bloomberg + Eikon charting** for visual technical analysis.
- **Prime-broker execution algos** — VWAP (Volume-Weighted Average Price), TWAP, Implementation Shortfall (IS), POV (Percent-of-Volume). Goldman / MS / JPM prime-brokerage desks provide.
- **Dedicated execution traders** — at Citadel / Millennium / Point72, execution traders are separate from PMs and embedded in pods. They optimize specifically for transaction-cost minimization.
- **Microstructure data** — Level II quotes, trade prints, options flow, dark-pool prints (NYSE OpenBook, Nasdaq TotalView).
- **Risk-overlay options** — covered calls, protective puts, collars used as systematic exit machinery (Spitznagel / Universa is the extreme version; many discretionary shops use modest overlays).

**Our system utilizes:**
- **/entry-check** — 4-factor scoring: trend alignment (20/50/200 DMA), distance from 200DMA, volume confirmation, MacroCycle modifier.
- **/exit-check** — exit signal evaluation (NONE / TRIM / FULL_EXIT / WAIT_FOR_LT_THRESHOLD) with tax-aware logic.
- **L5 empirical reference** — empirically validated patterns only (cross-sectional momentum, time-series momentum, vol-managed exposure, VIX backwardation as regime signal); discard list (head-and-shoulders, candlesticks, Elliott Waves) explicit.
- **Manual execution** — operator places trades themselves through their broker. No exec-algo abstraction.

**Material gap.** **No microstructure execution edge.** A Citadel trader with a $50M position might save 5-15 bps via algorithmic execution; we accept those bps. **No options-overlay machinery** for tail-risk hedging or systematic exit.

**Structural diff.** **Designed for low-turnover scale.** At a $25M-100M individual portfolio size, transaction cost is a small fraction of pre-tax alpha (10-20 bps round-trip for liquid US equities). Optimizing this further has diminishing returns. **L5 reference's discard list** prevents encoding chart-pattern folklore that big-shop traders sometimes still use; our system is constrained to empirically-validated signals only.

---

### 6. Daily refresh discipline

**Big firm utilizes:**
- **Morning meeting** — 8am NY time at most discretionary shops. Each analyst presents news / catalyst / change-of-view on their names. PMs decide adds / trims.
- **Weekly strategy meeting** — broader macro / regime conversation.
- **Quarterly Investment Committee** — every name defended from scratch.
- **Bridgewater-style "Issue Log"** — every disagreement / observation logged for retrospective review.
- **Pod-shop drawdown stops** — at Citadel / Millennium, a pod that hits -5% drawdown gets risk capital cut; -10% can mean termination. Forces immediate refresh discipline.
- **Slack / IB chat real-time** — analysts notify PMs of news as it breaks.

**Our system utilizes:**
- **/daily-monitor** — daily heartbeat of slow layer; sweeps news / filings for all watchlist names.
- **Two-tier classification**: Tier 1 Haiku does cheap routing; Tier 2 Sonnet auto-escalates on materiality-3 events.
- **Materiality-3 escalations** auto-trigger `/quarterly-reunderwrite` for the affected name (full re-underwrite, not just patch).
- **L4 empirical reference** — anchor-drift defense, trigger-based re-evaluation, Annie Duke kill criteria, Marks/Druckenmiller capitulation polarity surfaced as Section C disagreement.
- **Catalyst calendar** in Postgres — pre-defined "what would change my view" notes per held name.

**Material gap.** **No human-team second opinion in real time.** A Pershing analyst can ping Ackman with "this catalyst broke against us" in 30 seconds; our equivalent is the operator + Claude.

**Structural diff.** **Fully calibrated, auditable refresh.** Every reunderwrite produces a Postgres-versioned memo with Evidence Index citations. Big-shop daily-meeting decisions are typically verbal — institutional memory degrades. **No anchor-drift via human politics** — at a multi-team shop, the analyst who covers a losing name has incentive to defend it; our system has no such incentive.

---

### 7. Multi-horizon disposition (swing / invest / both)

**Big firm utilizes:**
- **Pod-shop structure** (Citadel / Millennium / Point72): each pod has a horizon mandate (intraday / swing / multi-month / longer); pod sizing and stops are different. **Multi-strat platforms run all horizons simultaneously.**
- **Single-strategy-fund discipline** (Pershing, Greenlight): one horizon per fund (Pershing concentrated long-term; Druckenmiller flexible 18mo-3yr; Klarman multi-year + cash-heavy).
- **Risk capital allocation** — formally split across horizons; multi-strat CIO allocates to pods based on Sharpe + drawdown + correlation contribution.
- **Tax-aware structure** — long-only funds harvest losses; multi-strats often hold positions in short-term capital-gains vehicles (it's not a constraint there).

**Our system utilizes:**
- **/size** — PositionSizingModel: dollar size + weight % per name, with sizing decomposition (calibration history, regime modifier, conviction).
- **/entry-check + /exit-check** — multi-horizon overlay on watchlist names.
- **L6 empirical reference** — Section D 22-row characteristic→disposition table (volatility regime → swing / long / both); Druckenmiller 18mo-3yr default; Munger tax math; Tudor Jones time-stop vs Marks thesis-break-stop separator.
- **Calibration-driven sizing** — Quarter-Kelly default, bounded floor (1/8 Kelly) / ceiling (1/2 Kelly), modulated by Brier score trends.
- **Wash-sale-aware tax handling** (per `/wash-sale-harvest`).

**Material gap.** **No separate intraday / swing book** — we run a single book with horizon labels per name, not multiple physically-separate books. **No leveraged exposure** — a multi-strat at 5x notional / GMV cannot be replicated.

**Structural diff.** **Tax-aware by design** — Munger's 13.3%-vs-9.75% math (3.5%/yr drag) is structurally honored. **Honest about disposition type** — every name has explicit horizon labeling; in pod shops, pods compete for risk capital and may fudge horizons to optimize their own metric. **Wide P10/P90 ranges** with realized-volatility honesty floor — big-shop position sizing rarely surfaces full distributions; ours is required to.

---

## Where we're knowingly accepting gaps

Material differences our build is *aware of and choosing not to close*:

1. **Expert-network access** ($500-2000/hr industry calls). Closing this means budget commitment of $20-100k/yr for a serious name-discovery capability. **Decision: accept**, defer until v0.5+ when paper-only validates the rest of the system.
2. **Real-time alt-data** ($1-10M/yr at scale). **Decision: accept structurally** — operator's portfolio size doesn't justify alt-data spend.
3. **Microstructure execution edge** (5-15 bps savings per round trip via algos). **Decision: accept** — at low turnover + small size, the absolute dollar savings is below the cost of building / buying execution infra.
4. **24/7 macro team** (~$5M/yr personnel cost). **Decision: replaced by LLM cognitive amplification**, with explicit acknowledgment that LLM coverage is not 24/7 in the same way (the operator must initiate inquiry).
5. **Sell-side research consumption** ($50-200M/yr at large firms). **Decision: replaced by Claude-driven primary-source research** (filings + earnings calls + alt-source analysis); accept losing the sell-side initiation-channel for new ideas.
6. **Trading at scale** — leverage, options-overlays, derivatives execution. **Decision: out of scope** for v0.1 / v0.5; cash equity only.

---

## Where we're structurally different (and that's OK)

Differences that aren't gaps — they're features of the architecture:

1. **PASS-default decision-making.** Big-shop analysts have career incentive to recommend; our system defaults to PASS unless conviction is earned. This is a structural advantage at our scale.
2. **No career-survival incentive on any specific name.** Removes a real source of anchor drift in human teams.
3. **Adversarial bull/bear isolation built into the architecture.** Few big shops have this systematized; many have only informal devil's-advocate rituals.
4. **Mechanical contamination defense via Evidence Index.** Every numerical / dated claim cites a source row predating the claim's resolution date. No big shop runs this protocol — they rely on analyst judgment + retrospective post-mortems.
5. **Calibration-driven sizing with Brier-score modulation.** Most big shops size by gut + risk-mandate; ours formally haircuts overconfident agents.
6. **Counterfactual ledger as a first-class object.** Tracks performance against simple baselines (SPY, equal-weight watchlist). Few discretionary shops do this rigorously.
7. **Full audit trail on every decision.** Every PMSupervisor synthesis writes its reasoning trace + the inputs it weighted. Big-shop decisions are typically verbal + Slack — institutional memory is lost on personnel turnover.
8. **Tax-aware as a first-class concern.** Big shops in tax-deferred vehicles (some hedge funds, endowments) ignore tax; family offices and individual investors don't have that luxury. Our wash-sale handling and tax-cost calculations are built into `/exit-check`.
9. **No tracking-error pressure.** A long-only mutual fund is benchmarked against the S&P; deviating too much risks redemptions. Our operator has no benchmark — pure absolute-return discipline.
10. **No regulatory disclosure cadence.** 13F filing every quarter shapes hedge-fund behavior in real ways (visibility of positions to competitors, copycat risk). We have no such constraint.

---

## Implications for the build

Reading the comparison phase by phase, the **highest-leverage gap to close** depends on what the operator most lacks today:

- **If the bottleneck is name discovery quality** → expert-network access ($20-100k/yr) is the highest-ROI close. L3 empirical reference + counterfactual catalog is the second-best substitute.
- **If the bottleneck is regime read** → alt-data is too expensive; the better close is **expanding L1 reference** to cover more practitioner regime-classification frameworks (Bridgewater All Weather decomposition, Brevan Howard regime detection).
- **If the bottleneck is execution** → at our scale, this is genuinely the lowest-priority gap.
- **If the bottleneck is daily refresh discipline** → the system is *already structurally better* than most big shops on this axis (auditable, calibration-driven, no human politics). The remaining gap is the operator's bandwidth, not the architecture.
- **If the bottleneck is disposition flexibility** → L6 empirical reference + the 22-row decision table is the operationally-richest version of this in the industry. Closing this further requires actual position experience (which v0.5 produces).

**The honest summary:** our system is *structurally weaker* than a big-firm stack on raw input volume (alt-data, expert networks, sell-side digestion, 24/7 team coverage) and *structurally stronger* on decision-quality machinery (Evidence Index, adversarial bull/bear, calibration-driven sizing, counterfactual ledger, audit trail). The design bet is that decision-quality machinery dominates input-volume advantages at small scale.

That bet may or may not be correct. **The empirical test of the bet is v0.1 → v0.5 → v1.0.** The comparison above defines what we'd need to add at each scale-up checkpoint if the bet fails.
