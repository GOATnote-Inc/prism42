# Team Phase-4 — Nemotron perception sub-panel design

**Mission.** Extend the Team-F PSAP-CAD console (`mvp/911-console-live/components/DispatchPanel.tsx`) with a sub-panel that renders the live structured-classifier output alongside the FSM-driven dispatcher state. Beta testers SEE what Nemotron perceived each turn, see confidence-graded values, and see whether the classifier and the FSM agreed on the broad-intent bucket.

**Author.** Claude (Team Phase-4, cycle-2C).

**Date.** 2026-04-26. Hackathon §0 mode active.

**Branch.** `voice/cycle2C-phase4-perception`.

**Frozen surfaces respected.** No edits to `agents/livekit/*` or `LiveCallRoom.tsx`. Audio path untouched. The 9 affordances Team F shipped in cycle-2R are unchanged.

---

## 1. Why now (the observability story)

Cycle-2C is pivoting from a single-prompt LLM dispatcher to "supervisors not dispatchers": Nemotron-3-Nano emits a structured 12-field classification per turn, the deterministic FSM picks the exact 21-value intent based on its current state plus that classification, and templates speak.

The risk is opaque drift. If Nemotron mis-classifies, the FSM will quietly absorb wrong features and produce a wrong intent. Without observability, the only signal is voice-quality regression heard at evaluation time.

Phase-4 makes the classifier output visible turn-by-turn. Three audiences:

1. **Brandon Dent, MD (the user).** Watches one call, sees what Nemotron perceived at each turn, and judges whether the FSM trust score is calibrated.
2. **Beta testers.** See the perception block paired with each FSM transition. Self-explanatory — no docs needed to understand AGREEMENT vs MISMATCH vs n/a.
3. **The future critic agent (cycle-2BC).** Will consume the same `perception` events from the data-track for post-hoc disagreement audits. The frontend rendering and the audit feed share a contract.

Phase-4 lands BEFORE Phase-3 fusion because observability has a higher truth-value than fusion: we want to see Nemotron's drift before we trust it to feed the FSM.

---

## 2. Affordance catalog (the new sub-panel)

The Nemotron perception sub-panel mounts in the right-pane below the transcript. Same `b3-cad-*` styling vocabulary Team F established. Five visual zones:

### 2.1 Header

Three compact tags, single row, monospace:

- `NEMOTRON · PERCEPTION` — title.
- `turn N` — pairs with the active FSM turn so the viewer can confirm the alignment.
- `conf · 0.92` — overall classifier confidence. Color-graded by the same thresholds the orchestrator uses to gate feature merging:
  - `>= 0.7` → green (high). FSM trusts the classifier.
  - `[0.4, 0.7)` → amber (mid). Logged disagreement; regex still wins on hard signals.
  - `< 0.4` → red (low). Classifier output ignored entirely; behaves as if the env flag were OFF.
- `AGREEMENT` / `MISMATCH` / `n/a · low conf` badge — the agreement signal.

### 2.2 Body (10 rows)

| Row | Field(s) rendered | Why |
|---|---|---|
| Intent | broad-bucket label + raw enum | What kind-of-move Nemotron classified the utterance as. |
| Acuity | P1-P5 colored chip (P1=hot pink, P2=orange, P3=yellow, P4=green, P5=blue, unknown=gray) | MPDS priority. P1 chip pulses with the cardiac border so the dispatcher cannot miss it. |
| Surface | `floor`/`chair`/`bed`/`couch`/`vehicle`/`standing`/`unknown` + reposition-needed hint | Direct fix for cycle-2R3 Bug 3 — must be visible, not buried. |
| Role | first-party / third-party / unknown | Drives KQ_RESPONSIVE_BREATHING vs KQ_SEVERITY routing. |
| Complaint | medical / trauma / fire / crime / unknown | Top-level bucket. Mirrors the existing CallerCard's `complaint` field. |
| Caller Q | YES/no boolean badge + direct_question_kind tag | Bug-1 fix surface. When the caller asked something, the panel says SO. |
| Negation | `CONTRADICTS prior Q` orange badge / no | Bug-3 fix surface. Brings the contradiction signal forward. |
| Awake | tri-state badge (responsive / unresponsive / "caller did not say") | Honest about null — never invents a value. |
| Breathing | tri-state badge (normal / not / "caller did not say") | Same null-honest discipline. |
| Address | raw / normalized / has_digit sub-rows | The model's own address view; useful for log diff against the FSM's deterministic normalizer. |

