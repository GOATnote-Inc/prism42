# Q4 Deep Dig — voice runtime stack forensics

UTC: 20260426T064303Z
Reviewer: Q4 (NVIDIA-senior-engineer mindset, read-only)
Scope: caching layers, cold-start state, embedding inheritance, cross-service handoffs.
Constraint: not duplicating Q1's systemd-precedence + adapter-mutex finding (verified). Focus on places those teams' lenses miss.

## Bottom line

Q1's systemd .env precedence finding is correct and load-bearing — but it is ONE of THREE compounding issues. After Q1's fix lands, two additional latent bugs will keep the user complaining about the wrong voice unless they are addressed in the same hotfix:

1. **Fish in-process VQ-token cache is process-scoped and never invalidated.** Replacing the WAV at `references/psap/sample.wav` on disk does NOT change synthesis output until `prism42-fish.service` is restarted. The pod has been running this fish process since Apr 25 21:09 UTC (≈9 hr at probe time), so any reference-WAV swap in that window is stale. (verified-by-source)
2. **Greeting cache (`/tmp/prism42-greeting.wav`) bakes the wrong voice in by construction, not by env.** Q1 noted the body has `references=[]` — but missed that the greeting cache's invalidation sentinel (`_GREETING_PCM_BYTES is not None`) cannot detect a voice change at all. Even after Q1's env fix, the cached greeting plays the WAV synthesized by *whichever voice was active at first warm of the current worker process*. The current cached greeting (mtime 06:35:36 UTC) was synthesized 5 minutes after worker process start, when `FISH_SPEECH_REFERENCE_ID=psap` was inherited — but Fish's `_warm_greeting_cache_blocking` body sends NO `reference_id` AND `references=[]`, so the greeting was actually rendered by Fish's *stock untrained* voice (different from psap and different from MW). (verified-by-source)
3. **Worker's `LIVEKIT_URL` points at LiveKit Cloud, not the self-hosted pod.** `/proc/<worker-pid>/environ` shows `LIVEKIT_URL=wss://ai-therapy-v3svfd9o.livekit.cloud`. The pod has its own `livekit-server` listening on `*:7880` (PID 76823, started Apr 25 21:09 UTC), Caddy at `livekit.thegoatnote.com` is configured to proxy to it, and `infra/b300/livekit.yaml` codifies the self-hosted intent — but the worker NEVER connects to it. The user's deploy can be using either path depending on which `NEXT_PUBLIC_LIVEKIT_URL` is set on the browser side. If browser hits cloud and worker hits cloud they meet, but the architectural goal in CLAUDE.md §0 ("LiveKit + B300 self-hosted") is silently violated. Doesn't itself cause the wrong-voice symptom, but means the self-hosted server's lifecycle (which would be relevant for any future custom Fish-resident pipeline) is not exercised. (verified-by-source)

These are the three ways the stack can keep playing the wrong voice EVEN after Q1's fix and a worker restart, IF those parallel issues aren't addressed.

## New failure modes Q1+Q2+Q3 might miss

