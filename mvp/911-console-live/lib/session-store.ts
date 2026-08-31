// In-memory session registry + pub/sub. Phase 2a only — one Vercel
// serverless instance per session for demo use. Phase 2b: swap for
// Upstash Redis (list per session + pub/sub channel per session).
// Callers see the same interface.

import type {
  PsapAlert,
  PsapPhase,
  PsapTurn,
  RubricGrade,
  SessionEvent,
  SessionEventKind,
  SessionRecord,
} from "./types";

type Listener = (event: SessionEvent) => void;

const SESSIONS = new Map<string, SessionRecord>();
const LISTENERS = new Map<string, Set<Listener>>();
const SESSION_TTL_MS = 60 * 60 * 1000; // 1 h

// Session ids double as LiveKit room names, so they must be
// unguessable — use the Web Crypto CSPRNG (available in Node >= 19
// and edge runtimes; every consumer of this module runs on Node).
function newSessionId(): string {
  return globalThis.crypto.randomUUID();
}

export function createSession(): SessionRecord {
  const now = Date.now();
  const rec: SessionRecord = {
    id: newSessionId(),
    created_at: now,
    last_touched_at: now,
    phase: { name: "intake" },
    turns: [],
    grades: [],
    alerts: [],
    subscriber_count: 0,
  };
  SESSIONS.set(rec.id, rec);
  LISTENERS.set(rec.id, new Set());
  gcOldSessions();
  return rec;
}

export function getSession(id: string): SessionRecord | undefined {
  const rec = SESSIONS.get(id);
  if (rec) rec.last_touched_at = Date.now();
  return rec;
}

/**
 * Adopt an externally-minted session id (e.g. from a LiveKit room name)
 * and create the in-memory record if missing. Used by the SSE route +
 * the worker's turn-ingest endpoint so a Vercel-instance cold start
 * doesn't 404 a live LiveKit voice call. Phase 2b replaces this with
 * Upstash Redis backed shared state.
 */
export function attachToSession(id: string): SessionRecord {
  const existing = SESSIONS.get(id);
  if (existing) {
    existing.last_touched_at = Date.now();
    return existing;
  }
  const now = Date.now();
  const rec: SessionRecord = {
    id,
    created_at: now,
    last_touched_at: now,
    phase: { name: "intake" },
    turns: [],
    grades: [],
    alerts: [],
    subscriber_count: 0,
  };
  SESSIONS.set(id, rec);
  LISTENERS.set(id, new Set());
  gcOldSessions();
  return rec;
}

export function requireSession(id: string): SessionRecord {
  const rec = getSession(id);
  if (!rec) throw new Error(`session not found: ${id}`);
  return rec;
}

export function subscribe(id: string, fn: Listener): () => void {
  const set = LISTENERS.get(id);
  if (!set) throw new Error(`session not found: ${id}`);
  set.add(fn);
  const rec = SESSIONS.get(id);
  if (rec) rec.subscriber_count = set.size;
  return () => {
    set.delete(fn);
    const r = SESSIONS.get(id);
    if (r) r.subscriber_count = set.size;
  };
}

function publish<T>(id: string, kind: SessionEventKind, payload: T) {
  const set = LISTENERS.get(id);
  if (!set) return;
  const evt: SessionEvent<T> = { kind, at: Date.now(), payload };
  for (const fn of set) {
    try {
      fn(evt);
    } catch {
      // A single subscriber crash must not take down the broadcast.
    }
  }
}

export function recordTurn(id: string, turn: PsapTurn): void {
  const rec = requireSession(id);
  rec.turns.push(turn);
  if (turn.next_phase) rec.phase = turn.next_phase;
  if (turn.alerts?.length) rec.alerts.push(...turn.alerts);
  publish(id, "turn", turn);
  if (turn.next_phase) publish(id, "phase_change", turn.next_phase);
  for (const a of turn.alerts ?? []) publish(id, "alert", a);
}

export function recordGrade(id: string, grade: RubricGrade): void {
  const rec = requireSession(id);
  rec.grades.push(grade);
  publish(id, "grade", grade);
}

export function recordAlert(id: string, alert: PsapAlert): void {
  const rec = requireSession(id);
  rec.alerts.push(alert);
  publish(id, "alert", alert);
}

export function closeSession(id: string, reason: string): void {
  const rec = SESSIONS.get(id);
  if (!rec) return;
  rec.phase = { name: "closed" };
  publish(id, "session_closed", { reason });
  // Keep in memory briefly so late subscribers can see the close event.
  setTimeout(() => {
    SESSIONS.delete(id);
    LISTENERS.delete(id);
  }, 30_000);
}

function gcOldSessions() {
  const cutoff = Date.now() - SESSION_TTL_MS;
  for (const [id, rec] of SESSIONS) {
    if (rec.last_touched_at < cutoff) {
      SESSIONS.delete(id);
      LISTENERS.delete(id);
    }
  }
}

// Heartbeat ticker — keeps SSE proxies from cutting idle connections.
// Fires every 15 s, broadcasts to every active session.
let HEARTBEAT_TIMER: ReturnType<typeof setInterval> | undefined;
export function ensureHeartbeat() {
  if (HEARTBEAT_TIMER) return;
  HEARTBEAT_TIMER = setInterval(() => {
    for (const id of SESSIONS.keys()) publish(id, "heartbeat", null);
  }, 15_000);
  // Don't pin the Node process on Vercel — the heartbeat is nice-to-
  // have, not load-bearing.
  if (typeof HEARTBEAT_TIMER.unref === "function") HEARTBEAT_TIMER.unref();
}
export function stopHeartbeat() {
  if (HEARTBEAT_TIMER) {
    clearInterval(HEARTBEAT_TIMER);
    HEARTBEAT_TIMER = undefined;
  }
}

export function _reset_for_tests() {
  SESSIONS.clear();
  LISTENERS.clear();
  stopHeartbeat();
}

export function listSessionIdsForDebug(): string[] {
  return [...SESSIONS.keys()];
}
