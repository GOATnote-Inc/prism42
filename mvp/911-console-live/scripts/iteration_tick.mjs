#!/usr/bin/env node
// One tick of the Phase 2-min iteration loop (Module F). Called every
// ~15 minutes by ScheduleWakeup, up to MAX_ITERATIONS total.
//
// What one tick does:
//   1. Read findings/iteration-log.jsonl → find last iteration_id.
//   2. If iteration_id >= MAX_ITERATIONS, emit final-summary row + exit 10
//      (signal to the outer ScheduleWakeup to stop).
//   3. Run compare_metrics.mjs on current findings/comparison.jsonl.
//   4. Inspect failure_type counts; if any category has hits, emit a
//      hotspot row to findings/iteration-log.jsonl naming the axes.
//   5. L3 regression guard: read previous iteration summary; if the new
//      agreement_rate dropped > 2pp, emit regression row, exit 11.
//   6. Otherwise emit ok row with next recommended action + reschedule.
//
// This script is pure analysis — it does NOT re-run the fixture harness
// (that is an expensive B300 call and must be gated by the user's
// scheduler separately). Run run_fixture_compare.mjs between ticks.

import {
  existsSync,
  readFileSync,
  appendFileSync,
  mkdirSync,
  readdirSync,
} from "node:fs";
import { execSync } from "node:child_process";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const APP_ROOT = resolve(__dirname, "..");
const REPO_ROOT = resolve(APP_ROOT, "..", "..");
const FINDINGS = resolve(APP_ROOT, "findings");
const ITER_LOG = resolve(FINDINGS, "iteration-log.jsonl");
const CMP_LOG = resolve(FINDINGS, "comparison.jsonl");
const MAX_ITERATIONS = Number(process.env.PRISM42_MAX_ITERATIONS ?? 8);
const AGREEMENT_REGRESSION_PP = 2;

function appendIter(row) {
  mkdirSync(FINDINGS, { recursive: true });
  appendFileSync(ITER_LOG, JSON.stringify(row) + "\n", "utf8");
}

function lastIterationId() {
  if (!existsSync(ITER_LOG)) return 0;
  const lines = readFileSync(ITER_LOG, "utf8").trim().split("\n").filter(Boolean);
  if (!lines.length) return 0;
  const last = JSON.parse(lines[lines.length - 1]);
  return last.iteration_id ?? 0;
}

function latestSummaryBefore(ts) {
  const files = readdirSync(FINDINGS)
    .filter((f) => f.startsWith("comparison-summary-") && f.endsWith(".json"))
    .filter((f) => f < `comparison-summary-${ts}`)
    .sort()
    .reverse();
  if (!files.length) return null;
  try {
    return JSON.parse(readFileSync(resolve(FINDINGS, files[0]), "utf8"));
  } catch {
    return null;
  }
}

async function main() {
  const now = new Date();
  const iso = now.toISOString();
  const nextIter = lastIterationId() + 1;

  if (nextIter > MAX_ITERATIONS) {
    appendIter({
      iteration_id: nextIter,
      at: iso,
      action_taken: "halted_max_iterations",
      reason: `MAX_ITERATIONS=${MAX_ITERATIONS} reached; loop ends cleanly`,
    });
    console.log(`[iter] halted — cap ${MAX_ITERATIONS} reached`);
    process.exit(10);
  }

  if (!existsSync(CMP_LOG)) {
    appendIter({
      iteration_id: nextIter,
      at: iso,
      action_taken: "skipped",
      reason: "no comparison.jsonl yet; run run_fixture_compare.mjs first",
    });
    console.log("[iter] skipped — no findings yet");
    return;
  }

  // Invoke compare_metrics as a child.
  const stamp = now.toISOString().replace(/[-:.]/g, "").slice(0, 15) + "Z";
  const outJson = resolve(FINDINGS, `comparison-summary-${stamp}.json`);
  let metricsOutput = "";
  let metricsExit = 0;
  try {
    metricsOutput = execSync(
      `node ${resolve(APP_ROOT, "scripts/compare_metrics.mjs")} --in=${CMP_LOG} --out=${outJson}`,
      { encoding: "utf8", cwd: APP_ROOT },
    );
  } catch (err) {
    metricsExit = err.status ?? 1;
    metricsOutput = String(err.stdout ?? "") + String(err.stderr ?? "");
  }

  const summary = JSON.parse(readFileSync(outJson, "utf8"));
  const b300 = summary.per_mode.b300;
  const agreement = b300?.agreement?.agreement_rate ?? null;
  const fc = b300?.failure_counts ?? {};

  // L3 regression guard vs previous summary.
  let regression = null;
  const prev = latestSummaryBefore(stamp);
  if (prev) {
    const prevAgreement = prev.per_mode?.b300?.agreement?.agreement_rate;
    if (
      typeof prevAgreement === "number" &&
      typeof agreement === "number" &&
      agreement + AGREEMENT_REGRESSION_PP / 100 < prevAgreement
    ) {
      regression = {
        previous_agreement: prevAgreement,
        current_agreement: agreement,
        drop_pp: (prevAgreement - agreement) * 100,
      };
    }
  }

  // Hotspot detection
  const hotspots = [];
  if ((fc.disagreement ?? 0) > 0) hotspots.push("disagreement");
  if ((fc.drift ?? 0) > 0) hotspots.push("drift");
  if ((fc.latency ?? 0) > 0) hotspots.push("latency");
  if ((fc.timeout ?? 0) > 0) hotspots.push("timeout");
  if ((fc.error ?? 0) > 0) hotspots.push("error");

  let gitShas = null;
  try {
    gitShas = execSync("git log --oneline -3", {
      encoding: "utf8",
      cwd: REPO_ROOT,
    }).trim();
  } catch {
    gitShas = null;
  }

  const row = {
    iteration_id: nextIter,
    at: iso,
    metrics_exit: metricsExit,
    agreement_rate: agreement,
    failure_type_counts: fc,
    hotspots,
    regression,
    git_recent: gitShas,
    action_taken: regression
      ? "halted_regression"
      : hotspots.length
        ? "queued_investigation"
        : "ok",
    summary_file: outJson,
  };
  appendIter(row);

  if (regression) {
    console.log(
      `[iter] ${nextIter} REGRESSION — agreement dropped ${regression.drop_pp.toFixed(2)}pp; halting`,
    );
    process.exit(11);
  }
  console.log(
    `[iter] ${nextIter}/${MAX_ITERATIONS} action=${row.action_taken} agreement=${
      agreement !== null ? (agreement * 100).toFixed(1) + "%" : "n/a"
    } hotspots=[${hotspots.join(",")}]`,
  );
  if (metricsOutput) console.log(metricsOutput.split("\n").slice(-12).join("\n"));
}

main().catch((err) => {
  console.error(err);
  appendIter({
    iteration_id: lastIterationId() + 1,
    at: new Date().toISOString(),
    action_taken: "error",
    reason: String(err?.message ?? err),
  });
  process.exit(1);
});