| # | Failure mode | Layer | Evidence | Validation |
|---|---|---|---|---|
| Q4-A | Fish's in-process `ref_by_id` dict caches encoded VQ tokens forever; replacing `references/psap/sample.wav` on disk does NOT invalidate them | Fish process memory | `vendor/fish-speech/fish_speech/inference_engine/reference_loader.py:76-95` | `cat /proc/<fishpid>/cwd && ls /opt/prism42/infra/b300/services/fish-speech/references/psap/`. Need fish process restart to pick up WAV change. |
| Q4-B | Greeting cache bakes an unrelated voice (Fish stock baseline, not psap, not MW) because `_warm_greeting_cache_blocking` sends `references=[]` and no `reference_id` field | Worker process memory + `/tmp/prism42-greeting.wav` | `agents/livekit/worker.py:221-237`; greeting mtime 06:35:36 UTC vs worker start 06:30:39 UTC | Compare actual greeting WAV to a sample synthesized via psap directly. If Q1 fix lands without greeting fix, greeting and dispatcher voices will still be different. |
| Q4-C | `LIVEKIT_URL=wss://ai-therapy-v3svfd9o.livekit.cloud` ≠ self-hosted livekit-server on pod port 7880 | Worker network config | `/proc/<wpid>/environ` shows cloud URL; `lsof -i :7880` shows local livekit-server PID 76823 unused | Compare `NEXT_PUBLIC_LIVEKIT_URL` on Vercel prod to `LIVEKIT_URL` on pod .env — if both point at cloud, the local server is dead weight; if browser points at thegoatnote subdomain and worker at cloud, browser+agent join different rooms (no audio at all). |
| Q4-D | Greeting cache sentinel cannot detect voice/text change — module-global `_GREETING_PCM_BYTES is not None` is the ONLY invalidation gate | Worker process memory | `worker.py:304-306, 1019-1033` — early-return if cache is populated, no hash/mtime compare | Verify by changing `GREETING_TEXT` const and noting cache file `/tmp/prism42-greeting.wav` retains the old text-rendered audio across `systemctl restart` of OTHER services (only worker restart drops the in-process bytes; the on-disk archive is overwritten on next warm but only fires once). |
| Q4-E | `FishSpeechTTS` `_client = httpx.AsyncClient(...)` is constructed at `__init__` and reused per-AgentSession — reuses TCP connection across sessions in the same worker process | Worker process memory | `fish_speech_tts.py:100`, ctor at 87-100 | Not a bug per se, but means HTTP request body is built fresh per call — reference_id swap mid-process WOULD propagate IF the dataclass `_opts` were rebuilt. It is NOT (it's frozen at line 88) — see Q4-G. |
| Q4-F | Fish hash-based cache `ref_by_hash` in `reference_loader.py:99-131` returns cached VQ tokens whenever sha256(audio_bytes) matches — but the entry was set with the FIRST text the audio was paired with | Fish process memory | `reference_loader.py:118-119` stores `(token, ref.text)`; line 124 reuses both | If the inline reference audio bytes are byte-identical across calls (likely for a static MW WAV) but the deployer changes `PRISM42_FISH_REFERENCE_TEXT`, Fish ignores the new text and replays the cached pairing. Mitigated only by `use_memory_cache="off"`. |
| Q4-G | Adapter `FishSpeechOptions` defaults are bound at MODULE IMPORT time (lines 28-29, 37-38, 48), captured into the dataclass via class-level `field(default=...)` semantics | Worker process memory | `fish_speech_tts.py:28-29, 37-38, 48, 53-83` | Even if the worker's env is mutated post-import (which doesn't happen here, but cf. proposed `os.environ.pop` workarounds), the FishSpeechOptions defaults are frozen. `worker.py:659` constructs `FishSpeechOptions()` (no args), so reference_id is whatever was on env at module-import. |
| Q4-H | LiveKit's `_audio_forwarding_task` resamples 44.1kHz Fish output to whatever the room SDP negotiates (typically 48kHz Opus) using `rtc.AudioResampler` | livekit-agents internal | `livekit/agents/voice/generation.py:406-434` | This is the standard resampler, it does NOT introduce robotic artifacts independent of source. If you hear robotic, the source audio is robotic. (Rules out Q5 from the brief — resampling pipeline is innocent.) |
| Q4-I | TTSCapabilities advertised as `streaming=False` (`fish_speech_tts.py:96`); livekit-agents will route via `synthesize()` chunked-stream path (no fallback adapter wrapping our TTS) | Worker process memory | `fish_speech_tts.py:95-99` | Confirms there is NO `FallbackAdapter` shimming our TTS. The `_tts` instance assigned at `worker.py:659` is exactly the one called via `_tts_task_impl` (`livekit/agents/voice/agent_activity.py:2204`). No stealth path. (Rules out Q3 / Q6 from the brief — no plugin-internal TTS bypass.) |
| Q4-J | `session.say(audio=cached_iter, ...)` for the greeting bypasses TTS entirely and forwards cached `rtc.AudioFrame` directly to the audio output | livekit-agents internal | `livekit/agents/voice/agent_activity.py:1083-1097` (`audio` arg branch) + `worker.py:1067-1081` | Greeting is NOT re-synthesized per session — the cached PCM bytes from `/tmp/prism42-greeting.wav` are framed and shipped as-is. Means greeting voice is locked at first cache warm; only worker restart unlocks it. |
| Q4-K | vLLM at `127.0.0.1:8001/v1` with `LLM_BACKEND=vllm-local` produces text → orchestrator-passthrough → fish_speech_tts adapter; no intermediate "filler TTS" or short-message bypass for short replies | Worker process memory | `worker.py:580-621` (LLM init), `_FILLERS_PLAIN/_FILLERS_TAGGED` (line 87-99) all go through `session.say(text)` (worker.py:1180) → standard TTS path | Filler voice = same as dispatcher voice. (Rules out Q6 short-circuit hypothesis from the brief.) |
| Q4-L | Two Vercel projects share the same monorepo: `prism42` (repo root, `prj_TPrU...`) AND `prism42-console` (`mvp/911-console-live/`, `prj_UCqQ...`) | Vercel deployment cache | `.vercel/project.json` at repo root vs `mvp/911-console-live/.vercel/project.json` | Each maintains its own env vars per environment — `NEXT_PUBLIC_LIVEKIT_URL` may differ between the two. If a deploy went to the wrong project, the new URL never hit prod. Worth checking with `vercel env ls` for BOTH project ids. |

