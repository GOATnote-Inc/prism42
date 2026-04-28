---
case_id: KERNEL-GOLDEN
target: kernel/hopper/fmha_fwd_fp8.cu
class: precision
severity_estimate: high
invariant_id: INV-002
attack_id: ATK-001
rail: cuda
status: confirmed
disclosure_target: N/A
embargo_channel: N/A
---

# KERNEL-GOLDEN -- fp8 online-softmax rescale underflow (golden-case regression anchor)

> This is a fixture, not a real vendor finding. Its content is correct in kernel-auditing
> terminology but the line numbers, file paths, and bug specifics are synthetic. It exists
> so the Prism L3 verification layer has a frozen, fully cross-referenced case to regress
> against.

## Summary

Under fp8 (E4M3) K/V tiles, the online-softmax accumulator's cross-tile
correction factor `exp(m_prev - m_new)` can be rounded to zero before it
multiplies the running denominator `l_prev`. When this happens every
probability mass accumulated in prior tiles is silently discarded and the
final softmax output is biased toward whatever tile was active at the
underflow. The bug is a precision-class invariant violation (INV-002) and
chains into a numerical-class violation (INV-003) on rows whose only
finite contributions live in the discarded tiles.

## Attack vector

ATK-001 drives INV-002 with:

- batch=1, heads=8, seq_q=128, seq_k=512, head_dim=128
- K and V tiles drawn from the E4M3 subnormal band `[2^-10, 2^-8]`
- Q scaled so that adjacent tile row-maxes are separated by exactly 9.0,
  forcing `exp(m_prev - m_new) ~ 1.23e-4`, well below the E4M3 subnormal
  boundary `2^-9 ~ 1.95e-3`

No special privilege is needed -- a user who controls the attention
inputs (any caller of the forward kernel) can trigger the flush.

## Expected vs actual

| Quantity | fp32 reference | buggy fp8 path | note |
|---|---|---|---|
| running denominator `l` after 3 tiles | 2.2343 | 1.0000 | prior-tile mass discarded |
| relative error | -- | 0.552 | > 0.5 violation threshold |
| downstream `O` row when only early tiles had mass | finite, well-scaled | NaN / inf | chains to INV-003 |

The PoC (`poc.py`) exits with code 1 and writes a diagnostic line to
stderr naming `invariant_id=INV-002` and `class=precision`. The executor
captured verdict `attack_succeeded` on the cuda rail
(run_id `464f659e-8099-41ef-899c-1aec6de57e04`).

## Proposed mitigation

1. Perform the cross-tile rescale in fp32 (or at minimum bf16) and only
   narrow the product back to fp8 after the addition. This preserves the
   correction factor across the subnormal band.
2. Clamp the correction factor: if `m_new - m_prev` exceeds the
   representable exponent range, treat the prior accumulator as zero
   *deliberately* -- i.e., replace silent flush with a documented
   early-out -- and assert `l_new > 0` before the final normalization so
   INV-003 cannot silently NaN.
3. Add a compile-time `static_assert` tying the rescale intermediate
   precision to the accumulator precision so a future refactor cannot
   regress the fix.

Mitigation (1) is the minimal change; (2) and (3) are defence in depth.

## Source citations

All line numbers reference the `target_path`
`kernel/hopper/fmha_fwd_fp8.cu` at the audit commit. These are the
`source_lines` tracked in `invariants.json`:

- INV-001 (online-softmax row-max finiteness): lines 142-144, 168-169
- INV-002 (fp8 rescale subnormal boundary): lines 201-205, 210
- INV-003 (final normalization denominator): lines 241-242

## Cross-artifact map

- Case: `case.json` (`KERNEL-GOLDEN`, domain=gpu, rail_hint=cuda)
- Invariants: `invariants.json` round 1 (INV-001, INV-002, INV-003)
- Attacks: `attacks.json` round 1 (ATK-001 -> INV-002, ATK-002 -> INV-001)
- PoC: `poc.py` -- mocked; exits 1 with `VIOLATION invariant_id=INV-002`
- Execution: `exec.json` -- rail=cuda, verdict=attack_succeeded
- Adjudication: `verdict.json` -- confirmed, severity=high, all cross_checks true
