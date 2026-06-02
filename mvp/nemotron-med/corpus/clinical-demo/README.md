# Prism Clinical Demo Fixtures

**Synthetic fixtures for the clinical-rail demo surface. Not a research
dataset. Not patient data. Not for clinical use.**

Each case under this directory is a self-contained bundle used by
`scripts/generate_clinical_demo_artifacts.py` to render a rubric card
without making any Claude Opus 4.7 API calls. The `baseline.md` and
`modified.md` files are hand-authored synthetic responses that
illustrate the *kind* of delta Prism's harness is designed to surface.

When `scripts/harness_runner.py` runs for real (T4.7b, gated behind
`--commit` + `PRISM_HARNESS_COMMIT=1`), these synthetic transcripts are
replaced by live Opus 4.7 responses. The rubric + case shape stays the
same.

## Case selection principles

The two cases here were chosen to stress two different cognitive errors
seen at the bedside in a level-1 ED:

1. **CLN-DEMO-001 — Pediatric fever (age <90 days).** Classic anchoring
   / premature closure. The viral-URI story in the room is *the trap*;
   the age threshold is *the rule* (Rochester / Step-by-Step / PECARN).
2. **CLN-DEMO-002 — Elderly syncope.** Representativeness error. A
   normal ECG and normal vitals in an older adult with no prodrome
   does not rule out a high-risk etiology; the Canadian Syncope Risk
   Score applies.

Every case is labeled synthetic in every output file. Every output
file carries a `physician-review-required` marker before it would be
promoted to any non-demo use.
