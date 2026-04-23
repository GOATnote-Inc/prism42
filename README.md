# Prism

**An Opus-4.7 auditor of Opus-4.7. Every finding ships with an executed artifact.**

Prism is a Managed Agents harness built on Claude Opus 4.7 that audits two
high-stakes targets under the same dialectic: numerical correctness in GPU
inference kernels and clinical reasoning on HealthBench Hard. Every kernel
finding is a PoC compiled and executed on real GPU hardware; every clinical
finding is a rubric-graded model-behavior delta, physician-gated before it
leaves the repo.

No speculative findings. No benchmark numbers we didn't measure ourselves.
No AI-slop.

## Three chapters, one harness

1. **Kernel-correctness rail** — evolutionary MLA / NVFP4 kernel search
   with a two-tier numerical validator and a clean-process rubric.
   Cross-vendor portability target: flagship NVIDIA accelerators, Google TPU
   via Pallas, AWS Trainium via NKI. See `mla/` for the package.
2. **Clinical-reasoning harness** — Opus 4.7 baseline + five-agent
   dialectic on HealthBench Hard. N ≥ 3 baseline runs with 95% CI;
   paired design for the harness delta (CI excludes 0 gate). Safeguards:
   physician-in-loop, no PHI, not for clinical use.
3. **Voice surface** — ElevenLabs front-end on the clinical harness with
   stopwatched p95 latency (Phase-V rule: cut at p95 > 4 s).

The five-agent design (coordinator / defender / attacker / synthesizer /
executor / adjudicator) is rail-agnostic — the executor branches on
`case.rail`.

## Clinical rail — HealthBench Hard

Defender asserts a rubric invariant, attacker perturbs the prompt,
synthesizer packages a candidate delta, executor runs stock Opus 4.7 vs.
harness-modified Opus 4.7 against the OpenAI `simple-evals` grader,
adjudicator scores. **The harness does not grade itself.**

Every technique ships only after an external public-benchmark delta:

| Benchmark | Role | Grader |
|---|---|---|
| HealthBench Hard | primary clinical metric | `simple-evals` (Apache 2.0, vendored pinned @ `third_party/simple-evals/`) |
| MedQA (USMLE) | null-result control — `|Δ|` must be small | exact-match |
| PubMedQA | RAG validator — retrieval must lift ≥10 pp | exact-match |
| MMLU-Medical-6 | breadth / null-result | exact-match |
| MedAgentBench | agentic clinical (H1 epic) | side-effect verifier |

### Opus 4.7 baseline card

Anthropic's Opus 4.7 launch page publishes zero medical benchmarks. Prism
establishes the full public suite, one run at a time. Every row in
`docs/opus47-baseline-card.md` is either a direct quote from a named
source with a fetch-date, or `pending`.

Baseline + harness deltas follow the determinism-aware gate defined in
`CLAUDE.md` §4: aggregates reported as mean ± 95% CI over N ≥ 3 runs;
the paired harness-delta CI must exclude 0 at α=0.05 before any
technique ships.

### Clinical findings are not CVEs

Clinical findings are model-behavior observations that route privately
through Anthropic's feedback channel after physician review —
**never** a public issue tracker, **never** a preprint before review,
**never** a social-media thread. Physician-in-loop gate is enforced
by the adjudicator's `physician_review` field in `verdict.json` (code
never pre-signs it). Disclosure posture: `docs/clinical-handling.md`.
Physician-facing 60-second safeguards summary: `docs/safeguards.md`.

## Reproduce

```bash
git clone https://github.com/GOATnote-Inc/prism42
cd prism42
make verify-all                        # offline tests green across 5 layers
make clinical-demo-artifacts-commit    # synthetic rubric cards (physician-review-required)
```

Live Managed Agents smoke (requires `ANTHROPIC_API_KEY` in `.env`;
~$0.15 per run):

```bash
PRISM_SMOKE_SESSION_COMMIT=1 python scripts/smoke_session.py --commit
```

## Repo map — where to look

