# Medical CBR / clinical decision support calibration patterns

**Research scope:** how medical case-based reasoning (CBR) systems and clinical decision support (CDS) calibrate "similar past patient/case" retrieval against curated case databases. Investigated as analog for our 32-case scenario catalog.

**Date:** 2026-04-29
**Owner:** Q6 / Section 5 deep-dive (medical-CBR analog)

---

## Section A — Curated sources (tier-labeled)

### Tier 1 — Foundational & academic CBR systems
1. **CARE-PARTNER (Bichindaritz, 1998–2003)** — case-based reasoning for stem-cell transplant follow-up. Multimodal reasoning combining CBR + rule-based reasoning + information retrieval; standardized terminology via UMLS Semantic Network; reported 82.2% compliance vs. evidence-based standards across 163 case interactions.
   - Source: <https://link.springer.com/chapter/10.1007/BFb0056345>
2. **CASEY (Koton, MIT 1988)** — earliest medical CBR system; heart-failure diagnosis. Two-step indexing (causal-state primary index → observed-feature secondary), with rule-based fallback when no similar case retrieved. Pioneering quote: *"A physician's problem-solving performance improves with experience. The performance of most medical expert systems does not."*
   - Source: <https://folk.idi.ntnu.no/agnar/publications/medical-cbrws.pdf>
3. **A Survey on Case-based Reasoning in Medicine** (Begum et al.) — comprehensive review of medical CBR adaptation problem.
   - Source: <https://pdfs.semanticscholar.org/4425/f40c1fadb0cfd043630e7d12802287a65625.pdf>
4. **Medical CBR Frameworks: Current Developments and Future Directions** (IGI Global) — 2016 survey covering iSearch, pCare, multi-agent CBR.
   - Source: <https://www.researchgate.net/publication/305451325>
5. **Synergistic CBR in medical domains** (Expert Systems w/ Apps, 2013) — hybrid CBR + rule-based + ontology integration patterns.
   - Source: <https://www.sciencedirect.com/science/article/abs/pii/S0957417413003618>

### Tier 1 — Disease classification + structured similarity
6. **ICD-10 / MS-DRG (CMS)** — Diagnosis-Related Groups grouper assigns patients to clinically + resource-similar classes via ICD-10 codes, procedures, age, sex, discharge status, comorbidities. Structured-feature similarity at scale (every US Medicare admission).
   - Source: <https://www.cms.gov/icd10m/version37-fullcode-cms/fullcode_cms/Design_and_development_of_the_Diagnosis_Related_Group_(DRGs).pdf>
7. **SNOMED CT Clinical Decision Support Guide** — concept hierarchies + Boolean logic for CDS rule firing; "primary" / "extended" / "value-set" methods for phenotype definition.
   - Source: <https://docs.snomed.org/snomed-ct-practical-guides/snomed-ct-clinical-decision-support-guide/1-introduction/1.1-overview>
8. **JMIR Medical Informatics — SNOMED CT Concept Hierarchies for Computable Phenotypes** (2019) — comparison of intensional vs. extensional value sets for similarity-based cohort identification.
   - Source: <https://medinform.jmir.org/2019/1/e11487/>
9. **OMIM (Online Mendelian Inheritance in Man)** — curated reference DB; 15,000+ genes, Phenotypic Series feature aggregates "identical or similar phenotypes across the genome." UMLS + Human Phenotype Ontology integration.
   - Source: <https://www.omim.org/>
10. **OMIM.org methodology paper** (Hamosh et al., NAR 2015) — MIMmatch outreach for collaborative phenotype matching.
    - Source: <https://academic.oup.com/nar/article/43/D1/D789/2439148>

### Tier 1 — Modern CDS infrastructure
11. **CDS Hooks (HL7 v2.0.1)** — open-source spec for embedding near-real-time CDS in EHR workflow; uses FHIR for patient state.
    - Source: <https://cds-hooks.hl7.org/>
12. **Epic Cosmos** — 300M+ patient records across 1,600+ hospitals; "Best Care Choices for My Patient" (treatment-response similarity) and "Look-Alikes" (peer-provider matching by symptom constellation). Cosmos AI (115B medical events) for trajectory prediction.
    - Source: <https://cosmos.epic.com/>
