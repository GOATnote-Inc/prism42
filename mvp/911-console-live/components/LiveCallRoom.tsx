"use client";

// LiveKit-powered caller experience replacing the ElevenLabs widget.
// Mounts a LiveKitRoom + RoomAudioRenderer, exposes a custom call
// button + the Orb (which we keep from the ElevenLabs version).
//
// Architecture: see docs/livekit-architecture.md §6.
// The browser:
//   1. Mints a session_id via /prism42/api/session/start (existing route)
//   2. Mints a LiveKit JWT via /prism42/api/livekit-token (this PR)
//   3. Connects to wss://livekit.thegoatnote.com (the B300 pod)
//   4. The Python agent worker on the pod auto-dispatches into the
//      same room and starts the AgentSession
//   5. Audio flows over WebRTC; structured turn events flow over
//      LiveKit data channels (Phase 3a uses the existing SSE stream
//      to the dispatcher panels — data-channel bridge lands in 3b)

import { useCallback, useEffect, useState } from "react";
import {
  LiveKitRoom,
  RoomAudioRenderer,
  useConnectionState,
  useLocalParticipant,
  useRoomContext,
  useTracks,
} from "@livekit/components-react";
import { ConnectionState, RoomEvent, Track } from "livekit-client";
import { Orb, type OrbAgentState } from "./Orb";

interface CallerProps {
  sessionId: string | null;
}

export function LiveCallRoom({ sessionId }: CallerProps) {
  const [token, setToken] = useState<string | null>(null);
  const [serverUrl, setServerUrl] = useState<string | null>(null);
  const [phase, setPhase] = useState<
    "idle" | "minting" | "connecting" | "live" | "ended" | "error"
  >("idle");
  const [errorText, setErrorText] = useState<string | null>(null);

  const startCall = useCallback(async () => {
    if (!sessionId) {
      setErrorText("Session id not ready — refresh the page.");
      setPhase("error");
      return;
    }
    setErrorText(null);
    setPhase("minting");
    try {
      // 1. Get the microphone permission ahead of room-join so the
      //    user-gesture click actually buys us a track. Browsers
      //    require the gesture chain to remain intact.
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        stream.getTracks().forEach((t) => t.stop());
      } catch (err) {
        setErrorText(
          err instanceof Error
            ? `Microphone permission denied: ${err.message}`
            : "Microphone permission denied",
        );
        setPhase("error");
        return;
      }

      // 2. Mint a JWT scoped to this session_id room.
      const r = await fetch("/prism42/api/livekit-token", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId }),
      });
      if (!r.ok) {
        const body = await r.text();
        throw new Error(`token mint ${r.status}: ${body.slice(0, 160)}`);
      }
      const data = (await r.json()) as { token: string; livekit_url: string };
      setToken(data.token);
      setServerUrl(data.livekit_url);
      setPhase("connecting");
    } catch (err) {
      setErrorText(err instanceof Error ? err.message : String(err));
      setPhase("error");
    }
  }, [sessionId]);

  const endCall = useCallback(() => {
    setPhase("ended");
    setToken(null);
    setServerUrl(null);
  }, []);

  // Pre-connect state — show idle hero with the call button.
  if (phase === "idle" || phase === "minting" || phase === "ended" || phase === "error") {
    return (
      <PreConnectHero
        phase={phase}
        errorText={errorText}
        sessionId={sessionId}
        onStart={startCall}
      />
    );
  }

  // Connected state — wrap children in the LiveKitRoom provider.
  if (!token || !serverUrl) {
    return <PreConnectHero phase="minting" errorText={null} sessionId={sessionId} onStart={startCall} />;
  }

  return (
    <LiveKitRoom
      token={token}
      serverUrl={serverUrl}
      audio={true}
      video={false}
      connect={true}
      onDisconnected={endCall}
      onError={(e) => {
        setErrorText(e.message);
        setPhase("error");
      }}
    >
      <RoomAudioRenderer />
      <ActiveCallHero onEnd={endCall} sessionId={sessionId} />
    </LiveKitRoom>
  );
}

