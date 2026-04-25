# Sources — cycle-2c MPS documentation refresh

All retrieved 2026-04-25. Tagged: `[B300]` verified-on-Blackwell-sm_103, `[B200]` verified-on-sm_100, `[H100]` verified-on-Hopper, `[U]` claimed-unverified, `[STABLE]` foundational doc reference (older but normative).

## A1. NVIDIA published changes

1. **CUDA 13.1 release blog** — `[B300]` `[STABLE since 2025-12-04]`
   - https://developer.nvidia.com/blog/nvidia-cuda-13-1-powers-next-gen-gpu-programming-with-nvidia-cuda-tile-and-performance-gains/
   - Released 2025-12-04. Explicit: *"In CUDA 13.1, we introduced the `-mlopart` option."* MLOPart explicitly applies to "Blackwell (compute capability 10.0 and 10.3)" — this includes B300.

2. **MPS Tools and Interface Reference** — `[B300]` `[STABLE]`
   - https://docs.nvidia.com/deploy/mps/appendix-tools-and-interface-reference.html
   - Authoritative `start_server -uid <uid> [-mlopart]`, `--static-partitioning` / `-S` daemon flag. Lists ALL control commands including `sm_partition add/rm`, `lspart`, `device_query`, `terminate_client`. `CUDA_MPS_CLIENT_PRIORITY` values: `0=NORMAL`, `1=BELOW_NORMAL`.

3. **MPS Overview PDF (r590, 2025-12-05)** — `[B300]` `[STABLE]`
   - https://docs.nvidia.com/deploy/pdf/CUDA_Multi_Process_Service_Overview.pdf
   - Doc revision r590 dated 2025-12-05. Latest r595.58.03 (Arch package) is referenced separately. Specifies Volta MPS server now supports 60 client CUDA contexts (up from 48 in CUDA 13.0).

4. **MPS "When to Use MPS"** — `[STABLE]`
   - https://docs.nvidia.com/deploy/mps/when-to-use-mps.html
   - *"MIG devices do not support MLOPart. Using MIG on one GPU does not prevent using MLOPart on another GPU."* And: *"When using MPS it is recommended to use `EXCLUSIVE_PROCESS` mode."*

5. **Boost GPU Memory Performance with CUDA MPS blog** — `[B200]` (NOT verified on B300)
   - https://developer.nvidia.com/blog/boost-gpu-memory-performance-with-no-code-changes-using-nvidia-cuda-mps
   - Published 2025-12-17. Benchmark on B200/HGX B200: MLOPart 2314.5ms→1480.8ms (36% latency cut on atomic-ops kernel). Article notes: *"MLOPart is currently only supported on x86 platforms."* Not vLLM-specific.

6. **Blackwell Compatibility Guide 13.2** — `[B300]` `[STABLE]`
   - https://docs.nvidia.com/cuda/blackwell-compatibility-guide/
   - sm_103 from CUDA 12.9.

7. **CUDA 13.0 Release Notes (archive)** — `[B300]` `[STABLE]`
   - https://docs.nvidia.com/cuda/archive/13.0.0/cuda-toolkit-release-notes/index.html
   - Pod's CUDA. No MLOPart, no `--static-partitioning`.

8. **CUDA 13.2 Update 1 Release Notes** — `[B300]` `[STABLE]`
   - https://docs.nvidia.com/cuda/cuda-toolkit-release-notes/index.html
   - Latest. Confirms 13.1 features carry forward.

9. **NVIDIA Devtalk: MPS on GB10 thread** — `[U]` (Grace-Blackwell GB10 unified-memory specific, NOT B300 SXM)
   - https://forums.developer.nvidia.com/t/mps-support-and-telemetry-on-grace-blackwell-gb10-with-unified-memory/363137
   - Posted 2026-03-11/23. *"nvmlDeviceGetMemoryInfo returns NVML_ERROR_NOT_SUPPORTED because there's no discrete framebuffer."* Workaround LD_PRELOAD shim. **Not applicable to our discrete-HBM3E B300 SXM6 pod** but flags monitoring caveats.

