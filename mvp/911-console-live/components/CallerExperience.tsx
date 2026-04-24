"use client";

// Voice-first hero replacing the floating <elevenlabs-convai> widget.
// Built on @elevenlabs/react v1.2.1 useConversation hook. Full control
// over the call button, the orb, the transcript — no ElevenLabs
// "engage in meaningful conversations" marketing modal.
//
// Flow:
//   1. Page mounts → we mint a session id from /prism42/api/session/start
//   2. Render the Orb + the "Call the dispatcher" button
//   3. On click → conversation.startSession({agentId, dynamicVariables:
//      {session_id}}) kicks off the WebRTC call
//   4. onMessage / isSpeaking / isListening → drive the Orb's
//      agentState and append transcript entries
//   5. onDisconnect → end the session, the dispatcher panels continue
//      showing the post-mortem

import { useCallback, useEffect, useRef, useState } from "react";
import { useConversation } from "@elevenlabs/react";
import { Orb, type OrbAgentState } from "./Orb";

export interface CallerExperienceProps {
  sessionId: string | null;
  agentId: string | undefined;
}

export function CallerExperience({
  sessionId,
  agentId,
}: CallerExperienceProps) {
  const [phase, setPhase] = useState<
    "idle" | "connecting" | "live" | "ending" | "ended" | "error"
  >("idle");
  const [errorText, setErrorText] = useState<string | null>(null);

  const conversation = useConversation({
    onConnect: () => setPhase("live"),
    onDisconnect: () => setPhase("ended"),
    onError: (err: unknown) => {
      const msg =
        typeof err === "string"
          ? err
          : err instanceof Error
            ? err.message
            : "unknown error";
      setErrorText(msg);
      setPhase("error");
    },
  });

  const isSpeaking = conversation?.isSpeaking ?? false;
  // status is one of: "connecting" | "connected" | "disconnected"
  const status = conversation?.status ?? "disconnected";

  const agentState: OrbAgentState = isSpeaking
    ? "talking"
    : status === "connected"
      ? "listening"
      : phase === "connecting"
        ? "thinking"
        : null;

  const startCall = useCallback(async () => {
    if (!agentId) {
      setErrorText(
        "NEXT_PUBLIC_ELEVENLABS_AGENT_ID is not set in the deploy environment",
      );
      setPhase("error");
      return;
    }
    if (!sessionId) {
      setErrorText("Session id not ready — refresh the page.");
      setPhase("error");
      return;
    }
    setErrorText(null);
    setPhase("connecting");
    try {
      await conversation.startSession({
        agentId,
        dynamicVariables: {
          session_id: sessionId,
        },
      } as Parameters<typeof conversation.startSession>[0]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setErrorText(msg);
      setPhase("error");
    }
  }, [agentId, sessionId, conversation]);

  const endCall = useCallback(async () => {
    setPhase("ending");
    try {
      await conversation.endSession();
    } catch {
      // ignore — onDisconnect will fire either way
    }
  }, [conversation]);

  // Auto-request microphone permission on mount so the first click
  // doesn't get stuck in a browser permission modal mid-call.
  const permRequestedRef = useRef(false);
  useEffect(() => {
    if (permRequestedRef.current) return;
    if (typeof navigator === "undefined" || !navigator.mediaDevices) return;
    permRequestedRef.current = true;
    navigator.mediaDevices
      .getUserMedia({ audio: true })
      .then((stream) => {
        // We don't use the stream — ElevenLabs's SDK grabs its own on
        // startSession. We just want the permission prompt handled
        // ahead of time so the conversation flows smoothly.
        stream.getTracks().forEach((t) => t.stop());
      })
      .catch(() => {
        // Ignore — user can grant on first call attempt.
      });
  }, []);

  const buttonLabel =
    phase === "connecting"
      ? "Connecting…"
      : phase === "live"
        ? "End the call"
        : phase === "ending"
          ? "Ending…"
          : phase === "ended"
            ? "Call again"
            : "Speak to the dispatcher";

  const live = status === "connected" || phase === "live";

  return (
    <div className="caller-hero">
      <div className="caller-orb-frame">
        <Orb
          agentState={agentState}
          colors={["#5fb7ff", "#ff5f6d"]}
          size={280}
        />
      </div>
      <div className="caller-cta">
        <h1>Live 911 Dispatcher Simulation</h1>
        <p className="caller-subtitle">
          A public demonstration of GOATnote Prism42 — a 14-agent PSAP
          stack built on Claude Opus 4.7 and ElevenLabs voice I/O,
          cross-vendor-graded in real time.{" "}
          <strong>Synthetic fixtures only.</strong> If this were a
          real emergency, you would hang up and dial 911 on a working
          phone.
        </p>
        <button
          className={`caller-button ${live ? "live" : ""}`}
          onClick={live ? endCall : startCall}
          disabled={phase === "connecting" || phase === "ending" || !agentId}
        >
          {buttonLabel}
        </button>
        <div className="caller-hint">
          {!agentId && (
            <span className="bad">
              Voice agent not configured yet (missing
              NEXT_PUBLIC_ELEVENLABS_AGENT_ID)
            </span>
          )}
          {agentId && phase === "idle" && (
            <span>
              Say anything a 911 caller might: a symptom, an address,
              or a name. Try it.
            </span>
          )}
          {phase === "live" && (
            <span>
              You are connected. Speak normally — the dispatcher will
              respond.
            </span>
          )}
          {errorText && (
            <span className="bad">Error: {errorText}</span>
          )}
        </div>
      </div>
    </div>
  );
}