### 2.3 Footer

Single line: `latency · 268ms`. Telemetry only — measures classifier vLLM-call wall-clock from Phase-1's emission. When absent, renders `—`.

---

## 3. Agreement / mismatch logic

The classifier emits a 6-value broad-intent (intake / key_question / verify / instruct / answer / reprompt). The FSM picks one of 21 named intents. We compare the broad bucket of the FSM's intent against the classifier's broad-intent.

```
classifier.confidence < 0.4    -> n_a   (don't fault classifier when it isn't sure)
broad(FSM.intent) == classifier.intent -> agreement
broad(FSM.intent) != classifier.intent -> mismatch
```

The mapping is hardcoded in `FSM_INTENT_TO_BROAD` in `DispatchPanel.tsx`. It mirrors the prose in `findings/voice/cycle2C_structured_classifier/team-c/system-prompt-spec.md` §3:

| FSM 21-value intent | Broad bucket |
|---|---|
| `request_location_and_emergency`, `request_location`, `request_emergency`, `confirm_address`, `deliver_reassurance` | `intake` |
| `kq_responsive_breathing`, `kq_severity`, `kq_bleeding_location`, `kq_fire_evacuation`, `kq_safe_location` | `key_question` |
| `verify_cpr_surface`, `verify_cpr_breathing` | `verify` |
| `instruct_cpr_compressions`, `instruct_choking_back_blows`, `instruct_pressure_bleed`, `instruct_seizure_clear_area` | `instruct` |
| `answer_do_not_move`, `answer_how_long`, `answer_outcome_uncertain`, `closeout` | `answer` |
| `reprompt_caller` | `reprompt` |

The mapping is exported as `fsmIntentToBroad()` and unit-tested. Adding a new FSM intent without updating the map breaks the test.

---

## 4. Subscription wiring

Phase-1 is adding a new event type `perception` to the `prism42.dispatch` LiveKit data-track topic (the same channel `turn` and `reply` already flow through). The frontend changes:

1. **`DispatchEvent` union** extended with `DispatchPerceptionEvent` mirroring all 12 schema fields plus optional `latency_ms` telemetry.
2. **`DispatchSubscription`** filter relaxed to also forward `parsed.type === "perception"` upstream.
3. **`reducer`** handles `kind: "perception"` by storing the event keyed by `turn_index` in `state.perception_by_turn` and incrementing `state.perception_count`. Existing `turn` / `reply` / `caller_partial` reducers are unchanged.
4. **`PerceptionPanel`** renders `state.perception_by_turn[state.current_turn_index]` against `state.current_fsm`.

When `perception_count == 0`, the sub-panel collapses to a single dashed-border placeholder reading `awaiting Phase-1 deploy`. This is the graceful-degradation path while Phase-1 is still in flight: the panel does not pop in/out; it sits in the layout but stays muted.

---

## 5. Fixture mode (the demo path)

`lib/dispatch-fixtures/cardiac-arrest-demo.json` is extended from 12 events (6 turns + 6 replies) to 18 events (6 turns + 6 replies + 6 perceptions). Each perception event fires ~250 ms after its paired turn — the same lag the worker side will produce after the classifier returns.

Three demonstration arcs the fixture exercises:

1. **Happy path (turns 1, 2, 3, 4).** Classifier confidence high (0.91-0.94). Broad bucket matches the FSM. AGREEMENT badge.
2. **Drift / negation (turn 5).** Caller says "wait he's in the chair not the floor I moved him earlier". Classifier sees `intent=verify, surface=chair, negation_signal=true, conf=0.87`. The FSM, having already latched cardiac_cpr, did NOT re-route to a verify intent and stayed on `instruct_cpr_compressions` (broad=instruct). `verify` ≠ `instruct` → MISMATCH badge fires. This is exactly the Bug-3 drift the panel is built to surface.
3. **Backchannel (turn 6).** Caller says "uh okay". Classifier confidence 0.18 (low). The FSM picked `reprompt_caller` (broad=reprompt) — and even though that broad-bucket would technically match the classifier's `reprompt`, the LOW-CONFIDENCE rule short-circuits the badge to `n/a · low conf`. We never pretend a low-conf classifier validates the FSM.

