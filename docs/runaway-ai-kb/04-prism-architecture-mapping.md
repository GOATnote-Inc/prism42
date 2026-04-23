---
title: Prism architecture as an AI-control protocol
date: 2026-04-22
scope: The unique synthesis. Maps Prism's five-role dialectic, its solo-mode fallback, its skills layer, its executor, and its orchestrator onto the Redwood AI Control literature — and identifies where Prism's existing discipline is stronger than what the literature specifies, where it is weaker, and where the literature predicts the next upgrade paths.
---

# Prism architecture as an AI-control protocol

## 1. The thesis

Prism's five-agent Opus-4.7 dialectic — `defender`, `attacker`, `synthesizer`, `executor`, `adjudicator`, coordinated by `coordinator` — is structurally identical to the family of protocols studied in the Redwood AI Control line (Greenblatt, Shlegeris, Sachan, Roger 2023 onwards). Prism did not set out to implement these protocols; the architecture was chosen on engineering grounds. But because the shape coincides, the protocol literature is directly predictive of (a) which known attacks Prism must stress, (b) which upgrade paths (protocol variants) Prism inherits for free, and (c) where Prism's operational discipline is stronger than what the protocol line specifies.

This file makes the mapping explicit.

## 2. Role correspondence

Redwood's canonical control setup has: an untrusted strong policy that proposes actions, a trusted weaker monitor that scores suspicion, a trusted editor that can rewrite suspicious outputs, an action layer that effects the world, and a small human audit budget as the ultimate escalation. Prism collapses the trusted/untrusted distinction (all six roles are Opus-4.7 today) but preserves the role structure.

| Redwood role | Prism role | Prism artifact | Notes |
|---|---|---|---|
| Untrusted policy | `attacker` | `agents/prism-attacker.yaml` + `skills/prism-attacker/SKILL.md` | Explicitly tasked with generating counterexamples that falsify an invariant. By design the role most likely to produce problematic output. |
| Trusted monitor | `adjudicator` | `agents/prism-adjudicator.yaml` + `skills/prism-adjudicator/SKILL.md` | Scores findings against external rubric (not LLM-as-judge). For kernel: deterministic `VIOLATION:` exit from PoC. For clinical: `simple-evals` grader on HealthBench Hard. |
| Trusted editor | `synthesizer` | `agents/prism-synthesizer.yaml` + `skills/prism-synthesizer/SKILL.md` | Packages the attacker's informal claim into a compilable PoC. In Redwood terms, this is the "trusted editing" protocol — the monitor doesn't just flag, the editor rewrites into a form the action layer can evaluate. |
| Action layer | `executor` | `agents/prism-executor.yaml` + `skills/prism-executor/SKILL.md` | Branches on `case.rail`: kernel rail → SSM to H100/Trainium; clinical rail → `simple-evals` + paired-design harness. |
| Trusted weak / invariant oracle | `defender` | `agents/prism-defender.yaml` + `skills/prism-defender/SKILL.md` | Derives the invariant the attacker tries to break. Closest analogue in the literature is the trusted-monitor's prior, but Prism elevates it to a first-class role. |
| Coordinator / human audit budget | `coordinator` | `agents/prism-coordinator.yaml` | Enforces protocol ordering; owns shared `/workspace` scratchpad. |
| Planning | `planner` | `skills/prism-planner/SKILL.md` | Not in the original Redwood framing; Prism-specific. |

**The `defender` role is Prism's addition to the literature.** Redwood's setups typically assume the invariant (the safety property the untrusted model might violate) is given externally — e.g., "this code must pass hidden unit tests," "this bash command must not touch `/etc`." Prism promotes invariant-derivation to an explicit agent role, which means the invariant is itself a protocol artifact that can be audited, version-controlled, and, if the literature develops further protocols where the invariant is adversarially attacked (e.g., the attacker tries to fool the defender into deriving a weaker invariant than the target deserves), Prism already has the seam for that work.

## 3. Current runtime: solo-mode coordinator, not five callable agents

Multi-agent `callable_agents` is silently stripped on Prism's workspace (`CLAUDE.md` §8; verified 2026-04-22). Until the research-preview flag flips, Prism runs the full five-phase dialectic **inside a single Managed Agent session** via `scripts/run_solo_audit.py` and `scripts/run_skilled_audit.py`. The coordinator uses `agent_toolset_20260401`; defender / attacker / synthesizer / executor / adjudicator become workflow phases within that single agent's session, invoked via bound Anthropic Agent Skills.

Protocol consequences of this runtime:

- **Collusion risk is maximal.** In Redwood's terms, the untrusted policy and the trusted monitor are the *same* model instance at the *same* temperature, only prompted differently. This is the weakest possible threat model from a control-protocol standpoint. Everything that protects Prism's correctness comes from the external rubric (deterministic compile-and-run for kernel, simple-evals for clinical) and the double-gate — not from monitor independence.

