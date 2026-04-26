# Q1 Code Review — voice path bug

UTC timestamp: 20260426T064303Z
Reviewer: Team Q1 (read-only code review, glasswing-discipline)
Repo HEAD reviewed: `/Users/kiteboard/prism42/agents/livekit/`
Pod canonical reviewed: `prism-mla-b300-h4h5:/opt/prism42/agents/livekit/`

## Bottom line

The MW reference voice deployment fails to take effect because
`/opt/prism42/agents/livekit/.env` (line 11) hard-codes
`FISH_SPEECH_REFERENCE_ID=psap`, and **systemd processes
`EnvironmentFile=` BEFORE drop-in `Environment=` directives, but a later
`Environment=` only wins when the value is non-empty**. Setting
`Environment=FISH_SPEECH_REFERENCE_ID=` in
`100-cycle2N-mwref.conf` does NOT clear an inherited value from the
EnvironmentFile — systemd treats the empty `Environment=NAME=` as a
no-op when the variable was already set upstream. The worker process
inherits `FISH_SPEECH_REFERENCE_ID=psap`, the adapter's mutex at
`fish_speech_tts.py:167-171` then sees `reference_id` truthy and
**short-circuits the inline references_payload to `[]`** (line 166),
sending the request to Fish with `reference_id="psap"` and zero
inline reference audio. Fish renders the old psap/Samantha voice
because that's the only voice token in the request body.

Verified by reading running worker process env via
`/proc/$(pgrep -f worker.py)/environ` at 2026-04-26T06:42Z:

```
PRISM42_FISH_REFERENCE_AUDIO=/opt/prism42/voice-refs/mw_sample.wav
PRISM42_FISH_REFERENCE_TEXT=Bleeding, choking, or trouble breathing? ...
FISH_SPEECH_REFERENCE_ID=psap          ← drop-in did NOT override
PRISM42_FISH_PACE_TAG=
FISH_SPEECH_URL=http://127.0.0.1:9200
TTS_BACKEND=fish
```

## Env source precedence (pod systemd)

systemd-unit drop-ins layer in this order (lowest → highest):

1. main unit `EnvironmentFile=/opt/prism42/agents/livekit/.env`
2. drop-ins applied alphabetically by filename, each adding to the
   environment built so far. Important nuance: `Environment=NAME=`
   with empty RHS does NOT unset; it sets to empty string ONLY if
   no prior source set it. To unset/clear an EnvironmentFile value,
   you need `UnsetEnvironment=NAME` (separate directive), not
   `Environment=NAME=`.

| Source | Path | Sets `FISH_SPEECH_REFERENCE_ID`? | Effective value | Order |
|---|---|---|---|---|
| Main unit `EnvironmentFile=` | `/opt/prism42/agents/livekit/.env:11` | Yes — `psap` | psap | 1 (lowest precedence in declaration order, but value latches) |
| Drop-in `10-vllm-model.conf` | n/a | No (sets VLLM_MODEL only) | — | 2 |
| Drop-in `20-vllm-max-tokens.conf` | n/a | No | — | 3 |
| Drop-in `50-cycle2i-greeting.conf` | n/a | No (sets greeting flag) | — | 4 |
| Drop-in `70-cycle2k-pacetag.conf` | n/a | No (empty pace tag) | — | 5 |
| Drop-in `100-cycle2N-mwref.conf` | `/etc/systemd/system/prism42-worker.service.d/100-cycle2N-mwref.conf:5` | `Environment=FISH_SPEECH_REFERENCE_ID=` (empty) | NO-OP — earlier value latches | 6 |

Net inherited environment for worker process: **`FISH_SPEECH_REFERENCE_ID=psap`**.

## Adapter mutex (fish_speech_tts.py)

File: `/Users/kiteboard/prism42/agents/livekit/fish_speech_tts.py`
(repo SHA differs from pod by Cycle-2L comma-to-period block at
pod-only lines 200-207, irrelevant to this bug).

Module-init read of env (frozen at import time, line 29):
```python
DEFAULT_REFERENCE_ID = os.environ.get("FISH_SPEECH_REFERENCE_ID", "")
```
Bound onto `FishSpeechOptions.reference_id` default at line 56.

The mutex sits in `_FishSpeechStream._run` at lines 166-193:

```python
references_payload: list[dict] = []
if (
    not self._opts.reference_id           # ← gates on reference_id falsy
    and self._opts.reference_audio_path
    and self._opts.reference_audio_text
):
    try:
        with open(self._opts.reference_audio_path, "rb") as f:
            audio_bytes = f.read()
        references_payload = [
            {"audio": audio_bytes,
             "text": self._opts.reference_audio_text}
        ]
        ...
```

Then at lines 199-222:
```python
body = {
    ...
    "references": references_payload,    # ← stays []
}
if self._opts.reference_id:               # ← truthy "psap"
    body["reference_id"] = self._opts.reference_id   # ← psap goes on wire
```

