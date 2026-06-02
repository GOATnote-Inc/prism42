# MedOmni v2 — corrected architecture after user feedback

**Date**: 2026-04-29 (afternoon).
**Trigger**: user (Brandon Dent, MD) corrected three things in the v0 brief that needed substantial re-architecting:
1. The nurse persona was framed too shallow (as "L1 + family register"). Reality: nurses operate at physician-knowledge depth or deeper, are the operational backbone of evidence-based medicine in the hospital, teach new residents, and instruct families.
2. I was underestimating OpenEvidence's strategy and their NVIDIA partnership. Honest competitive analysis required, not "we beat them at L2-3."
3. A specific clinical test case is the v0 acceptance gate: tamoxifen + Mirena IUD + familial breast cancer risk + nulliparity. Documented separately at `tamoxifen-mirena-test-fixture.md` (lands when research agent 4 returns).
**Disposition**: this doc supersedes v1's persona framing (§3) and adds a strategic positioning section that v1 lacked. v1's three-GPU role allocation, NemoClaw correction, retrieval pipeline, and foot-gun catalog still stand.
**Verification posture**: every concrete claim traces to a URL the parallel research agents cited. Karpathy/Glasswing audits taught us that under-claim beats over-claim and that the user catches flattery.

## 1. The strategic question: where does GOATnote actually win?

