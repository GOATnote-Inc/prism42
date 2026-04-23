// Comparison-log writer — appends one JSONL row per (turn, seed, mode) to
// findings/comparison.jsonl. Schema per the approved Phase 2-min plan,
// Module C. Server-side only (Node fs); not callable from browser.
//
// The log is the primary evidence for the Vercel ↔ B300 A/B experiment.
// Every row captures: mode, turn context, both rubric sources' scores and
// latencies, absolute + relative latency deltas, per-criterion deltas, and
// a failure_type tag assigned at write-time.

import { appendFile, mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import type { Mode } from "./mode";
import type { PsapAction, RubricGrade } from "./types";

export type FailureType =
  | "none"
  | "disagreement"
  | "latency"
  | "drift"
  | "timeout"
  | "error";

/**
 * Absolute threshold on per-criterion deltas to trigger `disagreement`.
 * Criteria are 0.0-1.0 floats in this repo (unlike the approved-plan
 * 0-5 framing). |Δ| > 0.2 ≈ > 1 point on a 0-5 scale.
 */
const DISAGREEMENT_DELTA = 0.2;
/**
 * |mean delta| across all 5 criteria; if this is exceeded on the same
 * scenario across multiple seeds, the aggregator will tag those rows
 * `drift` in a post-pass. At write-time we only tag per-row values.
 */
const DRIFT_MEAN_DELTA = 0.3;

export interface ComparisonRowInput {
  mode: Mode;
  turn_id: string;
  scenario_id?: string;
  seed?: number;
  iteration_id?: number;
  timestamp?: string;
  coordinator_model: string;
  rubric_primary?: RubricGrade | null;
  rubric_shadow?: RubricGrade | null;
  rubric_primary_source: string;
  rubric_shadow_source: string;
  rubric_primary_error?: string | null;
  rubric_shadow_error?: string | null;
  action: PsapAction;
  severity?: string | null;
  self_verify_all_passed: boolean;
}

interface ComparisonRow {
  mode: Mode;
  turn_id: string;
  scenario_id: string | null;
  seed: number | null;
  iteration_id: number | null;
  timestamp: string;
  coordinator_model: string;
  rubric_source_primary: string;
  rubric_source_shadow: string;
  rubric_primary_latency_ms: number | null;
  rubric_shadow_latency_ms: number | null;
  latency_delta_ms: number | null;
  latency_ratio: number | null;
  rubric_primary_scores: RubricGrade["criteria"] | null;
  rubric_shadow_scores: RubricGrade["criteria"] | null;
  rubric_primary_weighted: number | null;
  rubric_shadow_weighted: number | null;
  score_delta_max: number | null;
  score_delta_mean: number | null;
  action: PsapAction;
  severity: string | null;
  self_verify_all_passed: boolean;
  failure_type: FailureType;
  rubric_primary_error: string | null;
  rubric_shadow_error: string | null;
}

function pairDeltas(
  primary: RubricGrade["criteria"] | null | undefined,
  shadow: RubricGrade["criteria"] | null | undefined,
): { max: number | null; mean: number | null } {
  if (!primary || !shadow) return { max: null, mean: null };
  const keys = Object.keys(primary) as (keyof RubricGrade["criteria"])[];
  if (!keys.length) return { max: null, mean: null };
  const deltas = keys.map((k) => Math.abs(primary[k] - shadow[k]));
  const max = Math.max(...deltas);
  const mean = deltas.reduce((a, b) => a + b, 0) / deltas.length;
  return { max, mean };
}

function classify(input: ComparisonRowInput, deltaMax: number | null, deltaMean: number | null): FailureType {
  if (input.rubric_primary_error) {
    if (/timeout|abort/i.test(input.rubric_primary_error)) return "timeout";
    return "error";
  }
  if (!input.rubric_primary) {
    // primary fell back with no error string — treat as error for safety
    return "error";
  }
  if (deltaMax !== null && deltaMax > DISAGREEMENT_DELTA) return "disagreement";
  if (deltaMean !== null && deltaMean > DRIFT_MEAN_DELTA) return "drift";
  if (
    input.rubric_primary &&
    input.rubric_shadow &&
    input.rubric_primary.latency_ms >= input.rubric_shadow.latency_ms
  ) {
    return "latency";
  }
  return "none";
}

export function buildComparisonRow(input: ComparisonRowInput): ComparisonRow {
  const pLat = input.rubric_primary?.latency_ms ?? null;
  const sLat = input.rubric_shadow?.latency_ms ?? null;
  const latency_delta_ms = pLat !== null && sLat !== null ? pLat - sLat : null;
  const latency_ratio =
    pLat !== null && sLat !== null && sLat > 0 ? pLat / sLat : null;
  const { max: score_delta_max, mean: score_delta_mean } = pairDeltas(
    input.rubric_primary?.criteria,
    input.rubric_shadow?.criteria,
  );
  const failure_type = classify(input, score_delta_max, score_delta_mean);
  return {
    mode: input.mode,
    turn_id: input.turn_id,
    scenario_id: input.scenario_id ?? null,
    seed: input.seed ?? null,
    iteration_id: input.iteration_id ?? null,
    timestamp: input.timestamp ?? new Date().toISOString(),
    coordinator_model: input.coordinator_model,
    rubric_source_primary: input.rubric_primary_source,
    rubric_source_shadow: input.rubric_shadow_source,
    rubric_primary_latency_ms: pLat,
    rubric_shadow_latency_ms: sLat,
    latency_delta_ms,
    latency_ratio,
    rubric_primary_scores: input.rubric_primary?.criteria ?? null,
    rubric_shadow_scores: input.rubric_shadow?.criteria ?? null,
    rubric_primary_weighted: input.rubric_primary?.weighted_score ?? null,
    rubric_shadow_weighted: input.rubric_shadow?.weighted_score ?? null,
    score_delta_max,
    score_delta_mean,
    action: input.action,
    severity: input.severity ?? null,
    self_verify_all_passed: input.self_verify_all_passed,
    failure_type,
    rubric_primary_error: input.rubric_primary_error ?? null,
    rubric_shadow_error: input.rubric_shadow_error ?? null,
  };
}

const DEFAULT_LOG_PATH = resolve(
  process.cwd(),
  process.env.PRISM42_COMPARISON_LOG_PATH ?? "findings/comparison.jsonl",
);

export async function appendComparisonRow(
  input: ComparisonRowInput,
  options?: { path?: string },
): Promise<ComparisonRow> {
  const row = buildComparisonRow(input);
  const path = options?.path ?? DEFAULT_LOG_PATH;
  await mkdir(dirname(path), { recursive: true });
  await appendFile(path, JSON.stringify(row) + "\n", "utf8");
  return row;
}

// Helper for the fixture harness + route handlers.
export async function logParallelGrade(opts: {
  mode: Mode;
  turn_id: string;
  scenario_id?: string;
  seed?: number;
  iteration_id?: number;
  coordinator_model: string;
  action: PsapAction;
  severity?: string | null;
  self_verify_all_passed: boolean;
  primary: { source: string; grade: RubricGrade | null; error: string | null };
  shadow: { source: string; grade: RubricGrade | null; error: string | null };
  path?: string;
}): Promise<ComparisonRow> {
  return appendComparisonRow(
    {
      mode: opts.mode,
      turn_id: opts.turn_id,
      scenario_id: opts.scenario_id,
      seed: opts.seed,
      iteration_id: opts.iteration_id,
      coordinator_model: opts.coordinator_model,
      action: opts.action,
      severity: opts.severity,
      self_verify_all_passed: opts.self_verify_all_passed,
      rubric_primary: opts.primary.grade,
      rubric_primary_source: opts.primary.source,
      rubric_primary_error: opts.primary.error,
      rubric_shadow: opts.shadow.grade,
      rubric_shadow_source: opts.shadow.source,
      rubric_shadow_error: opts.shadow.error,
    },
    { path: opts.path },
  );
}