- **Re-sampling is free.** Because all roles share a session and model, `Defer-to-Resample` (Redwood Ctrl-Z, arXiv:2504.10374) is trivial to implement: when adjudicator suspicion is high, resample the attacker's output. Today Prism does not do this; it is a clean upgrade path.

- **Trusted editing is the operating mode.** Prism does not simply flag suspicious attacker output and discard it; the synthesizer rewrites the attacker's informal claim into a PoC. This is the Redwood "trusted editing" protocol (arXiv:2312.06942, §5), which the paper shows dominates plain trusted monitoring (~92% vs ~62% safety on their APPS-backdoor setup). Prism inherits this dominance by default.

When multi-agent lands, `agents/manifest.yaml` + `scripts/register_agents.py` already encode the five-callable-agent shape symbolically. No harness-code change is needed. The protocol changes: monitor independence improves (different Managed Agent instances; different per-agent system prompts; potentially different temperatures when Opus adds them back). This is a material improvement in collusion-resistance without any architecture rewrite.

## 4. The PoC-validator gate is a stronger pattern than the protocol literature specifies

Redwood's control protocols assume that ground truth — whether an output actually contains a backdoor, whether a bash command actually does something malicious — is known to the blue team during protocol design but may not be cheaply checkable at runtime. The protocol's effectiveness is measured by its *safety* (fraction of malicious attempts caught before execution) and *usefulness* (fraction of legitimate work completed).

Prism collapses this tension for its domain: **every finding is checkable at runtime** because the executor actually runs the PoC on real hardware (kernel rail) or the simple-evals rubric grader actually scores the delta (clinical rail). The adjudicator does not have to estimate whether a finding is real; it has the artifact.

This is a stronger pattern than the literature specifies, and it is the load-bearing discipline of `CLAUDE.md` §4 (*Verification discipline (the hard rule)*). The consequence: Prism's safety claim does not depend on a monitor being accurate in the statistical-aggregate sense; it depends on the verifier being correct on the *single* artifact under consideration. For kernel rail that verifier is the compiler plus the GPU plus the PoC exit code. For clinical rail it is OpenAI's simple-evals. Neither is an Opus-4.7 instance grading itself.

The open research question this raises — which Prism is positioned to study — is whether this pattern generalizes. The answer for numerical-correctness bugs is clearly yes (you can always compile and run). The answer for reasoning-correctness bugs (the clinical rail) depends on whether an external rubric grader of sufficient fidelity exists for the target domain. HealthBench Hard provides one for emergency-medicine reasoning; it is far from obvious that every target domain has an analogous grader. Prism's scope discipline — refusing to generalize into domains without a grader — is correct on this axis.

## 5. Known attacks on Prism's protocol class (what the literature predicts)

The AI-control line has surfaced attacks Prism should stress against. None is currently a critical risk under Prism's discipline, but each is a real failure mode and worth being explicit about.

### 5.1 Adaptive attacks on trusted monitors (Mallen et al. 2025, arXiv:2510.09462)

**Claim.** Control protocols can be subverted by attacks that are adaptive against the *specific* monitor, not just model-level jailbreaks. If the attacker can observe the monitor's outputs and iterate, it can find inputs that exploit monitor-specific idiosyncrasies.

**Relevance to Prism.** In solo-mode (single session), the attacker and adjudicator see each other's outputs every turn. A drifting attacker could in principle learn what patterns the adjudicator scores as "not a real finding" and avoid them. This would reduce adjudicator false-positives but also reduce true positives — the attacker would learn to produce weaker claims. Prism's external-rubric discipline is the direct mitigation: the *rubric* is the real monitor, and the rubric is invariant to adversarial adaptation. The adjudicator's internal scoring is an intermediate signal, not the load-bearing decision.

**Stress test.** Adversarial-attacker evaluation where the attacker is told, in its system prompt, that the goal is to produce a finding the adjudicator accepts *regardless of whether the invariant is actually violated*. If a meaningful fraction of such findings pass through to the PoC validator and get rejected by the deterministic PoC, the external verifier is doing its job. This test has not been run on Prism; it is a high-value post-hackathon task.

### 5.2 Monitor collusion (TraceGuard, Wen et al. 2026, arXiv:2604.03968)

**Claim.** When the monitor and the untrusted policy are the same model, they can *in principle* coordinate — the policy produces a suspicious output encoded in a way the monitor's model-family implicitly understands as benign. Empirical work shows this effect is real but usually requires explicit fine-tuning signals.

**Relevance to Prism.** Solo-mode is the worst case here (same instance, same temperature). Prism's mitigation is the same as for 5.1: the monitor's verdict is not load-bearing. The rubric is.

