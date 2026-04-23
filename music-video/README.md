# Prism

### Claude Opus 4.7 as your music-video editor.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Built with Opus 4.7](https://img.shields.io/badge/Built_with-Opus_4.7-purple.svg)](https://www.anthropic.com/)

> Drop a folder of clips. Drop a song. Prism gives you back a production-cut music video — every frame timed to the beat, every clip chosen by Claude.

---

## What it is

Prism is a beat-matched video splicing engine. It turns a pile of raw footage and a copyright-free track into a finished music video — simultaneously in **16:9 (YouTube)** and **9:16 (TikTok / Reels)**.

The trick isn't the cutting. Cutting to a beat grid is an ffmpeg call. The trick is **choosing which clip lands on which beat**, and that is where Claude Opus 4.7 earns its keep. Prism treats the model as a creative director: it watches every clip through vision, reads the song's energy curve and sections, and writes an `EditPlan` with a one-line director's note for every cut.

## How it works

```
   song.mp3  +  ./clips/
       │           │
       ▼           ▼
  ┌─────────┐  ┌─────────────────┐
  │ librosa │  │ ffprobe + cv2   │
  │ beats,  │  │ duration, fps,  │
  │ tempo,  │  │ motion, bright, │
  │ energy, │  │ keyframes       │
  │ sections│  │                 │
  └────┬────┘  └────────┬────────┘
       │                │
       │                ▼
       │        ┌──────────────────┐
       │        │ Opus 4.7 (vision)│
       │        │ mood, energy,    │
       │        │ motion_type,     │
       │        │ best_use,        │
       │        │ director's note  │
       │        └────────┬─────────┘
       ▼                 ▼
  ┌──────────────────────────────┐
  │  Opus 4.7 — Creative Director│
  │  matches beats × clips       │
  │  emits EditPlan + reasoning  │
  └──────────────┬───────────────┘
                 ▼
         ┌──────────────┐
         │    ffmpeg    │
         │ cut + concat │
         │ + mux audio  │
         └──────┬───────┘
                ▼
   ┌────────────────────────┐
   │ song__16x9.mp4         │
   │ song__9x16.mp4         │
   │ director.json (why)    │
   └────────────────────────┘
```

## Quick start

```bash
# 0. Prereq: ffmpeg on PATH (brew install ffmpeg)
# 1. Clone
gh repo clone GOATnote-Inc/prism && cd prism/music-video

# 2. Install
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# 3. Key
export ANTHROPIC_API_KEY="sk-ant-..."

# 4. Cut
prism cut --song ./examples/song.mp3 --clips ./examples/clips --out ./out
```

Outputs:

```
out/
├── song__16x9.mp4           # YouTube
├── song__9x16.mp4           # TikTok / Reels
├── song__16x9__director.json # Claude's reasoning per cut
└── song__9x16__director.json
```

## Example director's note

```json
{
  "overall_note": "Opens quiet — long takes on the intro to let the hook breathe. Hard cuts every downbeat through the first verse. On the drop, I switched to chaotic motion clips to mirror the synth stab. Outro mirrors the intro: slow, close, restrained.",
  "segments": [
    {
      "beat": "0.00-0.51",
      "clip": "a3f2e...",
      "cut": "hard",
      "why": "Tracking shot, low energy — earns the listener's ear before the first hit."
    },
    ...
  ]
}
```

## CLI

```
prism cut --song SONG --clips DIR [--out DIR] [--aspect both|16:9|9:16]
```

| Flag | Default | Meaning |
|---|---|---|
| `--song` | required | Path to a copyright-free audio file. |
| `--clips` | required | Folder of `.mp4/.mov/.jpg/.png/...`. |
| `--out` | `./out` | Output directory. |
| `--aspect` | `both` | `16:9`, `9:16`, or `both`. |
| `--cache` | `.prism-cache` | Keyframes + Claude tags cached per-clip. |

## Why Opus 4.7

Prism doesn't "call an LLM for a vibe." It hands Claude two separate, non-trivial jobs:

1. **Per-clip vision reasoning.** Claude sees four keyframes + motion/brightness stats for each clip and returns a structured `ClipTags` — mood, 1–10 energy, motion type, a tagged `best_use` (intro / build / drop / breakdown / outro), and a one-sentence director's note.
2. **Global edit planning.** Claude receives the full `BeatGrid` (tempo, section boundaries, per-beat energy) alongside every `ClipTags`, and returns a beat-by-beat `EditPlan`: which clip on which beat, what cut style, and *why*. The `directors_note` on the plan is the overall creative vision.

This is a model acting as a collaborator, not a classifier.

## Status

Built during the **Built with Opus 4.7** hackathon (Apr 21–26, 2026). Fully open source (MIT).

## License

MIT. See [LICENSE](LICENSE).
