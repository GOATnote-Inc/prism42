import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST } from "../app/prism42/api/rubric/grade-local/route";
import { recordGrade } from "../lib/session-store";
import type { PsapTurn } from "../lib/types";

vi.mock("../lib/session-store", () => ({ recordGrade: vi.fn() }));

const KEY = "local-rubric-test-key-do-not-use-in-prod";
const ENDPOINT = "https://rubric.example.invalid/v1/chat/completions";
const turn: PsapTurn = {
  agent: "psap-dispatch",
  turn_id: "turn-test",
  action: "speak",
  content: "Please stay on the line.",
  rationale: "Synthetic test turn",
  cites: [],
  confidence: 1,
  confidence_basis: "default",
  self_verify: { checks: [], all_passed: true },
};
const criteria = {
  R1_clinical_accuracy: 1,
  R2_scope_adherence: 1,
  R3_safety_preservation: 1,
  R4_clarity_for_caller: 1,
  R5_protocol_adherence: 1,
};
const fetchMock = vi.fn();

function request(key?: string, body = JSON.stringify({
  session_id: "session-test",
  turn,
  caller_text: "Synthetic caller",
  phase: "dispatch",
})) {
  return new NextRequest("https://console.example.invalid/prism42/api/rubric/grade-local", {
    method: "POST",
    headers: key === undefined ? {} : { "x-prism42-worker-key": key },
    body,
  });
}

beforeEach(() => {
  vi.stubEnv("NODE_ENV", "production");
  vi.stubEnv("PRISM42_DEV_OPEN", "");
  vi.stubEnv("PRISM42_WORKER_KEY", KEY);
  vi.stubEnv("PRISM42_B300_RUBRIC_URL", ENDPOINT);
  vi.stubEnv("PRISM42_B300_RUBRIC_TOKEN", "synthetic-backend-token");
  fetchMock.mockResolvedValue(Response.json({
    choices: [{ message: { content: JSON.stringify({ criteria, rationales: {} }) } }],
  }));
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.resetAllMocks();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("local rubric route access control", () => {
  it.each([undefined, "wrong-key", `${KEY}-suffix`])(
    "rejects unauthorized header %s before body parsing, inference, or storage",
    async (key) => {
      const req = request(key, "not json");
      const parse = vi.spyOn(req, "json");
      const response = await POST(req);
      expect(response.status).toBe(401);
      expect(parse).not.toHaveBeenCalled();
      expect(fetchMock).not.toHaveBeenCalled();
      expect(recordGrade).not.toHaveBeenCalled();
    },
  );

  it("fails closed when the server key is missing", async () => {
    vi.stubEnv("PRISM42_WORKER_KEY", "");
    const response = await POST(request(KEY));
    expect(response.status).toBe(503);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(recordGrade).not.toHaveBeenCalled();
  });

  it("does not honor the local development escape in production", async () => {
    vi.stubEnv("PRISM42_DEV_OPEN", "1");
    const response = await POST(request());
    expect(response.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(recordGrade).not.toHaveBeenCalled();
  });

  it("grades and records a turn for a valid key", async () => {
    const response = await POST(request(KEY));
    expect(response.status).toBe(200);
    const grade = await response.json();
    expect(grade).toMatchObject({ turn_id: turn.turn_id, criteria, self_grade_flag: false });
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith(ENDPOINT, expect.objectContaining({ method: "POST" }));
    expect(recordGrade).toHaveBeenCalledExactlyOnceWith("session-test", grade);
  });

  it("preserves the explicit local development escape", async () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("PRISM42_DEV_OPEN", "1");
    vi.stubEnv("PRISM42_WORKER_KEY", "");
    const response = await POST(request());
    expect(response.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(recordGrade).toHaveBeenCalledOnce();
  });

  it("preserves backend-unavailable behavior for an authorized caller", async () => {
    fetchMock.mockResolvedValue(Response.json({ error: "unavailable" }, { status: 503 }));
    const response = await POST(request(KEY));
    expect(response.status).toBe(503);
    expect(await response.json()).toMatchObject({ error: "b300_rubric_unavailable", fallback: "hosted" });
    expect(recordGrade).not.toHaveBeenCalled();
  });
});
