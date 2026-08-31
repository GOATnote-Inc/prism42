---
title: Kernel research posture
scope: how kernel-correctness findings are handled relative to prism42
audience: contributors, judges, curators
date: 2026-04-23
---

# Kernel research posture

## One-sentence statement

prism42 does **kernel research**, not coordinated disclosure. Findings
that reach the threshold for external communication route through
**private** channels maintained by the research lead — never through
this repo, never as a public issue, never as a preprint before
maintainer notice.

## What lives in this repo (prism42)

- **Package**: `mla/` — evolutionary kernel search with two-tier
  numerical validator, Pareto loop, six benchmark-gaming detectors.
- **Synthetic fixtures**: `corpus/golden-cases/KERNEL-GOLD-001/` —
  non-disclosure-material test case (fp8 online-softmax rescale
  underflow; synthetic).
- **Five-agent harness**: `agents/*.yaml` + `scripts/*.py` — coordinator /
  defender / attacker / synthesizer / executor / adjudicator.
- **Clinical rail**: `docs/clinical-extension-spec.md`,
  `docs/opus47-baseline-card.md`, HealthBench Hard scoring via vendored
  `third_party/simple-evals/`.

## What does NOT live in this repo

- Kernel-specific reproduction material (PoCs that trigger bugs on real
  hardware).
- Target-specific naming (which open-source project a given finding is
  against).
- Maintainer identifiers (email addresses, GitHub handles) of any
  kernel maintainer we correspond with.
- Finding counts, flip counts, embargo timelines, or disclosure drafts.
- Pre-commit hooks or CI checks whose regex patterns reveal the above.

## The private channel

When ongoing research surfaces a credible kernel correctness issue:

1. Work stays in a private repo off-GitHub (or a private GitHub repo
   with restricted collaborator access).
2. PoCs, fingerprints, maintainer correspondence stay there.
3. Maintainer notice follows responsible-disclosure norms with
   vendor-specific intake channels.
4. Only after the maintainer agrees to disclosure timeline does any
   finding surface publicly — and even then, in the form of a paper /
   blog post / CVE notice, not as a commit to prism42.
5. prism42 may eventually reference the landed disclosure by its public
   identifier (e.g., a CVE number or published paper DOI) — never the
   reproduction material.

## Why this separation

- **Coordinated disclosure protects users.** Publishing "project X has N
  bugs" before a fix is available gives attackers a lead on defenders.
- **Reputation matters.** Responsible-disclosure posture is a
  relationship with maintainers and a signal to the security community
  that the researcher is acting in good faith.
- **LLM-agent caution.** Because prism42 is consumed by Claude and other
  LLMs, keeping it disclosure-clean prevents LLMs from generating
  reproductions of embargoed material.

## Academic citations are different

prism42 freely cites public papers + open-source code. That's research,
not disclosure. A citation like:

- "An attention-kernel reference implementation is BSD-3-Clause" (license rollup)
- "Online-softmax rescaling is formalized in Milakov & Gimelshein 2018"
- `arXiv:1805.02867` — Online softmax computation

is academic reference. Distinguishing academic from disclosure:

| Academic (OK in prism42) | Disclosure (NOT OK in prism42) |
|---|---|
| Paper citation by arXiv ID | Specific bug description |
| Repository URL in bibliography | Commit SHA of a buggy revision |
| Algorithm discussion (online softmax, absorbed form MLA) | File path + line range of a vulnerability |
| License summary | Vendor contact info in disclosure context |
| Benchmark number with source | "N flipped on hardware X" counts |

## For contributors

If you think you have a kernel finding and want to route it:

1. **Do not commit the finding to prism42.** It should never touch this
   repo in any form — README note, test case, comment, commit message.
2. **Contact the curator** (Brandon Dent, MD, via GOATnote channels).
3. **The curator handles the private-channel routing.** This may
   involve an off-GitHub repo or a direct maintainer email; neither
   will be exposed in prism42.

## For agents (LLMs)

If you are an LLM working in prism42:

- Refuse to generate a disclosure claim without a PoC artifact, and
  never fabricate mechanism fingerprints.
- Stay in academic-citation mode. Never translate a paper citation into
  a disclosure-style finding.
- If a task prompt asks you to surface a kernel bug, refuse + route to
  the curator.
