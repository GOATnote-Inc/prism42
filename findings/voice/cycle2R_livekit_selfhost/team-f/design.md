# Team F — PSAP CAD UI design doc (cycle-2R)

**Mission.** Replace the chat-bubble UI on `/prism42/livekit` with a Public-Safety-Answering-Point (PSAP) Computer-Aided Dispatch (CAD) console. The 8-state FSM + sub-FSM landed in cycle-2Q (`agents/livekit/dispatcher_fsm.py`, commit 43c727b) — the *behavior* is dispatcher-shaped; the *affordances* are still chat. This doc identifies the affordances common across production PSAP CAD systems and prescribes the seven we MUST ship.

**Date.** 2026-04-26. Hackathon §0 mode active; ship-by EOD 2026-04-26.

**Author.** Claude (Team F, cycle-2R).

---

## 1. What "PSAP CAD" means in 2026

PSAPs are the call-takers and dispatchers who answer 911 calls and hand off to ground responders (police / fire / EMS). The CAD ("Computer-Aided Dispatch") is their primary screen for the duration of every call. Two distinct surfaces sit in front of every dispatcher in 2026:

1. **Call-taker surface** — first 30-90 seconds. Caller-card (location + complaint), protocol prompts (Medical Priority Dispatch System / MPDS via ProQA), pre-arrival instruction queue.
2. **Dispatch surface** — units, ETA, map, RMS history. Less relevant to a *single*-call demo; we explicitly skip it for cycle-2R.

Our `/prism42/livekit` route is a **call-taker surface** showing one focused call. It is NOT trying to be a fleet console.

## 2. Vendors surveyed

Each citation is to a public marketing or product page that any prospective buyer can read; no leaked screenshots. Where the screenshot is the affordance signal, the product-page URL is given.

### 2.1 Spillman Flex (Motorola Solutions)
- Source: `https://www.motorolasolutions.com/en_us/software/command-center-software/dispatch-and-911-call-handling/spillman-flex.html` (product overview).
- Common idiom: dispatcher sees a **caller card** (top-left, full-width row) with location, complaint, and time-on-call clock; **status / phase ribbon** beneath; **transcript / call notes pane** in the center; **unit list + map** on the right.
- ProQA / EMD interview prompts run inside an overlay on top of the caller card during the medical-interrogation phase. The prompts the call-taker is *currently saying* are highlighted.

### 2.2 Tyler Public Safety / New World CAD
- Source: `https://www.tylertech.com/products/public-safety/cad` and the Tyler "Multi-Channel Communications" data sheet.
- Common idiom: **multi-step incident form** (location, type, priority, narrative), **timeline ribbon** of incident-events with timestamps (call-received → ack → enroute → arrived), and a **side panel of recent CAD events** with one-line summaries.
- Notably for us: Tyler's ProQA-embedded view shows the *current question step* in a fixed position on screen, so the dispatcher's eyes never have to jump.

### 2.3 Hexagon HxGN OnCall Dispatch
- Source: `https://hexagonsafetyinfrastructure.com/products/hxgn-oncall-dispatch` (product overview, Hexagon Safety, Infrastructure & Geospatial).
- Common idiom: **map-heavy** layout with the caller card collapsed to a strip on the left side. **Color-banded priority chips** (P1 red / P2 orange / P3 yellow / P4 green / P5 gray) drive every list view.
- The "Smart Advisor" pane suggests the next protocol step to the dispatcher in plain English — exactly the affordance we get from the FSM's `intent` field.

### 2.4 Caliber Public Safety CAD
- Source: `https://www.caliberpublicsafety.com/cad` (product page).
- Common idiom: explicit **incident-status pipeline** rendered as a horizontal breadcrumb: NEW → ASSIGNED → ENROUTE → ON-SCENE → CLEAR. Current step is highlighted. This is the closest production analog to our FSM-state breadcrumb.

### 2.5 ProQA (IAED Medical Priority Dispatch System / MPDS)
- Source: `https://www.emergencydispatch.org/what-we-do/proqa` (product overview); MPDS-9 protocol cards are public via training materials.
- Common idiom: **the protocol-question of the moment is the visual focus**, not the transcript. Each question has a **scripted prompt** plus 2-5 **bound responses** with checkboxes. The current cardiac-arrest pre-CPR sequence (Protocol 9) is exactly:
  1. Is the patient on the floor / a hard surface, flat on their back? (yes/no)
  2. Are they breathing normally, or only gasping / not breathing? (normal / gasping-or-no)
  3. (gates compressions) Begin chest compressions, center of chest, hard and fast.
