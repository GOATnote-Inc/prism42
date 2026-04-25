# Where are we going + Munger inversion — 2026-04-25

Integrator-written strategic frame for the remaining ~30 hours to the
hackathon submission deadline (Sunday 2026-04-26 5 PM PT). Companion to
findings/voice/synthesis.md (5-team OODA results).

## Where are we going

**Sunday 5 PM PT target** — a hackathon submission that demonstrates:

1. A live `/prism42/livekit` URL where a real call (microphone in, audio
   out) completes a full PSAP turn end-to-end through the self-hosted
   B300 stack: livekit-agents 1.5.6 worker → Parakeet TDT v3 STT
   (:9100) → vLLM 0.20 + Nemotron-3-Nano-NVFP4 (:8001) → Fish Speech
   S2-Pro TTS (:9200) → returned audio.
2. Honestly-measured e2e latency in the SOTA-competitive band. Floor
   acceptable: p95 ≤ 3500 ms (inside Hamming's industry p95 band 4.3-5.4 s
   AND beats Hamming's median). Stretch: p95 ≤ 1500 ms (the original
   cycle-1 acceptance gate).
3. Demonstrates kernel-level engineering depth — Phase D rebuild
   (CUDA 13 nvcc + flashinfer-cubin + native sm_103 vLLM build) in tree
   with 5/5 strict gates committed (a22a8f0). Engine TTFT p95 = 44.1 ms.
4. UI is honestly attested — every number on screen ties to a live
   measurement OR is gated behind a "synthetic demo" badge. No
   p50/p95/CALLER-NAME hardcodes masquerading as live.
5. Repo is submission-readable — a README that walks judges from
   problem → approach → numbers → reproduce. License posture is clean
   (no FARL Section III violations on hosted surface).

**Path to get there** (composes — each cycle is reversible):

```
cycle-1   enable_thinking=False + caller_spoke gate    DONE   PARTIAL
                                                              LLM p95 803→157 ms

cycle-2a  drop preroll always-on                       FLIGHT  predicted -2400 ms
                                                              → e2e ~4600 ms

cycle-2c  CUDA MPS (Fish HIGH / vLLM DEFAULT)          STAGED  T2 measured +95% RTF
                                                              degradation → fix
                                                              predicted -1300 ms
                                                              → e2e ~3300 ms

cycle-2d  Fish FLASH_ATTENTION + drop dense mask       STAGED  T1 + SGLang-Omni
                                                              proven recipe →
                                                              -750 ms predicted
                                                              → e2e ~2550 ms

cycle-2e  Pipecat-style sentence-boundary emission     STAGED  T4 ref V2V 500-700 ms
                                                              even with worse
                                                              component latency
                                                              → e2e likely ≤ 1500 ms

cycle-3   UI honesty pass + live metrics fan-out       PARKED  post-engine
cycle-4   README + 3-min demo video                    PARKED  submission-shape
cycle-5   human attestation (laptop + mobile)          PARKED  user gate
```

Each cycle ships a measured artifact under findings/b300_bench/e2e_voice/<ts>/
+ reversibility command in commit message. Each cycle has a backup file
on the pod retained under .pre-cycleN suffix. Each cycle is reversed
with one ssh command if it regresses.

## Munger inversion: how we GUARANTEE we don't make it

> *"All I want to know is where I'm going to die so I'll never go there."*
> — Charlie Munger

Inverted: don't ask "how do we ship by Sunday?" Ask "what would
guarantee we DON'T?" Then never go there.

### Failure modes that guarantee we miss the target

1. **Measurement contamination.** We ship a number that doesn't reflect
   reality. **Guard**: Team H harness audit must land BEFORE we re-bench
   any cycle. Audit must catch every hardcoded sleep, every hard
   assertion, every magic threshold. Already in flight; cycle-2a
   anticipator already found 2 (preroll-required assertion at L254-256;
   sleep(4.0) at L177).

2. **Optimization theater.** Apply a change, see a metric move, ship,
   discover the metric moved because of an unrelated harness artifact
   not the change. **Guard**: every cycle's bench compares ALL legs
   (stt, llm, fish, e2e), not just the headline. Cycle-1's PARTIAL
   verdict is the canonical example — e2e went UP because preroll was
   masking honest measurement.

3. **Compounding without isolation.** Apply MPS + Fish patch +
   Pipecat all in one cycle, fail to know which moved the needle, can't
   reverse cleanly when one regresses. **Guard**: cycle 2c, 2d, 2e are
   SEPARATE cycles each with their own bench artifact. Compose only
   after each is measured solo.

4. **Single point of failure pod.** B300 crashes Sunday morning, demo
   dies. **Guard**: ElevenLabs `/prism42` mainline fallback is FROZEN
   per CLAUDE.md §0 hackathon-mode bullet 2. Verify it still works
   24h before submission.

