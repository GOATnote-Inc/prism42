"""ffmpeg-based assembly: cut every segment to its beat interval, concat, mux."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ..models import ClipProfile, EditPlan

FPS = 30


def aspect_dims(aspect: str) -> tuple[int, int]:
    return (1080, 1920) if aspect == "9:16" else (1920, 1080)


def _clip_by_id(profiles: list[ClipProfile], cid: str) -> ClipProfile:
    for p in profiles:
        if p.clip_id == cid:
            return p
    raise KeyError(cid)


def _scale_crop_vf(aspect: str) -> str:
    w, h = aspect_dims(aspect)
    return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"


def _render_segment(
    profile: ClipProfile,
    duration: float,
    out_path: Path,
    aspect: str,
    source_start: float = 0.0,
) -> None:
    vf = _scale_crop_vf(aspect)
    is_image = profile.fps == 0.0

    if is_image:
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-t", f"{duration:.3f}",
            "-i", profile.path, "-an",
            "-vf", vf, "-r", str(FPS),
            "-c:v", "libx264", "-preset", "veryfast",
            "-pix_fmt", "yuv420p",
            str(out_path),
        ]
    elif profile.duration >= duration:
        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{source_start:.3f}", "-i", profile.path,
            "-t", f"{duration:.3f}", "-an",
            "-vf", vf, "-r", str(FPS),
            "-c:v", "libx264", "-preset", "veryfast",
            "-pix_fmt", "yuv420p",
            str(out_path),
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", "-1", "-i", profile.path,
            "-t", f"{duration:.3f}", "-an",
            "-vf", vf, "-r", str(FPS),
            "-c:v", "libx264", "-preset", "veryfast",
            "-pix_fmt", "yuv420p",
            str(out_path),
        ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg segment failed for {profile.path}: {r.stderr[-600:]}")


def render(
    plan: EditPlan,
    profiles: list[ClipProfile],
    song_path: str,
    out_path: str,
    work_dir: str = ".prism-cache/render",
) -> None:
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    concat_list = work / "concat.txt"
    lines: list[str] = []
    for i, seg in enumerate(plan.segments):
        profile = _clip_by_id(profiles, seg.clip_id)
        dur = seg.beat_end - seg.beat_start
        if dur <= 0.033:  # < 1 frame at 30fps — skip
            continue
        seg_path = work / f"seg_{i:05d}.mp4"
        _render_segment(profile, dur, seg_path, plan.aspect, source_start=seg.source_start)
        lines.append(f"file '{seg_path.resolve()}'\n")

    concat_list.write_text("".join(lines))

    silent_out = work / "silent.mp4"
    r = subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy",
            str(silent_out),
        ],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg concat failed: {r.stderr[-600:]}")

    r = subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", str(silent_out),
            "-i", song_path,
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-map", "0:v:0", "-map", "1:a:0",
            "-shortest",
            str(out_path),
        ],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg mux failed: {r.stderr[-600:]}")


def write_directors_notes(plan: EditPlan, path: str) -> None:
    data = {
        "aspect": plan.aspect,
        "song": plan.song_path,
        "overall_note": plan.directors_note,
        "segments": [
            {
                "beat": f"{s.beat_start:.2f}-{s.beat_end:.2f}",
                "duration": round(s.beat_end - s.beat_start, 3),
                "clip": s.clip_id,
                "cut": s.cut_style,
                "why": s.reasoning,
            }
            for s in plan.segments
        ],
    }
    Path(path).write_text(json.dumps(data, indent=2))
