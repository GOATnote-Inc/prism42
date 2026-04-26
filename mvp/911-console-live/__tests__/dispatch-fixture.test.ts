// Cycle-2R Team F — DispatchPanel fixture validation.
//
// Verifies the cardiac-arrest fixture JSON is structurally valid and
// the FSM transitions it encodes match the cycle-2Q dispatcher_fsm.py
// invariants. No React, no DOM — fixture-only logic check.
//
// Cycle-2C Phase-4 (additive): also validates the interleaved
// `perception` events that mirror the structured-classifier schema in
// findings/voice/cycle2C_structured_classifier/team-c/schema.json.

import { describe, expect, it } from "vitest";
import fixture from "../lib/dispatch-fixtures/cardiac-arrest-demo.json";
import {
  computeAgreement,
  fsmIntentToBroad,
  type DispatchPerceptionEvent,
  type DispatchFSM,
  type FSMIntent,
} from "../components/DispatchPanel";

interface DispatchTurn {
  type: "turn";
  session_id: string;
  turn_index: number;
  timestamp_ms: number;
  caller_utterance: string;
  fsm: {
    state: string;
    intent: string;
    verify_step: string;
    pronouns: string;
    reassurance_done: boolean;
    is_cardiac_arrest: boolean;
    address_known: boolean;
  };
  latched_facts: string[];
  recent_replies: string[];
  latency_ms: { stt: number; llm_ttft: number; tts_ttfb: number };
}

interface DispatchReply {
  type: "reply";
  session_id: string;
  turn_index: number;
  timestamp_ms: number;
  text: string;
  tts_ttfb_ms: number;
  tts_total_ms: number;
}

type DispatchEvent = DispatchTurn | DispatchReply | DispatchPerceptionEvent;

describe("cardiac-arrest fixture", () => {
  const events = (fixture as { events: DispatchEvent[] }).events;

  it("has at least one turn and one reply", () => {
    const turns = events.filter((e) => e.type === "turn");
    const replies = events.filter((e) => e.type === "reply");
    expect(turns.length).toBeGreaterThan(0);
    expect(replies.length).toBeGreaterThan(0);
  });

  it("turns and replies are interleaved with monotonic turn_index", () => {
    let lastTurn = 0;
    let lastReply = 0;
    for (const e of events) {
      if (e.type === "turn") {
        expect(e.turn_index).toBeGreaterThanOrEqual(lastTurn);
        lastTurn = e.turn_index;
      } else if (e.type === "reply") {
        expect(e.turn_index).toBeGreaterThanOrEqual(lastReply);
        lastReply = e.turn_index;
      }
    }
  });

  it("first turn fires the cardiac override (FSM state=critical_verify)", () => {
    const firstTurn = events.find((e) => e.type === "turn") as DispatchTurn;
    expect(firstTurn.fsm.is_cardiac_arrest).toBe(true);
    // Per dispatcher_fsm.py: when not_breathing fires from intake, the
    // FSM transitions DIRECTLY into critical_verify — never to
    // address_confirmed nor reassurance_delivered. Cycle-2Q invariant.
    expect(firstTurn.fsm.state).toBe("critical_verify");
  });

  it("reassurance_done latches once and stays latched", () => {
    const turns = events.filter((e) => e.type === "turn") as DispatchTurn[];
    let everSeen = false;
    for (const t of turns) {
      if (t.fsm.reassurance_done) {
        everSeen = true;
      } else if (everSeen) {
        // Once it goes true, it must STAY true — that's the FSM latch.
        throw new Error(
          `reassurance_done flipped back to false at turn ${t.turn_index}`,
        );
      }
    }
  });

  it("CPR coaching only fires after both verify steps pass", () => {
    const turns = events.filter((e) => e.type === "turn") as DispatchTurn[];
    for (const t of turns) {
      if (t.fsm.intent === "instruct_cpr_compressions") {
        // Either we're inside critical_cpr (post-verify), or this is the
        // very first transition out of critical_verify with both
        // verifications confirmed. The fixture encodes the latter.
        expect(["critical_cpr"]).toContain(t.fsm.state);
        expect(t.fsm.verify_step).toBe("done");
      }
    }
  });

  it("latched_facts surfaces the cardiac-verify-in-progress hint", () => {
    const turnsBeforeReassurance = (events.filter((e) => e.type === "turn") as DispatchTurn[])
      .filter((t) => !t.fsm.reassurance_done);
    if (turnsBeforeReassurance.length === 0) return;
    const t0 = turnsBeforeReassurance[0];
    const haveCardiacFact = t0.latched_facts.some((f) =>
      f.toLowerCase().includes("cardiac-arrest verification in progress"),
    );
    expect(haveCardiacFact).toBe(true);
  });

  it("pronouns commit on the cardiac override (he/him from 'my husband')", () => {
    const firstTurn = events.find((e) => e.type === "turn") as DispatchTurn;
    expect(firstTurn.fsm.pronouns).toBe("he/him");
  });

  it("latency_ms fields are reasonable (< 1500ms budget)", () => {
    const turns = events.filter((e) => e.type === "turn") as DispatchTurn[];
    for (const t of turns) {
      const total = t.latency_ms.stt + t.latency_ms.llm_ttft + t.latency_ms.tts_ttfb;
      expect(total).toBeLessThan(1500);
      expect(t.latency_ms.stt).toBeGreaterThan(0);
      expect(t.latency_ms.llm_ttft).toBeGreaterThan(0);
      expect(t.latency_ms.tts_ttfb).toBeGreaterThan(0);
    }
  });
});

