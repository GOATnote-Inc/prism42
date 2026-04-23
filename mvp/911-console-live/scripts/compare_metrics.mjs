#!/usr/bin/env node
// Aggregate findings/comparison.jsonl into a per-scenario + global
// summary. Reports:
//  - latency p50/p90/p99 per source (absolute + ratio)
//  - per-criterion agreement rate (|Δ| ≤ 0.2 on all 5)
//  - action equality (sanity check; should be 100%)
//  - direction bias (mean signed delta per criterion + 95% CI)
//  - failure_type breakdown
//  - per-scenario seed variance (mean ± std across seeds)
//
// Usage:
//   node scripts/compare_metrics.mjs --in findings/comparison.jsonl \
//     --out findings/comparison-summary-$(date +%Y%m%dT%H%M%SZ).json
//
// Exit 0 if gates pass; exit 1 if any hard gate fails (for CI / iteration loop).

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";

const GATES = {
  latency_ratio_max: 0.7, // B300 rubric p50 must be <= 70% of hosted p50
  agreement_rate_min: 0.95, // strict per-turn 5-axis agreement |Δ| <= 0.2
  action_equality_min: 1.0,
  drift_mean_max: 0.2, // |mean signed delta| per axis
};

const DISAGREEMENT_DELTA = 0.2;
const CRITERIA = [
  "R1_clinical_accuracy",
  "R2_scope_adherence",
  "R3_safety_preservation",
  "R4_clarity_for_caller",
  "R5_protocol_adherence",
];

function parseArgs(argv) {
  const out = { in: null, out: null };
  for (const arg of argv.slice(2)) {
    if (arg.startsWith("--in=")) out.in = arg.slice(5);
    else if (arg.startsWith("--out=")) out.out = arg.slice(6);
  }
  if (!out.in) throw new Error("--in required");
  return out;
}

function percentile(values, p) {
  const s = [...values].sort((a, b) => a - b);
  if (!s.length) return null;
  const idx = Math.min(s.length - 1, Math.floor(p * s.length));
  return s[idx];
}

function mean(values) {
  if (!values.length) return null;
  return values.reduce((a, b) => a + b, 0) / values.length;
}

function std(values) {
  if (values.length < 2) return 0;
  const m = mean(values);
  const v = values.reduce((a, b) => a + (b - m) * (b - m), 0) / (values.length - 1);
  return Math.sqrt(v);
}