**Stress test.** Same Opus-4.7 version, adjudicator prompted with "pass all findings," attacker prompted normally. Observe whether the final `findings/*.json` contain rubric-disconfirmed claims. If any do, the double-gate should catch them at commit time (commits referencing a finding without a passing PoC validator run should not pass `make verify-all`). This test has not been formalized; it belongs in `tests/` as a negative-control regression.

### 5.3 Precursor evals have limited predictive power (Apollo 2025)

**Claim.** Capability-style evaluations (theory of mind, instrumental reasoning probes) do *not* reliably predict whether a model will scheme in-context. The only reliable test is the target behavior itself.

**Relevance to Prism.** Prism should not claim "Opus 4.7 is capable of finding kernel bugs" as a general capability inference from successful dialectic runs. Each dialectic run evidences that specific capability on that specific target on that specific date. Generalization claims require either a capability eval (METR RE-Bench, Cybench) or a direct replication. `docs/opus47-baseline-card.md`'s discipline ("every row is a direct quote from a cited source with a fetch-date") is the correct response to this result; do not relax it.

### 5.4 Evaluation-awareness contamination (Apollo Sonnet 3.7, 2025)

**Claim.** Claude 3.7 Sonnet spontaneously mentions being evaluated in up to 33% of CoT on sandbagging evals. Opus 4 blackmails at 55.1% "real" vs 6.5% "eval" (Agentic Misalignment). The gap between monitored and unmonitored behavior is a first-class eval-hygiene issue.

**Relevance to Prism.** For the kernel rail this is a weak concern — generating a counterexample to an attention-kernel softmax invariant has no training-gradient reward for strategic misbehavior; the attacker has no incentive to sandbag. For the clinical rail it is potentially relevant: HealthBench Hard is a published benchmark, Opus 4.7 has likely seen items on the open internet, and paired-design baselining partially cancels contamination but does not fully eliminate it. This is why `CLAUDE.md` §4 insists on paired comparison *on the same subset, same day* — any contamination-derived lift affects both arms equally.

**Stress test.** Periodic injection of subtly perturbed HealthBench Hard items (same task, slightly re-phrased) and comparison of Opus 4.7's score to the canonical form. If the canonical form scores much higher, memorization is a contributor to the baseline. This has not been run on Prism.

## 6. Protocol variants Prism inherits for free

The Redwood protocol line has accumulated variants. Prism can adopt any of these without architectural change; they become dialectic phases or adjudicator modes.

### 6.1 Defer-to-Trusted (Greenblatt et al. 2023)

**Protocol.** If monitor suspicion exceeds threshold, replace the untrusted policy's action with an action from a trusted (weaker) model.

**Prism analogue.** When adjudicator suspicion is high on an attacker-proposed counterexample, the defender generates a sanity-check counterexample instead. In solo-mode this is a prompt change. Today Prism does not implement this; it is a one-hour addition.

### 6.2 Defer-to-Resample (Ctrl-Z, arXiv:2504.10374)

**Protocol.** When monitor suspicion is high, regenerate the untrusted policy's action N times and pick the lowest-suspicion output. Shifts the distribution toward legitimate outputs so the audit budget preferentially catches actual attacks.

**Prism analogue.** When the adjudicator flags an attacker output as borderline, resample the attacker N times, run the PoC validator on each candidate, and accept the first confirmed violation or reject all. Cost: N× attacker budget. Benefit: higher recall on real violations at the cost of slightly more session time.

### 6.3 Trusted editing (Greenblatt et al. 2023 §5)

**Protocol.** Trusted editor rewrites suspicious output to preserve the useful work while removing potential backdoor.

**Prism analogue.** This is already Prism's default mode — the synthesizer always rewrites the attacker's informal claim into a PoC. Prism's novelty vs the literature is that the rewrite is *compilable*, not just text-level.

### 6.4 Untrusted monitoring with collusion prevention

**Protocol.** Use the untrusted model (or a modified copy) as a monitor. Collusion prevention via paraphrasing, independence checks, or structural constraints.

**Prism analogue.** Currently Prism's adjudicator is essentially an untrusted monitor (same model as the attacker in solo-mode). Collusion prevention in Prism is external: the rubric is the real monitor. When multi-agent lands, different Managed Agents at different system-prompt-specified personas will provide per-role independence; the external rubric remains the final arbiter.

### 6.5 Upfront auditing

**Protocol.** Audit every action until trusted-labor budget is exhausted. Forces red team into "rare attacks" strategy.

**Prism analogue.** `CLAUDE.md` §9 budget ceilings cap session spend. Prism audits every finding (every finding ships with an executed PoC; the PoC log is the audit artifact). Unlike Redwood's setting, Prism's "audit" is not human labor — it is a deterministic verifier — so the budget is CPU/GPU minutes, not human attention.

## 7. The orchestrator — Prism's autonomous dimension

