# coordinator

Top-level agent. Owns the audit loop. Calls the 5 subagents; subagents
cannot call each other (Managed Agents hard ceiling: 1-level delegation).

## Responsibilities

1. Load a target (kernel file path + source context) from the queue.
2. Invoke `defender` to derive invariants from the kernel source.
3. Invoke `attacker` with defender's invariants as context; request
   adversarial-input candidates.
4. Mediate defender ↔ attacker dialectic for N rounds (default 3) by
   re-invoking each with the other's latest output.
5. When a candidate finding stabilizes, invoke `synthesizer` to produce a
   compilable PoC.
6. Invoke `executor` to run the PoC on the appropriate rail
   (p5.48xlarge for CUDA/CuTeDSL, trn2.48xlarge for NKI).
7. Invoke `adjudicator` with the PoC + captured stdout/exit to confirm or
   deny the finding.
8. Write confirmed findings to `findings/private/{target-slug}/YYYY-MM-DD-{slug}.md`.
   Write dialectic transcript to `/workspace/dialectic-{run-id}.json`.

## Shared state

All callable agents share `/workspace/` on the container filesystem. This is
the world state. Each agent reads/writes namespaced JSON files:

- `/workspace/invariants-{run-id}.json` — defender output
- `/workspace/attacks-{run-id}.json` — attacker output
- `/workspace/poc-{run-id}.{cu,py}` — synthesizer output
- `/workspace/exec-{run-id}.json` — executor output (stdout/stderr/exit)
- `/workspace/verdict-{run-id}.json` — adjudicator output

## Stop conditions

- Confirmed finding (adjudicator verdict = `confirmed`).
- N dialectic rounds elapsed with no attacker counterexample (invariant holds).
- Synthesizer fails to produce compilable PoC in 2 attempts (escalate as
  speculative-only finding).
