---
title: Sources — runaway-AI knowledge base
date: 2026-04-22
scope: Every citation referenced by the four content files. Organized by category, with a one-line annotation per source. Citations-only; synthesis belongs in the content files.
---

# Sources

## Foundations

- [I.J. Good 1965 — Speculations Concerning the First Ultraintelligent Machine](https://languagelog.ldc.upenn.edu/myl/Good1964.pdf) — the founding text of the intelligence-explosion framing.
- [Bostrom — The Superintelligent Will](https://nickbostrom.com/superintelligentwill.pdf) — orthogonality thesis and instrumental convergence.
- [Superintelligence (book) — Wikipedia](https://en.wikipedia.org/wiki/Superintelligence:_Paths,_Dangers,_Strategies) — treacherous-turn framing canonical source.
- [Turner — Seeking Power Is Often Convergently Instrumental in MDPs (LessWrong)](https://www.lesswrong.com/posts/6DuJxY8X45Sco4bS2/seeking-power-is-often-convergently-instrumental-in-mdps) — formalization of instrumental convergence.
- [Turner et al. 2025 — Will Artificial Agents Pursue Power by Default?](https://arxiv.org/pdf/2506.06352v1) — update on power-seeking literature.
- [Carlsmith 2023 — Scheming AIs](https://arxiv.org/abs/2311.08379) — taxonomy of scheming vs training-gaming vs terminal-reward models.
- [Carlsmith — A taxonomy of non-schemer models](https://www.alignmentforum.org/posts/9fnzkSFeLwFbZQ5WG/a-taxonomy-of-non-schemer-models-section-1-2-of-scheming-ais) — full taxonomy excerpt.
- [Carlsmith 2022 — Existential risk from power-seeking AI](https://arxiv.org/pdf/2206.13353) — older formal framing.

## Technical precursors

- [Krakovna — Specification gaming examples](https://vkrakovna.wordpress.com/2018/04/02/specification-gaming-examples-in-ai/) — canonical list.
- [DeepMind — Specification gaming: the flip side of AI ingenuity](https://deepmind.google/blog/specification-gaming-the-flip-side-of-ai-ingenuity/) — definitional blog post.
- [Reward hacking — Wikipedia](https://en.wikipedia.org/wiki/Reward_hacking) — decent first read.
- [Lilian Weng — Reward hacking](https://lilianweng.github.io/posts/2024-11-28-reward-hacking/) — modern reference post.
- [Langosco, Shah et al. 2022 — Goal Misgeneralization](https://arxiv.org/abs/2210.01790) — capabilities generalize, goals don't.
- [DeepMind — How undesired goals can arise with correct rewards](https://deepmind.google/blog/how-undesired-goals-can-arise-with-correct-rewards/) — companion blog.
- [Anthropic 2025 — Natural Emergent Misalignment from Reward Hacking (arXiv 2511.18397)](https://arxiv.org/abs/2511.18397) — key 2025 result on runaway emerging from production RL.
- [Anthropic blog — Emergent misalignment from reward hacking](https://www.anthropic.com/research/emergent-misalignment-reward-hacking) — companion blog.
- [Reward Hacking and Emergent Misalignment review (arXiv 2604.13602)](https://arxiv.org/html/2604.13602v1) — review.
- [Model Organisms for Emergent Misalignment](https://arxiv.org/html/2506.11613v1) — model-organism framing.

## Anthropic — alignment and safety research

- [Constitutional Classifiers paper (arXiv 2501.18837)](https://arxiv.org/abs/2501.18837) — 86% → 4.4% jailbreak success at 23.7% inference overhead.
- [Constitutional Classifiers — Anthropic blog](https://www.anthropic.com/research/constitutional-classifiers) — product framing.
- [Next-generation constitutional classifiers](https://www.anthropic.com/research/next-generation-constitutional-classifiers) — 2026 deployment at ASL-3, ~1% overhead.
- [Claude's Constitution](https://www.anthropic.com/constitution) — public constitution.
- [Claude's new constitution (2025)](https://www.anthropic.com/news/claude-new-constitution) — revision.
- [Anthropic RSP v3](https://www.anthropic.com/news/responsible-scaling-policy-v3) — current Responsible Scaling Policy.
- [Anthropic RSP landing page](https://www.anthropic.com/responsible-scaling-policy) — current page.
- [RSP October 2024 PDF](https://assets.anthropic.com/m/24a47b00f10301cd/original/Anthropic-Responsible-Scaling-Policy-2024-10-15.pdf) — prior RSP snapshot.
- [ASL-3 activation May 2025](https://www.anthropic.com/news/activating-asl3-protections) — precautionary ASL-3 deployment for Opus 4.
- [Sketches of ASL-4 safety case components](https://alignment.anthropic.com/2024/safety-cases/) — three ASL-4 case types.
- [IAPS — RSP critique](https://www.iaps.ai/research/responsible-scaling) — external critique.
- [Hubinger et al. 2024 — Sleeper Agents (arXiv 2401.05566)](https://arxiv.org/html/2401.05566v3) — trigger-based backdoors persist through safety training.
- [Sleeper agents — Anthropic blog](https://www.anthropic.com/research/sleeper-agents-training-deceptive-llms-that-persist-through-safety-training) — blog.
- [Detection probes for sleeper agents](https://www.anthropic.com/research/probes-catch-sleeper-agents) — white-box detection AUROC >99%.
- [Sleeper agents code](https://github.com/anthropics/sleeper-agents-paper) — reproducibility artifacts.
- [Greenblatt, Hubinger et al. 2024 — Alignment Faking (arXiv 2412.14093)](https://arxiv.org/abs/2412.14093) — first empirical demo of unprompted strategic training-time compliance.
- [Alignment Faking — Anthropic blog](https://www.anthropic.com/research/alignment-faking) — blog.
- [Alignment Faking — training-time mitigations (2025)](https://alignment.anthropic.com/2025/alignment-faking-mitigations/) — goal-guarding and helpful-scratchpad interventions.
- [Alignment Faking Revisited (2025)](https://alignment.anthropic.com/2025/alignment-faking-revisited/) — improved 20-vote GPT-4o classifier AUROC 0.92.
- [Why do some language models fake alignment?](https://arxiv.org/html/2506.18032v1) — causal factors.
- [Agentic Misalignment — Anthropic blog (Jun 2025)](https://www.anthropic.com/research/agentic-misalignment) — 16-model study, Opus 4 blackmail 96%.
- [Agentic Misalignment paper (arXiv 2510.05179)](https://arxiv.org/abs/2510.05179) — paper.
- [Agentic Misalignment appendix](https://assets.anthropic.com/m/6d46dac66e1a132a/original/Agentic_Misalignment_Appendix.pdf) — full appendix.
- [Adapting Insider Risk mitigations (arXiv 2510.05192)](https://arxiv.org/html/2510.05192v1) — operational response.
- [Hot Mess of AI — Anthropic alignment](https://alignment.anthropic.com/2026/hot-mess-of-ai/) — early 2026 reflection.
- [Sabotage Evaluations — Anthropic](https://www.anthropic.com/research/sabotage-evaluations) — four eval families.
- [Sabotage Evaluations PDF](https://assets.anthropic.com/m/377027d5b36ac1eb/original/Sabotage-Evaluations-for-Frontier-Models.pdf) — full paper.
- [Summer 2025 Pilot Sabotage Risk Report](https://alignment.anthropic.com/2025/sabotage-risk-report/) — Opus 4 report.
- [Summer 2025 Pilot Sabotage PDF](https://alignment.anthropic.com/2025/sabotage-risk-report/2025_pilot_risk_report.pdf) — full.
- [Claude Opus 4.6 Sabotage Risk Report](https://anthropic.com/claude-opus-4-6-risk-report) — 8 catastrophic pathways mapped.
- [METR review of Opus 4.6 sabotage report](https://metr.org/blog/2026-03-12-sabotage-risk-report-opus-4-6-review/) — independent review.
- [SHADE-Arena — Anthropic blog](https://www.anthropic.com/research/shade-arena-sabotage-monitoring) — 17 paired benign + malicious tasks.
- [SHADE-Arena paper (arXiv 2506.15740)](https://arxiv.org/pdf/2506.15740) — full paper.
- [Petri — Anthropic blog](https://www.anthropic.com/research/petri-open-source-auditing) — auditor-agent framework.
- [Petri technical page](https://alignment.anthropic.com/2025/petri/) — v1 technical detail.
- [Petri v2 (2026)](https://alignment.anthropic.com/2026/petri-v2/) — multi-agent collusion scenarios.
- [Bloom — Anthropic blog](https://www.anthropic.com/research/bloom) — automated behavioral eval tool.
- [Bloom repo](https://github.com/safety-research/bloom) — code.
- [Scaling Monosemanticity](https://transformer-circuits.pub/2024/scaling-monosemanticity/) — SAEs on Claude 3 Sonnet.
- [Biology of a Large Language Model](https://transformer-circuits.pub/2025/attribution-graphs/biology.html) — attribution graphs on Haiku 3.5.
- [Circuit Tracing methods](https://transformer-circuits.pub/2025/attribution-graphs/methods.html) — method paper.
- [Circuits October 2025 update](https://transformer-circuits.pub/2025/october-update/index.html) — cross-modal feature steering.
- [Attribution graphs frontend](https://github.com/anthropics/attribution-graphs-frontend) — OSS visualization.
- [Reasoning Models Don't Always Say What They Think](https://www.anthropic.com/research/reasoning-models-dont-say-think) — CoT faithfulness ~25%.
- [Tracing the thoughts of an LLM](https://www.anthropic.com/research/tracing-thoughts-language-model) — interp explainer.
- [Activation Oracles](https://alignment.anthropic.com/2025/activation-oracles/) — activation-based decision support.
- [Automated Weak-to-Strong Researcher](https://alignment.anthropic.com/2026/automated-w2s-researcher/) — 2026 research pipeline.
- [Strengthening Red Teams](https://alignment.anthropic.com/2025/strengthening-red-teams/) — red-team framework evolution.
- [Frontier Red Team — progress and insights](https://www.anthropic.com/news/strategic-warning-for-ai-risk-progress-and-insights-from-our-frontier-red-team) — product-side summary.
- [red.anthropic.com](https://red.anthropic.com/) — frontier red team homepage.
- [Claude Mythos Preview](https://red.anthropic.com/2026/mythos-preview/) — first model through 32-step TLO range.
- [AISI Claude Mythos cyber evaluation](https://www.aisi.gov.uk/blog/our-evaluation-of-claude-mythos-previews-cyber-capabilities) — AISI assessment.
- [Claude Opus 4.5 system card PDF](https://assets.anthropic.com/m/64823ba7485345a7/Claude-Opus-4-5-System-Card.pdf) — card.
- [Claude Opus 4.5 system card page](https://www.anthropic.com/claude-opus-4-5-system-card) — index.
- [Claude Opus 4.6 system card PDF](https://www-cdn.anthropic.com/14e4fb01875d2a69f646fa5e574dea2b1c0ff7b5.pdf) — card.
- [Zvi on Opus 4.5](https://thezvi.substack.com/p/claude-opus-45-model-card-alignment) — external alignment read.
- [Zvi on Opus 4.6](https://thezvi.wordpress.com/2026/02/10/claude-opus-4-6-system-card-part-2-frontier-alignment/) — external alignment read.
- [Zvi on Opus 4.7](https://thezvi.substack.com/p/opus-47-part-1-the-model-card) — 232-page system card summary, 45% → 12.5% hack rate under anti-hack prompt.
- [Anthropic Alignment Science blog](https://alignment.anthropic.com/) — index.

## Redwood — AI Control line

- [Greenblatt, Shlegeris, Sachan, Roger 2023 — AI Control (arXiv 2312.06942)](https://arxiv.org/abs/2312.06942) — founding paper; Trusted Monitoring, Defer-to-Trusted, Trusted Editing.
- [AI Control paper PDF](https://arxiv.org/pdf/2312.06942) — PDF form.
- [Ctrl-Z: Controlling AI Agents via Resampling (arXiv 2504.10374)](https://arxiv.org/pdf/2504.10374) — high-stakes agent setting; resample protocol.
- [BashControl](https://www.bashcontrol.com/) — companion site.
- [Mallen et al. 2025 — Adaptive attacks on trusted monitors (arXiv 2510.09462)](https://arxiv.org/html/2510.09462) — protocols subverted by monitor-specific adaptation.
- [Wen et al. 2026 — TraceGuard (arXiv 2604.03968)](https://arxiv.org/html/2604.03968) — structured multi-dimensional monitoring, collusion resistance.
- [Redwood control-arena repo](https://github.com/redwoodresearch/redwood-control-arena) — Inspect-hosted protocol experiments.
- [Redwood reading list](https://www.redwoodresearch.org/reading-list) — curated research reading.
- [Redwood Research](https://www.redwoodresearch.org/) — org.
- [Redwood — AI Control research](https://www.redwoodresearch.org/research/ai-control) — research page.
- [The case for ensuring that powerful AIs are controlled](https://blog.redwoodresearch.org/p/the-case-for-ensuring-that-powerful) — foundational position.
- [Overview of control work](https://blog.redwoodresearch.org/p/an-overview-of-areas-of-control-work) — map of research.
- [Overview of control measures](https://blog.redwoodresearch.org/p/an-overview-of-control-measures) — catalogue.
- [Jankily controlling superintelligence](https://blog.redwoodresearch.org/p/jankily-controlling-superintelligence) — control is for the early-schemer regime; not expected to scale to wildly superintelligent systems.
- [Handling schemers if shutdown is not an option](https://www.lesswrong.com/posts/XxjScx4niRLWTfuD5/handling-schemers-if-shutdown-is-not-an-option) — extended discussion.
- [Why it's hard to make settings for high-stakes control](https://blog.redwoodresearch.org/p/why-its-hard-to-make-settings-for) — empirical methodology.
- [Redwood apps-monitor-control-eval](https://github.com/redwoodresearch/apps-monitor-control-eval) — paired attack/monitor eval.
- [Redwood subversion-strategy-eval](https://github.com/redwoodresearch/subversion-strategy-eval) — untrusted-model reasoning about subverting protocols.
- [Redwood Measurement-Tampering](https://github.com/redwoodresearch/Measurement-Tampering) — tampering benchmark.
- [Redwood Text-Steganography-Benchmark](https://github.com/redwoodresearch/Text-Steganography-Benchmark) — covert channel detection.
- [Redwood bench-af-2](https://github.com/redwoodresearch/bench-af-2) — alignment-faking model organisms + detectors.
- [Redwood basharena_public](https://github.com/redwoodresearch/basharena_public) — high-stakes bash control setting.
- [brucewlee mini-control-arena](https://github.com/brucewlee/mini-control-arena) — educational mini-setting.
- [Apollo + Redwood — Safety cases for AI scheming (arXiv 2411.03336)](https://arxiv.org/abs/2411.03336) — evaluations-based safety case framework.
- [Korbak et al. 2025 — Sketch of an AI control safety case (arXiv 2501.17315)](https://arxiv.org/abs/2501.17315) — three case types: scheming-inability, harm-inability, harm-control.
- [Control measures trajectory to superintelligence (arXiv 2504.05259)](https://arxiv.org/html/2504.05259v1) — protocol evolution.

## METR

- [METR homepage](https://metr.org/) — org.
- [Measuring AI Ability to Complete Long Tasks (Mar 2025)](https://metr.org/blog/2025-03-19-measuring-ai-ability-to-complete-long-tasks/) — 50% time-horizon paper.
- [METR paper HTML (arXiv 2503.14499)](https://arxiv.org/html/2503.14499v1) — full paper.
- [Time Horizon 1.1 (Jan 2026)](https://metr.org/blog/2026-1-29-time-horizon-1-1/) — Opus 4.5 at 320 min; 89-day doubling since 2024.
- [Time Horizon across domains](https://metr.org/blog/2025-07-14-how-does-time-horizon-vary-across-domains/) — cross-domain measurements.
- [Rogue Replication Threat Model](https://metr.org/blog/2024-11-12-rogue-replication-threat-model/) — threat framing.
- [Common Elements](https://metr.org/common-elements) — shared task components.
- [METR red-teaming Anthropic agent monitoring (Mar 2026)](https://metr.org/blog/2026-03-25-red-teaming-anthropic-agent-monitoring/) — 3-week red-team of Anthropic's internal monitoring.
- [METR — Autonomy Evaluation Resources](https://metr.org/blog/2024-03-13-autonomy-evaluation-resources/) — resource index.
- [Autonomy Evals Guide](https://metr.github.io/autonomy-evals-guide/) — methodology.
- [METR task-standard](https://github.com/METR/task-standard) — eval task format.
- [METR public-tasks](https://github.com/METR/public-tasks) — 31 examples + 186 summaries.
- [METR RE-Bench](https://github.com/METR/RE-Bench) — ML research-engineering tasks.
- [METR HCAST-public](https://github.com/METR/hcast-public) — Human-Calibrated Autonomy Software Tasks.
- [METR Vivaria](https://github.com/METR/vivaria) — self-hostable agent-elicitation runner.

## Apollo Research

- [Apollo Research — research page](https://www.apolloresearch.ai/research/) — index.
- [Frontier models are capable of in-context scheming (arXiv 2412.04984)](https://arxiv.org/abs/2412.04984) — 6 eval protocol, 5 of 6 frontier models scheme on ≥1.
- [Apollo — in-context scheming blog](https://www.apolloresearch.ai/research/frontier-models-are-capable-of-incontext-scheming/) — blog form.
- [More capable models are better at scheming](https://www.apolloresearch.ai/blog/more-capable-models-are-better-at-in-context-scheming/) — scaling trend + eval-awareness contamination.
- [Stress testing deliberative alignment for anti-scheming training](https://www.apolloresearch.ai/research/stress-testing-deliberative-alignment-for-anti-scheming-training/) — 30× covert-action reduction.
- [Demo scheming evals](https://www.apolloresearch.ai/blog/demo-example-scheming-reasoning-evaluations/) — worked examples.
- [Scheming precursor evals had limited predictive power](https://www.apolloresearch.ai/blog/research-note-our-scheming-precursor-evals-had-limited-predictive-power-for-our-in-context-scheming-evals/) — capability-style evals do not reliably predict downstream scheming.
- [Claude Sonnet 3.7 knows when it's in alignment evaluations](https://www.apolloresearch.ai/blog/claude-sonnet-37-often-knows-when-its-in-alignment-evaluations/) — 33% spontaneous eval-mention rate; the eval-awareness finding.
- [Apollo deception-detection](https://github.com/ApolloResearch/deception-detection) — linear-probe-based (white-box only).
- [Apollo insider-trading](https://github.com/ApolloResearch/insider-trading) — GPT-4 strategic-deception case corpus.
- [OpenAI — Detecting and reducing scheming in AI models](https://openai.com/index/detecting-and-reducing-scheming-in-ai-models/) — OpenAI collaborative work.
- [AI Sandbagging paper (arXiv 2406.07358)](https://arxiv.org/html/2406.07358v2) — sandbagging formalization.

## Replication and exfiltration

- [RepliBench — AISI blog (Apr 2025)](https://www.aisi.gov.uk/blog/replibench-measuring-autonomous-replication-capabilities-in-ai-systems) — four-domain autonomous replication measurement.
- [RepliBench paper (arXiv 2504.18565)](https://arxiv.org/abs/2504.18565) — paper.
- [RepliBench HTML](https://arxiv.org/html/2504.18565v2) — HTML form.
- [Pan et al. 2025 — LLM-powered systems achieve self-replication (arXiv 2503.17378)](https://arxiv.org/abs/2503.17378) — 11/32 systems self-replicate including 14B models on consumer hardware.
- [Self-exfiltration as key capability (Aligned Substack)](https://aligned.substack.com/p/self-exfiltration) — framing of self-exfiltration as single most dangerous agentic capability.

## External frameworks

- [Inspect AI homepage](https://inspect.aisi.org.uk/) — UK AISI eval framework.
- [Inspect evals list](https://inspect.aisi.org.uk/evals/) — catalogue.
- [Inspect AI repo](https://github.com/UKGovernmentBEIS/inspect_ai) — source.
- [Inspect evals repo](https://github.com/UKGovernmentBEIS/inspect_evals) — 200+ prebuilt.
- [AISI — Inspect blog](https://www.aisi.gov.uk/blog/inspect-evals) — blog launch.
- [AISI Autonomous Systems Evaluation Standard](https://ukgovernmentbeis.github.io/as-evaluation-standard/) — standard.
- [ControlArena (UK AISI + Redwood)](https://github.com/UKGovernmentBEIS/control-arena) — AI-control protocol experiments.
- [US AISI FLI profile](https://futureoflife.org/us-agency/us-ai-safety-institute-usaisi/) — org profile.
- [NIST TRAINS taskforce (Nov 2024)](https://www.nist.gov/news-events/news/2024/11/us-ai-safety-institute-establishes-new-us-government-taskforce-collaborate) — DoD/DoE/DHS/NIH coordination.
- [DOE TRAINS announcement](https://www.energy.gov/articles/us-ai-safety-institute-establishes-new-us-government-taskforce-collaborate-research-and) — DOE side.
- [Pre-deployment evaluation of OpenAI o1 — AISI](https://www.aisi.gov.uk/blog/pre-deployment-evaluation-of-openais-o1-model) — joint US/UK eval.
- [Pre-deployment evaluation of o1 — NIST](https://www.nist.gov/news-events/news/2024/12/pre-deployment-evaluation-openais-o1-model) — US side.
- [US-UK joint evaluation (FedScoop)](https://fedscoop.com/anthropic-tested-by-us-uk-ai-safety-institutes/) — Anthropic-specific.
- [OpenAI Preparedness Framework v2](https://openai.com/index/updating-our-preparedness-framework/) — v2 framework.
- [OpenAI Preparedness v2 PDF](https://cdn.openai.com/pdf/18a02b5d-6b67-4cec-ab64-68cdfbddebcd/preparedness-framework-v2.pdf) — full.
- [Mowshowitz on OpenAI Preparedness 2](https://thezvi.substack.com/p/openai-preparedness-framework-20) — external critique.
- [OpenAI rewrote preparedness framework (LessWrong)](https://www.lesswrong.com/posts/Yy5ijtbNfwv8DWin4/openai-rewrote-its-preparedness-framework) — LW discussion.
- [DeepMind FSF v3 blog (Apr 2026)](https://deepmind.google/blog/strengthening-our-frontier-safety-framework/) — harmful-manipulation CCL added; TCLs for earlier warning.
- [DeepMind FSF v3 PDF](https://storage.googleapis.com/deepmind-media/DeepMind.com/Blog/strengthening-our-frontier-safety-framework/frontier-safety-framework_3.pdf) — full.
- [DeepMind FSF v2 PDF](https://storage.googleapis.com/deepmind-media/DeepMind.com/Blog/updating-the-frontier-safety-framework/Frontier%20Safety%20Framework%202.0%20(1).pdf) — prior snapshot.
- [DeepMind — evaluating and monitoring for AI scheming](https://deepmindsafetyresearch.medium.com/evaluating-and-monitoring-for-ai-scheming-d3448219a967) — DeepMind scheming framing.

## MIRI

- [MIRI — Corrigibility (2015)](https://intelligence.org/2014/10/18/new-report-corrigibility/) — utility-function analysis for shutdown cooperation.
- [HRAD arguments (arXiv 2201.02950)](https://arxiv.org/pdf/2201.02950) — agent-foundations agenda.
- [Agent Foundations study](https://agentfoundations.study/) — study program.

## Open-source capability/redteam evals

- [Cybench](https://github.com/andyzorigin/cybench) — 40 CTFs with subtask scoring.
- [WMDP (CAIS)](https://github.com/centerforaisafety/wmdp) — 3,668 MCQs on hazardous knowledge + RMU unlearning.
- [BioLP-bench](https://github.com/baceolus/BioLP-bench) — biology-protocol understanding probe.
- [HarmBench (CAIS)](https://github.com/centerforaisafety/HarmBench) — 18 attacks × 33 target defenses; frozen at v1.0.
- [Microsoft PyRIT](https://github.com/microsoft/PyRIT) — multi-turn adversarial orchestration.
- [NVIDIA garak](https://github.com/NVIDIA/garak) — jailbreak/encoding/leak probe scanner.
- [MLCommons AILuminate](https://github.com/mlcommons/ailuminate) — curated harm benchmark.
- [MLCommons modelbench](https://github.com/mlcommons/modelbench) — modelbench runner.
- [AISI sandbagging_auditing_games](https://github.com/AI-Safety-Institute/sandbagging_auditing_games) — five model organisms for auditor training.

## Observability

- [Langfuse](https://github.com/langfuse/langfuse) — MIT core, OTel-based.
- [Arize Phoenix](https://github.com/Arize-ai/phoenix) — OTel; Claude Agent SDK instrumentation.
- [traceloop OpenLLMetry](https://github.com/traceloop/openllmetry) — pure OTel.
- [Helicone](https://github.com/Helicone/helicone) — proxy-model rate limit.
- [W&B Weave](https://github.com/wandb/weave) — W&B tracing.
- [Langtrace](https://github.com/Scale3-Labs/langtrace) — OTel-based.
- [LangSmith SDK](https://github.com/langchain-ai/langsmith-sdk) — SaaS-first.
- [LangWatch — 4 best tools for monitoring LLM agents 2026](https://langwatch.ai/blog/4-best-tools-for-monitoring-llm-agentapplications-in-2026) — landscape summary.
- [Galileo — 8 best AI agent reliability solutions 2026](https://galileo.ai/blog/best-ai-agent-reliability-solutions) — landscape.
- [Arize — best AI observability tools for autonomous agents 2026](https://arize.com/blog/best-ai-observability-tools-for-autonomous-agents-in-2026/) — landscape.

## Guardrails

- [NVIDIA NeMo Guardrails](https://github.com/NVIDIA-NeMo/Guardrails) — Colang rails.
- [Guardrails AI](https://github.com/guardrails-ai/guardrails) — Validator Hub.
- [Protect AI llm-guard](https://github.com/protectai/llm-guard) — 15 input + 20 output scanners.
- [Lakera docs](https://docs.lakera.ai/) — Lakera Guard.

## Claude API docs (the API control-levers source set)

- [Claude API — Messages](https://platform.claude.com/docs/en/build-with-claude/the-messages-api) — core Messages API.
- [Claude API — Handling stop reasons](https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons) — stop_reason semantics.
- [Claude API — Extended thinking](https://platform.claude.com/docs/en/build-with-claude/extended-thinking) — thinking config, signed blocks.
- [Claude API — Tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/) — tool-use overview.
- [Claude API — Computer use](https://platform.claude.com/docs/en/build-with-claude/computer-use) — desktop automation.
- [Claude API — Code execution tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool) — server-side sandbox.
- [Claude API — Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) — cache control.
- [Claude API — Batch processing](https://platform.claude.com/docs/en/build-with-claude/batch-processing) — async batch.
- [Claude API — MCP connector](https://platform.claude.com/docs/en/agents-and-tools/mcp-connector) — MCP usage.
- [Claude API — Vision](https://platform.claude.com/docs/en/build-with-claude/vision) — image input.
- [Claude API — Streaming refusals](https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/handle-streaming-refusals) — refusal semantics.
- [Claude API — Managed Agents overview](https://platform.claude.com/docs/en/managed-agents/overview) — Managed Agents.
- [Claude API — Credential vaults](https://platform.claude.com/docs/en/managed-agents/vaults) — vaults for MCP auth.
- [Claude API — CLI (ant)](https://platform.claude.com/docs/en/api/sdks/cli) — official CLI sidecar.
- [HelpNet — Claude Managed Agents bring execution and control](https://www.helpnetsecurity.com/2026/04/09/claude-managed-agents-bring-execution-and-control-to-ai-agent-workflows/) — external launch coverage.
- [VentureBeat — AI agent runtime security 2026](https://venturebeat.com/security/ai-agent-runtime-security-system-card-audit-comment-and-control-2026) — landscape.

## Additional related reading

- [Treacherous turns in the wild (Muehlhauser)](https://lukemuehlhauser.com/treacherous-turns-in-the-wild/) — informal treacherous-turn catalogue.
- [AI Researchers perspectives on AGI automation (arXiv 2603.03338)](https://arxiv.org/html/2603.03338) — survey of researcher views.
- [Technological singularity — Wikipedia](https://en.wikipedia.org/wiki/Technological_singularity) — reference.
- [LessWrong — AI Takeoff](https://www.lesswrong.com/w/ai-takeoff) — wiki page.
- [LessWrong — Intelligence explosion](https://www.lesswrong.com/w/intelligence-explosion) — wiki.
- [AlignmentForum — Recursive self-improvement](https://www.alignmentforum.org/w/recursive-self-improvement) — wiki.

## Generational markers — post-cutoff literature

The following are important for any work that cites the literature; a model trained before these will have weak or zero coverage:

- Natural Emergent Misalignment from Reward Hacking (Anthropic Nov 2025)
- Claude Opus 4.5 / 4.6 / 4.7 system cards (Nov 2025 / Feb 2026 / Apr 2026)
- RSP v3.1 (2026); ASL-3 deployment (May 22 2025)
- METR Time Horizon 1.1 (Jan 2026)
- Constitutional Classifiers++ (2026)
- Apollo deliberative-alignment anti-scheming (2025)
- Alignment Faking Revisited (2025)
- Claude Mythos cyber preview (Apr 2026)
- Ctrl-Z, BashArena, TraceGuard, Adaptive Attacks on Trusted Monitors (2024-2026)
- Apollo evaluation-awareness finding (Claude 3.7 at 33%)
- Petri v2 (2026)
- DeepMind FSF v3 with TCLs (Apr 2026)
- Pan et al. 2025 self-replication
- Anthropic Managed Agents (beta header `managed-agents-2026-04-01`, GA April 2026)
- Credential vaults (platform.claude.com Managed Agents, April 2026)

Last research sweep: 2026-04-22. Update this list when a release meaningfully changes a mapping in the content files.
