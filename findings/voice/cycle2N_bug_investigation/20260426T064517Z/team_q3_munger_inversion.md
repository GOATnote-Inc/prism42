# Q3 Munger Inversion — what guarantees no MW voice?

Read-only static analysis. No mutations applied. Inversion question:
**what would GUARANTEE the user does NOT hear the MW reference voice
on `https://prism42-console.vercel.app/prism42/livekit`, given:**

- a `100-cycle2N-mwref.conf` drop-in is claimed installed
- worker process env shows `FISH_SPEECH_REFERENCE_ID=psap` STILL set
  (the override apparently failed)
- `PRISM42_FISH_REFERENCE_AUDIO=mw_sample.wav` and
  `PRISM42_FISH_REFERENCE_TEXT="Bleeding,..."` ARE set on the worker
- all 4 services HTTP-healthy
- greeting cache mtime Apr 26 06:35 (post-deploy)
- no `fish.reference_voice.loaded` log events post-deploy

## Top failure modes (ranked by probability)

| #  | Failure mode                                                                    | Likelihood | Cost to validate           | Cost to fix                |
|----|---------------------------------------------------------------------------------|------------|----------------------------|----------------------------|
| F1 | `reference_id=psap` wins — engine silently drops `references` payload           | ~0.85      | grep one source line       | one-line drop-in / unit env |
| F2 | systemd `Environment=FISH_SPEECH_REFERENCE_ID=` (empty) does NOT clear the var when `EnvironmentFile=` already loaded a non-empty value | ~0.80 | `systemctl show prism42-worker -p Environment` | `Environment=FISH_SPEECH_REFERENCE_ID=" "` workaround OR `sudo sed -i 's/^FISH_SPEECH_REFERENCE_ID=.*/FISH_SPEECH_REFERENCE_ID=/' /opt/prism42/agents/livekit/.env` |
| F3 | The greeting "Nine one one. Where is your emergency?" is served from PCM cache that was warmed under PSAP voice and never invalidated; user hears the greeting first and stops listening | ~0.55 | check what the user heard — was it the greeting only, or a reply? Listen end-of-call, after a follow-up turn | n/a (greeting is intentional non-MW) |
| F4 | User's browser audio cache or Vercel CDN edge is stale; the demo URL was loaded BEFORE the deploy and has not been hard-reloaded | ~0.40 | check Vercel-side last-deploy ts vs first listen attempt | hard-reload (Cmd-Shift-R) |
| F5 | LiveKit room sticky-routing to a previously-spawned worker process (PID ≠ 462080) that still has old env (`FISH_SPEECH_REFERENCE_ID=psap` AND no MW envs) | ~0.30 | `pgrep -af worker.py` on pod, count workers; check LiveKit Cloud dispatch logs | restart all workers, ensure single-worker config |
| F6 | `_GREETING_PCM_BYTES` cache survives across systemd restart via shared FS at `/tmp/prism42-greeting.wav`; warm path reads stale file? (NO — re-read shows warm always re-synths via HTTP, file is archive-only. See worker.py:268-276.) | ~0.05 | inspect _warm_greeting_cache_blocking semantics | n/a (this hypothesis falsified by source code) |
| F7 | LiveKit Agents 1.5.6 internal TTS (e.g. preemptive-tts cache or default echo path) bypasses our FishSpeechTTS plugin entirely | ~0.05 | grep livekit-agents 1.5.6 source for any `tts.synthesize` callsite that does not route through `session.tts` | n/a if false |
| F8 | MW voice is acoustically close-enough to "old robotic" that user perception cannot differentiate; cycle-2k pace tag was disabled, cycle-2f tags off, dispatcher reply text differs from MW reference content ("Bleeding, choking..." vs LLM-generated reply text) | ~0.20 (covering, not exclusive) | listen test on captured audio file with known voice metadata | reference voice still IS firing; user just can't tell — would not match the F1/F2 evidence above |
| F9 | The Vercel demo's `NEXT_PUBLIC_LIVEKIT_URL` points at a different LiveKit project / different B300 pod entirely | ~0.10 | `vercel env pull` or read browser devtools → WS URL on /prism42/livekit | redeploy with correct env |
| F10 | Pre-cached `/tmp/prism42-greeting.wav` exists from before the deploy; module-level `_GREETING_PCM_BYTES` is None on fresh process so re-warmed via HTTP — but the HTTP path itself silently uses `reference_id=psap` (because the greeting body at worker.py:221-237 sets `references=[]` and does NOT include `reference_id`, so it depends on Fish-side server defaults rather than worker env). Wait — re-read: greeting body has NO `reference_id` field at all. Server may apply a default reference if registered. | ~0.45 | check Fish server default reference behavior; `curl http://127.0.0.1:9200/v1/references/list` | n/a if greeting is OK; greeting is intentional and matches user expectation of "9-1-1, where is your emergency" |

