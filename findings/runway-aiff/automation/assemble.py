"""assemble.py — ffmpeg-based assembly of the AIFF teaser.

Inputs:
  ../clips/B01.mp4 ... B05.mp4       (xAI Imagine B-roll)
  ../clips/dec2024-ken-*.mp4         (user-downloaded Dec-2024 Ken Act-One clips)
  ../clips/dec2024-fizz-*.mp4        (user-downloaded Dec-2024 Fizzlepuff Gen-3 clips)
  ../audio/*.mp3                     (ElevenLabs VO lines)
  ../audio/music-bed.mp3             (CC0 newsroom bed — user-provided)
  ../audio/vo-manifest.json          (timing data)

Outputs:
  ../master.mp4                      (final 60-90s teaser, H.264 1080p 24fps)
  ../master-edl.json                 (timeline EDL for verification)

This is the orchestrator. Run after xai_batch + elevenlabs_vo + user-Dec2024
downloads complete. Idempotent — re-runs use cached probe data when possible.
"""
from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
import textwrap
from dataclasses import dataclass, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
CLIPS_DIR = PROJECT_ROOT / "clips"
AUDIO_DIR = PROJECT_ROOT / "audio"
MASTER = PROJECT_ROOT / "master.mp4"
EDL = PROJECT_ROOT / "master-edl.json"


def ffprobe_duration(path: Path) -> float:
    """Get duration in seconds via ffprobe."""
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
    out = subprocess.check_output(cmd, text=True).strip()
    return float(out) if out else 0.0


