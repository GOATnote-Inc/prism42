"""The heart of Prism: Claude Opus 4.7 as the creative director."""

from __future__ import annotations

import json
import os

from anthropic import Anthropic

from ..models import BeatGrid, ClipTags, EditPlan, EditSegment

DEFAULT_MODEL = os.environ.get("PRISM_MODEL", "claude-opus-4-7")

SYSTEM = """You are Prism — an AI music-video editor.

You receive:
1. A BeatGrid: song tempo, beat timestamps, per-beat energy (0-1), and section boundaries.
2. A list of ClipTags: each clip's mood, energy (1-10), motion_type, subject, best_use,
   and a short director's note.

Produce an EditPlan that cuts on EVERY beat. Rules:
- Match song energy to clip energy (song energy 0.8+ wants clip energy 7+).
- Respect best_use hints (intro clips early; drop clips on high-energy sections).
- Never repeat the same clip on two consecutive beats.
- Group thematically-adjacent clips inside a section.
- Every beat interval must have exactly one clip.
- Prefer rapid/chaotic motion on beats with high energy; static/subtle on low-energy.

Output ONLY this JSON (no fences, no prose):
{
  "directors_note": "<2-4 sentences; your overall creative vision for this edit>",
  "segments": [
    {
      "beat_index": <int 0..N-2>,
      "clip_id": "<id from the clips list>",
      "cut_style": "hard|whip|flash|dip",
      "reasoning": "<one short sentence>"
    }
  ]
}

beat_index = i means the segment fills the interval [beats[i], beats[i+1]]."""


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
    text = text.strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        text = text[start : end + 1]
    return json.loads(text)


def _compact_grid(grid: BeatGrid) -> dict:
    intervals = []
    for i in range(len(grid.beats) - 1):
        intervals.append(
            {
                "i": i,
                "start": round(grid.beats[i], 3),
                "end": round(grid.beats[i + 1], 3),
                "energy": round(grid.energy[i], 2) if i < len(grid.energy) else 0.5,
            }
        )
    sections = [
        {
            "start": round(s["start"], 2),
            "end": round(s["end"], 2),
            "label": s["label"],
        }
        for s in grid.sections
    ]
    return {
        "tempo": round(grid.tempo, 1),
        "duration": round(grid.duration, 1),
        "sections": sections,
        "beats": intervals,
    }


def plan_edit(
    grid: BeatGrid,
    tags: list[ClipTags],
    aspect: str = "16:9",
    model: str = DEFAULT_MODEL,
) -> EditPlan:
    client = Anthropic()
    payload = {
        "aspect": aspect,
        "grid": _compact_grid(grid),
        "clips": [t.model_dump() for t in tags],
    }

    # Roughly 8k tokens headroom; plans scale linearly with beat count.
    msg = client.messages.create(
        model=model,
        max_tokens=16000,
        system=SYSTEM,
        messages=[{"role": "user", "content": json.dumps(payload)}],
    )
    text = msg.content[0].text if msg.content and hasattr(msg.content[0], "text") else ""
    parsed = _extract_json(text)

    valid_ids = {t.clip_id for t in tags}
    segments: list[EditSegment] = []
    last_id: str | None = None
    for seg in parsed.get("segments", []):
        i = int(seg.get("beat_index", -1))
        if i < 0 or i >= len(grid.beats) - 1:
            continue
        cid = seg.get("clip_id")
        if cid not in valid_ids:
            continue
        # Enforce no-repeat
        if cid == last_id:
            # swap with any other available clip
            alt = next((x for x in valid_ids if x != last_id), cid)
            cid = alt
        bs, be = grid.beats[i], grid.beats[i + 1]
        dur = be - bs
        segments.append(
            EditSegment(
                clip_id=cid,
                source_start=0.0,
                source_end=dur,
                beat_start=bs,
                beat_end=be,
                cut_style=seg.get("cut_style", "hard"),
                reasoning=seg.get("reasoning", ""),
            )
        )
        last_id = cid

    # If the model skipped beats, fill from the tag list round-robin.
    # Rebuild in beat order, filling gaps.
    by_index: dict[int, EditSegment] = {}
    for s in segments:
        for i in range(len(grid.beats) - 1):
            if abs(grid.beats[i] - s.beat_start) < 1e-4:
                by_index[i] = s
                break
    ordered: list[EditSegment] = []
    rr = 0
    last_id = None
    tag_ids = [t.clip_id for t in tags]
    for i in range(len(grid.beats) - 1):
        if i in by_index:
            ordered.append(by_index[i])
            last_id = by_index[i].clip_id
            continue
        # fallback: round-robin, skip repeats
        cid = tag_ids[rr % len(tag_ids)]
        rr += 1
        if cid == last_id and len(tag_ids) > 1:
            cid = tag_ids[rr % len(tag_ids)]
            rr += 1
        bs, be = grid.beats[i], grid.beats[i + 1]
        ordered.append(
            EditSegment(
                clip_id=cid,
                source_start=0.0,
                source_end=be - bs,
                beat_start=bs,
                beat_end=be,
                cut_style="hard",
                reasoning="fill (director did not specify)",
            )
        )
        last_id = cid

    return EditPlan(
        song_path=grid.path,
        aspect=aspect,
        segments=ordered,
        directors_note=parsed.get("directors_note", ""),
    )
