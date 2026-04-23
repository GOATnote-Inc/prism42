#!/usr/bin/env node
// Fixture A/B harness — single-variable Vercel ↔ B300 comparison on the
// 42-scenario red-team fixture, 4 turns per scenario, 3 seeds per turn.
// Logs one JSONL row per (mode, turn, seed) to findings/comparison.jsonl.
//
// Usage:
//   node scripts/run_fixture_compare.mjs --mode=vercel --seeds=1,2,3
//   node scripts/run_fixture_compare.mjs --mode=b300  --seeds=1,2,3
//
// Env vars:
//   OPENAI_API_KEY           — required; hosted grader (shadow in b300 mode, primary in vercel mode)
//   PRISM42_B300_RUBRIC_URL  — required when --mode=b300; points at vLLM OpenAI-compat endpoint
//   PRISM42_B300_RUBRIC_TOKEN — optional bearer token for the B300 endpoint
//   PRISM42_ITERATION_ID     — optional integer tagged on every row
//   PRISM42_COMPARISON_LOG_PATH — override the output path
//
// The script NEVER calls the coordinator LLM — inputs are pre-written
// canonical turns so the rubric-grader is the only variable.

import { readFileSync, existsSync, mkdirSync, appendFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { loadFixture } from "./load_fixture.mjs";
import { canonicalTurnsFor } from "./canonical-turns.mjs";
import { RUBRIC_SYSTEM_PROMPT, weightedScore } from "./rubric-shared.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(__dirname, "..", "..", "..");
const APP_ROOT = resolve(__dirname, "..");
const FIXTURE_PATH = resolve(
  REPO_ROOT,
  "corpus/red-team/psap-fixtures-v0.1.yaml",
);
const DEFAULT_LOG_PATH = resolve(APP_ROOT, "findings", "comparison.jsonl");
const HOSTED_PRIMARY_MODEL = "gpt-5-5";
const HOSTED_FALLBACK_MODEL = "gpt-5-4";
const HOSTED_TIMEOUT_MS = 8000;
const B300_TIMEOUT_MS = 1500;

// ---- arg parsing --------------------------------------------------------

function parseArgs(argv) {
  const out = { mode: null, seeds: [1, 2, 3], path: null, limit: null };
  for (const arg of argv.slice(2)) {
    if (arg.startsWith("--mode=")) out.mode = arg.slice(7);
    else if (arg.startsWith("--seeds="))
      out.seeds = arg.slice(8).split(",").map((s) => Number(s.trim()));
    else if (arg.startsWith("--path=")) out.path = arg.slice(7);
    else if (arg.startsWith("--limit=")) out.limit = Number(arg.slice(8));
  }
  if (out.mode !== "vercel" && out.mode !== "b300") {
    throw new Error(
      `--mode must be "vercel" or "b300"; got ${JSON.stringify(out.mode)}`,
    );
  }
  return out;
}

// ---- grader calls -------------------------------------------------------

async function gradeHosted(turn, scenario, model = HOSTED_PRIMARY_MODEL) {
  const apiKey = process.env.OPENAI_API_KEY;
  if (!apiKey) throw new Error("OPENAI_API_KEY not set");
  const start = Date.now();
  const userMsg = JSON.stringify({
    agent_turn: turn,
    caller_text: scenario.caller_script_summary ?? "",
    session_phase: "dispatch",
    gedp_section: scenario.gedp_anchor,
  });
  const body = {
    model,
    messages: [
      { role: "system", content: RUBRIC_SYSTEM_PROMPT },
      { role: "user", content: userMsg },
    ],
    response_format: { type: "json_object" },
  };
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), HOSTED_TIMEOUT_MS);
  let resp;
  try {
    resp = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timer);
  }
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(`hosted ${model} http ${resp.status}: ${text.slice(0, 200)}`);
  }
  const completion = await resp.json();
  const raw = completion.choices?.[0]?.message?.content ?? "{}";
  const parsed = JSON.parse(raw);
  return {
    turn_id: turn.turn_id,
    criteria: parsed.criteria,
    rationales: parsed.rationales ?? {},
    cites: parsed.cites ?? [],
    weighted_score: weightedScore(parsed.criteria),
    model_used: model,
    self_grade_flag: false,
    latency_ms: Date.now() - start,
  };
}

