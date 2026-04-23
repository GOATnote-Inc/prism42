"use client";

import type { RubricGrade } from "@/lib/types";

function fmt(n: number) {
  return n.toFixed(2);
}

export function RubricStrip({ grades }: { grades: RubricGrade[] }) {
  const latest = grades[grades.length - 1];
  return (
    <div className="panel">
      <h2>Live rubric</h2>
      {!latest && (
        <div className="dim">
          No turns graded yet. GPT-5.5 cross-vendor grader is warming up.
        </div>
      )}
      {latest && (
        <>
          <div className="rubric-grid">
            <div className="label">R1 clinical accuracy</div>
            <div className="score">{fmt(latest.criteria.R1_clinical_accuracy)}</div>
            <div className="label">R2 scope adherence</div>
            <div className="score">{fmt(latest.criteria.R2_scope_adherence)}</div>
            <div className="label">R3 safety preservation</div>
            <div className="score">{fmt(latest.criteria.R3_safety_preservation)}</div>
            <div className="label">R4 clarity for caller</div>
            <div className="score">{fmt(latest.criteria.R4_clarity_for_caller)}</div>
            <div className="label">R5 protocol adherence</div>
            <div className="score">{fmt(latest.criteria.R5_protocol_adherence)}</div>
            <div className="weighted">
              <span>weighted</span>
              <span>{fmt(latest.weighted_score)}</span>
            </div>
          </div>
          <div className="mono dim" style={{ marginTop: 10, fontSize: 11 }}>
            grader · {latest.model_used} · {latest.latency_ms} ms
          </div>
          {latest.self_grade_flag && (
            <div className="self-grade-flag">
              SELF-GRADE FLAG · OpenAI chain exhausted; Claude graded
              Claude; score not load-bearing for baselines this session.
            </div>
          )}
        </>
      )}
      {grades.length > 1 && (
        <div className="mono dim" style={{ marginTop: 10, fontSize: 11 }}>
          {grades.length} turns graded · mean{" "}
          {fmt(
            grades.reduce((acc, g) => acc + g.weighted_score, 0) /
              grades.length,
          )}
        </div>
      )}
    </div>
  );
}
