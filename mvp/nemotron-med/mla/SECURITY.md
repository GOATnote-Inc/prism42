# Security policy

## Reporting a vulnerability

If you find a security issue in this repository — including in any generated
kernel that this repository's evolve loop produces — please report it
responsibly.

**Do not** open a public GitHub issue for security-sensitive findings.
Instead, email: `b@thegoatnote.com` (GPG key available on request).

Expected response time: 72 hours for initial acknowledgement, 30 days for a
disposition.

## Scope

This repository provides scaffolding for evolutionary discovery of GPU
kernels. Security-relevant surfaces include:

1. **The safety gate** (`agent/safety.py`). This module blocks imports,
   dangerous built-ins, and known-dangerous torch APIs in LLM-generated
   source. If you find a bypass (code that runs `os.system`, loads a native
   extension, exfiltrates, etc. despite passing `compile_candidate` or
   `compile_candidate_torch`), report it privately.

2. **The validator** (`prism/validator.py`, `prism/validator_torch.py`).
   If you find a kernel that passes the two-tier validator but produces
   numerically-incorrect outputs on inputs the validator did not exercise,
   report it privately. These are candidate *adversarial numerics* issues
   and are in scope.

3. **The benchmark harness** (`scripts/isolated_bench.py`,
   `scripts/_bench_worker.py`). If you find a benchmark-gaming pattern
   that the harness does not detect, report it privately so we can add it
   to the `gaming_patterns.py` catalogue (Robust-KBench-style).

4. **The runpod provisioner** (`runner/runpod_provisioner.py`). If you find
   a way to cause cost-incurring API operations to run without
   `confirm=True`, report it. That's a direct financial exposure.

## Out of scope

- Issues in dependencies (torch, flashinfer, numpy, anthropic SDK, requests,
  pytest). Report those upstream.
- Issues in the RunPod REST API itself. Report to runpod.io.
- Issues in the Anthropic API. Report to Anthropic's responsible-disclosure
  channel.

## Dependency license and distribution stance

- This repository is Apache-2.0 licensed.
- No GPL-licensed code is fork-included.
- The CuTe DSL (NVIDIA/cutlass `python/CuTeDSL/`) is under NVIDIA EULA and
  is never forked or redistributed here. Any reference is permalink-only.
- The `prism-mla-archive/ledger/provenance.md` companion ledger tracks
  the license + access date of every cited source.

## Evolve-loop-specific disclosures

Kernels discovered by the evolve loop that reveal bugs in upstream open-source
attention / MLA implementations will be reported under each project's respective
security policy. We do not publish un-disclosed bugs
in public benchmarks. See `mental-models/red-team-adversarial.md §3` in the
archive for the numerics-as-weapon threat model this policy addresses.

## Attribution

Reports that lead to a substantive improvement are credited in
`SECURITY_HALL_OF_FAME.md` (to be created as needed) with reporter's
permission.