**Net behavior** when env is `FISH_SPEECH_REFERENCE_ID=psap`:
`references_payload` is the empty list (mutex took the `if` branch
that requires `not reference_id`), and `body["reference_id"] = "psap"`.
Fish renders the psap voice. The MW WAV at
`/opt/prism42/voice-refs/mw_sample.wav` is never opened, never read,
never sent. There is no log line `fish.reference_voice.loaded` in
`/tmp/prism42-logs/worker.log` after worker restart, because the
`open()` call is inside the unreachable `if` branch.

The frozen-at-module-init read on line 29 also means: even if a
runtime-only env mutation happened (it doesn't here, but as a closed
question), the dataclass default has already captured `"psap"` and a
subsequent `del os.environ["FISH_SPEECH_REFERENCE_ID"]` would not
re-bind it.

## Greeting cache code path (worker.py)

File: `/Users/kiteboard/prism42/agents/livekit/worker.py` lines 161-340.

The greeting at the top of every call ("Nine one one. Where is your
emergency?") is rendered via a SEPARATE httpx call inside
`_warm_greeting_cache_blocking`, lines 210-295. **It bypasses the
`FishSpeechTTS` adapter entirely.** Notable details:

- Body construction at lines 221-237 hard-codes `"references": []`
  AND does NOT pass any `reference_id` field. So the greeting renders
  in **Fish's default voice** regardless of env:
  ```python
  body = {
      "text": GREETING_TEXT,         # "Nine one one. Where is your emergency?"
      "format": "wav",
      "chunk_length": 200,
      "normalize": True,
      "streaming": True,
      "max_new_tokens": 1024,
      "top_p": 0.7,
      "repetition_penalty": 1.1,
      "temperature": 0.1,
      "use_memory_cache": "on",
      "seed": 911,
      "references": [],              # ← always empty
  }                                  # ← no `reference_id` key at all
  ```
- Cache invariant (lines 304-306): `_GREETING_PCM_BYTES is not None`
  is the cache-warm sentinel. It is never invalidated. Once the
  greeting is warmed once per worker process, it is reused for every
  session for the lifetime of the process.
- **Implication for cycle-2N reference change:** even AFTER fixing
  the env precedence bug for the dispatcher reply path, the greeting
  cache will still play whatever voice was cached on first warm of
  the current worker process. To pick up a voice change, the worker
  MUST be restarted (drops the `_GREETING_PCM_BYTES` module global)
  AND the greeting body MUST be modified to include the inline
  references payload (it currently sends `references=[]`).
- The greeting pre-warm + dispatch wiring is at lines 1019-1090; the
  cached PCM frames are streamed via `_greeting_audio_iter()` (lines
  309-340), which is a pure replayer with no Fish call.

In the current pod state, the greeting renders in Fish's stock voice
(neither psap nor MW), and the dispatcher follow-on replies render in
the psap voice (because they go through the adapter, which gets the
`reference_id="psap"` short-circuit). That is the "still robotic
voice" the public demo exhibits.

## Other fish-synth call sites

| File:line | Purpose | Passes `reference_id` explicitly? | Sends inline `references`? |
|---|---|---|---|
| `worker.py:210-295` (`_warm_greeting_cache_blocking`) | Greeting pre-synth | No (key absent from body) | `[]` always (line 236) |
| `fish_speech_tts.py:135-289` (`_FishSpeechStream._run`) | All dispatcher TTS | Conditional — `if self._opts.reference_id:` (line 221) | Conditional — only when `reference_id` falsy AND audio path+text set (lines 167-171) |
| `synthetic_caller_full.py:42,66` | Local test harness for synthetic 911 caller (not a runtime path on the worker) | n/a — sends own body | n/a |
| `bench_b300.py:138` (`fish_healthy`) | Liveness probe (`GET /v1/...` not `/v1/tts`) | n/a | n/a |

The dispatcher-reply path (the one the user hears once the LLM
generates a turn) goes through `FishSpeechTTS` only — there is no
short-circuit, no parallel httpx fallback, no specialist-routed Fish
call. So the bug's blast radius is exactly: every dispatcher reply
during a session, plus the greeting (which has its own
`references=[]` hard-code).

## Recommended surgical fix (one-line preferred)

The bug lives on the systemd / .env axis, not in the Python. Two
candidate fixes, both one-edit:

**Option A (systemd-side, preferred — fixes the env source of truth):**

File: `/opt/prism42/agents/livekit/.env:11` (pod, root-owned)
Change: delete or comment out the line `FISH_SPEECH_REFERENCE_ID=psap`.

Rationale: the EnvironmentFile is the OUTERMOST source. With that
line gone, the variable is unset by the time the drop-in's empty
`Environment=FISH_SPEECH_REFERENCE_ID=` runs (which then sets it to
empty string), and the adapter mutex at lines 167-171 takes the
inline-references branch. No code change. Survives restart. Auditable
in `git log` of any /prism42-public mirror that tracks .env.example.

**Option B (systemd-side, alternative — uses the explicit unset directive):**

File: `/etc/systemd/system/prism42-worker.service.d/100-cycle2N-mwref.conf`
Change line 5 from `Environment=FISH_SPEECH_REFERENCE_ID=` to:
```
UnsetEnvironment=FISH_SPEECH_REFERENCE_ID
```
Rationale: this is the systemd-canonical way to clear an
EnvironmentFile-set variable in a drop-in. Zero ambiguity.
`Environment=NAME=` (empty RHS) is NOT a clear; `UnsetEnvironment=`
is. After the change: `systemctl daemon-reload && systemctl restart
prism42-worker`. Verify with
`tr '\0' '\n' < /proc/$(pgrep -f worker.py)/environ | grep REFERENCE_ID`
— should be absent (or empty, depending on whether anything else sets
it).

**Code-side hardening (separate commit, do later, NOT load-bearing for the demo):**

File: `fish_speech_tts.py:166-171`
Change the mutex from "reference_id falsy" to "reference_id absent OR
explicitly disabled by sentinel":
```python
# Treat reference_id="" or "none" as explicit disable so EnvironmentFile
# residue can't shadow PRISM42_FISH_REFERENCE_AUDIO.
_ref_id = (self._opts.reference_id or "").strip().lower()
_ref_id_active = bool(_ref_id) and _ref_id != "none"
if (
    not _ref_id_active
    and self._opts.reference_audio_path
    and self._opts.reference_audio_text
):
    ...
```
This still preserves the engine-side mutex contract
(vendor/.../inference_engine/__init__.py:48-57) but lets a deployer
type `FISH_SPEECH_REFERENCE_ID=none` to definitively disable the
named reference without having to delete the EnvironmentFile line.
Rationale: defense-in-depth so a future drop-in author who hits
this same `Environment=NAME=` confusion can't silently regress.

Recommend shipping Option A (or B) IMMEDIATELY for the demo, then
filing the code-side hardening as a follow-up commit. Option A wins
on simplicity if no other code path reads `FISH_SPEECH_REFERENCE_ID`
from .env as a non-default (it doesn't — only `fish_speech_tts.py:29`
reads it).

Greeting follow-up (separate, demo-secondary): if the demo wants the
greeting itself to render in the MW voice, edit
`worker.py:221-237` to mirror the adapter's references_payload
construction (read `PRISM42_FISH_REFERENCE_AUDIO` + `_TEXT` env at
warm time, populate `body["references"]`). Without that, the
greeting will always render in Fish's stock voice. Acceptable for
the demo; user-perceived continuity comes from the *dispatcher* voice
matching once the conversation starts.

## Sources

1. `/etc/systemd/system/prism42-worker.service` (main unit, via `systemctl cat prism42-worker`)
2. `/etc/systemd/system/prism42-worker.service.d/100-cycle2N-mwref.conf:1-5` (drop-in)
3. `/etc/systemd/system/prism42-worker.service.d/{10,20,50,70}-*.conf` (other drop-ins, alphabetical order verified by `ls -la`)
4. `/opt/prism42/agents/livekit/.env:11` — `FISH_SPEECH_REFERENCE_ID=psap`
5. `/proc/$(pgrep -f worker.py)/environ` (read 2026-04-26T06:42Z) confirming `FISH_SPEECH_REFERENCE_ID=psap` in running process
6. `/Users/kiteboard/prism42/agents/livekit/fish_speech_tts.py:29` — `DEFAULT_REFERENCE_ID = os.environ.get("FISH_SPEECH_REFERENCE_ID", "")`
7. `/Users/kiteboard/prism42/agents/livekit/fish_speech_tts.py:56` — dataclass default binding
8. `/Users/kiteboard/prism42/agents/livekit/fish_speech_tts.py:166-193` — mutex on `not self._opts.reference_id`
9. `/Users/kiteboard/prism42/agents/livekit/fish_speech_tts.py:199-222` — body assembly, `body["reference_id"] = self._opts.reference_id` when truthy
10. `/Users/kiteboard/prism42/agents/livekit/worker.py:210-295` — greeting `_warm_greeting_cache_blocking`, `body["references"] = []` hard-coded line 236, no `reference_id` key
11. `/Users/kiteboard/prism42/agents/livekit/worker.py:304-306` — greeting cache invariant (`_GREETING_PCM_BYTES is not None`); never invalidated mid-process
12. `/Users/kiteboard/prism42/agents/livekit/worker.py:54,659` — only one `FishSpeechTTS` construction site in the worker
13. `/Users/kiteboard/prism42/agents/livekit/synthetic_caller_full.py:42,66` — separate test fixture, not a runtime path on the prism42-worker service
14. systemd EnvironmentFile vs Environment= precedence — see `man systemd.exec` ("Environment", "EnvironmentFile", "UnsetEnvironment"): `Environment=NAME=` is value-set, `UnsetEnvironment=NAME` is the unset primitive
15. Pod fish_speech_tts.py SHA `98406d6f...` (has Cycle-2L comma-to-period block) vs repo SHA `8519ec4a...` — diff is irrelevant to this bug; both versions have the identical mutex logic at lines 166-193 and body-build at 199-222
16. Pod worker.py SHA `a1ca91ab...` matches repo SHA `a1ca91ab...` exactly (no drift)
