# Cycle-2Q2 Team Q — Phantom-turn diagnosis

**Date:** 2026-04-26
**Session attested:** `f2c54453-2a81-4377-390e-5145196d859b` (17:15:54 UTC)
**Mode:** Read-only on `agents/livekit/*`. Integrator applies fixes.
**Ship-blocking:** Beta testers hit `https://prism42-app.thegoatnote.com` in hours.

---

## TL;DR (Munger inversion form: what is the dragon?)

**The dragon is fixing five things at once and shipping the wrong combination.**
There is ONE root cause and four amplifiers. Apply the root-cause fix in
isolation, verify, then triage amplifiers.

**Root cause (H1, certainty 100% from live evidence):** The cycle-2L
"raise StopResponse outside the broad except" patch in
`agents/livekit/orchestrator.py:482-483` is **dead code**. Python
`return` from inside a `try:` block exits the function before reaching
the post-try statement. So `StopResponse()` is never raised. So
LiveKit's `agent_activity.py:1973` `except StopResponse: return` path
is never taken. So the preemptive_generation LLM call that fired in
parallel with `on_user_turn_completed` runs to completion AND its TTS
output plays — on top of the gate's `session.say()` template. Every
caller turn produces TWO dispatcher utterances: the gate template,
followed ~0-2s later by an LLM-generated reply (which, because the LLM
sees the full FAST_DISPATCHER_SYSTEM_PROMPT and not the FSM-rewritten
prompt, often re-asks the same question or asks the next protocol
question). Combined with the filler bridge firing in non-INTAKE phases,
the caller hears 2-3 dispatcher utterances per single caller utterance.

**This is the same bug that cycle-2L diagnosed as fixed, but the fix
itself contains a Python control-flow error.**

---

## Evidence — single live session, 4 caller turns

Time window 17:16:10 – 17:16:48 UTC, session `f2c54453-2a81-4377-390e-5145196d859b`.

### Event counts (canonical `/tmp/prism42-logs/worker.log` on B300)

| Event | Count | Expected (1 reply / turn) |
|---|---|---|
| `received user transcript` | 4 | 4 |
| `fsm.transition` | 4 | 4 |
| `response_gate.decision used_template=True` | 4 | 4 |
| `orchestrator.gate_template_ms` | 4 | 4 |
| `using preemptive generation` (LiveKit DEBUG) | 4 | 0 (should be cancelled) |
| `fishspeech.t0` (TTS render started) | **9** | 4 |
| `fishspeech.done` | 8 | 4 |
| `filler.spoken` | 1 | 0 |
| `filler.suppressed_intake` | 5 | (informational) |

9 fishspeech.t0 ÷ 4 caller turns = **2.25 TTS playbacks per caller turn**, +1
filler.

### Per-turn signature (verbatim, turn 3 at 17:16:37)

```
17:16:37.330 DEBUG    livekit.agents     received user transcript
17:16:37 [info     ] fsm.transition       intent=verify_cpr_surface turns=3
17:16:37 [info     ] response_gate.decision intent=verify_cpr_surface
                     final_text='Are they on the floor, flat on their back?' (42 chars)
                     used_template=True used_llm=False
17:16:37 [info     ] overlap.llm_first_token_after_speech_ms ms=27050 source=say
17:16:37 [info     ] orchestrator.gate_template_ms intent=verify_cpr_surface
17:16:37.367 DEBUG    livekit.agents     using preemptive generation   <-- LLM ran in parallel
17:16:37 [info     ] fishspeech.t0 chunk_length=200 text_len=42        <-- gate template
17:16:37 [info     ] fishspeech.t0 chunk_length=200 text_len=45        <-- LLM-generated DIFFERENT reply
17:16:39 [info     ] fishspeech.done total_ms=2153                     <-- template TTS played
17:16:41 [info     ] fishspeech.done total_ms=4026                     <-- LLM TTS played
```

Two TTS playbacks of DIFFERENT TEXTS (42 chars vs 45 chars) for one
caller utterance. Same pattern at turn 1 (text_len 52 then 52), turn 2
(35 then 28), turn 4 (42 then 44). **Different `text_len` per turn
proves these are two distinct LLM/template outputs, not a single output
played twice.**

### `fsm_turn_failed` count (StopResponse leaking into broad except)

```
$ grep -c "fsm_turn_failed" /tmp/prism42-logs/worker.log
0
```