## Per-mode detail

### F1 — `reference_id=psap` wins; `references` payload silently dropped (HIGHEST)

**Mechanism.** Fish-engine code at
`vendor/fish-speech/fish_speech/inference_engine/__init__.py:48-57`:
```
ref_id: str | None = req.reference_id
if ref_id is not None:
    prompt_tokens, prompt_texts = self.load_by_id(ref_id, req.use_memory_cache)
elif req.references:
    prompt_tokens, prompt_texts = self.load_by_hash(req.references, ...)
```
The engine ONLY falls back to inline `references` when `reference_id is None`.
The adapter mirrors this contract at `fish_speech_tts.py:166-193`: it skips
inline reference assembly when `self._opts.reference_id` is truthy (line 168),
which means **even though `PRISM42_FISH_REFERENCE_AUDIO` and `PRISM42_FISH_REFERENCE_TEXT`
are correctly set, the adapter never builds the `references_payload` because
`FISH_SPEECH_REFERENCE_ID=psap` is still in the worker env**. So no
`fish.reference_voice.loaded` log fires (line 181), the request includes
`reference_id: "psap"`, and the server uses the psap preset.

**Evidence.**
- `agents/livekit/fish_speech_tts.py:166-193` — adapter mutex matches engine.
- `agents/livekit/fish_speech_tts.py:221-222` — body unconditionally
  appends `reference_id` when truthy.
- Diagnostic prior: `FISH_SPEECH_REFERENCE_ID=psap` in process env.
- Diagnostic prior: NO `fish.reference_voice.loaded` events post-deploy.

**Validation probe.** `grep -n "reference_id\|reference_audio\|reference_text" /Users/kiteboard/prism42/agents/livekit/fish_speech_tts.py | head -10` confirms mutex.

**Remediation.** Either (a) actually clear `FISH_SPEECH_REFERENCE_ID` in the
running worker env, or (b) change the adapter mutex to prefer
`PRISM42_FISH_REFERENCE_AUDIO` over `reference_id` when both are set — but
that would break upstream Fish engine semantics (server still drops
references). So **(a) is the only correct fix** — the precedence is
established at the Fish ENGINE layer, not the adapter.

### F2 — systemd `Environment=KEY=` empty does not "unset" when `EnvironmentFile=` already loaded a value

**Mechanism.** systemd's documented merge order:
1. Base unit `[Service]` block is parsed (no env vars yet).
2. `EnvironmentFile=/opt/prism42/agents/livekit/.env` is loaded — this
   reads `FISH_SPEECH_REFERENCE_ID=psap` from `setup_psap_reference.sh`
   line 47 (which appended that line to the file, so it lives there).
3. Drop-ins under `prism42-worker.service.d/*.conf` are applied in
   filename-sort order. Each drop-in's `Environment=KEY=value` adds to
   the merged map.

The catch: a directive `Environment=FISH_SPEECH_REFERENCE_ID=` with
empty RHS sets the var to **empty string**, not unset. systemd-show may
display it as cleared, but if any downstream Python code reads it and
treats `""` and `None` differently, behavior diverges.