13. **Epic "Best Care" CDS pilot announcement** — real-world data from Cosmos as similarity engine for point-of-care decisions.
    - Source: <https://www.epic.com/epic/post/best-care-will-use-real-world-data-from-cosmos-for-clinical-decision-support/>

### Tier 1 — FDA / regulatory
14. **FDA Good Machine Learning Practice (GMLP) — 10 Guiding Principles** (FDA + Health Canada + MHRA, 2021).
    - Source: <https://www.fda.gov/medical-devices/software-medical-device-samd/good-machine-learning-practice-medical-device-development-guiding-principles>
15. **FDA AI/ML Action Plan (Jan 2021, finalized Dec 2024)** — five initiatives incl. predetermined change-control plans (PCCPs) for self-learning models.
    - Source: <https://www.fda.gov/news-events/press-announcements/fda-releases-artificial-intelligencemachine-learning-action-plan>
16. **FDA Software as a Medical Device (SaMD) framework** — IMDRF four-tier risk categorization (I–IV) + three-pillar clinical evaluation.
    - Source: <https://www.fda.gov/medical-devices/digital-health-center-excellence/software-medical-device-samd>
17. **Transparency for Machine Learning-Enabled Medical Devices: Guiding Principles** (FDA, June 2024).
    - Source: <https://www.fda.gov/medical-devices/software-medical-device-samd/transparency-machine-learning-enabled-medical-devices-guiding-principles>

### Tier 1 — Test sets and benchmarks
18. **MIMIC-III / MIMIC-IV (PhysioNet)** — ~60k ICU admissions BIDMC 2001–2012; relational schema (26 tables); demographics + vitals + labs + procedures + meds + notes + mortality. Gold-standard de-identified clinical dataset; HIPAA-bound DUA.
    - Sources: <https://physionet.org/content/mimiciii/1.4/>, <https://www.nature.com/articles/s41597-022-01899-x>
19. **HealthBench (OpenAI, 2025)** — 5,000 realistic health conversations; 48,562 rubric criteria authored by 262 physicians from 60 countries; rubric-graded open-ended evaluation. HealthBench Hard top score still 32% (April 2025).
    - Source: <https://openai.com/index/healthbench/> | Paper: <https://arxiv.org/abs/2505.08775>
20. **Med-PaLM / Med-PaLM 2 (Google/DeepMind)** — MultiMedQA benchmark (7 datasets); training-data-overlap audit (≥512 contiguous chars or full-question match flagged); 9-axis pairwise physician preference rubric.
    - Sources: <https://sites.research.google/gr/med-palm/>, <https://www.nature.com/articles/s41591-024-03423-7>

### Tier 1 — Failure modes & bias
21. **Obermeyer, Powers, Vogeli, Mullainathan (Science 2019)** — "Dissecting racial bias in an algorithm used to manage the health of populations." Algorithm targeted *cost* as proxy for *need*; at given risk score, Black patients sicker than White by measured illness signs. Adjusting target reduced bias by 84%; lifted Black patients receiving extra help from 17.7% to 46.5%.
    - Source: <https://www.science.org/doi/10.1126/science.aax2342>
22. **STAT News exposé on Watson for Oncology (Ross & Swetlitz, July 2018)** — internal IBM documents flagged "unsafe and incorrect" recommendations.
    - Source: <https://www.statnews.com/2018/07/25/ibm-watson-recommended-unsafe-incorrect-treatments/>
23. **Concordance Study: Watson for Oncology vs. Real Practice in China** (PMC 6656482) — only ~30% match with local best practice; ~30% somewhat similar; ~30% completely different.
    - Source: <https://pmc.ncbi.nlm.nih.gov/articles/PMC6656482/>
24. **Henrico Dolfing case study — $4 Billion Watson failure** — synthesis of root causes.
    - Source: <https://www.henricodolfing.com/2024/12/case-study-ibm-watson-for-oncology-failure.html>

### Tier 1 — Calibration methodology
25. **Steyerberg, "Towards better clinical prediction models: seven steps for development and ABCD for validation"** (Eur Heart J 2014) — A: calibration-in-the-large (intercept α); B: calibration slope (β); C: discrimination (C-statistic); D: clinical usefulness (decision-curve analysis).
    - Source: <https://academic.oup.com/eurheartj/article/35/29/1925/2293109>