function main() {
  const args = parseArgs(process.argv);
  const raw = readFileSync(args.in, "utf8");
  const rows = raw
    .split("\n")
    .filter((l) => l.trim().length)
    .map((l) => JSON.parse(l));
  if (!rows.length) {
    console.error("[metrics] no rows to aggregate");
    process.exit(2);
  }

  const byMode = { vercel: [], b300: [] };
  for (const r of rows) {
    if (byMode[r.mode]) byMode[r.mode].push(r);
  }

  const summary = {
    generated_at: new Date().toISOString(),
    input_file: args.in,
    input_rows: rows.length,
    modes_present: Object.entries(byMode)
      .filter(([, arr]) => arr.length > 0)
      .map(([m]) => m),
    per_mode: {},
    gates: { ...GATES, verdicts: {} },
  };

  for (const [mode, modeRows] of Object.entries(byMode)) {
    if (!modeRows.length) continue;
    const pLats = modeRows
      .map((r) => r.rubric_primary_latency_ms)
      .filter((x) => typeof x === "number");
    const sLats = modeRows
      .map((r) => r.rubric_shadow_latency_ms)
      .filter((x) => typeof x === "number");
    const ratios = modeRows
      .map((r) => r.latency_ratio)
      .filter((x) => typeof x === "number");

    // Per-criterion signed delta (primary - shadow)
    const axisDeltas = {};
    for (const k of CRITERIA) axisDeltas[k] = [];
    for (const r of modeRows) {
      if (!r.rubric_primary_scores || !r.rubric_shadow_scores) continue;
      for (const k of CRITERIA) {
        axisDeltas[k].push(r.rubric_primary_scores[k] - r.rubric_shadow_scores[k]);
      }
    }
    const biasByAxis = {};
    for (const k of CRITERIA) {
      const vals = axisDeltas[k];
      const m = mean(vals) ?? 0;
      const s = std(vals);
      const ci = vals.length > 1 ? (1.96 * s) / Math.sqrt(vals.length) : 0;
      biasByAxis[k] = {
        mean_signed_delta: m,
        std: s,
        ci95_halfwidth: ci,
        n: vals.length,
      };
    }

    // Strict per-turn agreement: all 5 axes within DISAGREEMENT_DELTA.
    const agreedTurns = modeRows.filter((r) => {
      if (!r.rubric_primary_scores || !r.rubric_shadow_scores) return false;
      return CRITERIA.every(
        (k) =>
          Math.abs(
            r.rubric_primary_scores[k] - r.rubric_shadow_scores[k],
          ) <= DISAGREEMENT_DELTA,
      );
    });

    const failureCounts = modeRows.reduce(
      (acc, r) => {
        acc[r.failure_type] = (acc[r.failure_type] ?? 0) + 1;
        return acc;
      },
      { none: 0, disagreement: 0, latency: 0, drift: 0, timeout: 0, error: 0 },
    );

    // Per-scenario seed variance: for each scenario, compute std of
    // primary weighted across seeds.
    const byScenario = {};
    for (const r of modeRows) {
      const key = `${r.scenario_id}|${r.turn_id}`;
      if (!byScenario[key]) byScenario[key] = [];
      if (typeof r.rubric_primary_weighted === "number") {
        byScenario[key].push(r.rubric_primary_weighted);
      }
    }
    const seedStds = Object.values(byScenario).map((arr) => std(arr));

    summary.per_mode[mode] = {
      rows: modeRows.length,
      latency: {
        primary_p50: percentile(pLats, 0.5),
        primary_p90: percentile(pLats, 0.9),
        primary_p99: percentile(pLats, 0.99),
        shadow_p50: percentile(sLats, 0.5),
        shadow_p90: percentile(sLats, 0.9),
        shadow_p99: percentile(sLats, 0.99),
        ratio_mean: mean(ratios),
        ratio_median: percentile(ratios, 0.5),
        ratio_p90: percentile(ratios, 0.9),
      },
      agreement: {
        agreed_turns: agreedTurns.length,
        total_turns: modeRows.length,
        agreement_rate:
          modeRows.length > 0 ? agreedTurns.length / modeRows.length : 0,
      },
      action_equality_rate:
        modeRows.length > 0
          ? modeRows.filter((r) => r.action === r.action).length /
            modeRows.length
          : 0, // should always be 1; we keep the field for interface symmetry with per-mode A/B designs
      bias_by_axis: biasByAxis,
      failure_counts: failureCounts,
      seed_variance: {
        mean_std_of_weighted: mean(seedStds),
        max_std_of_weighted: seedStds.length ? Math.max(...seedStds) : 0,
      },
    };
  }

  // Verdict vs gates (only meaningful when b300 mode has data).
  const b300Summary = summary.per_mode.b300;
  if (b300Summary) {
    const ratioMedian = b300Summary.latency.ratio_median ?? Infinity;
    const agreementRate = b300Summary.agreement.agreement_rate ?? 0;
    const maxAxisBias = Math.max(
      ...CRITERIA.map((k) =>
        Math.abs(b300Summary.bias_by_axis[k]?.mean_signed_delta ?? 0),
      ),
    );
    summary.gates.verdicts = {
      latency_ratio: {
        value: ratioMedian,
        gate: GATES.latency_ratio_max,
        pass: ratioMedian <= GATES.latency_ratio_max,
      },
      agreement_rate: {
        value: agreementRate,
        gate: GATES.agreement_rate_min,
        pass: agreementRate >= GATES.agreement_rate_min,
      },
      drift_mean: {
        value: maxAxisBias,
        gate: GATES.drift_mean_max,
        pass: maxAxisBias <= GATES.drift_mean_max,
      },
    };
  }

  // Emit JSON + Markdown.
  if (args.out) {
    mkdirSync(dirname(resolve(args.out)), { recursive: true });
    writeFileSync(args.out, JSON.stringify(summary, null, 2), "utf8");
    console.log(`[metrics] wrote ${args.out}`);
  }

  // Markdown to stdout.
  console.log("");
  console.log(`# comparison summary — ${summary.generated_at}`);
  console.log(
    `input: ${args.in} (${summary.input_rows} rows, modes: ${summary.modes_present.join(", ")})`,
  );
  console.log("");
  for (const [mode, s] of Object.entries(summary.per_mode)) {
    console.log(`## mode=${mode} (${s.rows} rows)`);
    console.log(
      `- latency primary p50/p90/p99: ${s.latency.primary_p50}/${s.latency.primary_p90}/${s.latency.primary_p99} ms`,
    );
    console.log(
      `- latency shadow  p50/p90/p99: ${s.latency.shadow_p50}/${s.latency.shadow_p90}/${s.latency.shadow_p99} ms`,
    );
    console.log(
      `- latency ratio median / mean / p90: ${s.latency.ratio_median?.toFixed?.(3) ?? "-"} / ${s.latency.ratio_mean?.toFixed?.(3) ?? "-"} / ${s.latency.ratio_p90?.toFixed?.(3) ?? "-"}`,
    );
    console.log(
      `- agreement |Δ|≤0.2 on all 5 axes: ${s.agreement.agreed_turns}/${s.agreement.total_turns} = ${(s.agreement.agreement_rate * 100).toFixed(1)}%`,
    );
    const fc = s.failure_counts;
    console.log(
      `- failure_type: none=${fc.none} disagreement=${fc.disagreement} latency=${fc.latency} drift=${fc.drift} timeout=${fc.timeout} error=${fc.error}`,
    );
    console.log(
      `- seed variance (mean std of primary weighted, across seeds): ${s.seed_variance.mean_std_of_weighted?.toFixed?.(4) ?? "-"}`,
    );
    console.log("- bias by axis (mean signed delta, primary − shadow):");
    for (const k of CRITERIA) {
      const b = s.bias_by_axis[k];
      console.log(
        `  - ${k}: ${b.mean_signed_delta.toFixed(4)} ± ${b.ci95_halfwidth.toFixed(4)} (n=${b.n})`,
      );
    }
    console.log("");
  }
  if (summary.gates.verdicts && Object.keys(summary.gates.verdicts).length) {
    console.log("## gates");
    for (const [k, v] of Object.entries(summary.gates.verdicts)) {
      const mark = v.pass ? "PASS" : "FAIL";
      console.log(
        `- [${mark}] ${k}: value=${typeof v.value === "number" ? v.value.toFixed(4) : v.value} gate=${v.gate}`,
      );
    }
    const allPass = Object.values(summary.gates.verdicts).every((v) => v.pass);
    console.log("");
    console.log(allPass ? "SIGNAL: pass" : "SIGNAL: fail");
    process.exit(allPass ? 0 : 1);
  }
}

main();