The viewer can SEE the three different states by playing the fixture once.

---

## 6. Tests

`__tests__/dispatch-fixture.test.ts` gains 9 new tests in a `describe("perception sub-panel — cycle-2C Phase-4")` block:

1. fixture has at least one perception event per turn
2. every perception entry has all 12 schema-required fields (mirrors `schema.json:required`)
3. each perception turn_index pairs with a turn event
4. perception events fire AFTER their paired turn (timestamp ordering)
5. `fsmIntentToBroad` maps every 21-value FSM intent to a broad bucket — adding a new intent without updating the map fails this test
6. high-confidence + matching broad-intent → `agreement`
7. low-confidence (<0.4) → `n_a` regardless of FSM
8. high-confidence MISMATCH on broad-intent disagreement (turn-5 drift case)
9. cardiac fixture exercises agreement + mismatch + n_a (the demo discipline)

Plus the original 8 cardiac-fixture tests still pass — Phase-4 is strictly additive.

Total: 17 tests in `dispatch-fixture.test.ts`, 40 across the file (with the 23 in glasswing-* tests). All green.

---

## 7. Verification

```
$ npx tsc --noEmit                          # clean — no type errors
$ npm run test                              # 40/40 green
$ npm run build                             # clean
$ NEXT_PUBLIC_DISPATCH_FIXTURE_MODE=1 npm run dev
$ open http://localhost:3042/prism42/livekit
```

Screenshot saved to `screenshot.png` in this directory.

---

## 8. Files touched

| File | Change | LoC delta |
|---|---|---:|
| `mvp/911-console-live/components/DispatchPanel.tsx` | Added perception types, reducer case, `PerceptionPanel` sub-component, helper exports (`fsmIntentToBroad`, `computeAgreement`), CSS rules | +700 |
| `mvp/911-console-live/lib/dispatch-fixtures/cardiac-arrest-demo.json` | Added 6 perception events interleaved with existing turns; expanded turn 5 to demonstrate negation drift | +120 |
| `mvp/911-console-live/__tests__/dispatch-fixture.test.ts` | Added 9 tests in a new describe block | +160 |
| `findings/voice/cycle2C_phase4_ui/team-phase4/design.md` | This doc | NEW |
| `findings/voice/cycle2C_phase4_ui/team-phase4/screenshot.png` | Fixture-mode screenshot | NEW |

Total: ~980 LoC across one component file, one fixture, one test file. Pure additive — no existing affordance regressed.

---

## 9. Out of scope (deferred)

- **Critic side.** The cycle-2BC critic agent will consume the same `perception` events from the data-track to flag drift turns for prompt-revision training data. The contract is the same. Phase-4 ships the frontend; the critic ships separately.
- **Per-field confidence visualization.** The schema gates on a single overall `confidence` (per system-prompt-spec.md §3 — explicitly rejected per-field for complexity reasons). When/if per-field confidence ships, this panel can extend without breaking compat.
- **Diff view.** "Show me what the regex Features look like vs what the LLM Features look like" would be valuable — defer to cycle-2BC.
- **Latency strip integration.** The classifier latency is shown in the perception footer. We could lift it into the existing top-level `LatencyStrip` as a 5th pill, but that would change the meaning of the strip (now mixes voice-pipeline latency with classifier-call latency). Deferred — keep the strip clean.
- **Audio pipeline changes.** Frozen by Hackathon §0. Phase-4 is read-only on `agents/livekit/*`.

---

## 10. References

- `findings/voice/cycle2C_structured_classifier/team-c/schema.json` — JSON schema for the 12 perception fields
- `findings/voice/cycle2C_structured_classifier/team-c/system-prompt-spec.md` — semantic meaning of every value
- `findings/voice/cycle2C_structured_classifier/team-c/integration-plan.md` — Phase-1's worker-side payload contract (§12 telemetry surface)
- `findings/voice/cycle2R_livekit_selfhost/team-f/design.md` — design language and the existing 9 affordances
- `agents/livekit/dispatch_publisher.py` — current data-track publisher; Phase-1 will add a `publish_perception` method paired with `publish_turn`
- `mvp/911-console-live/components/DispatchPanel.tsx` — extended in this branch
