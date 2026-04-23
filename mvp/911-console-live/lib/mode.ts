/**
 * A/B mode selection — Vercel baseline vs B300 augmented path.
 *
 * Single-variable discipline: the ONLY thing that differs between modes
 * is the rubric-grader source. Coordinator LLM, STT, TTS, and prompts are
 * identical across modes. See docs/analysis-cost-reliability.md and the
 * Phase 2-min plan for the experimental rationale.
 */

export type Mode = "vercel" | "b300";

export const DEFAULT_MODE: Mode = "vercel";

export function isMode(value: unknown): value is Mode {
  return value === "vercel" || value === "b300";
}

/**
 * Resolve mode from a Next.js searchParams object (server components) or a
 * Request URL (route handlers). Unknown or missing values fall back to
 * DEFAULT_MODE so the A/B is opt-in, never accidental.
 */
export function modeFromSearchParams(
  sp: Record<string, string | string[] | undefined> | URLSearchParams | undefined,
): Mode {
  if (!sp) return DEFAULT_MODE;
  const raw =
    sp instanceof URLSearchParams
      ? sp.get("mode")
      : Array.isArray(sp.mode)
        ? sp.mode[0]
        : sp.mode;
  return isMode(raw) ? raw : DEFAULT_MODE;
}

export function modeFromRequest(req: Request): Mode {
  const url = new URL(req.url);
  return modeFromSearchParams(url.searchParams);
}

/**
 * Label for UI pills + log rows. Deliberately short so it fits a one-line
 * header strip without truncation in the Claude-design narrow layout.
 */
export function modeLabel(m: Mode): string {
  return m === "b300" ? "MODE: B300" : "MODE: VERCEL";
}