26. **"Validation of clinical prediction models: what does the calibration slope really measure?"** (J Clin Epidemiol 2019) — formal treatment of slope as miscalibration / overfitting indicator.
    - Source: <https://www.jclinepi.com/article/S0895-4356(19)30357-9/fulltext>
27. **"Distribution shift detection for postmarket surveillance of medical AI algorithms"** (npj Digital Medicine 2024) — retrospective simulation of monitoring infrastructure.
    - Source: <https://www.nature.com/articles/s41746-024-01085-w>
28. **Cross-population domain shift in chest X-ray classification** (Sci Reports 2025) — performance degrades 10–25% on unseen populations; framework separates prevalence shift / covariate shift / mixed shift.
    - Source: <https://www.nature.com/articles/s41598-025-95390-3>

### Tier 2 — LLM-augmented clinical
29. **Frontiers in AI — Validated evaluation of LLM ambient scribe (PDQI-9 framework, 2025)** — comparable quality to physician notes; Ambient more thorough but less succinct + more hallucination-prone.
    - Source: <https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2025.1691499/full>

---

## Section B — CBR calibration methodology

### B.1 Structured-feature similarity (ICD/SNOMED-style)

Medical CBR overwhelmingly uses **structured ontologies** rather than free-text embedding for the *primary* similarity index. Three layers:

1. **Disease classification (ICD-10 / MS-DRG)** — every Medicare claim in the US passes through a DRG grouper that assigns a patient to a *clinically + resource-intensity-similar* peer class using diagnosis codes, procedures, demographics, comorbidities, complications, and discharge status. The grouper is deterministic and auditable. (CMS DRG manual)
2. **Concept-hierarchy similarity (SNOMED CT)** — Description-Logic reasoners infer that "asthma subtype X" is-a "asthma" and therefore should fire any rule keyed off "asthma." Similarity is *taxonomic distance + co-occurrence*, not raw embedding cosine. JMIR 2019 documented three formal methods: primary concept + descendants ("primary"), + relations ("extended"), and text-search ("value set").
3. **Phenotype matching (OMIM / HPO)** — for rare disease, retrieval keys off Human Phenotype Ontology terms; OMIM's "Phenotypic Series" is an explicit similarity cluster across genes.

**Hybrid layer:** modern systems (CARE-PARTNER, Synergistic CBR) wrap ontology-based retrieval with rule-based reasoning fallback when no near-neighbor case is found, *and* with information-retrieval over free-text notes for context. CASEY's two-step indexing (causal-state primary, observed-feature secondary) is the canonical pattern.

**Calibration of similarity itself:**
- CARE-PARTNER reports *compliance with evidence-based standards* (82.2% over 163 cases) as the calibration metric — not raw retrieval accuracy.
- Steyerberg's framework formalizes: calibration-in-the-large (α), calibration slope (β), discrimination (C), and clinical usefulness (decision-curve analysis). These four are now standard for any clinical prediction model going to deployment.

### B.2 Test-set design (MIMIC + similar)

**MIMIC family** (Beth Israel Deaconess, Boston):
- ~60k ICU admissions, 26-table relational schema, hourly vitals + labs + procedures + meds + notes + mortality.
- Access requires HIPAA training + signed Data Use Agreement.
- Used as the de facto external test set for ICU prediction models worldwide.

**HealthBench (OpenAI, 2025)** as reference for *rubric-graded* test design:
- 5,000 realistic conversations × 48,562 physician-authored rubric criteria.
- 262 physicians from 60 countries → geographic + clinical diversity.
- HealthBench Consensus (34 critical behaviors, validated by physician panel) and HealthBench Hard (top-tier difficulty, current SOTA only 32%).

**Med-PaLM 2 contamination control:**
- Searched for ≥512 contiguous-character overlap between MultiMedQA test items and base-LLM training corpus.
- Pairwise comparative ranking by physicians on **9 clinical-utility axes** (not single accuracy score).

These test-design patterns map directly onto our problem: the gold-standard set should be (a) curator-authored, (b) graded on multi-axis rubrics, (c) audited for contamination against any LLM training corpus, and (d) split for both pre-cutoff and post-cutoff evaluation.

### B.3 Domain-shift handling

Documented pattern: **10–25% performance degradation when models are tested on unseen patient populations** (Sci Reports 2025 chest-X-ray meta-analysis).