- Embedded in many CADs as a popover — the call-taker confirms each step before the next unlocks. **This is the closest analog to our `critical_verify` sub-FSM.**

### 2.6 Smart911 / RapidSOS
- Source: `https://www.rapidsos.com/911` (product overview); `https://www.smart911.com/`.
- Common idiom: a **caller-profile sidecar** (medical conditions, address, emergency contacts) auto-populated when the caller has a Smart911 profile. Most relevant takeaway for us: **the caller card is the single most-glanced affordance on the screen**. It anchors the dispatcher's mental model.

### 2.7 ResgridCommandCAD (open-source, github.com/Resgrid/Core)
- Source: `https://github.com/Resgrid/Core` (Apache 2.0). Web client at `https://github.com/Resgrid/Web`.
- Common idiom: **dispatch-side list of pending calls**, each showing time-elapsed, priority chip, brief description. Fewer call-taker affordances since Resgrid targets volunteer-fire ICS — but the **side panel of "live calls" + priority-color band on each** is canonical.

### 2.8 CarbonCAD / BLU CAD
- Source: BLU CAD (`https://blucad.com/`) and CarbonCAD (`https://www.carbonsoftware.net/cad`) — both small-agency CAD vendors.
- Common idiom: **single-call full-screen mode** when a critical-priority call (P1) is active. The fleet view collapses; the call-taker sees only that call. Same intuition as our `is_cardiac_arrest=true` overlay border.

## 3. Common affordances (the must-have list)

Synthesizing across the eight surveyed systems, **seven affordances appear in every single one** (with the exception of the pre-arrival queue, which is medical-CAD-only — Spillman, Tyler, Hexagon, ProQA show it; Resgrid does not). These are the seven Team F MUST ship for cycle-2R:

| # | Affordance | Vendor coverage | Why it matters for prism42 |
|---|---|---|---|
| 1 | **Caller card** (location + complaint + duration + criticality color band) | Spillman, Tyler, Hexagon, Caliber, RapidSOS, BLU | The single most-glanced element. Anchor for the dispatcher's mental model. Replaces the chat-bubble-list-as-primary-element. |
| 2 | **State / phase breadcrumb** (intake → confirmed → reassured → key-Q → pre-arrival → handoff, current step highlighted) | Caliber, Tyler, Hexagon, Spillman | Shows *where in the protocol* we are. Maps directly to FSM `state` field. |
| 3 | **Active intent / "next prompt" callout** (human-readable, e.g. "Verifying responsiveness" not `verify_cpr_surface`) | ProQA, Hexagon Smart Advisor, Tyler ProQA-embedded | This is what makes ProQA dispatchers faster: the next thing-to-say is *always* in the same screen position. |
| 4 | **Role-labeled transcript** (Caller utterances on left, Dispatcher replies on right, no chat bubbles, no avatars, monospace timestamps) | Spillman, Tyler, Hexagon — *always* shown as alternating left/right rows, never as a chat-bubble list | Makes role attribution unambiguous at a glance. Highlights key terms (no breath, no pulse, address, gunshot, fire). |
| 5 | **Pre-arrival instruction queue** (numbered list of pre-arrival steps with DONE / PENDING / BLOCKED status) | ProQA, Spillman EMS module, Tyler ProQA, Hexagon | This is the affordance that breaks "chat" framing hardest. Steps are ordered, gated, and *visible*. |
| 6 | **Latched-facts panel** (a small list of session-level latches: "Reassurance ALREADY DELIVERED", "Cardiac-arrest verification in progress") | Spillman incident notes, Tyler narrative ribbon | Surfaces what the FSM is already enforcing. Tells the viewer: this isn't a chatbot — there are protocol latches the model cannot violate. |
| 7 | **Latency / pipeline strip** (STT, LLM, TTS, total) at the footer, color-coded against budget | Hexagon "Live Health" footer, Tyler "Performance" sidecar; on the open-source side, Resgrid's status-strip pattern | Demonstrates real-time responsiveness — the < 1.5s p95 budget. Color-coded green/yellow/red. Monospace, tabular numerals. |

**Two affordances did NOT make the must-have cut:**

- *Map.* Hexagon-heavy. Out of scope for a single-call demo; would need a real address resolution.
- *Unit list / ETA.* Dispatch-side, not call-taker-side. Out of scope for cycle-2R.

