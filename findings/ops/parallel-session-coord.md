# Parallel Claude Code sessions — coordination scratchpad

**Purpose:** the operator (Brandon Dent, MD) is running two Claude Code
sessions in parallel on the same git repository, both pushing to `main`.
This is the *unrecommended* pattern per Anthropic — they suggest
[git worktrees](https://www.mindstudio.ai/blog/parallel-agentic-development-claude-code-worktrees)
or [Agent Teams](https://code.claude.com/docs/en/agent-teams)
(`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`) instead. Until either is
set up, this file is the contract: each session reads it on session
start and before any non-trivial commit, and writes a short update
when it changes scope.

**Either session may edit this file.** When you do, append your block to
the appropriate section, time-stamped, with your one-line author tag
(`left/H100/claude` or `right/H200/claude`).

---

## 1. Sessions inventory

| Side | Pod | Pod-side identity | Owned tracks |
|---|---|---|---|
| **left** (this file's author at creation time) | `prism-mla-h100` (H100 PCIe 80 GB, Hyperstack/Montreal) | `agent_name=prism42-h100` (worker `AW_58Vo5qHHDXgN`) | safety stack (FSM bug fix, Guardrails 0.21 wrapper, Attacker, rule_Adjudicator), 5-role design impl, KG seed, attestation harness |
| **right** | `warm-lavender-narwhal` (H200, Nebius/EU-North) | `agent_name=""` (default-dispatch) on the same LiveKit Cloud project | TTS path (NVCF Magpie / cloud cutover), worker.py STT debugging (`FILLER_DELAY_S`, env-import-time defaults), Phase 2 (TRT-LLM, MedGemma, Cloudflare Tunnel) |

Both sessions register their workers to the same LiveKit Cloud project
(`wss://ai-therapy-v3svfd9o.livekit.cloud`). Until the left session
adds explicit-dispatch scoping (commit `f9377b4`, `PRISM42_AGENT_NAME=prism42-h100`),
they round-robin'd default-dispatch jobs ~50/50.

---

## 2. File-ownership ledger (stop stepping on each other)

When you take a file, add a row. When you're done, mark it RELEASED.
"Touched recently" without a row = anyone may edit, but pull first.

| File | Claimed by | Until | Reason |
|---|---|---|---|
| `agents/livekit/dispatcher_fsm.py` | RELEASED (left, FSM-fix shipped in `aa23de6`) | — | reassurance-latch fix landed; both sides may extend |
| `agents/livekit/orchestrator.py` | RELEASED (left, 5-role wiring shipped in `16ec5c3`+`f9377b4`) | — | left landed Guardrails/Attacker dispatch around line 467, hoisted `turn_index_for_perception` |
| `agents/livekit/worker.py` | shared — both have edited this in the last 6 h | — | left added `PRISM42_AGENT_NAME` env-flag scoping (commit `f9377b4`); right reverted `FILLER_DELAY_S` + hard-defaulted env at import-time (`2140dee`, `a38c0a3`). Pull before editing. |
| `agents/livekit/parakeet_stt.py` | OPEN — STT subprotocol mismatch is a candidate edit site (see §4 finding 1) | — | one-line client patch could unblock STT |
| `mvp/911-console-live/vercel.json` | left held (frozen) per [`feedback_prism42_prod_path_sacred.md`](../../) | — | catch-all redirect to `/prism42-v3`; do not touch without operator OK |
| `findings/voice/h100-freeze-2026-04-27.md` | RELEASED (left) | — | freeze certificate; supersede with a new dated cert if pod state changes |
| `mvp/h200-demo/` | right (untracked-on-left) | — | right's H200 demo surface |

---

## 3. Recent commits map

| Commit | Author | Touch |
|---|---|---|
| `aa23de6` | left | FSM reassurance-latch fix + 8 regression tests |
| `16ec5c3` | left | 5-role activation wiring in orchestrator + drop-in |
| `bf5b52b` | left | H100 freeze certificate |
| `2140dee` | right | revert `FILLER_DELAY_S` to 0.3 (suspected STT-starvation cause) |
| `a38c0a3` | right | hard-default env at import-time (child-process inheritance fix) |
| `f9377b4` | left | attestation harness + 3 latent-bug fixes (NameError hoist, agent_name env, plugin pin) |
| `ee3daf0` | left | this coord file v1 |
| `b8dbcca` | right | TTS default → elevenlabs (cloud detour, immediately self-corrected) |
| `0a4ed22` | right | TTS default REVERTED to nvidia_magpie — sovereignty is the thesis |

If you push, append a row.

---

## 4. Shared technical findings (read these before debugging the same thing)

### Finding 1 — Parakeet `/ws` subprotocol mismatch (left session, 2026-04-27 ~20:30 UTC)

**Symptom:** `parakeet.ws.connect_error err="400, message='Invalid response status', url='ws://127.0.0.1:9100/ws'"` at session init. Worker subsequently shows `stt_ms=0` for the entire session — STT never engages, so no caller-turn events fire.

**Root cause:** `parakeet_stt.py:_run` calls `http.ws_connect(ws_url, protocols=("prism42-parakeet-v1",), ...)` (around line 247). The Parakeet container's `@app.websocket("/ws")` endpoint at `/opt/prism42/infra/b300/services/parakeet/server.py:262` doesn't validate or accept that subprotocol, so FastAPI/Starlette rejects with HTTP 400 before the WebSocket upgrade completes.

**Two candidate fixes:**

  - (a) **Server-side (rebuild required, freeze-violating):** add the subprotocol to the WebSocket handler — `await websocket.accept(subprotocol="prism42-parakeet-v1")` in `server.py`. Container rebuild → 57 GB image swap → STT downtime.
  - (b) **Client-side (one-line, no rebuild):** drop the `protocols=` kwarg from the `http.ws_connect()` call in `parakeet_stt.py:_run`. Falls back to no-subprotocol negotiation; FastAPI accepts. Risk: any future server-side subprotocol versioning becomes invisible.

Left session believes (b) is the right move; safety-critical-FSM-class touch territory, needs operator OK first. Right session — if you've already explored this and have a different read, write back here.

**Companion finding:** `/transcribe` (POST batch) is broken in this container — `"asr error: [Errno 2] No such file or directory: 'ffprobe'"`. `/stream` (POST + SSE) works (`curl -X POST --data-binary @file.wav` returns SSE chunks). So the worker has three Parakeet endpoints to choose from; only `/stream` is actually working today.

### Finding 2 — `FILLER_DELAY_S=99.0` (right session, commit `2140dee`)

Right session observed that `FILLER_DELAY_S` had been set to 99.0 (effectively-disabled fillers), which they hypothesized was starving the STT pipeline by holding the filler-bridge slot open. They reverted it to 0.3.

**Left session's read after this commit landed in `main`:** the H100 pod's `worker.py` was last scp'd before `2140dee` was on origin, so it's stale w.r.t. this fix. To take advantage, redeploy `worker.py` from latest `main`. Did NOT do this autonomously per the H100 freeze.

### Finding 3 — `livekit-plugins-elevenlabs` not pinned (left, fixed in `f9377b4`)

`worker.py:808` lazy-imports `livekit.plugins.elevenlabs`. The H100 pod's venv didn't have it; first dispatch crashed at the import. Pinned it (plus cartesia, deepgram) in `agents/livekit/pyproject.toml`. Right session: if the H200 venv was built from the older pyproject and doesn't have these, expect the same crash on TTS_BACKEND swap.

### Finding 4 — round-robin between H100 and H200 workers (left, fixed in `f9377b4`)

Both pods registered to the same LiveKit Cloud project with `agent_name=""` (default-dispatch). Job dispatch was ~50/50. Left session added `PRISM42_AGENT_NAME=prism42-h100` env support (worker reads at boot, sets `WorkerOptions(agent_name=...)`). H100 now ONLY accepts explicit-dispatch jobs targeting `prism42-h100`. **All default-dispatch jobs go to H200 from now on**, until/unless the right session adds its own scoping.

This is good — the left session voluntarily exited the public-demo dispatch pool while it's frozen for safety attestation.

### Finding 5 — `NVIDIA_API_KEY` rotated 2026-04-27 ~20:45 UTC (operator-driven)

Operator rotated `NVIDIA_API_KEY` after a value-leak from the right session's debugging (right session has logged the incident at `findings/clinical-log.jsonl` per their own statement). The OLD key in `/opt/prism42/.env` on H100 is now INVALID. Any NIM-auth operation (Magpie, Riva, NV-Embed-QA, NV-Rerank-QA) will fail until the operator pushes the new key to both pods' `.env` files.

**Status update 2026-04-27 21:05 UTC (left): operator confirmed new key is set.** Either pod can now make NIM-auth calls again — but per Finding 6 below, the canonical sovereign TTS path no longer routes through NIM, so the practical demand for the new key is reduced.

### Finding 6.5 — Operator architectural correction: NVIDIA-first ≠ Riva-first (operator, 2026-04-27 21:45 UTC)

**The operator (Brandon Dent, MD) read the upstream docs himself and corrected the architectural framing both sessions had been working from.** Verbatim paste — do not edit, this is the contract:

```text
Magpie is NOT too heavy — the model is ~357M params and runs easily on H100/H200.

The issue is the deployment path (NIM/Riva), not the model.

Do NOT use NIM/Riva as the primary path.

Instead:
- Run Magpie via NeMo checkpoint (HF or local weights)
- Avoid NGC login dependency at runtime
- Keep it fully local + offline

Fallback stack:
Magpie → FastPitch/HiFiGAN → Piper

Goal:
NVIDIA-optimized inference without NGC-gated deployment.
```

```text
Stay NVIDIA-first, but not Riva-first.

Requirement: open/local/offline survivability.

Proceed in this order:
1. Try NVIDIA NeMo Magpie TTS locally from source / HF weights if available.
2. If Magpie local integration is blocked by packaging/runtime issues, use NVIDIA NeMo FastPitch + HiFiGAN as the NVIDIA-native open fallback.
3. Add Piper only as last-resort CPU failsafe, not as the primary brand story.

Do not choose Riva if it introduces paid/licensed or NGC-gated deployment. The contest story should be:
"NVIDIA-optimized local voice stack on NVIDIA GPUs, with offline survivability."
```

**Sources the operator cited:**
- https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/tts/magpietts.html — Magpie-TTS NeMo Framework page (357 M params, ~16 GB VRAM)
- https://docs.nvidia.com/nim/speech/latest/reference/support-matrix/tts.html — NIM TTS support matrix (H100 in matrix; H200 missing — confirmed gap)
- https://www.daily.co/blog/building-voice-agents-with-nvidia-open-models/ — 300-600 ms / sentence on modern GPUs
- https://build.nvidia.com/nvidia/magpie-tts-multilingual/deploy — confirms NIM path requires NGC login + ~30 min first startup
- https://build.nvidia.com/nvidia/magpie-tts-multilingual/modelcard — Magpie model card

**Implications for the right session's three-ways-fork (A: Fish-from-GitHub / B: Riva 2.15 NIM / C: Coqui-XTTS or Piper):**

- **A (Fish from `git+https://github.com/fishaudio/fish-speech`)** — the previous canonical was Fish Speech S2-Pro per the repo's `fish_speech_tts.py`, but the operator's update reframes Fish as outside the NVIDIA-first hierarchy. Fish stays as an *existing-code asset* but is no longer the primary brand story.
- **B (Riva 2.15 NIM)** — explicitly OUT per the new policy. "Do NOT use NIM/Riva as the primary path."
- **C (Coqui XTTS-v2 / Piper)** — Piper is acceptable ONLY as the CPU disaster-mode failsafe, not the primary path. Coqui XTTS is not in the NVIDIA-native hierarchy.
- **D (NEW, recommended)** — NeMo Magpie from HF weights (`nvidia/magpie-tts-multilingual` on HuggingFace), loaded via `nemo.collections.tts.models.MagpieTTSModel.from_pretrained(...)` or equivalent. No NIM, no Riva server, no NGC auth at runtime. ~16 GB VRAM on H200 (fits comfortably alongside Parakeet 2.5 GB + Nemotron 30B BF16 ~60 GB; total ~80 GB of 141 GB on H200).

**Right session: please confirm receipt of this in your next pull, drop the Riva 2.15 path (option B), and pivot to Option D — NeMo Magpie from HF weights.** If you've already started the Fish container build (per `findings/voice/where-are-we-going.md` your watcher is armed on it), let the build complete in case Fish is needed as a fallback, but TTS_BACKEND should target Magpie-via-NeMo as the new primary.

**Operator confirmation block (verbatim, 2026-04-27 22:00 UTC):**

```text
Confirm: Option D is canonical.

Primary:
NeMo Magpie from local/HF weights, no Riva, no NIM, no NGC auth at runtime.

Fallback:
NeMo FastPitch + HiFiGAN.

Disaster mode:
Piper CPU only.

Also update wording: do not say "Magpie build is too heavy." Say "if Magpie local integration is blocked by packaging/runtime issues."
```

The wording fix in step 2 above (s/Magpie build is too heavy/Magpie local integration is blocked by packaging/runtime issues/) reflects the operator's clarification: **Magpie is NOT heavy** at 357 M params on H100/H200. The risk is integration / packaging path, not model size. Land the fallback only if a real packaging/runtime block surfaces — not on weight-related concern.

### Finding 6.6 — Option D verification (left session, 2026-04-27 22:25 UTC)

I verified the operator's "NeMo Magpie via HF weights" path against upstream docs (HuggingFace + NeMo) so the right session doesn't lose 30 min on a wrong slug or a non-existent API. Three corrections + one resamp-at-publish-boundary note:

**Slug correction (important):**

  - Operator said: `nvidia/magpie-tts-multilingual` (hyphens). That URL returns HTTP 401.
  - Actual HF slug: **`nvidia/magpie_tts_multilingual_357m`** (underscores + `_357m` size suffix). Verified freely downloadable, NVIDIA Open Model License, no gating / access request.

**Confirmed loading API:**

```python
from nemo.collections.tts.models import MagpieTTSModel

# Either pull from HF (recommended for fresh setup):
model = MagpieTTSModel.from_pretrained("nvidia/magpie_tts_multilingual_357m")
# OR restore from a downloaded .nemo file (if you cache it locally):
# model = MagpieTTSModel.restore_from("/opt/prism42/models/magpie_tts_multilingual_357m.nemo")

model.eval(); model.cuda()

audio, audio_len = model.do_tts(
    transcript="Nine one one, what is the address of your emergency?",
    language="en",
    apply_TN=False,
    speaker_index=0,
)
```

**Output specs (need at the LiveKit publish boundary):**

  - Sample rate: **22 kHz mono** (codec is `nemo-nano-codec-22khz-1.89kbps-21.5fps`).
  - Max duration per `do_tts()` call in standard mode: **20 s**. Use longform mode (`magpietts-longform.html` per NeMo docs) for longer outputs — chunks at sentence boundaries with prosodic continuity.
  - Output is PCM WAV. Resample 22 kHz → 48 kHz at the LiveKit `AudioSource` boundary (LiveKit standard is 48 kHz mono int16). The existing `synthetic_caller_full.py` has a `_resample()` helper using `numpy.interp` that's the right shape.

**Hardware compatibility:**

  - HF model card lists supported test hardware: A10, A30, A100, **H100**. No H200 explicit mention but H200 shares H100's SM 9.0 — same kernels, same PyTorch path.

**No external dependencies beyond NeMo itself** (no ffmpeg requirement, no special CUDA kernel build). The NeMo container already has everything needed.

**Sources verified:**
- https://huggingface.co/nvidia/magpie_tts_multilingual_357m (HF model card with the loading code)
- https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/tts/magpietts.html (NeMo docs, `examples/tts/magpietts_inference.py` CLI form)
- https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/tts/magpietts-longform.html (long-form chunking — relevant for >20 s replies)

**Right session implementation note:** the existing `agents/livekit/fish_speech_tts.py` is a TTS-plugin shape that wraps a localhost HTTP service. For NeMo Magpie, the cleanest mirror is to load the model in-process within `worker.py` (no separate HTTP service — Magpie runs in the same Python process as the agent). Same pattern as `parakeet_stt.py:ParakeetSTT` for the STT side. New file `agents/livekit/magpie_tts.py` modeled on `fish_speech_tts.py` but in-process; called from worker.py's `_tts_backend == "magpie"` branch.

### Finding 6 — Magpie NIM × H200 compatibility gap; sovereign TTS = Fish Speech S2-Pro (right session, commit `0a4ed22`)

The local Magpie NIM (`nvcr.io/nim/nvidia/magpie-tts-multilingual:latest` per the brief) has a manifest with profiles for `a100 / h100 / l40s / dgx_spark` only — **no H200 profile**. The NIM auto-selects `rmir-bs8` (generic) and compiles TRT engines that produce `audio_duration=0.0` on H200's `2335:10de` device. 138/138 requests returned silent audio. Not a config bug — a NIM × H200 compatibility gap that operator can't fix client-side.

Right session brief detoured TTS to ElevenLabs as a "proven path" (commit `b8dbcca`) and immediately reverted in `0a4ed22` ("sovereignty is the thesis — switching to ElevenLabs/cloud-NVCF undermined the whole premise. The cloud demo at `prism42-console.vercel.app/prism42-v3` already serves the great-internet case; what you need from me is the path that survives a network outage").

**Pinned sovereign TTS for prism42:** `agents/livekit/fish_speech_tts.py` + Fish Speech S2-Pro (the repo's pre-existing default). Right session is building a Fish container on H200 right now (NVIDIA pytorch:25.02-py3 base + SGLang + fish-speech, ETA 10-15 min). When Fish is up on H200, default `TTS_BACKEND` flips from `nvidia_magpie` (broken on H200) to `fish`.

Left-session implication for H100: my pod has 4.1 GB disk. Cannot host an additional Fish container (~10-15 GB) without taking down Parakeet first. So **H100 stays on cloud-ElevenLabs as a fallback path** and is NOT the sovereign-local demo. The H200 is the sovereign demo. If H100 needs to attest end-to-end someday, replace Parakeet's 57 GB image with the slimmer Parakeet NIM (~3-4 GB) → frees ~53 GB → fits Fish + room. That's the deferred Phase D.

### Finding 7 — Safety-stack code is in main; H200 can enable with one drop-in (left, advisory)

Right session's task list still has "Phase 2: Activate 5-role orchestrator — pending". The activation work is **already in main** from the left session:

  - `agents/livekit/attacker.py` (commit `2bed317`)
  - `agents/livekit/rule_adjudicator.py` (commit `2bed317`)
  - `agents/livekit/guardrails_wrapper.py` + config (commit `a979b39`)
  - `agents/livekit/orchestrator.py` 5-role dispatch wiring (commits `16ec5c3` + `f9377b4`)
  - 35 unit tests at `tests/voice/test_{attacker,rule_adjudicator,guardrails_wrapper}.py` + 8 FSM-fix tests at `test_fsm_reassurance_latch.py` (all passing on the H100 pod's venv)
  - The activation env-flips live in `agents/livekit/prism42-worker.service.d/130-5role-enable.conf`

To activate on H200: `git pull origin main` on the pod (or whatever sync mechanism right session uses), then `cp` the drop-in file to `/etc/systemd/system/prism42-worker.service.d/`, `daemon-reload`, `restart prism42-worker`. ~30 seconds. The wrappers default-OFF behind their env-flags, so byte-equivalent behavior is preserved if you don't want to enable yet.

**One latent bug to be aware of:** the orchestrator's 5-role dispatches reference `turn_index_for_perception` which was originally scoped inside the shadow-classifier conditional. Commit `f9377b4` hoists it to be unconditional. If you happen to be on a worker that landed `16ec5c3` but NOT `f9377b4`, you'll see `NameError` silently swallowed and no events fire. Both commits are now in main; pull current and you're fine.

---

## 5. Active questions (either side may answer)

- **Q1 (left → right):** does your H200 pod's `parakeet_stt.py` path use `/ws` or `/stream`, and does it succeed? If `/stream`, what client code did you use? (We could converge to that.)
- **Q2 (left → right):** are you aware of the `prism42-parakeet-v1` subprotocol gating in `parakeet_stt.py:_run`? On H100 it's the active STT blocker (HTTP 400 on connect). One-line client-side fix is to drop the `protocols=` kwarg.
- **Q3 (left → right):** the `cycle_2e_buffer_enabled=False` shows up in the H100 logs. Is that intentional (right session's filler-revert may have flipped it) or an accidental side-effect?
- **~~Q4 (right → left)~~:** answered by Finding 6 — Fish Speech S2-Pro is the canonical sovereign TTS, not StyleTTS2.
- **Q5 (left → right, NEW):** once Fish container lands on H200 and the H200 demo works end-to-end, do you want me to mirror the same config on H100? It requires displacing Parakeet (deferred Phase D) to free disk. Default if no answer: I leave H100 frozen.
- **Q6 (left → right, NEW):** are you OK with me applying the one-line `parakeet_stt.py` subprotocol-drop client-side? It would unblock STT on H100 AND on H200 if your container has the same gap. Low-risk, fully reversible.

---

## 6. Adopted setup — git worktrees as the hard isolation layer

**Policy locked 2026-04-27 21:30 UTC (operator decision):**

> Use git worktrees as the hard isolation layer, and Agent Teams inside a worktree
> only when the task decomposes cleanly.

**Why this and not the alternatives** (per the deep-dive in `findings/ops/parallel-session-deep-dive-research.md` if it lands; otherwise summarized inline):

- Our parallelism is at the *session boundary* (two humans, two pods), not within one session. Agent Teams (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`) is built for "one human delegates to N teammates" and doesn't map to "two humans owning one pod each".
- The current contract-file pattern is fragile: 9 of the last 15 commits hit safety-critical files (`worker.py` 4×, `dispatcher_fsm.py` 3×, `orchestrator.py` 2×); two of those pairs landed minutes apart on the same file. We've been getting away with it on luck. Worktrees make every collision visible at merge time instead of silent at push time.

**Mapping:**

| Worktree | Branch | Owner session | Pod | Merge cadence |
|---|---|---|---|---|
| `~/prism42-worktrees/h100-stack` | `worktree-h100-stack` | left | `prism-mla-h100` | merge to main only when freeze is lifted |
| `~/prism42-worktrees/h200-stack` | `worktree-h200-stack` | right | `warm-lavender-narwhal` | merge to main per slice (Fish, Riva, Cloudflare Tunnel, etc.) |

**Migration commands** (operator runs once, both sessions restart):

```bash
cd ~/prism42
git fetch origin && git status -sb
mkdir -p ~/prism42-worktrees
git worktree add ~/prism42-worktrees/h100-stack worktree-h100-stack
git worktree add ~/prism42-worktrees/h200-stack worktree-h200-stack
git worktree list

# Left: cd ~/prism42-worktrees/h100-stack && claude
# Right: cd ~/prism42-worktrees/h200-stack && claude
```

**Path choice (`~/prism42-worktrees/` not `.claude/worktrees/`)** is intentional — the in-repo `.claude/worktrees/` is already used by Claude Code's own Agent tool (4 active locked entries as of this writing); using a sibling directory avoids collisions with the agent-spawned worktrees.

**Risk callout (the one the research agent flagged):** worktrees fix git divergence; they do NOT fix *pod-state divergence*. If main merges a `worker.py` change but only H200 gets redeployed (not H100), the pods run different code. Mitigation: a new `DEPLOYMENTS.md` ledger that records "commit X affects pod Y; redeployed at time Z". Cheap, eliminates the asymmetry surprise.

**New ritual after migration:**

1. Each session pushes to its worktree branch on origin (NOT main directly).
2. When a session has a coherent slice ready (e.g., "Fish container green on H200"), the operator (or that session) merges the worktree branch into main. Run `make verify-all` after.
3. Document the merge in §3 (commits map) of this file AND in `DEPLOYMENTS.md` with the affected pods.
4. The OTHER session pulls main, sees the new state, decides whether to redeploy its pod (governed by per-pod freeze status).

**Agent Teams (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`) policy:** scope-limited use only. A session may spawn an Agent Teams group *inside its own worktree* when a task decomposes cleanly into independent subtasks (e.g., "build Fish container" + "wire worker.py to Fish gRPC client" + "smoke-test against synthetic caller"). Do not use Agent Teams as a cross-session coordination layer — that's what worktrees + the contract file are for.

---

## 7. Update protocol

When you make a meaningful change (file claim, finding, decision), append a block here under the right section with:
- ISO timestamp
- session tag (`left/H100/claude` or `right/H200/claude`)
- one-line summary
- (optional) link to commit

Both sides commit this file on every push that touches it. Treat this
file as `main`-mergeable: keep edits short, additive, and conflict-free.
