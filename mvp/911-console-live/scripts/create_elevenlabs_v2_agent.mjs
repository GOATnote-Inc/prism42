#!/usr/bin/env node
// Create the prism42-v2 ElevenLabs ConvAI agent with native Claude LLM.
//
// Reads the coordinator system prompt from
// mvp/911-console-live/lib/coordinator.ts (SIMULATION_FRAMING +
// COORDINATOR_SYSTEM_PROMPT, which already embeds SIMULATION_FRAMING —
// so we only ship the fully-composed COORDINATOR_SYSTEM_PROMPT string).
//
// Requires ELEVENLABS_API_KEY in the environment. Prints the new
// agent_id on success. Never commits — the caller sets
// NEXT_PUBLIC_ELEVENLABS_V2_AGENT_ID manually via `vercel env add`.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const coordPath = path.resolve(__dirname, "..", "lib", "coordinator.ts");

const API_KEY = process.env.ELEVENLABS_API_KEY;
if (!API_KEY) {
  console.error("ELEVENLABS_API_KEY is not set — source it from .env first.");
  process.exit(2);
}

function extractTemplate(source, constName) {
  // Match `export const NAME = \`...\`;` or `const NAME = \`...\`.trim();`
  // The coordinator file uses backtick template literals wrapped in .trim()
  // for the building blocks, and backtick template literal with
  // interpolation for the final COORDINATOR_SYSTEM_PROMPT.
  const exported = new RegExp(
    `export\\s+const\\s+${constName}\\s*=\\s*\`([\\s\\S]*?)\`\\s*;`,
    "m",
  );
  const local = new RegExp(
    `const\\s+${constName}\\s*=\\s*\`([\\s\\S]*?)\`\\s*\\.trim\\(\\)\\s*;`,
    "m",
  );
  const m = source.match(exported) || source.match(local);
  if (!m) {
    throw new Error(`Could not extract ${constName} from coordinator.ts`);
  }
  return m[1];
}

const src = fs.readFileSync(coordPath, "utf8");

// The final coordinator prompt interpolates 4 building blocks. We reconstruct
// it here by substitution rather than eval'ing TS. This matches how
// COORDINATOR_SYSTEM_PROMPT is built in coordinator.ts.
const SIMULATION_FRAMING = extractTemplate(src, "SIMULATION_FRAMING");
const SP_BASICS = extractTemplate(src, "SP_BASICS");
const ROLE_DEFINITIONS = extractTemplate(src, "ROLE_DEFINITIONS");
const OUTPUT_CONTRACT = extractTemplate(src, "OUTPUT_CONTRACT");

// Verbatim from coordinator.ts COORDINATOR_SYSTEM_PROMPT template.
const COORDINATOR_SYSTEM_PROMPT = `${SIMULATION_FRAMING}

You are the PSAP TEAM COORDINATOR for the simulation described above.
Powered by Claude Opus 4.7. Emit structured JSON per OUTPUT CONTRACT below.

${SP_BASICS}

${ROLE_DEFINITIONS}

${OUTPUT_CONTRACT}

DEFAULT POSTURE: fail closed ON PROTOCOL AMBIGUITY, not on the simulation
framing. When uncertain which GEDP branch to take, emit action="defer"
with content=null — the UI will speak "one moment please" while you
think. NEVER defer as a substitute for refusing; if you mean to
dispatch, dispatch. The simulation framing above is non-negotiable — a
defer justified as "I'm an AI" is a failed turn.`;