Distribution-shift taxonomy now standard in clinical AI:
- **Temporal shift** — practice patterns drift over years.
- **Demographic shift** — race, age, SES, geography distribution differs from training.
- **Label shift** — outcome prevalence differs (e.g., COVID era).
- **Covariate shift** — input feature distribution differs.
- **Prevalence shift** — base rate of target disease differs.

Formal frameworks (npj Digital Medicine 2024) now exist for **postmarket distribution-shift detection**, treated as required infrastructure for FDA-cleared AI/ML SaMDs under the post-2024 PCCP regime.

---

## Section C — Regulatory expectations (FDA SaMD / GMLP)

### C.1 SaMD risk categorization (IMDRF/FDA)

Four categories (I–IV) on two axes:
- *Significance of information provided* (inform → drive → diagnose/treat)
- *Healthcare situation/condition* (non-serious → serious → critical)

Category IV (e.g., diagnostic AI for critical condition like cancer triage) requires the most rigorous clinical evaluation. Watson for Oncology nominally lived here; the public-facing positioning vs. actual evidence-base mismatch is part of why the failure was so reputationally severe.

### C.2 GMLP — 10 Guiding Principles (FDA + Health Canada + MHRA, 2021)

The published principles, paraphrased with calibration-relevance:

1. **Multi-disciplinary expertise across full lifecycle** — clinicians, data scientists, software engineers, ethicists *together*, not handoff-style.
2. **Good software engineering & cybersecurity practices** — version control, testing, audit logs, secure deployment.
3. **Clinical-study participants & datasets representative of intended population** — sex, age, race, ethnicity, comorbidity distribution must match deployment context. (This is what Watson missed.)
4. **Training & test data sets are independent** — no leakage. (HealthBench / Med-PaLM 2 implement.)
5. **Selected reference datasets based on best available methods** — gold-standard labels, ideally adjudicated.
6. **Model design tailored to available data + reflects intended use** — no off-the-shelf model dropped into a context it wasn't trained for.
7. **Focus on performance of the human-AI team** — calibration of *interaction*, not model alone.
8. **Testing demonstrates device performance during clinically relevant conditions** — including edge cases and stress conditions.
9. **Users provided with clear, essential information** — transparency on inputs, performance, limitations, intended use.
10. **Deployed models monitored for performance & retraining risks managed** — drift detection, recalibration triggers, controls against overfitting/bias on retrain.

### C.3 Documentation / audit-trail requirements

The Dec 2024 finalized AI/ML Action Plan requires under the Predetermined Change Control Plan (PCCP) regime:
- Description of planned modifications.
- Methodology used to implement modifications safely.
- Impact assessment on safety / effectiveness.
- Real-world performance monitoring infrastructure.

Translation to audit trail: every retraining must produce a record of *what changed, what data trained it, what performance metrics showed pre/post, what bias audits ran*.

### C.4 Bias auditing (Obermeyer 2019 lessons)

- **Target-variable audit is mandatory.** Obermeyer's algorithm targeted *cost* (proxy for need) → systematically under-allocated to Black patients because less is spent on them at given illness severity.
- **Subgroup performance reporting** — overall accuracy can hide subgroup disparities.
- **Causal review of features** — are any features (insurance type, ZIP, prior utilization) carrying socioeconomic signal that proxies for race?
- After remediation, the share of Black patients receiving extra help rose from 17.7% to 46.5% — a calibration adjustment, not an architecture change.

---

## Section D — Failure modes documented

### D.1 Watson for Oncology — the canonical CBR failure

**Root causes documented:**
1. **Synthetic training cases.** IBM trained Watson on hypothetical patients constructed by a small group of MSKCC oncologists rather than real-patient outcome data — meaning the "case base" was *expert opinion in case form*, not empirical evidence. (STAT News 2018)
2. **Local-population mismatch.** China concordance study (PMC 6656482) showed only ~30% alignment with local best practice; treatments unavailable in-region were recommended; drug-availability and guideline differences ignored.
3. **No real-time recalibration to user feedback.** Physicians couldn't easily push back on outputs and improve the system.
4. **Marketing-vs-evidence gap.** Sold as oracle, performed as opinion-aggregator.
5. **No transparency into similarity reasoning.** Opaque "Watson said X" with no breakdown of *which prior cases* drove the recommendation.
6. **Cost ~$4B with effectively zero clinical adoption** at scale.