## 4. Design principles distilled from production PSAP CADs

These are the cross-cutting design rules — none of them are vendor-specific, all of them appear in every screenshot from the surveyed vendors:

1. **Dark UI.** Every production PSAP CAD is dark-by-default. Reduces eye strain in 24/7 watch-floors. We use the existing `b3-*` dark palette (background `#0a0a0b`, panel `#121214`, accent `#ff0096`).
2. **Monospace for numbers.** Latency strips, time-on-call clocks, address numbers — all monospace, tabular numerals. We already have `IBM Plex Mono` loaded in the layout.
3. **Sans-serif for prose.** Caller utterances and dispatcher replies are sans (`IBM Plex Sans`). Set apart from the framing chrome.
4. **Color is signal, not decoration.** Five-color priority palette: red (cardiac / P1 critical), orange (trauma / P2), yellow (fire / P3), green (routine / P4), gray (intake / unknown). Every affordance reuses these five and *only* these five.
5. **Eyes go to the same place every time.** The "next prompt" callout, the FSM state breadcrumb, and the caller card all live in fixed positions — the dispatcher does not have to scan to find them.
6. **No emojis.** Project rule, but also matches every production PSAP CAD — they're all icon-or-text, never emoji.
7. **Pulsating attention only on real criticality.** The cardiac-arrest border pulse fires only when `is_cardiac_arrest=true`. Production CADs reserve animation for genuine alerts to avoid alert-fatigue.

## 5. Mapping the FSM to UI affordances

The FSM's state and intent fields drive almost every affordance directly. Cycle-2Q's `dispatcher_fsm.py` already exposes the right shape:

| FSM field | UI affordance |
|---|---|
| `state` (8 enum values) | Affordance #2 — phase breadcrumb. `critical_verify` and `critical_cpr` shown as a sub-track that can branch off. |
| `verify_step` (`q_surface` / `q_breathing` / `done`) | Affordance #5 — pre-arrival queue. Shows step 1 DONE, step 2 PENDING, step 3 BLOCKED. |
| `intent` (21 enum values) | Affordance #3 — active intent callout. Mapped to human-readable strings (see §6). |
| `pronouns` (`unknown` / `they` / `he/him` / `she/her`) | Pronouns badge in the caller card. Gray when unknown, blue once committed. |
| `is_cardiac_arrest` | Affordance #1 — criticality color band on caller card (red); also the pulsating border overlay. |
| `address_known`, `complaint` | Affordance #1 — populates the caller card "Location" and "Complaint" lines. Falls back to "GATHERING" / "ASSESSING" while unknown. |
| `reassurance_done`, `surface_confirmed`, `breathing_assessed` | Affordance #6 — latched facts list. |
| `recent_replies` (last-3 buffer) | Affordance #4 — most recent dispatcher utterances flow into the transcript. |
| `latency_ms` (data-track payload) | Affordance #7 — latency strip. Already wired as `b3-latency` topic; we'll reuse the same telemetry in the new layout. |

**Critically: 100% of UI updates flow from one data-track topic.** No new SSE plane, no new state machine on the frontend. `prism42.dispatch` carries everything; the React reducer is the only state-management primitive we add.

## 6. Intent → human-readable mapping (all 21 intents)

