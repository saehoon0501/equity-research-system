---
description: Run a structured Q&A consensus session to align operator and system on a design decision, architectural choice, or strategic plan. Resolve ambiguity through dialogue + push-back; produce a formal consensus document. Use whenever a design has multiple defensible options, when the operator and system might be implicitly disagreeing, or when implementation can't proceed without locking specific parameter values.
argument-hint: <topic-or-section-name>
---

# /grill-me

Run a structured Q&A consensus session on `<topic>`. The protocol forces the operator and the system to surface every ambiguity, push back where they actually disagree, and lock decisions in writing — so implementation can proceed without rebuilding context from the conversation transcript later.

This is the protocol that produced `docs/section-1-consensus.md` during the Section 1 review of the empirical-domain library design (2026-04-26). Use it whenever a design decision has multiple defensible options or whenever the operator and system might be implicitly disagreeing without realizing it.

## When to use this skill

- A design has 2+ defensible options and a choice must be made
- The operator stated a preference, but you (the system) suspect it has hidden risks
- Implementation can't proceed without locking specific parameter values
- An architectural document was produced but never formally agreed-to
- Earlier conversation reached "we'll figure it out" — that needs to be replaced with a real decision
- Reviewing a multi-component design (split it into sections, run /grill-me per section)

## When NOT to use this skill

- The operator just wants a quick answer or fact-lookup (use a normal response)
- The decision is clearly the operator's prerogative with no system-side risks (just do it)
- The question is "what does X mean?" (just explain it)

## Argument

`<topic-or-section-name>` — required. The specific decision area to align on. Examples:
- "the bet + architectural multipliers"
- "L1 regime capture lane review"
- "smart-money tracking signal selection"
- "v2-final coexistence vs supersession"

If the topic is a multi-section design, propose a section breakdown first and run `/grill-me` per section.

## Session protocol

### Step 1 — Frame the section

In 1-3 sentences, state:
- What this section is about
- Why it matters (what cascades from this decision)
- What success looks like (consensus on N specific items + a written doc)

### Step 2 — 3-minute deep-dive

Tighter than a full summary. Surface only the **load-bearing claims** for this section:
- The core position / thesis being decided
- The 3-5 most important sub-claims
- The 1-2 hidden assumptions the position rests on
- A quick taxonomy of what's "Tier A load-bearing" vs "Tier B supporting" vs "Tier C implementation consequence"

Keep it dense. The operator already knows the topic exists; they need the structure surfaced.

### Step 3 — pose ONE consensus question

Ask exactly one question per round. Sharp, with multiple-choice or yes/no when possible. The question must:

- **Define every term it uses inline.** No assumed jargon. If the operator doesn't have a finance/CS/domain background, explain in plain language with engineering analogies. Example: "Brier score (a measure of how well-calibrated probability forecasts are — lower = better; like RMSE on probabilistic predictions)."
- **State why this matters** (1 line above the question — what cascades from the answer).
- **Offer specific options** when the choice space is bounded. Don't ask "what do you think about X?" — ask "(a) X with consequence Y / (b) Z with consequence W / (c) other (specify)."
- **Be self-contained.** Do not preview Q2, Q3, Q4. The operator handles one decision at a time; previewing creates cognitive load that defeats the protocol.

After posing Q1, plan Q2 internally but do NOT show it. Wait for the operator's answer to Q1 first. After Step 5 synthesis and any Step 6 push-back is resolved on Q1, THEN pose Q2 in a new round.

### Step 4 — Open floor

End each round with: "Your turn — anything to push back on, or something I haven't addressed in this section?"

This is non-optional. Skipping the open floor produces guided-monologue-disguised-as-consensus. The operator must have unprompted dialogue space.

### Step 5 — Synthesize the operator's answers

After the operator answers, in writing:

- **Acknowledge each answer specifically** (not "thanks for that" — restate what they said in your own words to confirm understanding)
- **Surface design consequences** the operator may not have realized their answer triggers (e.g., "your answer to Q2 means the architecture currently has X mis-tuned — flagging as Consensus Item #N")
- **Identify new ambiguity** that the answers introduce (operator's answer to Q3 leaves Q3a, Q3b, Q3c unanswered — pose them as follow-ups)
- **Lock items as you go**. Format: `Consensus Item #N: [specific decision with parameter values]`. Don't batch.

### Step 6 — Push back when warranted

This is the load-bearing part of the protocol. Silent agreement is poor service.

When the operator's stated preference has hidden risks, push back with the structure:

```
**Push-back #N — [the issue, in plain language]**

**What you said:** [restate operator's preference]

**Why I disagree:** [specific reasoning, ideally with concrete failure example]

**Proposed fix:** [your alternative with rationale]

**Confirm or override.**
```

Push-back triggers (use any of these):

- Operator's stated preference contradicts an empirical finding from research the system has done
- Operator's preference creates a hidden parameter value that's miscalibrated for their stated goal
- Operator's preference has a known failure mode that produces the opposite of their stated objective
- Operator's preference inverts a structural protection that's load-bearing in the architecture
- Operator's examples don't match their stated definition (category error)
- Two of operator's answers in this session contradict each other

When NOT to push back:

- Operator's preference is a values judgment (they'd rather have steady returns than aggressive returns — that's their choice)
- Operator's preference is well-calibrated for their stated goal even if it's not your preference
- The disagreement is "I'd do it differently" without specific reasoning — that's not push-back, that's preference

After push-back, the operator decides. Their answer is final unless it produces new contradictions, in which case loop to Step 5 with the new ambiguity.

### Step 7 — Iterate Step 3-6 until the section closes

Don't lock the section just because the conversation has gone on for a while. Lock the section when:

- All Tier A load-bearing claims have explicit parameter values
- All design forks have been resolved (option chosen with reasoning)
- All push-backs have been resolved (operator confirmed or overrode)
- The operator and system both agree there are no hidden ambiguities left
- A formal consensus document can be written that doesn't have the phrases "TBD," "we'll figure out," "to be decided," "depends on context"

If you hit a genuine impasse — operator wants A, system flagged risks, operator confirmed risks but still wants A — log it as a noted-disagreement-with-acknowledged-risk and proceed.

### Step 8 — Write the formal consensus document

Save to `docs/<topic>-consensus.md` (or `docs/section-N-consensus.md` if part of a numbered series).

Required sections:

1. **Header** — date, session purpose, status (locked / partially-locked / impasse-noted)
2. **Operator profile** — captured during the session (scale, goal, constraints, success criteria, falsifiability tests)
3. **The position / thesis** — refined form, with all components decomposed
4. **N locked consensus items** — each with: claim, reasoning, parameter values, examples
5. **Critical architectural findings** — load-bearing structural decisions and their implementation requirements
6. **Design changes from prior baseline** — table of what changed vs the previous spec/design
7. **Deferred items** — what's being put off, with activation triggers
8. **What's locked vs what's open** — explicit list of remaining open questions for next sections

The document must be structured so a future implementer (or future-you with no memory of the conversation) can implement from it without re-reading the conversation transcript.

Commit the document to git as a single coherent commit with an explanatory message.

### Step 9 — Hand off

End with: "Section N closed. Document at `<path>`. Ready for [Section N+1] or another topic."

Do not auto-start the next section. Wait for the operator to invoke /grill-me again or to redirect.

## Style rules during the session

### Plain language + engineering analogies

If the operator doesn't have a background in the domain, every jargon term must be defined inline the first time it's used. Engineering analogies are encouraged where they fit. Examples from the Section 1 reference session:

- "Survivorship bias = like training a classifier on only positive examples; you learn nothing about the boundary."
- "Counterfactual ledger = like keeping a `rejected_pull_requests` log and reviewing it monthly."
- "Calibration / Brier score = online learning where each agent's track record adjusts its weight in the ensemble."
- "Trigger-based refresh = event-driven architecture vs polling."
- "Pre-defined kill criteria = circuit breakers in distributed systems."
- "Anchor drift = stale cache that you've forgotten to invalidate."
- "Mode-aware discipline = different SLAs per service."
- "Adversarial bull/bear = GAN-style architecture; or red-team / blue-team separation."

If the operator says "all the questions are hard to interpret since I don't know any background on each jargon you used" — that's a hard signal to restart with full definitions.

### Same terminology between operator and system

Once a term is defined and locked in the session (e.g., "B-mode = steady compounder; B'-mode = growth compounder; C-mode = thematic"), the system uses the locked terminology for the rest of the session. Don't switch between "B-mode" and "steady-mode" — pick one and use it consistently. The consensus document also uses the locked terminology.

If the operator coins a term, the system adopts it. If the operator corrects the system's terminology mid-session ("what I meant is mix of both"), the system updates and re-uses the corrected terminology.

### Tightness over length

Each round should be readable in 1-2 minutes. Long synthesis blocks lose the operator. If you must produce a long output (e.g., a refined design table), structure it so the operator can scan headers and skip details.

### One question at a time — strict

Ask ONE consensus question per round. Wait for the operator's answer. Synthesize it (Step 5). Push back if warranted (Step 6). THEN pose the next question.

The prior version of this rule allowed batching "tightly coupled" questions, which created drift toward 3-5-question rounds the operator couldn't track. Empirically (session 2026-05-06), batching produced operator pushback "one question at a time."

The only legal multi-question exception: a single conceptual question with explicit (a)/(b)/(c) sub-options that can be answered as a single multiple-choice answer. Two distinct decisions stacked = two rounds, even if they feel related.

If the operator volunteers answers to questions you haven't asked yet, accept those answers but DO NOT batch ahead — still pose the next question one at a time.

### No silent assumptions

If you make a reasonable assumption to keep the session moving (e.g., picking a default during auto mode), state the assumption and what would change it. Don't bury assumptions inside multi-paragraph synthesis.

### Auto-mode handling

If the operator is in auto mode, you may pick reasonable defaults for routine sub-decisions to keep the session moving. But push-back rules still apply — auto mode is not "silently agree with the operator." Auto mode is "make routine decisions autonomously; surface non-routine ones."

## Failure modes the protocol prevents

| Failure mode | Without /grill-me | With /grill-me |
|---|---|---|
| Conversation reaches "we'll figure it out" | Becomes technical debt | Step 7 forces explicit resolution before locking |
| AI silently agrees with operator's preference that has hidden risks | Bad design ships | Step 6 push-back surfaces the disagreement |
| Operator and AI use the same word with different meanings | Implementation mis-matched | Style rule: same terminology, locked once defined |
| Decisions made in chat are forgotten when implementation starts | Re-litigated, time wasted | Step 8 produces a written document |
| One operator answer triggers cascading design changes the operator didn't see | Hidden bugs in design | Step 5 surfaces consequences explicitly |
| Operator can't track 7 questions stacked in one message | Skips questions or answers shallowly | Step 3 caps at 3-5 questions per round |
| Operator without domain background can't engage | Disengagement, low-quality consensus | Style rule: define every term inline; engineering analogies |

## Reference: how the protocol ran in Section 1

The session that produced `docs/section-1-consensus.md` is a complete reference example:

- **Section framed** as "the bet + architectural multipliers" with explicit reason (cascades to L1-L8 lane priorities + funnel design)
- **Initial 5 questions** posed in finance jargon → operator pushed back with "all the questions are hard to interpret since I don't know any background on each jargon you used" → re-posed in plain language with definitions → 3 questions instead of 5 (cut to essentials)
- **Operator answered Q1-Q3** (scale = <$1M; goal = mix of B and C; success criteria = mode-conditional)
- **Q4-Q5 re-asked in plain language** when operator asked "where are q4 and q5?"
- **Operator answered Q4-Q5** revealing two design changes: bull/bear → negotiation; smart-money tracking is missing
- **System pushed back 6 times** (NVDA/AMD/GOOGL category error in B-mode definition; absolute drawdown triggers should be relative-to-benchmark; per-thesis multi-mode is over-engineered; Phase C should be conditional; quarterly cadence is wrong for some reviews; L7 ride-along is empirically weak — needs refinement)
- **Operator confirmed 5 of 6 push-backs**, pushed back on #6 (ride-along works in specific conditions — drawdown-period institutional accumulation), pushed back on #4 (replace bull/bear with style debate)
- **Two research subagents dispatched** (L7 + L8) to refine designs the operator wanted backed by evidence
- **L7 + L8 returned** with refinements that further validated/refuted operator's stated preferences
- **9 consensus items locked** with full parameter values
- **Section 1 consensus document committed** at `docs/section-1-consensus.md` (commit `8f10922`)

Total session length: ~30 turns of dialogue. Output: 365-line consensus document with all parameter values. Implementation can proceed without re-reading.

## Anti-patterns the protocol explicitly rejects

- **"Let's just go with the operator's preference"** — silent-agreement service is poor service. Push-back when warranted.
- **"We'll iterate on this in implementation"** — no, we lock the spec now. Iteration in implementation is fine for unknowns; not for things we can decide now.
- **"This sounds good, ready to move on?"** — premature consensus. Force Step 7's exit criteria.
- **Single-paragraph synthesis with no structure** — operator can't scan it. Use tables, headers, numbered items.
- **Asking "what would you like?"** — that's a vague question. Offer specific options with consequences.
- **Forgetting to commit the consensus document** — chat memory is volatile. Documents persist.

## Output

The session produces three things:

1. **A locked-and-committed consensus document** at `docs/<topic>-consensus.md`
2. **An updated task list** showing what's now locked, what's deferred, what's open for next sections
3. **A clean handoff message** stating what's ready to proceed and what isn't

If any of these is missing, the session isn't done.