function PreConnectHero({
  phase,
  errorText,
  sessionId,
  onStart,
}: {
  phase: "idle" | "minting" | "ended" | "error";
  errorText: string | null;
  sessionId: string | null;
  onStart: () => void;
}) {
  const buttonLabel =
    phase === "minting"
      ? "Connecting…"
      : phase === "ended"
        ? "Call again"
        : "Speak to the dispatcher";

  return (
    <div className="caller-hero">
      <div className="caller-orb-frame">
        <Orb agentState={null} colors={["#5fb7ff", "#ff5f6d"]} size={280} />
      </div>
      <div className="caller-cta">
        <h1>Live 911 Dispatcher Simulation</h1>
        <p className="caller-subtitle">
          A public demonstration of GOATnote Prism42 — a 14-specialist
          dispatcher stack on Claude Opus 4.7, voice via LiveKit +
          Cartesia + Deepgram, cross-vendor-graded in real time.
          Self-hosted on a Blackwell GPU.{" "}
          <strong>Synthetic fixtures only.</strong> If this were a real
          emergency, you would hang up and dial 911 on a working phone.
        </p>
        <button
          className="caller-button"
          onClick={onStart}
          disabled={phase === "minting" || !sessionId}
        >
          {buttonLabel}
        </button>
        <div className="caller-hint">
          {phase === "idle" && (
            <span>
              Say anything a 911 caller might: a symptom, an address,
              or a name. Try it.
            </span>
          )}
          {errorText && <span className="bad">Error: {errorText}</span>}
        </div>
      </div>
    </div>
  );
}

function ActiveCallHero({
  onEnd,
  sessionId,
}: {
  onEnd: () => void;
  sessionId: string | null;
}) {
  const room = useRoomContext();
  const connectionState = useConnectionState();
  const { localParticipant } = useLocalParticipant();
  const tracks = useTracks([Track.Source.Microphone], { onlySubscribed: false });

  // Map LiveKit state to OrbAgentState. The agent's audio track tells
  // us when it's speaking; the local track presence + audioLevel tells
  // us when the caller is speaking.
  const [orbState, setOrbState] = useState<OrbAgentState>(null);

  useEffect(() => {
    if (!room) return;
    function onActiveSpeakers(speakers: Array<{ identity: string }>): void {
      // If any remote (= the agent) is speaking → "talking".
      const agentSpeaking = speakers.some(
        (p) => p.identity !== localParticipant?.identity,
      );
      const callerSpeaking = speakers.some(
        (p) => p.identity === localParticipant?.identity,
      );
      if (agentSpeaking) setOrbState("talking");
      else if (callerSpeaking) setOrbState("listening");
      else setOrbState(null);
    }
    room.on(RoomEvent.ActiveSpeakersChanged, onActiveSpeakers);
    return () => {
      room.off(RoomEvent.ActiveSpeakersChanged, onActiveSpeakers);
    };
  }, [room, localParticipant]);

  const live = connectionState === ConnectionState.Connected;

  return (
    <div className="caller-hero">
      <div className="caller-orb-frame">
        <Orb agentState={orbState} colors={["#5fb7ff", "#ff5f6d"]} size={280} />
      </div>
      <div className="caller-cta">
        <h1>Live 911 Dispatcher Simulation</h1>
        <p className="caller-subtitle">
          {live ? (
            <>
              You are connected. Speak normally — the dispatcher will
              respond. The orb pulses blue when you're being heard,
              red when the dispatcher is speaking.
            </>
          ) : (
            <>Connecting to the LiveKit room…</>
          )}
        </p>
        <button className="caller-button live" onClick={onEnd}>
          End the call
        </button>
        <div className="caller-hint">
          <span className="mono dim" style={{ fontSize: 11 }}>
            session · {sessionId?.slice(0, 8) ?? "—"} · state ·{" "}
            {connectionState} · tracks · {tracks.length}
          </span>
        </div>
      </div>
    </div>
  );
}