**Lessons crystallized:**
- A case base built from hypothetical / expert-opinion cases ≠ a case base built from outcome-validated empirical cases.
- Geographic/demographic transfer requires explicit recalibration, not implicit generalization.
- Opaque retrieval reasoning ("trust me") fails in high-stakes clinical contexts.

### D.2 Domain-shift propagation

Sci Reports 2025 meta-analysis: 10–25% performance drop on unseen populations is the *typical* degradation, not the exception. This is the baseline expectation absent explicit recalibration infrastructure.

### D.3 Bias propagation

Obermeyer 2019: an algorithm trained on *cost* as label silently encoded racial care disparities. Bias is a *target-variable* problem at least as much as a feature problem. The fix was redefining the prediction target, not adding more features.

### D.4 Hallucination in LLM-augmented clinical (Frontiers AI 2025, Abridge/Suki reviews)

Even at high baseline accuracy (matching physician notes), LLM clinical scribes show:
- **Stylistic hallucinations** that look correct but are fabricated.
- **Omitted negatives** — failure to record "patient denies X."
- **Misattributed statements** — patient quote attributed to family or clinician.
- These require structured PDQI-9-style multi-axis review, not single-score evaluation.

---

## Section E — Lessons applicable to our case

### E.1 32-case catalog calibration

Direct mappings from medical CBR to our scenario catalog:

| Medical CBR practice | Our system equivalent |
|---|---|
| ICD/DRG structured grouping deterministic + auditable | Mechanical-feature scoring deterministic + auditable; LLM rubric layered on top, never replacing |
| CARE-PARTNER's 82.2% compliance vs. evidence-based standards | Track our %-of-cases-where-system-output-aligns-with-curator-judgment as primary metric |
| CASEY two-step indexing: primary causal-state index + secondary observed-feature index | Two-stage retrieval: primary mechanical features (regime, sector, leverage), secondary embedding similarity over scenario narrative |
| OMIM Phenotypic Series — explicit clusters of "identical or similar" phenotypes | Curator-authored case clusters; multiple cases retrievable as a "scenario family" not just nearest single case |
| Steyerberg ABCD: intercept (α), slope (β), discrimination (C), clinical usefulness (D) | Track all four for any predictive layer; calibration slope tells overfitting; intercept tells systematic bias; decision-curve tells whether using-the-system-beats-not-using-it |
| HealthBench rubric: 48k physician-authored criteria, multi-axis | Curator-authored rubric for each scenario at multi-axis level (not single conviction score) |

**Contamination control specifically:** Med-PaLM 2 used ≥512-character contiguous overlap as flag. We should adopt similar contamination-check rigor for our LLM-rubric layer against any case in the curated 32 that postdates LLM training cutoff.

### E.2 Asymmetric cost handling (missed multi-bagger vs. false alarm)

Medical literature is explicit on this point: in conditions where **missing a case is catastrophic** (cancer, MI, sepsis), calibration is deliberately tilted toward **sensitivity at the cost of specificity** — accepting false alarms to never miss a true case. This is implemented via:
- Cost-sensitive learning (weight false-negatives higher in loss).
- Lower decision thresholds for high-stakes positive class.
- Explicit acknowledgement that downstream alarm fatigue is a design tradeoff to manage separately.

**Translation to our case:** if a missed multi-bagger is far more costly than a false alarm (which it likely is for a long-only equity research system over a multi-year horizon, given asymmetric upside), our calibration should:
- Bias retrieval threshold toward inclusion (more candidates flagged for human review).
- Use Steyerberg-style calibration slope to monitor whether the system is over- or under-confident at the high-conviction tail.
- Explicitly track false-negative rate (multi-baggers missed) as a primary KPI, not just precision.
- Build downstream filters (e.g., bear-case + PM supervisor) to handle the high-recall/lower-precision upstream — analogous to how clinical workflow handles high-sensitivity screening tests with confirmatory specific tests.

The structural pattern from medicine: **screening (high sensitivity) → confirmatory (high specificity) → action**. Our research-company → bear-case → PM-supervisor pipeline already approximates this; the medical literature confirms it as the sound calibration architecture for asymmetric-cost domains.

### E.3 Audit trail expectations adaptable from FDA GMLP

Adopt these GMLP principles directly into our system documentation:

- **Principle 3 → Representativeness:** the 32-case catalog must explicitly cover the regime/sector/cap/leverage matrix we expect to deploy against. If we deploy on small-cap healthcare and the catalog is 80% large-cap tech, we have a Watson-in-China problem coming.
- **Principle 4 → Train/test independence:** scenarios used for catalog construction must not double as held-out evaluation. Our checkpoint test sets must be curator-fresh.
- **Principle 7 → Human-AI team performance:** the calibration metric is not "system gets right answer alone" but "system + analyst gets better answer than analyst alone." Evaluate the team, not the model.
- **Principle 9 → Transparency:** for every recommendation, we must surface *which retrieved cases* drove it, *what mechanical features matched*, *what the rubric scored*, and *what the bear case raised*. Watson's opacity was a major failure mode.
- **Principle 10 → Postmarket monitoring:** distribution-shift detection (regime change, sector rotation, vol regime change) must trigger recalibration. The npj Digital Medicine 2024 framework is a direct template.

### E.4 Watson lessons — explicit don'ts

- **Don't build the catalog from synthetic / hypothetical scenarios written by an "expert."** Build from outcome-validated historical cases (the L3-successful-companies approach is correct on this front).
- **Don't ship without explicit recalibration when deploying into a new regime/sector.** Treat it like Watson going from MSKCC to China — explicit revalidation, not implicit transfer.
- **Don't market the system as oracle.** Position as decision-support; surface uncertainty; require human override pathway.
- **Don't ignore opacity.** Every retrieval must be inspectable: which cases, why, what features matched.

### E.5 Cost-asymmetry approach (concrete proposal)

Adopting medical CBR + Steyerberg framework:

1. **Define cost matrix explicitly:** C_FN (cost of missing a multi-bagger) vs. C_FP (cost of false alarm requiring deeper-dive labor). Best-guess: C_FN/C_FP ≥ 10× given long-only multi-bagger asymmetry.
2. **Calibrate retrieval threshold to that ratio**, not to balanced accuracy.
3. **Track Steyerberg ABCD on conviction-score → realized-return:**
   - α (intercept): is the system systematically over- or under-confident?
   - β (slope): does conviction differentiate winners from losers monotonically?
   - C (discrimination): rank-order accuracy.
   - D (decision-curve): does following the system's recommendations beat a passive policy?
4. **Postmarket monitor distribution shift** on regime/sector/macro features. Trigger recalibration when shift detected.
5. **Bias audit on target variable:** are we predicting *return* or *attention/news-coverage* or *liquidity-friendliness* (the equity equivalent of Obermeyer's cost-as-proxy-for-need)? Audit explicitly.

---

## Reporting summary

- **(a) Deliverable path:** `/Users/sehoonbyun/Documents/equity-research-system/.claude/references/empirical/data-sources/Q6-Section5-medical-cbr.md`
- **(b) Most-applicable medical-CBR pattern:** **CASEY-style two-step indexing + CARE-PARTNER-style multimodal retrieval.** Primary index on hard mechanical features (regime, sector, leverage, valuation regime); secondary index on narrative similarity. Rule-based fallback (kill criteria) when no near-neighbor case is found. Compliance-with-curator-judgment (CARE-PARTNER's 82.2%) as the primary calibration metric.
- **(c) Watson for Oncology lessons:** (i) synthetic / expert-opinion case base ≠ outcome-validated empirical case base; (ii) geographic/demographic transfer requires explicit recalibration; (iii) opacity in retrieval reasoning is fatal in high-stakes domains; (iv) marketing-vs-evidence gap destroys credibility; (v) ~$4B spent with near-zero adoption when calibration is wrong.
- **(d) FDA GMLP principles relevant to our audit trail:** P3 (representative data), P4 (train/test independence), P7 (human-AI team performance), P9 (transparency), P10 (postmarket monitoring + retrain risk management). All five are directly adoptable as documentation-checklist items for v0.5+.
- **(e) Cost-asymmetry approach:** medical literature supports tilting calibration toward sensitivity in high-FN-cost domains via cost-sensitive thresholds + screening→confirmatory pipeline architecture. Concrete proposal: C_FN/C_FP ≥ 10× explicit cost matrix; lower retrieval threshold; track FN rate (missed multi-baggers) as primary KPI; rely on bear-case + PM-supervisor downstream filters for specificity recovery (analogous to clinical screening → confirmatory test workflow).
