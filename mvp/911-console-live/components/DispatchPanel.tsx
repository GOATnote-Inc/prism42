"use client";

// DispatchPanel — Team F, cycle-2R.
//
// PSAP-CAD-style dispatcher console. Hydrates from the LiveKit data-track
// topic `prism42.dispatch` (Team A's spec). All UI updates flow from one
// reducer fed by `turn` and `reply` events.
//
// Frozen surface: this component does NOT touch `agents/livekit/*`. The
// worker publishes events on the data-track; we render. Read-only.
//
// See findings/voice/cycle2R_livekit_selfhost/team-f/design.md for the
// affordance survey and the FSM-to-UI mapping.
//
// Fixture mode: when NEXT_PUBLIC_DISPATCH_FIXTURE_MODE=1, the panel
// replays mvp/911-console-live/lib/dispatch-fixtures/cardiac-arrest-demo.json
// at ~3500ms cadence so the UI can be developed and screenshotted without
// the worker live. Default OFF.

import { useEffect, useMemo, useReducer, useRef } from "react";
import { useDataChannel } from "@livekit/components-react";
import cardiacArrestFixture from "@/lib/dispatch-fixtures/cardiac-arrest-demo.json";

// Topic string MUST match the worker.py producer side authored by Team A.
export const DISPATCH_TOPIC = "prism42.dispatch";
export const FIXTURE_REPLAY_INTERVAL_MS = 3500;

// ─────────────────────────────────────────────────────────────────────
// Data-track schema (per the team-f brief; reconcile with team-a/data-
// track-spec.md when it lands).
// ─────────────────────────────────────────────────────────────────────

export type FSMState =
  | "intake"
  | "address_confirmed"
  | "reassurance_delivered"
  | "key_questions"
  | "pre_arrival"
  | "critical_verify"
  | "critical_cpr"
  | "handoff";

export type FSMIntent =
  | "request_location_and_emergency"
  | "request_location"
  | "request_emergency"
  | "confirm_address"
  | "deliver_reassurance"
  | "kq_responsive_breathing"
  | "kq_severity"
  | "kq_bleeding_location"
  | "kq_fire_evacuation"
  | "kq_safe_location"
  | "verify_cpr_surface"
  | "verify_cpr_breathing"
  | "instruct_cpr_compressions"
  | "instruct_choking_back_blows"
  | "instruct_pressure_bleed"
  | "instruct_seizure_clear_area"
  | "answer_do_not_move"
  | "answer_how_long"
  | "answer_outcome_uncertain"
  | "reprompt_caller"
  | "closeout";

export type FSMVerifyStep = "q_surface" | "q_breathing" | "none" | "done";

export type FSMPronouns = "they" | "he/him" | "she/her" | "unknown" | "patient";

export interface DispatchFSM {
  state: FSMState;
  intent: FSMIntent;
  verify_step: FSMVerifyStep;
  pronouns: FSMPronouns;
  reassurance_done: boolean;
  is_cardiac_arrest: boolean;
  address_known: boolean;
  /** Optional: complaint category if the worker emits it. */
  complaint?: "medical" | "fire" | "trauma" | "crime" | "unknown";
  /** Optional: free-form address string as the caller stated it. */
  address?: string;
}

export interface DispatchTurnEvent {
  type: "turn";
  session_id: string;
  turn_index: number;
  timestamp_ms: number;
  caller_utterance: string;
  fsm: DispatchFSM;
  latched_facts: string[];
  recent_replies: string[];
  latency_ms: {
    stt: number;
    llm_ttft: number;
    tts_ttfb: number;
  };
}

export interface DispatchReplyEvent {
  type: "reply";
  session_id: string;
  turn_index: number;
  timestamp_ms: number;
  text: string;
  tts_ttfb_ms: number;
  tts_total_ms: number;
}

export type DispatchEvent = DispatchTurnEvent | DispatchReplyEvent;

// ─────────────────────────────────────────────────────────────────────
// Reducer.
// ─────────────────────────────────────────────────────────────────────

interface TranscriptRow {
  role: "caller" | "dispatcher";
  text: string;
  turn_index: number;
  timestamp_ms: number;
}

interface DispatchState {
  session_id: string | null;
  current_fsm: DispatchFSM | null;
  current_turn_index: number;
  latched_facts: string[];
  transcript: TranscriptRow[];
  latency: { stt: number; llm_ttft: number; tts_ttfb: number; tts_total: number } | null;
  call_started_at: number | null;
  /** Address as known. May be promoted from `caller_utterance` by extractors
   * upstream; for the demo we render whatever the worker sends in `fsm.address`
   * if present, else "GATHERING". */
  address: string | null;
  /** Complaint summary string, surfaced from FSM.complaint. */
  complaint: string;
}

type Action =
  | { kind: "turn"; ev: DispatchTurnEvent }
  | { kind: "reply"; ev: DispatchReplyEvent }
  | { kind: "reset" };

const INITIAL_STATE: DispatchState = {
  session_id: null,
  current_fsm: null,
  current_turn_index: 0,
  latched_facts: [],
  transcript: [],
  latency: null,
  call_started_at: null,
  address: null,
  complaint: "ASSESSING",
};

