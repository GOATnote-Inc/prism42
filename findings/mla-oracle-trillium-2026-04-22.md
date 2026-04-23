# M7 — Trillium bf16 oracle verdict (2026-04-22)

Phase M / M7 executed artifact. First cross-accelerator datapoint for the
MLA decode oracle paper (`docs/papers/mla-oracle/`). Ran the JAX port of
the numpy FP32 reference on a GCP Trillium v6e-1 VM, captured the bf16
output, and graded it against the committed FP32 golden via the oracle
at the `bf16` tolerance preset.

## TL;DR

**PASS.** The same algebra that produced the FP32 golden, when run on
TPU Trillium v6e in bf16, agrees with the reference to within bf16's
ULP floor. `cos_sim = 0.999977`, `max_abs_diff = 8.9 × 10^{-3}`,
`max_rel_diff = 6.1 × 10^{-3}`. All three well inside the bf16 preset
(max_abs 5e-2, max_rel 2e-2, min_cos_sim 0.999).

This is one datapoint toward the paper's cross-substrate consistency
claim: the MLA decode **reference** reproduces the FP32 golden on a
non-NVIDIA substrate at bf16 precision, on the seeded committed
inputs. It supports — but does not by itself establish — the
hypothesis that the three target Blackwell bugs (SGLang #10284, vLLM
#38439, FlashInfer #3047) are kernel-local rather than spec-level.
That attribution requires executing the bug reproducers on SM100
NVFP4 paths (M6b), which is deferred pending RunPod B200 capacity.
NVFP4 microscaling has no analog on Trillium or Hopper, so this
bf16 rail cannot itself rule out a spec-level interaction that only
surfaces at the NVFP4 layer.

## Hardware provenance

| Field | Value |
|---|---|
| Provider | GCP |
| Project | `prism421` |
| Zone | `us-east5-a` |
| Accelerator | `v6e-1` (Trillium, one chip) |
| TPU VM name | `prism-mla-v6e1` (ephemeral, deleted after run) |
| `device_kind` (JAX) | `TPU v6 lite` |
| Runtime version | `v2-alpha-tpuv6e` |
| JAX version | `0.6.2` |
| Billing mode | on-demand (~$2.70/chip-hr; ~10 min of use) |

## Reproduction

```bash
# Provision (on-demand — preemptible was reclaimed immediately in us-east5-a).
gcloud compute tpus tpu-vm create prism-mla-v6e1 \
  --zone=us-east5-a --accelerator-type=v6e-1 --version=v2-alpha-tpuv6e \
  --project=prism421

# Push + install + run
gcloud compute tpus tpu-vm scp \
  corpus/mla/reference/mla_decode_jax.py prism-mla-v6e1:~/ --zone=us-east5-a
gcloud compute tpus tpu-vm ssh prism-mla-v6e1 --zone=us-east5-a \
  --command='pip install --quiet --upgrade "jax[tpu]>=0.4.34" numpy \
    -f https://storage.googleapis.com/jax-releases/libtpu_releases.html \
    && python3 ~/mla_decode_jax.py --dtype bf16 --config v2_lite --seqlen 16'

# Teardown (do not forget — billing is hourly).
gcloud compute tpus tpu-vm delete prism-mla-v6e1 --zone=us-east5-a --quiet
```

## Oracle verdict

```json
{
  "case_id": "TPU-RAIL-PROOF",
  "run_id": "80d718df-5864-4f6e-add5-6bf386fdc598",
  "rail": "tpu-pallas",
  "tolerance_preset": "bf16",
  "verdict": {
    "passed": true,
    "reasons": [],
    "max_abs_diff": 0.00892460,
    "max_rel_diff": 0.00614256,
    "cos_sim":      0.99997697,
    "nan_count": 0,
    "inf_count": 0,
    "reference_shape": [1, 2048],
    "candidate_shape": [1, 2048]
  }
}
```

Full verdict + raw TPU stdout output live at (gitignored per repo
convention, but regenerable via the reproduction.sh above plus
`scripts/mla_oracle_runner.py` when it wires up end-to-end):

```
results/mla-oracle/80d718df-5864-4f6e-add5-6bf386fdc598/verdict.json
results/mla-oracle/80d718df-5864-4f6e-add5-6bf386fdc598/tpu-raw-output.json
```

## An oracle bug surfaced by the run

The first grading attempt against the TPU output returned
`passed: False` with `max_rel_diff: 345.23` despite `max_abs_diff` of
8.9e-3 and `cos_sim` of 0.999977 — both well inside the bf16 preset.
Root cause: the oracle's `max_rel_diff` metric was pointwise
`|diff[i]| / (|ref[i]| + eps)`, which blows up at near-zero reference
entries even when the kernel is correct. Decode outputs routinely
have elements near zero, so this was a **false-negative bug in the
oracle itself** waiting for a real run to surface.

Fix landed in this same commit batch: `max_rel_diff` is now globally
scaled (`max(|diff|) / max(|ref|)`). All 11 pre-existing oracle-
integrity tests still pass under the new definition; the Trillium
verdict now correctly reads PASS.

The bug is exactly the class of thing an oracle is supposed to surface
on a real kernel run. That it surfaced against *the oracle itself* is
a useful calibration: the oracle is not above the discipline it
imposes on candidate kernels. Both the bug and the fix are recorded in
the commit history and in `docs/papers/mla-oracle/paper.tex` §4
(Method) as a footnote on the tolerance spec.

## Cost

| Item | Cost |
|---|---|
| Preemptible attempt (reclaimed immediately) | ~$0.05 |
| On-demand v6e-1 (~12 min) | ~$0.55 |
| **Total M7 spend** | **~$0.60** |

Well under the $20 M7 budget ceiling from `docs/mla-oracle-roadmap.md`.

## Next

- Commit the JAX reference, the oracle fix, and this findings note to
  the `t-mla` branch.
- Update `docs/papers/mla-oracle/paper.tex`: fill in the Trillium row
  of Table 2 (cross-accelerator concordance) with the real
  `cos_sim = 0.999977` number.
- M6 (B200 run) still deferred pending RunPod B200 capacity
  (`scripts/poll_b200_capacity.sh` is watching).