def _make_chyron_png(text: str, out_path: Path, size: tuple = (1920, 1080)) -> None:
    """Render a chyron lower-third as a transparent PNG overlay using PIL.
    Avoids ffmpeg drawtext (which requires freetype, missing in slim brew bottle).
    Lower-third style: dark translucent strip across bottom 10% with text, left-aligned."""
    from PIL import Image, ImageDraw, ImageFont
    W, H = size
    strip_top = int(H * 0.85)
    strip_h = int(H * 0.10)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Dark translucent strip
    d.rectangle([0, strip_top, W, strip_top + strip_h], fill=(0, 0, 0, 180))
    # Mint accent bar on left
    d.rectangle([0, strip_top, 12, strip_top + strip_h], fill=(102, 221, 170, 255))
    # Text — auto-shrink to fit width
    font_paths = [
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    ttf = next((p for p in font_paths if Path(p).exists()), None)
    if ttf:
        max_w = W - 120
        for sz in (44, 40, 36, 32, 28):
            f = ImageFont.truetype(ttf, sz)
            tw = d.textlength(text, font=f)
            if tw <= max_w:
                break
        bbox = d.textbbox((0, 0), text, font=f)
        tx = 60
        ty = strip_top + (strip_h - (bbox[3] - bbox[1])) // 2 - bbox[1]
        d.text((tx, ty), text, fill=(255, 255, 255, 255), font=f)
    img.save(out_path, "PNG")


def run(cmd: list[str], log: bool = True) -> None:
    if log:
        print("$", " ".join(shlex.quote(c) for c in cmd))
    subprocess.run(cmd, check=True)


@dataclass
class Cue:
    """One timeline cue — a video segment with optional VO overlay + chyron."""
    t_start: float       # timeline position (seconds)
    duration: float      # how long this cue holds the timeline
    visual: Path         # video source file
    visual_in: float     # in-point in the source clip
    vo: Path | None = None       # VO audio file aligned to start of cue
    chyron: str | None = None    # lower-third text
    label: str = ""              # human-readable label


def build_edl() -> list[Cue]:
    """v3 EDL — hackathon cut. ~150s. 12-beat structure from winning-demo-structure.md.

    Harrison Gale narrator (replaces Brian + Charlie). Hero 44ms motion graphic
    replaces drawtext chyron. Beat 3 placeholder until live voice turn captured.
    Beats 13-14 placeholder until vhs hooks-sting recorded.
    Beat 18 placeholder until p5.js agent swimlane built.
    """
    cues_v3: list[Cue] = []
    t = 0.0
    a = AUDIO_DIR
    c = CLIPS_DIR

    # ===== B1 — 911 dispatch, "How fast can help arrive" (0:00–0:08) =====
    cues_v3.append(Cue(t, 4.0, c / "C01.mp4", 0.0,
                       vo=a / "v3-B1-question-harrison.mp3",
                       chyron="GOATnote · prism42",
                       label="B1-dispatch"))
    t += 4.0
    cues_v3.append(Cue(t, 4.0, c / "C02.mp4", 0.0,
                       chyron="how fast can help arrive",
                       label="B1-headset"))
    t += 4.0

    # ===== B2 — Physician build, 5 days, <50ms (0:08–0:20) =====
    cues_v3.append(Cue(t, 6.0, c / "C03.mp4", 0.0,
                       vo=a / "v3-B2-physician-harrison.mp3",
                       chyron="Brandon Dent, MD · solo build",
                       label="B2-stakes"))
    t += 6.0
    cues_v3.append(Cue(t, 6.0, c / "C04.mp4", 0.0,
                       chyron="five days · between hospital shifts",
                       label="B2-emt"))
    t += 6.0

    # ===== B3 — LIVE VOICE TURN placeholder (0:20–0:35) =====
    # TODO: replace with live screen recording of bench_b300.py running on B300
    cues_v3.append(Cue(t, 15.0, c / "C07.mp4", 0.0,
                       chyron="LIVE — voice turn (placeholder until pod capture)",
                       label="B3-live-voice-turn-PLACEHOLDER"))
    t += 15.0

    # ===== B4 — TTFT 1655 → 44 reveal (0:35–0:55) =====
    # The hero motion graphic is 7s; bracket with 911 dispatch B-roll for context
    cues_v3.append(Cue(t, 6.0, c / "C09.mp4", 0.0,
                       vo=a / "v3-B4-baseline-harrison.mp3",
                       chyron="hosted API baseline",
                       label="B4-baseline-context"))
    t += 6.0
    cues_v3.append(Cue(t, 7.0, c / "HERO_44ms.mp4", 0.0,
                       label="B4-HERO-44ms"))
    t += 7.0
    cues_v3.append(Cue(t, 7.0, c / "B01.mp4", 0.0,
                       chyron="−91.6%",
                       label="B4-gpu-context"))
    t += 7.0

    # ===== B5 — Native sm_103 codegen, NVFP4, vLLM rebuild (0:55–1:10) =====
    cues_v3.append(Cue(t, 8.0, c / "B03.mp4", 0.0,
                       vo=a / "v3-B5-codegen-harrison.mp3",
                       chyron="sm_103 native · NVFP4 · CUDA 13 · vLLM rebuilt",
                       label="B5-codegen"))
    t += 8.0
    cues_v3.append(Cue(t, 7.0, c / "B02.mp4", 0.0,
                       chyron="B300 SXM6 AC",
                       label="B5-rack"))
    t += 7.0

    # ===== B6 — Three things broke (1:10–1:25) =====
    cues_v3.append(Cue(t, 12.0, c / "B03.mp4", 0.0,
                       vo=a / "v3-B6-broke-harrison.mp3",
                       chyron="honesty audit · three things broke first",
                       label="B6-honesty"))
    t += 12.0
    cues_v3.append(Cue(t, 3.0, c / "C05.mp4", 0.0,
                       label="B6-tail"))
    t += 3.0

    # ===== B7 — Opus 4.7 adaptive thinking + Opus self-monologue (1:25–1:50) =====
    cues_v3.append(Cue(t, 8.0, c / "B01.mp4", 0.0,
                       vo=a / "v3-B7a-opus-intro-harrison.mp3",
                       chyron="adaptive thinking · display omitted · task budgets",
                       label="B7a-opus-intro"))
    t += 8.0
    # The Opus 4.7 self-monologue (16s)
    cues_v3.append(Cue(t, 16.0, c / "C07.mp4", 0.0,
                       vo=a / "v3-opus-self-harrison.mp3",
                       chyron="Voice: ElevenLabs.  Words: Opus 4.7, unedited.",
                       label="B7b-opus-self"))
    t += 16.0
    cues_v3.append(Cue(t, 3.0, c / "B04.mp4", 0.0,
                       vo=a / "v3-B7c-attribution-harrison.mp3",
                       label="B7c-attribution"))
    t += 3.0

    # ===== B8 — Managed Agents parallel threads (1:50–2:15) =====
    # TODO: replace with p5.js agent swimlane animation
    cues_v3.append(Cue(t, 12.0, c / "B02.mp4", 0.0,
                       vo=a / "v3-B8-managed-agents-harrison.mp3",
                       chyron="Managed Agents · agent_toolset_20260401",
                       label="B8-managed-agents-PLACEHOLDER"))
    t += 12.0
    cues_v3.append(Cue(t, 8.0, c / "C07.mp4", 0.0,
                       chyron="coordinator · dispatcher · auditor · in parallel",
                       label="B8-tail"))
    t += 8.0

    # ===== B9 — E2E p95 4.4s (2:15–2:30) =====
    cues_v3.append(Cue(t, 15.0, c / "C09.mp4", 0.0,
                       vo=a / "v3-B9-e2e-harrison.mp3",
                       chyron="end-to-end p95 · 4.4 seconds",
                       label="B9-e2e"))
    t += 15.0

    # ===== B10 — Built between hospital shifts (2:30–2:45) =====
    cues_v3.append(Cue(t, 7.0, c / "C04.mp4", 0.0,
                       vo=a / "v3-B10-shifts-harrison.mp3",
                       chyron="five days · one developer",
                       label="B10-shifts"))
    t += 7.0
    cues_v3.append(Cue(t, 8.0, c / "C01.mp4", 0.0,
                       chyron="Brandon Dent, MD",
                       label="B10-room"))
    t += 8.0

    # ===== B11 — GitHub repo (2:45–2:55) =====
    cues_v3.append(Cue(t, 10.0, c / "B05.mp4", 0.0,
                       vo=a / "v3-B11-repo-harrison.mp3",
                       chyron="github.com/GOATnote-Inc/prism42  ·  Apache 2.0",
                       label="B11-repo"))
    t += 10.0

    # ===== B12 — End card (2:55–3:00) =====
    cues_v3.append(Cue(t, 5.0, c / "B04.mp4", 0.0,
                       chyron="prism42 — answer in 44 ms",
                       label="B12-endcard"))
    t += 5.0

    return cues_v3
    cues: list[Cue] = []
    t = 0.0
    a = AUDIO_DIR
    c = CLIPS_DIR

    # ===== SEGMENT 1 — Cold Open (0:00–14.17) =====
    cues.append(Cue(t, 7.48, c / "C01.mp4", 0.0,
                    vo=a / "v2-S1-bumper-brian.mp3",
                    chyron="GOATnote Nightly · Special Report",
                    label="S1-bumper"))
    t += 7.48
    cues.append(Cue(t, 6.69, c / "C02.mp4", 0.0,
                    vo=a / "v2-S1-tease-brian.mp3",
                    chyron="PRISM42 · solo developer build",
                    label="S1-tease"))
    t += 6.69

    # ===== SEGMENT 2 — Field Stringer Cold (14.17–26.80) =====
    cues.append(Cue(t, 11.56, c / "C03.mp4", 0.0,
                    vo=a / "v2-S2-stringer-charlie.mp3",
                    chyron="FIELD — REPORTING IN",
                    label="S2-stringer"))
    t += 11.56
    cues.append(Cue(t, 1.07, c / "C03.mp4", 4.0,
                    vo=a / "v2-S2-stay-brian.mp3",
                    label="S2-stay"))
    t += 1.07

    # ===== SEGMENT 3 — Hardware (26.80–66.55) =====
    # vo build (16.53s) carries across C04 -> B02 -> B01
    cues.append(Cue(t, 6.0, c / "C04.mp4", 0.0,
                    vo=a / "v2-S3-build-brian.mp3",
                    chyron="THE BUILD", label="S3-emt"))
    t += 6.0
    cues.append(Cue(t, 6.0, c / "B02.mp4", 0.0,
                    chyron="THE BUILD", label="S3-servers"))
    t += 6.0
    cues.append(Cue(t, 4.53, c / "B01.mp4", 0.0,
                    chyron="THE BUILD", label="S3-gpu"))
    t += 4.53
    # vo broke (23.22s) across B03 -> C05 -> C06 -> tail
    cues.append(Cue(t, 6.0, c / "B03.mp4", 0.0,
                    vo=a / "v2-S3-broke-brian.mp3",
                    chyron="three things broke before anything worked",
                    label="S3-broke-board"))
    t += 6.0
    cues.append(Cue(t, 5.0, c / "C05.mp4", 0.0,
                    chyron="three things broke before anything worked",
                    label="S3-broke-police"))
    t += 5.0
    cues.append(Cue(t, 5.0, c / "C06.mp4", 0.0,
                    chyron="three things broke before anything worked",
                    label="S3-broke-fire"))
    t += 5.0
    cues.append(Cue(t, 7.22, c / "B03.mp4", 0.0,
                    chyron="three things broke before anything worked",
                    label="S3-broke-tail"))
    t += 7.22

    # ===== SEGMENT 4 — Engineering Breaking News (66.55–93.91) =====
    cues.append(Cue(t, 8.0, c / "C07.mp4", 0.0,
                    vo=a / "v2-S4-firstboot-brian.mp3",
                    chyron="ENGINEERING BREAKING NEWS",
                    label="S4-firstboot"))
    t += 8.0
    cues.append(Cue(t, 9.18, c / "B01.mp4", 0.0,
                    chyron="ENGINEERING BREAKING NEWS",
                    label="S4-firstboot-cont"))
    t += 9.18
    # 44ms reveal
    cues.append(Cue(t, 7.11, c / "B04.mp4", 0.0,
                    vo=a / "v2-S4-passed-brian.mp3",
                    chyron="44 ms · TTFT p95",
                    label="S4-44ms"))
    t += 7.11
    cues.append(Cue(t, 3.07, c / "C03.mp4", 0.0,
                    vo=a / "v2-S4-quiet-charlie.mp3",
                    chyron="latency of a well-rested human",
                    label="S4-quiet"))
    t += 3.07

    # ===== SEGMENT 5 — Closer (93.91–108.9) =====
    cues.append(Cue(t, 5.0, c / "C08.mp4", 0.0,
                    vo=a / "v2-S5-closer-brian.mp3",
                    chyron="five days · one developer",
                    label="S5-closer-skyline"))
    t += 5.0
    cues.append(Cue(t, 5.82, c / "C09.mp4", 0.0,
                    chyron="five days · one developer",
                    label="S5-closer-dawn"))
    t += 5.82
    cues.append(Cue(t, 2.97, c / "C09.mp4", 3.0,
                    vo=a / "v2-S5-room-brian.mp3",
                    chyron="GOATnote Nightly · AIFF 2026",
                    label="S5-room"))
    t += 2.97
    cues.append(Cue(t, 1.21, c / "B04.mp4", 0.0,
                    vo=a / "v2-S5-button-charlie.mp3",
                    chyron="GOATnote Nightly · AIFF 2026",
                    label="S5-button"))
    t += 1.21

    return cues


def first_existing(*paths: Path) -> Path:
    """Return first path that exists; else the last one (visible failure)."""
    for p in paths:
        if p.exists() and p.stat().st_size > 1024:
            return p
    return paths[-1]


def render(cues: list[Cue], out_path: Path = MASTER) -> None:
    """Build the master via per-cue clip extraction → concat → audio mix.

    Strategy:
      1. For each cue: extract subclip via -ss/-t into temp file with chyron drawtext burned in.
      2. concat demuxer joins all subclips.
      3. Mix VO + music bed under the concatenated visual.
      4. Final encode H.264 1080p 24fps.
    """
    work = ROOT / "work"
    work.mkdir(exist_ok=True)
    sub_paths: list[Path] = []
    vo_concat_lines: list[str] = []   # ffmpeg amix-friendly inputs with delays

    print(f"=== rendering {len(cues)} cues to {out_path.name} ===")
    for i, cue in enumerate(cues):
        sub = work / f"sub-{i:02d}-{cue.label}.mp4"
        sub_paths.append(sub)
        if not cue.visual.exists():
            print(f"  cue {i:02d} MISSING visual {cue.visual.name} — using black slate")
            # Generate a black slate of correct duration
            run(["ffmpeg", "-y", "-f", "lavfi",
                 "-i", f"color=c=black:s=1920x1080:d={cue.duration}:r=24",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                 "-pix_fmt", "yuv420p", str(sub)])
            continue
        # Probe source duration; loop if cue needs more
        try:
            src_dur = ffprobe_duration(cue.visual)
        except Exception:
            src_dur = 0.0
        needs_loop = (cue.visual_in + cue.duration) > src_dur - 0.05

        # Generate chyron overlay PNG (PIL — bypasses ffmpeg drawtext freetype requirement)
        chyron_png = None
        if cue.chyron:
            chyron_png = work / f"chyron-{i:02d}.png"
            _make_chyron_png(cue.chyron, chyron_png)

        vf = "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:-1:-1:color=black"
        # Force exact output frame count to avoid -stream_loop + filter_complex duration confusion
        n_frames = int(round(cue.duration * 24))
        cmd = ["ffmpeg", "-y"]
        if needs_loop:
            cmd += ["-stream_loop", "-1", "-i", str(cue.visual)]
        else:
            cmd += ["-ss", f"{cue.visual_in}", "-i", str(cue.visual)]
        if chyron_png:
            cmd += ["-i", str(chyron_png),
                    "-filter_complex",
                    f"[0:v]{vf}[base];[base][1:v]overlay=0:0[outv]",
                    "-map", "[outv]"]
        else:
            cmd += ["-vf", vf]
        # -frames:v caps the OUTPUT at exact frame count (fixes runaway-loop bug)
        cmd += ["-frames:v", str(n_frames),
                "-r", "24",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-pix_fmt", "yuv420p", "-an", str(sub)]
        run(cmd)

    # Concat
    concat_file = work / "concat.txt"
    concat_file.write_text("\n".join(f"file '{p.resolve()}'" for p in sub_paths))
    visual_only = work / "visual.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
         "-c", "copy", str(visual_only)])

    # Mix audio: VO lines at cue starts + music bed under everything
    audio_inputs: list[str] = []
    audio_filter_parts: list[str] = []
    audio_idx = 0
    for cue in cues:
        if cue.vo and cue.vo.exists():
            audio_inputs.extend(["-i", str(cue.vo)])
            delay_ms = int(cue.t_start * 1000)
            audio_filter_parts.append(f"[{audio_idx + 1}:a]adelay={delay_ms}|{delay_ms},volume=1.0[vo{audio_idx}]")
            audio_idx += 1

    music_path = AUDIO_DIR / "music-bed.mp3"
    has_music = music_path.exists()
    music_input_idx = None
    if has_music:
        audio_inputs.extend(["-i", str(music_path)])
        music_input_idx = audio_idx + 1
        audio_filter_parts.append(f"[{music_input_idx}:a]volume=0.18,afade=t=in:st=0:d=1.5[bed]")

    vo_labels = "".join(f"[vo{i}]" for i in range(audio_idx))
    if vo_labels and has_music:
        audio_filter_parts.append(f"{vo_labels}[bed]amix=inputs={audio_idx + 1}:dropout_transition=0:normalize=0[a]")
    elif vo_labels:
        audio_filter_parts.append(f"{vo_labels}amix=inputs={audio_idx}:dropout_transition=0:normalize=0[a]")
    elif has_music:
        audio_filter_parts.append(f"[bed]anull[a]")

    if not audio_filter_parts:
        # No audio at all — copy visual only
        run(["ffmpeg", "-y", "-i", str(visual_only), "-c", "copy", str(out_path)])
        return

    cmd = ["ffmpeg", "-y", "-i", str(visual_only), *audio_inputs,
           "-filter_complex", ";".join(audio_filter_parts),
           "-map", "0:v", "-map", "[a]",
           "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
           "-shortest", str(out_path)]
    run(cmd)
    print(f"\n=== master rendered: {out_path} ({out_path.stat().st_size/1e6:.1f} MB) ===")


def main() -> None:
    cues = build_edl()
    EDL.write_text(json.dumps([{**asdict(c), "visual": str(c.visual),
                                "vo": str(c.vo) if c.vo else None} for c in cues],
                              indent=2))
    print(f"EDL written: {EDL}")
    print(f"  {len(cues)} cues, total duration {cues[-1].t_start + cues[-1].duration:.1f}s")
    # Check what's missing
    missing = []
    for c in cues:
        if not c.visual.exists() or c.visual.stat().st_size < 1024:
            missing.append(("visual", c.label, str(c.visual)))
        if c.vo and (not c.vo.exists() or c.vo.stat().st_size < 1024):
            missing.append(("vo", c.label, str(c.vo)))
    if missing:
        print(f"\n=== MISSING ASSETS ({len(missing)}) ===")
        for kind, label, path in missing:
            print(f"  {kind:6} {label:25} {path}")
        print("\nrender will use black slate / no-audio for missing pieces.")

    render(cues)


if __name__ == "__main__":
    main()