## Per-finding detail

### Q4-A: Fish process-memory VQ cache for `reference_id="psap"` (verified-by-source)

**Where:** `vendor/fish-speech/fish_speech/inference_engine/reference_loader.py:62-97` (`load_by_id`).

**Mechanism:** when `req.reference_id` is set (e.g. `"psap"`) AND `use_memory_cache="on"` (which we send unconditionally — `fish_speech_tts.py:217`), `load_by_id` returns the previously-encoded `(prompt_tokens, prompt_texts)` tuple from `self.ref_by_id[id]` (line 95) WITHOUT re-reading `references/psap/sample.wav` from disk. The dict entry is set on first miss at line 90 and never deleted until either `delete_reference()` is called (only via API server's `/v1/references/delete` endpoint) or the process restarts.

**Observable signature:** if you `cp new.wav references/psap/sample.wav` while fish is running, the next synthesis call STILL uses the old encoded VQ tokens. Fish log will not say `"Encoded prompt: torch.Size([10, 262])"` again — that line only emits on first encode.

**Fix path:** `systemctl restart prism42-fish.service` AFTER any reference WAV swap. Or send `use_memory_cache="off"` (degrades latency for steady-state callers). Not load-bearing for cycle-2N MW deployment because cycle-2N is replacing reference_id with inline references via the adapter — but it's load-bearing for any cycle-2L "psap-fast" rollout that swaps the WAV at `references/psap/`.

**Pod state at probe:** fish PID 383030, started Apr 25 21:09 UTC. Cycle-2L `psap-fast/` directory mtime is Apr 26 04:43 UTC (created post-fish-start) — so any psap-fast WAV that was dropped in there is encoded only on the first synthesis call that names it (`reference_id="psap-fast"`), and once encoded, lives in process memory.

### Q4-B: Greeting cache bakes Fish stock voice (not psap, not MW) (verified-by-source)

**Where:** `agents/livekit/worker.py:221-237`.

**Mechanism:** `_warm_greeting_cache_blocking` sends a Fish HTTP request with body:
```
references=[]
# no reference_id key
```
Fish's `inference_engine/__init__.py:48-57` decision tree:
- `ref_id is None` → falls through (we don't send a `reference_id` key, so `ServeTTSRequest.reference_id` defaults to `None` per `vendor/fish-speech/fish_speech/utils/schema.py:93`)
- `req.references` is empty list → falsy in Python → `elif req.references:` fails
- both branches skipped: `prompt_tokens, prompt_texts = [], []` from line 49

When Fish has no reference, text2semantic generates from base distribution → Fish's stock untrained voice. NOT psap, NOT MW.

**Observable signature:** the cached greeting WAV at `/tmp/prism42-greeting.wav` (mtime 06:35:36 UTC) sounds different from BOTH the dispatcher reply path (psap, post-fix MW) AND the cycle-2L psap-fast tests. It's a third voice — Fish's no-reference baseline.

**User-visible:** the user hears a generic voice say "Nine one one. Where is your emergency?" then a different voice (psap right now, MW after Q1 fix) speak the actual reply. The voice change between greeting and reply is jarring, and likely contributes to the "still robotic" perception even after Q1's fix.

**Fix path:** modify `_warm_greeting_cache_blocking` body construction to mirror the adapter's `_run` reference logic — read `PRISM42_FISH_REFERENCE_AUDIO`/`_TEXT` at warm time and populate `body["references"]` (fields named identically). For demo, can ship Q1 fix first and accept greeting-vs-reply voice mismatch; for production, fix both in the same patch.

**Critical interaction with Q1 fix:** the cached greeting WAV does NOT regenerate on `systemctl restart prism42-worker` UNLESS the in-process `_GREETING_PCM_BYTES` is None (it is, because that's a per-process global), AND the on-disk `/tmp/prism42-greeting.wav` is overwritten by the new warm. **It IS overwritten** (line 269 unconditionally writes wav_bytes to GREETING_AUDIO_PATH). But it is overwritten with Fish stock voice, again, because the body is unchanged.

### Q4-C: Worker connects to LiveKit Cloud, not self-hosted (verified-by-source)

**Where:** `/proc/$(pgrep -f worker.py)/environ` line `LIVEKIT_URL=wss://ai-therapy-v3svfd9o.livekit.cloud`.

**Mechanism:** the `livekit-agents` worker SDK initiates an outbound WSS to `LIVEKIT_URL` and registers as a worker with the LiveKit cluster on that URL. Cloud LiveKit is a multi-tenant service; the worker registers there, and rooms are dispatched there. Self-hosted livekit-server on the pod (PID 76823, port 7880) handles only requests routed to `livekit.thegoatnote.com` via Caddy.

**Observable signature:** `infra/b300/Caddyfile` has live config for `livekit.thegoatnote.com` → 127.0.0.1:7880. `infra/b300/livekit.yaml` config exists. `lsof -i :7880` shows livekit-server listening. But `/proc/<wpid>/environ` shows the worker dialing `ai-therapy-v3svfd9o.livekit.cloud`. The two never meet.

**User-visible impact (current state, voice bug):** none directly. The wrong-voice symptom is independent of LiveKit transport.

**User-visible impact (architectural drift):** if the Vercel-deployed frontend at `www.thegoatnote.com/prism42/livekit` mints tokens with `livekit_url: "wss://livekit.thegoatnote.com"` (per `mvp/911-console-live/.env.local:50`) but the worker is dialing `ai-therapy-v3svfd9o.livekit.cloud`, the browser and the worker join DIFFERENT rooms. The browser sees no agent, the agent never sees the browser's audio, the call fails silently. **This may be why the user is hearing the OLD voice — the live cloud-deployed frontend may be pointed at a Vercel deployment of an older `prism42` project that uses ElevenLabs (the cycle-2j fallback path), not the LiveKit-Fish path the worker serves.**

**Fix path:**
- Verify `NEXT_PUBLIC_LIVEKIT_URL` on Vercel prod for BOTH `prism42` (root) AND `prism42-console` (mvp) projects.
- Decide: serve from cloud (drop self-hosted server, simplifies arch) OR serve from self-hosted (point worker at thegoatnote subdomain). Cannot have both running and reachable simultaneously without confusion.
- If self-hosted: change worker .env `LIVEKIT_URL=wss://livekit.thegoatnote.com` (or `ws://127.0.0.1:7880` for in-pod), restart worker, verify with `journalctl -u prism42-worker -f` shows `connected to ws://127.0.0.1:7880`.

### Q4-D: Greeting cache sentinel can't detect text/voice change (verified-by-source)

**Where:** `worker.py:298-306, 1019-1033`.

**Mechanism:**
```python
async def _ensure_greeting_cache(fish_url: str) -> bool:
    if _GREETING_PCM_BYTES is not None:
        return True   # ← cache hit, no re-synth
    return await asyncio.to_thread(_warm_greeting_cache_blocking, fish_url)
```

The ONLY invalidation gate is "is the in-process global non-None". If you `kill -HUP` the worker (no — systemd will restart fully), or change `GREETING_TEXT` in source and reload via systemd's `Restart=always` policy, the cache invalidates because the new process has fresh globals. But:

- If the WAV at `/tmp/prism42-greeting.wav` was archived under voice A, and you restart the worker which re-warms under voice B, the on-disk file IS overwritten (line 269 `with open(GREETING_AUDIO_PATH, "wb")`). So on-disk eventually catches up. Good.
- If you change `PRISM42_FISH_REFERENCE_AUDIO` env, restart worker. Greeting body is hard-coded to NOT use it (line 236 `references: []`). On-disk file is now the same Fish-stock voice as before. **No way to fix this without code change.**

**Fix path:** mirror adapter's reference building in greeting (see Q4-B) OR add a hash of the greeting parameters to the cache filename (`/tmp/prism42-greeting-{sha256(GREETING_TEXT+ref_id+ref_path)}.wav`). The latter eliminates the silent reuse-stale-greeting class entirely.

### Q4-E, Q4-G: AsyncClient + dataclass defaults frozen at import (verified-by-source)

**Where:** `fish_speech_tts.py:28-29, 37-38, 48, 88, 100`.

**Mechanism:** `DEFAULT_REFERENCE_ID`, `DEFAULT_REFERENCE_AUDIO_PATH`, `DEFAULT_REFERENCE_AUDIO_TEXT`, `DEFAULT_PACE_TAG` are module-level constants assigned from `os.environ.get(...)` at import time. The `FishSpeechOptions` dataclass binds these as field defaults (lines 56, 63-64). At `worker.py:659`, `FishSpeechTTS(FishSpeechOptions())` constructs with defaults — frozen as of worker process import.

**Implication:** the env IS read once. Sequence is:
1. Worker process starts (06:30:39 UTC)
2. systemd has injected env (Environment= drop-ins THEN EnvironmentFile applied)
3. `import fish_speech_tts` runs lines 28-48 — captures `FISH_SPEECH_REFERENCE_ID="psap"` (from .env), `PRISM42_FISH_REFERENCE_AUDIO="/opt/prism42/voice-refs/mw_sample.wav"` (from drop-in), `PRISM42_FISH_REFERENCE_TEXT="Bleeding..."` (from drop-in)
4. `FishSpeechOptions()` defaults to those values
5. The mutex at line 167 sees `reference_id="psap"` (truthy) AND audio_path/text both set, takes the FALSE branch (skips inline references)
6. `body["reference_id"] = "psap"` always

**This is the same bug Q1 found, just zoomed-in on the import-time mechanism.** Adds context: post-import os.environ mutation does NOT help — even a hypothetical "monkeypatch the env after start" approach would fail because the dataclass defaults are already locked.

### Q4-F: Hash-cache replays first-paired text (verified-by-source)

**Where:** `vendor/fish-speech/fish_speech/inference_engine/reference_loader.py:99-131`.

**Mechanism:** `load_by_hash` keys by `sha256(ref.audio).hexdigest()`. First time a given audio is sent, line 119 stores `self.ref_by_hash[h] = (prompt_tokens[-1], ref.text)`. Subsequent calls with same audio bytes (line 122-126) return the cached `(token, text)` — **including the first text it was paired with**.

**Implication for cycle-2N deployment:** if MW WAV is sent with a cleaned `PRISM42_FISH_REFERENCE_TEXT` (e.g. fix typo "fear" → "fire" in the trailing question), and Fish has already cached the original pairing, the new text is silently ignored. Mitigation: send `use_memory_cache="off"` for the first request after a text-update deploy, or restart the fish process.

**Likelihood in current state:** low. The current text in the drop-in ends with "Do you see smoke, fear?" which appears to be a typo (probably should read "smoke, fire?") — if/when that's fixed, fish process should be restarted to drop the bad cache entry.

### Q4-H: Audio resampler is innocent (rules out Q5 hypothesis)

**Where:** `livekit/agents/voice/generation.py:406-434`.

**Mechanism:** standard `rtc.AudioResampler` from livekit-rtcsdk. Runs only if `frame.sample_rate != audio_output.sample_rate`. Fish emits 44.1kHz, WebRTC tracks negotiate at 48kHz typically → resampler engages. This is well-tested code; rejecting it as a source of "robotic" artifacts.

**Conclusion:** the robotic perception is on the Fish-side voice identity, not the resampling chain. If MW reference is properly applied, output WILL sound like the MW reference (modulo Fish's documented ~93% f0-variance inheritance per cycle-2N findings) regardless of resampling.

### Q4-I: No fallback / no FallbackAdapter shim (rules out Q3 hypothesis)

**Where:** `fish_speech_tts.py:95-99`, `worker.py:683`, `livekit/agents/voice/agent_activity.py:2204`.

**Mechanism:** `FishSpeechTTS` advertises `TTSCapabilities(streaming=False)`. livekit-agents 1.5.6 then routes to the `synthesize()` method (`agent_activity.py:2204` calls `perform_tts_inference` which calls `self.tts.synthesize(...)` directly — verified by reading `livekit/agents/voice/generation.py`). Worker assigns `_tts = FishSpeechTTS(FishSpeechOptions())` at `worker.py:659` and passes to `AgentSession(tts=_tts, ...)` at line 683. There is NO `FallbackAdapter` wrap, NO `StreamAdapter` wrap, NO plugin-internal TTS that bypasses our adapter.

**Conclusion:** every audible reply in a session goes through our `_FishSpeechStream._run`. There is no stealth path. (Note: greeting goes through `session.say(audio=...)` which is a separate path — Q4-J.)

### Q4-J: Greeting bypasses TTS entirely (verified-by-source)

**Where:** `livekit/agents/voice/agent_activity.py:1021-1097` + `worker.py:1067-1081`.

**Mechanism:** `session.say(text, audio=_greeting_audio_iter(), ...)` triggers `agent_activity.py:1083-1097`'s `_tts_task` branch with `audio=audio` non-None. Internal `_tts_task_impl` at line 2099-onward calls `perform_tts_inference` ONLY when `audio is None` (line 2202). When audio is given, it forwards the AudioFrames directly to `audio_output.capture_frame()`. So the cached PCM is shipped as-is.

**Implication:** the cached greeting is locked at first warm of the worker process. The voice it was rendered in is whatever Fish picked at that moment. No code path re-renders the greeting except worker restart.

### Q4-K: vLLM → orchestrator → adapter (no short-message bypass)

**Where:** `worker.py:580-621` (LLM init), `87-105` (FILLERS), `1180` (`session.say(text, ...)` in fillers).

**Mechanism:** `LLM_BACKEND=vllm-local` constructs `OpenAILLM(...)` at `worker.py:598-610` pointing at `127.0.0.1:8001/v1`. vLLM produces streaming tokens → livekit-agents accumulates → calls `tts.synthesize(text)` per chunk. Fillers at `worker.py:1180` use `session.say(text, allow_interruptions=True)` (NOT `session.say(text, audio=...)`), so they go through the standard TTS path. No short-message TTS bypass.

**Conclusion:** filler voice = dispatcher voice = same Fish synth path. (Rules out Q6.)

### Q4-L: Two Vercel projects (verified-by-source)

**Where:** `.vercel/project.json` (repo root) — `prism42` `prj_TPrURgNWNtXJiltoj8PirlNewXRV`. `mvp/911-console-live/.vercel/project.json` — `prism42-console` `prj_UCqQGmKnXhmqeQgwIHWJ9zzfX4vP`.

**Mechanism:** monorepo with two distinct Vercel projects. Each has its own env vars per (Production, Preview, Development) environment. `vercel env ls` against the current cwd-linked project will show ONE set; the OTHER project's env may differ. `npx vercel env ls` from `mvp/911-console-live` listed `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `NEXT_PUBLIC_LIVEKIT_URL` for both Development and Production with mtime "2d ago" (Apr 24).

**Implication:** if the user is hitting `www.thegoatnote.com/prism42/livekit` and that custom domain is mapped to the OTHER project (`prism42` at `prj_TPrU...`) and that project still has `NEXT_PUBLIC_LIVEKIT_URL` pointing at LiveKit Cloud OR an old custom URL, the browser will dial the wrong room. Worker dials cloud, browser dials thegoatnote → ships ships pass in the night, no audio at all (caller hears nothing OR caller hears whatever fallback was deployed last).

**Fix path:** check Vercel's domain → project mapping. `vercel domains ls` and `vercel project inspect <project>` for both `prj_TPrU...` and `prj_UCqQ...`. Whichever project owns `www.thegoatnote.com/prism42/*` paths is the live one — its `NEXT_PUBLIC_LIVEKIT_URL` and worker `LIVEKIT_URL` MUST agree.

## Surprising stuff worth flagging

1. **Q1's Option A (delete `.env:11`) is more correct than it looks** — it's the only way to get the FishSpeechOptions module-import to capture `reference_id=""` AND `reference_audio_path=/opt/...mw_sample.wav` simultaneously, which then makes the mutex take the inline-references branch. Option B (`UnsetEnvironment`) achieves the same effect at the systemd layer but adds a step (`systemctl daemon-reload && systemctl restart`).

2. **The greeting is rendered TWICE on every cold start** — log shows two `greeting.911.cache_warmed` events (06:35:33 then 06:35:36) with different audio durations (3780ms then 4320ms). This is the entrypoint-spawned background warm (line 565-568) racing with the entrypoint-blocking warm (line 1031). The blocking warm wins (last write to GREETING_AUDIO_PATH is the second one), so the dispatched greeting is the 4320ms one. Wasteful but not incorrect. Worth tracking as a follow-up — the background warm is dead code given the blocking warm always runs.

3. **`vendor/fish-speech/fish_speech/utils/schema.py:95` defaults `use_memory_cache: Literal["on", "off"] = "off"`** — but our adapter sends `"on"` unconditionally (`fish_speech_tts.py:217`). When testing reference voice changes, you can override per-request to `"off"` to bypass Q4-A and Q4-F caches. Not load-bearing for cycle-2N deploy, but useful for any future voice-change validation.

4. **The pod `/tmp/prism42-logs/worker.log` is being SPAMMED with `metrics.captured` debug lines** — multiple per second, all duplicates of the last set of completed-turn metrics. Looks like `_on_metrics` is firing on stale metrics events. Not bug-relevant, but is making log triage difficult — `tail -200` shows only `metrics.captured` lines, useful events are buried thousands of lines back.

5. **Drop-in 100-cycle2N-mwref.conf was added Apr 26 06:30:39 UTC, exact same second as worker process start** — meaning the user did `vim /etc/.../100-cycle2N-mwref.conf && systemctl daemon-reload && systemctl restart prism42-worker` in one fast keystroke sequence. The systemd unit is properly merged (verified by `systemctl show prism42-worker -p Environment`); the merge correctly synthesized the empty FISH_SPEECH_REFERENCE_ID. The bug is in systemd's `Environment=NAME=` semantics, not the deploy procedure.

6. **The cycle-2N findings document (`cycle2N_mw_reference/.../decision.txt:55-58`) explicitly notes**: "100-cycle2N drop-in was NEVER installed — bench was direct Fish HTTP synth mirroring cycle-2j harness pattern". Yet at probe time, `100-cycle2N-mwref.conf` IS installed (mtime 06:30:39 UTC, ~20 min after that decision.txt was written). Someone (the user or a parallel session) installed it after deciding NOT to. The current production state is therefore unintended — the user was explicitly told "MW WAV stays at /opt/prism42/voice-refs/mw_sample.wav as inert data", but the worker now references that WAV via env. That mismatch may be why the symptoms are confusing — the deploy state is past the decision point that said "don't deploy".

7. **The `livekit.thegoatnote.com` Caddy site bound for self-hosted is configured but unused by the agent** — meaning the public face of the LiveKit pipeline IS pointed at the self-hosted server (Caddy will TLS-terminate and proxy to 7880), but the agent process bypasses that entirely and dials cloud. The pod is running TWO LiveKit transports simultaneously, only one of which has a registered agent. This is a strong signal the deploy story is incomplete — either the self-hosted side was set up speculatively and never finished, or the worker .env was reverted to a cloud URL after testing self-host.

## Sources

1. `~/prism42/agents/livekit/fish_speech_tts.py:28-29, 37-38, 48, 53-83, 86-100, 167-222` (verified-by-source)
2. `~/prism42/agents/livekit/worker.py:54, 161-340, 543-702, 1019-1097, 1180` (verified-by-source)
3. `~/prism42/vendor/fish-speech/fish_speech/inference_engine/__init__.py:39-72` (verified-by-source)
4. `~/prism42/vendor/fish-speech/fish_speech/inference_engine/reference_loader.py:62-131` (verified-by-source)
5. `~/prism42/vendor/fish-speech/fish_speech/utils/schema.py:89-95` (verified-by-source)
6. `~/prism42/agents/livekit/.venv/lib/python3.14/site-packages/livekit/agents/voice/agent_activity.py:1021-1097, 2099-2218` (verified-by-source)
7. `~/prism42/agents/livekit/.venv/lib/python3.14/site-packages/livekit/agents/voice/generation.py:400-444` (verified-by-source)
8. `~/prism42/agents/livekit/.venv/lib/python3.14/site-packages/livekit/agents/voice/agent_session.py:1095-1127` (verified-by-source)
9. `~/prism42/.vercel/project.json` — `prism42` project id (verified-by-source)
10. `~/prism42/mvp/911-console-live/.vercel/project.json` — `prism42-console` project id (verified-by-source)
11. `~/prism42/mvp/911-console-live/.env.example:50` — `NEXT_PUBLIC_LIVEKIT_URL=wss://livekit.thegoatnote.com` (verified-by-source)
12. `~/prism42/mvp/911-console-live/components/LiveCallRoom.tsx:91-102` — frontend uses `data.livekit_url` from token-mint (verified-by-source)
13. `~/prism42/mvp/911-console-live/app/prism42/api/livekit-token/route.ts:28-32` — Vercel route reads `process.env.NEXT_PUBLIC_LIVEKIT_URL` (verified-by-source)
14. `~/prism42/infra/b300/Caddyfile:1-30` — `livekit.thegoatnote.com` site config (verified-by-source)
15. `~/prism42/infra/b300/livekit.yaml:1-30` — self-hosted livekit-server config (verified-by-source)
16. Pod SSH probes (read-only) at 2026-04-26T06:42-06:48Z:
    - `/proc/462080/environ` (worker) — `FISH_SPEECH_REFERENCE_ID=psap`, `PRISM42_FISH_REFERENCE_AUDIO=/opt/prism42/voice-refs/mw_sample.wav`, `LIVEKIT_URL=wss://ai-therapy-v3svfd9o.livekit.cloud`, `LLM_BACKEND=vllm-local`, `TTS_BACKEND=fish` (verified-by-source)
    - `ls -la /etc/systemd/system/prism42-worker.service.d/` — drop-in load order 10/20/50/70/100 confirmed (verified-by-source)
    - `cat /etc/systemd/system/prism42-worker.service.d/100-cycle2N-mwref.conf` — `Environment=FISH_SPEECH_REFERENCE_ID=` (empty value) confirmed (verified-by-source)
    - `sudo grep FISH_SPEECH_REFERENCE_ID /opt/prism42/agents/livekit/.env` — line 11 `FISH_SPEECH_REFERENCE_ID=psap` (verified-by-source)
    - `systemctl show prism42-worker.service -p Environment -p EnvironmentFiles` — shows `EnvironmentFiles=/opt/prism42/agents/livekit/.env (ignore_errors=no)` plus merged `Environment=...` block — empty FISH_SPEECH_REFERENCE_ID is in the Environment= block, but EnvironmentFile's psap value latches (verified-by-source)
    - `lsof -i :7880` — livekit-server PID 76823 listening, started Apr 25 21:09 UTC (verified-by-source)
    - `ss -tlnp | grep :9200` — fish process PID 383030 listening, started Apr 25 21:09 UTC (verified-by-source)
    - `stat /tmp/prism42-greeting.wav` — mtime 06:35:36 UTC, post-worker-start, archive overwritten by current process's warm (verified-by-source)
    - `tail /tmp/prism42-logs/worker.log | grep greeting` — `greeting.911.cache_warmed` fired twice on this process (06:35:33 + 06:35:36) (verified-by-source)
    - `pgrep -af livekit-server` — confirms self-hosted server running on pod (verified-by-source)
17. systemd documentation `man systemd.exec` — `Environment=NAME=` (empty RHS) sets to empty string only when no prior source has set the variable; to clear an EnvironmentFile-set variable in a drop-in, use `UnsetEnvironment=NAME` (cited from man-page; not re-fetched in this session, but referenced in Q1's findings as well — Q1 source #14)
18. `findings/voice/cycle2N_mw_reference/2026-04-26T060507Z/decision.txt:1-43` — original cycle-2N decision was REJECT_MW with explicit "100-cycle2N drop-in was NEVER installed"; current pod state contradicts this (verified-by-source — both files read)
19. `npx vercel env ls` (run from `mvp/911-console-live/`) — shows `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `NEXT_PUBLIC_LIVEKIT_URL` exist in Production+Development for the `prism42-console` project, mtime 2d ago (verified-by-source). Did NOT pull values (read-only constraint respected — would have written secrets to disk).
20. `mvp/911-console-live/.env.example:48-50` documents the canonical intent: `NEXT_PUBLIC_LIVEKIT_URL=wss://livekit.thegoatnote.com` (verified-by-source)
