# Prism — Engineer Handoff

**Last updated:** 2026-04-21 21:45 PDT · **Hackathon day 1 of 6** · **Submission due: 2026-04-26 20:00 EST**

---

## TL;DR

A beat-matched music-video splicing engine where Claude Opus 4.7 acts as the creative director. CLI + streamlit UI both work. `--dry` smoke-tested end-to-end (117 BPM detection → 40 cuts → 1920×1080 h264+aac MP4 + `director.json`). Live Claude run has NOT been executed yet — that's the first thing to do.

## Status matrix

| Component | State | Verified how |
|---|---|---|
| `src/prism/models.py` | ✅ frozen | 3/3 pytest |
| `src/prism/audio/analyze.py` | ✅ working | 117 BPM detected on synthetic 120 BPM test song, 41 beats, 2 clean sections |
| `src/prism/vision/ingest.py` | ✅ working | 10/10 clips profiled (8 video + 2 image), keyframes cached to `.prism-cache/<clip_id>/` |
| `src/prism/vision/tag.py` | ⚠️ untested live | Code reviewed; cache logic + JSON extraction robust. NOT YET CALLED WITH REAL KEY. |
| `src/prism/director/plan.py` | ⚠️ untested live | Code reviewed; has fallback round-robin fill for model-skipped beats. NOT YET CALLED WITH REAL KEY. |
| `src/prism/assembly/render.py` | ✅ working | Dry mode produced 20s/1920×1080/30fps/h264+aac MP4 of correct duration |
| `src/prism/cli.py` | ✅ working | `prism --help`, `prism cut --help`, `prism cut … --dry` all green |
| `streamlit_app.py` | ✅ syntax-clean | `py_compile` passes. NOT YET LAUNCHED (sandbox blocks port binding). |
| `scripts/make_sample_assets.py` | ✅ working | Generates 20s 120 BPM test song + 8 colored clips + 2 stills, all via ffmpeg lavfi |
| `tests/test_models.py` | ✅ 3/3 pass | `pytest -q` |
| **Ruff** | ✅ clean | `ruff check` — all checks passed |

## Architecture in 30 seconds

```
song.mp3 ─┐                            ┌─ ClipProfile (duration, motion, keyframes)
          ▼                            ▼
    [librosa analyze]              [ffprobe + cv2 ingest]
          │                            │
          ▼                            ▼
       BeatGrid                     ClipProfile list
      (beats,                            │
       sections,                         ▼
       energy)                    [Claude Opus 4.7 vision tag]
          │                            │
          └──────────┬─────────────────┘
                     ▼
             [Claude Opus 4.7 director.plan_edit]
                     │
                     ▼
                  EditPlan  (segments + directors_note)
                     │
                     ▼
              [ffmpeg render + mux]
                     │
                     ▼
          song__16x9.mp4  +  song__9x16.mp4  +  director.json
```

All inter-module values are pydantic — contracts live in `src/prism/models.py`.

## Setup — fresh laptop, one command

```bash
bash scripts/bootstrap.sh
```

That script is idempotent. It installs `ffmpeg` (brew on macOS, apt on Linux),
finds or requires Python ≥3.11, creates `.venv/`, pip-installs the package
editable with dev+ui extras, synthesizes test assets if missing, runs the
`--dry` pipeline, and runs pytest. You should see a "✅ Dry render succeeded"
and "3 passed" at the end.

If bootstrap fails, read the error — the script says *why* it failed, not
just *that* it failed.

### After bootstrap

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
source .venv/bin/activate