10. **NVIDIA Devtalk: static partitioning on Jetson Orin Nano** — `[U]` (Jetson, not B300)
    - https://forums.developer.nvidia.com/t/static-partitioning-failed-with-nvidia-mps-on-jetson-orin-nano/363234
    - Posted 2026-03-18. NVIDIA AastaLLL: *"Static partitioning is a new feature from CUDA 13.1. So this is not supported in CUDA 12.6."* — confirms 13.1 gate.

## A2. vLLM project changes

11. **vLLM Releases page** — https://github.com/vllm-project/vllm/releases — `[B300]`
    - v0.20.0 (released 2026-04-23): "Allreduce fusion enabled by default" on B300/GB300 (SM 10.3); FA4 default MLA prefill on SM90+. Pod runs `0.20.1.dev0+g101584af0.d20260425` (post-0.20.0).
    - No MPS-specific change in 0.20.0 release notes.

12. **vLLM CUDA Graphs design doc** — `[STABLE]`
    - https://docs.vllm.ai/en/stable/design/cuda_graphs/
    - Five `cudagraph_mode` modes (NONE, PIECEWISE, FULL, FULL_DECODE_ONLY, FULL_AND_PIECEWISE). Default is `FULL_AND_PIECEWISE`. `cudagraph_capture_sizes` controls which batch sizes are captured.

13. **vLLM Issue #37242 — RTX 5090 + WSL2 2.7.0 CUDA graph startup** — `[U]` (sm_120, not sm_103)
    - https://github.com/vllm-project/vllm/issues/37242
    - WSL2 2.7.0 dropped CUDA graph startup from ~90s (`--enforce-eager`) to ~25s. **Empirical evidence that small `cudagraph_capture_sizes` reduces capture time** — but not measured on B300.

14. **vLLM Recipe — Nemotron-3-Nano-30B-A3B** — `[B300]`
    - https://docs.vllm.ai/projects/recipes/en/latest/NVIDIA/Nemotron-3-Nano-30B-A3B.html
    - Notes Blackwell B200/B300 supported; CUDA 12.8+ required (we have 13.0). `--max-num-seqs` and `--tensor-parallel-size` are the two main tunables.

15. **vLLM Blog: Nemotron-3-Nano post** — `[B200]`/`[H100]`
    - https://blog.vllm.ai/2025/12/15/run-nvidia-nemotron-3-nano.html (redirects to vllm.ai/blog/run-nvidia-nemotron-3-nano)
    - Published 2025-12-15. NVFP4 delivers "4x throughput on B200 compared to FP8-H100". No MPS-specific guidance.

16. **vLLM Issue #35065 — Nemotron NVFP4 fails on sm_120** — `[U]` (sm_120, not sm_103)
    - https://github.com/vllm-project/vllm/issues/35065
    - "No NvFp4 MoE backend supports the deployment configuration" on RTX 5090. Our pod ran NVFP4 successfully via FLASHINFER_CUTLASS, so sm_103 path differs from sm_120.

17. **Allen Kuo Medium: vLLM or Ollama on Blackwell** — `[U]` (RTX PRO 6000, sm_120)
    - https://allenkuo.medium.com/vllm-or-ollama-on-blackwell-benchmarks-landmines-and-what-agents-actually-need-5dc539bb28ef
    - Published 2026-04-08. `--enforce-eager` cost: decode TPS -40%, TTFT +97%, concurrent throughput -44%. *"CUDA graphs account for 40-77% of vLLM's performance advantage."* **This is the strongest published number for the cost of `--enforce-eager` as a startup-time mitigation.**

## A3. FlashInfer changes

18. **FlashInfer Releases** — `[B300]`
    - https://github.com/flashinfer-ai/flashinfer/releases
    - **v0.6.9 released 2026-04-24** (yesterday): "Add SM 103 as one of supported capabilities for mm_M1_16_K7168_N256"; "Add CuTe-DSL backend for NVFP4 quantization"; routing_replay_out for MoE.
    - **v0.6.8 released 2026-04-16**: "use float instead of double in sampling binary search to avoid FP64 bottleneck on SM103" — **directly affects B300, since B300 has gutted FP64**.

