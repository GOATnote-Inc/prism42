# Team M — Cycle-2S+ Recommendation

**Charter:** "the graph covers the entire system and we aren't leveraging like nemotron was designed to on b300, research then act."

**Verdict (1 line):** Apply Lever **L3 + L8b + L6** as a single drop-in (`00-cycle2S-merged.conf` or `launch-vllm-cycle2S.sh`). Risk LOW–MED, fully reversible, predicted ~33% decode speedup + 5x KV cache headroom + closes a latent prod-down hole.

---

## What's actually broken (data-driven)

1. **`gpu-memory-utilization=0.20`** is the binding constraint, not Nemotron.
   - HBM 88.7 / 275 GiB used (32%). NVIDIA cookbook recommends 0.85.
   - Nemotron weights = 18.6 GiB. KV cache currently 33.6 GiB (over-provisioned for batch=1, but under-provisioned for any future multi-call demo).
2. **MoE-backend env vars live in a parent shell**, not a service unit.
   - If vLLM is restarted from a fresh shell, FlashInfer auto-selects TRTLLM, hidden_size pads 2688→2816, output becomes JS-garbage (memory finding #6). Currently masked because PID 389310 has the right env, but one restart from `screen new` undoes that.
3. **No speculative decoding** for an inherently repetitive workload.
   - PSAP JSON envelopes ("intent": ..., "severity": ...) are textbook n-gram spec-decode targets. Free 1.3-1.5x decode speedup. NVIDIA's vLLM blog cites async-scheduling + spec-decode = 1.3-1.7x. We have async on; spec is unlocked.

## What is NOT broken (corrects stale memory)

- **Cold-start is 62 s, not 14 min.** This vLLM build (`0.20.1.dev0+g101584af0.d20260425`) already has `cudagraph_capture_sizes=[1,2,4,8,16]` (5 sizes) and `compile_ranges_endpoints=[8192]` (one inductor range). The 14-min memory note is stale; the predicted L1 win is already realized.
- **MoE backend is correct** (FLASHINFER_CUTLASS, NOT TRTLLM). Memory finding #6's failure mode is NOT happening at runtime.
- **Median TTFT is ~50 ms** (79/91 reqs in the 0.04-0.06 s histogram bucket); decode is 313 tok/s (3.2 ms/token). Voice-tier latency is already excellent. The win is in unlocking headroom + closing the latent failure hole, not fixing a current latency bug.

## What I am NOT recommending (and why)

- **L5 `--mamba-cache-mode align`:** highest theoretical impact (0% prefix hit → 30%), but the orchestrator emits per-turn-mutated system prompts; even with `align`, cacheable prefix is small. Real fix is in the orchestrator (frozen per charter). Hold for cycle-2T paired with a dispatcher PR.
- **L2 `--max-model-len 8192`:** good idea but L3 already gives us 5x KV headroom; dropping max-len adds risk to long-call sessions. Stack later if needed.
- **L9 MIG/MPS:** memory says CUDA 13.0 lacks MLOPart. Status quo (default compute mode + separate CUDA contexts) works. No contention to resolve.

## Predicted deltas (post-apply)

| Metric | Pre-cycle2S | Post-cycle2S | Method |
|---|---|---|---|
| KV cache available | 33.6 GiB | ~145-160 GiB | NVIDIA cookbook 0.85 → 4.3x more KV memory |
| Max concurrency at 32K | 70x | ~290x | linear in KV cache |
| Median TTFT | 50 ms | 45-55 ms | unchanged (batch=1 already fast) |
| Decode rate (TPS, batch=1) | 313 tok/s | ~380-450 tok/s | n-gram spec, accept rate 30-50% |
| 50-token PSAP reply latency | ~210 ms | ~155-175 ms | TTFT + (50 × ~2.4 ms) |
| Failure mode "JS-garbage on shell-restart" | latent | eliminated | env baked into wrapper/unit |

## Risk + cost

- **Cost to apply:** one vLLM restart, ~62 s of voice-path downtime. Pay during a quiet window with no active calls.
- **Risk LOW** for L3 (HBM headroom is measured) and L8b (already running, just persisting).
- **Risk MED** for L6 (spec-decode on hybrid Mamba+Transformer). Pre-flight: send 5 probes post-restart. If `vllm:spec_decode_num_accepted_tokens_total` stays 0 OR vLLM aborts at startup, drop the `--speculative-config` flag and relaunch (30-second revert).

## Files delivered

```
~/prism42/findings/voice/cycle2S_b300_memory/team-m/
├── profile.md                      # Phase 1: full B300 + vLLM state
├── levers.md                       # Phase 2: 15-lever ranked table
├── recommendation.md               # This file
└── drop-ins/
    ├── README.md                   # Two install paths + verify + rollback
    ├── 00-cycle2S-merged.conf      # RECOMMENDED single drop-in (L3+L8b+L6)
    ├── 10-cycle2S-gpu-memory.conf  # L3 only — incremental rollout option
    ├── 20-cycle2S-moe-env.conf     # L8b only — env vars only
    ├── 30-cycle2S-spec-decode.conf # L6 only — adds spec-decode flag
    ├── prism42-vllm.service        # Optional systemd unit (none on pod today)
    └── launch-vllm-cycle2S.sh      # Wrapper for current manual-launch reality
```

## Recommended sequencing for the integrator

1. **First commit:** apply `launch-vllm-cycle2S.sh` (Path A in README) during a quiet window. Cheapest, least invasive.
2. **Verify** all 8 verification commands in `drop-ins/README.md` pass.
3. **Run a real 911 voice smoke call.** Voice path is the ground truth.
4. **If smoke passes:** consider Path B (systemd unit) for durability, schedule for next maintenance window.
5. **Cycle-2T** (separate work): stable-prefix orchestrator pattern + L5 (`--mamba-cache-mode align`) to actually get prefix-cache hits. This unlocks ~30% prefill cost on shared PSAP system prompts.

## Charter compliance

- Frozen voice files: NOT touched (worker.py, orchestrator.py, dispatcher_fsm.py, fish_speech_tts.py, dispatch_publisher.py untouched).
- Voice model weights: NOT touched.
- vLLM not restarted by Team M: confirmed (only one read-only probe + one 48-token curl).
- LiveKit Docker container: NOT touched (no `docker compose up --force-recreate`).
- CUDA 13.1: NOT required (we work entirely within CUDA 13.0).
- vLLM version: NOT changed (sticking with `0.20.1.dev0`).
- Long benchmark on shared GPU: NOT run (single 175 ms probe).