Zero. So `StopResponse` is **not** being caught by the `except Exception`
at line 458 (which would log `fsm_turn_failed`). The cycle-2L diagnosis
expected this counter to be the canary — the fact that it's zero PROVES
that StopResponse is also not being raised inside the try (which would
otherwise leak to the except).

### Code on the pod matches local (sha256 verified)

```
fd9946bd...  /opt/prism42/agents/livekit/orchestrator.py
96aa193a...  /opt/prism42/agents/livekit/worker.py
```

Bytecode is fresh (11:55:35 UTC, worker started 11:55:46 UTC, attested
session 17:16 UTC).

---

## H1 — `return` inside `try:` skips the post-try `raise StopResponse()` (CERTAINTY 100% × SEVERITY P0)

**File:** `agents/livekit/orchestrator.py:336-483`
**Mechanism:** Python control flow.

The current code:
```python
async def on_user_turn_completed(...):
    gate_emitted_template = False
    try:
        ...
        if self._response_gate is not None:
            ...
            if decision.used_template and decision.final_text:
                ...
                self.session.say(decision.final_text, allow_interruptions=True)
                ...
                gate_emitted_template = True
                return  # <-- THIS EXITS THE FUNCTION
        ...  # LLM-fallthrough path
    except Exception as e:
        ...

    # Cycle-2L: raise StopResponse OUTSIDE the broad except
    if gate_emitted_template and StopResponse is not None:
        raise StopResponse()  # <-- NEVER REACHED on template path
```

**Reproducer (verified locally with Python 3.14 / 3.12):**
```python
def f():
    flag = False
    try:
        flag = True
        return       # exits function, post-try block is unreachable
    except Exception:
        pass
    if flag:
        raise ValueError('would raise')

try:
    f()
    print('f returned normally')   # this prints
except ValueError:
    print('ValueError caught')      # this does NOT print
```

So:
1. Gate elects template → `gate_emitted_template = True`
2. `return` at line 440 exits the function
3. The post-try `raise StopResponse()` at line 482-483 is **dead code**
4. Control returns to `agent_activity.py:1970` which sees `on_user_turn_completed`
   completed normally (no exception)
5. Code at line 2021 checks `self._preemptive_generation` — set, valid → schedules
   the speech_handle for the LLM-generated reply
6. Caller hears: gate template + LLM reply + (optional filler)

**Severity:** P0 ship-blocking. Every template-path turn produces 2 utterances.

**Probability:** 100%. Verified by reading the code, Python semantics,
and 4 distinct caller utterances all producing 2 fishspeech.t0 calls.

---

## H2 — Filler bridge fires between the duplicate utterances (CERTAINTY 95% × SEVERITY P1)

**File:** `agents/livekit/worker.py:1325-1411`
**Mechanism:** `_schedule_filler` runs on every `user_state_changed`
speaking→listening event in non-INTAKE phases. After H1's first TTS
(gate template) finishes around 2s, the caller pauses; VAD fires
listening; `_schedule_filler` queues a `_fire_filler` task; 0.3s later
`session.say("I'm with you.")` plays. Meanwhile the LLM's preemptive
TTS is also queued.

The session log at 17:16:48 shows the filler racing the second TTS:
```
17:16:48 fishspeech.t0 text_len=42         <-- gate template
17:16:48 fishspeech.t0 text_len=44         <-- LLM duplicate
17:16:48 overlap.filler_after_speech_ms ms=38101 text="I'm with you."
17:16:50 fishspeech.done total_ms=2118     <-- gate template plays
17:16:52 fishspeech.done total_ms=4149     <-- LLM duplicate plays
17:16:55 fishspeech.t0 text_len=13         <-- filler "I'm with you." (13 chars)
17:16:56 fishspeech.done total_ms=954      <-- filler plays
17:16:56 [info     ] filler.spoken text="I'm with you."
```

So caller's turn 4 produces **3 distinct dispatcher utterances**: gate
template, LLM duplicate, filler. The user's symptom "5 times in a row"
maps to: turn 3 template + turn 3 LLM + turn 4 template + turn 4 LLM +
filler = 5 utterances of "Are they on the floor, flat on their back?"
(or close paraphrases) within ~25 seconds.

**Severity:** P1. Fixing H1 reduces this to "filler + (rare) duplicate";
H2 is a secondary amplifier.