```
CLAUDE.md                              Operating contract (§8 for Managed Agents specifics)
docs/clinical-extension-spec.md        Normative clinical-rail contract (frozen path)
docs/clinical-roadmap.md               Task DAG + dispatch protocol
docs/sota-portfolio.md                 Technique portfolio + benchmark grammar
docs/safeguards.md                     Physician-facing 60-second safeguards page
docs/opus47-baseline-card.md           Every quoted Opus 4.7 medical benchmark, with fetch-date
docs/clinical-handling.md              Clinical-finding disclosure posture (physician-gated)
docs/kernel-research-posture.md        Kernel-research disclosure posture (private channels)
docs/runaway-ai-kb/                    AI-control literature mapped onto Prism's dialectic
docs/anthropic-elevenlabs-agent-bp-*.md  ElevenLabs + Opus 4.7 voice stack reference
agents/*.yaml                          6 agent configs (coordinator + 5 sub-agents)
agents/manifest.yaml                   Live Anthropic IDs after register_agents.py --commit
environments/prism-standard-env.yaml   BetaCloudConfigParams body (limited networking, 4-host allowlist)
scripts/register_agents.py             Double-gated; writes manifest on success
scripts/smoke_session.py               Live session smoke (event-channel proof)
scripts/smoke_delegation.py            Live delegation smoke (gate-aware)
scripts/generate_clinical_demo_artifacts.py  Clinical demo artifact generator
scripts/check_sdk_containment.py       AST guard: SDK import only inside do_commit()
scripts/check_pipeline_invariants.py   Model pins, role-filename, egress, mounts, manifest, schemas
corpus/clinical-demo/CLN-DEMO-*/       Synthetic clinical fixtures (not PHI)
corpus/golden-cases/KERNEL-GOLDEN/     Synthetic kernel regression fixture
corpus/golden-cases/HBH-CLN-SYNTH/     Synthetic clinical golden case
corpus/mla/                            MLA oracle + reference implementations
findings/*.md                          Evidence + smoke reports (no embargoed material)
mla/                                   Evolutionary MLA/NVFP4 kernel package (validator + runners + evolve loop)
tests/                                 pytest suite; offline verification green in CI
music-video/                           Subtree; Opus-4.7 video editor
mvp/                                   PSAP / 911 console research prototypes
```

## Verification discipline

Five offline layers gate every commit. Matches `.github/workflows/verify.yml`.

| Layer | Command | Proves |
|---|---|---|
| L1 schema | `scripts/validate_artifacts.py` | Every case-dir artifact matches its JSON Schema 2020-12 |
| L2 agent | per-agent output validation | Agent emitted a parseable, schema-aligned verdict |
| L3 regression | `make validate-golden` | `KERNEL-GOLDEN` and `HBH-CLN-SYNTH` fixtures still pass |
| L4 invariants | `scripts/check_pipeline_invariants.py` | Model pins, role↔filename, egress allowlist, no-secret-mount, manifest shape, schemas compile |
| L5 CI | `.github/workflows/verify.yml` | Offline-green on every push |
| T3 umbrella | `make verify-all` | All of the above + generator dry-runs |

No commit ships without `make verify-all` green. SDK containment is
AST-verified by `scripts/check_sdk_containment.py` across gated scripts —
the `anthropic` SDK may only be imported inside `do_commit()`, never at
module scope.

## Hard rules (excerpted from `CLAUDE.md`)

- Every action ends with a verification step whose exit code proves the claim.
- Any script that spends money or calls an external LLM is gated by TWO
  independent signals: `--commit` flag + `PRISM_<COMPONENT>_COMMIT=1`
  env var. Either alone stays dry-run.
- No technique ships without a measured delta on a Phase B scorer.
- Frozen paths (`docs/clinical-extension-spec.md`, `.env`, `.state/`) are
  read-only.

## Research posture

Prism performs kernel-correctness research against public open-source
code, running on hardware we rent by the hour. Kernel findings that reach
the threshold for disclosure route through **private** channels, never
through this repo; see `docs/kernel-research-posture.md` for the
contract. This repo intentionally carries no embargoed material, no
target-specific naming, and no reproduction fingerprints.

## Credits

- Claude Opus 4.7 — the auditor and the audited.
- OpenAI `simple-evals` (Apache 2.0) — HealthBench Hard rubric grader.
- Anthropic Managed Agents — research-preview multi-agent.
- GOATnote-Inc — Brandon Dent, MD (emergency medicine, physician-of-record).

## License

MIT. See `LICENSE`. Third-party code under `third_party/` retains its
upstream license; attribution in `NOTICE`.
