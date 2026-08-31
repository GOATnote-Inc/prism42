/**
 * Fail-closed regression tests for lib/route-auth.ts — the shared
 * session-auth gate on /api/session/:id/turn, /api/livekit-token, and
 * /api/rubric/grade (P0-2, 2026-08-24 readiness audit).
 *
 * Polarity under test:
 *   - PRISM42_WORKER_KEY unset  → 503 (never silently open)
 *   - wrong / missing header    → 401
 *   - correct header            → ok
 *   - dev escape requires BOTH NODE_ENV !== "production" AND
 *     PRISM42_DEV_OPEN === "1"; production ignores PRISM42_DEV_OPEN.
 */

import { describe, it, expect, afterEach, vi } from "vitest";
import { devOpenEscape, requireWorkerKey } from "../lib/route-auth";

const KEY = "route-auth-test-key-do-not-use-in-prod";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("requireWorkerKey — fail-closed polarity", () => {
  it("PRISM42_WORKER_KEY unset → 503 fail closed", () => {
    vi.stubEnv("PRISM42_WORKER_KEY", "");
    vi.stubEnv("PRISM42_DEV_OPEN", "");
    const result = requireWorkerKey("anything");
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.status).toBe(503);
  });

  it("missing header → 401", () => {
    vi.stubEnv("PRISM42_WORKER_KEY", KEY);
    vi.stubEnv("PRISM42_DEV_OPEN", "");
    const result = requireWorkerKey(null);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.status).toBe(401);
  });

  it("wrong key → 401", () => {
    vi.stubEnv("PRISM42_WORKER_KEY", KEY);
    vi.stubEnv("PRISM42_DEV_OPEN", "");
    const result = requireWorkerKey("not-the-key");
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.status).toBe(401);
  });

  it("correct key → ok", () => {
    vi.stubEnv("PRISM42_WORKER_KEY", KEY);
    vi.stubEnv("PRISM42_DEV_OPEN", "");
    expect(requireWorkerKey(KEY).ok).toBe(true);
  });
});

describe("dev escape — dual gate", () => {
  it("NODE_ENV=production ignores PRISM42_DEV_OPEN=1 (no deployed escape)", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("PRISM42_DEV_OPEN", "1");
    expect(devOpenEscape()).toBe(false);
    vi.stubEnv("PRISM42_WORKER_KEY", "");
    const result = requireWorkerKey(null);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.status).toBe(503);
  });

  it("non-production without PRISM42_DEV_OPEN stays closed", () => {
    vi.stubEnv("NODE_ENV", "test");
    vi.stubEnv("PRISM42_DEV_OPEN", "");
    expect(devOpenEscape()).toBe(false);
  });

  it("non-production + PRISM42_DEV_OPEN=1 opens (local dev only)", () => {
    vi.stubEnv("NODE_ENV", "test");
    vi.stubEnv("PRISM42_DEV_OPEN", "1");
    expect(devOpenEscape()).toBe(true);
    vi.stubEnv("PRISM42_WORKER_KEY", "");
    expect(requireWorkerKey(null).ok).toBe(true);
  });
});
