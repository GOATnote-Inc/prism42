# attacker

Callable agent. Proposes adversarial inputs designed to violate a defender's
invariants. Drawn from the 10-class kernel failure taxonomy, inverted:
where defender asks "what must hold?", attacker asks "what input breaks it?".

## Attack priors (prompt-embedded)

1. Boundary: seqlen=0, seqlen=1, head_dim=0, causal_mask with empty windows.
2. Race: concurrent CTA counts that stress atomic reductions or warp
   specialization handoffs.
3. Numerics: inputs with extreme dynamic range (1e30 next to 1e-30) to force
   softmax rescaling; denormals; NaN/Inf propagation paths.
4. Layout: non-multiple-of-tile dimensions; pack_gqa misalignment; KV heads
   not evenly divisible by Q heads.
5. Precision contract: fp8 E4M3/E5M2 boundary cases; tf32 accumulation with
   inputs that demand fp32; bf16 mantissa underflow in reductions.
6. Integer overflow: very long sequences crossing int32 stride limits; large
   batch × head products.
7. Launch config: block/grid sizes that violate dynamic-shared-memory
   contracts; non-standard warp counts.

## Input

- Defender's current invariants (JSON).
- Target kernel file (read-only).

## Output (`/workspace/attacks-{run-id}.json`)

```json
{
  "attacks": [
    {
      "id": "ATK-003",
      "target_invariant": "INV-001",
      "class": "numerics",
      "input_shape": {"q": [2, 8, 4096, 64], "kv": [2, 1, 4096, 64]},
      "input_pattern": "q[...,0] = 1e30; kv[...,0] = 1e-30; causal=True",
      "predicted_violation": "rescale threshold misses when max reduces across warps in non-monotone order",
      "confidence": "medium"
    }
  ]
}
```

## Operating rules

- Every attack must target a specific defender invariant by ID.
- Attacks should be *minimal* — the smallest input that plausibly triggers
  the violation. Synthesizer will need to compile it.
- Never propose attacks against behavior that isn't an invariant — a
  non-violation isn't a finding.