**Probability:** 95% (the filler suppression in INTAKE works — see 5
`filler.suppressed_intake` logs — but does NOT cover CRITICAL_VERIFY,
KEY_QUESTIONS, etc. That's the gap.)

---

## H3 — `session.say()` is a SYNC call inside an async function (CERTAINTY 80% × SEVERITY P2)

**File:** `agents/livekit/orchestrator.py:386-389`

```python
self.session.say(
    decision.final_text,
    allow_interruptions=True,
)
```

`AgentSession.say` (livekit-agents 1.5.6) returns a `SpeechHandle`
immediately and schedules the speech asynchronously. We do NOT `await`
the handle. So the gate template TTS is QUEUED but not yet played when
`on_user_turn_completed` returns. By the time control returns to
`agent_activity.py:1970`, the preemptive LLM has already finished (LLM
TTFT is ~60ms per `LLMMetrics llm_ms=60` in the log). The pre-existing
preemptive speech_handle is then validated against the unchanged chat
context (line 2024-2029) — it matches because we never modified the
chat ctx in the gate path — and `_schedule_speech` is called at line
2035, putting the LLM reply directly behind the queued gate template.

**Severity:** P2. Even with H1 fixed (StopResponse properly raised),
the mechanism that makes the duplicate possible in the first place is
the asynchronous schedule of `session.say()`. With H1 fixed, the
StopResponse cancels the preemptive — so this is informational only.

**Probability:** 80% — confirmed via livekit-agents source reading. Can
be verified by examining the SpeechHandle id of the gate template vs
the preemptive in `speech_id` log fields if/when that telemetry is
extended.

---

## H4 — FSM emits VERIFY_SURFACE on consecutive turns until caller answers (CORRECT BEHAVIOR — not a bug)

**File:** `agents/livekit/dispatcher_fsm.py:461-479` (`_intent_in_verify`)

Caller's turn 3 says "shooting / friend shot / not breathing" → FSM
sets `is_cardiac_arrest=True`, `state=CRITICAL_VERIFY`,
`surface_confirmed=False`, `breathing_assessed=False`. FSM emits
`VERIFY_SURFACE`. Gate template "Are they on the floor, flat on their
back?" plays.

Caller's turn 4 says something that does NOT match `_RE_FLOOR_FLAT`
("on the floor", "flat on their back", "lying down", etc.). FSM still
has `surface_confirmed=False`. FSM correctly re-emits `VERIFY_SURFACE`.

This is the FSM doing its job (MPDS-9 protocol: never instruct CPR
without verifying surface and breathing). The user's perception of
"same template 3-5 times" is partly H1+H2 (duplicates and fillers),
partly correct FSM behavior on caller utterances that don't disambiguate
the verification step.

**Severity:** None — correct.

**Probability:** This is design-intended behavior. Mark as
"out-of-scope for cycle-2Q2 fix; possible Team P enhancement: add
softer reprompt after 2 consecutive same-intent VERIFY events."

---

## H5 — `min_endpointing_delay=1.0`+`silero min_silence=0.9` is allowing 13s gaps between caller turns (NOT THE PHANTOM BUG, but worth noting)

The session log shows caller turns at 17:16:10, 17:16:23, 17:16:37,
17:16:48 — 11-14 second gaps. The cycle-2I increases (0.55→0.9 silero,
0.6→1.0 endpointing) make the agent SLOW to recognize end-of-turn.
This is desirable for address dictation but it does NOT explain the
double-utterance symptom.

**Severity:** None for this diagnosis.

**Probability:** N/A.

---

## Hypothesis ranking (severity × probability)

| # | Hypothesis | Severity | Probability | Score | Verdict |
|---|---|---|---|---|---|
| H1 | `return` inside `try:` skips StopResponse | P0 | 100% | **100** | ROOT CAUSE — fix this first |
| H2 | Filler in non-INTAKE phases adds 3rd utterance | P1 | 95% | 65 | Amplifier — fix after H1 |
| H3 | session.say is async-fire-and-forget | P2 | 80% | 30 | Informational only after H1 fix |
| H4 | FSM correctly re-emits VERIFY_SURFACE | None | (design) | 0 | Out-of-scope |
| H5 | Endpointing delay too long | None | (intended) | 0 | Out-of-scope |

**Hypotheses falsified by evidence (do NOT fix):**

- "on_user_turn_completed firing on every interim STT" — falsified.
  Exactly 4 `received user transcript` events for 4 caller turns; STT
  finalizes once per turn.
- "VAD micro-pauses being treated as turn boundaries" — falsified. 4
  caller turns produced 4 fsm.transition events with monotonically
  increasing `turns=N`. No spurious transitions.
- "FSM auto-advances even on non-matching utterances" — partially true
  but only via H4 which is correct behavior.
- "Greeting cache + first session.say() interaction" — falsified.
  Greeting fires once at session start; no second greeting in turn
  events.
- "preemptive_generation race with cycle-2L StopResponse" — diagnosis
  is correct but the fix is broken (H1).

---

## Why the cycle-2L diagnosis was right but the fix was broken

Cycle-2L (Team L) correctly identified that:
1. LiveKit's preemptive_generation runs the LLM in parallel with
   `on_user_turn_completed`
2. `return` from `on_user_turn_completed` is NOT enough — only StopResponse
   cancels the in-flight generation
3. The fix needed to raise StopResponse OUTSIDE the broad `except Exception`
   so it would propagate to LiveKit's catch at agent_activity.py:1973

What cycle-2L missed: **`return` inside the `try:` block does NOT continue
to the post-try code.** It exits the function. So the StopResponse-after-
the-try pattern only works if the gate-template branch sets the flag
and FALLS THROUGH the rest of the try (without return), so that the
try completes normally and the post-try if-statement executes.

This is a classic Python control-flow trap. The cycle-2L verification
plan (3-turn synthetic_caller test with `tail -F | grep fishspeech.done`)
would have caught this immediately — but the verification was apparently
not run end-to-end after the patch landed, or only shallow-tested before
the cycle-2T2 dispatch-publisher work was layered on top.

---

## What we did NOT change (read-only constraint honored)

- `agents/livekit/orchestrator.py` — read only
- `agents/livekit/dispatcher_fsm.py` — read only
- `agents/livekit/response_gate.py` — read only
- `agents/livekit/worker.py` — read only
- `agents/livekit/dispatch_publisher.py` — read only

---

## Sources

All web sources fetched 2026-04-26.

- [LiveKit Build/Turns guide](https://docs.livekit.io/agents/build/turns/) — does not document StopResponse semantics specifically
- [LiveKit GitHub Issue #5026 — commit_user_turn skip_reply](https://github.com/livekit/agents/issues/5026) — documents that `skip_reply` is the only documented way to commit a user turn without firing a reply
- [LiveKit GitHub Issue #3787 — StopResponse logged as error](https://github.com/livekit/agents/issues/3787) — confirms StopResponse is the canonical "ignore this turn" signal
- LiveKit Agents 1.5.6 source on the pod:
  - `livekit/agents/voice/agent_activity.py:1798-1846` — `on_preemptive_generation` schedules an LLM call via `_generate_reply(schedule_speech=False)` which RUNS in background but does not push to TTS until `_schedule_speech` is called
  - `livekit/agents/voice/agent_activity.py:1969-1977` — `await self._agent.on_user_turn_completed(...)` then `except StopResponse: return` is the cancel path
  - `livekit/agents/voice/agent_activity.py:2020-2046` — preemptive generation is consumed: if chat_ctx is unchanged, `_schedule_speech` is called and "using preemptive generation" is logged. **This is what we see in our logs after every gate template path.**
- Local files (path-anchored):
  - `/Users/kiteboard/prism42/agents/livekit/orchestrator.py:336-483` (the broken cycle-2L block)
  - `/Users/kiteboard/prism42/findings/voice/cycle2L_logic_regression/team-l/diagnosis.md` (cycle-2L's correct diagnosis but broken fix)
  - `/Users/kiteboard/prism42/findings/voice/cycle2T2_transcript_debug/team-t2/diagnosis.md` — explicit note: "the actual `raise StopResponse()` re-raise outside the broad `except` is NOT yet present (the comment 'StopResponse raised below' points at code that doesn't exist)" — this was Team T2's belief at the time of T2's write; subsequent commit DID add the raise but with the broken control flow
- Live worker log sample (canonical, non-redacted):
  `/tmp/prism42-logs/worker.log` 17:15:54-17:18:00 UTC, session
  `f2c54453-2a81-4377-390e-5145196d859b`
