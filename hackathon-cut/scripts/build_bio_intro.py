"""build_bio_intro.py — sub-30s bio intro per viral-hooks.md drop-in shot table.

v1: uses ONLY existing assets (Ken_Fox.mp4, Fizzlepuff.mp4). Shots that need
new Runway/Veo gens fall back to creative reframes of existing footage + solid
slates with credential stamps. Once Runway research agent lands, we'll swap
those placeholders for proper B-roll.

Output: ../final/bio-intro-v1.mp4 (~29.5s, 1920x1080 24fps H.264 + AAC)
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
ASSETS = PROJECT / "assets"
VO = PROJECT / "vo"
FINAL = PROJECT / "final"
WORK = PROJECT / "work"
FINAL.mkdir(parents=True, exist_ok=True)
if WORK.exists():
    shutil.rmtree(WORK)
WORK.mkdir(parents=True, exist_ok=True)

KEN = ASSETS / "Ken_Fox.mp4"      # 12.04s, 1280x768, with audio
FIZZ = ASSETS / "Fizzlepuff.mp4"  # 5.21s,  1280x768, video only
VO_MIX = VO / "bio-intro-mix.mp3"  # 28.8s

FFMPEG = "/opt/homebrew/bin/ffmpeg"
W, H, FPS = 1920, 1080, 24
MINT = (127, 227, 196)        # #7FE3C4 per research
CHARCOAL = (10, 14, 20)
WHITE = (255, 255, 255)


@dataclass
class Shot:
    idx: int
    t_in: float       # timeline in (seconds, 0-based)
    t_out: float      # timeline out
    label: str
    source: Path      # mp4 to extract from (or None for slate)
    src_in: float     # in-point in source clip
    crop: str | None = None      # ffmpeg crop expr (e.g. "ih*0.6:ih*0.6:iw*0.2:ih*0.2")
    move: str | None = None      # zoompan / scale move (or None)
    overlay_png: Path | None = None
    note: str = ""


def font(sz: int):
    for p in ["/System/Library/Fonts/HelveticaNeue.ttc",
              "/System/Library/Fonts/Helvetica.ttc",
              "/System/Library/Fonts/Supplemental/Arial.ttf"]:
        if Path(p).exists():
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default()


def make_corner_mark(text: str, out_path: Path) -> None:
    """PRISM 42 / BUILT WITH OPUS 4.7 corner-mark."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = font(28)
    bbox = d.textbbox((0, 0), text, font=f)
    tw = bbox[2] - bbox[0]
    pad = 24
    x = W - tw - pad - 12
    y = H - pad - 36
    d.text((x, y), text, fill=(*MINT, 255), font=f)
    img.save(out_path, "PNG")


