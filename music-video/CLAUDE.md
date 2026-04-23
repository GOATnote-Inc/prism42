# Prism — Agent Guide

> **Project-specific rules for this repo.** For *general* Claude Code / agent
> best-practices (context engineering, tool design, skills, hooks, MCP,
> Managed Agents, prompt engineering), read `docs/BEST_PRACTICES.md`.

## Project Identity

**Prism** turns a folder of clips + a song into a beat-matched music video, with Claude Opus 4.7 acting as the creative director. Built during the Built with Opus 4.7 hackathon (Apr 21–26, 2026).

## Architecture

Five modules under `src/prism/`:

- `audio/analyze.py` — librosa beat tracking → `BeatGrid`
- `vision/ingest.py` — ffprobe + opencv per-clip probe → `ClipProfile`
- `vision/tag.py` — Opus 4.7 vision per clip → `ClipTags`
- `director/plan.py` — Opus 4.7 global planner → `EditPlan`
- `assembly/render.py` — ffmpeg concat + mux → MP4 + `director.json`

`models.py` holds all pydantic data contracts. Every module's public surface is typed.

## Rules of Engagement

1. **Opus 4.7 is the feature, not the dependency.** If you're writing rule-based code that picks clips, stop and hand it to the model instead. Creative judgment belongs to Claude.
2. **Cache aggressively.** Keyframes + `ClipTags` cache under `.prism-cache/<clip_id>/`. Never re-tag a clip the user already paid for.
3. **Pydantic contracts are canon.** Don't pass loose dicts between modules. If a shape changes, update `models.py` first.
4. **ffmpeg is the floor, not the ceiling.** Every rendered segment goes through `render_segment` — add filters there, not in callers.
5. **Secrets never touch the repo.** `ANTHROPIC_API_KEY` via env only. `.env` is gitignored.

## Hackathon constraints (until Apr 26 8PM EST)

- **No pre-existing code.** Everything must be new, written during the hackathon.
- **MIT licensed, fully open source.** No closed components.
- **Repo is private until submission.** Don't push public before the deadline.

## Commit style

`[area] short imperative description` — e.g. `[director] add overall director's note to EditPlan`.

## Running end-to-end

```
export ANTHROPIC_API_KEY=...
prism cut --song examples/song.mp3 --clips examples/clips --out out
```

## Debugging tips

- Clip tagging failed? Inspect `.prism-cache/<clip_id>/tags.json` — delete to retry.
- Plan JSON malformed? Bump `max_tokens` in `director/plan.py`; Claude sometimes truncates long plans.
- ffmpeg concat failed? Check `ffprobe` output on the offending segment; aspect/scale mismatch is the usual suspect.
