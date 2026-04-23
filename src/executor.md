# executor

Callable agent. Compiles and runs the synthesizer's PoC on the appropriate
hardware rail. Captures stdout, stderr, and exit code verbatim.

## MCP / transport

Dual-rail. Executor picks the rail from the `/workspace/current-rail`
marker that `coordinator` sets at session start.

- **Lambda Labs rail (primary)** — no MCP. Shells out to
  `scripts/ssh_exec.sh <ip> <cmd> --expect <marker>` with the IP read from
  `.state/lambda-current.json`. Exit code from the remote is preserved;
  `--expect` gates on a stdout marker so "exit 0 but wrong output" is
  caught.
- **AWS rail (secondary, when quotas clear)** — `awslabs/mcp` AWS API
  Server. Uses `ssm:SendCommand`, `ssm:GetCommandInvocation`,
  `ec2:DescribeInstances`.

## Skills

- `cuda-toolkit` — nvcc invocation templates, CUDA version detection.
- `nki-toolkit` — neuron-cc invocation, trn2 profiling knobs.

## Rail selection

| PoC type | SM target | RunPod (primary) | Lambda (backup) | AWS (upgrade) |
|---|---|---|---|---|
| `.cu` (raw CUDA) | SM90 | `NVIDIA H100 80GB HBM3` | `gpu_1x_h100_pcie` | `p5.48xlarge` |
| `.py` with `cute.` imports | SM90 | H100 SXM | Lambda H100 | `p5.48xlarge` |
| `.py` with `cute.` imports | SM100 | `NVIDIA H200` | *capacity tight* | `p5.48xlarge` |
| `.py` with `@nki.jit` | Trainium | *not available* | *not available* | `trn2.48xlarge` |

If the current rail cannot satisfy the PoC's SM/toolchain requirement, mark
the finding `verdict=execution_deferred_<reason>` (e.g.
`execution_deferred_sm100`, `execution_deferred_nki`) and skip — do not
fabricate confirmation.

## Input

- `/workspace/poc-{run-id}.{cu,py}` — synthesizer artifact.
- Rail hint (CUDA / CuTeDSL / NKI).

## Output (`/workspace/exec-{run-id}.json`)

```json
{
  "run_id": "...",
  "rail": "cuda",
  "instance_id": "i-0abc...",
  "command_id": "12345678-aaaa-bbbb-...",
  "compile": {"duration_sec": 18.4, "exit": 0, "stderr": "..."},
  "run": {"duration_sec": 2.1, "exit": 1, "stdout": "...", "stderr": "..."},
  "verdict": "attack_succeeded"
}
```

`verdict` is derived from `run.exit`:
- exit 0 -> `attack_failed` (kernel held)
- exit nonzero -> `attack_succeeded` (kernel violated invariant)
- compile nonzero -> `poc_compile_error` (escalate back to synthesizer)

## Operating rules

- Never mutate instance state beyond scratch files under
  `/tmp/prism-{run-id}/` on the instance. No package installs, no kernel
  rebuilds; rely on pre-warmed toolchain.
- Round-trip SLO: 30s for CUDA, 60s for CuTeDSL, 90s for NKI. Timeout
  triggers `verdict=execution_timeout`.
- Never swallow stderr. The adjudicator may need it.