In our adapter, the relevant read is at `fish_speech_tts.py:29`:
`DEFAULT_REFERENCE_ID = os.environ.get("FISH_SPEECH_REFERENCE_ID", "")`.
This treats unset and empty equivalently — both produce `""`, the
`reference_id` field on `FishSpeechOptions` is `""` (falsy), and the
mutex at line 167-168 should let inline assembly proceed.

So the adapter SHOULD honor an empty drop-in. But the diagnostic prior
says `FISH_SPEECH_REFERENCE_ID=psap` is STILL set in the process env.
Either (i) the drop-in was never installed at the path systemd loads
from (`/etc/systemd/system/prism42-worker.service.d/100-cycle2N-mwref.conf`
vs `/opt/prism42/...` — only the systemd-managed path counts);
(ii) `daemon-reload` wasn't run after install; (iii) the worker
wasn't restarted after `daemon-reload` so old env survives in the
already-running PID 462080; (iv) the drop-in does set the var but
the .env file has `FISH_SPEECH_REFERENCE_ID=psap` AFTER the drop-in
in merge order — but that's not how systemd works, drop-in `Environment=`
should override `EnvironmentFile=` content (per systemd.exec(5):
"variables set with Environment= will override those from
EnvironmentFile="). Most likely cause: **the worker process was
not actually restarted after the drop-in install + daemon-reload**.

**Evidence.**
- `prism42-worker.service:11` — `EnvironmentFile=/opt/prism42/agents/livekit/.env`.
- `setup_psap_reference.sh:47` — appends `FISH_SPEECH_REFERENCE_ID=psap`
  to that file.
- Diagnostic prior: `FISH_SPEECH_REFERENCE_ID=psap` STILL in process env
  for PID 462080.
- systemd.exec(5): `Environment=` from drop-in overrides `EnvironmentFile=`
  content, but BOTH only apply at process spawn time. An already-running
  PID retains its original env exec.

**Validation probe.** On pod:
- `cat /etc/systemd/system/prism42-worker.service.d/100-cycle2N-mwref.conf`
  to confirm content + path.
- `systemctl show prism42-worker -p Environment` to see merged env (this
  is what would BE applied on next start — not necessarily the running PID).
- `systemctl show prism42-worker -p MainPID,ExecMainStartTimestamp` —
  is MainPID 462080? Has it restarted since the drop-in install?
- `cat /proc/462080/environ | tr '\0' '\n' | grep -i fish` — what env
  does the actually-running PID have?

**Cheapest probe of all four:** the last one — `/proc/<pid>/environ` is
the ground truth for the running PID. If `FISH_SPEECH_REFERENCE_ID=psap`
appears there, the worker started before the drop-in took effect.

**Remediation.** `sudo systemctl daemon-reload && sudo systemctl restart prism42-worker`.

### F3 — Greeting cache served from psap-warmed PCM that never invalidated

**Mechanism.** `worker.py:210-307` — `_warm_greeting_cache_blocking`
synthesizes the greeting via Fish HTTP at boot. CRITICAL: the body
(line 221-237) does NOT include `reference_id` AND has `references=[]`.
This means the greeting synthesis path bypasses BOTH reference
mechanisms entirely — it relies on whatever Fish server default is in
play (the `--reference_id` CLI flag at server start, OR the implicit
"default voice" with no reference). The worker module-global
`_GREETING_PCM_BYTES` lives in process memory; mtime Apr 26 06:35
suggests this was generated AT or AFTER the deploy.

If the user heard ONLY the greeting and stopped listening (because they
expected MW voice and it sounded similar to "old robotic"), the
inversion is satisfied without any of the F1/F2 paths even mattering.
The greeting voice was always going to be the Fish-server-default
voice, which has been "psap" since cycle-2L (or whatever was the
last `--reference_id` server flag).

But the user said "still old robotic voice" past the greeting. So this
mode alone is insufficient — the dispatch reply (which DOES route
through FishSpeechTTS with full env-config) must also be hitting psap.
Combined with F1/F2: greeting is psap because the synth body explicitly
omits reference_id; reply is psap because the adapter's mutex prefers
`reference_id` over `references`.

**Evidence.**
- `worker.py:221-237` — greeting body has `references=[]`, no `reference_id`.
- `worker.py:1067-1075` — greeting played via `session.say(audio=...)`,
  bypassing TTS entirely on hot path.
- Diagnostic prior: greeting cache mtime Apr 26 06:35 (post-deploy).

**Validation probe.** Listen to greeting WAV at `/tmp/prism42-greeting.wav`
on pod (or scp it down) — compare to MW sample. If they sound
indistinguishable, the user heard the cached greeting and assumed it
was the whole reply. If they sound different, the user definitely
heard the reply path too.

**Remediation.** If greeting needs to also use MW: change worker.py
greeting body (line 221-237) to include `references` OR set
server-default to MW reference. Currently NOT in scope — the greeting
IS intentionally a baseline "9-1-1, where is your emergency?" and the
MW reference target is the **dispatch reply**, not the greeting.

### F4 — Vercel/browser cache stale

**Mechanism.** The /prism42/livekit page is a Next.js client component
that opens a WebSocket via `NEXT_PUBLIC_LIVEKIT_URL`. The audio comes
LIVE over WebRTC to `wss://livekit.thegoatnote.com:7882`, so audio
itself cannot be browser-cached — it's UDP RTP frames decoded in
real time. But the *page bundle* and ESPECIALLY the JWT mint route
config can be cached. If the page was last loaded BEFORE the cycle-2N
deploy, and the user did not hard-reload, the page bundle could be
referencing an older worker pool. (Probably not — the worker pool is
LiveKit-side, not Vercel-side.)

**Evidence.** `mvp/911-console-live/app/prism42/livekit/page.tsx` is
client component. `vercel.json:8` regions: `iad1`. No CDN-side audio
caching is plausible.

**Validation probe.** Hard-reload (Cmd-Shift-R) and try again. If
problem persists, F4 is falsified.

**Remediation.** Hard-reload. No code change.

### F5 — Multiple worker processes; LiveKit dispatched to non-MW worker

**Mechanism.** If the systemd unit failed to fully kill the old worker
and a new one spawned, two workers may be racing for LiveKit dispatch.
The diagnostic prior says PID 462080 is THE worker, but if there are
also stale processes from prior runs (e.g. `nohup` recovery mentioned
in finding-6 of the durable-findings memory) they could still be
holding LiveKit registration.

**Evidence.** None positive; relies on operational hygiene gap.

**Validation probe.** On pod: `pgrep -af 'python.*worker.py' | wc -l`.
Should equal 1.

**Remediation.** `sudo systemctl restart prism42-worker`; verify
single PID after.

### F6 — Greeting cache file persistence across restart (FALSIFIED)

**Mechanism.** I considered whether `_GREETING_PCM_BYTES` could be
recovered from `/tmp/prism42-greeting.wav` on warm-restart. Re-read of
`worker.py:210-306` confirms: every fresh process always re-synths via
HTTP (no file read on the warm path). The file is archive-only. So
the cache is truly per-process and dies with the worker. With mtime
Apr 26 06:35 it was synthesized POST-deploy. **Falsified.**

### F7 — LiveKit Agents 1.5.6 alternate TTS path bypassing our plugin

**Mechanism.** Hypothetically, the adaptive-interruption / preemptive-
generation pipeline might have its own TTS shim. Re-reading the
`AgentSession` config in `worker.py:679-703`, the only `tts=` slot
is our `FishSpeechTTS`. Preemptive-TTS speculatively warms our TTS
plugin, not a separate one. Adaptive interruption is audio-input only.

**Evidence.** No 1.5.6 source citation positive for an alternate path.

**Validation probe.** `grep -rn "tts.synthesize\|tts.stream" agents/livekit/.venv/lib/python3.14/site-packages/livekit/agents/voice/`. Any path NOT routing through `session.tts` would be a smoking gun.

**Remediation.** None until probe positive.

### F8 — MW voice indistinguishable from psap-fast / "robotic"

**Mechanism.** Per cycle-2N decision (`/Users/kiteboard/prism42/findings/voice/cycle2N_mw_reference/2026-04-26T060507Z/decision.txt:1-9`):

```
MW            mean f0_std 35.7   mean f0_range 202.3
psap-fast     mean f0_std 28.6   mean f0_range 132.8
```

MW has HIGHER f0 variance than psap-fast — not a wildly different voice.
And the live deploy still uses `FISH_SPEECH_REFERENCE_ID=psap` (not
psap-fast), so the user is comparing MW (in the user's mental model)
against `psap` (in the actual wire). The acoustic gap MAY be
perceptible, but if the user's calibration of "old robotic" is the
psap baseline, MW would have to overcome that perceptual prior in
~one listening pass. If F1/F2 are true, MW never even fires, so this
mode is moot. If F1/F2 are false, this mode could explain a "false
negative" on the user's perception.

**Evidence.** cycle-2N f0 measurements above; cycle-2L pace tag was
disabled; cycle-2f tags off.

**Validation probe.** Capture Fish-side request body during a live
session (Fish log shows the full body in INFO mode). If request body
has `reference_id: "psap"` AND empty/missing `references`, F1+F2 are
confirmed and F8 is moot. If body has populated `references` AND no
`reference_id`, F1+F2 are falsified and F8 (perception) is the
remaining explanation.

**Remediation.** N/A in inversion frame (this is "not actually broken").

### F9 — `NEXT_PUBLIC_LIVEKIT_URL` mis-pointed

**Mechanism.** Vercel-side env. If the demo URL is built against a
NEXT_PUBLIC_LIVEKIT_URL pointing at a different LiveKit project (e.g.
LiveKit Cloud project A vs B), the dispatch goes to a different worker
pool entirely. None of our pod-side env changes apply.

**Evidence.** `.env.example:50` shows `NEXT_PUBLIC_LIVEKIT_URL=wss://livekit.thegoatnote.com`. As long as Vercel prod has this value, the URL points at OUR Caddy front-end → our pod's livekit-server.

**Validation probe.**
- Browser devtools → Network → WS frames on /prism42/livekit page.
  Confirm the WebSocket URL is `wss://livekit.thegoatnote.com/...`.
- `vercel env ls --environment production --token <token>` (read-only).

**Remediation.** Sync env, redeploy. Out of scope unless probe-confirmed.

### F10 — Greeting bypass: server-default reference applied to greeting body

**Mechanism.** `worker.py:236` sets `references=[]` AND no `reference_id`
field in the greeting body. Fish server may have a default reference
configured at server-start time (the `--reference_id` CLI flag at
`vendor/fish-speech/tools/server/views.py`). If that flag is `psap`,
the greeting comes out in psap voice. Otherwise it's the bare model
voice (whatever Fish ships out of the box).

**Evidence.** `worker.py:221-237`. Fish server start config not in
this conversation context but documented at
`vendor/fish-speech/docs/en/server.md:30-62` per J0 sources.

**Validation probe.** `ps -ef | grep api_server.py` on pod; look for
`--reference_id` flag.

**Remediation.** Out of scope for this task; the greeting MW-ification
is a separate cycle.

## Cheapest-to-validate first

The single highest-leverage probe, in this order:

1. **`cat /proc/462080/environ | tr '\0' '\n' | grep -i fish_speech_reference_id`**
   on the pod — settles F2 instantly. If output is `FISH_SPEECH_REFERENCE_ID=psap`,
   the running worker has the OLD env and a restart fixes it. If output is
   empty, F2 is falsified.

2. **`tail -100 /tmp/prism42-logs/fish.log | grep -E "Loaded audio|Encoded prompt|reference_id"`**
   — what did Fish-server actually receive? If it logs `reference_id=psap`
   on every recent synth call, F1 is confirmed.

3. **`grep -n "reference_id\|references" /Users/kiteboard/prism42/agents/livekit/fish_speech_tts.py | head -20`**
   (already done) — confirms adapter mutex.

4. **`ls -la /etc/systemd/system/prism42-worker.service.d/`** on pod
   (claimed step the user already did; re-confirm path).

5. **`systemctl show prism42-worker -p MainPID,ExecMainStartTimestamp`**
   on pod — was the worker actually restarted post-drop-in? If
   ExecMainStartTimestamp is BEFORE the drop-in install time, restart
   is the fix.

If all five point at "drop-in is installed, MainPID was restarted after,
but `/proc/<pid>/environ` STILL has `FISH_SPEECH_REFERENCE_ID=psap`",
then the drop-in's `Environment=FISH_SPEECH_REFERENCE_ID=` empty value
is genuinely not overriding `EnvironmentFile=`'s value — that is a
systemd-drop-in semantic worth verifying with `systemctl show`. The
escape hatch is to set `Environment=FISH_SPEECH_REFERENCE_ID=__none__`
and have the adapter treat `__none__` as unset, OR to simply
`sudo sed -i '/^FISH_SPEECH_REFERENCE_ID=/d' /opt/prism42/agents/livekit/.env`.

Estimated total time to validate all 5 probes: **under 3 minutes** (one
ssh, five reads).

## What this DOESN'T explain

The inversion above accounts for "user hears a non-MW voice." It does
not explain:

- **Latency degradation.** If the user perceives "robotic" partly as
  jitter / stutter / dropouts (not voice timbre), F1-F10 don't address
  it. Look at preemptive-tts pipeline or RTF measurements separately.
- **The dispatcher reply *content* sounding off.** If the user heard
  MW-correct timbre but unfamiliar phrasing, that's an LLM-side issue,
  not a TTS-side issue. The orchestrator's STEP 2 Opus call generates
  the reply text — its content is independent of which voice renders it.
- **A scenario where MW DOES fire but the user can't tell.** F8 partly
  covers this; if F1+F2 are falsified by the probes above and the
  user STILL says "robotic," the answer is perception, not config.
- **Vercel-side caching of API responses** for the rubric/transcript
  SSE feeds. Those are server-sent events with `no-cache` headers
  (`vercel.json` sets maxDuration but no cache headers); voice path
  is WebRTC and unaffected.

## Sources

- `/Users/kiteboard/prism42/agents/livekit/fish_speech_tts.py:29,166-193,221-222`
  — adapter mutex (the `reference_id`-wins contract)
- `/Users/kiteboard/prism42/agents/livekit/worker.py:54,210-306,659,1067-1075`
  — Fish TTS instantiation, greeting cache warm path, `session.say` greeting dispatch
- `/Users/kiteboard/prism42/agents/livekit/prism42-worker.service:11`
  — `EnvironmentFile=` declaration
- `/Users/kiteboard/prism42/infra/b300/services/fish-speech/setup_psap_reference.sh:47`
  — proves `FISH_SPEECH_REFERENCE_ID=psap` was appended to `/opt/prism42/agents/livekit/.env` historically
- `/Users/kiteboard/prism42/findings/voice/cycle2j_reference_voice/2026-04-26T014938Z/team_j0_static_audit.md:117-134`
  — engine-side reference precedence (silent drop)
- `/Users/kiteboard/prism42/findings/voice/cycle2N_mw_reference/2026-04-26T060507Z/decision.txt`
  — cycle-2N MW reference results, REJECT_MW verdict; key f0 numbers
- `/Users/kiteboard/prism42/findings/voice/cycle2N_mw_reference/2026-04-26T060507Z/summary.md:53-60`
  — explicit production-state note: "100-cycle2N drop-in NOT installed,
  FISH_SPEECH_REFERENCE_ID=psap from .env stays canonical, env var
  PRISM42_FISH_REFERENCE_AUDIO unset" (this matches the diagnostic
  prior — drop-in stage was never actually committed before user listened)
- `/Users/kiteboard/.claude/projects/-Users-kiteboard/memory/prism42_b300_voice_durable_findings.md`
  — durable-findings cycle-2 context
- systemd.exec(5) — `Environment=` overrides `EnvironmentFile=` documented
  semantic; both apply only at process spawn

Co-Authored-By: Claude Opus 4.7 (do not commit; integrator commits.)