19. **FlashInfer Issue #2723 — SM120 CUTLASS Grouped GEMM patches** — `[U]` (sm_120)
    - https://github.com/flashinfer-ai/flashinfer/issues/2723
    - Confirms NVFP4 cubins exist for SM100 + SM103 only in artifact repo as of search date. Our pod is sm_103, so cubin path is supported.

## A4. Community / cross-vendor

20. **NVIDIA Devtalk: Testing Nemotron-3-Nano on DGX Spark / Jetson Thor** — `[U]` (DGX Spark, not B300 SXM)
    - https://forums.developer.nvidia.com/t/testing-nemotron-3-nano-models-on-nvidia-dgx-spark-jetson-thor-with-vllm-and-flashinfer/360642

21. **LiveKit Sequential Pipeline Architecture blog** — `[STABLE]`
    - https://livekit.com/blog/sequential-pipeline-architecture-voice-agents
    - Pipeline (cascaded STT-LLM-TTS) is correct for telephony/regulated. No GPU co-residency guidance.

22. **NVIDIA Multi-Process Service architecture page** — `[STABLE]`
    - https://docs.nvidia.com/deploy/mps/index.html (brief landing page)

23. **Microsoft CycleCloud GPU slicing with MPS** — `[U]`
    - https://techcommunity.microsoft.com/blog/azurehighperformancecomputingblog/gpu-slicing-in-cyclecloud-slurm-with-cuda-multi-process-service-mps/4365999
    - General SLURM+MPS pattern. Not B300-specific. Confirms `nvidia-cuda-mps-control -d` is the canonical daemon launch.

24. **MPS helper repo (community)** — `[U]`
    - https://yanbc.github.io/nvidia_mps_helper/
    - Reference shell scripts for MPS lifecycle.

## A5. Tooling-chain (auto-mode classifier)

25. **Anthropic Claude Code Issue #38618 — auto-mode classifier blocks** — `[STABLE]`
    - https://github.com/anthropics/claude-code/issues/38618
    - Classifier-unavailable / classifier-blocked patterns documented. Cycle-2c hit this exactly.

26. **Anthropic Claude Code Issue #39259 — auto-mode blocks read-only ops** — `[STABLE]`
    - https://github.com/anthropics/claude-code/issues/39259
    - Confirms `systemctl is-active` and similar can hang/block when classifier is uncertain.

27. **Anthropic engineering: Claude Code Auto Mode** — `[STABLE]`
    - https://www.anthropic.com/engineering/claude-code-auto-mode
    - 17% false-negative rate on overeager classifier decisions. 3 consecutive denials → terminate.

## Foundational (cited but not refreshed)

- T2 ablation: `findings/voice/coresidency/ablation.json` (Fish RTF +95% under all-busy contention)
- Phase D rebuild: `findings/b300_bench/phase-d-rebuild/result.json` (TTFT p95=44.1ms, tok/s=311.5; vLLM cold-boot 868s = 14m28s)
- Cycle-2c halt postmortem: `findings/b300_bench/cycle2c_mps/2026-04-25T19-48-50Z/summary.md`
- Team M runbook v1: `findings/voice/cycle-2c-mps/runbook.md`
- Team 4 ready-to-run: `findings/b300_bench/cycle2c_mps/ready_to_run.md`
- Team 0 rollback + watchdog: `findings/b300_bench/cycle2_guard/2026-04-25T13-56-50Z/{cycle2c_rollback.sh,health_check.sh}`
- Pebble case study (vLLM under MPS): https://www.gopebble.com/case-studies/nvidia-mps-vs-dedicated-gpu-allocation-for-llm-inference (cited in Team M; not refreshed)
- SGLang issue #22192 (vLLM under MPS works): https://github.com/sgl-project/sglang/issues/22192 (cited in Team M; not refreshed)
- NVIDIA Forum stream-priority hint (not preemption): https://forums.developer.nvidia.com/t/how-high-priority-stream-preemption/78183 (cited in Team M; stable claim)
