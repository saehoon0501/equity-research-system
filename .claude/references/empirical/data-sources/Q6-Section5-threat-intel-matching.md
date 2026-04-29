# Threat-intel signature matching calibration patterns

**Investigation question:** How do threat-intelligence and cybersecurity teams calibrate signature-based pattern matching against known-bad reference databases — what are the precision/recall tradeoffs, gold-standard test set designs, and drift-monitoring practices we can borrow for our 32-case "signature DB" of failed multi-baggers?

**Closest analog:** YARA rules / Suricata signatures / MISP IOC matching. Same structural problem: small curated DB of "known bad" patterns, scored against incoming candidates, false-positive cost (alert fatigue / wasted analyst cycles) vs false-negative cost (missed threat / failed thesis) is asymmetric.

**Bottom line up front (BLUF):**
- The dominant production pattern in security is a **two-tier funnel**: (1) loose mechanical matching tuned for high recall, (2) human/analyst review tuned for precision. Our system already maps cleanly onto this — mechanical signature-DB scoring as Tier 1, LLM/PM judgment as Tier 2.
- For a 32-case DB, **the closest precedent is MISP warning-list + sightings** (curated small-N indicator DB with quality scoring + decay), NOT ML-style high-dim embedding matching. Boolean/categorical feature matching with **explicit warning lists for known-benign-collisions** is the right architecture at our sample size.
- **Gold-standard test set design** in security uses scripted benign + scripted adversarial activity windows (DARPA Engagement model), with **EICAR-style canaries** as continuous heartbeat checks. We need both.
- **Drift is the dominant failure mode**, not initial calibration. Half-life of IOCs is hours-to-days at the network layer, weeks-to-months at the TTP layer. Our "kill criteria" features sit at TTP layer → expect months-to-years half-life, but still need explicit decay/retirement protocol.

---

## Section A — Curated sources (tier-labeled)

**Tier conventions:**
- **T1** = primary technical documentation, peer-reviewed academic, or official framework docs
- **T2** = vendor whitepapers, industry-standard practitioner blogs, ACM/IEEE conference proceedings
- **T3** = secondary reporting, glossary explainers, mainstream tech press

### A.1 — YARA / signature-rule design (T1-T2)