function reducer(state: DispatchState, action: Action): DispatchState {
  switch (action.kind) {
    case "reset":
      return INITIAL_STATE;
    case "turn": {
      const ev = action.ev;
      // Append the caller utterance row.
      const transcript = [
        ...state.transcript,
        {
          role: "caller" as const,
          text: ev.caller_utterance,
          turn_index: ev.turn_index,
          timestamp_ms: ev.timestamp_ms,
        },
      ];
      // Derive a shown address: prefer fsm.address (worker-provided),
      // else cache the first utterance that the FSM declared
      // address-bearing. The LLM-grade address is shown verbatim;
      // we never invent one.
      let nextAddress = state.address;
      if (ev.fsm.address) nextAddress = ev.fsm.address;
      else if (ev.fsm.address_known && !state.address) {
        nextAddress = extractAddressSnippet(ev.caller_utterance);
      }
      return {
        ...state,
        session_id: ev.session_id,
        current_fsm: ev.fsm,
        current_turn_index: ev.turn_index,
        latched_facts: ev.latched_facts,
        transcript,
        latency: state.latency
          ? {
              stt: ev.latency_ms.stt,
              llm_ttft: ev.latency_ms.llm_ttft,
              tts_ttfb: ev.latency_ms.tts_ttfb,
              tts_total: state.latency.tts_total,
            }
          : { stt: ev.latency_ms.stt, llm_ttft: ev.latency_ms.llm_ttft, tts_ttfb: ev.latency_ms.tts_ttfb, tts_total: 0 },
        call_started_at: state.call_started_at ?? Date.now(),
        address: nextAddress,
        complaint: complaintFromFSM(ev.fsm),
      };
    }
    case "reply": {
      const ev = action.ev;
      const transcript = [
        ...state.transcript,
        {
          role: "dispatcher" as const,
          text: ev.text,
          turn_index: ev.turn_index,
          timestamp_ms: ev.timestamp_ms,
        },
      ];
      return {
        ...state,
        transcript,
        latency: state.latency
          ? {
              stt: state.latency.stt,
              llm_ttft: state.latency.llm_ttft,
              tts_ttfb: ev.tts_ttfb_ms,
              tts_total: ev.tts_total_ms,
            }
          : { stt: 0, llm_ttft: 0, tts_ttfb: ev.tts_ttfb_ms, tts_total: ev.tts_total_ms },
      };
    }
    default:
      return state;
  }
}

// Extract a likely-address snippet from a caller utterance. Best-effort
// only; the worker should send `fsm.address` in the data-track payload
// once Team A's spec lands. We never display anything we did not just
// hear from the caller.
function extractAddressSnippet(utterance: string): string | null {
  if (!utterance) return null;
  // Prefer a "<digits> <street-words> <suffix>" anchor so we stop at the
  // street suffix and don't drag pronouns/verbs into the address.
  const suffixed = utterance.match(
    /\b(\d{1,5}\s+(?:[A-Za-z][A-Za-z0-9]*\s+){0,4}(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|Way|Highway|Hwy|Parkway|Pkwy)\b)\.?/i,
  );
  if (suffixed) return suffixed[1].replace(/\s+/g, " ").trim();
  // Fall back to "<digits> <2-3 capitalized words>".
  const fallback = utterance.match(
    /\b(\d{1,5}\s+[A-Za-z][A-Za-z0-9]*(?:\s+[A-Za-z][A-Za-z0-9]*){0,2})\b/,
  );
  if (fallback) return fallback[1].trim();
  return null;
}

function complaintFromFSM(fsm: DispatchFSM): string {
  if (fsm.is_cardiac_arrest) return "CARDIAC ARREST · CPR PRE-ARRIVAL";
  if (fsm.complaint === "fire") return "FIRE";
  if (fsm.complaint === "trauma") return "TRAUMA";
  if (fsm.complaint === "medical") return "MEDICAL";
  if (fsm.complaint === "crime") return "CRIME";
  if (fsm.state === "intake") return "ASSESSING";
  return "ASSESSING";
}

// ─────────────────────────────────────────────────────────────────────
// Static lookup tables.
// ─────────────────────────────────────────────────────────────────────

const STATE_ORDER: FSMState[] = [
  "intake",
  "address_confirmed",
  "reassurance_delivered",
  "key_questions",
  "pre_arrival",
  "handoff",
];

const STATE_LABEL: Record<FSMState, string> = {
  intake: "Intake",
  address_confirmed: "Address",
  reassurance_delivered: "Reassured",
  key_questions: "Key questions",
  pre_arrival: "Pre-arrival",
  critical_verify: "Critical verify",
  critical_cpr: "Coaching CPR",
  handoff: "Handoff",
};

// Human-readable intent strings — see design.md §6.
const INTENT_LABEL: Record<FSMIntent, string> = {
  request_location_and_emergency: "Asking for location and nature",
  request_location: "Asking for location",
  request_emergency: "Asking what the emergency is",
  confirm_address: "Confirming address",
  deliver_reassurance: "Reassuring caller (one-time)",
  kq_responsive_breathing: "Checking responsiveness and breathing",
  kq_severity: "Probing severity (1-10 / sentence-length)",
  kq_bleeding_location: "Locating bleed and severity",
  kq_fire_evacuation: "Verifying everyone is out",
  kq_safe_location: "Verifying caller is safe",
  verify_cpr_surface: "Verifying patient on hard surface",
  verify_cpr_breathing: "Verifying breathing vs gasping",
  instruct_cpr_compressions: "Coaching chest compressions",
  instruct_choking_back_blows: "Coaching back blows for choking",
  instruct_pressure_bleed: "Coaching direct pressure for bleed",
  instruct_seizure_clear_area: "Coaching seizure clear-area",
  answer_do_not_move: "Answering: do not move patient",
  answer_how_long: "Answering: ETA — stay on the line",
  answer_outcome_uncertain: "Answering: outcome uncertain — keep watching",
  reprompt_caller: "Re-prompting caller",
  closeout: "Closing out — stay on the line",
};

// Criticality color band — drives the caller-card left border + top-bar pulse.
function criticalityClass(fsm: DispatchFSM | null): string {
  if (!fsm) return "b3-cad-crit-gray";
  if (fsm.is_cardiac_arrest) return "b3-cad-crit-red";
  if (fsm.complaint === "trauma") return "b3-cad-crit-orange";
  if (fsm.complaint === "fire") return "b3-cad-crit-yellow";
  if (fsm.complaint === "medical") return "b3-cad-crit-orange";
  if (fsm.complaint === "crime") return "b3-cad-crit-orange";
  if (fsm.state === "intake") return "b3-cad-crit-gray";
  return "b3-cad-crit-green";
}