5. **License wall.** Ship hosted demo on Fish (FARL §III hosted-product
   commercial-license requirement) → submission flagged. **Guard**:
   either keep Fish internal-only and serve `/prism42/livekit` via
   Cartesia for the public URL, OR document the license posture
   transparently in the README and let judges assess.

6. **Hidden production drift between bench and demo.** Bench p95 is
   1500 ms; demo URL plays back at 4 s because something between the
   bench harness and the browser path differs. **Guard**: cycle-5
   (human attestation) is the actual ship gate. Do NOT ship without
   it.

7. **Agent context exhaustion.** A long-running orchestrator agent
   truncates mid-task (cycle-1 already did this — 98K tokens, 65 tool
   uses). **Guard**: bound each Claude Code Agent invocation tightly;
   for >4-hour iterative loops, evaluate Managed Agents (Team MA
   research in flight).

8. **Reversibility lost.** A patch lands, can't be undone, blocks the
   next cycle. **Guard**: every cycle's executor saves `.pre-cycleN`
   backup BEFORE pushing, and rollback command goes in the commit
   message AND in the artifact's result.json `rollback_status` field.
   `scripts/rollback_phase_e.sh` already shipped (commit ce0fe8e) for
   the LLM_BACKEND flip; equivalent needed for any production change.

9. **Documentation debt.** Ship a working demo with no README the
   judges can read. **Guard**: cycle-4 README is non-optional.
   Allocate at minimum 2 hours late Saturday for it. Use existing
   KB material (synthesis.md + 5-team deliverables) as source.

10. **UI-vs-engine schism.** Engine ships sub-1500 ms p95 but UI
    header still says `llm sonnet-4.6` + fake `p50 187ms`. Submission
    looks like theatre. **Guard**: cycle-3 UI honesty pass is the
    second-priority post-engine work after README.

### What this inversion means tactically NOW

- Every running team (cycle-2a executor + 4 pre-research teams + Managed
  Agents leverage research) has a Glasswing-disciplined scope and
  artifact. None can introduce theatre by themselves.
- The integrator (me) must NOT compose 2c+2d+2e in a single
  authorization. Each must land + bench solo before the next.
- The user attestation (task #87) is the actual ship gate.
  Schedule it for ~6-8 hours before submission so we have iteration
  budget if it surfaces a regression.
- ElevenLabs `/prism42` fallback gets one drift-check pass
  Saturday afternoon — not now, but pre-staged as an explicit task.

## Reversibility scoreboard

| Cycle | Patch surface | Rollback latency | Reversibility risk |
|---|---|---|---|
| 1 (Fix 1+2) | worker.py only | ~30s ssh+cp+restart | LOW (worker.py.pre-cycle1 saved) |
| 2a (drop preroll) | worker.py only | ~30s | LOW (worker.py.pre-cycle2a will be saved) |
| 2c (MPS) | systemd MPS daemon + service restarts | ~5min if vllm needs reattach | **MEDIUM** — vllm 14-min boot if it has to restart cold |
| 2d (Fish FA patch) | vendor/fish-speech tree + Fish service restart | ~2min Fish reboot | MEDIUM — Fish AR may diverge numerically |
| 2e (Pipecat retrofit) | worker.py + orchestrator.py | ~30s | LOW (file backups same pattern) |
| 3 (UI honesty) | mvp/911-console-live | git revert + redeploy | LOW (Vercel rollback) |

The MEDIUM-risk cycles (2c, 2d) deserve their own .pre-cycleN backups
AND a dry-run test where possible.

## Reading list when context is fresh

- `findings/voice/synthesis.md` — 5-team OODA results
- `findings/voice/where-are-we-going.md` — this file
- `findings/voice/managed-agents-leverage/recommendation.md` — Team MA, in flight
- `findings/voice/cycle-2a-anticipator/contingencies.md` — already done
- `findings/voice/harness-audit/audit.md` — Team H, in flight
- `findings/voice/cycle-2c-mps/runbook.md` — Team M, in flight
- `findings/voice/cycle-2d-fish-patches/recipe.md` — Team F, in flight
- `findings/voice/cycle-2e-pipecat/pattern.md` — Team P, in flight
- `findings/b300_bench/e2e_voice/20260425T123607Z/result.json` — cycle-1 PARTIAL baseline
- `CLAUDE.md` §0 hackathon mode rails

## When in doubt, the rule is

Glasswing > shipping a number we can't defend. If 2a alone gets us to
~3300 ms and the user authorizes ship, we ship — with the open-stack
path documented as future work. We do NOT ship a Cartesia-shimmed
sub-1500 ms demo with a README that brags about "self-hosted B300
stack" while the public URL is on a paid third-party API. That's the
exact theatre Munger's inversion tells us to avoid.
