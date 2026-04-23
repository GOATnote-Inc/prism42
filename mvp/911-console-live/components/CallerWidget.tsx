"use client";

// ElevenLabs Conversational AI widget. Embeds the public
// <elevenlabs-convai> custom element with the dispatcher's current
// session id passed through as a dynamic variable.
//
// Widget docs (fetched 2026-04-23):
// https://elevenlabs.io/docs/eleven-agents/customization/widget
//
// Widget setup requires:
//   1. Create a PUBLIC ConvAI agent in the ElevenLabs dashboard
//      (Security → Authentication disabled; Advanced tab).
//   2. Point its Custom LLM → Endpoint URL at
//      https://<your-vercel-domain>/prism42/api/chat/completions
//   3. Allowlist www.thegoatnote.com (and any preview domains) in the
//      agent's Security tab to restrict embed origin.
//   4. Copy the agent id into NEXT_PUBLIC_ELEVENLABS_AGENT_ID.
//   5. In the ElevenLabs agent's system prompt (dashboard), include
//      the string `Session-ID: {{session_id}}` — our custom-LLM
//      endpoint parses it out of messages[0].content to route turns
//      to the right dispatcher console. (Phase 2b refinement: use
//      ElevenLabs' server-side dynamic variables to pass via a
//      dedicated header instead of a templated system-prompt
//      token.)

import Script from "next/script";
import { useEffect, useRef } from "react";

const WIDGET_SCRIPT = "https://unpkg.com/@elevenlabs/convai-widget-embed";

type ConvaiWidgetAttrs = {
  "agent-id": string;
  "dynamic-variables"?: string;
  variant?: string;
  "avatar-orb-color-1"?: string;
  "avatar-orb-color-2"?: string;
};

// Extend JSX so TypeScript accepts the custom element.
declare module "react" {
  namespace JSX {
    interface IntrinsicElements {
      "elevenlabs-convai": React.DetailedHTMLProps<
        React.HTMLAttributes<HTMLElement> & Partial<ConvaiWidgetAttrs>,
        HTMLElement
      >;
    }
  }
}

export function CallerWidget({ sessionId }: { sessionId: string | null }) {
  const agentId = process.env.NEXT_PUBLIC_ELEVENLABS_AGENT_ID;
  const ref = useRef<HTMLElement | null>(null);

  // Keep the widget in sync with the current session_id. ElevenLabs
  // renders the widget once; changing `dynamic-variables` after mount
  // is not guaranteed to update. For now we remount via the key prop.
  useEffect(() => {
    // no-op; the keyed remount is the update mechanism.
  }, [sessionId]);

  if (!agentId) {
    return (
      <div className="panel">
        <h2>Voice call</h2>
        <div className="dim">
          ElevenLabs agent not configured. Set{" "}
          <code>NEXT_PUBLIC_ELEVENLABS_AGENT_ID</code> in your Vercel
          project env (or local <code>.env.local</code>) and redeploy.
          Until then, the dispatcher console runs in transcript-only
          mode — use the test curl in the README to feed turns.
        </div>
      </div>
    );
  }

  if (!sessionId) {
    return (
      <div className="panel">
        <h2>Voice call</h2>
        <div className="dim">
          Establishing session — widget will appear once the session id
          is minted.
        </div>
      </div>
    );
  }

  const dynamicVars = JSON.stringify({ session_id: sessionId });

  return (
    <div className="panel">
      <h2>Voice call</h2>
      <Script
        src={WIDGET_SCRIPT}
        strategy="afterInteractive"
        type="text/javascript"
      />
      <div style={{ minHeight: 120 }}>
        <elevenlabs-convai
          key={sessionId}
          ref={ref}
          agent-id={agentId}
          dynamic-variables={dynamicVars}
          avatar-orb-color-1="#5fb7ff"
          avatar-orb-color-2="#ff5f6d"
        />
      </div>
      <div className="mono dim" style={{ fontSize: 11, marginTop: 8 }}>
        agent · {agentId.slice(0, 8)}…
      </div>
    </div>
  );
}