Per the parallel competitive-analysis agent, OpenEvidence is at:
- $12 B valuation ([CNBC, Jan 2026](https://www.cnbc.com/2026/01/21/openevidence-chatgpt-for-doctors-doubles-valuation-to-12-billion.html))
- $100 M ARR
- ~757 K active clinicians, 18 M consultations/month, 40% of US physicians as daily users
- Backed by Sequoia, NVIDIA, Mayo Clinic, Kleiner Perkins, Blackstone
- Uses NVIDIA Nemotron for their DeepConsult agent ([NVIDIA blog post on Nemotron-3-Nano-Omni explicitly names OpenEvidence as a customer](https://developer.nvidia.com/blog/nvidia-nemotron-3-nano-omni-powers-multimodal-agent-reasoning-in-a-single-efficient-open-model/))

**NVIDIA's partnership with OpenEvidence is not exclusive.** NVIDIA also partners with [Hippocratic AI, Mayo Clinic, Verily, GE HealthCare, Microsoft, Abridge](https://nvidianews.nvidia.com/news/nvidia-partners-with-industry-leaders-to-advance-genomics-drug-discovery-and-healthcare). Portfolio hedging, not a moat for either side.

**OpenEvidence's documented weaknesses** (cited, not invented):
- 34% accuracy on complex multifactorial scenarios ([medRxiv pilot, Nov 2025](https://www.medrxiv.org/content/10.64898/2025.11.29.25341091v1)) vs 100% on USMLE single-pick MCQ — the gap widens with multifactorial decision-making, which is exactly the regime MedOmni's tamoxifen test case exercises.
- "Cannot effectively integrate past medical history, physical exam, ROS" ([clinical review](https://www.iatrox.com/blog/openevidence-review-uk-clinicians-alternatives))
- US-centric corpus; cites AHA/FDA recommendations not aligned with NICE / BNF
- Recommends treatments dropped per current NICE guidelines (corpus lag or synthesis error)
- Search opacity — clinicians cannot target specific articles, authors, journals
- 44% of physicians cite accuracy/misinformation risk; 19% lack of explainability; 16% liability concerns

**Where GOATnote cannot compete head-on**: corpus breadth. OE has 35M+ peer-reviewed papers, NEJM/JAMA/NCCN/Cochrane/Wiley licensing, $700M raised. Corpus-size is not where to fight.

**Where GOATnote can credibly win** (per the agent's 9-axis matrix):
- **Emergency-medicine depth** — OpenEM 370 EM conditions + EM-specific workflows beat OE's general coverage in that specialty. "OpenEvidence + Mayo will own the general tower. You own the EM spire."
- **Multi-persona register** — OE is physician-only by design. Nurse + family + patient is a "more users" play, literally.
- **Reproducibility + audit-trail** — opacity is OE's documented weakness; reproducibility-first is prism42's stated north star.
- **Sovereignty / on-prem** — OE is SaaS only. VA, hospitals with strict-HIPAA / data-residency requirements are unserved.
- **Voice + multimodal** — OE is text-first. Omni's vision/audio + the prism42 PSAP voice work is a wedge.

**The blunt verdict**: pick **one** differentiation strategy, execute deeply, pilot with EM residency + academic hospital. Do not chase OE on corpus or general-medicine users.

Three buildable v0 wedges (the agent's framing):

| Strategy | v0 wedge | Early users |
|---|---|---|
| **Multi-persona teaching register** | Nurse asks corpus question; MedOmni returns answer shaped for teaching a family member at the bedside (analogies, plain language, decision tree). | Nursing residency programs; family-centered EDs; post-ED follow-up telemedicine |
| **Sovereignty + reproducibility** | Every answer ships with patient-scenario-ID, corpus-version date, model-version, exact sources in rank order, confidence score, query timestamp. Export to EPIC for chart. | VA hospital system; large academic EDs with IR/data-governance teams; hospitals blocked on cloud |
| **Voice-first + procedure walkthroughs** | "I'm intubating a hypoxic patient on BiPAP" → MedOmni voice returns sequence + ultrasound landmark images. Logs voice query for med-legal audit. Hands-free ED. | EM residency simulation labs; rural/small EDs; mass-casualty triage |

These are not mutually exclusive on the technical layer — the same MedOmni stack supports all three at different surfaces — but the **go-to-market** focus should be one. Recommendation in §7.

## 2. Three-GPU role allocation (unchanged from v1)

| GPU | Role | Stack |
|---|---|---|
| **RunPod H100** | dev-expert orchestrator + Llama-Guard-3-8B safety rails | Claude Code (headless) or OpenClaw direct |
| **Brev H200** | MedOmni inference + retrieval brain | Nemotron-3-Nano-Omni-30B-A3B-Reasoning-NVFP4 + NV-Embed-v2 (or Omni-Embed-Nemotron-3B for multimodal) + Llama-Nemotron-Rerank-VL + nx-cugraph in-VRAM medical KG |
| **Brev H100** | voice gateway (existing) | parakeet STT + LiveKit + Redis (UNCHANGED) |

NemoClaw correction from v1 stands: NemoClaw is NVIDIA's [alpha sandbox lifecycle manager](https://docs.nvidia.com/nemoclaw/latest/index.html) for OpenClaw agents — single-node, designed for unprivileged-agent isolation. Not a multi-pod orchestrator. The dev-expert role uses Claude Code (headless) or OpenClaw direct.

## 3. The four-persona architecture — corrected

**Old framing (v1, wrong)**: physician (L1) → nurse (L1+L2) → family (L2+L3) → patient (L3). Nurse cast as "physician knowledge plus communication."

**New framing (v2, evidence-based per the parallel research agent)**: nurses are not "physician + comms"; they are a distinct expert layer with three irreducible roles:

| Persona | Role | Distinct expertise |
|---|---|---|
| **Physician** | Diagnostic + treatment decision-making | Textbook + recent literature; weighted toward the new attending and resident reality. Junior physicians underweight tacit/contextual knowledge. |
| **Nurse** | Clinical anchor + EBM operationalizer + family-and-resident teacher | (a) Subtle-deterioration recognition: NIPDS scale (Nurse Intuition Patient Deterioration Scale, [Sciencedirect](https://www.sciencedirect.com/science/article/abs/pii/S0020748923000329)) + NEWS2 predicts code/ICU/death within 24h before vital-sign change; (b) Magnet-hospital EBP committees translate research into bedside protocols ([PMC10229039](https://pmc.ncbi.nlm.nih.gov/articles/PMC10229039/)); (c) Specialty certs (CCRN, CEN, CNRN) require continuing EBM education as Category A ([AACN CCRN](https://www.aacn.org/certification/get-certified/ccrn-adult)); (d) Nurse preceptors formally teach residents — One-Minute Preceptor model ([MedEdPORTAL](https://www.mededportal.org/doi/10.15766/mep_2374-8265.10718)). |
| **Family member** | Receives the explanation that drives adherence and rescue | The nurse's voice in the family discussion is the family's primary clinical interpreter ([PMC11151341](https://pmc.ncbi.nlm.nih.gov/articles/PMC11151341/)). Teach-back from nurses reduced 30-day readmissions 45% ([BMC Nursing](https://bmcnurs.biomedcentral.com/articles/10.1186/s12912-021-00622-2)). |
| **Patient** | Self-management, adherence, when-to-call-911 | Lay register, ≤grade-6 readability ([NIH/AMA standard](https://pmc.ncbi.nlm.nih.gov/articles/PMC4139691/)) |

**The literature gap**: only 6% of 67 medical KG studies addressed nursing-specific applications ([Medical KG Review, JMIR AI 2025](https://ai.jmir.org/2025/1/e58670/)). MedOmni's nurse persona — modeled on the experienced clinical-educator nurse, not the assistant-style nurse — is genuinely under-served research territory. Hippocratic AI's nurse co-pilot is a "task automaton, not clinical-educator persona" per the agent.

### Graph schema additions to honor the nurse persona (not just nurse register)

Five concrete schema additions per the parallel agent's research:

1. **Subtle-signal nodes** — pre-vital-sign deterioration indicators (behavior change, skin turgor, mental-status shift). Edges: "precedes [complication] with X% sensitivity" weighted from NIPDS data. **This is the nurse's pattern-recognition advantage encoded.**
2. **Context-dependent protocol variants** — sepsis bundle in *this* ICU, when *this* attending is on, when census is high. Edges encode "nurse judgment to adapt protocol" with explicit deference rules. Captures the tacit hospital-specific knowledge experienced nurses teach.
3. **Pedagogical intent edges** — `teaches_via_[why|what|when|caution]` between protocols/findings and learner personas (PGY-1, MS3, family). The "teacher voice" — explaining *why*, not just *what*.
4. **Failure-to-recognize patterns** — anonymized FTR cases linked to staffing context (acuity ratio, turnover). Edges: "missed at acuity ratio >4:1." Honors the structural-safety layer Aiken/Silber documented (each additional patient/nurse = 7% mortality increase).
5. **Evidence-currency nodes** — date of latest guideline review, certifying body, deviation frequency in the hospital's EHR. Nurses use this to challenge outdated orders. AI surfaces it proactively: "this order may not align with [guideline update, date]."

**This is what "two levels deeper than OpenEvidence" actually looks like architecturally.** OE encodes physician-facing literature-synthesis. MedOmni encodes the nurse layer's intuitive-judgment + EBM-operational + pedagogical-deference dimensions, none of which are in OE's published feature surface.

## 4. The 2026 medical-corpus integration recipe

Per the parallel SOTA-corpus agent. **OpenEM 370 is Layer 0 (ground truth), not the whole corpus.** Layered integration:

| Layer | Source | License | Role |
|---|---|---|---|
| **L0** | OpenEM 370 EM conditions (GOATnote) | Apache-2.0 / CC-BY tier1 | physician-curated EM ground truth; one node per condition, mapped to ICD-10 + SNOMED (when UTS-licensed) + MeSH |
| **L1** | PubMed Central OA | CC-BY family | clinical evidence; ~209K articles in PubMed-OCR, 18M images in Open-PMC-18M ([cited](https://arxiv.org/abs/2601.11425)) |
| **L1** | Cochrane Reviews | partner license (Wiley→OE) | systematic-review backbone; access via partner agreement or summary citation |
| **L1** | NCCN / ACEP / ACOG / NICE / NCCN | proprietary, varies | normative guidelines; subset open, subset OE-licensed |
| **L2** | OpenFDA drug labels + adverse events | public domain | drug safety, recalls; real-time API |
| **L2** | RxNorm | NLM, public domain | drug normalization; weekly updates |
| **L2** | LOINC | free with registration | lab codes; biannual |
| **L2** | DailyMed (FDA SPL) | public domain | drug labeling |
| **L3** | ClinVar (genetic variants) | public domain | when relevant (BRCA, etc.) |
| **L3** | ClinicalTrials.gov | public domain | trial registry |

**Status of StatPearls**: CC-BY-NC-ND. **Cannot redistribute.** Citation-only — link to NCBI, do not include passages in the graph.

**Federated vs unified**: federated retrieval (NeMo Retriever microservices, real-time API per source) wins when data is siloed (EHRs, partner networks). Unified graph (single ingest into nx-cugraph) wins when transitive reasoning is required (e.g., "what drugs interact with comorbidities in EM patients with X?"). MedOmni uses **unified for L0+L2 (high reasoning value) + federated for L1 (volume + license complexity)**.

**Embedding model**: NV-Embed-v2 is a strong general default. Medical-tuned alternatives ([MedEmbed](https://huggingface.co/blog/abhinand/medembed-finetuned-embedding-models-for-medical-ir), 51-task medical IR benchmark) are worth A/B-ing once v0 ships. For multimodal (images, audio): [Omni-Embed-Nemotron-3B](https://huggingface.co/nvidia/omni-embed-nemotron-3b) is the NVIDIA-native multimodal embedder.

**MDS-ED benchmark** ([arXiv 2407.17856](https://arxiv.org/html/2407.17856v3)) — 630 EM conditions, AUROC > 0.8 baseline. This is the EM-specific eval target alongside HealthBench Hard.

## 5. Technical commitments (locked from user)

- **nx-cugraph for GraphRAG** ✓ (per yesterday's reversal + today's confirmation)
- **CUDA 13.2** ✓ (matches the prism42 future-stack brief; required for NVFP4 on certain Hopper paths and Blackwell)
- **Fine-tune** ✓ — moves R3 (PEFT LoRA on Omni) from "deferred" to "planned." Order:
  - v1 (this week): persona-tagged GraphRAG + Llama-Guard-3 rails — no fine-tune yet
  - v1.5: EASY-EP expert pruning ([arXiv 2504.06792](https://arxiv.org/html/2504.06792)) on a 10-20 sample medical calibration set; identifies the top 32-64 medically-active experts of Omni's 128
  - v2: PEFT LoRA on the Omni router (frozen experts) per [Med-MoE](https://arxiv.org/html/2404.10237v2). Targets nurse-persona register (the gap OE doesn't address). Training data: real nurse-to-family translation pairs once usage produces them.

## 6. The acceptance test — tamoxifen + Mirena + familial-risk + nulliparity

Pinned as the v0 gate per the user. The patient asks "does Mirena affect my tamoxifen-chemoprevention risk-benefit?" and "how do I assess this risk?" The model must return curious + helpful + accurate every time.

**Why this test case**: it crosses pharmacology (tamoxifen = SERM with breast antagonist + endometrium agonist), drug-device interaction (Mirena's intrauterine levonorgestrel as endometrial protection), risk modeling (BRCA, Tyrer-Cuzick, IBIS, Gail), and shared-decision-making register (curiosity, not directive). Multi-factor; exactly the regime where OE's [34% on complex multifactorial scenarios](https://www.medrxiv.org/content/10.64898/2025.11.29.25341091v1) shows the gap.

**The fixture** lands at `corpus/clinical-demo/CLN-DEMO-TAMOXIFEN-MIRENA/` once research agent 4 returns. It includes:
- The clinical answer with primary-source citations (USPSTF, NCCN, ACOG, FDA label)
- The graph walk: the minimum subgraph required to answer correctly
- 6-10 rubric items (HealthBench-Hard-shaped) for automated grading

**Acceptance criterion for MedOmni v0**: the deployed system answers this fixture with rubric ≥ 0.8 across 3 trials. Below that bar, v0 is not done.

## 7. v0 ship path — recommended differentiation

Of the three differentiation strategies in §1, the **strategy 1 (multi-persona teaching) + strategy 2 (sovereignty + reproducibility) combined** is the recommended v0 — they share infrastructure (the graph + rails) and the persona work IS the audit trail. Strategy 3 (voice-first procedures) is v0.5 — it depends on the LiveKit stack already running on the Brev H100 voice mirror.

**v0 build order (this week)**:

1. Day 1–2: ship the prompt-conditional four-persona MVP on the existing R1 stack (no new graph). FKGL guardrail on family/patient outputs. Tests: tamoxifen fixture rubric.
2. Day 3–4: build the OpenEM 370 → nx-cugraph KG with persona_mask edges. Index node descriptions in cuVS. Wire the citation-grounding rail.
3. Day 5: spin up Llama-Guard-3-8B on RunPod H100 as the input/output rail. Wire the dev-expert orchestrator (Claude Code headless) for end-to-end health checks.
4. Day 6–7: A/B the persona-tagged retrieval against bare retrieval on the tamoxifen fixture + 2-3 additional EM-specific multifactorial cases (cardiac chest pain in a 58-yo with new AF on Eliquis; suicidal ideation in a postpartum patient on sertraline; pediatric DKA + new T1D family discussion).

**v1 (next week)**: layer PubMed OA + OpenFDA via federated retrieval. NeMo Retriever microservice for L1.

**v1.5 (week 3)**: EASY-EP expert pruning + router-only fine-tune.

## 8. Decisions for user (gating v0 build)

1. Confirm strategy 1 + 2 combined as v0 — or pick 1 OR 2 single-strategy.
2. Confirm OpenEM-as-L0 + PubMed-OA-as-L1 (federated) ingestion sequencing — or alternative.
3. Confirm UTS license status for SNOMED CT integration (deferred otherwise; ICD-10 + MeSH suffice for v0).
4. Confirm the tamoxifen test case as the v0 acceptance gate (or amend with additional multifactorial cases).
5. Confirm the EM-residency + academic-hospital pilot framing as the go-to-market wedge (vs broader market).

## 9. Side issues surfaced by agents

- **Mayo Clinic + NVIDIA Blackwell partnership** ([Mayo News](https://www.insideprecisionmedicine.com/topics/informatics/jpm-2025-nvidia-mayo-clinic-partner-on-ai-powered-digital-pathology/)) — pathology-focused, infrastructure not corpus. Doesn't compete with EM positioning directly but worth knowing the partnership ecosystem.
- **PMC moves to PMC Cloud Aug 2026** — bulk download FTP is being deprecated; cloud-fee model coming. Plan ingestion timing accordingly.
- **NCCN guidelines now licensed to OpenEvidence** ([Nov 2025](https://www.openevidence.com/announcements/nccn-and-openevidence-collaborate-to-bring-clinical-oncology-guidelines-to-medical-ai)) — OE's oncology depth is now exclusive in a way it wasn't. Reinforces the EM-specialty positioning (NCCN doesn't own EM guidelines; ACEP does, and ACEP is more open-license-friendly).
- **OpenEM corpus is 370 conditions, YAML frontmatter, GOATnote-curated**. The corpus is not in OpenEvidence's 35M-paper corpus. That's a real differentiator.

## Sources

Strategic / competitive:
- <https://www.cnbc.com/2026/01/21/openevidence-chatgpt-for-doctors-doubles-valuation-to-12-billion.html>
- <https://www.openevidence.com/announcements/openevidence-the-fastest-growing-application-for-physicians-in-history-announces-dollar210-million-round-at-dollar35-billion-valuation>
- <https://www.medrxiv.org/content/10.64898/2025.11.29.25341091v1> — 34% complex-scenario accuracy
- <https://www.iatrox.com/blog/openevidence-review-uk-clinicians-alternatives>
- <https://nvidianews.nvidia.com/news/nvidia-partners-with-industry-leaders-to-advance-genomics-drug-discovery-and-healthcare>
- <https://developer.nvidia.com/blog/nvidia-nemotron-3-nano-omni-powers-multimodal-agent-reasoning-in-a-single-efficient-open-model/>

Nurse-persona / clinical-educator:
- <https://www.sciencedirect.com/science/article/abs/pii/S0020748923000329> — NIPDS
- <https://pubmed.ncbi.nlm.nih.gov/38244252/> — NIPDS + NEWS2
- <https://pmc.ncbi.nlm.nih.gov/articles/PMC10229039/> — Magnet + EBP
- <https://www.aacn.org/certification/get-certified/ccrn-adult> — CCRN cert requirements
- <https://www.mededportal.org/doi/10.15766/mep_2374-8265.10718> — One-Minute Preceptor (nurse-led)
- <https://pmc.ncbi.nlm.nih.gov/articles/PMC11151341/> — nurses in EOL family conversations
- <https://bmcnurs.biomedcentral.com/articles/10.1186/s12912-021-00622-2> — teach-back 45% readmission reduction
- <https://ai.jmir.org/2025/1/e58670/> — only 6% of medical KG studies on nursing
- <https://www.ncbi.nlm.nih.gov/books/NBK555513/> — failure to rescue (Aiken/Silber)
- <https://hippocraticai.com/copilot/> — Hippocratic AI nurse co-pilot

Corpus / SOTA:
- <https://pmc.ncbi.nlm.nih.gov/about/new-in-pmc/> — PMC cloud transition
- <https://arxiv.org/abs/2601.11425> — PubMed-OCR
- <https://arxiv.org/html/2506.02738v3> — Open-PMC-18M
- <https://www.nlm.nih.gov/research/umls/sourcereleasedocs/current/SNOMEDCT_US/index.html> — SNOMED CT US
- <https://developer.nvidia.com/nemo-retriever> — NeMo Retriever
- <https://huggingface.co/blog/abhinand/medembed-finetuned-embedding-models-for-medical-ir> — MedEmbed
- <https://arxiv.org/html/2407.17856v3> — MDS-ED benchmark (630 EM conditions)
- <https://huggingface.co/nvidia/omni-embed-nemotron-3b>
- <https://www.openevidence.com/announcements/nccn-and-openevidence-collaborate-to-bring-clinical-oncology-guidelines-to-medical-ai> — NCCN + OE
- <https://hitconsultant.net/2026/03/12/wiley-openevidence-partnership-clinical-ai-peer-reviewed-research/> — Wiley + OE
