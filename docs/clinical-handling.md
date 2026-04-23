---
title: Prism — Clinical Finding Handling and Disclosure
date: 2026-04-21
status: Draft
scope: Disclosure posture for clinical-rail findings — NOT-a-CVE framing, Anthropic feedback channel primary, physician-review gate mandatory.
---

### 1. Scope of a "clinical finding"

A clinical finding is a single `confirmed_delta` case produced by Prism's
harness on the clinical rail. Precisely: a HealthBench-Hard-style example
in which baseline Claude Opus 4.7 produces a response that violates the
published rubric, and the harness's modified path produces a response on
the same prompt, under the same model, that passes the rubric. The case
is only a finding once the adjudicator agent has returned a verdict with
every entry in `cross_checks` set to true — rubric agreement, score
delta above threshold, and no adjudicator-side abstentions. Anything
short of that (e.g. rubric ambiguity, a single cross-check false, judge
disagreement across trials) stays in internal review and is not treated
as a clinical finding for the purposes of this document.

### 2. NOT-a-CVE framing

Clinical findings are model-behavior observations, not kernel or code
defects. Concretely this means:

- No GHSA entry is filed.
- No CVE request is submitted.
- No embargo timer is started.
- No security-coordinator is involved.

The failure mode being reported is narrow: the best-available frontier
model, on this specific prompt, produced a clinically weaker answer than
the same model with a harness around it. That is a capability /
elicitation observation about a shipping model, not a vulnerability in
software.

Explicit contrast with the kernel rail: numerical-correctness findings
route through private channels (see `docs/kernel-research-posture.md`).
Clinical findings do not follow any of those paths. The routing below
is separate and deliberately lighter-weight.

### 3. Disclosure routing

**3a. Primary — Anthropic model-feedback channel.** Every clinical
finding goes to Anthropic first. Channel options are the thumbs-down
control on claude.ai attached to the offending conversation, or the
direct feedback form if one is active at the time of disclosure
(Anthropic model-feedback channel, thumbs-down UI or direct feedback
form). The packet contains: the rubric excerpt, the verbatim prompt,
the verbatim baseline response, the verbatim modified-path response,
the numeric delta score, and a one-sentence physician annotation
explaining why the baseline answer is clinically weaker than the
modified-path answer.

**3b. Secondary — research venue, only if the finding generalizes.**
If the same failure pattern is reproduced across multiple prompts and
appears to extend beyond Claude Opus 4.7 specifically, a public
write-up at a research venue (arXiv preprint, workshop paper) is
acceptable. The write-up is anonymized at the patient-scenario level,
links to Prism's methodology, and does not republish HealthBench Hard
rubric text beyond what OpenAI's `simple-evals` repository already
releases publicly. Generalization must be demonstrated — a single
model, single prompt failure does not qualify for secondary
disclosure.

**3c. Never.** These findings are not released via social media,
adversarial blog posts, or any framing that calls them a "bug" or a
"vulnerability." They are model-behavior observations reported to the
model provider. Anything more dramatic misrepresents the claim.

### 4. Redaction rules

All cases in scope come from synthetic fixtures produced under
`corpus/clinical/` or from HealthBench Hard, which is OpenAI-published
and contains no PHI by construction. The harness never touches real
patient data.

Before any external send, the packet is scanned for inadvertent PII —
real patient names, real provider names, real institution names, or
any identifier that could re-identify a person. A simple regex script
or a manual pass is acceptable; the point is that the pass is
performed and logged. The adjudicator's own notes are included in
that scan.

The underlying raw HealthBench Hard rubric text is not republished
beyond what `simple-evals` already releases publicly. OpenAI retains
the canonical rubric. Excerpts used in the disclosure packet are
limited to the criterion directly relevant to the finding.

### 5. Physician-review gate

No clinical packet leaves the repository without sign-off from the
physician-of-record — currently Brandon Dent, MD. The packet carries
a one-line attestation in a fixed form:

> Reviewed by Brandon Dent, MD, YYYY-MM-DD: clinical assessment
> concurs with adjudicator verdict.

If the physician-of-record does not concur with the adjudicator's
verdict, the finding is labeled `adjudicator_only` in the log and
stays internal. It is not sent to Anthropic, not written up for a
research venue, not referenced externally. The adjudicator can be
wrong; the human clinician is the final gate.

### 6. Cadence and severity triage

Default cadence is monthly batch disclosure: all findings accumulated
during a month ship together on the first business day of the
following month. Batching prevents flooding the feedback channel and
lets multiple findings be reviewed in a single physician sitting.

Hard-stop exception: if any finding plausibly describes patient-harm
potential in a real clinical deployment context — not the synthetic
benchmark context — it is disclosed immediately, tagged
severity-urgent, and carries an in-line note in the packet: "DO NOT
DEPLOY THIS MODEL CONTEXT without mitigation." HealthBench Hard is
not a live clinical system and its prompts are synthetic, so in
practice this trigger should be rare; it must still be treated as a
hard stop whenever a reviewer (adjudicator or physician) flags the
pattern as portable to real deployment.

### 7. Record-keeping

Each disclosed clinical finding is recorded in
`findings/clinical-log.jsonl`. The log is append-only and carries one
JSON object per line with the shape:

```
{
  "finding_id": "...",
  "case_id": "...",
  "disclosed_at": "YYYY-MM-DDTHH:MM:SSZ",
  "channel": "anthropic_thumbs_down | anthropic_feedback_form | research_venue",
  "physician_attestation": "Brandon Dent, MD, YYYY-MM-DD",
  "followup_status": "sent | acknowledged | closed | adjudicator_only"
}
```

`findings/clinical-log.jsonl` is gitignored. It is an operational log
that tracks outbound disclosures, not a public artifact. The on-disk
packet bodies live under `findings/private/` alongside the GPU-rail
drafts and follow the same never-push discipline.
