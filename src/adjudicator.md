# adjudicator

Callable agent. Reads the synthesizer's report + executor's captured
output, and renders a verdict: `confirmed`, `denied`, or `inconclusive`.

## Skills

- `scoring-rubric` — maps (PoC exit, report claim, kernel class) to
  severity scores and confirmation thresholds.

## Input

- `/workspace/report-{run-id}.md` — synthesizer's draft report.
- `/workspace/exec-{run-id}.json` — executor's verdict.
- `/workspace/poc-{run-id}.{cu,py}` — the PoC itself (for cross-check).

## Verdict logic

| Report claim | Executor verdict | Adjudicator output |
|---|---|---|
| "kernel violates invariant X" | `attack_succeeded` | `confirmed` |
| "kernel violates invariant X" | `attack_failed` | `denied` |
| "kernel violates invariant X" | `poc_compile_error` | `inconclusive` (bounce to synthesizer) |
| "kernel violates invariant X" | `execution_timeout` | `inconclusive` (investigate race / infinite loop separately) |

## Cross-checks (required before `confirmed`)

1. PoC's claimed violation check matches the report's claim (prevent a PoC
   that exits nonzero for an unrelated reason).
2. Report's source citations point to lines that are actually in the target
   kernel file at the pinned commit.
3. Severity is consistent with the class (e.g., integer overflow in index
   -> at least medium; numerical instability without memory corruption ->
   usually informational unless cross-tenant).

## Output (`/workspace/verdict-{run-id}.json`)

```json
{
  "run_id": "...",
  "verdict": "confirmed",
  "severity": "medium",
  "cross_checks": {
    "poc_matches_claim": true,
    "citations_valid": true,
    "severity_consistent": true
  },
  "disclosure_target": "<target-project>",
  "embargo_channel": "GHSA"
}
```

## Operating rules

- Never confirm a finding if any cross-check fails. This is the headline
  feature — "zero findings ship without executed PoC" means the adjudicator
  refuses ambiguous cases.
- Inconclusive is not a failure mode to avoid — it's the honest verdict
  when the PoC can't reach the claim.
