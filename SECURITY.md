# prism42 Security Policy

## Purpose

prism42 is a Managed Agents harness on Claude Opus 4.7 that audits (a)
numerical correctness in GPU inference kernels and (b) clinical reasoning
on public benchmarks. This policy covers **the security of the auditor and
its infrastructure**, not a coordinated-disclosure channel for kernel
findings.

prism42 carries no embargoed reproduction material, no target-specific
naming, and no maintainer identifiers. Kernel findings that reach the
threshold for external disclosure route through private, off-repo channels
(see `docs/kernel-research-posture.md`). Clinical findings route through
Anthropic's model-feedback channel after physician review (see
`docs/clinical-handling.md`).

## Scope

This policy applies to:

1. **Prism's own codebase** — harness runners, agents, skills, schemas,
   CI workflows, tooling.
2. **Generated artifacts** — case directories, verdicts, rubric-graded
   session outputs under `results/`.
3. **Third-party pins** — `third_party/simple-evals/` (cloned at CI/setup
   time at a pinned commit, MIT — never committed in-tree; see
   `third_party/README.md`).

Out of scope (separate policies):

- Kernel-research findings — `docs/kernel-research-posture.md`.
- Clinical model-behavior observations — `docs/clinical-handling.md`.
- Anthropic Managed Agents platform itself — Anthropic's responsibility.

## Report a vulnerability in Prism itself

If you discover a security issue in Prism's harness code (not in a target
being audited), please report it:

- **Email**: security@goatnote.app (with `b@thegoatnote.com` CC'd).
- **GitHub private security advisory** on this repo.
- Do not open a public issue for security findings; use the channels above.

We acknowledge within 5 business days and aim to remediate within 30 days,
faster for critical issues. Good-faith security research is welcomed.

## What counts as a Prism security issue

Examples:

- Authentication / credential handling (`.env` lifecycle, double-gate bypass).
- SDK containment bypass (`anthropic` imported outside `do_commit()`).
- Schema-validation bypass (malformed artifacts accepted by L1 check).
- CI / pre-commit hook bypass.
- Supply-chain issues in `third_party/` pins.
- PII / PHI leakage from logs, caches, or published artifacts.

## Safeguards enforced by code

- **Double-gate on live LLM / compute calls.** `--commit` flag + `PRISM_*_COMMIT=1`
  env var. Default dry-run. AST-verified by `scripts/check_sdk_containment.py`.
- **Schema validation on every case-dir artifact** (L1 gate).
- **Pipeline invariants check** (L4) — model pins, role↔filename
  correspondence, egress allowlist, no secret mount, manifest shape,
  schemas compile.
- **Pre-commit hooks** block target-specific naming and secrets.
- **Physician-review gate** on clinical findings — adjudicator's
  `physician_review` field; generators never pre-sign.

## Clinical-finding handling (summary — see `docs/clinical-handling.md`)

Clinical findings are model-behavior observations, not vulnerabilities.
Private routing: physician review → Anthropic model-feedback channel.
Never public issue tracker, never preprint before review, never social.
No PHI. Synthetic fixtures only.

## Kernel-research-finding handling (summary — see `docs/kernel-research-posture.md`)

prism42 does kernel-research, not coordinated disclosure. If research
surfaces a credible kernel correctness concern, it routes through a
private channel maintained by the research lead, off this repo. prism42
intentionally excludes reproduction material, target-specific naming,
and maintainer contact data from its public surface.

## Acknowledgments

This policy draws on CERT/CC coordinated-disclosure norms and Redwood AI
Control protocol hygiene. See `docs/runaway-ai-kb/` for the full literature
map.