make demo     # WITH Claude — costs ~$0.50-$1 per run on 10 clips
make ui       # streamlit UI at localhost:8501
make assets   # re-synth test song + clips (if deleted)
make dry      # no-API smoke
```

### Moving to a new laptop

`music-video/` is a subtree of the umbrella `GOATnote-Inc/prism` repo (which
also holds the separate GPU-kernel + clinical auditor project). Clone the
umbrella; work inside `music-video/`:

```bash
gh auth login                             # if not already
gh repo clone GOATnote-Inc/prism
cd prism/music-video
bash scripts/bootstrap.sh
```

The umbrella root has its own `CLAUDE.md` with project-wide discipline:
commit format `T-{id}: {subject}`, required `Co-Authored-By: Claude Opus 4.7
<noreply@anthropic.com>` footer, frozen paths (never touch them), and
verification gates. Read `prism/CLAUDE.md` first, then `prism/music-video/CLAUDE.md`
for the music-video rules.

## Non-obvious decisions + gotchas

1. **`brew` ffmpeg was compiled without `drawtext`** (no freetype). `scripts/make_sample_assets.py` avoids it. If you need text overlays, switch to rendering PNGs with Pillow and `overlay=`.
2. **`zoompan` with `d=N` produces N output frames per input frame** — not total frames. If you add motion filters, always cap with `-t duration` on the output.
3. **librosa `agglomerative` segmentation emits sliver boundaries** near 0 and `duration`. `audio/analyze.py` post-filters sections < `max(1.5s, duration/20)`.
4. **Typer collapses single-command apps**; we added a `version` subcommand solely so `prism cut …` parses. Don't remove it unless you restructure the CLI.
5. **Clip cache key** is `sha256(filename + size + mtime_ns)[:16]`. Replacing a file in place invalidates the cache automatically; renaming does not. That's intended — tags are semantic, not tied to path.
6. **ffmpeg `stream_loop` is used for clips shorter than their assigned beat interval**; frames are looped silently. If this causes visible stutter on long shots + fast tempos, switch to `-filter_complex` with `tile` instead.
7. **`EditPlan.segments[i].source_start` is always 0.0 today** — we cut from the start of each clip. Smart cue-point selection (e.g., land on a motion peak inside the clip) is a clear next improvement.
8. **Director plan JSON can exceed `max_tokens=16000`** on very long songs with many clips (>200 beats). Right now we fall back to round-robin for truncated plans. Long-song support needs either streaming or chunking by section.
9. **`.env` is gitignored; `.env.example` is the committed template.** Never commit `.env`.

## Hackathon rules (hard constraints)

- **Fully open source, MIT** — no closed components.
- **New work only** — all code written Apr 21+, first commit `d6b454c`.
- **Submission** — 3-min demo video + repo URL + 100-200 word summary at https://cerebralvalley.ai/e/built-with-4-7-hackathon/hackathon/submit by Apr 26 20:00 EST.
- **Repo visibility** — private until submission, then flip public. Do NOT push publicly before Apr 26.

## Open tasks (ordered)

1. **Live Claude smoke test** — `make demo` with `ANTHROPIC_API_KEY` set. Inspect `out/song__16x9__director.json` — is Claude's reasoning coherent? Does the plan respect `best_use`? If not, tune `SYSTEM` prompts in `src/prism/vision/tag.py` and `src/prism/director/plan.py`.
2. **Replace synthetic assets for the real demo** — find ~20 CC-BY clips + one CC-BY song (Pixabay Music, Pexels, FMA). Save to `examples/clips/` and `examples/song.mp3`. These are gitignored so no licensing risk to the repo.
3. **Record the 3-min demo video** — shot list in `docs/DEMO_SCRIPT.md`.
4. **Repo already exists** at `GOATnote-Inc/prism` (umbrella). `music-video/` is a subtree; push normally with `git push origin main`. Flip umbrella public at submission only if embargo allows (see root `CLAUDE.md` §6).
5. **Fill submission form** — summary ready in `docs/SUBMISSION.md`.

## Stretch improvements (if time allows)

- **Smart cue-point selection** (`EditSegment.source_start`): pick a moment inside each clip that lines up with the beat's energy. librosa-style onset detection on the clip's audio channel is one path.
- **Motion-matched transitions**: on high-energy beats pair a "whip" cut; on downbeats use "dip-to-black." Stub is in `EditSegment.cut_style` — ffmpeg filter graph needs to honor it.
- **Lyrics-aware planning**: if the song has vocals, transcribe with `whisper` → pass lyrics to the director so it can align images to phrases.
- **Downbeat detection upgrade**: current fallback is every-4th-beat. `madmom`'s RNN downbeat tracker is the correct tool but adds a heavy dep.
- **Streaming renders**: render segments to a named pipe; concat on the fly. Cuts latency on the streamlit UI.

## Key files to read first (if handed this cold)

1. `README.md` — what this is + quickstart
2. `src/prism/models.py` — the data contracts
3. `src/prism/director/plan.py` — the creative core
4. `CLAUDE.md` — agent guide / rules of engagement
5. `docs/SUBMISSION.md` + `docs/DEMO_SCRIPT.md` — hackathon context

## Contact

- GitHub: `bGOATnote`
- Email: `b@thegoatnote.com`
