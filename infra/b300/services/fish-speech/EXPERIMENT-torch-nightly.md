# Experiment — PyTorch nightly + Fish RTF on B300

> **Branch**: `experiment/torch-nightly-fish-rtf`. **Mainline frozen.**
> Acceptance: `/v1/health` 200 + TTFB < 100 ms + RTF < 1.5 + E2E voice
> works. Fail any → document + revert focus, no merge.
> Timebox 60–90 min active work.

## Hypothesis

Fish-speech upstream wires `torch.compile(decode_one_token, mode="default", fullgraph=True)` at `inference.py:383-390`. Stable PyTorch 2.8.0 + cu128 hits the Triton PTXAS sm_103a regression (no valid triton configs → `Internal Triton PTX codegen error`) on first inference. PyTorch nightly (≥ 2.11.dev with cu130 index) bundles a Triton whose PTXAS recognizes sm_103a. If install + Fish import + compile path all hold under nightly, expected RTF impact: 1.96 → ~0.7-1.4 (1.5-3× typical for autoregressive transformer decode).

## Isolation strategy

- New venv at `/opt/prism42/infra/b300/services/fish-speech/.venv-nightly`.
- Second Fish instance on port **9201** (mainline stays on 9200, untouched).
- Same source tree, same checkpoints, same input text.
- Bench script (below) hits both ports with identical body, prints baseline-vs-nightly table.

## Steps

```
# 0. Snapshot pre-state (pod)
ls /opt/prism42/infra/b300/services/fish-speech/.venv-nightly  # absent
df -h /opt/prism42                                              # 4.8 TB free
nvidia-smi --query-gpu=memory.used,memory.free,memory.total --format=csv,noheader  # 244 GB free

# 1. Create venv with pip
cd /opt/prism42/infra/b300/services/fish-speech
python3 -m venv .venv-nightly
.venv-nightly/bin/python -m pip install --upgrade pip wheel

# 2. Install nightly torch + torchvision + torchaudio (cu130 index)
.venv-nightly/bin/pip install --pre torch torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/nightly/cu130

# 3. Install fish-speech editable + remaining deps
.venv-nightly/bin/pip install -e src/

# 4. Launch second Fish instance on port 9201 (no systemd; nohup'd)
PORT=9201 nohup .venv-nightly/bin/python src/tools/api_server.py \
    --mode tts --listen 127.0.0.1:9201 \
    --llama-checkpoint-path checkpoints/s2-pro \
    --decoder-checkpoint-path checkpoints/s2-pro/codec.pth \
    --device cuda --half --compile \
    > /tmp/fish-nightly.log 2>&1 &

# 5. Wait for "Startup done, listening server" in /tmp/fish-nightly.log

# 6. Bench (script: scripts/bench_fish_two_ports.py)
.venv-nightly/bin/python scripts/bench_fish_two_ports.py 9200 9201
```

## Bench script (proposed)

`scripts/bench_fish_two_ports.py` (created in this branch):

```python
"""Apples-to-apples Fish bench across two ports.
Same text, same params, N samples each, prints comparison table."""
import argparse, json, time
import httpx, ormsgpack

UTTERANCE = "Nine one one, what is the address of your emergency? Please stay on the line."

def bench(port: int, n: int) -> dict:
    samples = []
    for _ in range(n):
        body = ormsgpack.packb({
            "text": UTTERANCE,
            "format": "wav",
            "chunk_length": 200,
            "streaming": True,
            "max_new_tokens": 256,
            "top_p": 0.7,
            "repetition_penalty": 1.1,
            "temperature": 0.1,
            "seed": 911,
            "references": [],
        })
        t0 = time.monotonic(); first = None; total = 0
        try:
            with httpx.stream("POST", f"http://127.0.0.1:{port}/v1/tts",
                              content=body,
                              headers={"Content-Type": "application/msgpack"},
                              timeout=60.0) as r:
                if r.status_code != 200:
                    samples.append({"err": f"HTTP {r.status_code}"})
                    continue
                for chunk in r.iter_bytes():
                    if first is None and chunk:
                        first = time.monotonic() - t0
                    total += len(chunk)
        except Exception as e:
            samples.append({"err": str(e)[:200]}); continue
        done = time.monotonic() - t0
        audio_ms = total / 2 / 44100 * 1000  # PCM16 mono 44.1kHz
        samples.append({
            "ttfb_ms": int(first*1000) if first else None,
            "total_ms": int(done*1000),
            "audio_ms": int(audio_ms),
            "rtf": done*1000/audio_ms if audio_ms else None,
            "bytes": total,
        })
    return {"port": port, "n": n, "samples": samples}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ports", nargs="+", type=int)
    ap.add_argument("--n", type=int, default=3)
    a = ap.parse_args()
    results = [bench(p, a.n) for p in a.ports]
    print(json.dumps(results, indent=2))
    # Summary
    print("\n=== Summary ===")
    print(f"{'port':<8}{'TTFB ms':<12}{'Total ms':<12}{'RTF':<8}")
    for r in results:
        ok = [s for s in r["samples"] if "err" not in s]
        if not ok:
            print(f"{r['port']:<8}{'(all err)':<12}")
            continue
        ttfb_med = sorted(s["ttfb_ms"] for s in ok)[len(ok)//2]
        total_med = sorted(s["total_ms"] for s in ok)[len(ok)//2]
        rtf_med = sorted(s["rtf"] for s in ok)[len(ok)//2]
        print(f"{r['port']:<8}{ttfb_med:<12}{total_med:<12}{rtf_med:<8.2f}")

if __name__ == "__main__":
    main()
```

## Acceptance criteria

| Check | Threshold |
|---|---|
| `/v1/health` (or first synth call) returns 200 | required |
| TTFB stays under 100 ms | required (don't regress current 29 ms) |
| RTF < 1.5 | required for "fast win" (current baseline 1.96) |
| E2E LiveKit voice works (worker can route to nightly Fish) | required only if we plan to migrate; deferred to merge step |

If any required check fails: document + leave mainline unchanged. **No commit to main.**

## Logs

- Install progress: `pod:/tmp/fish-nightly-install.log`
- Nightly Fish runtime: `pod:/tmp/fish-nightly.log`
- Mainline Fish runtime: `pod:/tmp/prism42-logs/fish.log` (untouched)

## Status

- Pre-flight: ✓
- venv created (`.venv-nightly`, Python 3.12.3, pip 26.0.1): ✓
- nightly torch install: in flight (background pid 224315 on pod)
- Fish install in nightly venv: pending
- Second Fish launch on 9201: pending
- Bench: pending
- Verdict: pending
