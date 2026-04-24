"use client";

// B300 design primitives — ported from /tmp/b300_design/named/01-Primitives.jsx.
// Pure presentation; no business logic. Used by the /prism42/livekit page.
//
// All components are SSR-safe: the canvas-based Soundbar animations
// only run inside useEffect so Next.js renders fine.

import { useEffect, useRef, useState } from "react";

interface SoundbarProps {
  bars?: number;
  height?: number;
  seed?: number;
  active?: boolean;
  color?: string;
  idle?: boolean;
  speed?: number;
}

export function Soundbar({
  bars = 24,
  height = 20,
  seed = 1,
  active = true,
  color,
  idle = false,
  speed = 80,
}: SoundbarProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const rafRef = useRef<number>(0);
  const t0 = useRef<number>(0);

  useEffect(() => {
    t0.current = performance.now();
    const c = canvasRef.current;
    if (!c) return;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const w = c.clientWidth;
    const h = c.clientHeight;
    c.width = w * dpr;
    c.height = h * dpr;
    ctx.scale(dpr, dpr);

    const accent = color || (active ? "#ff0096" : "#55555a");
    const tickW = 2;
    const gap = (w - bars * tickW) / Math.max(1, bars - 1);

    const draw = () => {
      ctx.clearRect(0, 0, w, h);
      const now = performance.now();
      const t = (now - t0.current) / (active ? speed : 400);
      for (let i = 0; i < bars; i++) {
        const phase = i * 0.45 + seed * 3.7;
        const s1 = Math.sin(t * 0.09 + phase) * 0.5 + 0.5;
        const s2 = Math.sin(t * 0.21 + phase * 1.3) * 0.5 + 0.5;
        const s3 = Math.sin(t * 0.37 + phase * 0.7) * 0.5 + 0.5;
        let amp = s1 * 0.55 + s2 * 0.3 + s3 * 0.15;
        if (idle) amp = 0.12 + amp * 0.08;
        else if (!active) amp = 0.08 + amp * 0.15;
        const barH = Math.max(1, amp * (h - 2));
        const x = i * (tickW + gap);
        const y = (h - barH) / 2;
        ctx.fillStyle = accent;
        ctx.globalAlpha = active ? 0.9 : 0.35;
        ctx.fillRect(x, y, tickW, barH);
      }
      rafRef.current = requestAnimationFrame(draw);
    };
    draw();
    return () => cancelAnimationFrame(rafRef.current);
  }, [bars, seed, active, color, idle, speed]);

  return (
    <canvas
      ref={canvasRef}
      style={{ width: "100%", height: `${height}px`, display: "block" }}
    />
  );
}

interface DualSoundbarProps {
  bars?: number;
  height?: number;
  seed?: number;
  callerActive?: boolean;
  aiActive?: boolean;
}

export function DualSoundbar({
  bars = 48,
  height = 28,
  seed = 1,
  callerActive = true,
  aiActive = false,
}: DualSoundbarProps) {
  return (
    <div style={{ display: "grid", gap: "2px" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "8px",
        }}
      >
        <span
          style={{
            fontSize: "9px",
            color: "var(--b3-text-3)",
            width: "28px",
          }}
        >
          CLR
        </span>
        <div style={{ flex: 1 }}>
          <Soundbar
            bars={bars}
            height={height / 2}
            seed={seed}
            active={callerActive}
            color="#ff0096"
          />
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
        <span
          style={{
            fontSize: "9px",
            color: "var(--b3-text-3)",
            width: "28px",
          }}
        >
          AI
        </span>
        <div style={{ flex: 1 }}>
          <Soundbar
            bars={bars}
            height={height / 2}
            seed={seed + 100}
            active={aiActive}
            color="#e8e8ea"
          />
        </div>
      </div>
    </div>
  );
}

interface LatencyMeterProps {
  ms: number;
  budget?: number;
  label?: string;
}

export function LatencyMeter({ ms, budget = 400, label }: LatencyMeterProps) {
  const pct = Math.min(100, (ms / budget) * 100);
  const status: "green" | "amber" | "hot" =
    ms < budget * 0.5 ? "green" : ms < budget * 0.85 ? "amber" : "hot";
  const colors: Record<typeof status, string> = {
    green: "#4ade80",
    amber: "#ffb84d",
    hot: "#ff0096",
  };
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr auto",
        gap: "8px",
        alignItems: "center",
        fontSize: "10px",
      }}
    >
      <div style={{ display: "grid", gap: "3px" }}>
        {label && (
          <span
            style={{
              color: "var(--b3-text-3)",
              fontSize: "9px",
              letterSpacing: "0.05em",
              textTransform: "uppercase",
            }}
          >
            {label}
          </span>
        )}
        <div
          style={{
            height: "3px",
            background: "var(--b3-panel-2)",
            borderRadius: "1px",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              width: `${pct}%`,
              height: "100%",
              background: colors[status],
            }}
          />
        </div>
      </div>
      <span
        className="b3-mono-num"
        style={{
          color: colors[status],
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {ms}ms
      </span>
    </div>
  );
}

interface ElapsedProps {
  start: number;
  suffix?: string;
}

export function Elapsed({ start, suffix = "" }: ElapsedProps) {
  const [n, setN] = useState(0);
  useEffect(() => {
    const tick = () => setN(Math.floor((Date.now() - start) / 1000));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [start]);
  const mm = String(Math.floor(n / 60)).padStart(2, "0");
  const ss = String(n % 60).padStart(2, "0");
  return (
    <span className="b3-mono-num">
      {mm}:{ss}
      {suffix}
    </span>
  );
}

interface SparklineProps {
  data: number[];
  width?: number;
  height?: number;
  color?: string;
}

export function Sparkline({
  data,
  width = 80,
  height = 16,
  color = "#ff0096",
}: SparklineProps) {
  if (data.length === 0) return null;
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;
  const pts = data
    .map((d, i) => {
      const x = (i / Math.max(1, data.length - 1)) * width;
      const y = height - ((d - min) / range) * height;
      return `${x},${y}`;
    })
    .join(" ");
  return (
    <svg width={width} height={height} style={{ display: "block" }}>
      <polyline fill="none" stroke={color} strokeWidth="1" points={pts} />
    </svg>
  );
}