def make_credential_stamp(text: str, out_path: Path, two_line: bool = False) -> None:
    """Big mint credential stamp, mid-frame, with mint underline accent."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if two_line:
        lines = text.split(" · ")
        f = font(64)
        line_h = 90
        total_h = line_h * len(lines) + 18
        y0 = int(H * 0.42) - total_h // 2
        for i, line in enumerate(lines):
            bbox = d.textbbox((0, 0), line, font=f)
            tw = bbox[2] - bbox[0]
            x = (W - tw) // 2
            y = y0 + i * line_h
            # subtle drop shadow
            d.text((x + 3, y + 3), line, fill=(0, 0, 0, 200), font=f)
            d.text((x, y), line, fill=(*WHITE, 255), font=f)
        # underline
        u_y = y0 + total_h
        d.rectangle([(W - 220) // 2, u_y, (W + 220) // 2, u_y + 6], fill=(*MINT, 255))
    else:
        f = font(72)
        bbox = d.textbbox((0, 0), text, font=f)
        tw = bbox[2] - bbox[0]
        x = (W - tw) // 2
        y = int(H * 0.78)
        d.text((x + 3, y + 3), text, fill=(0, 0, 0, 200), font=f)
        d.text((x, y), text, fill=(*WHITE, 255), font=f)
        u_y = y + 90
        d.rectangle([(W - 180) // 2, u_y, (W + 180) // 2, u_y + 5], fill=(*MINT, 255))
    img.save(out_path, "PNG")


def make_lower_third(name: str, role: str, out_path: Path) -> None:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    strip_top = int(H * 0.84)
    strip_h = int(H * 0.11)
    d.rectangle([0, strip_top, W, strip_top + strip_h], fill=(0, 0, 0, 200))
    d.rectangle([0, strip_top, 14, strip_top + strip_h], fill=(*MINT, 255))
    d.text((60, strip_top + 16), name, fill=WHITE, font=font(48))
    d.text((60, strip_top + 76), role, fill=MINT, font=font(28))
    img.save(out_path, "PNG")


def make_kinetic_label(text: str, accent: bool, out_path: Path) -> None:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = font(48)
    bbox = d.textbbox((0, 0), text, font=f)
    tw = bbox[2] - bbox[0]
    pad = 48
    x = W - tw - pad - 24
    y = pad
    d.rectangle([x - 16, y - 8, x + tw + 16, y + 64], fill=(0, 0, 0, 200))
    d.text((x, y), text, fill=WHITE, font=f)
    if accent:
        d.rectangle([x - 16, y + 60, x + tw + 16, y + 66], fill=(*MINT, 255))
    img.save(out_path, "PNG")


def make_slate(text: str, out_path: Path) -> None:
    """Solid-charcoal slate with caption — placeholder for shots needing new gens."""
    img = Image.new("RGB", (W, H), CHARCOAL)
    d = ImageDraw.Draw(img)
    # subtle vignette
    f = font(54)
    bbox = d.textbbox((0, 0), text, font=f)
    tw = bbox[2] - bbox[0]
    d.text(((W - tw) // 2, (H - 60) // 2), text, fill=(*MINT, 220), font=f)
    img.save(out_path, "PNG")


def run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(" ".join(cmd))
        print(r.stderr[-800:])
        raise RuntimeError(f"ffmpeg failed exit {r.returncode}")


def cut_clip(src: Path, t_in: float, dur: float, out: Path,
             crop: str | None = None, move: str | None = None,
             overlay: Path | None = None) -> None:
    """Extract subclip, scale to 1920x1080, optional crop/move, optional overlay."""
    n_frames = max(2, int(round(dur * FPS)))
    inputs: list[str] = []
    if src.exists():
        inputs += ["-ss", f"{t_in}", "-i", str(src)]
    else:
        inputs += ["-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:d={dur}:r={FPS}"]
    if overlay:
        inputs += ["-loop", "1", "-i", str(overlay)]

    base_vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"
    if crop:
        base_vf = f"crop={crop},scale={W}:{H}"
    if move == "push3":
        # 3% slow push-in over the clip duration
        base_vf += f",zoompan=z='1+0.03*on/{n_frames}':d=1:s={W}x{H}:fps={FPS}"
    elif move == "pushken4":
        base_vf += f",zoompan=z='1+0.04*on/{n_frames}':d=1:s={W}x{H}:fps={FPS}"
    elif move == "pullout8":
        base_vf += f",zoompan=z='1.08-0.08*on/{n_frames}':d=1:s={W}x{H}:fps={FPS}"
    elif move == "shake":
        # micro-shake via crop with sin-based offset
        base_vf = (
            f"scale={W+40}:{H+40}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H}:'(in_w-{W})/2+5*sin(2*PI*t)':'(in_h-{H})/2+5*cos(2*PI*t)'"
        )

    if overlay:
        filt = f"[0:v]{base_vf}[base];[base][1:v]overlay=0:0[outv]"
        cmd = [FFMPEG, "-y", *inputs,
               "-filter_complex", filt, "-map", "[outv]",
               "-frames:v", str(n_frames), "-r", str(FPS),
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
               "-pix_fmt", "yuv420p", "-an", str(out)]
    else:
        cmd = [FFMPEG, "-y", *inputs,
               "-vf", base_vf,
               "-frames:v", str(n_frames), "-r", str(FPS),
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
               "-pix_fmt", "yuv420p", "-an", str(out)]
    run(cmd)


def main() -> None:
    print("==> rendering credential / lower-third / corner-mark PNGs")
    p_corner = WORK / "ovr_corner.png"
    make_corner_mark("PRISM 42 · BUILT WITH OPUS 4.7", p_corner)

    p_kinetic = WORK / "ovr_kinetic.png"
    make_kinetic_label("PRISM 42", accent=True, out_path=p_kinetic)

    p_lt = WORK / "ovr_lt.png"
    make_lower_third("DR. BRANDON DENT", "physician · AI researcher", p_lt)

    p_emt = WORK / "ovr_emt.png"
    make_credential_stamp("EMT", p_emt)

    p_med = WORK / "ovr_med.png"
    make_credential_stamp("MEDICAL SCHOOL", p_med)

    p_trauma = WORK / "ovr_trauma.png"
    make_credential_stamp("TRAUMA RESIDENCY", p_trauma)

    p_assistant = WORK / "ovr_assistant.png"
    make_credential_stamp("ASSISTANT PROFESSOR · 6.5 YEARS", p_assistant, two_line=True)

    p_ai = WORK / "ovr_ai.png"
    make_credential_stamp("AI RESEARCH", p_ai)

    # Slates for B-roll placeholders (Runway gens go here later)
    p_slate_emt = WORK / "slate_emt.png"
    make_slate("[ B-ROLL · ambulance bay · Veo 3.1 placeholder ]", p_slate_emt)
    p_slate_med = WORK / "slate_med.png"
    make_slate("[ B-ROLL · medical text · Gen-4.5 placeholder ]", p_slate_med)
    p_slate_trauma = WORK / "slate_trauma.png"
    make_slate("[ B-ROLL · trauma corridor · Veo 3.1 placeholder ]", p_slate_trauma)
    p_slate_archival = WORK / "slate_archival.png"
    make_slate("[ archival still · Brandon Dent, MD ]", p_slate_archival)

    # 12-shot table per viral-hooks DROP-IN
    shots = [
        # 1. ECU Ken mouth+eyes, 3/4 — locked, kinetic PRISM 42 caption
        Shot(1, 0.0, 1.4, "01_ken_ecu", KEN, 0.5,
             crop="iw*0.5:ih*0.6:iw*0.30:ih*0.18", overlay_png=p_kinetic),
        # 2. MS Ken at desk, 3% push-in, lower-third
        Shot(2, 1.4, 3.6, "02_ken_ms_lt", KEN, 1.5, move="push3", overlay_png=p_lt),
        # 3. B-roll EMT (slate placeholder)
        Shot(3, 3.6, 5.2, "03_emt_slate", p_slate_emt, 0.0, overlay_png=p_emt),
        # 4. Archival still (slate placeholder, Ken-Burns push)
        Shot(4, 5.2, 7.4, "04_archival_slate", p_slate_archival, 0.0, move="pushken4"),
        # 5. B-roll medical (slate)
        Shot(5, 7.4, 9.6, "05_med_slate", p_slate_med, 0.0, overlay_png=p_med),
        # 6. OTS Ken (different reframe, hides lip-sync)
        Shot(6, 9.6, 12.2, "06_ken_ots", KEN, 4.0,
             crop="iw*0.7:ih*0.85:iw*0.25:ih*0.10", overlay_png=p_trauma),
        # 7. Trauma corridor (slate)
        Shot(7, 12.2, 14.8, "07_trauma_slate", p_slate_trauma, 0.0),
        # 8. MCU Ken 3/4 — locked
        Shot(8, 14.8, 17.2, "08_ken_mcu", KEN, 6.0,
             crop="iw*0.65:ih*0.75:iw*0.20:ih*0.15"),
        # 9. CU Ken — eye-line off-lens, ASSISTANT PROFESSOR stamp
        Shot(9, 17.2, 19.9, "09_ken_cu", KEN, 8.0,
             crop="iw*0.45:ih*0.55:iw*0.32:ih*0.22", overlay_png=p_assistant),
        # 10. Hard cut to Fizzlepuff MS — single 0.9s yell
        Shot(10, 19.9, 20.8, "10_fizz", FIZZ, 1.5),
        # 11. Match-cut back to Ken (mock-startled) — micro-zoom
        Shot(11, 20.8, 23.4, "11_ken_react", KEN, 9.5,
             crop="iw*0.55:ih*0.65:iw*0.28:ih*0.18", move="push3"),
        # 12. Pull-out wide (slate placeholder for Runway gen)
        Shot(12, 23.4, 28.8, "12_wide_pullout", KEN, 2.0,
             crop="iw*0.95:ih*0.95:iw*0.025:ih*0.025", move="pullout8",
             overlay_png=p_corner),
    ]

    print(f"==> rendering {len(shots)} sub-clips (no audio)")
    sub_paths: list[Path] = []
    for s in shots:
        out = WORK / f"sub_{s.label}.mp4"
        sub_paths.append(out)
        cut_clip(s.source, s.src_in, s.t_out - s.t_in, out,
                 crop=s.crop, move=s.move, overlay=s.overlay_png)
        print(f"  {s.idx:2}  {s.t_in:5.1f}-{s.t_out:5.1f}s  {s.label} OK")

    # AI stamp comes later — overlay onto end of shot 12 in a separate pass
    print("==> shot 12 second overlay: AI RESEARCH stamp")
    out12 = WORK / "sub_12_ai_overlay.mp4"
    # overlay AI stamp from t=0.6s of the shot until end
    cmd = [FFMPEG, "-y", "-i", str(WORK / "sub_12_wide_pullout.mp4"),
           "-loop", "1", "-i", str(p_ai),
           "-filter_complex", "[0:v][1:v]overlay=0:0:enable='gte(t,0.6)'",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
           "-pix_fmt", "yuv420p", "-an", str(out12)]
    run(cmd)
    sub_paths[-1] = out12

    # Concat
    print("==> concat")
    concat_txt = WORK / "concat.txt"
    concat_txt.write_text("\n".join(f"file '{p.resolve()}'" for p in sub_paths))
    visual = WORK / "bio_visual.mp4"
    run([FFMPEG, "-y", "-f", "concat", "-safe", "0",
         "-i", str(concat_txt), "-c", "copy", str(visual)])

    # Mux with VO
    print("==> mux with bio-intro-mix.mp3")
    out_master = FINAL / "bio-intro-v1.mp4"
    run([FFMPEG, "-y", "-i", str(visual), "-i", str(VO_MIX),
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
         "-map", "0:v", "-map", "1:a", "-shortest", str(out_master)])

    # Probe final
    r = subprocess.run([FFMPEG.replace("ffmpeg", "ffprobe"), "-v", "error",
                        "-show_entries", "format=duration,size", "-of", "default=noprint_wrappers=1",
                        str(out_master)], capture_output=True, text=True)
    print(f"==> done -> {out_master}")
    print(r.stdout)


if __name__ == "__main__":
    main()
