# Cycle-2Q2 Team Q — verification plan

How the integrator confirms each fix landed. Designed for fast
turnaround: each verification is a single shell command + a single
log-grep predicate.

---

## Pre-flight (run BEFORE deploying any fix)

Capture the bug signature so post-deploy verification can prove it's gone.

```bash
ssh b300-pod 'wc -l /tmp/prism42-logs/worker.log'
# Note the line number — call it $BASELINE
```

```bash
# Open https://prism42-app.thegoatnote.com in a browser and run the
# canonical 3-turn cardiac scenario:
#   Turn 1: "Twelve Riverside Drive."
#   Turn 2: "My friend stopped breathing."
#   Turn 3: "Yes they're on the floor."
```

```bash
ssh b300-pod 'tail -n +$BASELINE /tmp/prism42-logs/worker.log | \
    awk "/fishspeech.t0/" | wc -l'
# Expected pre-fix: ~6-7 (3 turns × 2 utterances per turn = 6, plus 1 filler)
# Expected post-fix: 3 (3 turns × 1 utterance each)
```

Save the pre-fix count. Post-fix should drop by ~50%.

---

## Verifying Fix #1 (StopResponse propagation)

### V1.1 — Bytecode is rebuilt after deploy

```bash
ssh b300-pod 'stat -c "%Y %n" /opt/prism42/agents/livekit/orchestrator.py /opt/prism42/agents/livekit/__pycache__/orchestrator.cpython-3*.pyc'
# Both timestamps should be after `systemctl restart` time
```

### V1.2 — `using preemptive generation` count drops to ZERO on template paths

```bash
# Run the canonical 3-turn scenario, then:
ssh b300-pod 'tail -n 500 /tmp/prism42-logs/worker.log | \
    grep -c "using preemptive generation"'
# Expected: 0 (was 4 in the f2c54453 baseline)
```

### V1.3 — Exactly ONE fishspeech.t0 per fsm.transition

```bash
ssh b300-pod 'tail -n 500 /tmp/prism42-logs/worker.log | \
    awk "/fsm.transition/ {fsm++} /fishspeech.t0/ {tts++} END {print \"fsm:\", fsm, \"tts:\", tts}"'
# Expected: fsm=3 tts=3 (1:1 mapping)
# Pre-fix: fsm=3 tts=6+ (1:2 mapping)
```

### V1.4 — `fsm_turn_failed` count is still zero (StopResponse not leaking to broad except)

```bash
ssh b300-pod 'grep -c "fsm_turn_failed" /tmp/prism42-logs/worker.log'
# Expected: 0 (StopResponse should propagate cleanly to LiveKit; if it's
# being caught by the broad `except Exception`, we'd see fsm_turn_failed
# warnings, indicating the fix's else-branch placement is wrong)
```

### V1.5 — User-attestable: ONE dispatcher utterance per caller turn

Open `https://prism42-app.thegoatnote.com`. Run:
- Caller: "Hello."
- Expected dispatcher: ONE utterance — "What is happening at that location?"
  (since the cached greeting already played "Nine one one, what is the address...")
  OR ONE of: greeting + "What is happening...". NOT both "Nine one one..."
  AND "What is happening..." in turn 1.

Pre-fix symptom (per user attestation):
- Caller: "Hello."
- Dispatcher: 4 utterances — "Nine one one...", "What is happening...",
  "Are they on the floor...", "Are they on the floor..." (repeat).

---

## Verifying H2 fix (filler suppression in CRITICAL_VERIFY + KEY_QUESTIONS)

### V2.1 — `filler.spoken` count drops to zero across the canonical 3-turn run

```bash
ssh b300-pod 'tail -n 500 /tmp/prism42-logs/worker.log | \
    grep -c "filler.spoken"'
# Expected: 0
# Pre-fix: 1+ (filler fired during VERIFY_SURFACE pause in the f2c54453 baseline)
```

### V2.2 — `filler.suppressed_intake` count grows to cover all phase events

```bash
ssh b300-pod 'tail -n 500 /tmp/prism42-logs/worker.log | \
    grep filler.suppressed_intake | awk "{print \$NF}" | sort | uniq -c'
# Expected output should include: phase=critical_verify, phase=key_questions
# (in addition to phase=intake and phase=address_confirmed which already worked)
```

### V2.3 — User-attestable: no "I'm with you" / "I hear you" between dispatcher questions

After Fix #1+H2, the canonical 3-turn run should have NO short-utterance
fillers in the audio stream. Each caller turn -> exactly one short
dispatcher question/instruction.

---

## Synthetic-caller probe (deterministic, runs in CI)

This is the integrator's go-to single-command repro:

```bash
ssh b300-pod 'cd /opt/prism42/agents/livekit && \
    .venv/bin/python synthetic_caller.py \
    --transcript "twelve riverside drive my friend stopped breathing yes on the floor flat on their back" \
    --turns 3 \
    --capture-log /tmp/synthetic-q2-probe.log'
```

Then:
```bash
ssh b300-pod 'awk "
    /fsm.transition/ { fsm++ }
    /fishspeech.t0/ { tts++ }
    /using preemptive generation/ { preempt++ }
    /filler.spoken/ { fill++ }
    /response_gate.decision/ { gate++ }
    END { 
        printf \"fsm=%d gate=%d tts=%d preempt=%d filler=%d\n\", 
            fsm, gate, tts, preempt, fill
        ok = (tts == fsm) && (preempt == 0) && (fill == 0) && (gate == fsm)
        print ok ? \"PASS\" : \"FAIL\"
    }" /tmp/synthetic-q2-probe.log'
```

**PASS criteria:**
- `fsm` = 3 (one transition per caller turn)
- `gate` = 3 (one gate decision per caller turn)
- `tts` = 3 (exactly one TTS render per caller turn — H1 fixed)
- `preempt` = 0 (preemptive_generation never picked up — StopResponse worked)
- `filler` = 0 (filler suppressed in CRITICAL_VERIFY — H2 fixed)

**FAIL signatures and what they mean:**
- `tts > fsm` and `preempt > 0` → H1 fix did NOT take effect; double-check
  bytecode timestamp and the patched code structure (LLM-fallthrough must
  be guarded on `if not gate_emitted_template:`).
- `tts > fsm` and `preempt == 0` → H1 fixed but the LLM-fallthrough is
  still running for non-template intents (REPROMPT). Confirm the gate
  used_template=True for all 3 turns; if any turn was used_llm=True
  this is expected and not a regression.
- `filler > 0` → H2 fix did not deploy. Verify worker.py was scp'd and
  worker restarted.

---

## Rollback verification

If we need to revert Fix #1 fast:

```bash
# Disable the response gate; cycle-2Q FSM-rewritten-prompt path takes over.
ssh b300-pod 'sudo rm /etc/systemd/system/prism42-worker.service.d/140-cycle2T-response-gate.conf'
ssh b300-pod 'sudo systemctl daemon-reload && sudo systemctl restart prism42-worker'

# Verify fallback:
ssh b300-pod 'sudo systemctl show prism42-worker -p Environment | grep RESPONSE_GATE || echo "FLAG REMOVED"'
# Expected: FLAG REMOVED

ssh b300-pod 'tail -n 100 /tmp/prism42-logs/worker.log | \
    grep -c "orchestrator.gate_template_ms"'
# Expected: 0 (gate path skipped)
```

If we need to revert H2 fix only:
```bash
# Set the env back to suppress only INTAKE phases (the cycle-2I baseline):
ssh b300-pod 'sudo sed -i "s/PRISM42_FILLER_INTAKE_DISABLE=1/PRISM42_FILLER_INTAKE_DISABLE=0/" /etc/systemd/system/prism42-worker.service.d/130-cycle2I-barge-in.conf'
ssh b300-pod 'sudo systemctl daemon-reload && sudo systemctl restart prism42-worker'
# Filler returns to all phases (the pre-cycle-2I behavior).
```

---

## What "GREEN" looks like (single-line summary for status reports)

After Fix #1 + H2, on the canonical 3-turn cardiac scenario:

```
fsm=3 gate=3 tts=3 preempt=0 filler=0  →  PASS
```

This is the bench-CI-pass-fail bit the integrator copies into a Slack
status. If any number deviates, the diagnosis.md hypothesis ranking
maps directly to which subsystem broke.

---

## Mapping of user-visible symptoms to log signatures

| User symptom | Log evidence | Fix |
|---|---|---|
| "Same template fires 3-5 times" | `fishspeech.t0` count > `fsm.transition` count, multiple `using preemptive generation` lines | Fix #1 |
| "Different template fires after the gate said one" | Two `fishspeech.t0` events in the same second with DIFFERENT `text_len` | Fix #1 |
| "Filler 'I'm with you' fires in the middle of cardiac questioning" | `filler.spoken` line during a session that has `state=critical_verify` events | H2 fix |
| "Address question fires twice when caller said it once" | Two `fishspeech.t0` after one `received user transcript` | Fix #1 |
| "STT mis-hears 100 ocean avenue, dispatcher still progresses" | `fsm.transition address_known=True` despite mis-heard utterance | NOT in Q's scope (Team P / FSM regex) |
