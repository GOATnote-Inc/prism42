"use client";

// Animated voice-agent orb — visual state machine for call activity.
// Inspired by the ElevenLabs UI Orb (ui.elevenlabs.io) but implemented
// with CSS conic gradients + transform animations so we don't pull in
// Tailwind. The props shape matches the ElevenLabs contract so a later
// migration to the CLI-installed version is drop-in compatible.
//
// States:
//   idle       — slow ambient rotation, low saturation
//   listening  — faster rotation, cool blue breathing (agent hearing caller)
//   talking    — fast rotation, warm amber ripple (agent speaking)
//   thinking   — medium rotation, white-hot pulse (coordinator resolving a turn)

import { useEffect, useRef } from "react";

export type OrbAgentState = null | "thinking" | "listening" | "talking";

export interface OrbProps {
  agentState?: OrbAgentState;
  colors?: [string, string];
  /**
   * Function that returns the current input (mic) volume 0-1. Called
   * each RAF tick; the orb scales subtly with caller loudness.
   */
  getInputVolume?: () => number;
  /**
   * Function that returns the current output (TTS) volume 0-1.
   */
  getOutputVolume?: () => number;
  className?: string;
  size?: number;
}

export function Orb({
  agentState = null,
  colors = ["#5fb7ff", "#ff5f6d"],
  getInputVolume,
  getOutputVolume,
  className,
  size = 220,
}: OrbProps) {
  const ref = useRef<HTMLDivElement | null>(null);
  const animRef = useRef<number | undefined>(undefined);

  // Gentle RAF loop that scales the orb with active volume. Idle when
  // no volume callback is provided — the CSS keyframes handle ambient
  // motion.
  useEffect(() => {
    if (!getInputVolume && !getOutputVolume) return;
    let running = true;
    const tick = () => {
      if (!running) return;
      const el = ref.current;
      if (el) {
        const input = getInputVolume?.() ?? 0;
        const output = getOutputVolume?.() ?? 0;
        const active = Math.max(input, output);
        // scale 1.00 → 1.10 on the most active sound
        const scale = 1 + active * 0.1;
        el.style.setProperty("--orb-volume-scale", String(scale));
      }
      animRef.current = requestAnimationFrame(tick);
    };
    animRef.current = requestAnimationFrame(tick);
    return () => {
      running = false;
      if (animRef.current) cancelAnimationFrame(animRef.current);
    };
  }, [getInputVolume, getOutputVolume]);

  const state = agentState ?? "idle";

  return (
    <div
      ref={ref}
      className={`orb orb-${state} ${className ?? ""}`}
      style={
        {
          ["--orb-size" as string]: `${size}px`,
          ["--orb-color-a" as string]: colors[0],
          ["--orb-color-b" as string]: colors[1],
        } as React.CSSProperties
      }
      aria-hidden
    >
      <div className="orb-core" />
      <div className="orb-halo" />
      <div className="orb-ring" />
    </div>
  );
}
