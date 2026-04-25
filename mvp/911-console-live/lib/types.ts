// TypeScript mirror of schemas/psap-turn.schema.json. The schema is the
// source of truth — this file is a hand-written TS projection kept in
// lockstep. When the schema changes, mirror the change here and re-run
// the schema-validator CI check. Zod parsing in session-store.ts is the
// runtime gate that enforces the shape on every turn.

export type PsapAgent =
  | "psap-intake"
  | "psap-triage"
  | "psap-dispatch"
  | "psap-pdi"
  | "psap-handoff"
  | "psap-safety-monitor"
  | "psap-ohca-detector"
  | "psap-intent-verifier"
  | "psap-rubric-live"
  | "psap-rubric-live-shim"
  | "psap-auditor"
  | "psap-qi-reviewer"
  | "psap-team-coordinator"
  | "prism-ci-safety-expert"
  | "prism-release-gate";

export type PsapAction =
  | "speak"
  | "defer"
  | "refuse"
  | "escalate"
  | "handoff"
  | "end";

export type ConfidenceBasis =
  | "citation"
  | "inference"
  | "uncertain"
  | "default"
  | "blocked";

export type AlertKind =
  | "real-emergency-claim"
  | "ohca-signal"
  | "contraindicated-instruction"
  | "phi-disclosure"
  | "caller-distress"
  | "intent-ambiguous"
  | "verify-failed"
  | "latency-breach"
  | "injection-blocked";

export type AlertSeverity = "info" | "medium" | "high" | "critical";

export interface PsapAlert {
  kind: AlertKind;
  severity: AlertSeverity;
  detail: string;
  source_agent: PsapAgent;
}

export interface SelfVerifyCheck {
  name: string;
  passed: boolean;
  note?: string;
}

export interface PsapPhase {
  name:
    | "intake"
    | "triage"
    | "dispatch"
    | "pdi"
    | "handoff"
    | "closed";
  kq_index?: number;
  determinant?: string;
}

export interface PsapTurn {
  agent: PsapAgent;
  turn_id: string;
  action: PsapAction;
  content: string | null;
  rationale: string;
  cites: string[];
  confidence: number;
  confidence_basis: ConfidenceBasis;
  self_verify: {
    checks: SelfVerifyCheck[];
    all_passed: boolean;
  };
  refuse?: {
    sp_reference: string;
    next_step_for_caller: string;
  };
  next_phase?: PsapPhase;
  alerts?: PsapAlert[];
  debug?: Record<string, unknown>;
}

export interface RubricGrade {
  turn_id: string;
  criteria: {
    R1_clinical_accuracy: number;
    R2_scope_adherence: number;
    R3_safety_preservation: number;
    R4_clarity_for_caller: number;
    R5_protocol_adherence: number;
  };
  weighted_score: number;
  rationales: Record<string, string>;
  model_used: string;
  self_grade_flag: boolean;
  flag_reason?: string;
  latency_ms: number;
  cites: string[];
}

// ElevenLabs custom-LLM request body. Minimal subset per
// docs/anthropic-elevenlabs-agent-bp-2026-04-21.md §3.1.
export interface CustomLLMRequest {
  model?: string;
  messages: Array<{
    role: "system" | "user" | "assistant" | "tool";
    content: string;
    tool_calls?: unknown[];
    tool_call_id?: string;
  }>;
  stream?: boolean;
  temperature?: number;
  max_tokens?: number;
  tools?: unknown[];
  // ElevenLabs-specific pass-throughs we look for:
  user?: string; // sometimes populated with conversation id
}

export interface OpenAIChunk {
  id: string;
  object: "chat.completion.chunk";
  created: number;
  model: string;
  choices: Array<{
    index: number;
    delta: { content?: string; role?: "assistant" };
    finish_reason: null | "stop" | "length" | "tool_calls";
  }>;
}

// Session-store shape. In Phase 2a this is in-memory (per-process).
// Phase 2b swaps the driver for Upstash Redis without changing callers.
export interface SessionRecord {
  id: string;
  created_at: number; // epoch ms
  last_touched_at: number;
  phase: PsapPhase;
  turns: PsapTurn[];
  grades: RubricGrade[];
  alerts: PsapAlert[];
  // Anthropic Managed Agents session id, set after first coordinator call.
  anthropic_session_id?: string;
  // Coordinator thread id, if multi-thread delegation is available.
  anthropic_thread_id?: string;
  // Subscribers: UI consoles listening via /api/session/:id/stream.
  subscriber_count: number;
}

export type SessionEventKind =
  | "turn"
  | "grade"
  | "alert"
  | "phase_change"
  | "session_closed"
  | "heartbeat";

export interface SessionEvent<T = unknown> {
  kind: SessionEventKind;
  at: number; // epoch ms
  payload: T;
}