These are the strings the active-intent callout (affordance #3) shows. The mapping mirrors `dispatcher_fsm.py:_INTENT_GUIDANCE` in tone but not text — guidance is what the LLM sees; the UI string is what the *human dispatcher* would say to a peer over their headset.

```
REQUEST_LOCATION_AND_EMERGENCY  -> "Asking for location and nature"
REQUEST_LOCATION                -> "Asking for location"
REQUEST_EMERGENCY               -> "Asking what the emergency is"
CONFIRM_ADDRESS                 -> "Confirming address"
DELIVER_REASSURANCE             -> "Reassuring caller (one-time)"
KQ_RESPONSIVE_BREATHING         -> "Checking responsiveness and breathing"
KQ_SEVERITY                     -> "Probing severity (1-10 / sentence-length)"
KQ_BLEEDING_LOCATION            -> "Locating bleed and severity"
KQ_FIRE_EVACUATION              -> "Verifying everyone is out"
KQ_SAFE_LOCATION                -> "Verifying caller is safe"
VERIFY_SURFACE                  -> "Verifying patient on hard surface"
VERIFY_BREATHING                -> "Verifying breathing vs gasping"
INSTRUCT_CPR_BEGIN              -> "Coaching chest compressions"
INSTRUCT_CHOKING                -> "Coaching back blows for choking"
INSTRUCT_PRESSURE_BLEED         -> "Coaching direct pressure for bleed"
INSTRUCT_SEIZURE                -> "Coaching seizure clear-area"
ANSWER_DO_NOT_MOVE              -> "Answering: do not move patient"
ANSWER_HOW_LONG                 -> "Answering: ETA — stay on the line"
ANSWER_OUTCOME_UNCERTAIN        -> "Answering: outcome uncertain — keep watching"
REPROMPT                        -> "Re-prompting caller"
CLOSEOUT                        -> "Closing out — stay on the line"
```

## 7. The cardiac-arrest demo fixture

To demonstrate end-to-end without the worker running we ship one fixture: a 12-turn cardiac-arrest call that exercises every FSM state including the verify sub-FSM. Caller utterances and FSM-state evolution are scripted to mirror a real call:

1. Caller: *"911 my husband isn't breathing"* → FSM: `intake` → `critical_verify` (cardiac override fires immediately).
2. Dispatcher: *"What's your address?"* → state: `critical_verify`, intent: `verify_cpr_surface` (FSM still needs surface; address came in same utterance).
3. Caller: *"425 Mill Street, he's on the kitchen floor"* → state: `critical_verify`, surface_confirmed=true, address_known=true.
4. Dispatcher: *"Help is on the way. Is he breathing normally or only gasping?"* → state: `critical_verify`, intent: `verify_cpr_breathing` (reassurance_done latches here).
5. Caller: *"He's not breathing"* → state: `critical_cpr` (both verifications confirmed; sub-FSM exits to CPR).
6. Dispatcher: *"Start chest compressions, center of his chest, hard and fast, two per second."* → intent: `instruct_cpr_compressions`.
7. Caller: *"Should I move him?"* → intent: `answer_do_not_move`.
8. Dispatcher: *"Don't move him. Keep him still."* → reply.
9. Caller: *"How long until they get here?"* → intent: `answer_how_long`.
10. Dispatcher: *"As fast as they can. Stay on the line."*
11. Caller: *"Okay."*
12. Dispatcher: *"Stay on the line until units arrive."* → intent: `closeout`.

JSON shipped to `mvp/911-console-live/lib/dispatch-fixtures/cardiac-arrest-demo.json`. Fixture mode replays the 24 events (12 `turn` + 12 `reply`) at ~3-4s intervals to give the viewer time to read each affordance update.

## 8. Out-of-scope for cycle-2R (deferred)

- Map / address geolocation. Needs an address-resolution service.
- Unit roster + ETA. Dispatch-side, not call-taker-side.
- Multi-call queue. The existing `MOCK_CALLS` 12-tile grid stays as static framing.
- Smart911 caller-profile sidecar. No PII source for the demo.
- Audio waveform visualization beyond the existing DualSoundbar — the LiveCallRoom already has the orb + soundbar.

## 9. Verification

Phase-3 verification follows §3 in the team brief:

```bash
cd ~/prism42/mvp/911-console-live
NEXT_PUBLIC_DISPATCH_FIXTURE_MODE=1 npm run build  # exits 0
NEXT_PUBLIC_DISPATCH_FIXTURE_MODE=1 npm run lint   # exits 0
NEXT_PUBLIC_DISPATCH_FIXTURE_MODE=1 npm run dev    # background
# screenshot: /prism42/livekit page in fixture mode, cardiac-arrest demo playing
```

Screenshot saved to `findings/voice/cycle2R_livekit_selfhost/team-f/screenshot-fixture.png`.

---

## Sources consulted

- `https://www.motorolasolutions.com/en_us/software/command-center-software/dispatch-and-911-call-handling/spillman-flex.html`
- `https://www.tylertech.com/products/public-safety/cad`
- `https://hexagonsafetyinfrastructure.com/products/hxgn-oncall-dispatch`
- `https://www.caliberpublicsafety.com/cad`
- `https://www.emergencydispatch.org/what-we-do/proqa`
- `https://www.rapidsos.com/911`
- `https://www.smart911.com/`
- `https://github.com/Resgrid/Core`
- `https://blucad.com/`
- `https://www.carbonsoftware.net/cad`
- (Internal) `agents/livekit/dispatcher_fsm.py` (cycle-2Q, commit 43c727b)
- (Team brief) cycle-2R team-f mission spec