1. **[Neo23x0 / Florian Roth — YARA Style Guide (GitHub)](https://github.com/Neo23x0/YARA-Style-Guide)** — T1. The canonical practitioner spec for writing maintainable, low-FP YARA rules. Conventions for naming, metadata, FP-prevention strings (`$fp*` pattern), and required test coverage. Florian Roth runs Nextron Systems / THOR scanner; this is the reference style guide most YARA rule authors follow.
2. **[Neo23x0 — YARA Performance Guidelines (gist)](https://gist.github.com/Neo23x0/e3d4e316d7441d9143c7)** — T1. Specific guidance on string atom selection (≥4 bytes), avoiding regex backtracking, and the relationship between rule specificity and scan-time cost. Directly relevant to "feature richness vs match speed" tradeoff.
3. **[Securview — YARA Rule Tuning](https://www.securview.com/ai-security-essentials/yara-rule-tuning)** — T2. Defines tuning workflow: analyze rule against known-good and known-bad sets; iterate on FP/FN counts; governance/version-control for rule lifecycle.
4. **[Securview — YARA Validation](https://www.securview.com/ai-security-essentials/yara-validation)** — T2. Validation protocol: maintain paired benign + malicious test corpora; require both before promoting a rule to production.
5. **[Raff & Filar — Automatic YARA Rule Generation Using Biclustering (arXiv 2009.03779)](https://arxiv.org/pdf/2009.03779)** — T1. Academic work on auto-generating YARA rules from a small set of malware samples — directly analogous to "given 32 known-bad cases, what features should the signature DB encode?"
6. **[Cymulate — YARA Rules Explained](https://cymulate.com/cybersecurity-glossary/yara-rules/)** — T2/T3. Decent overview of structure-tactics-detection use cases; useful for the staged-detection idea (loose YARA → ML classifier filter).

### A.2 — Suricata / Snort IDS rule calibration (T1-T2)

7. **[Suricata Docs — Making Sense out of Alerts (7.0.2)](https://docs.suricata.io/en/suricata-7.0.2/make-sense-alerts.html)** — T1. Official docs on alert interpretation, threshold/suppression, and alert-quality management.
8. **[Emerging Threats Community — Handling False Positive Reports as a Rule Writer](https://community.emergingthreats.net/t/handling-false-positive-reports-as-a-rule-writer-special-guests-pcres-dalton-dalton-s-flowsynth/1031)** — T1. ET Open is the largest open IDS ruleset (~50k rules); this is the rule-writers' guide on handling FP reports, including PCRE anchoring, Dalton testing harness, and Flowsynth pcap generation.
9. **[Snort — README.thresholding](https://www.snort.org/faq/readme-thresholding)** — T1. Canonical reference for `gen_id`/`sig_id` per-rule throttling; how to limit alert volume on noisy rules without disabling them.
10. **[Snort — README.filters](https://www.snort.org/faq/readme-filters)** — T1. Suppression vs. event-filter mechanics. Suppression eliminates events entirely; event-filter throttles them.
11. **[Cisco — Options to Reduce False Positive Intrusions](https://www.cisco.com/c/en/us/support/docs/security/firesight-management-center/117909-config-sourcefire-00.html)** — T2. Vendor-side framework: tune by host criticality, asset profiles, and protocol context.

### A.3 — Threat-intel platforms (MISP, STIX/TAXII, VirusTotal) (T1-T2)

12. **[MISP — Best Practices in Threat Intelligence](https://www.misp-project.org/best-practices-in-threat-intelligence.html)** — T1. The reference doc for IOC quality, sightings (community ground truth), and decay models.
13. **[MISP — Decaying of Indicators (2019)](https://www.misp-project.org/2019/09/12/Decaying-Of-Indicators.html/)** — T1. Specifies the decaying-indicator model: configurable decay rules per indicator type, score → 0 retire-from-detection. Directly applicable to our "when to retire a kill-criterion signature."
14. **[MISP/misp-warninglists (GitHub)](https://github.com/MISP/misp-warninglists)** — T1. The actual data: curated lists of indicators known to cause FPs (CDN IPs, public DNS resolvers, Microsoft IPs, etc.). The structural analog for our system would be "list of features that look like multi-bagger killers but are spurious."
15. **[Ermerins & de — Scoring Model for IoCs by Combining Open Intelligence Feeds (UvA OS3 2020)](https://rp.os3.nl/2019-2020/p55/report.pdf)** — T1. Academic paper on combining feeds → 0-to-1 IOC quality score. Multi-source consensus reduces FP.
16. **[CARIOCA: Prioritizing IoCs by Threat Assessment on MISP (Springer 2025)](https://link.springer.com/article/10.1007/s10207-025-01006-2)** — T1. Recent academic prioritization scheme using analysis-stage status as a proxy for FP risk.
17. **[OASIS — Introduction to STIX](https://oasis-open.github.io/cti-documentation/stix/intro.html)** — T1. STIX patterning language: structured AND/OR/observable expressions. The data model we should mirror for "kill-criterion signature."
18. **[VirusTotal — How It Works](https://docs.virustotal.com/docs/how-it-works)** — T1. 70+ engine aggregation. Multi-scanner consensus is the production model for "ensemble of weak detectors."
19. **[VirusTotal — False Positive docs](https://docs.virustotal.com/docs/false-positive)** — T1. Operational guidance on how AV vendors handle FP reports; the "shared signature" gotcha (multiple AV products use the same backend → consensus is not as independent as it looks).

### A.4 — SOC operations & alert triage (T1-T2)

20. **[Saaheli et al. — Alert Fatigue in Security Operations Centres: Research Challenges and Opportunities (ACM Computing Surveys 2025)](https://dl.acm.org/doi/10.1145/3723158)** — T1. Recent comprehensive survey of alert-fatigue research: automation, augmentation, and human-AI collaboration as the three escape valves.
21. **[Reducing SOC Analysts Alert Fatigue via Real-Time CTI Correlation and Deduplication (Springer)](https://link.springer.com/chapter/10.1007/978-3-032-19540-1_2)** — T1. Deduplication/correlation as FP-suppression mechanism.
22. **[Exaforce — Tier 1 Alert Triage: SOC Analyst's Complete Guide](https://www.exaforce.com/learning-center/tier-1-alert-triage)** — T2. Concrete checklist for what Tier 1 verifies before closure-as-FP vs. escalation; the canonical hand-off package contents.
23. **[Q-Sec — SOC Roles & Responsibilities: Tier 1, 2, 3 Explained](https://q-sec.com/soc-knowledge-base/soc-roles-responsibilities-tier-1-2-3)** — T2. Standard tiered-review model.

### A.5 — Test-set design (T1)

24. **[DARPA Transparent Computing — Engagement E3/E5 README (GitHub)](https://github.com/darpa-i2o/Transparent-Computing/blob/master/README-E3.md)** — T1. The reference design for adversary-emulation test sets: scripted benign baseline + adversarial windows + ground-truth file curated by red team.
25. **[Berady et al. — Analyzing the Usefulness of DARPA OpTC Dataset in Cyber Threat Detection (ACM SACMAT 2021)](https://dl.acm.org/doi/10.1145/3450569.3463573)** — T1. Independent academic critique of DARPA OpTC test-set design — what worked, what didn't.
26. **[EICAR — Anti-Malware Testfile](https://www.eicar.org/download-anti-malware-testfile/)** — T1. The canonical canary: a benign file every AV vendor agrees to flag. The model for "always-flagged-positive" calibration anchor.
27. **[EICAR Test File — Wikipedia](https://en.wikipedia.org/wiki/EICAR_test_file)** — T2. Background on the canary pattern.

### A.6 — Drift & feedback loops (T1-T2)

28. **[RFC 9424 — Indicators of Compromise (IoCs) and Their Role in Attack Defence (IETF)](https://datatracker.ietf.org/doc/html/rfc9424)** — T1. Standards-track document on IOC lifecycle, velocity, and tactical decay.
29. **[Dragos — End of Life of an Indicator of Compromise](https://www.dragos.com/blog/end-of-life-of-an-indicator-of-compromise-ioc)** — T2. Practitioner perspective on retirement criteria.
30. **[Chismon & Ruks — Decaying Indicators of Compromise (ResearchGate)](https://www.researchgate.net/publication/324104555_Decaying_Indicators_of_Compromise)** — T1. The original MISP-decay paper.
31. **[Cuckoo Sandbox — Signatures Documentation](https://cuckoo.readthedocs.io/en/latest/customization/signatures/)** — T1. How dynamic-analysis signatures get authored, scored (severity 1-3), and combined.
32. **[Walker & Sengupta — Cuckoo's Malware Threat Scoring and Classification (IEEE CCWC 2019)](https://www.cse.unr.edu/~shamik/papers/Walker-IEEE_CCWC-Accepted-2019.pdf)** — T1. Academic work on combining sandbox signatures into composite threat scores — directly analogous to combining multiple kill-criterion signatures into a composite "this looks like a failed multi-bagger" score.

### A.7 — MITRE ATT&CK & threat hunting (T1-T2)

33. **[MITRE ATT&CK — Enterprise Techniques](https://attack.mitre.org/techniques/enterprise/)** — T1. The canonical TTP taxonomy. Sub-techniques are the pattern for hierarchical signatures (broad pattern + specific sub-instance).
34. **[MITRE — TTP-Based Hunting (mitre.org)](https://www.mitre.org/sites/default/files/2021-11/prs-19-3892-ttp-based-hunting.pdf)** — T1. Behavioral-pattern hunting at the TTP level (slower-decaying than IOC level). Most relevant to our use case because our kill-criteria are TTP-like, not IOC-like.
35. **[Splunk — Hypothesis-Driven Hunting with the PEAK Framework](https://www.splunk.com/en_us/blog/security/peak-hypothesis-driven-threat-hunting.html)** — T2. PEAK = Prepare-Execute-Act-with-Knowledge. Hypothesis-driven validation workflow.
36. **[Elastic Security Labs — From Hypothesis to Action](https://www.elastic.co/security-labs/proactive-threat-hunting-with-elastic-security)** — T2. Practitioner walkthrough of hypothesis → query → validation → feedback-into-detection cycle.

### A.8 — Honeypot / ground-truth collection (T1-T2)

37. **[A Practical Honeypot-Based Threat Intelligence Framework (arXiv 2512.05321, 2026)](https://arxiv.org/pdf/2512.05321)** — T1. Recent framework for ingesting honeypot data → MITRE ATT&CK-aligned detection. The continuous-ground-truth-collection model.
38. **[Intelligent Threat Detection — AI-Driven Analysis of Honeypot Data (MDPI Electronics 2024)](https://www.mdpi.com/2079-9292/13/13/2465)** — T1. Academic survey of honeypot-based ML training pipelines.

---

## Section B — Production calibration approaches

### B.1 YARA-style precision/recall tuning

The YARA community has converged on a small number of disciplines that map almost 1:1 onto our problem.

**B.1.1 String specificity over string count.** Neo23x0's style guide is emphatic: prefer 6-8+ byte strings that uniquely identify the malware family over a large set of short generic strings. Short generic strings → high collision rate with benign code → high FP. **Translation to us:** prefer a small number of high-information features (e.g., "EBITDA-to-FCF gap >40% sustained 3y") over many low-information features ("revenue grew last year"). The signature DB should encode 5-15 high-information features per case, not 50 low-information ones.

**B.1.2 Explicit FP-string convention (`$fp*`).** YARA rules explicitly enumerate strings that, if present, *negate* the match — even if the malicious strings are also present. The rule logic is `(malicious_strings) and not any of ($fp*)`. **Translation to us:** every kill-criterion signature should ship with an explicit "exoneration list" — features that, if present in the candidate, override the negative match. E.g., "EBITDA-FCF gap >40%" might match Amazon 2010-2015 (capex-heavy reinvestment) which would be a FP for the "earnings quality" kill-criterion → need an exoneration condition like "if reinvestment ROIC trajectory is rising AND TAM expansion is documented, exonerate."

**B.1.3 Constraint conjunctions.** Pure pattern-OR is high-recall, high-FP. Production YARA rules require conjunctions: filesize range AND module check AND string combination. **Translation to us:** a kill-criterion signature should not fire on any single feature; require K-of-N conjunction (e.g., "fires only if at least 3 of [governance flag, accounting flag, customer concentration, capex distortion, insider selling] are present").

**B.1.4 Two-stage detection.** Modern practice (e.g., the Securview pipeline) uses loose YARA tuned for high recall as Stage 1, followed by an ML classifier or human analyst as Stage 2. This is the dominant pattern for one reason: **the precision-recall frontier is non-monotonic when you allow a second stage** — you can simultaneously get higher recall AND higher precision than a single-stage tuned classifier. **Translation to us:** mechanical signature-DB scoring should be tuned for *recall* (catch every plausibly suspect candidate), with the LLM/PM stage doing *precision* work (filtering benign matches). This is exactly what our v0.5 architecture already does.

### B.2 Tiered review model

The Tier 1 / Tier 2 / Tier 3 SOC model is well-documented (Q-Sec, Exaforce, Radiant). Key invariants:

- **Tier 1** does mechanical triage — does the alert fit any documented FP pattern? Is the asset in a tagged test environment? Is the user/asset in baseline? If yes to any → close. If no → enrich + escalate. Tier 1 closes ~70-90% of alerts as FP.
- **Tier 2** validates, scopes, and decides on action. Tier 2 sees only the alerts Tier 1 escalated, with the enrichment package attached.
- **Tier 3** does threat hunting and incident response — works hypothesis-driven, not alert-driven.

**Critical invariant: escalation quality.** Exaforce's guide is explicit: a Tier 1 → Tier 2 escalation must include (a) the original alert, (b) all enrichment Tier 1 collected, (c) Tier 1's documented reasoning, (d) initial scope/impact assessment. **If Tier 2 has to redo enrichment, the tiering provides no value.** This is the "package the context, don't re-derive it" rule.

**Translation to us:** the signature-DB-match output that goes to the LLM analyst should be a structured package: which signatures fired, which features matched/exonerated, distance metric, nearest-neighbor case IDs in the DB, prior outcomes for similar matches. Not just a "score."

### B.3 Aggregation patterns (multi-engine consensus)

VirusTotal aggregates 70+ AV engines. The folk rule is **90% consensus → trust as malicious**, but this hides important nuance:

- **Independent engines aren't independent.** Many AV products license each other's engines or share signature feeds. A 5-of-70 detection might really be 1-of-effectively-3 if those 5 share a backend. (VirusTotal docs are explicit about this gotcha.)
- **Per-engine reliability priors matter.** Some engines (Microsoft, Kaspersky, ESET, BitDefender) have much higher TPR/lower FPR than long-tail engines.
- **Vote weighting beats simple counting.** Production consensus systems weight by historical engine reliability per malware family.

**Translation to us:** if we ever build "ensemble of feature-detectors" voting on multi-bagger-failure risk, we cannot treat features as independent. Many of our kill-criteria features are correlated (e.g., aggressive accounting and customer concentration co-occur in failed roll-ups). Consensus thresholds need to account for the correlation structure, not just count features.

### B.4 The MISP "warning list + sightings + decay" stack

This is the closest production analog to our system size and structure. MISP is the de facto open-source threat-intel platform; its operational model is:

- **Warning lists** = curated lists of known-FP-prone indicators (CDN IPs, public resolvers, Microsoft IPs, Google IPs, well-known good hashes). Indicators that match a warning list are flagged but not automatically suppressed — humans see the warning context. **Pattern: don't auto-filter, surface context.**
- **Sightings** = community-contributed signal that an indicator was seen in the wild (TP) or was a FP. Aggregates over time → quality score per indicator.
- **Decay model** = indicators score down over time at type-specific rates. IPs decay fastest (hours-days); domains slower (days-weeks); file hashes slowest (weeks-months); TTPs slowest of all (months-years).

**Translation to us (most important pattern in this whole research brief):**
- **Warning list analog:** maintain explicit list of features that look like kill-criterion hits but are systematically benign in our domain (e.g., "negative FCF in years 1-3" is a kill-criterion-looking feature for mature companies but is benign for early-stage growth). Features matching the warning list get a context flag, not auto-rejection.
- **Sightings analog:** every PM override of a signature-DB match (either direction) is a "sighting" — log it, aggregate, use to recalibrate.
- **Decay analog:** kill-criteria features tied to specific historical regimes (e.g., "ZIRP-era roll-up debt structure") need explicit decay rules; features tied to fundamental accounting/governance issues decay slowly.

---

## Section C — Test-set design in security

### C.1 Known-positive test cases (canaries)

**EICAR is the gold standard.** A 68-byte text file that every compliant AV product agrees to flag. Used for:
- Heartbeat checks (does the detector still work?)
- Pipeline validation (does the alert reach the SIEM? Does it route to the right analyst queue?)
- Cross-layer testing (endpoint, network, email, cloud-storage, web-proxy — each layer should catch EICAR independently)

**Critical limitation:** EICAR proves only that signature matching mechanism works, NOT that the detector catches sophisticated threats. Malwarebytes and others are explicit about this.

**Translation to us:** we need an "EICAR set" of 3-5 historical multi-bagger failures that are **so unambiguously failed that every variant of our system should flag them**. Examples: Enron 2000, Theranos 2014, Wirecard 2018-2019, Luckin Coffee 2019. If our signature DB does not flag these on their pre-collapse data, the pipeline is broken — independent of any specific kill-criterion calibration. These should be in a separate canaries/ directory, NOT inside the 32-case signature DB itself (otherwise we're testing-on-train).

### C.2 Negative test cases (known-good must-not-flag)

DARPA Engagement model: scripted **benign baseline** that runs continuously, on top of which adversarial activity is overlaid in time-bounded windows. The benign baseline answers "what does normalcy look like?" and any alert during pure-benign windows is by-construction a FP.

**Translation to us:** we need a curated list of historical *successful* multi-baggers (NVDA 2013, AMZN 2008, MSFT 2014, AAPL 2003, etc.) at *similar valuation/skepticism conditions* — these must NOT trigger our kill-criteria. Practical target: 8-15 known-good cases. If a kill-criterion fires on >X% of known-goods, it's miscalibrated. This is the analog of the "loose YARA + benign corpus regression test" that all serious YARA rule shops run before promoting a rule.

### C.3 Coverage of feature space

DARPA Engagements ran multiple TA1 platforms (different OSes, different host types) to ensure detectors weren't overfit to one substrate. Critical insight: **a test set that doesn't span the feature space the detector will see in production is worthless.**

**Translation to us:**
- **Sector coverage:** 32 cases must span sectors, not concentrate in one (e.g., not all biotech failures).
- **Era coverage:** must span macro regimes (pre-GFC, ZIRP era, post-2022) — features that fired in one regime may not in another.
- **Failure-mode coverage:** must span failure types (fraud, secular decline, operational execution, capital structure, regime/cycle).
- **Size coverage:** should not be all megacaps or all small caps.

If our 32 cases don't span these axes, the calibration is structurally biased — we'll have low FPR on cases similar to training set, high FPR on out-of-distribution candidates.

### C.4 Time-windowed evaluation (DARPA pattern)

DARPA Engagements evaluated detectors in two phases: live detection (real-time) and forensic analysis (post-hoc). The forensic phase typically catches more, but the operationally-relevant metric is live detection.

**Translation to us:** evaluate signature DB on **the data available at time T** (e.g., 6-12 months before the failure crystallized), not on hindsight-complete data. This is the contamination-check rigor we already have, but worth re-emphasizing in this context.

---

## Section D — Drift monitoring

### D.1 How signature DBs degrade over time

Three distinct decay timescales (per RFC 9424, MISP decay model, Dragos):

| Indicator type | Half-life | Failure mode |
|---|---|---|
| IP addresses | hours-days | Attackers rotate infrastructure |
| Domains | days-weeks | Domain-fronting, fast-flux DNS |
| File hashes | weeks-months | Recompilation, polymorphism |
| TTPs / behaviors | months-years | Tooling/methodology shifts |
| Strategy patterns | years-decade+ | Regime shifts |

Our kill-criteria sit between TTP and strategy-pattern levels. Expected half-life: years, not months. But "long half-life" does not mean "no decay" — regime shifts (e.g., post-ZIRP capital structure norms) can rapidly invalidate a previously-reliable signature.

### D.2 When to retire / recalibrate signatures

MISP's decay model is configurable per-indicator-type. Retirement triggers:
- **Score-based:** indicator decays below threshold → auto-retire from active detection but keep in archive.
- **Sighting-based:** if N consecutive sightings flag as FP, escalate for human review.
- **Event-based:** explicit invalidation (threat actor remediated, infrastructure taken down, vendor patched the vuln).
- **Calendar-based:** quarterly/annual full review of all rules.

**Translation to us (event-driven update model from Q4):** our update cadence is event-driven, which matches MISP's sighting + event-based triggers. We should explicitly add:
- **PM-override sightings:** every time PM overrides a signature-DB match in either direction, log it. ≥3 consecutive same-direction overrides → review the signature.
- **Regime-shift events:** when macro Q3/Q4 framework escalates a regime change, all kill-criteria signatures with regime-tied features get a flag for review.
- **Annual full audit:** on every Jan 1, every signature gets a fresh review against the most-recent year of data.

### D.3 Feedback loops from production

Three production patterns:

1. **Honeypot ingest** (continuously generates labeled-positive samples). For us, the analog is **post-mortem write-ups of new failed-multi-bagger candidates as they emerge** — these are the new "samples." Cadence: opportunistic (when new failures crystallize), not scheduled.
2. **Sandbox feedback (Cuckoo)** — every analyzed sample contributes to score calibration. For us, the analog is **every PM decision (ADD/REJECT/WATCH) becomes labeled training data for the signature-DB calibration**.
3. **Sightings aggregation (MISP)** — community ground truth. For us, single-operator system means sightings = our own historical PM decisions. Long term, if multiple operators use the system, sightings could aggregate across operators.

---

## Section E — Lessons applicable to our case

### E.1 Most-applicable security pattern: MISP-style warning-list + sightings + decay

The MISP pattern is the closest structural match to our problem. Why:
- Small-N curated DB (MISP threat-feed sizes are typically thousands of indicators, but per-organization curated subsets are often dozens-to-hundreds — same order of magnitude as our 32).
- Boolean/categorical feature matching (not embedding-based).
- Quality-score model (each indicator has a confidence/quality score, not just present/absent).
- Explicit warning-list mechanism for known-benign collisions.
- Decay model with event-driven and calendar-driven retirement.
- Sightings as the feedback-loop primitive.

**Recommendation:** explicitly model our system after MISP's data primitives:
1. Each of the 32 signature-DB cases → a **STIX-style indicator object** with: pattern (the K-of-N feature conjunction), confidence, valid_from, valid_until (optional), references to source documents.
2. A **warning-list table** of features that look like kill-criterion hits but are systematically benign in our universe (sector- and regime-specific).
3. A **sightings log** = every PM decision indexed by which signatures fired, with the ground-truth outcome label appended later.
4. A **decay schedule** = per-signature retirement criteria.

### E.2 32-case DB calibration considerations

**32 is small — embrace it, don't pretend otherwise.**

- **Don't use ML/embedding methods.** With 32 cases and 5-15 features each, you have 160-480 data points total — far below the threshold where embedding methods (which need 10^4+ samples) generalize. Boolean/categorical conjunction matching is the right tool.
- **Cross-validation is unreliable at N=32.** Leave-one-out CV on 32 cases gives standard errors on FPR/TPR estimates that swamp the point estimates. **Use it directionally, not for tight calibration.**
- **The Probability of Backtest Overfitting (PBO) framework you already use applies here.** Treat each "tuning iteration" of the signature DB as a backtest trial, deflate any apparent improvement by trial count. Don't tune the DB to 100% TPR on the 32 cases — that's overfit by definition.
- **Lean on canaries and known-good cases for actual calibration.** The 32 cases are the *training* set; calibration happens against (a) EICAR-style canaries (the 3-5 unambiguous failures every variant must flag), (b) the known-good list (8-15 successful multi-baggers that must NOT flag).

### E.3 Boolean-feature matching pitfalls

The literature flags several recurring failure modes for boolean-feature signature systems:

1. **Feature correlation pretending to be multi-feature confirmation.** If "aggressive accounting" and "customer concentration" co-occur in 80% of cases, requiring "both must fire" is barely stricter than requiring either. Compute the correlation matrix of features across the 32 cases; treat highly-correlated feature clusters as one feature for K-of-N counting.
2. **Missing-data ambiguity.** If a feature is "unknown" (not absent), boolean logic treats it as "false" by default → biases toward FN. Need explicit handling: "missing data" should propagate as warning, not as silent negative.
3. **Threshold cliff effects.** A feature like "EBITDA-FCF gap >40%" has a sharp threshold; cases at 39.5% don't trigger but are nearly identical to cases at 40.5%. Use **fuzzy thresholds** (membership functions) or **per-feature confidence scores** instead of hard booleans.
4. **Survivorship bias in the 32.** The 32 are cases that failed loudly. Cases that failed quietly, or that "almost failed but pivoted," are systematically absent. Calibration based purely on the 32 will under-represent the latter category.

### E.4 Recommendations (ranked)

**Top 3 immediate actions:**

1. **Build the canaries set.** Pick 3-5 historical failures that are absolutely unambiguous (Enron, Theranos, Wirecard, Luckin, plus one more). They go in `tests/canaries/` separate from the 32 signature DB. Every signature-DB calibration cycle must produce a TP on every canary. This is the "EICAR test" for our pipeline.
2. **Build the known-good set.** Pick 8-15 historical successful multi-baggers at conditions superficially similar to failure cases (high valuation, skepticism, capital-intensive, etc.). They must NOT trigger kill-criteria. FP rate on this set is the headline calibration metric.
3. **Build the warning-list table.** Enumerate features that look like kill-criterion hits but are systematically benign in specific contexts (e.g., "negative FCF in years 1-3 of a hyper-growth platform business" is benign; "negative FCF in year 8 of a mature distributor" is malign).

**Medium-term (Q5-Q7 phase):**

4. **Adopt STIX-like indicator schema** for signature objects: pattern, confidence, valid_from, valid_until, references. JSON-serializable, version-controlled.
5. **Build sightings log.** Every PM override of a signature match becomes a sighting record. Aggregate quarterly to recalibrate signature confidence scores.
6. **Define decay schedule.** Per-signature retirement criteria — at minimum, an annual full review.

**Long-term (post-v1.0):**

7. **Two-stage architecture is already there.** Mechanical signature-DB scoring as Tier 1 (high-recall), LLM/PM judgment as Tier 2 (high-precision). This is exactly the YARA-loose + ML-classifier-strict pattern, and exactly the SOC Tier-1/Tier-2 model. Don't break it.
8. **Multi-engine consensus, if budget allows.** If we ever run multiple variant scorers (e.g., signature-DB match, LLM rubric, ensemble), apply VirusTotal-style weighted consensus, accounting for non-independence across scorers.

### E.5 Common failure modes (what to monitor for)

From the threat-intel literature, these are the recurring ways signature systems break:

| Failure mode | Security analog | Translation to us |
|---|---|---|
| **Signature drift** | IOCs go stale | Kill-criteria features lose discriminatory power as regime shifts |
| **Overfitting to training corpus** | YARA rule that only matches training samples | Signature DB that catches only cases very similar to the 32 |
| **Alert fatigue → ignored alerts** | SOC under-triages | PM over-rides signature alerts wholesale → mechanism becomes vestigial |
| **Missed-threat tradeoff** | Tightening for FP creates blind spots | Tightening kill-criteria filters causes FN on next-generation failures |
| **Shared-engine fake-consensus** | Multiple AVs share backend | Multiple kill-criteria sourced from same paper/framework give illusion of independence |
| **Survivorship-biased training** | Training only on caught threats | 32 cases are loud failures — quiet failures are missing |
| **Threshold cliff** | Hard cutoffs miss near-miss cases | Hard feature thresholds miss cases just below threshold |
| **Missing-data treated as negative** | NULL-handling bug | "Unknown" feature value silently treated as "feature absent" |

Build monitoring/dashboards for the top 4 (drift, overfit, fatigue, FN). The bottom 4 are design-time concerns — handle in architecture review, not in production monitoring.

---

## Appendix — Quick-reference mapping table

| Our concept | Security analog | Reference source |
|---|---|---|
| Signature DB of 32 cases | MISP IOC database | MISP best-practices doc |
| Kill-criterion signature | YARA rule | Neo23x0 style guide |
| Feature in a signature | YARA string | YARA performance guidelines |
| Feature exoneration | YARA `$fp*` strings | Neo23x0 style guide |
| Mechanical match → PM review | Tier 1 → Tier 2 SOC | Exaforce Tier 1 guide |
| Match score | IOC quality score (0-1) | UvA OS3 scoring paper |
| Known-benign collision list | MISP warning list | misp-warninglists |
| PM decision feedback | MISP sightings | MISP best-practices |
| Signature retirement | IOC decay model | MISP decay paper |
| Canaries (must always fire) | EICAR | EICAR.org |
| Known-good test set | DARPA benign baseline | DARPA TC E3 README |
| Held-out evaluation | DARPA live-detection phase | DARPA TC E3 README |
| Multiple-scorer consensus | VirusTotal aggregation | VirusTotal docs |
| Hierarchical signatures | MITRE ATT&CK technique → sub-technique | attack.mitre.org |
| Hypothesis-driven analysis | Threat hunting (PEAK) | Splunk PEAK blog |

---

## Notes on confidence / limitations of this research

- **Direct domain transfer is not 1:1.** Security signatures match on file/network bytes; ours match on company features. The data primitive is different. The *system architecture* patterns transfer; the specific calibration thresholds (e.g., "consensus at 90%") do NOT transfer numerically.
- **All sources accessed via web search.** No primary source code review of MISP/YARA/Suricata internals was performed in this research session. Recommendations B.4 and E.1 are at the architecture-pattern level, not the code-port level.
- **Sample-size rigor caveat.** At N=32, no calibration approach (security-derived or otherwise) will give tight error bars. The recommendations in E.2 explicitly account for this.
- **The "MISP pattern is closest" claim is a judgment call.** Other reasonable choices: Snort thresholding (if we wanted per-rule alert volume management) or Cuckoo composite-scoring (if we wanted to combine multiple weak signatures into a composite score). MISP wins on closest data-primitive match.