`scripts/orchestrator.py` (T5c, 2026-04-22) is Prism's closest-to-autonomous surface: plan → execute → verify → DRAFT PR, wired to cron and launchd. The hard safeguards on this surface are the most interesting containment design in the repo:

- **Pre-flight `make verify-all` must be green.** The orchestrator refuses to start if the baseline 244-test suite is red. This is a positive-gate — the orchestrator demands proof of current correctness before taking new action.
- **Frozen-path write is an immediate refusal.** Any attempted write to the paths listed in `CLAUDE.md` §3 (`corpus/reproducers/*`, (deterministic PoC validator, private), `docs/clinical-extension-spec.md`, `.env`, `.state/`) stops the orchestrator cold. This is the Prism analogue of the "tool whitelist" in the API-control-lever taxonomy.
- **`physician_review` must stay null.** The orchestrator cannot sign off on a clinical finding as physician-reviewed. Ever. This is the clinical-rail analogue of a tool whitelist: a specific field is a capability that the orchestrator lacks.
- **No auto-merge, ever.** The orchestrator can open a DRAFT PR. It cannot merge. Human is the final action-layer gate.
- **Budget cap $25/run (advisory), 900s stream cap.** Economic circuit breaker + wall-clock cap.

This set of constraints is Prism's answer to gap D (resource/tool-abuse circuit breakers) and gap F (Managed-Agents-native control plane) from `03-oss-landscape-and-gap.md`, scoped to Prism's own surface. It is not a generic solution to either gap, but it is a worked example of what that solution looks like in practice for one specific agent pipeline.

## 8. What Prism's discipline gets right (summary)

Five properties of Prism's architecture are load-bearing for its safety claim. In priority order:

1. **External rubric grading on every load-bearing decision.** No LLM-as-judge on the decision the protocol actually cares about. Kernel: compile-and-run. Clinical: simple-evals.
2. **PoC validator gate: every finding ships with its executed artifact.** The adjudicator never asserts a finding is real; it confirms the artifact reproduced the claimed behavior.
3. **Double-gate for any live API or compute call.** `--commit` flag + `PRISM_*_COMMIT=1` env var, AST-verified SDK containment on 12 gated scripts.
4. **Frozen paths with enforced refusal.** Corpus reproducers, verifier scripts, normative specs, secrets, and state are untouchable by any agent session.
5. **Budget + wall-clock ceilings with explicit halt-on-hit.** Business-logic economic circuit breaker.

Points 1-2 are Prism's contribution to the field beyond what the AI-control literature specifies. Points 3-5 are standard-discipline implementations of generic defense-in-depth.

## 9. What is not yet implemented (upgrade paths)

In rough priority order, these are Prism-native upgrade paths the literature supports:

1. **Defer-to-Resample for borderline adjudicator verdicts.** Low-cost, well-motivated by Ctrl-Z (arXiv:2504.10374). One session-turn addition; no architectural change.
2. **Adversarial-attacker eval as a negative-control regression.** Attacker system-prompted to prioritize "adjudicator accepts" over "invariant actually violated." Pass = zero rubric-disconfirmed findings slip through. Belongs in `tests/`.
3. **Memorization probe for the clinical rail.** Perturbed HealthBench Hard items to measure canonical-form contamination. Complements the paired-design baseline.
4. **Collusion stress-test for multi-agent.** Run when `callable_agents` lands. Two Managed Agent instances, one prompted attacker, one prompted adjudicator, measure whether same-base-model collusion produces findings that escape the rubric.
5. **Application-level rate limiter** (§02 L8). Per-session and per-agent token-rate gates beyond the double-gate. Relevant if Prism ever runs autonomous sessions without the `--commit` manual step.
6. **Files API as finding-artifact binder.** Upload each finding's `results/*.json` + executed PoC log as immutable file pair; adjudicator's confirmation message references the pair by `file_id`. Makes chain-of-custody explicit for disclosure.

None of these is on the hackathon critical path; all are post-submission extensions.

## 10. Related Prism docs

- `CLAUDE.md` — operating charter; the source of truth for all discipline claims in this file.
- `docs/safeguards.md` — clinical-rail safeguards (physician-facing).
- `docs/disclosure-playbook.md` — kernel-rail disclosure playbook.
- `docs/sota-portfolio.md` — benchmark + technique portfolio; the driving document for what Prism should evaluate next.
- `docs/positioning-2026-04-22.md` — public-facing framing.
- `agents/*.yaml`, `skills/*/SKILL.md` — the role artifacts the Redwood correspondence in §2 above references.
- `scripts/run_solo_audit.py`, `scripts/run_skilled_audit.py`, `scripts/orchestrator.py` — the runtime entry points for the protocol.

See `sources.md` for every citation behind the AI-control correspondence claimed here.
