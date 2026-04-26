# cycle-2Q + cycle-2P live evidence — pre-staged for research teams

User attestation 2026-04-26 ~10:00 PT on `https://prism42-app.thegoatnote.com`
(post-cycle-2D; redirects to /prism42/livekit). Caller said "100 Ocean Avenue"
(among other tests). Multiple bugs:

1. Phantom auto-progression (dispatcher fires 3-5 turns per caller utterance)
2. Repeated identical templates ("Are they on the floor..." 5x)
3. STT misheard "100 Ocean Avenue" as "One hundred ocean of new" on turn 1
4. STT recovered "One hundred Ocean Avenue" on turn 2 — but UI screenshot
   showed `LOCATION: GATHERING` and `No latches yet — caller still in intake`
   even though log says `address_known=True` after turn 2

## Captured session

`session-b4880122-100ocean.log` — 201 lines, the actual session
`b4880122-417a-ffb2-2db5-ce16492ac84e` from worker.log filtered to that session.

## Smoking-gun line for Team Q (auto-progression / repetition)

Turn 2 log entries show:

```
17:09:04 source=generate_reply ms=14475   ← LLM started + got first token
17:09:04 source=say         ms=14509      ← template ALSO emitted
```

Two reply sources fired at the same timestamp. cycle-2L's StopResponse fix
was supposed to cancel `generate_reply` — but here the LLM got to its first
token, AND the template was still emitted. That's the double-TTS bug
that cycle-2L was supposed to fix. Either the StopResponse fired too late
OR something else is producing parallel emits.

## Smoking-gun line for Team P (STT + UI sync)

Turn 1: `received user transcript: "One hundred ocean of new."`
Turn 2: `received user transcript: "One hundred Ocean Avenue."`

Parakeet recovered on turn 2 — model heard correctly when the user repeated.
But screenshot taken later showed "GATHERING" and "no latches" — UI didn't
reflect the FSM's `address_known=True`. This is a publish_turn payload bug
or a frontend reducer bug.

## Notes

- `filler.suppressed_intake` event confirmed firing (cycle-2I P1 working
  correctly)
- `dispatch_publisher.attached` + `published seq=1` confirmed firing
  (cycle-2T2 working at the producer level)
- Worker is at AW_qqBMZAHBwT6t (Team L deploy) running on selfhost
- cycle-2I + cycle-2L + cycle-2T2 + cycle-2U all live; cycle-2J flags
  active

## Test scenarios that exposed the bugs

| Scenario | STT heard | FSM intent | What dispatcher said | Bug |
|---|---|---|---|---|
| "100 ocean avenue" | "One hundred ocean of new" | request_location_and_emergency | "Nine one one, what is the address..." (re-asked) | STT mishear + intent mismatch |
| same, retry | "One hundred Ocean Avenue" | request_emergency (address_known=True) | "What is happening at that location?" | recovered |
| (unscripted continuation) | (silence?) | jumps to verify_cpr_surface | "Are they on the floor, flat on their back?" | phantom progression — no caller turn between |
| "Hello" cold | "Hello" | INTAKE | 4 dispatcher turns fire | phantom auto-progression |
| cardiac scenario | (correct cardiac latch) | CRITICAL_VERIFY/verify_cpr_surface | "Are they on the floor, flat on their back?" 5x | repetition — same template fires 5 times |
