---
title: Prism — threat model and intended use
date: 2026-04-22
audience: Researchers, maintainers, and contributors reading the repo cold. Complements `docs/safeguards.md` (clinical-facing) and `SECURITY.md` (disclosure intake).
scope: Names the dual-use surface honestly, the boundary between authorized and unauthorized use, and the disciplines Prism enforces in code rather than aspiration.
---

# Threat model and intended use

## What Prism is for

Prism is a research harness for auditing two things:

- **Numerical correctness** in GPU kernels (open-source attention and MLA-decode implementations on flagship NVIDIA hardware, and accelerator-native kernels on AWS Trainium), verified by compiling and running a proof-of-concept on real GPU or Trainium hardware.
- **Reasoning correctness** in clinical-decision surfaces (HealthBench Hard rubric), scored by OpenAI's `simple-evals` grader under a paired-design gate whose 95% CI must exclude zero.

The common substrate is a five-role adversarial dialectic (defender / attacker / synthesizer / executor / adjudicator, coordinated by a coordinator role) run against Claude Opus 4.7 as Anthropic Managed Agents. See `docs/runaway-ai-kb/04-prism-architecture-mapping.md` for why this shape is load-bearing.

## What Prism is explicitly not for

- General-purpose vulnerability scanning of third-party software.
- Audits of systems you do not maintain or do not have authorization to audit.
- Adversarial probing of production services, hosted endpoints, or other people's infrastructure.
- Any patient-facing clinical use. All clinical fixtures are synthetic; the harness does not accept PHI and has no medical-device clearance.
- Publishing a finding — kernel or clinical — without routing through the disclosure pipeline in `SECURITY.md`.

## Dual-use honesty

The same five-role dialectic that surfaces a pre-fix NaN in an attention kernel can, with changed invariants, be pointed at arbitrary targets. Publishing the architecture is a net-positive call — Inspect AI, ControlArena, PyRIT, garak, and HarmBench are all public — but the call does not erase the surface. We name it here rather than pretend it does not exist.

Three concrete uplift vectors anyone forking Prism should acknowledge:

1. **Prompt shape.** `agents/*.yaml` system prompts become fingerprintable once public; future Opus-4.7 red-team work using similar shapes becomes attributable or mis-attributable to the Prism pattern.
2. **Protocol leverage.** The correspondence with the Redwood AI Control protocol family (see runaway-AI KB `04-prism-architecture-mapping.md`) makes it explicit which attacks this architecture is known to be weak against — adaptive attacks on trusted monitors (Mallen et al. 2025), monitor collusion under shared-model regimes (TraceGuard 2026). A hostile operator can use that map to design prompts that slip Prism's adjudicator.
3. **Execution surface.** The executor role calls real compute (SSM → H100 / Trainium, or local Python). Prism ships a double-gate (`--commit` + `PRISM_*_COMMIT=1`) and AST-verified SDK containment on twelve runners; a fork that removes those is a supply-chain concern.

## Discipline that is code, not aspiration

Prism's safety claims are only valid to the extent they are enforced by the codebase. The enforced disciplines are:

- **External-rubric grading on every load-bearing decision.** Kernel findings: deterministic compile-and-run via a PoC validator. Clinical findings: `simple-evals` rubric grader, not an LLM self-grade. Enforced by `scripts/pipeline_invariants.py`.
- **Double-gate for any live API or compute call.** Both `--commit` flag and `PRISM_*_COMMIT=1` environment variable must be present. Default is dry-run. AST-verified by `scripts/check_sdk_containment.py` across twelve gated runners.
- **Frozen paths that agent sessions cannot modify.** `docs/clinical-extension-spec.md`, `.env`, `.state/`. Enforced by the orchestrator's immediate-refusal policy.
- **`physician_review` field that only a human can set.** The adjudicator verdict schema includes it; generators never pre-sign. Enforced by `scripts/validate_artifacts.py` L1 schema check.
- **Budget and wall-clock ceilings with explicit halt-on-hit.** `CLAUDE.md` §9; orchestrator cap is 900 seconds per run, $25 default.
- **`findings/private/` gitignored.** Novel findings cannot reach `main` by accident. Enforced by `.gitignore` + CI's offline verification layer.

Breaking any one of the above is a protocol violation, not a feature. A PR that weakens any of these must declare it in the PR body and name a compensating control.

## Authorized-use contract for contributors

By contributing to Prism or using Prism-derived code, you agree that:

1. You will only audit targets you maintain or have written authorization to audit.
2. You will route any finding — kernel or clinical — through `SECURITY.md` before any public mention.
3. You will not remove or weaken the disciplines enumerated above without a compensating control that preserves the same invariant.
5. For clinical work: you will not use Prism to generate advice for a real patient.

## Incident response

If you believe Prism has been misused, or you find an operational-security issue in Prism itself (not in a kernel it audits), email `b@thegoatnote.com` with subject `PRISM-OPSEC`. If a kernel or clinical finding is leaking from Prism inadvertently, email the same address with subject `PRISM-LEAK`. We will respond within 48 hours.

Kernel vulnerabilities in targets Prism audits go through `SECURITY.md`, not through this doc.

## Related reading

- `docs/safeguards.md` — clinical-rail safeguards, physician-facing.
- `SECURITY.md` — vulnerability intake, severity rubric, PoC requirement.
- `docs/disclosure-playbook.md` — kernel disclosure playbook.
- `docs/runaway-ai-kb/04-prism-architecture-mapping.md` — the AI-control-protocol mapping referenced above.
- `docs/runaway-ai-kb/03-oss-landscape-and-gap.md` — where Prism sits vs existing OSS red-team / guardrail / control frameworks.
- `CLAUDE.md` — operating charter; the source of truth for every discipline claim above.
