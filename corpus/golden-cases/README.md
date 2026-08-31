# corpus/golden-cases

Frozen end-to-end fixtures for the Prism L3 verification layer.

Each subdirectory is a complete, cross-reference-consistent case that the
pipeline must continue to validate: case + invariants + attacks + PoC +
executor record + adjudicator verdict + human-readable report.

## Purpose

- **Regression anchor.** Every schema change, every cross-reference rule,
  every PoC-exit-semantics assumption is exercised by these cases. If a
  change to L1 schemas or L3 validators breaks a golden case, the change
  is wrong -- not the fixture.
- **Onboarding reference.** New agents and reviewers can read a full,
  non-redacted case without needing access to any real embargoed finding.

## Cases

- `KERNEL-GOLD-001/` -- synthetic fp8 online-softmax rescale underflow.
  CONFIRMED, severity=high, rail=cuda, attack_succeeded. Exercises every
  required file, every schema, every cross-reference rule.

## Rule

Do **not** edit a golden case to silence a failing test. Fix the test
or the validator. The fixture is the specification.