const KEY_TERMS_RE = /(\b(?:not breathing|no breath|no pulse|stopped breathing|gasping|agonal|address|gunshot|stabbed|fire|burning|smoke|seizure|chest pain|heart attack|unconscious|unresponsive)\b)/gi;

// ─────────────────────────────────────────────────────────────────────
// DispatchSubscription — subscribes to the `prism42.dispatch` LiveKit
// data channel and forwards decoded events upstream. MUST be mounted
// INSIDE a <LiveKitRoom>; the parent page is responsible for gating.
//
// React hooks must be called unconditionally, so this is a separate
// component the page mounts only when the Room is connected.
// ─────────────────────────────────────────────────────────────────────

export function DispatchSubscription({
  onEvent,
}: {
  onEvent: (ev: DispatchEvent) => void;
}) {
  useDataChannel(DISPATCH_TOPIC, (msg) => {
    try {
      const text = new TextDecoder().decode(msg.payload);
      const parsed = JSON.parse(text) as DispatchEvent;
      if (parsed.type === "turn" || parsed.type === "reply") {
        onEvent(parsed);
      }
    } catch {
      // Malformed payload — drop. Frontend stays on last-known values.
    }
  });
  return null;
}

// ─────────────────────────────────────────────────────────────────────
// useFixtureMode — replays the bundled JSON fixture on a timer when
// NEXT_PUBLIC_DISPATCH_FIXTURE_MODE === "1".
// ─────────────────────────────────────────────────────────────────────

function useFixtureMode(dispatch: React.Dispatch<Action>) {
  const enabled =
    typeof process !== "undefined" &&
    process.env.NEXT_PUBLIC_DISPATCH_FIXTURE_MODE === "1";

  useEffect(() => {
    if (!enabled) return;
    const events = (cardiacArrestFixture as { events: DispatchEvent[] }).events;
    let idx = 0;
    let cancelled = false;

    function tick() {
      if (cancelled) return;
      if (idx >= events.length) return; // freeze on the last frame
      const ev = events[idx++];
      if (ev.type === "turn") dispatch({ kind: "turn", ev });
      else if (ev.type === "reply") dispatch({ kind: "reply", ev });
      // First few events fire faster so the viewer sees the FSM hop into
      // CARDIAC + verify quickly; later events space out so the dispatcher
      // discipline (one-time reassurance, CPR coaching) reads cleanly.
      const interval = idx <= 2 ? 1100 : FIXTURE_REPLAY_INTERVAL_MS;
      setTimeout(tick, interval);
    }
    // Kick off after a short delay so the static panel chrome paints first.
    const handle = setTimeout(tick, 500);

    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
  }, [enabled, dispatch]);

  return enabled;
}

// ─────────────────────────────────────────────────────────────────────
// Sub-components.
// ─────────────────────────────────────────────────────────────────────

function CallerCard({
  state,
}: {
  state: DispatchState;
}) {
  const fsm = state.current_fsm;
  const elapsed = useElapsed(state.call_started_at);
  const critClass = criticalityClass(fsm);
  return (
    <div className={`b3-cad-caller ${critClass}`}>
      <div className="b3-cad-caller-band" />
      <div className="b3-cad-caller-body">
        <div className="b3-cad-caller-row">
          <div className="b3-cad-caller-meta">CALLER · LIVE</div>
          <div className="b3-cad-caller-clock">
            <span className="b3-cad-clock-label">on call</span>{" "}
            <span className="b3-cad-clock-num">{elapsed}</span>
          </div>
        </div>
        <div className="b3-cad-caller-row">
          <div className="b3-cad-caller-loc">
            <div className="b3-cad-field-label">Location</div>
            <div className="b3-cad-field-val">
              {state.address ?? (fsm?.address_known ? "STATED" : "GATHERING")}
            </div>
          </div>
          <div className="b3-cad-caller-comp">
            <div className="b3-cad-field-label">Complaint</div>
            <div className="b3-cad-field-val">{state.complaint}</div>
          </div>
        </div>
        <div className="b3-cad-caller-row">
          <PronounsBadge fsm={fsm} />
          {fsm?.is_cardiac_arrest && (
            <span className="b3-cad-pill b3-cad-pill-red">CARDIAC P1</span>
          )}
          {fsm?.reassurance_done && (
            <span className="b3-cad-pill b3-cad-pill-blue">REASSURED</span>
          )}
        </div>
      </div>
    </div>
  );
}

function PronounsBadge({ fsm }: { fsm: DispatchFSM | null }) {
  const committed =
    fsm?.pronouns === "he/him" ||
    fsm?.pronouns === "she/her" ||
    fsm?.pronouns === "they";
  const label = fsm?.pronouns ?? "unknown";
  return (
    <span
      className={`b3-cad-pill ${committed ? "b3-cad-pill-blue" : "b3-cad-pill-gray"}`}
      title="Pronouns committed by the FSM"
    >
      pronouns · {label}
    </span>
  );
}

