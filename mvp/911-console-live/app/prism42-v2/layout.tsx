import type { Metadata } from "next";

// /prism42-v2 is the "native Claude" demo-safe plan-C path: ElevenLabs
// ConvAI with the native claude-sonnet-4-6 LLM integration — no custom
// /chat/completions hop, no harness, no JSON envelope. The coordinator
// prompt is baked into the agent's platform config; Claude speaks
// directly through ElevenLabs TTS. See:
//   - /prism42 (plan A) — external LLM via /prism42/api/chat/completions
//   - /prism42/livekit (plan B) — LiveKit + B300 self-hosted stack
//   - /prism42-v2 (plan C) — this route, ElevenLabs + native Claude
//
// Root layout's simulation-banner still renders above this subtree.

export const metadata: Metadata = {
  title: "Prism42 v2 · Native Claude voice",
  description:
    "Plan-C 911-dispatcher simulation — ElevenLabs ConvAI with native Claude integration. Synthetic-fixture demo. Not a medical device. Not a substitute for 911.",
};

export default function PrismV2Layout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}