// Cycle-2C Phase-4 — perception sub-panel.
//
// Verifies that:
// - the cardiac fixture interleaves perception events alongside turns
// - each perception entry conforms to the 12-field schema
// - the agreement / mismatch / n/a logic against the FSM intent is sane
//   for the fixture content (cardiac scenario, mostly verify/instruct,
//   one negation, one low-confidence backchannel).
describe("perception sub-panel — cycle-2C Phase-4", () => {
  const events = (fixture as { events: DispatchEvent[] }).events;
  const perceptions = events.filter(
    (e) => e.type === "perception",
  ) as DispatchPerceptionEvent[];
  const turns = events.filter((e) => e.type === "turn") as DispatchTurn[];

  it("fixture has at least one perception event per turn", () => {
    expect(perceptions.length).toBeGreaterThan(0);
    expect(perceptions.length).toBe(turns.length);
  });

  it("every perception entry has all 12 schema-required fields", () => {
    // Mirrors findings/voice/cycle2C_structured_classifier/team-c/schema.json
    // `required` array. Missing field === schema invalid === Phase-1 bug.
    const REQUIRED = [
      "intent",
      "acuity",
      "address_candidate",
      "awake",
      "breathing",
      "surface",
      "caller_question",
      "caller_role",
      "complaint_category",
      "negation_signal",
      "direct_question_kind",
      "confidence",
    ];
    for (const p of perceptions) {
      for (const k of REQUIRED) {
        // null is a valid value for awake/breathing/address parts;
        // we only require the KEY to be present.
        expect(Object.prototype.hasOwnProperty.call(p, k)).toBe(true);
      }
      // address_candidate sub-fields per schema.
      expect(Object.prototype.hasOwnProperty.call(p.address_candidate, "raw_text")).toBe(true);
      expect(Object.prototype.hasOwnProperty.call(p.address_candidate, "normalized")).toBe(true);
      expect(Object.prototype.hasOwnProperty.call(p.address_candidate, "has_digit")).toBe(true);
      // confidence in [0, 1].
      expect(p.confidence).toBeGreaterThanOrEqual(0);
      expect(p.confidence).toBeLessThanOrEqual(1);
      // intent is one of the 6 broad-bucket enum values.
      expect([
        "intake",
        "key_question",
        "verify",
        "instruct",
        "answer",
        "reprompt",
      ]).toContain(p.intent);
      // acuity is one of the 6 schema enum values.
      expect(["P1", "P2", "P3", "P4", "P5", "unknown"]).toContain(p.acuity);
      // surface is one of the 7 enum values.
      expect([
        "floor",
        "chair",
        "bed",
        "couch",
        "vehicle",
        "standing",
        "unknown",
      ]).toContain(p.surface);
    }
  });

  it("each perception turn_index pairs with a turn event", () => {
    const turnIdxSet = new Set(turns.map((t) => t.turn_index));
    for (const p of perceptions) {
      expect(turnIdxSet.has(p.turn_index)).toBe(true);
    }
  });

  it("perception events fire AFTER their paired turn (timestamp ordering)", () => {
    // The classifier runs after STT-final but before the FSM transition;
    // Phase-1 emits perception events ~10-300ms after the turn event.
    for (const p of perceptions) {
      const pairedTurn = turns.find((t) => t.turn_index === p.turn_index);
      expect(pairedTurn).toBeDefined();
      if (pairedTurn) {
        expect(p.timestamp_ms).toBeGreaterThanOrEqual(pairedTurn.timestamp_ms);
      }
    }
  });

  it("fsmIntentToBroad maps every 21-value FSM intent to a broad bucket", () => {
    // No undefined results — every FSM intent must be classifiable.
    const ALL_FSM_INTENTS: FSMIntent[] = [
      "request_location_and_emergency",
      "request_location",
      "request_emergency",
      "confirm_address",
      "deliver_reassurance",
      "kq_responsive_breathing",
      "kq_severity",
      "kq_bleeding_location",
      "kq_fire_evacuation",
      "kq_safe_location",
      "verify_cpr_surface",
      "verify_cpr_breathing",
      "instruct_cpr_compressions",
      "instruct_choking_back_blows",
      "instruct_pressure_bleed",
      "instruct_seizure_clear_area",
      "answer_do_not_move",
      "answer_how_long",
      "answer_outcome_uncertain",
      "reprompt_caller",
      "closeout",
    ];
    for (const fi of ALL_FSM_INTENTS) {
      const broad = fsmIntentToBroad(fi);
      expect(broad).not.toBeNull();
    }
  });

  it("computeAgreement: high-confidence matching broad-intent → 'agreement'", () => {
    // Turn 1 in the cardiac fixture: FSM intent=verify_cpr_surface
    // (broad=verify), classifier intent=verify, conf=0.92 → AGREEMENT.
    const t1 = turns.find((t) => t.turn_index === 1)!;
    const p1 = perceptions.find((p) => p.turn_index === 1)!;
    const fsm: DispatchFSM = {
      ...t1.fsm,
      intent: t1.fsm.intent as FSMIntent,
      state: t1.fsm.state as DispatchFSM["state"],
      verify_step: t1.fsm.verify_step as DispatchFSM["verify_step"],
      pronouns: t1.fsm.pronouns as DispatchFSM["pronouns"],
    };
    expect(computeAgreement(p1, fsm)).toBe("agreement");
  });

  it("computeAgreement: low-confidence (<0.4) → 'n_a' regardless of FSM", () => {
    // Turn 6 in the cardiac fixture: classifier confidence 0.18 ("uh okay"
    // backchannel). The FSM picked reprompt_caller (broad=reprompt) — even
    // though that broad-bucket would technically agree with the classifier,
    // the LOW-CONFIDENCE rule short-circuits to 'n_a' so we never pretend
    // a low-conf classifier output validates the FSM.
    const t6 = turns.find((t) => t.turn_index === 6)!;
    const p6 = perceptions.find((p) => p.turn_index === 6)!;
    expect(p6.confidence).toBeLessThan(0.4);
    const fsm: DispatchFSM = {
      ...t6.fsm,
      intent: t6.fsm.intent as FSMIntent,
      state: t6.fsm.state as DispatchFSM["state"],
      verify_step: t6.fsm.verify_step as DispatchFSM["verify_step"],
      pronouns: t6.fsm.pronouns as DispatchFSM["pronouns"],
    };
    expect(computeAgreement(p6, fsm)).toBe("n_a");
  });

  it("computeAgreement: high-confidence MISMATCH on broad-intent disagreement", () => {
    // Turn 5 in the cardiac fixture: caller says "wait he's in the chair
    // not the floor I moved him earlier" — classifier sees this as a
    // verify-style negation (intent=verify, surface=chair, negation=true,
    // conf=0.87). The FSM, having ALREADY latched cardiac_cpr, did not
    // route to a re-verify intent and stayed on instruct_cpr_compressions
    // (broad=instruct). verify ≠ instruct → MISMATCH. This is exactly
    // the Bug-3-style drift the panel is built to surface to beta testers.
    const t5 = turns.find((t) => t.turn_index === 5)!;
    const p5 = perceptions.find((p) => p.turn_index === 5)!;
    expect(p5.confidence).toBeGreaterThanOrEqual(0.4);
    expect(p5.intent).toBe("verify");
    expect(p5.negation_signal).toBe(true);
    expect(p5.surface).toBe("chair");
    const fsm: DispatchFSM = {
      ...t5.fsm,
      intent: t5.fsm.intent as FSMIntent,
      state: t5.fsm.state as DispatchFSM["state"],
      verify_step: t5.fsm.verify_step as DispatchFSM["verify_step"],
      pronouns: t5.fsm.pronouns as DispatchFSM["pronouns"],
    };
    expect(computeAgreement(p5, fsm)).toBe("mismatch");
  });

  it("computeAgreement: null perception → 'no_fsm' (panel hides chrome)", () => {
    const fsm: DispatchFSM = {
      state: "intake",
      intent: "request_location_and_emergency",
      verify_step: "none",
      pronouns: "unknown",
      reassurance_done: false,
      is_cardiac_arrest: false,
      address_known: false,
    };
    expect(computeAgreement(null, fsm)).toBe("no_fsm");
    expect(computeAgreement(undefined, fsm)).toBe("no_fsm");
  });

  it("cardiac fixture exercises both happy-path and drift scenarios", () => {
    // High-level smoke: at least one AGREEMENT, at least one MISMATCH,
    // and at least one n_a (low-conf). This is the demo discipline —
    // beta testers seeing the panel must SEE all three states.
    const tagsByTurn = perceptions.map((p) => {
      const pairedTurn = turns.find((t) => t.turn_index === p.turn_index)!;
      const fsm: DispatchFSM = {
        ...pairedTurn.fsm,
        intent: pairedTurn.fsm.intent as FSMIntent,
        state: pairedTurn.fsm.state as DispatchFSM["state"],
        verify_step: pairedTurn.fsm.verify_step as DispatchFSM["verify_step"],
        pronouns: pairedTurn.fsm.pronouns as DispatchFSM["pronouns"],
      };
      return computeAgreement(p, fsm);
    });
    expect(tagsByTurn).toContain("agreement");
    expect(tagsByTurn).toContain("mismatch");
    expect(tagsByTurn).toContain("n_a");
  });
});