async function gradeHostedWithFallback(turn, scenario) {
  try {
    return await gradeHosted(turn, scenario, HOSTED_PRIMARY_MODEL);
  } catch (primaryErr) {
    try {
      return await gradeHosted(turn, scenario, HOSTED_FALLBACK_MODEL);
    } catch {
      throw primaryErr;
    }
  }
}

async function gradeB300(turn, scenario) {
  const url = process.env.PRISM42_B300_RUBRIC_URL;
  if (!url) throw new Error("PRISM42_B300_RUBRIC_URL not set");
  const start = Date.now();
  const userMsg = JSON.stringify({
    agent_turn: turn,
    caller_text: scenario.caller_script_summary ?? "",
    session_phase: "dispatch",
    gedp_section: scenario.gedp_anchor,
  });
  const body = {
    model: "local_llama70b_nvfp4",
    messages: [
      { role: "system", content: RUBRIC_SYSTEM_PROMPT },
      { role: "user", content: userMsg },
    ],
    response_format: { type: "json_object" },
    max_tokens: 600,
    temperature: 0,
  };
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), B300_TIMEOUT_MS);
  let resp;
  try {
    resp = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${process.env.PRISM42_B300_RUBRIC_TOKEN ?? "unset"}`,
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timer);
  }
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(`b300 http ${resp.status}: ${text.slice(0, 200)}`);
  }
  const completion = await resp.json();
  const raw = completion.choices?.[0]?.message?.content ?? "{}";
  const parsed = JSON.parse(raw);
  // Validate all five criteria present.
  const required = [
    "R1_clinical_accuracy",
    "R2_scope_adherence",
    "R3_safety_preservation",
    "R4_clarity_for_caller",
    "R5_protocol_adherence",
  ];
  for (const k of required) {
    if (typeof parsed.criteria?.[k] !== "number") {
      throw new Error(`b300 missing criterion ${k}`);
    }
  }
  return {
    turn_id: turn.turn_id,
    criteria: parsed.criteria,
    rationales: parsed.rationales ?? {},
    cites: parsed.cites ?? [],
    weighted_score: weightedScore(parsed.criteria),
    model_used: "local_llama70b_nvfp4",
    self_grade_flag: false,
    latency_ms: Date.now() - start,
  };
}

// ---- classification + row build (mirrors lib/comparison-log.ts) ---------

const DISAGREEMENT_DELTA = 0.2;
const DRIFT_MEAN_DELTA = 0.3;

function pairDeltas(p, s) {
  if (!p || !s) return { max: null, mean: null };
  const keys = Object.keys(p);
  if (!keys.length) return { max: null, mean: null };
  const deltas = keys.map((k) => Math.abs(p[k] - s[k]));
  return {
    max: Math.max(...deltas),
    mean: deltas.reduce((a, b) => a + b, 0) / deltas.length,
  };
}

function classify(primary, primaryError, max, mean) {
  if (primaryError) {
    if (/timeout|abort/i.test(primaryError)) return "timeout";
    return "error";
  }
  if (!primary) return "error";
  if (max !== null && max > DISAGREEMENT_DELTA) return "disagreement";
  if (mean !== null && mean > DRIFT_MEAN_DELTA) return "drift";
  return "none";
}

function buildRow({
  mode,
  turn,
  scenario,
  seed,
  primary,
  shadow,
  primaryError,
  shadowError,
}) {
  const pLat = primary?.latency_ms ?? null;
  const sLat = shadow?.latency_ms ?? null;
  const latency_delta_ms = pLat !== null && sLat !== null ? pLat - sLat : null;
  const latency_ratio =
    pLat !== null && sLat !== null && sLat > 0 ? pLat / sLat : null;
  const { max, mean } = pairDeltas(primary?.criteria, shadow?.criteria);
  const hasLatencyLoss =
    !primaryError &&
    primary &&
    shadow &&
    primary.latency_ms >= shadow.latency_ms;
  let failure_type = classify(primary, primaryError, max, mean);
  if (failure_type === "none" && hasLatencyLoss) failure_type = "latency";
  return {
    mode,
    turn_id: turn.turn_id,
    scenario_id: scenario.id,
    seed,
    iteration_id: process.env.PRISM42_ITERATION_ID
      ? Number(process.env.PRISM42_ITERATION_ID)
      : null,
    timestamp: new Date().toISOString(),
    coordinator_model: "claude-opus-4-7",
    rubric_source_primary:
      mode === "b300" ? "local_llama70b_nvfp4" : "hosted_gpt55",
    rubric_source_shadow:
      mode === "b300" ? "hosted_gpt55" : "local_llama70b_nvfp4",
    rubric_primary_latency_ms: pLat,
    rubric_shadow_latency_ms: sLat,
    latency_delta_ms,
    latency_ratio,
    rubric_primary_scores: primary?.criteria ?? null,
    rubric_shadow_scores: shadow?.criteria ?? null,
    rubric_primary_weighted: primary?.weighted_score ?? null,
    rubric_shadow_weighted: shadow?.weighted_score ?? null,
    score_delta_max: max,
    score_delta_mean: mean,
    action: turn.action,
    severity: null,
    self_verify_all_passed: turn.self_verify.all_passed,
    failure_type,
    rubric_primary_error: primaryError,
    rubric_shadow_error: shadowError,
    turn_quality: turn.quality,
  };
}

// ---- main ---------------------------------------------------------------

async function gradePair(mode, turn, scenario) {
  // In vercel mode: primary=hosted, shadow=b300 (shadow fire-and-forget; OK to fail).
  // In b300 mode: primary=b300, shadow=hosted.
  const primaryFn = mode === "b300" ? gradeB300 : gradeHostedWithFallback;
  const shadowFn = mode === "b300" ? gradeHostedWithFallback : gradeB300;
  const [primaryRes, shadowRes] = await Promise.allSettled([
    primaryFn(turn, scenario),
    shadowFn(turn, scenario),
  ]);
  const primary = primaryRes.status === "fulfilled" ? primaryRes.value : null;
  const primaryError =
    primaryRes.status === "rejected" ? String(primaryRes.reason?.message ?? primaryRes.reason) : null;
  const shadow = shadowRes.status === "fulfilled" ? shadowRes.value : null;
  const shadowError =
    shadowRes.status === "rejected" ? String(shadowRes.reason?.message ?? shadowRes.reason) : null;
  return { primary, primaryError, shadow, shadowError };
}

async function main() {
  const args = parseArgs(process.argv);
  const path = args.path ?? process.env.PRISM42_COMPARISON_LOG_PATH ?? DEFAULT_LOG_PATH;
  mkdirSync(dirname(path), { recursive: true });
  if (!existsSync(path)) {
    appendFileSync(path, "", "utf8"); // touch
  }

  const scenarios = loadFixture(FIXTURE_PATH);
  let turns = canonicalTurnsFor(scenarios);
  if (args.limit) turns = turns.slice(0, args.limit);

  const scenarioById = Object.fromEntries(scenarios.map((s) => [s.id, s]));
  console.log(
    `[fixture] mode=${args.mode} turns=${turns.length} seeds=[${args.seeds.join(",")}] out=${path}`,
  );

  let ok = 0;
  let fail = 0;
  for (const turn of turns) {
    const scenario = scenarioById[turn.scenario_id];
    for (const seed of args.seeds) {
      try {
        const { primary, primaryError, shadow, shadowError } =
          await gradePair(args.mode, turn, scenario);
        const row = buildRow({
          mode: args.mode,
          turn,
          scenario,
          seed,
          primary,
          primaryError,
          shadow,
          shadowError,
        });
        appendFileSync(path, JSON.stringify(row) + "\n", "utf8");
        ok++;
      } catch (err) {
        fail++;
        console.error(
          `[fixture] ${turn.turn_id} seed=${seed} failed: ${String(err?.message ?? err)}`,
        );
      }
    }
  }
  console.log(`[fixture] done ok=${ok} fail=${fail} file=${path}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