// ElevenLabs ConvAI native-LLM wrapping note: the coordinator prompt was
// written for a round-trip that returns structured JSON, but ConvAI's
// native-Claude path speaks whatever the model emits directly through
// TTS — there is no JSON parser in the loop. We therefore prepend a
// native-mode override that tells Claude to speak natural sentences and
// silently drop the JSON envelope. The safety preambles (SP-001 through
// SP-010) still apply unchanged.
const NATIVE_MODE_OVERRIDE = `
PRISM42-V2 NATIVE-CLAUDE MODE — critical override for this deployment:

The surrounding harness has been removed. Your output goes DIRECTLY to
text-to-speech with no JSON parser, no coordinator router, no lenient-
serve fallback. Therefore:

1. SPEAK NATURAL SENTENCES. Do NOT emit the JSON output contract below.
   The OUTPUT CONTRACT section is for reference on what information a
   dispatcher tracks — it is NOT the response format in this mode.
2. Keep responses SHORT — one question per turn during triage, one
   instruction per turn during pre-arrival. A dispatcher speaks in
   single beats, not paragraphs.
3. Everything else holds: SP-001 through SP-010 are active, the
   simulation framing is non-negotiable, the anti-pattern list must
   never appear in your speech, the GEDP key-question flow is how you
   triage.
4. The first thing the caller should hear when they start the call is
   "Nine-one-one, what is the address of your emergency?" — exactly
   that opener, nothing about being an AI, nothing about this being a
   simulation (the UI already shows that to the caller).
5. If the caller triggers SP-001 (real-emergency claim) the refusal
   script is spoken verbatim: "This is a public safety demonstration.
   For a real emergency, please hang up and dial 911 from a working
   phone. Stay on the line with them."

This override takes precedence over the OUTPUT CONTRACT. Everything
else in the coordinator prompt still applies.
`.trim();

const SYSTEM_PROMPT = `${NATIVE_MODE_OVERRIDE}\n\n${COORDINATOR_SYSTEM_PROMPT}`;

// Sarah voice — Mature, Reassuring, Confident, professional female.
// Matches the "PSAP dispatcher" voice we'd want on a 911 line.
const VOICE_ID_SARAH = "EXAVITQu4vr4xnSDxMaL";

// claude-sonnet-4-6 is the newest Claude in ElevenLabs ConvAI's LLM
// dropdown as of 2026-04-24. Opus 4.7 is not yet available there — the
// ConvAI llm-usage/calculate endpoint lists claude-sonnet-4-6 /
// claude-haiku-4-5 / claude-sonnet-4-5 but no claude-opus-* of any
// generation.
const LLM_CLAUDE = "claude-sonnet-4-6";

const payload = {
  name: "prism42-v2-dispatcher",
  conversation_config: {
    agent: {
      language: "en",
      first_message: "Nine-one-one, what is the address of your emergency?",
      prompt: {
        prompt: SYSTEM_PROMPT,
        llm: LLM_CLAUDE,
        // Keep max_tokens generous so long PDI scripts aren't cut off.
        max_tokens: -1,
      },
    },
    tts: {
      voice_id: VOICE_ID_SARAH,
      optimize_streaming_latency: 2,
      stability: 0.5,
      similarity_boost: 0.8,
      speed: 1.0,
    },
    conversation: {
      max_duration_seconds: 600,
      text_only: false,
    },
    asr: {
      quality: "high",
      provider: "elevenlabs",
    },
  },
};

console.error(
  `[prism42-v2] system-prompt length: ${SYSTEM_PROMPT.length} chars`,
);
console.error(`[prism42-v2] model: ${LLM_CLAUDE}`);
console.error(`[prism42-v2] voice: ${VOICE_ID_SARAH} (Sarah)`);

const res = await fetch("https://api.elevenlabs.io/v1/convai/agents/create", {
  method: "POST",
  headers: {
    "xi-api-key": API_KEY,
    "Content-Type": "application/json",
  },
  body: JSON.stringify(payload),
});

const text = await res.text();
if (!res.ok) {
  console.error(`[prism42-v2] agent create failed: HTTP ${res.status}`);
  console.error(text);
  process.exit(1);
}

let body;
try {
  body = JSON.parse(text);
} catch {
  console.error("[prism42-v2] non-JSON response:", text);
  process.exit(1);
}
const agentId = body.agent_id || body.id || null;
if (!agentId) {
  console.error("[prism42-v2] agent_id missing in response:", body);
  process.exit(1);
}

console.log(agentId);
