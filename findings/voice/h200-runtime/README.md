# prism42-h200 runtime — health snapshots

Periodic JSON snapshots of the H200 voice-agent pod state, written from
the deploying session and committed to main so out-of-band observers
(scheduled remote agents, follow-up reviews) have authoritative data
to read without SSH access to the pod.

## Schema (each `health-*.json`)

| Key | Meaning |
|---|---|
| `snapshot_ts_utc` | when this snapshot was taken |
| `tag` | snapshot tag (`tplus0`, `tplus1h45`, etc.) |
| `host` / `ip` | pod host (`warm-lavender-narwhal`, 89.169.123.251) |
| `worker.status` | `running` / `down` |
| `worker.pid` / `agent_id` / `agent_name` / `lk_url` / `region` | LiveKit worker registration |
| `backends.{stt,tts,llm,vllm_model}` | the env-flipped backends in effect |
| `containers.{vllm_nemotron,redis}` | docker `ps` status string |
| `gpu.{name,mem_used_mib,mem_total_mib,util_pct,driver,cuda_runtime}` | nvidia-smi |
| `log_signals.{sessions_total,errors_total,last_5_info_lines_pipe_separated}` | greps over `/home/ubuntu/worker.log` |
| `disk_root_used_pct` | `/` usage |

## Architecture pin (this run, 2026-04-27)

- **Reference:** `NVIDIA-AI-Blueprints/nemotron-voice-agent`
- **STT:** Parakeet 1.1B CTC streaming via NVCF (`grpc.nvcf.nvidia.com:443`)
- **LLM:** Nemotron-Nano-30B-A3B BF16 on local vLLM (Hopper SM 9.0, 186 ms / 50 tok measured Team A)
- **TTS:** Magpie-Multilingual.EN-US.Leo via NVCF
- **Orchestration:** LiveKit Agents 1.5.6 + `livekit-plugins-nvidia`
- **Public URL:** `https://prism42-h200-demo.vercel.app/`
- **LK Cloud project:** `wss://ai-therapy-v3svfd9o.livekit.cloud`
- **Worker agent_name:** `prism42-h200`

The architecture brief at
[`../../research/2026-04-27-future-stack/nvidia-voice-stack-architecture.md`](../../research/2026-04-27-future-stack/nvidia-voice-stack-architecture.md)
explains why these pins, what's next (self-hosted Riva 2.15, RAPIDS
26.04 cu13, NeMo Guardrails 0.21.0, nx-cugraph for medical KG), and the
CUDA 13.2 thesis.

## How a remote observer should read these

1. Sort `health-*.json` files by `snapshot_ts_utc`.
2. Compare consecutive snapshots: if `worker.status` flipped to `down`,
   that's a P0. If `errors_total` jumped, look at `last_5_info_lines`.
3. If `gpu.util_pct` stays at 0 across snapshots, no real calls landed
   (idle vLLM holds memory but doesn't compute).
4. If `containers.vllm_nemotron` no longer says `Up …`, vLLM died and
   no LLM completion is possible regardless of LK signaling.
