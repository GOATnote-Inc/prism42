// Thin Anthropic Managed Agents wrapper.
//
// Two responsibilities:
// 1. Lazy-import the SDK (so the build step never fails if the package
//    is absent during local scaffolding before `npm install`).
// 2. Hold the coordinator-agent id + beta headers in one place so the
//    API routes don't duplicate the knobs.
//
// Per CLAUDE.md §8: no temperature/top_p/top_k/budget_tokens on 4.7.
// Per docs/anthropic-elevenlabs-agent-bp-2026-04-21.md §3.2: we translate
// Anthropic content_block_delta events into OpenAI chunks — the translator
// lives in the /api/chat/completions route, not here.

// 2026-04-24 demo-day swap HISTORY: briefly switched default to Sonnet 4.6
// for lower TTFT (~800ms-1.5s vs Opus 4.7's ~6.8s), but Sonnet 4.6 produces
// refusal-adjacent prose ("I'm not able to diagnose...", "I can't advise on
// medications...", and in some runs the full "I am an AI, I cannot provide
// advice or diagnosis, please contact emergency services" verbatim) even
// with the simulation preamble. The lenient-serve path in
// app/prism42/api/chat/completions/route.ts passes that content straight
// to ElevenLabs TTS.
//
// 2026-04-24 REVERT to Opus 4.7 as the default — reliability > latency for
// a demo where the caller hears the refusal. Sonnet 4.6 stays available
// via PRISM42_ANTHROPIC_MODEL env override once we re-test with the
// hardened prompt in lib/coordinator.ts.
//
// Trade-off acknowledged: TTFT reverts to ~6-7s on cold sessions. Mitigate
// with "please hold" pre-roll on the widget side, not here.
export const ANTHROPIC_MODEL_OPUS_47 = "claude-opus-4-7";
export const ANTHROPIC_MODEL_SONNET_46 = "claude-sonnet-4-6";

// Env override: PRISM42_ANTHROPIC_MODEL=claude-sonnet-4-6 switches back to
// Sonnet. Any other value must be a valid Anthropic model id; we don't
// validate here — if the id is bad, messages.stream returns 400 and the
// route falls through to SAFE_FALLBACK_CONTENT ("One moment please").
export const ANTHROPIC_MODEL =
  process.env.PRISM42_ANTHROPIC_MODEL || ANTHROPIC_MODEL_OPUS_47;

// Beta header set per CLAUDE.md §8. We intentionally omit the callable-
// agents beta — it's silently stripped on this workspace.
export const ANTHROPIC_BETA_HEADERS = [
  "managed-agents-2026-04-01",
];

// Default coordinator. Overridden by env — the registered agent id lands
// in agents/psap-manifest.yaml after scripts/register_psap_agents.py
// --commit. For demo mode without a live agent, the code falls back to
// direct messages.stream calls against ANTHROPIC_MODEL (see
// makeCoordinatorFallback below).
export function getCoordinatorAgentId(): string | undefined {
  return process.env.PRISM42_COORDINATOR_AGENT_ID || undefined;
}

export async function getAnthropicClient() {
  // Lazy import so `npm run build` works even in environments where the
  // SDK hasn't been installed yet (e.g., scaffolding commit CI).
  const mod = await import("@anthropic-ai/sdk");
  const Anthropic = mod.default;
  return new Anthropic({
    apiKey: process.env.ANTHROPIC_API_KEY,
    defaultHeaders: {
      "anthropic-beta": ANTHROPIC_BETA_HEADERS.join(","),
    },
  });
}

// Used when PRISM42_COORDINATOR_AGENT_ID is unset — we fall back to a
// direct messages.stream call with the coordinator's system prompt
// baked in. Same voice-facing behavior; loses the Managed Agents
// session durability. Useful for local dev before registration.
export interface CoordinatorFallbackArgs {
  systemPrompt: string;
  messages: Array<{ role: "user" | "assistant"; content: string }>;
  maxTokens?: number;
  onDeltaText?: (text: string) => void;
}

export async function coordinatorFallbackStream(
  args: CoordinatorFallbackArgs,
): Promise<{ fullText: string; stopReason: string | null }> {
  const client = await getAnthropicClient();
  let fullText = "";
  let stopReason: string | null = null;

  // messages.stream is present on both Managed Agents and base Messages.
  // No temperature / top_p / top_k / budget_tokens — 4.7 rejects all.
  const stream = await client.messages.stream({
    model: ANTHROPIC_MODEL,
    max_tokens: args.maxTokens ?? 1200,
    system: args.systemPrompt,
    messages: args.messages,
  });

  for await (const event of stream) {
    if (
      event.type === "content_block_delta" &&
      event.delta.type === "text_delta"
    ) {
      const text = event.delta.text;
      fullText += text;
      args.onDeltaText?.(text);
    }
    if (event.type === "message_delta" && event.delta.stop_reason) {
      stopReason = event.delta.stop_reason;
    }
  }
  return { fullText, stopReason };
}