function StateBreadcrumb({ fsm }: { fsm: DispatchFSM | null }) {
  const current = fsm?.state ?? "intake";
  const inCritical = current === "critical_verify" || current === "critical_cpr";
  // Find current-step index against the canonical sequence. Critical
  // states render as a sub-track that branches off the active step.
  const currentIndex = STATE_ORDER.indexOf(current as FSMState);
  return (
    <div className="b3-cad-bread">
      <div className="b3-cad-bread-row">
        {STATE_ORDER.map((s, i) => {
          const reached = currentIndex >= i || inCritical;
          const here = !inCritical && current === s;
          return (
            <div key={s} className="b3-cad-bread-step">
              <div
                className={`b3-cad-bread-dot ${reached ? "b3-cad-bread-dot-on" : ""} ${here ? "b3-cad-bread-dot-here" : ""}`}
              />
              <div
                className={`b3-cad-bread-label ${here ? "b3-cad-bread-label-here" : ""}`}
              >
                {STATE_LABEL[s]}
              </div>
              {i < STATE_ORDER.length - 1 && (
                <div className={`b3-cad-bread-line ${reached ? "b3-cad-bread-line-on" : ""}`} />
              )}
            </div>
          );
        })}
      </div>
      {inCritical && (
        <div className="b3-cad-bread-crit">
          <div className="b3-cad-bread-crit-tag">CRITICAL VERIFY</div>
          <div className="b3-cad-bread-crit-track">
            <span
              className={`b3-cad-bread-crit-step ${current === "critical_verify" ? "b3-cad-bread-crit-step-here" : "b3-cad-bread-crit-step-on"}`}
            >
              verify
            </span>
            <span
              className={`b3-cad-bread-crit-step ${current === "critical_cpr" ? "b3-cad-bread-crit-step-here" : ""}`}
            >
              cpr
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

function ActiveIntent({ fsm }: { fsm: DispatchFSM | null }) {
  if (!fsm) {
    return (
      <div className="b3-cad-intent">
        <div className="b3-cad-intent-label">Active intent</div>
        <div className="b3-cad-intent-text b3-cad-dim">Waiting for first turn</div>
      </div>
    );
  }
  const human = INTENT_LABEL[fsm.intent] ?? fsm.intent;
  return (
    <div className="b3-cad-intent">
      <div className="b3-cad-intent-label">Active intent</div>
      <div className="b3-cad-intent-text">{human}</div>
      <div className="b3-cad-intent-tag">tag · {fsm.intent}</div>
    </div>
  );
}

function LatchedFacts({ facts }: { facts: string[] }) {
  return (
    <div className="b3-cad-latched">
      <div className="b3-cad-latched-label">Latched facts</div>
      {facts.length === 0 ? (
        <div className="b3-cad-dim b3-cad-latched-empty">
          No latches yet — caller still in intake.
        </div>
      ) : (
        <ul className="b3-cad-latched-list">
          {facts.map((f, i) => (
            <li key={i} className="b3-cad-latched-item">
              {f}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Transcript({ rows }: { rows: TranscriptRow[] }) {
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  // Auto-scroll only if user is already near the bottom. Lets a viewer
  // scroll back to inspect history without being yanked forward.
  useEffect(() => {
    const c = containerRef.current;
    if (!c) return;
    const nearBottom = c.scrollHeight - c.scrollTop - c.clientHeight < 80;
    if (nearBottom) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [rows.length]);
  return (
    <div className="b3-cad-trx-wrap">
      <div className="b3-cad-trx-hd">
        <span className="b3-cad-trx-hd-t">TRANSCRIPT · ROLE-LABELED</span>
        <span className="b3-cad-trx-hd-s">
          {rows.length} turn{rows.length === 1 ? "" : "s"}
        </span>
      </div>
      <div className="b3-cad-trx-body" ref={containerRef}>
        {rows.length === 0 && (
          <div className="b3-cad-trx-empty">
            Console initialized. Waiting for the first caller utterance.
          </div>
        )}
        {rows.map((r, i) => (
          <TranscriptRowView key={i} row={r} />
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

function TranscriptRowView({ row }: { row: TranscriptRow }) {
  const isCaller = row.role === "caller";
  const highlighted = useMemo(() => highlightKeyTerms(row.text), [row.text]);
  return (
    <div
      className={`b3-cad-trx-row ${isCaller ? "b3-cad-trx-row-caller" : "b3-cad-trx-row-disp"}`}
    >
      <div className="b3-cad-trx-rowhead">
        <span className={`b3-cad-trx-roletag ${isCaller ? "b3-cad-trx-roletag-caller" : "b3-cad-trx-roletag-disp"}`}>
          {isCaller ? "CALLER" : "DISPATCHER"}
        </span>
        <span className="b3-cad-trx-meta">turn {row.turn_index}</span>
      </div>
      <div className="b3-cad-trx-text">{highlighted}</div>
    </div>
  );
}

function highlightKeyTerms(text: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  let lastIdx = 0;
  let m: RegExpExecArray | null;
  KEY_TERMS_RE.lastIndex = 0;
  let i = 0;
  while ((m = KEY_TERMS_RE.exec(text)) !== null) {
    if (m.index > lastIdx) out.push(text.slice(lastIdx, m.index));
    out.push(
      <span key={`hi-${i++}`} className="b3-cad-trx-hi">
        {m[0]}
      </span>,
    );
    lastIdx = m.index + m[0].length;
  }
  if (lastIdx < text.length) out.push(text.slice(lastIdx));
  return out;
}

function PreArrivalQueue({ fsm }: { fsm: DispatchFSM | null }) {
  const showQueue =
    fsm?.state === "critical_verify" || fsm?.state === "critical_cpr" || fsm?.state === "pre_arrival";
  if (!showQueue || !fsm) {
    return (
      <div className="b3-cad-queue">
        <div className="b3-cad-queue-label">Pre-arrival queue</div>
        <div className="b3-cad-dim b3-cad-queue-empty">
          Inactive — pre-arrival fires once the protocol enters verify or CPR.
        </div>
      </div>
    );
  }
  // Three steps for the cardiac-arrest path. Real CADs show MPDS-9 verbatim;
  // this is the conservative subset our FSM gates on.
  const surfaceDone =
    fsm.verify_step === "q_breathing" || fsm.verify_step === "done" || fsm.state === "critical_cpr";
  const breathingDone = fsm.verify_step === "done" || fsm.state === "critical_cpr";
  const cprActive = fsm.state === "critical_cpr";
  return (
    <div className="b3-cad-queue">
      <div className="b3-cad-queue-label">Pre-arrival queue · MPDS-9</div>
      <ol className="b3-cad-queue-list">
        <QueueStep n={1} done={surfaceDone} active={!surfaceDone} blocked={false}>
          Verify patient on a hard surface, flat on their back
        </QueueStep>
        <QueueStep n={2} done={breathingDone} active={surfaceDone && !breathingDone} blocked={!surfaceDone}>
          Verify breathing — normal vs gasping / absent
        </QueueStep>
        <QueueStep n={3} done={false} active={cprActive} blocked={!breathingDone}>
          Coach chest compressions, hard and fast
        </QueueStep>
      </ol>
    </div>
  );
}

function QueueStep({
  n,
  done,
  active,
  blocked,
  children,
}: {
  n: number;
  done: boolean;
  active: boolean;
  blocked: boolean;
  children: React.ReactNode;
}) {
  let status = "PENDING";
  let cls = "b3-cad-q-pending";
  if (done) {
    status = "DONE";
    cls = "b3-cad-q-done";
  } else if (blocked) {
    status = "BLOCKED";
    cls = "b3-cad-q-blocked";
  } else if (active) {
    status = "IN PROGRESS";
    cls = "b3-cad-q-active";
  }
  return (
    <li className={`b3-cad-q-item ${cls}`}>
      <span className="b3-cad-q-n">{n}</span>
      <span className="b3-cad-q-text">{children}</span>
      <span className="b3-cad-q-status">{status}</span>
    </li>
  );
}

function LatencyStrip({
  latency,
}: {
  latency: { stt: number; llm_ttft: number; tts_ttfb: number; tts_total: number } | null;
}) {
  const stt = latency?.stt ?? 0;
  const llm = latency?.llm_ttft ?? 0;
  const tts = latency?.tts_ttfb ?? 0;
  const rtt = stt + llm + tts;
  return (
    <div className="b3-cad-lat">
      <LatPill label="STT" ms={stt} budget={350} />
      <LatPill label="LLM TTFT" ms={llm} budget={500} />
      <LatPill label="TTS TTFB" ms={tts} budget={350} />
      <LatPill label="RTT" ms={rtt} budget={1500} />
      <div className="b3-cad-lat-budget">budget · 1500ms</div>
    </div>
  );
}

function LatPill({ label, ms, budget }: { label: string; ms: number; budget: number }) {
  let cls = "b3-cad-lat-green";
  if (ms > budget) cls = "b3-cad-lat-red";
  else if (ms > budget * 0.75) cls = "b3-cad-lat-amber";
  return (
    <span className={`b3-cad-lat-pill ${cls}`}>
      <span className="b3-cad-lat-label">{label}</span>
      <span className="b3-cad-lat-num">{ms}ms</span>
    </span>
  );
}

// ─────────────────────────────────────────────────────────────────────
// useElapsed — formats hh:mm:ss since the call_started_at timestamp.
// ─────────────────────────────────────────────────────────────────────

function useElapsed(startedAt: number | null): string {
  // Re-render every second so the on-call clock ticks.
  const [, setTick] = useReducer((x) => x + 1, 0);
  useEffect(() => {
    if (!startedAt) return;
    const handle = setInterval(() => setTick(), 1000);
    return () => clearInterval(handle);
  }, [startedAt]);
  if (!startedAt) return "00:00:00";
  const ms = Date.now() - startedAt;
  const s = Math.floor(ms / 1000);
  const hh = String(Math.floor(s / 3600)).padStart(2, "0");
  const mm = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
  const ss = String(s % 60).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}

// ─────────────────────────────────────────────────────────────────────
// Main panel.
// ─────────────────────────────────────────────────────────────────────

export interface DispatchPanelProps {
  /** Force fixture mode regardless of env. Used by tests / Storybook. */
  forceFixture?: boolean;
  /** Optional external event-feed; e.g. forwarded from a LiveKit
   * <DispatchSubscription /> mounted inside <LiveKitRoom>. */
  externalEvent?: DispatchEvent | null;
}

export function DispatchPanel({
  forceFixture = false,
  externalEvent = null,
}: DispatchPanelProps) {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE);
  const fixtureEnabled = useFixtureMode(dispatch);
  // Force-fixture override (test path).
  const forcedFixtureRef = useRef(false);
  useEffect(() => {
    if (!forceFixture || forcedFixtureRef.current) return;
    forcedFixtureRef.current = true;
    const events = (cardiacArrestFixture as { events: DispatchEvent[] }).events;
    let idx = 0;
    const handle = setInterval(() => {
      if (idx >= events.length) return clearInterval(handle);
      const ev = events[idx++];
      if (ev.type === "turn") dispatch({ kind: "turn", ev });
      else if (ev.type === "reply") dispatch({ kind: "reply", ev });
    }, FIXTURE_REPLAY_INTERVAL_MS);
    return () => clearInterval(handle);
  }, [forceFixture]);

  // External event feed (e.g. from <DispatchSubscription /> nested in
  // a <LiveKitRoom>). Each new ref-identical event triggers one dispatch.
  const lastExternalRef = useRef<DispatchEvent | null>(null);
  useEffect(() => {
    if (!externalEvent || externalEvent === lastExternalRef.current) return;
    lastExternalRef.current = externalEvent;
    if (externalEvent.type === "turn") dispatch({ kind: "turn", ev: externalEvent });
    else if (externalEvent.type === "reply") dispatch({ kind: "reply", ev: externalEvent });
  }, [externalEvent]);

  const cardiac = state.current_fsm?.is_cardiac_arrest === true;

  return (
    <div className={`b3-cad ${cardiac ? "b3-cad-cardiac" : ""}`}>
      <style>{B3_CAD_STYLES}</style>
      {(fixtureEnabled || forceFixture) && (
        <div className="b3-cad-fixture-banner">
          fixture mode · cardiac-arrest-demo · NEXT_PUBLIC_DISPATCH_FIXTURE_MODE=1
        </div>
      )}
      <div className="b3-cad-grid">
        {/* LEFT pane — caller, state, intent, latched, queue */}
        <div className="b3-cad-left">
          <CallerCard state={state} />
          <StateBreadcrumb fsm={state.current_fsm} />
          <ActiveIntent fsm={state.current_fsm} />
          <LatchedFacts facts={state.latched_facts} />
          <PreArrivalQueue fsm={state.current_fsm} />
        </div>
        {/* RIGHT pane — transcript */}
        <div className="b3-cad-right">
          <Transcript rows={state.transcript} />
        </div>
      </div>
      <LatencyStrip latency={state.latency} />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Styles. Scoped under .b3-cad. Reuses the b3-* CSS-variable palette
// that the parent .b3-console exposes — works whether DispatchPanel is
// nested inside .b3-console or rendered standalone (we provide
// fallbacks via the `:where(.b3-cad)` block at the bottom).
// ─────────────────────────────────────────────────────────────────────

const B3_CAD_STYLES = `
.b3-cad {
  /* Re-declare the same b3-* variables locally so the panel renders
     correctly even if rendered outside the .b3-console scope. The
     parent .b3-console scope wins when both are present. */
  --b3-bg: #0a0a0b;
  --b3-panel: #121214;
  --b3-panel-2: #161618;
  --b3-border: #1f1f22;
  --b3-border-2: #2a2a2e;
  --b3-text: #e8e8ea;
  --b3-text-2: #8a8a90;
  --b3-text-3: #55555a;
  --b3-text-4: #3a3a3e;
  --b3-hot: #ff0096;
  --b3-hot-bg: rgba(255, 0, 150, 0.08);
  --b3-hot-border: rgba(255, 0, 150, 0.35);
  --b3-amber: #ffb84d;
  --b3-green: #4ade80;
  --b3-blue: #60a5fa;
  --b3-red: #ef4444;
  --b3-orange: #f97316;
  --b3-yellow: #facc15;
  --b3-mono: 'IBM Plex Mono', ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
  --b3-sans: 'IBM Plex Sans', -apple-system, system-ui, sans-serif;
  --b3-r-sm: 2px;
  --b3-r-md: 3px;
  position: relative;
  display: grid;
  grid-template-rows: auto 1fr auto;
  gap: 10px;
  background: var(--b3-bg);
  color: var(--b3-text);
  font-family: var(--b3-mono);
  font-size: 12px;
  border: 1px solid var(--b3-border);
  border-radius: var(--b3-r-md);
  padding: 12px;
  min-height: 540px;
}
.b3-cad * { box-sizing: border-box; }

/* Cardiac pulsating border — subtle, animation-honoring. */
@keyframes b3-cad-pulse {
  0%, 100% { box-shadow: 0 0 0 1px var(--b3-hot-border), 0 0 0 0 rgba(255, 0, 150, 0); }
  50%      { box-shadow: 0 0 0 1px var(--b3-hot), 0 0 18px 4px rgba(255, 0, 150, 0.18); }
}
.b3-cad-cardiac { animation: b3-cad-pulse 1.6s ease-in-out infinite; border-color: var(--b3-hot-border); }
@media (prefers-reduced-motion: reduce) { .b3-cad-cardiac { animation: none; box-shadow: 0 0 0 1px var(--b3-hot-border); } }

.b3-cad-fixture-banner {
  background: rgba(255, 184, 77, 0.06);
  color: var(--b3-amber);
  border: 1px solid rgba(255, 184, 77, 0.3);
  padding: 6px 10px; font-size: 10px; letter-spacing: 0.08em;
  text-transform: uppercase; border-radius: var(--b3-r-sm);
}

.b3-cad-grid {
  display: grid;
  grid-template-columns: 1fr 1.05fr;
  gap: 10px;
  min-height: 0;
}
@media (max-width: 1100px) { .b3-cad-grid { grid-template-columns: 1fr; } }

.b3-cad-left {
  display: grid;
  grid-template-rows: auto auto auto auto auto;
  gap: 10px;
  min-height: 0;
  align-content: start;
}
.b3-cad-right { display: grid; grid-template-rows: 1fr; min-height: 0; }

.b3-cad-dim { color: var(--b3-text-3); }

/* === CALLER CARD === */
.b3-cad-caller {
  position: relative;
  background: var(--b3-panel-2);
  border: 1px solid var(--b3-border);
  border-radius: var(--b3-r-md);
  padding-left: 6px;
  display: grid; grid-template-columns: 4px 1fr; gap: 10px;
  min-height: 110px;
}
.b3-cad-caller-band {
  border-radius: var(--b3-r-sm) 0 0 var(--b3-r-sm);
  width: 4px; background: var(--b3-text-4);
  align-self: stretch;
}
.b3-cad-crit-red    .b3-cad-caller-band { background: var(--b3-hot); box-shadow: 0 0 8px var(--b3-hot); }
.b3-cad-crit-orange .b3-cad-caller-band { background: var(--b3-orange); }
.b3-cad-crit-yellow .b3-cad-caller-band { background: var(--b3-yellow); }
.b3-cad-crit-green  .b3-cad-caller-band { background: var(--b3-green); }
.b3-cad-crit-gray   .b3-cad-caller-band { background: var(--b3-text-4); }

.b3-cad-caller-body { padding: 10px 12px 10px 4px; display: grid; gap: 8px; min-width: 0; }
.b3-cad-caller-row { display: flex; gap: 14px; align-items: baseline; flex-wrap: wrap; }
.b3-cad-caller-meta {
  font-size: 9px; letter-spacing: 0.12em; text-transform: uppercase;
  color: var(--b3-text-3);
}
.b3-cad-caller-clock { font-size: 11px; color: var(--b3-text-2); margin-left: auto; }
.b3-cad-clock-label { font-size: 9px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--b3-text-3); }
.b3-cad-clock-num { font-variant-numeric: tabular-nums; color: var(--b3-text); font-weight: 500; }

.b3-cad-caller-loc { flex: 1 1 60%; min-width: 200px; }
.b3-cad-caller-comp { flex: 1 1 35%; min-width: 140px; }
.b3-cad-field-label {
  font-size: 9px; letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--b3-text-3); margin-bottom: 2px;
}
.b3-cad-field-val {
  font-family: var(--b3-sans);
  font-size: 14px; color: var(--b3-text); font-weight: 500;
  line-height: 1.25;
}

.b3-cad-pill {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 9px; letter-spacing: 0.08em; text-transform: uppercase;
  padding: 3px 8px; border-radius: 2px; font-weight: 500;
}
.b3-cad-pill-red    { background: var(--b3-hot-bg); color: var(--b3-hot); border: 1px solid var(--b3-hot-border); }
.b3-cad-pill-blue   { background: rgba(96, 165, 250, 0.08); color: var(--b3-blue); border: 1px solid rgba(96, 165, 250, 0.3); }
.b3-cad-pill-gray   { background: transparent; color: var(--b3-text-3); border: 1px solid var(--b3-border-2); }
.b3-cad-pill-amber  { background: rgba(255, 184, 77, 0.06); color: var(--b3-amber); border: 1px solid rgba(255, 184, 77, 0.3); }

/* === STATE BREADCRUMB === */
.b3-cad-bread {
  background: var(--b3-panel);
  border: 1px solid var(--b3-border);
  border-radius: var(--b3-r-md);
  padding: 10px 12px;
  display: grid; gap: 8px;
}
.b3-cad-bread-row {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 0;
  align-items: center;
  position: relative;
}
.b3-cad-bread-step {
  position: relative;
  display: flex; flex-direction: column; align-items: flex-start;
}
.b3-cad-bread-dot {
  width: 9px; height: 9px; border-radius: 50%;
  border: 1px solid var(--b3-text-4);
  background: var(--b3-bg);
  margin-bottom: 4px;
  flex-shrink: 0;
}
.b3-cad-bread-dot-on   { border-color: var(--b3-blue); background: var(--b3-blue); }
.b3-cad-bread-dot-here { border-color: var(--b3-hot); background: var(--b3-hot); box-shadow: 0 0 6px var(--b3-hot); }
.b3-cad-bread-line {
  position: absolute; top: 4px; left: calc(50% + 6px); right: calc(-50% + 6px);
  height: 1px; background: var(--b3-border-2);
  pointer-events: none;
}
.b3-cad-bread-line-on { background: var(--b3-blue); }
.b3-cad-bread-label {
  font-size: 9px; letter-spacing: 0.04em; text-transform: uppercase;
  color: var(--b3-text-3);
  font-family: var(--b3-mono);
}
.b3-cad-bread-label-here { color: var(--b3-hot); font-weight: 500; }

.b3-cad-bread-crit {
  display: grid; grid-template-columns: auto 1fr; gap: 12px;
  align-items: center;
  padding: 6px 8px;
  background: var(--b3-hot-bg);
  border: 1px solid var(--b3-hot-border);
  border-radius: var(--b3-r-sm);
}
.b3-cad-bread-crit-tag {
  font-size: 9px; letter-spacing: 0.12em; text-transform: uppercase;
  color: var(--b3-hot); font-weight: 600;
}
.b3-cad-bread-crit-track { display: flex; gap: 18px; }
.b3-cad-bread-crit-step {
  font-size: 9px; letter-spacing: 0.06em; text-transform: uppercase;
  color: var(--b3-text-3); padding: 2px 6px;
  border: 1px solid var(--b3-border-2); border-radius: 2px;
}
.b3-cad-bread-crit-step-on { color: var(--b3-blue); border-color: rgba(96, 165, 250, 0.4); }
.b3-cad-bread-crit-step-here { color: var(--b3-hot); border-color: var(--b3-hot-border); background: rgba(255, 0, 150, 0.05); font-weight: 600; }

/* === ACTIVE INTENT === */
.b3-cad-intent {
  background: var(--b3-panel);
  border: 1px solid var(--b3-border);
  border-radius: var(--b3-r-md);
  padding: 10px 12px;
  display: grid; gap: 4px;
}
.b3-cad-intent-label {
  font-size: 9px; letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--b3-text-3);
}
.b3-cad-intent-text {
  font-family: var(--b3-sans);
  font-size: 16px; color: var(--b3-text); font-weight: 500;
  line-height: 1.3;
}
.b3-cad-intent-tag {
  font-size: 9px; color: var(--b3-text-3);
  letter-spacing: 0.04em;
}

/* === LATCHED FACTS === */
.b3-cad-latched {
  background: var(--b3-panel);
  border: 1px solid var(--b3-border);
  border-radius: var(--b3-r-md);
  padding: 10px 12px;
  display: grid; gap: 6px;
}
.b3-cad-latched-label {
  font-size: 9px; letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--b3-text-3);
}
.b3-cad-latched-empty { font-size: 11px; }
.b3-cad-latched-list { margin: 0; padding-left: 14px; display: grid; gap: 4px; }
.b3-cad-latched-item {
  font-size: 11px; color: var(--b3-text); line-height: 1.4;
}

/* === PRE-ARRIVAL QUEUE === */
.b3-cad-queue {
  background: var(--b3-panel);
  border: 1px solid var(--b3-border);
  border-radius: var(--b3-r-md);
  padding: 10px 12px;
  display: grid; gap: 6px;
}
.b3-cad-queue-label {
  font-size: 9px; letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--b3-text-3);
}
.b3-cad-queue-empty { font-size: 11px; }
.b3-cad-queue-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; }
.b3-cad-q-item {
  display: grid; grid-template-columns: 22px 1fr auto; gap: 10px;
  align-items: center;
  padding: 6px 8px; border-radius: var(--b3-r-sm);
  border: 1px solid var(--b3-border);
  font-size: 11px;
}
.b3-cad-q-n {
  width: 18px; height: 18px; border-radius: 50%;
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 10px; font-weight: 600;
  border: 1px solid var(--b3-border-2);
  color: var(--b3-text-2);
}
.b3-cad-q-text { color: var(--b3-text); }
.b3-cad-q-status {
  font-size: 9px; letter-spacing: 0.08em; text-transform: uppercase;
  font-weight: 600;
}
.b3-cad-q-done    { border-color: rgba(74, 222, 128, 0.4); background: rgba(74, 222, 128, 0.05); }
.b3-cad-q-done    .b3-cad-q-n { border-color: var(--b3-green); color: var(--b3-green); background: rgba(74, 222, 128, 0.1); }
.b3-cad-q-done    .b3-cad-q-status { color: var(--b3-green); }
.b3-cad-q-active  { border-color: var(--b3-hot-border); background: var(--b3-hot-bg); }
.b3-cad-q-active  .b3-cad-q-n { border-color: var(--b3-hot); color: var(--b3-hot); }
.b3-cad-q-active  .b3-cad-q-status { color: var(--b3-hot); }
.b3-cad-q-pending .b3-cad-q-status { color: var(--b3-amber); }
.b3-cad-q-blocked { opacity: 0.55; }
.b3-cad-q-blocked .b3-cad-q-status { color: var(--b3-text-3); }
.b3-cad-q-blocked .b3-cad-q-text { color: var(--b3-text-3); }

/* === TRANSCRIPT === */
.b3-cad-trx-wrap {
  background: var(--b3-panel);
  border: 1px solid var(--b3-border);
  border-radius: var(--b3-r-md);
  display: grid; grid-template-rows: auto 1fr;
  min-height: 0; min-width: 0;
}
.b3-cad-trx-hd {
  display: flex; align-items: baseline; justify-content: space-between;
  padding: 10px 14px; border-bottom: 1px solid var(--b3-border);
}
.b3-cad-trx-hd-t {
  font-size: 9px; letter-spacing: 0.12em; text-transform: uppercase;
  color: var(--b3-text-2); font-weight: 500;
}
.b3-cad-trx-hd-s { font-size: 10px; color: var(--b3-text-3); }
.b3-cad-trx-body {
  padding: 12px 14px;
  overflow-y: auto;
  display: grid; gap: 10px;
  min-height: 0;
  align-content: start;
  max-height: 540px;
}
.b3-cad-trx-empty {
  font-size: 11px; color: var(--b3-text-3);
  padding: 16px 4px; line-height: 1.5;
}
.b3-cad-trx-row {
  display: grid; gap: 4px;
  padding: 8px 10px;
  border-radius: var(--b3-r-sm);
  border: 1px solid var(--b3-border);
}
.b3-cad-trx-row-caller {
  background: rgba(96, 165, 250, 0.04);
  border-color: rgba(96, 165, 250, 0.15);
  margin-right: 18%;
}
.b3-cad-trx-row-disp {
  background: rgba(255, 0, 150, 0.04);
  border-color: rgba(255, 0, 150, 0.18);
  margin-left: 18%;
}
.b3-cad-trx-rowhead {
  display: flex; gap: 10px; align-items: baseline;
  font-size: 9px; letter-spacing: 0.08em; text-transform: uppercase;
}
.b3-cad-trx-roletag { font-weight: 600; padding: 2px 6px; border-radius: 2px; }
.b3-cad-trx-roletag-caller { color: var(--b3-blue); border: 1px solid rgba(96, 165, 250, 0.3); }
.b3-cad-trx-roletag-disp   { color: var(--b3-hot); border: 1px solid var(--b3-hot-border); }
.b3-cad-trx-meta { color: var(--b3-text-3); }
.b3-cad-trx-text {
  font-family: var(--b3-sans);
  font-size: 13px; line-height: 1.5; color: var(--b3-text);
}
.b3-cad-trx-hi {
  background: rgba(255, 184, 77, 0.18);
  color: var(--b3-amber);
  padding: 1px 3px; border-radius: 2px;
  font-weight: 500;
}

/* === LATENCY STRIP === */
.b3-cad-lat {
  display: flex; gap: 6px; align-items: center;
  padding: 8px 10px;
  background: var(--b3-panel);
  border: 1px solid var(--b3-border);
  border-radius: var(--b3-r-md);
  font-family: var(--b3-mono);
  flex-wrap: wrap;
}
.b3-cad-lat-pill {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 8px;
  border: 1px solid var(--b3-border-2);
  border-radius: var(--b3-r-sm);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}
.b3-cad-lat-label { font-size: 9px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--b3-text-3); }
.b3-cad-lat-num { font-weight: 500; color: var(--b3-text); }
.b3-cad-lat-green  { border-color: rgba(74, 222, 128, 0.35); background: rgba(74, 222, 128, 0.05); }
.b3-cad-lat-green  .b3-cad-lat-num { color: var(--b3-green); }
.b3-cad-lat-amber  { border-color: rgba(255, 184, 77, 0.35); background: rgba(255, 184, 77, 0.05); }
.b3-cad-lat-amber  .b3-cad-lat-num { color: var(--b3-amber); }
.b3-cad-lat-red    { border-color: var(--b3-hot-border); background: var(--b3-hot-bg); }
.b3-cad-lat-red    .b3-cad-lat-num { color: var(--b3-hot); }
.b3-cad-lat-budget {
  margin-left: auto; font-size: 9px; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--b3-text-3);
}

/* Scrollbar consistent with the parent .b3-console scope. */
.b3-cad *::-webkit-scrollbar { width: 6px; height: 6px; }
.b3-cad *::-webkit-scrollbar-track { background: transparent; }
.b3-cad *::-webkit-scrollbar-thumb { background: var(--b3-border-2); border-radius: 3px; }
.b3-cad *::-webkit-scrollbar-thumb:hover { background: var(--b3-text-4); }
`;
