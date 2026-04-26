// Cycle-2R Team F — DispatchPanel fixture validation.
//
// Verifies the cardiac-arrest fixture JSON is structurally valid and
// the FSM transitions it encodes match the cycle-2Q dispatcher_fsm.py
// invariants. No React, no DOM — fixture-only logic check.

import { describe, expect, it } from "vitest";
import fixture from "../lib/dispatch-fixtures/cardiac-arrest-demo.json";

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

type DispatchEvent = DispatchTurn | DispatchReply;

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
